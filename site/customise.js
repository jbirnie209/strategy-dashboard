// Customise mode: colour pickers and card layout, saved on this device (localStorage).
(function () {
  const root = document.documentElement;
  const theme = () => root.getAttribute("data-theme") || "sand";
  const COLOURS = [
    ["Page", [["--bg", "Background"], ["--card", "Cards"], ["--tile", "Tiles"], ["--border", "Borders"], ["--text", "Text"], ["--muted", "Secondary text"]]],
    ["Regimes", [["--growth", "Growth"], ["--inflation", "Inflation"], ["--slowdown", "Slowdown"]]],
    ["Allocation", [["--a-spx", "S&P 500"], ["--a-ty", "10Y Treasury"], ["--a-gold", "Gold"], ["--a-cash", "Cash"]]],
    ["Charts", [["--neg", "Drawdown"]]]
  ];
  const SLIDERS = [["--band", "Regime shading strength", 0.04, 0.5, 0.01], ["--probfill", "Probability chart fill", 0.15, 1, 0.05]];
  const KEY = "custom";

  const load = () => {
    try { const s = localStorage.getItem(KEY); if (s) return JSON.parse(s); } catch (e) {}
    return JSON.parse(JSON.stringify(window.DEFAULT_CUSTOM || {}));
  };
  let cfg = load();
  cfg.colors = cfg.colors || {}; cfg.blocks = cfg.blocks || {};
  const save = () => { try { localStorage.setItem(KEY, JSON.stringify(cfg)); } catch (e) {} };

  const main = document.querySelector("main.grid");
  const cards = () => [...main.querySelectorAll(":scope > section[data-card]")];
  if (!cfg.cards) cfg.cards = cards().map(c => ({ id: c.id, show: true, wide: c.classList.contains("wide") }));
  // cards added to the page after the layout was saved: slot each in after the card it follows in the page
  cards().forEach((c, i, all) => {
    if (cfg.cards.some(x => x.id === c.id)) return;
    const prev = i ? cfg.cards.findIndex(x => x.id === all[i - 1].id) : -1;
    cfg.cards.splice(prev + 1, 0, { id: c.id, show: true, wide: c.classList.contains("wide") });
  });

  function applyColours() {
    root.removeAttribute("style");
    for (const [k, v] of Object.entries(cfg.colors[theme()] || {})) root.style.setProperty(k, v);
  }
  function applyLayout() {
    const byId = Object.fromEntries(cards().map(c => [c.id, c]));
    for (const c of cfg.cards) {
      const e = byId[c.id];
      if (!e) continue;
      main.append(e);                                // order
      e.hidden = !c.show;
      e.classList.toggle("wide", !!c.wide);
    }
    document.querySelectorAll("[data-block]").forEach(b => { b.hidden = cfg.blocks[b.dataset.block] === false; });
  }
  applyColours();
  applyLayout();

  const el = (tag, attrs = {}, ...kids) => {
    const e = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs)) {
      if (k === "class") e.className = v; else if (v === true) e.setAttribute(k, ""); else if (v !== false && v != null) e.setAttribute(k, v);
    }
    for (const k of kids) e.append(k);
    return e;
  };
  const cur = name => getComputedStyle(root).getPropertyValue(name).trim();
  let redrawTimer;
  const redraw = () => { clearTimeout(redrawTimer); redrawTimer = setTimeout(() => window.redrawAll && window.redrawAll(), 150); };

  function setColour(name, v) {
    (cfg.colors[theme()] = cfg.colors[theme()] || {})[name] = v;
    root.style.setProperty(name, v);
    save(); redraw();
  }

  function build(panel) {
    panel.replaceChildren();
    const head = el("div", { class: "cHead" }, el("h2", {}, "Customise"),
      el("button", { class: "pill", type: "button", id: "cDone" }, "Done"));
    panel.append(head, el("p", { class: "muted xs" }, `Changes save on this device straight away. Colours apply to the ${theme() === "navy" ? "Navy" : "Sand"} theme.`));

    // colours
    for (const [group, items] of COLOURS) {
      const g = el("div", { class: "cGrid" });
      for (const [name, label] of items) {
        const id = "c" + name.replace(/-/g, "");
        const inp = el("input", { type: "color", id, value: cur(name).slice(0, 7) });
        inp.addEventListener("input", () => setColour(name, inp.value));
        g.append(el("label", { class: "cSwatch", for: id }, inp, el("span", {}, label)));
      }
      panel.append(el("h3", {}, group), g);
    }
    for (const [name, label, mn, mx, st] of SLIDERS) {
      const id = "s" + name.replace(/-/g, "");
      const inp = el("input", { type: "range", id, min: mn, max: mx, step: st, value: parseFloat(cur(name)) || mn });
      inp.addEventListener("input", () => setColour(name, inp.value));
      panel.append(el("label", { class: "cSlider", for: id }, el("span", {}, label), inp));
    }

    // cards
    panel.append(el("h3", {}, "Cards"), el("p", { class: "muted xs" }, "Reorder, hide, or set full width (wide screens only)."));
    const list = el("div", { class: "cCards" });
    const names = Object.fromEntries(cards().map(c => [c.id, c.dataset.card]));
    cfg.cards.forEach((c, i) => {
      const show = el("input", { type: "checkbox", id: "show_" + c.id, checked: c.show });
      show.addEventListener("change", () => { c.show = show.checked; save(); applyLayout(); redraw(); });
      const wide = el("input", { type: "checkbox", id: "wide_" + c.id, checked: !!c.wide });
      wide.addEventListener("change", () => { c.wide = wide.checked; save(); applyLayout(); redraw(); });
      const move = d => () => {
        const j = i + d;
        if (j < 0 || j >= cfg.cards.length) return;
        [cfg.cards[i], cfg.cards[j]] = [cfg.cards[j], cfg.cards[i]];
        save(); applyLayout(); build(panel); redraw();
        panel.querySelector(`#show_${c.id}`)?.closest(".cCard")?.scrollIntoView({ block: "nearest" });
      };
      const up = el("button", { class: "pill icon sm", type: "button", "aria-label": `Move ${names[c.id]} up`, disabled: i === 0 }, "↑");
      const down = el("button", { class: "pill icon sm", type: "button", "aria-label": `Move ${names[c.id]} down`, disabled: i === cfg.cards.length - 1 }, "↓");
      up.addEventListener("click", move(-1)); down.addEventListener("click", move(1));
      list.append(el("div", { class: "cCard" },
        el("label", { for: "show_" + c.id, class: "cName" }, show, names[c.id]),
        el("label", { for: "wide_" + c.id, class: "cWide muted xs" }, wide, "Full width"),
        el("span", { class: "cMove" }, up, down)));
    });
    panel.append(list);

    // blocks inside cards
    panel.append(el("h3", {}, "Charts and sections"));
    const bl = el("div", { class: "cBlocks" });
    document.querySelectorAll("[data-block]").forEach((b, k) => {
      const name = b.dataset.block, id = "blk" + k;
      const cb = el("input", { type: "checkbox", id, checked: cfg.blocks[name] !== false });
      cb.addEventListener("change", () => { cfg.blocks[name] = cb.checked; save(); applyLayout(); redraw(); });
      const card = b.closest("section[data-card]");
      bl.append(el("label", { for: id, class: "cBlock" }, cb, el("span", {}, name), el("span", { class: "muted xxs" }, card ? card.dataset.card : "")));
    });
    panel.append(bl);

    // export / reset
    const out = el("textarea", { class: "cOut", readonly: true, rows: 4, "aria-label": "Exported settings", hidden: true });
    const exp = el("button", { class: "pill", type: "button" }, "Export settings");
    exp.addEventListener("click", async () => {
      out.hidden = false; out.value = JSON.stringify(cfg); out.select();
      try { await navigator.clipboard.writeText(out.value); exp.textContent = "Copied to clipboard"; } catch (e) { exp.textContent = "Copy the text below"; }
    });
    const reset = el("button", { class: "pill", type: "button" }, "Reset to default");
    reset.addEventListener("click", () => { try { localStorage.removeItem(KEY); } catch (e) {} location.reload(); });
    panel.append(el("h3", {}, "Save as default"),
      el("p", { class: "muted xs" }, "To make these settings the default on every device, tap Export and send me the copied text."),
      el("div", { class: "pills" }, exp, reset), out);
    panel.querySelector("#cDone").addEventListener("click", close);
  }

  let sheet, prevFocus;
  function close() { sheet.hidden = true; document.body.classList.remove("cOpen"); prevFocus && prevFocus.focus(); }
  window.openCustomise = () => {
    prevFocus = document.activeElement;
    if (!sheet) {
      sheet = el("div", { class: "cSheet", role: "dialog", "aria-modal": "true", "aria-label": "Customise colours and layout" });
      sheet.addEventListener("keydown", e => { if (e.key === "Escape") close(); });
      document.body.append(sheet);
    }
    build(sheet);
    sheet.hidden = false;
    document.body.classList.add("cOpen");
    sheet.querySelector("#cDone").focus();
  };
})();
