"""Daily execution checklist: what changed at the last close and what to do about it.

Each row: check, yes (bool, None for the manual reminder), detail, attention (highlight: Y rows, or stale data).
"""
import numpy as np, pandas as pd
from pandas.tseries.holiday import USFederalHolidayCalendar
import model as M

NAMES = {'spx': 'S&P', 'r2k': 'Russell', 'ty': '10Y', 'gold': 'Gold', 'wti': 'WTI', 'cash': 'Cash'}
# contract multipliers for the sizing helper (price x multiplier = notional per contract)
CONTRACTS = {'spx': ('MES', 5), 'r2k': ('M2K', 5), 'gold': ('MGC', 10), 'wti': ('MCL', 100), 'ty': ('ZN', 1000)}


def zn_price(y10_pct):
    """Rough 10Y note futures price: a 6% coupon 10-year bond priced at the 10Y yield (ZN's notional coupon)."""
    y = y10_pct / 100 / 2
    return 3 * (1 - (1 + y) ** -20) / y + 100 * (1 + y) ** -20


def pct(x):
    return f'{x:.0%}'


def build(d, res, fred, asof):
    L, P = res.iloc[-1], res.iloc[-2]
    rows = []

    # 1. data current: prices moved on the last trading day; FRED no older than the prior trading day
    # FRED posts each day's value the next business day, and Treasury series skip US bond-market holidays,
    # so the newest value we can expect is from the bond-market business day before the last trading day
    bday = pd.offsets.CustomBusinessDay(calendar=USFederalHolidayCalendar())
    prev_day = res.date.iloc[-1] - bday
    stale = [NAMES[a] for a in ('spx', 'r2k', 'gold', 'wti') if d[a].iloc[-1] == d[a].iloc[-2]]
    for nm, sid in (('HY spread', 'BAMLH0A0HYM2'), ('10Y yield', 'DGS10'), ('T-bill', 'DTB3')):
        if sid in fred and fred[sid].index.max() < prev_day:
            stale.append(f"{nm} (FRED to {fred[sid].index.max():%d %b})")
    fred_lag = fred['BAMLH0A0HYM2'].index.max() < res.date.iloc[-1] if 'BAMLH0A0HYM2' in fred else False
    rows.append({'check': 'Data current', 'yes': not stale, 'attention': bool(stale),
                 'detail': ('Stale: ' + ', '.join(stale)) if stale else
                           ('All legs priced; FRED lags a day, as usual' if fred_lag else 'All legs priced')})

    # 2. regime change confirmed today
    chg = L.regime != P.regime
    rows.append({'check': 'Regime change confirmed (5-day rule)', 'yes': bool(chg), 'attention': bool(chg),
                 'detail': f'{P.regime} → {L.regime}, new targets from next session' if chg else ''})

    # 3. regime change pending
    pend = L.raw != L.regime
    n = 0
    if pend:
        for x in res.raw.values[::-1]:
            if x != L.raw:
                break
            n += 1
    rows.append({'check': 'Regime change pending', 'yes': bool(pend), 'attention': bool(pend),
                 'detail': f'{L.raw}, day {n} of {M.REC["regime_confirm"]}' if pend else ''})

    # 4 and 5. trend flags: confirmed today, and crossed but not yet confirmed
    legs = [(a, n_, f'{a}_up{n_}', d[a]) for a in ('spx', 'r2k') for n_ in M.SPX_MAS]
    legs += [('gold', 200, 'up_gold', d.gold), ('wti', 200, 'up_wti', d.wti), ('ty', 200, 'up_ty', d.ty_tr_idx)]
    flipped, pending = [], []
    for a, n_, col, px in legs:
        on_now, on_prev = bool(L[col]), bool(P[col])
        if on_now != on_prev:
            flipped.append(f"{NAMES[a]} {n_}d {'on' if on_now else 'off'}")
        ma = px.rolling(n_).mean()
        above = (px > ma).values
        if bool(above[-1]) != on_now:
            k = 0
            for x in above[::-1]:
                if bool(x) != bool(above[-1]):
                    break
                k += 1
            dist = px.iloc[-1] / ma.iloc[-1] - 1
            pending.append(f"{NAMES[a]} {n_}d {'on' if above[-1] else 'off'}: day {k} of {M.REC['ma_confirm']}, "
                           f"{dist:+.1%} from MA")
    rows.append({'check': 'Trend flag confirmed on/off', 'yes': bool(flipped), 'attention': bool(flipped),
                 'detail': ', '.join(flipped)})
    rows.append({'check': 'Trend flag pending', 'yes': bool(pending), 'attention': bool(pending), 'detail': '; '.join(pending)})

    # 6. volatility switch (S&P and Russell each have their own)
    spikes, changed = [], False
    for a in ('spx', 'r2k'):
        r = L[a + '_vol10'] / L[a + '_vol252']
        ch = bool(L[a + '_spike']) != bool(P[a + '_spike'])
        changed |= ch
        if L[a + '_spike'] or ch:
            spikes.append(f"{NAMES[a]} 10d/1y vol {r:.1f}x"
                          + (' (switched on today)' if ch and L[a + '_spike'] else ' (switched off today)' if ch else '')
                          + (', exposure halved' if L[a + '_spike'] else ''))
    any_spike = bool(L.spx_spike or L.r2k_spike)
    rows.append({'check': 'Volatility switch (10d vol > 2× 1y)', 'yes': any_spike or changed, 'attention': any_spike or changed,
                 'detail': '; '.join(spikes) if spikes else
                           f"S&P {L.spx_vol10 / L.spx_vol252:.1f}x, Russell {L.r2k_vol10 / L.r2k_vol252:.1f}x"})

    # 7. target weights changed (shown at the levered size, % of NAV)
    keys = M.LIVE_ASSETS + ['cash']
    lev = M.LEVERAGE
    new = np.array([L['tw_' + a] for a in keys]); old = np.array([P['tw_' + a] for a in keys])
    moved = [i for i in range(len(keys)) if abs(new[i] - old[i]) > 0.0005 and keys[i] != 'cash']
    detail = ', '.join(f"{NAMES[keys[i]]} {pct(old[i] * lev)} → {pct(new[i] * lev)}" for i in moved)
    rows.append({'check': f'Target weights changed (at {lev}x, % of NAV)', 'yes': bool(moved), 'attention': bool(moved),
                 'detail': detail})

    # 8. drift reminder, always shown
    rows.append({'check': 'Drift check (manual)', 'yes': None, 'attention': False,
                 'detail': 'Compare your positions with targets; trade a leg only if it is more than 5–10% of NAV off target.'})

    verdict = f'Trade at next session: {detail}' if moved else 'No action today'
    sizing = {a: {'code': c, 'notional': round(float((zn_price(d.dgs10.iloc[-1]) if a == 'ty' else d[a].iloc[-1]) * m), 2),
                  'w': round(float(L['tw_' + a]), 4)} for a, (c, m) in CONTRACTS.items()}
    return {'asof': asof, 'verdict': verdict, 'rows': rows, 'leverage': lev, 'sizing': sizing}
