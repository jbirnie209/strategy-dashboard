"""One-off: seed data/ from the strategy workbook (v4 layout).

Usage: python pipeline/seed.py path/to/Countercyclical_Investment_Strategy_Data_v4.xlsm
After this the nightly job (update.py) keeps data/ current on its own.
"""
import sys, pathlib, openpyxl, pandas as pd

ROOT = pathlib.Path(__file__).resolve().parents[1]
DATA = ROOT / 'data'
CONSO_COLS = {'date': 'date', 'HY Spread': 'hy', '10Yr Minus 1Yr': 'slope', '10Y Yield': 'dgs10',
              '3 Month T-Bill': 'tbill', 'S&P500': 'spx', 'Gold Fut': 'gold',
              'JPY/USD': 'jpy', 'CHF/USD': 'chf', 'USD/AUD': 'aud'}


def main(path):
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    rows = [list(r) for r in wb['Data - Conso'].iter_rows(values_only=True)]
    hdr = rows[2]
    df = pd.DataFrame([r for r in rows[3:] if r[1] is not None], columns=hdr)[list(CONSO_COLS)]
    df = df.rename(columns=CONSO_COLS)
    df['date'] = pd.to_datetime(df['date'])
    df['tbill'] = df['tbill'].astype(float) * 100          # store in percent, like FRED DTB3
    df = df.drop_duplicates('date').sort_values('date')
    (DATA / 'fred').mkdir(parents=True, exist_ok=True)
    df.to_csv(DATA / 'daily.csv', index=False, float_format='%.6g', date_format='%Y-%m-%d')
    print('daily.csv', len(df), df.date.min().date(), df.date.max().date())

    fr = [list(r) for r in wb['Data - FRED'].iter_rows(values_only=True)]
    ids = fr[0]
    for c in range(0, len(ids), 2):
        sid = ids[c]
        if not sid:
            continue
        pts = [(r[c], r[c + 1]) for r in fr[7:] if r[c] is not None and isinstance(r[c + 1], (int, float))]
        s = pd.DataFrame(pts, columns=['date', 'value'])
        s['date'] = pd.to_datetime(s['date'])
        s.to_csv(DATA / 'fred' / f'{sid}.csv', index=False, date_format='%Y-%m-%d')
        print(sid, len(s), s.date.min().date(), s.date.max().date())


if __name__ == '__main__':
    main(sys.argv[1])
