"""Countercyclical strategy model: regimes, trend filters, backtest, Mahalanobis regime probabilities, regime depth.

Signals use data up to the close of day t; weights earn the return of day t+1.
Live rules: 200-day MA with 5-day confirmation, trend-filtered weight parked in 10Y (if the 10Y is itself in trend),
10Y leg = DGS10 total return.
"""
import numpy as np, pandas as pd

ASSETS = ['spx', 'ty', 'gold']
REGS = ['Growth', 'Inflation', 'Slowdown']
BASE_ALLOC = {'Growth': (0.8, 0.0, 0.2), 'Inflation': (0.6, 0.0, 0.4), 'Slowdown': (0.0, 1.0, 0.0)}
REC = dict(ma_len=200, ma_confirm=5, regime_confirm=5, trend_out='10y')
SPX_MAS = (50, 100, 200)        # live rule 'A + B': S&P exposure = share of these confirmed trends ...
VOL_SPIKE = (10, 252, 2.0)      # ... halved when 10d realised vol > 2 x 1y realised vol (same day)
LEVERAGE = 2.1                  # levered view: cash + 2.1 x (strategy - cash), matches S&P vol since 1987
PROB_COLS = ['hy_gap', 'slope_gap', 'slope_chg13', 'y1_chg26', 'sahm']   # best set from the Mahalanobis study
SAHM_LAG_DAYS = 40                                                      # Sahm/UNRATE released ~5 weeks after month start


def prepare(daily):
    """daily: date, hy, slope, dgs10 (%), tbill (%), spx, gold, ... -> engine frame with returns."""
    out = daily.copy().reset_index(drop=True)
    out['tbill'] = out['tbill'].ffill()
    out['dgs10'] = out['dgs10'].ffill()
    gap = out['date'].diff().dt.days.fillna(1).values
    out['r_cash'] = np.r_[0, out['tbill'].values[:-1] / 100 * gap[1:] / 365]   # prior day's T-bill rate
    for a in ['spx', 'gold']:
        out['r_' + a] = out[a].pct_change(fill_method=None).fillna(0)
    y = out['dgs10'].values / 100
    yp = np.r_[np.nan, y[:-1]]
    with np.errstate(invalid='ignore', divide='ignore'):
        dur = (1 - (1 + yp / 2) ** -20) / yp
        conv = 2 / yp ** 2 * (1 - (1 + yp / 2) ** -20) - 20 / (yp * (1 + yp / 2) ** 21)
    dy = y - yp
    out['r_ty_tr'] = np.nan_to_num(yp * gap / 365 - dur * dy + 0.5 * conv * dy ** 2)
    out['ty_tr_idx'] = np.cumprod(1 + out['r_ty_tr'])
    return out


def rolling_threshold(dates, x, years, q):
    """Quantile q of Friday values in (date - years, date], like the workbook's MEDIAN(FILTER(...))."""
    fri = (dates.dt.day_of_week == 4).values & np.isfinite(x.values)
    fd, fv = dates.values[fri], x.values[fri]
    starts = (dates - pd.DateOffset(years=years)).values
    hi = np.searchsorted(fd, dates.values, side='right')
    lo = np.searchsorted(fd, starts, side='right')
    res = np.full(len(dates), np.nan)
    for i in range(len(dates)):
        if hi[i] > lo[i]:
            res[i] = np.quantile(fv[lo[i]:hi[i]], q)
    return res


def rolling_std(dates, x, years=10):
    """Std of Friday values in (date - years, date], same window as the median thresholds."""
    fri = (dates.dt.day_of_week == 4).values & np.isfinite(x.values)
    fd, fv = dates.values[fri], x.values[fri]
    hi = np.searchsorted(fd, dates.values, side='right')
    lo = np.searchsorted(fd, (dates - pd.DateOffset(years=years)).values, side='right')
    c1 = np.r_[0, np.cumsum(fv)]; c2 = np.r_[0, np.cumsum(fv ** 2)]
    n = hi - lo
    with np.errstate(invalid='ignore', divide='ignore'):
        m = (c1[hi] - c1[lo]) / n
        v = (c2[hi] - c2[lo]) / n - m ** 2
    return np.sqrt(np.maximum(v, 0)) * np.sqrt(n / np.maximum(n - 1, 1))


def confirm(raw, n):
    """Switch state only after n consecutive days of a new raw value."""
    out = np.empty(len(raw), dtype=object)
    cur, run, last = raw[0], 0, None
    for i, v in enumerate(raw):
        run = run + 1 if v == last else 1
        last = v
        if v != cur and run >= n:
            cur = v
        out[i] = cur
    return out


def trend_flags(price, length, n_confirm):
    above = (price > price.rolling(length).mean()).values
    return confirm(above, n_confirm).astype(bool) if n_confirm > 1 else above


def run(d, ma_len=200, ma_confirm=5, regime_confirm=5, trend_out='10y', alloc=None):
    """Full-history backtest. Returns daily frame with regime, raw regime, thresholds, trend flags,
    target weights (decided at close t) and held weights (lagged one day), and portfolio return."""
    alloc = alloc or BASE_ALLOC
    hy_thr = rolling_threshold(d['date'], d['hy'], 10, 0.5)
    sl_thr = rolling_threshold(d['date'], d['slope'], 10, 0.5)
    raw = np.where(d['hy'].values > hy_thr, 'Growth', np.where(d['slope'].values < sl_thr, 'Inflation', 'Slowdown'))
    reg = confirm(raw, regime_confirm)
    up_s = trend_flags(d['spx'], ma_len, ma_confirm)
    up_t = trend_flags(d['ty_tr_idx'], ma_len, ma_confirm)
    up_g = trend_flags(d['gold'], ma_len, ma_confirm)
    A = np.array([alloc[r] for r in reg])
    ok = np.c_[up_s, up_t, up_g]
    W = A * ok
    out_w = (A * ~ok).sum(1)
    if trend_out == '10y':
        W[:, 1] += out_w * up_t
    Wl = np.r_[np.zeros((1, 3)), W[:-1]]
    R = np.c_[d['r_spx'], d['r_ty_tr'] - d['r_cash'], d['r_gold']]
    rc = d['r_cash'].values
    port = (Wl * R).sum(1) + rc * np.maximum(1 - Wl[:, [0, 2]].sum(1), 0)
    res = pd.DataFrame({'date': d['date'], 'ret': port, 'cash': rc, 'regime': reg, 'raw': raw,
                        'hy_thr': hy_thr, 'sl_thr': sl_thr, 'up_spx': up_s, 'up_ty': up_t, 'up_gold': up_g,
                        'reb': np.r_[False, np.any(np.diff(Wl, axis=0) != 0, axis=1)]})
    for i, a in enumerate(ASSETS):
        res['tw_' + a] = W[:, i]
        res['w_' + a] = Wl[:, i]
    res['tw_cash'] = 1 - W.sum(1)
    return res


def live(d, base, ma_confirm=5):
    """Live rule 'A + B' on the regimes of `base` (a run() result). Fractional S&P exposure; gold and 10Y keep the
    200d confirmed flag. Removed S&P/gold weight parks in the 10Y if its flag is on, else cash. Same maths as
    the leverage study's custom.run."""
    fl = {n: trend_flags(d['spx'], n, ma_confirm).astype(float) for n in SPX_MAS}
    trend = sum(fl.values()) / len(SPX_MAS)
    n_s, n_l, k = VOL_SPIKE
    v_s = d['r_spx'].rolling(n_s).std().values * np.sqrt(261)
    v_l = d['r_spx'].rolling(n_l).std().values * np.sqrt(261)
    spike = v_s > k * v_l
    e_spx = trend * np.where(spike, 0.5, 1)
    e_ty, e_gold = base['up_ty'].values.astype(float), base['up_gold'].values.astype(float)
    A = np.array([BASE_ALLOC[r] for r in base['regime']])
    W = A * np.c_[e_spx, e_ty, e_gold]
    W[:, 1] += (A.sum(1) - W.sum(1)) * e_ty
    Wl = np.r_[np.zeros((1, 3)), W[:-1]]
    rc = d['r_cash'].values
    R = np.c_[d['r_spx'], d['r_ty_tr'] - rc, d['r_gold']]
    res = base.copy()
    res['ret'] = (Wl * R).sum(1) + rc * np.maximum(1 - Wl[:, [0, 2]].sum(1), 0)
    res['reb'] = np.r_[False, np.any(np.abs(np.diff(Wl, axis=0)) > 1e-9, axis=1)]
    for i, a in enumerate(ASSETS):
        res['tw_' + a] = W[:, i]
        res['w_' + a] = Wl[:, i]
    res['tw_cash'] = 1 - W.sum(1)
    for n in SPX_MAS:
        res[f'spx_up{n}'] = fl[n].astype(bool)
    res['e_spx'], res['vol10'], res['vol252'], res['spike'] = e_spx, v_s, v_l, spike
    return res


def lever(ret, cash, x=LEVERAGE):
    return np.asarray(cash) + x * (np.asarray(ret) - np.asarray(cash))


def stats(ret, cash, dates):
    r, c = np.asarray(ret), np.asarray(cash)
    yrs = (dates.iloc[-1] - dates.iloc[0]).days / 365.25
    eq = np.cumprod(1 + r)
    ex = r - c
    out = dict(ret=eq[-1] - 1, cagr=eq[-1] ** (1 / yrs) - 1 if yrs >= 1 else None,
               vol=r.std() * np.sqrt(261), maxdd=(eq / np.maximum.accumulate(np.r_[1, eq])[1:] - 1).min())
    out['sharpe'] = ex.mean() * 261 / (ex.std() * np.sqrt(261)) if ex.std() > 0 else None
    return out


# ---------- Mahalanobis regime probabilities ----------

def features(d, res, fred):
    """Weekly (Friday) features, each using only data published by that Friday."""
    fri = d[d.date.dt.day_of_week == 4].copy()
    fri['hy_gap'] = (d.hy - res.hy_thr)[fri.index]
    fri['slope_gap'] = (d.slope - res.sl_thr)[fri.index]
    fri['slope_chg13'] = fri.slope.diff(13)
    dgs1 = fred['DGS1'].reindex(fri.date, method='ffill')
    fri['y1_chg26'] = dgs1.diff(26).values
    sahm = fred['SAHMREALTIME'].copy()
    sahm.index = sahm.index + pd.Timedelta(days=SAHM_LAG_DAYS)
    fri['sahm'] = sahm.reindex(fri.date, method='ffill').values
    return fri.set_index('date')


def regime_probs(F, labels, cols=PROB_COLS, min_obs=104, shrink=0.1, start=None):
    """Gaussian (QDA) likelihood of each regime, means/covariances fitted on earlier Fridays only."""
    X = F[cols].values
    lab = labels.reindex(F.index).values
    P = np.full((len(F), 3), np.nan)
    t0 = 0 if start is None else np.searchsorted(F.index.values, np.datetime64(start))
    for t in range(t0, len(F)):
        past = np.isfinite(X[:t]).all(1) & pd.notna(lab[:t])
        if past.sum() < min_obs or not np.isfinite(X[t]).all():
            continue
        Xp, Lp = X[:t][past], lab[:t][past]
        ll = np.full(3, -np.inf)
        for k, r in enumerate(REGS):
            Xk = Xp[Lp == r]
            if len(Xk) < 20:
                continue
            S = np.atleast_2d(np.cov(Xk.T))
            S = (1 - shrink) * S + shrink * np.diag(np.diag(S))
            dx = X[t] - Xk.mean(0)
            ll[k] = -0.5 * dx @ np.linalg.solve(S, dx) - 0.5 * np.linalg.slogdet(S)[1] + np.log(len(Xk) / len(Xp))
        if np.isfinite(ll).any():
            e = np.exp(ll - ll[np.isfinite(ll)].max())
            P[t] = e / e.sum()
    return pd.DataFrame(P, index=F.index, columns=REGS)


def depth(d, res):
    """How far HY spread and slope sit from their 10y medians, in 10y standard deviations."""
    with np.errstate(invalid='ignore', divide='ignore'):
        z_hy = (d.hy.values - res.hy_thr.values) / rolling_std(d.date, d.hy)
        z_sl = (d.slope.values - res.sl_thr.values) / rolling_std(d.date, d.slope)
    reg = res.regime.values
    dep = np.where(reg == 'Growth', z_hy, np.where(reg == 'Slowdown', z_sl, np.minimum(-z_hy, -z_sl)))
    return z_hy, z_sl, dep
