"""Nightly: pull the latest FRED series and market prices and append them to data/.

FRED: official API when FRED_API_KEY is set, otherwise the public fredgraph CSV.
Prices: Yahoo Finance daily bars, chain-linked onto the workbook history so levels stay continuous.
A failed source is logged and skipped; the previous data stays in place.
"""
import os, io, sys, pathlib, datetime as dt
import numpy as np, pandas as pd, requests

ROOT = pathlib.Path(__file__).resolve().parents[1]
DATA = ROOT / 'data'
UA = {'User-Agent': 'Mozilla/5.0 (strategy-dashboard nightly update)'}
FRED_IDS = ['BAMLH0A0HYM2', 'DGS1', 'DGS10', 'DTB3', 'BAA10Y', 'DFII10',
            'SAHMREALTIME', 'UNRATE', 'NFCI', 'ICSA', 'CPIAUCSL']
# column -> (Yahoo symbol, transform from Yahoo quote to the workbook's convention)
PRICES = {'spx': ('ES=F', lambda x: x),            # S&P 500 e-mini front month
          'gold': ('GC=F', lambda x: x),           # COMEX gold front month
          'jpy': ('JPY=X', lambda x: 100 / x),     # USD per 100 JPY
          'chf': ('CHF=X', lambda x: 1 / x),       # USD per CHF
          'aud': ('AUD=X', lambda x: x)}           # AUD per USD
LOOKBACK_DAYS = 60
FFILL_LIMIT = 5


def fetch_fred(sid, start):
    key = os.environ.get('FRED_API_KEY')
    if key:
        r = requests.get('https://api.stlouisfed.org/fred/series/observations', timeout=30,
                         params=dict(series_id=sid, api_key=key, file_type='json', observation_start=start))
        r.raise_for_status()
        obs = r.json()['observations']
        s = pd.Series({o['date']: o['value'] for o in obs})
    else:
        r = requests.get('https://fred.stlouisfed.org/graph/fredgraph.csv', params=dict(id=sid, cosd=start),
                         headers=UA, timeout=30)
        r.raise_for_status()
        df = pd.read_csv(io.StringIO(r.text))
        s = pd.Series(df.iloc[:, 1].values, index=df.iloc[:, 0].values)
    s.index = pd.to_datetime(s.index)
    return pd.to_numeric(s.replace('.', np.nan), errors='coerce').dropna()


def fetch_yahoo(sym, days=LOOKBACK_DAYS):
    r = requests.get(f'https://query1.finance.yahoo.com/v8/finance/chart/{sym}',
                     params=dict(range=f'{days}d', interval='1d'), headers=UA, timeout=30)
    r.raise_for_status()
    res = r.json()['chart']['result'][0]
    off = res['meta'].get('gmtoffset', 0)
    dates = pd.to_datetime(np.array(res['timestamp']) + off, unit='s').normalize()
    close = res['indicators']['quote'][0]['close']
    s = pd.Series(close, index=dates, dtype=float).dropna()
    return s[~s.index.duplicated(keep='last')]


def update_fred():
    fred = {}
    for sid in FRED_IDS:
        path = DATA / 'fred' / f'{sid}.csv'
        old = pd.read_csv(path, parse_dates=['date']).set_index('date')['value'] if path.exists() else pd.Series(dtype=float)
        start = (old.index.max() - pd.Timedelta(days=LOOKBACK_DAYS)).strftime('%Y-%m-%d') if len(old) else '1960-01-01'
        try:
            new = fetch_fred(sid, start)
            merged = pd.concat([old[~old.index.isin(new.index)], new]).sort_index()
            merged.rename('value').rename_axis('date').reset_index().to_csv(path, index=False, date_format='%Y-%m-%d')
            print(f'FRED {sid}: {len(new)} obs from {start}, last {merged.index.max().date()}')
            old = merged
        except Exception as e:                       # keep going with what we have
            print(f'FRED {sid}: FAILED ({e})', file=sys.stderr)
        fred[sid] = old
    return fred


def update_daily(fred):
    path = DATA / 'daily.csv'
    daily = pd.read_csv(path, parse_dates=['date'])
    last = daily.date.max()
    quotes = {}
    for col, (sym, f) in PRICES.items():
        try:
            quotes[col] = f(fetch_yahoo(sym))
            print(f'Yahoo {sym}: last {quotes[col].index.max().date()}')
        except Exception as e:
            print(f'Yahoo {sym}: FAILED ({e})', file=sys.stderr)
    if 'spx' in quotes:                              # the S&P futures calendar drives new rows
        today = pd.Timestamp(dt.datetime.now(dt.timezone.utc).date())
        new_dates = quotes['spx'].index[(quotes['spx'].index > last) & (quotes['spx'].index <= today)]
        new_dates = new_dates[new_dates.weekday < 5]
        if len(new_dates):
            daily = pd.concat([daily, pd.DataFrame({'date': new_dates})], ignore_index=True)
    daily = daily.sort_values('date').reset_index(drop=True)
    new = daily.date > last
    for col, q in quotes.items():                   # chain-link: new level = last level x Yahoo return since then
        base = q[q.index <= last]
        if not len(base) or not new.any():
            continue
        factor = daily.loc[daily.date == last, col].iloc[0] / base.iloc[-1]
        daily.loc[new, col] = q.reindex(daily.date[new]).values * factor
        daily.loc[new, col] = daily[col].ffill()[new]
    # rates and spreads: recompute the recent tail from FRED (picks up late publications)
    tail = daily.date > last - pd.Timedelta(days=LOOKBACK_DAYS)
    idx = daily.date[tail]

    def asof(sid):
        s = fred.get(sid)
        if s is None or not len(s):
            return pd.Series(np.nan, index=idx)
        return s.reindex(s.index.union(idx)).ffill(limit=FFILL_LIMIT).reindex(idx)
    vals = {'hy': asof('BAMLH0A0HYM2'), 'dgs10': asof('DGS10'), 'tbill': asof('DTB3')}
    vals['slope'] = vals['dgs10'] - asof('DGS1')
    for col, v in vals.items():
        v = v.values
        cur = daily.loc[tail, col].values
        daily.loc[tail, col] = np.where(np.isfinite(v), v, cur)
        daily[col] = daily[col].where(daily.date <= last, daily[col].ffill())
    daily.to_csv(path, index=False, float_format='%.6g', date_format='%Y-%m-%d')
    print(f'daily.csv: {int(new.sum())} new rows, last {daily.date.max().date()}')


if __name__ == '__main__':
    update_daily(update_fred())
