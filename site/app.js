// Strategy Pulse: renders data.json (built nightly by pipeline/build.py).
const REGS = ["Growth", "Inflation", "Slowdown"];
const css = name => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
const C = {};
function readColors() {
  Object.assign(C, {
  text: css("--text"), muted: css("--muted"), faint: css("--faint"), border: css("--border"),
  card: css("--card"), neg: css("--neg"), grid: css("--grid"), band: parseFloat(css("--band")) || 0.2,
  probfill: parseFloat(css("--probfill")) || 0.5,
  reg: [css("--growth"), css("--inflation"), css("--slowdown")],
  assets: [css("--a-spx"), css("--a-ty"), css("--a-gold"), css("--a-cash")]
  });
  Chart.defaults.color = C.muted;
  Chart.defaults.borderColor = C.border;
}
readColors();
const ASSET_NAMES = ["S&P 500", "10Y Treasury", "Gold", "Cash"];
const PERF_RANGES = ["1M", "3M", "YTD", "1Y", "3Y", "5Y", "10Y", "Max"];
const IND_RANGES = ["1Y", "3Y", "5Y", "10Y", "Max"];
const MACRO = {
  sahm: { name: "Sahm rule (real-time)", unit: "pp", ref: 0.5 },
  unrate: { name: "Unemployment rate", unit: "%" },
  nfci: { name: "Chicago Fed NFCI", unit: "", ref: 0 },
  claims: { name: "Initial claims, 4-wk avg", unit: "k" },
  real10: { name: "10Y real yield (TIPS)", unit: "%", ref: 0 }
};

const $ = id => document.getElementById(id);
const alpha = (hex, a) => { const n = parseInt(hex.slice(1), 16); return `rgba(${n >> 16},${(n >> 8) & 255},${n & 255},${a})`; };
const pct = (x, d = 1) => x == null ? "—" : (x * 100).toFixed(d).replace("-", "−") + "%";
const signed = (x, d = 2) => x == null ? "—" : (x >= 0 ? "+" : "−") + Math.abs(x).toFixed(d);
const fmtDate = s => new Date(s + "T00:00:00Z").toLocaleDateString("en-AU", { day: "numeric", month: "short", year: "numeric", timeZone: "UTC" });
const el = (tag, attrs = {}, ...kids) => {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") e.className = v; else if (k === "style") e.style.cssText = v; else e.setAttribute(k, v);
  }
  for (const k of kids) e.append(k);
  return e;
};

let D = null;
const charts = {};
const state = { perf: "1Y", ind: "1Y", asset: "1Y", risk: "1Y", lev: "1x", macro: null, openAsset: null };
const levKey = () => state.lev === "1x" ? "strat" : "lev";

Chart.defaults.font.family = "Inter, system-ui, sans-serif";
Chart.defaults.font.size = 11;
Chart.defaults.animation = false;

// ---------- time windows ----------
function startFor(range, lastStr) {
  const last = new Date(lastStr + "T00:00:00Z");
  const d = new Date(last);
  const m = { "1M": [0, 1], "3M": [0, 3], "1Y": [1, 0], "3Y": [3, 0], "5Y": [5, 0], "10Y": [10, 0] }[range];
  if (range === "Max") return null;
  if (range === "YTD") return `${last.getUTCFullYear() - 1}-12-31`;
  d.setUTCFullYear(d.getUTCFullYear() - m[0]);
  d.setUTCMonth(d.getUTCMonth() - m[1]);
  return d.toISOString().slice(0, 10);
}
function firstIndex(t, start) {           // first index with t[i] > start (t sorted YYYY-MM-DD)
  if (!start) return 0;
  let lo = 0, hi = t.length;
  while (lo < hi) { const mid = (lo + hi) >> 1; if (t[mid] <= start) lo = mid + 1; else hi = mid; }
  return Math.max(0, Math.min(lo, t.length - 1));
}
const pts = (t, v) => t.map((x, i) => ({ x, y: v[i] }));

// ---------- regime band plugin ----------
const regimeBands = {
  id: "regimeBands",
  beforeDatasetsDraw(chart, args, opts) {
    if (!opts || !opts.on) return;
    const { ctx, chartArea: a, scales: { x } } = chart;
    ctx.save();
    ctx.globalAlpha = opts.alpha || C.band;
    for (const s of D.spans) {
      const x0 = Math.max(x.getPixelForValue(Date.parse(s.a)), a.left);
      const x1 = Math.min(x.getPixelForValue(Date.parse(s.b)), a.right);
      if (x1 <= a.left || x0 >= a.right || x1 <= x0) continue;
      ctx.fillStyle = C.reg[REGS.indexOf(s.r)];
      ctx.fillRect(x0, a.top, x1 - x0, a.bottom - a.top);
    }
    ctx.restore();
  }
};
Chart.register(regimeBands);

function baseOpts({ log = false, bands = true, yfmt = v => v, stacked = false, ymin, ymax } = {}) {
  return {
    responsive: true, maintainAspectRatio: false, parsing: true, normalized: true,
    interaction: { mode: "index", intersect: false },
    elements: { point: { radius: 0, hitRadius: 6 }, line: { borderWidth: 1.5, tension: 0 } },
    plugins: {
      legend: { display: false },
      regimeBands: { on: bands },
      tooltip: {
        backgroundColor: C.card, borderColor: C.border, borderWidth: 1, titleColor: C.text, bodyColor: C.text,
        callbacks: { label: c => `${c.dataset.label}: ${c.parsed.y == null ? "—" : yfmt(c.parsed.y)}` }
      }
    },
    scales: {
      x: { type: "time", time: { tooltipFormat: "d MMM yyyy" }, grid: { color: C.grid }, ticks: { maxTicksLimit: 5, maxRotation: 0 } },
      y: { type: log ? "logarithmic" : "linear", stacked, min: ymin, max: ymax, grid: { color: C.grid },
           ticks: { maxTicksLimit: 5, callback: v => yfmt(v) } }
    }
  };
}
function draw(id, config) {
  if (charts[id]) charts[id].destroy();
  charts[id] = new Chart($(id), config);
}
const line = (label, data, color, extra = {}) => ({ label, data, borderColor: color, backgroundColor: color, fill: false, ...extra });

// ---------- pulse ----------
function renderPulse() {
  const p = D.pulse;
  $("stamp").textContent = `Data to ${fmtDate(p.asof)} · built ${D.generated.replace("T", " ").replace("Z", " UTC")}`;
  const ri = REGS.indexOf(p.regime);
  $("regimeName").textContent = p.regime;
  $("regimeName").style.color = C.reg[ri];
  $("regimeSince").textContent = `confirmed · since ${fmtDate(p.since)}`;
  if (p.pending) {
    $("pending").hidden = false;
    $("pending").textContent = `Raw signal reads ${p.pending.regime}: day ${p.pending.days} of ${p.pending.needed} needed to confirm a switch.`;
  }
  $("hyVal").textContent = p.hy.toFixed(2) + "%";
  $("hyCmp").textContent = `${p.hy > p.hy_med ? "above" : "below"} ${p.hy_med.toFixed(2)}% median`;
  $("slVal").textContent = p.slope.toFixed(2);
  $("slCmp").textContent = `${p.slope < p.sl_med ? "below" : "above"} ${p.sl_med.toFixed(2)} median`;

  const bar = $("probBar"), leg = $("probLegend");
  bar.replaceChildren(); leg.replaceChildren();
  REGS.forEach((r, i) => {
    const v = p.probs[r];
    bar.append(el("div", { style: `flex:${Math.max(v, 0.001)};background:${C.reg[i]}`, title: `${r} ${pct(v, 0)}` }));
    leg.append(el("span", {}, el("i", { class: "sw", style: `background:${C.reg[i]}` }), `${r} `, el("span", { class: "num" }, pct(v, 0))));
  });
  $("probDate").textContent = `Mahalanobis · week of ${fmtDate(p.probs.date)}`;

  const depthWord = Math.abs(p.depth) < 0.5 ? "shallow" : Math.abs(p.depth) < 1 ? "moderate" : "deep";
  const zName = p.regime === "Growth" ? "HY z" : p.regime === "Slowdown" ? "slope z" : "inside both, z";
  $("depthTxt").textContent = `${zName} ${signed(p.depth)} · ${depthWord}`;
  $("gDot").style.left = `${50 + Math.max(-2, Math.min(2, p.depth)) * 25}%`;
  $("gDot").style.background = C.reg[ri];
  $("gauge").style.setProperty("--gauge", C.reg[ri]);
  $("depthHelp").textContent = {
    Growth: "Growth has paid best when shallow (HY z below 0.5); very deep Growth has meant crisis.",
    Inflation: "Depth in Inflation has not mattered much historically.",
    Slowdown: "Deep Slowdown (slope z above 0.5) has paid best for the 10Y; shallow Slowdown has been close to cash."
  }[p.regime];

  // allocation
  const ab = $("allocBar"), rows = $("allocRows");
  ab.replaceChildren(); rows.replaceChildren();
  const trend = {};
  for (const a of D.assets) trend[a.key] = a;
  const keys = ["spx", "ty", "gold", null];
  p.target.forEach((w, i) => {
    if (w > 0) ab.append(el("div", { style: `flex:${w};background:${C.assets[i]}` }));
    const k = keys[i];
    const tr = k ? trend[k] : null;
    const rk = p.risk, nUp = Object.values(rk.trend).filter(Boolean).length;
    const note = k === "spx" ? `${nUp}/3 trends${rk.spike ? " · vol spike, halved" : ""} · keep ${pct(rk.e_spx, 0)}`
      : tr ? (tr.confirmed_up ? "↑ in trend (200d)" : "↓ below trend (200d)") : `T-bill ${p.tbill.toFixed(2)}%`;
    rows.append(el("div", { class: "allocRow" },
      el("span", {}, el("i", { class: "dot", style: `background:${C.assets[i]}` }), ASSET_NAMES[i]),
      el("span", { class: "muted xs" }, note),
      el("span", { class: "num" }, pct(w, 0))));
  });
  const L = p.risk.leverage, g = p.target.slice(0, 3).map(w => w * L);
  rows.append(el("div", { class: "muted xs" }, g.some(x => x > 0)
    ? `At ${L}x: ${g.map((w, i) => w > 0 ? `${ASSET_NAMES[i].replace(" Treasury", "")} ${pct(w, 0)}` : null).filter(Boolean).join(" · ")} of capital, funded at the T-bill rate`
    : `At ${L}x: nothing to lever while the allocation is all cash`));
  $("rebTxt").textContent = p.rebalance_today ? "rebalance today" : `last change ${fmtDate(p.last_change)}`;
  $("blendTxt").textContent = `S&P ${pct(p.blend[0], 0)} · 10Y ${pct(p.blend[1], 0)} · Gold ${pct(p.blend[2], 0)}`;
  const ch = $("changes");
  ch.replaceChildren(el("div", { class: "lbl" }, "Recent allocation changes"));
  for (const c of D.changes) {
    const parts = c.w.map((w, i) => w > 0 ? `${ASSET_NAMES[i].replace(" Treasury", "")} ${pct(w, 0)}` : null).filter(Boolean).join(" · ");
    ch.append(el("div", { class: "change" },
      el("span", { class: "num" }, c.d),
      el("span", { style: `color:${C.reg[REGS.indexOf(c.r)]}` }, c.r),
      el("span", { class: "muted" }, parts)));
  }
}

// ---------- performance ----------
function pills(boxId, ranges, key, onChange) {
  const box = $(boxId);
  box.querySelectorAll("button").forEach(b => b.remove());
  for (const r of ranges) {
    const b = el("button", { class: "pill" + (state[key] === r ? " on" : ""), type: "button", "aria-pressed": String(state[key] === r) }, r);
    b.addEventListener("click", () => {
      state[key] = r;
      box.querySelectorAll("button").forEach(x => { const on = x.textContent === r; x.classList.toggle("on", on); x.setAttribute("aria-pressed", String(on)); });
      onChange();
    });
    box.append(b);
  }
}

function renderPerf() {
  const S = D.series, st = D.stats[state.perf];
  const i0 = firstIndex(S.t, startFor(state.perf, D.pulse.asof));
  const t = S.t.slice(i0);
  const rebase = v => { const a = v.slice(i0), b = a[0]; return a.map(x => x / b); };
  const key = levKey(), s1 = st[key];
  const strat = rebase(S[key === "lev" ? "lev" : "strat"]), b64 = rebase(S.b6040), spx = rebase(S.spx_bh);
  const yrs = (Date.parse(D.pulse.asof) - Date.parse(st.from)) / 3.156e10;
  $("perfFrom").textContent = `from ${fmtDate(st.from)}`;
  const k = $("kpis");
  k.replaceChildren();
  const tile = (label, v, cmp) => el("div", { class: "tile" }, el("div", { class: "muted xs" }, label), el("div", { class: "v" }, v), el("div", { class: "cmp" }, cmp));
  const useCagr = yrs >= 1 && s1.cagr != null;
  const ret = x => pct(useCagr ? x.cagr : x.ret);
  const other = key === "lev" ? `1x ${ret(st.strat)}` : `${D.pulse.risk.leverage}x ${ret(st.lev)}`;
  k.append(
    tile(useCagr ? "CAGR" : "Return", ret(s1), `${other} · 60/40 ${ret(st.b6040)} · S&P ${ret(st.spx)}`),
    tile("Sharpe", s1.sharpe == null ? "—" : s1.sharpe.toFixed(2),
         `200d-only rule ${st.rec.sharpe?.toFixed(2) ?? "—"} · 60/40 ${st.b6040.sharpe?.toFixed(2) ?? "—"} · S&P ${st.spx.sharpe?.toFixed(2) ?? "—"}`),
    tile("Max drawdown", pct(s1.maxdd), `60/40 ${pct(st.b6040.maxdd)} · S&P ${pct(st.spx.maxdd)}`),
    tile("Volatility", pct(s1.vol), `S&P ${pct(st.spx.vol)} · ${st.strat.reb_per_yr} rebalances / yr`)
  );
  $("stratLbl").textContent = key === "lev" ? `Strategy ${D.pulse.risk.leverage}x` : "Strategy";
  const log = ["5Y", "10Y", "Max"].includes(state.perf);
  draw("eqChart", {
    type: "line",
    data: { datasets: [
      line("S&P 500", pts(t, spx), C.faint, { borderDash: [4, 3] }),
      line("60/40", pts(t, b64), C.muted),
      line(key === "lev" ? `Strategy ${D.pulse.risk.leverage}x` : "Strategy", pts(t, strat), C.text, { borderWidth: 2.2 })
    ] },
    options: baseOpts({ log, yfmt: v => "$" + (+v).toFixed(v < 10 ? 2 : 0) })
  });
  const dd = (() => { let pk = -Infinity; return strat.map(v => (pk = Math.max(pk, v), v / pk - 1)); })();
  draw("ddChart", {
    type: "line",
    data: { datasets: [line("Drawdown", pts(t, dd), C.neg, { fill: "origin", backgroundColor: alpha(C.neg, 0.3), borderWidth: 1 })] },
    options: baseOpts({ bands: false, yfmt: v => pct(v, 0), ymax: 0 })
  });
}

function renderTables() {
  const at = $("annualTbl");
  at.replaceChildren(el("tr", {}, el("th", {}, "Year"), el("th", {}, "Strategy"), el("th", {}, `${D.pulse.risk.leverage}x`), el("th", {}, "60/40"), el("th", {}, "S&P 500")));
  for (const a of [...D.annual].reverse()) {
    const td = v => el("td", { class: v < 0 ? "neg" : "" }, pct(v));
    at.append(el("tr", {}, el("td", {}, String(a.y) + (a.y === new Date(D.pulse.asof).getUTCFullYear() ? " YTD" : "")), td(a.strat), td(a.lev), td(a.b6040), td(a.spx)));
  }
  const rt = $("regimeTbl");
  rt.replaceChildren(el("tr", {}, el("th", {}, "Regime"), el("th", {}, "Time"), el("th", {}, "Strategy p.a."), el("th", {}, "60/40 p.a.")));
  for (const r of D.by_regime) {
    rt.append(el("tr", {},
      el("td", {}, el("i", { class: "sw", style: `background:${C.reg[REGS.indexOf(r.r)]}` }), r.r),
      el("td", {}, pct(r.share, 0)), el("td", {}, pct(r.ann)), el("td", {}, pct(r.ann_6040))));
  }
}

// ---------- S&P exposure and volatility ----------
function renderRisk() {
  const S = D.series, p = D.pulse, rk = p.risk, st = D.stats.Max;
  const tile = (label, v, cmp) => el("div", { class: "tile" }, el("div", { class: "muted xs" }, label), el("div", { class: "v" }, v), el("div", { class: "cmp" }, cmp));
  $("riskAsOf").textContent = fmtDate(p.asof);
  $("riskTiles").replaceChildren(
    tile("S&P exposure", pct(rk.e_spx, 0), Object.entries(rk.trend).map(([n, up]) => `${n}d ${up ? "↑" : "↓"}`).join(" · ")),
    tile("S&P 10d vol", pct(rk.vol10), rk.spike ? `spike: above ${pct(rk.trigger)} trigger` : `no spike · trigger ${pct(rk.trigger)}`),
    tile("Leverage", `${rk.leverage}x`, `targets S&P vol ${pct(rk.target_vol)}`),
    tile(`Vol at ${rk.leverage}x`, pct(st.lev.vol), `since 1987 · last 3M ${pct(rk.rv_lev)}`)
  );
  $("levX").textContent = rk.leverage;
  $("volNow").textContent = `${pct(rk.vol10)} vs ${pct(rk.trigger)}`;
  $("rvNow").textContent = `3M ${pct(rk.rv_lev)} vs ${pct(rk.target_vol)}`;
  const i0 = firstIndex(S.t, startFor(state.risk, p.asof));
  const t = S.t.slice(i0), cut = v => v.slice(i0);
  draw("volChart", { type: "line", data: { datasets: [
    line("Trigger (2 × 1y vol)", pts(t, cut(S.vol_trig)), C.neg, { borderDash: [5, 4] }),
    line("10-day vol", pts(t, cut(S.vol10)), C.text, { borderWidth: 1.6 })
  ] }, options: baseOpts({ bands: false, ymin: 0, yfmt: v => pct(+v, 0) }) });
  draw("expChart", { type: "line", data: { datasets: [
    line("S&P exposure", pts(t, cut(S.e_spx)), C.assets[0], { stepped: true, fill: "origin", backgroundColor: alpha(C.assets[0], 0.25), borderWidth: 1.2 })
  ] }, options: baseOpts({ bands: false, ymin: 0, ymax: 1, yfmt: v => pct(+v, 0) }) });
  const tv = t.length ? [{ x: t[0], y: rk.target_vol }, { x: t[t.length - 1], y: rk.target_vol }] : [];
  draw("rvChart", { type: "line", data: { datasets: [
    line("Target (S&P vol since 1987)", tv, C.faint, { borderDash: [5, 4], borderWidth: 1 }),
    line(`3M realised vol at ${rk.leverage}x`, pts(t, cut(S.rv_lev)), C.text, { borderWidth: 1.8 })
  ] }, options: baseOpts({ ymin: 0, yfmt: v => pct(+v, 0) }) });
}

// ---------- indicators ----------
function renderIndicators() {
  const S = D.series, p = D.pulse;
  const i0 = firstIndex(S.t, startFor(state.ind, p.asof));
  const t = S.t.slice(i0), cut = v => v.slice(i0);
  $("hyNow").textContent = `${p.hy.toFixed(2)}% vs ${p.hy_med.toFixed(2)}%`;
  $("slNow").textContent = `${p.slope.toFixed(2)} vs ${p.sl_med.toFixed(2)}`;
  draw("hyChart", { type: "line", data: { datasets: [
    line("10y median", pts(t, cut(S.hy_med)), C.reg[0], { borderDash: [5, 4] }),
    line("HY spread", pts(t, cut(S.hy)), C.text, { borderWidth: 2 })
  ] }, options: baseOpts({ yfmt: v => (+v).toFixed(1) + "%" }) });
  draw("slChart", { type: "line", data: { datasets: [
    line("10y median", pts(t, cut(S.sl_med)), C.reg[1], { borderDash: [5, 4] }),
    line("10Y − 1Y", pts(t, cut(S.slope)), C.text, { borderWidth: 2 })
  ] }, options: baseOpts({ yfmt: v => (+v).toFixed(1) }) });
  draw("depthChart", { type: "line", data: { datasets: [
    line("HY z", pts(t, cut(S.z_hy)), C.reg[0]),
    line("Slope z", pts(t, cut(S.z_sl)), C.reg[2])
  ] }, options: baseOpts({ yfmt: v => signed(+v, 1) }) });

  const W = D.weekly;
  const j0 = firstIndex(W.t, startFor(state.ind, p.asof));
  const wt = W.t.slice(j0);
  draw("probChart", { type: "line", data: { datasets: [
    line("Growth", pts(wt, W.G.slice(j0)), C.reg[0], { fill: "origin", borderWidth: 0, backgroundColor: alpha(C.reg[0], C.probfill), stack: "p" }),
    line("Inflation", pts(wt, W.I.slice(j0)), C.reg[1], { fill: "-1", borderWidth: 0, backgroundColor: alpha(C.reg[1], C.probfill), stack: "p" }),
    line("Slowdown", pts(wt, W.S.slice(j0)), C.reg[2], { fill: "-1", borderWidth: 0, backgroundColor: alpha(C.reg[2], C.probfill), stack: "p" })
  ] }, options: baseOpts({ bands: false, stacked: true, ymin: 0, ymax: 1, yfmt: v => pct(+v, 0) }) });
  renderMacro();
}

function renderMacroPills() {
  const box = $("macroPills");
  for (const [k, m] of Object.entries(MACRO)) {
    if (!D.macro[k]) continue;
    const b = el("button", { class: "pill", type: "button", "aria-pressed": "false" }, m.name.split(" (")[0].replace(", 4-wk avg", ""));
    b.addEventListener("click", () => {
      state.macro = state.macro === k ? null : k;
      box.querySelectorAll("button").forEach(x => { const on = x === b && state.macro === k; x.classList.toggle("on", on); x.setAttribute("aria-pressed", String(on)); });
      renderMacro();
    });
    box.append(b);
  }
}
function renderMacro() {
  const k = state.macro;
  $("macroBox").hidden = !k;
  if (!k) return;
  const m = MACRO[k], s = D.macro[k];
  const i0 = firstIndex(s.t, startFor(state.ind, D.pulse.asof));
  const t = s.t.slice(i0), v = s.v.slice(i0);
  $("macroTitle").textContent = m.name;
  $("macroNow").textContent = `${(+s.v[s.v.length - 1]).toFixed(k === "claims" ? 0 : 2)}${m.unit} · ${fmtDate(s.last)}`;
  const ds = [line(m.name, pts(t, v), C.text, { borderWidth: 2 })];
  if (m.ref != null) ds.unshift(line("Reference", t.length ? [{ x: t[0], y: m.ref }, { x: t[t.length - 1], y: m.ref }] : [], C.faint, { borderDash: [3, 3], borderWidth: 1 }));
  draw("macroChart", { type: "line", data: { datasets: ds }, options: baseOpts({ yfmt: x => (+x).toFixed(k === "claims" ? 0 : 1) + m.unit }) });
}

// ---------- assets ----------
function renderAssets() {
  const list = $("assetList");
  list.replaceChildren();
  for (const a of D.assets) {
    const row = el("button", { class: "assetRow", type: "button", "aria-expanded": String(state.openAsset === a.key) },
      el("span", {}, a.name, " ", el("span", { class: "tag" }, `${a.ma_len}d${a.in_rules ? "" : " · not in rules"}`)),
      el("span", { class: "num muted xs" }, a.price.toLocaleString("en-US", { maximumFractionDigits: a.price > 100 ? 1 : 4 })),
      el("span", { class: "num" }, `${a.above ? "↑" : "↓"} ${a.dist >= 0 ? "+" : "−"}${Math.abs(a.dist * 100).toFixed(1)}%`));
    row.addEventListener("click", () => { state.openAsset = state.openAsset === a.key ? null : a.key; renderAssets(); });
    list.append(row);
    if (state.openAsset === a.key) {
      const box = el("div", { class: "assetChart" }, el("div", { class: "chartBox" }, el("canvas", { id: "assetChart", role: "img", "aria-label": `${a.name} with ${a.ma_len}-day moving average` })));
      list.append(box);
      const S = D.series;
      const i0 = firstIndex(S.t, startFor(state.asset, D.pulse.asof));
      const t = S.t.slice(i0);
      draw("assetChart", { type: "line", data: { datasets: [
        line(`${a.ma_len}d MA`, pts(t, S[a.key + "_ma"].slice(i0)), C.muted, { borderDash: [5, 4] }),
        line(a.name, pts(t, S[a.key].slice(i0)), C.text, { borderWidth: 2 })
      ] }, options: baseOpts({ log: ["10Y", "Max"].includes(state.asset) && a.key !== "aud" && a.key !== "jpy" && a.key !== "chf",
                               yfmt: v => (+v).toLocaleString("en-US", { maximumFractionDigits: a.price > 100 ? 0 : 3 }) }) });
    }
  }
}

// ---------- boot ----------
async function load() {
  try {
    const r = await fetch(`data.json?t=${Date.now()}`, { cache: "no-store" });
    if (!r.ok) throw new Error(`data.json ${r.status}`);
    D = await r.json();
  } catch (e) {
    $("stamp").innerHTML = "";
    $("stamp").append(el("span", { class: "err" }, `Could not load data (${e.message}).`));
    return;
  }
  renderPulse();
  pills("perfPills", PERF_RANGES, "perf", renderPerf);
  pills("indPills", IND_RANGES, "ind", renderIndicators);
  pills("riskPills", IND_RANGES, "risk", renderRisk);
  pills("levPills", ["1x", `${D.pulse.risk.leverage}x`], "lev", renderPerf);
  pills("assetPills", IND_RANGES, "asset", renderAssets);
  if (!$("macroPills").querySelector("button")) renderMacroPills();
  renderPerf();
  renderTables();
  renderRisk();
  renderIndicators();
  renderAssets();
}
function renderThemeToggle() {
  const navy = document.documentElement.getAttribute("data-theme") === "navy";
  const b = el("button", { class: "themeBtn", type: "button" }, navy ? "Switch to Sand theme" : "Switch to Navy theme");
  b.addEventListener("click", () => {
    try { localStorage.setItem("theme", navy ? "sand" : "navy"); } catch (e) {}
    location.replace(location.pathname + (navy ? "?theme=sand" : "?theme=navy"));
  });
  $("themes").append(b);
}
renderThemeToggle();
const meta = document.querySelector('meta[name="theme-color"]');
if (meta) meta.setAttribute("content", css("--bg"));
$("refresh").addEventListener("click", load);
// called by customise.js after colours change: re-read them and redraw everything
window.redrawAll = () => {
  readColors();
  if (meta) meta.setAttribute("content", css("--bg"));
  if (!D) return;
  renderPulse(); renderPerf(); renderTables(); renderRisk(); renderIndicators(); renderAssets();
};
const cBtn = el("button", { class: "themeBtn", type: "button" }, "Customise colours and layout");
cBtn.addEventListener("click", () => window.openCustomise());
$("themes").append(cBtn);
$("customiseTop").addEventListener("click", () => window.openCustomise());
load();
