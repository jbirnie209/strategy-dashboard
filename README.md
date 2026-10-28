# Strategy Pulse

Phone-friendly dashboard for the countercyclical investment strategy: current regime, Mahalanobis regime
probabilities, regime depth, target allocation, historical performance and the indicator and asset charts.

**How it updates.** A GitHub Action (`.github/workflows/update.yml`) runs on weekdays after the US close and
again the next morning (when FRED publishes the prior day's yields and spreads). It:

1. `pipeline/update.py` pulls the latest FRED series (official API if the `FRED_API_KEY` secret is set,
   otherwise the public fredgraph CSV) and daily prices from Yahoo Finance (ES=F, GC=F, JPY=X, CHF=X, AUD=X),
   chain-linked onto the workbook history in `data/`.
2. `pipeline/build.py` runs the model (`pipeline/model.py`) and writes `site/data.json`.
3. Commits the new data and deploys `site/` to GitHub Pages.

Run it by hand from the Actions tab ("Update data and deploy" → Run workflow).

**Rules** (same as the optimisation study): regimes from HY spread and 10Y–1Y vs their 10-year Friday medians,
5-day regime confirmation; 200-day MA trend filters with 5-day confirmation; weight removed by a trend filter
moves to the 10Y if the 10Y is in trend, otherwise cash; 10Y leg = DGS10 total return; backtest from 1987.

**Re-seeding** from a new workbook version: `python pipeline/seed.py path/to/workbook.xlsm` (overwrites `data/`).

**Local preview:** `cd pipeline && python build.py && cd ../site && python -m http.server`.

Chart.js 4.4.1 and chartjs-adapter-date-fns 3.0.0 are vendored in `site/vendor` (MIT).

**Customise mode.** The sliders button (top right) or "Customise colours and layout" (bottom) opens a panel to change
colours, reorder/hide/resize cards and hide individual charts. Settings save in the browser on that device.
"Export settings" copies them as JSON; paste that into `site/layout.js` to make it the default for every device.
