"""Run the model on data/ and write site/data.json for the dashboard."""
import json, pathlib, datetime as dt
import numpy as np, pandas as pd
import model as M

ROOT = pathlib.Path(__file__).resolve().parents[1]
DATA, SITE = ROOT / 'data', ROOT / 'site'
START = pd.Timestamp('1987-01-02')          # first day of the backtest (needs 200d MA and 10y medians)
DAILY_YEARS = 3                             # full daily detail for recent years, Fridays before that
FX_MA = 120
MACRO = {'sahm': 'SAHMREALTIME', 'unrate': 'UNRATE', 'nfci': 'NFCI', 'claims': 'ICSA', 'real10': 'DFII10'}


def rnd(a, n):
    return [None if (x is None or not np.isfinite(x)) else round(float(x), n) for x in np.asarray(a, float)]


def ds(ts):
    return [t.strftime('%Y-%m-%d') for t in ts]


def main():
    daily = pd.read_csv(DATA / 'daily.csv', parse_dates=['date'])
    fred = {p.stem: pd.read_csv(p, parse_dates=['date']).set_index('date')['value'] for p in (DATA / 'fred').glob('*.csv')}
    d = M.prepare(daily)
    res = M.run(d, **M.REC)
    z_hy, z_sl, dep = M.depth(d, res)
    F = M.features(d, res, fred)
    P = M.regime_probs(F, pd.Series(res.regime.values, index=res.date), start='1980-01-01')

    m = (res.date >= START).values
    r, c, dates = res.ret[m].values, res.cash[m].values, res.date[m].reset_index(drop=True)
    b6040 = (0.6 * d.r_spx + 0.4 * d.r_ty_tr)[m].values
    bspx = d.r_spx[m].values + c                 # futures return + cash = S&P total return proxy
    eq = {'strat': np.cumprod(1 + r), 'b6040': np.cumprod(1 + b6040), 'spx': np.cumprod(1 + bspx)}
    rets = {'strat': r, 'b6040': b6040, 'spx': bspx}

    # ---- stats per look-back window
    last = dates.iloc[-1]
    windows = {'1M': last - pd.DateOffset(months=1), '3M': last - pd.DateOffset(months=3),
               'YTD': pd.Timestamp(last.year - 1, 12, 31), '1Y': last - pd.DateOffset(years=1),
               '3Y': last - pd.DateOffset(years=3), '5Y': last - pd.DateOffset(years=5),
               '10Y': last - pd.DateOffset(years=10), 'Max': dates.iloc[0] - pd.Timedelta(days=1)}
    stats = {}
    for k, t0 in windows.items():
        w = (dates > t0).values
        stats[k] = {'from': dates[w].iloc[0].strftime('%Y-%m-%d')}
        for nm, rr in rets.items():
            s = M.stats(rr[w], c[w], dates[w])
            stats[k][nm] = {a: (None if v is None else round(float(v), 4)) for a, v in s.items()}
        stats[k]['strat']['reb_per_yr'] = round(float(res.reb[m].values[w].sum() / max((dates[w].iloc[-1] - dates[w].iloc[0]).days / 365.25, 1e-9)), 1)

    # ---- chart series: daily for recent years, Fridays before
    full = res[m].reset_index(drop=True)
    dd = d[m].reset_index(drop=True)
    keep = ((dates >= last - pd.DateOffset(years=DAILY_YEARS)) | (dates.dt.day_of_week == 4)).to_numpy(copy=True)
    keep[-1] = True
    k = np.where(keep)[0]
    ma = lambda s, n: s.rolling(n).mean()
    reg_code = pd.Categorical(full.regime, categories=M.REGS).codes
    series = {
        't': ds(dates[k]),
        'strat': rnd(eq['strat'][k], 5), 'b6040': rnd(eq['b6040'][k], 5), 'spx_bh': rnd(eq['spx'][k], 5),
        'dd': rnd((eq['strat'] / np.maximum.accumulate(eq['strat']) - 1)[k], 4),
        'regime': [int(x) for x in reg_code[k]],
        'hy': rnd(dd.hy[k], 3), 'hy_med': rnd(full.hy_thr[k], 3),
        'slope': rnd(dd.slope[k], 3), 'sl_med': rnd(full.sl_thr[k], 3),
        'z_hy': rnd(z_hy[m][k], 3), 'z_sl': rnd(z_sl[m][k], 3),
    }
    assets = [('spx', 'S&P 500', d.spx, 200), ('ty', '10Y Treasury TR', d.ty_tr_idx * 100, 200),
              ('gold', 'Gold', d.gold, 200), ('jpy', 'JPY/USD', d.jpy, FX_MA),
              ('chf', 'CHF/USD', d.chf, FX_MA), ('aud', 'USD/AUD', d.aud, FX_MA)]
    asset_meta = []
    for key, name, px, n in assets:
        mv = ma(px, n)
        series[key] = rnd(px[m].values[k], 5)
        series[key + '_ma'] = rnd(mv[m].values[k], 5)
        p_last, ma_last = float(px.iloc[-1]), float(mv.iloc[-1])
        meta = {'key': key, 'name': name, 'ma_len': n, 'price': round(p_last, 5), 'ma': round(ma_last, 5),
                'dist': round(p_last / ma_last - 1, 4), 'above': bool(p_last > ma_last), 'in_rules': n == 200}
        if key in ('spx', 'ty', 'gold'):
            meta['confirmed_up'] = bool(res['up_' + ('ty' if key == 'ty' else key)].iloc[-1])
        asset_meta.append(meta)

    # ---- weekly: probabilities and macro indicators
    Pw = P[P.index >= START - pd.DateOffset(years=1)].dropna()
    weekly = {'t': ds(Pw.index), 'G': rnd(Pw.Growth, 3), 'I': rnd(Pw.Inflation, 3), 'S': rnd(Pw.Slowdown, 3)}
    macro = {}
    for key, sid in MACRO.items():
        s = fred.get(sid)
        if s is None:
            continue
        if sid == 'ICSA':
            s = s.rolling(4).mean() / 1000                   # 4-week average, thousands
        s = s[s.index >= START]
        if sid in ('DFII10',):
            s = s.resample('W-FRI').last().dropna()
        macro[key] = {'t': ds(s.index), 'v': rnd(s.values, 3), 'last': ds(s.index[-1:])[0]}

    # ---- regime spans, annual returns, by-regime returns, recent allocation changes
    spans, cur, s0 = [], full.regime.iloc[0], dates.iloc[0]
    for i in range(1, len(full)):
        if full.regime.iloc[i] != cur:
            spans.append({'r': cur, 'a': s0.strftime('%Y-%m-%d'), 'b': dates.iloc[i].strftime('%Y-%m-%d')})
            cur, s0 = full.regime.iloc[i], dates.iloc[i]
    spans.append({'r': cur, 'a': s0.strftime('%Y-%m-%d'), 'b': last.strftime('%Y-%m-%d')})
    yr = dates.dt.year.values
    annual = [{'y': int(y), **{nm: round(float(np.prod(1 + rr[yr == y]) - 1), 4) for nm, rr in rets.items()}}
              for y in np.unique(yr)]
    held = np.concatenate([full.regime.values[:1], full.regime.values[:-1]])
    by_regime = []
    for rg in M.REGS:
        w = held == rg
        by_regime.append({'r': rg, 'share': round(float(w.mean()), 3),
                          'ann': round(float(np.prod(1 + r[w]) ** (261 / max(w.sum(), 1)) - 1), 4),
                          'ann_6040': round(float(np.prod(1 + b6040[w]) ** (261 / max(w.sum(), 1)) - 1), 4)})
    tw = full[['tw_spx', 'tw_ty', 'tw_gold', 'tw_cash']].round(4)
    chg = np.where((tw.diff().abs().sum(axis=1) > 1e-9).values)[0]
    changes = [{'d': dates.iloc[i].strftime('%Y-%m-%d'), 'r': full.regime.iloc[i],
                'w': [float(x) for x in tw.iloc[i]]} for i in chg[-8:][::-1]]

    # ---- pulse
    L = full.iloc[-1]
    since = spans[-1]['a']
    pending = None
    if L.raw != L.regime:                      # raw regime differs: count days towards the 5-day confirmation
        n = 0
        for x in full.raw.values[::-1]:
            if x != L.raw:
                break
            n += 1
        pending = {'regime': L.raw, 'days': n, 'needed': M.REC['regime_confirm']}
    pl = P.dropna().iloc[-1]
    blend = np.array([M.BASE_ALLOC[g] for g in M.REGS]).T @ pl.values
    pulse = {
        'asof': last.strftime('%Y-%m-%d'), 'regime': L.regime, 'since': since, 'pending': pending,
        'hy': round(float(dd.hy.iloc[-1]), 3), 'hy_med': round(float(L.hy_thr), 3),
        'slope': round(float(dd.slope.iloc[-1]), 3), 'sl_med': round(float(L.sl_thr), 3),
        'z_hy': round(float(z_hy[-1]), 2), 'z_sl': round(float(z_sl[-1]), 2), 'depth': round(float(dep[-1]), 2),
        'probs': {'date': pl.name.strftime('%Y-%m-%d'), **{g: round(float(pl[g]), 3) for g in M.REGS}},
        'blend': [round(float(x), 3) for x in blend],
        'target': [float(L.tw_spx), float(L.tw_ty), float(L.tw_gold), float(L.tw_cash)],
        'tbill': round(float(d.tbill.iloc[-1]), 2), 'rebalance_today': bool(changes and changes[0]['d'] == last.strftime('%Y-%m-%d')),
        'last_change': changes[0]['d'] if changes else None,
    }
    out = {'generated': dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%dT%H:%MZ'),
           'pulse': pulse, 'assets': asset_meta, 'stats': stats, 'series': series, 'weekly': weekly,
           'macro': macro, 'spans': spans, 'annual': annual, 'by_regime': by_regime, 'changes': changes}
    SITE.mkdir(exist_ok=True)
    (SITE / 'data.json').write_text(json.dumps(out, separators=(',', ':')))
    print('data.json', round((SITE / 'data.json').stat().st_size / 1024), 'KB; as of', pulse['asof'], pulse['regime'])


if __name__ == '__main__':
    main()
