/* Two small SVG charts, no libraries (so the mock-up opens straight from disk).
   - lineChart: balance and equity over time, crosshair + tooltip, arrow-key control.
   - barChart:  signed horizontal bars from a zero baseline, one tooltip per bar.
   Colours come from CSS classes, so switching light/dark needs no redraw. */
(function () {
  "use strict";
  const { h, s } = window.DOM;

  function niceScale(min, max, target) {
    const pad = (max - min) * 0.08 || 1;
    const lo = min - pad;
    const hi = max + pad;
    const raw = (hi - lo) / target;
    const mag = Math.pow(10, Math.floor(Math.log10(raw)));
    const step = [1, 2, 5, 10].find((m) => m * mag >= raw) * mag;
    const start = Math.floor(lo / step) * step;
    const end = Math.ceil(hi / step) * step;
    const ticks = [];
    for (let v = start; v <= end + step * 0.001; v += step) ticks.push(Math.round(v * 1e6) / 1e6);
    return { min: ticks[0], max: ticks[ticks.length - 1], ticks };
  }

  function timeTicks(t0, t1, stepHours) {
    const out = [];
    const d = new Date(t0);
    d.setMinutes(0, 0, 0);
    if (d.getTime() < t0) d.setHours(d.getHours() + 1);
    while (d.getHours() % stepHours !== 0) d.setHours(d.getHours() + 1);
    while (d.getTime() <= t1) {
      out.push(new Date(d.getTime()));
      d.setHours(d.getHours() + stepHours);
    }
    return out;
  }

  function tipRow(keyNode, value, name) {
    return h("div", { class: "tip-row" }, keyNode, h("span", { class: "tip-val" }, value), h("span", { class: "tip-name" }, name));
  }

  /* ------------------------------------------------------------------ line */
  function lineChart(root, cfg) {
    const H = cfg.height || 280;
    let M = { t: 14, r: 118, b: 30, l: 66 };
    const pts = cfg.points;
    const t0 = pts[0].t;
    const t1 = pts[pts.length - 1].t;
    const values = [];
    pts.forEach((p) => cfg.series.forEach((se) => values.push(p.v[se.key])));
    const scale = niceScale(Math.min(...values), Math.max(...values), 5);

    const wrap = h("div", { class: "chart-wrap" });
    const tip = h("div", { class: "tip", hidden: true, "aria-live": "polite" });
    root.replaceChildren(wrap);

    let svg = null;
    let current = -1;
    let lastWidth = 0;
    let api = null;

    function draw() {
      const W = Math.max(300, Math.round(wrap.clientWidth));
      // Narrow screens: tighter margins and fewer time labels so nothing collides.
      M = W < 480 ? { t: 14, r: 98, b: 30, l: 56 } : { t: 14, r: 118, b: 30, l: 66 };
      const iw = W - M.l - M.r;
      const ih = H - M.t - M.b;
      const stepHours = cfg.xStepHours || (iw < 260 ? 8 : iw < 420 ? 6 : 4);
      const x = (t) => M.l + ((t - t0) / (t1 - t0)) * iw;
      const y = (v) => M.t + ((scale.max - v) / (scale.max - scale.min)) * ih;

      const kids = [];
      for (const tv of scale.ticks) {
        kids.push(s("line", { class: tv === scale.min ? "ch-axis" : "ch-grid", x1: M.l, x2: W - M.r, y1: y(tv), y2: y(tv) }));
        kids.push(s("text", { class: "ch-tick", x: M.l - 10, y: y(tv) + 4, "text-anchor": "end" }, cfg.fmtTick(tv)));
      }
      for (const d of timeTicks(t0, t1, stepHours)) {
        kids.push(s("text", { class: "ch-tick", x: x(d.getTime()), y: H - 8, "text-anchor": "middle" }, cfg.fmtXTick(d)));
      }

      // The first series in the config sits on top.
      for (const se of [...cfg.series].reverse()) {
        let d = "";
        pts.forEach((p, i) => {
          const px = x(p.t).toFixed(1);
          const py = y(p.v[se.key]).toFixed(1);
          if (i === 0 || (cfg.gapMs && p.t - pts[i - 1].t > cfg.gapMs)) d += `M${px} ${py}`;   // a gap (weekend) breaks the line
          else if (se.step) d += `H${px}V${py}`;
          else d += `L${px} ${py}`;
        });
        kids.push(s("path", { class: `ch-line ${se.cls}`, d }));
      }

      // End dots and direct labels. Labels are pushed apart if two lines finish close together.
      const last = pts[pts.length - 1];
      const ends = cfg.series.map((se) => ({ se, py: y(last.v[se.key]), ly: y(last.v[se.key]) }));
      ends.sort((a, b) => a.py - b.py);
      for (let i = 1; i < ends.length; i++) if (ends[i].ly - ends[i - 1].ly < 36) ends[i].ly = ends[i - 1].ly + 36;
      for (const e of [...ends].reverse()) {
        kids.push(s("circle", { class: `ch-dot ${e.se.cls}`, cx: x(t1), cy: e.py, r: 4.5 }));
      }
      for (const e of ends) {
        kids.push(s("text", { class: "ch-end-name", x: x(t1) + 14, y: e.ly - 2 }, e.se.label));
        kids.push(s("text", { class: "ch-end-val", x: x(t1) + 14, y: e.ly + 14 }, cfg.fmtValue(last.v[e.se.key])));
      }

      const cross = s("line", { class: "ch-cross", y1: M.t, y2: M.t + ih, visibility: "hidden" });
      const dots = cfg.series.map((se) => s("circle", { class: `ch-dot ${se.cls}`, r: 4.5, visibility: "hidden" }));
      kids.push(cross, ...dots);

      function indexAt(px) {
        const t = t0 + ((px - M.l) / iw) * (t1 - t0);
        let lo = 0;
        let hi = pts.length - 1;
        while (hi - lo > 1) {
          const mid = (lo + hi) >> 1;
          if (pts[mid].t <= t) lo = mid;
          else hi = mid;
        }
        return Math.abs(pts[lo].t - t) <= Math.abs(pts[hi].t - t) ? lo : hi;
      }

      function show(i) {
        current = Math.max(0, Math.min(pts.length - 1, i));
        const p = pts[current];
        const px = x(p.t);
        cross.setAttribute("x1", px);
        cross.setAttribute("x2", px);
        cross.setAttribute("visibility", "visible");
        cfg.series.forEach((se, k) => {
          dots[k].setAttribute("cx", px);
          dots[k].setAttribute("cy", y(p.v[se.key]));
          dots[k].setAttribute("visibility", "visible");
        });
        const rows = [...cfg.series].sort((a, b) => p.v[b.key] - p.v[a.key]).map((se) =>
          tipRow(h("i", { class: `line-key ${se.cls}` }), cfg.fmtValue(p.v[se.key]), se.label));
        for (const extra of cfg.extraRows ? cfg.extraRows(p) : []) {
          rows.push(tipRow(h("i"), extra.value, extra.name));
        }
        tip.replaceChildren(h("div", { class: "tip-title" }, cfg.fmtTipTitle(new Date(p.t))), ...rows);
        tip.hidden = false;
        const tw = tip.offsetWidth;
        let left = px + 16;
        if (left + tw > W - 4) left = px - tw - 16;
        tip.style.left = `${Math.max(4, left)}px`;
        tip.style.top = `${M.t + 6}px`;
      }

      function hide() {
        current = -1;
        cross.setAttribute("visibility", "hidden");
        dots.forEach((d) => d.setAttribute("visibility", "hidden"));
        tip.hidden = true;
      }

      svg = s("svg", {
        class: "chart", viewBox: `0 0 ${W} ${H}`, width: W, height: H, role: "img", tabindex: 0,
        "aria-label": cfg.ariaLabel,
      }, ...kids);

      svg.addEventListener("pointermove", (e) => {
        const r = svg.getBoundingClientRect();
        const px = ((e.clientX - r.left) * W) / r.width;
        if (px < M.l - 4 || px > W - M.r + 4) return hide();
        show(indexAt(px));
      });
      svg.addEventListener("pointerleave", () => { if (document.activeElement !== svg) hide(); });
      svg.addEventListener("focus", () => show(pts.length - 1));
      svg.addEventListener("blur", hide);
      svg.addEventListener("keydown", (e) => {
        const step = { ArrowLeft: -1, ArrowRight: 1, PageDown: -12, PageUp: 12 }[e.key];
        if (step !== undefined) { e.preventDefault(); show((current < 0 ? pts.length - 1 : current) + step); }
        else if (e.key === "Home") { e.preventDefault(); show(0); }
        else if (e.key === "End") { e.preventDefault(); show(pts.length - 1); }
        else if (e.key === "Escape") hide();
      });

      wrap.replaceChildren(svg, tip);
      api = { show, hide };
    }

    // Redraw on the next frame: drawing inside the callback resizes the wrapper and trips the
    // browser's "ResizeObserver loop" warning.
    let queued = false;
    const ro = new ResizeObserver(() => {
      if (queued) return;
      queued = true;
      requestAnimationFrame(() => {
        queued = false;
        const w = Math.round(wrap.clientWidth);
        if (w === 0 || w === lastWidth) return;
        lastWidth = w;
        const keep = current;
        const hadFocus = document.activeElement === svg;
        draw();
        if (hadFocus) {
          svg.focus({ preventScroll: true });
          if (keep >= 0) api.show(keep);
        }
      });
    });
    ro.observe(wrap);

    return { destroy: () => ro.disconnect() };
  }

  /* ------------------------------------------------------------------- bar */
  function barRoundedPath(x0, x1, y, hgt, r) {
    const len = Math.abs(x1 - x0);
    if (len < 1) return `M${x0 - 1} ${y}h2v${hgt}h-2z`;
    const rad = Math.min(r, len / 2, hgt / 2);
    const dir = x1 >= x0 ? 1 : -1;
    // Square at the baseline (x0), 4px rounded at the data end (x1).
    return [
      `M${x0} ${y}`,
      `H${x1 - dir * rad}`,
      `Q${x1} ${y} ${x1} ${y + rad}`,
      `V${y + hgt - rad}`,
      `Q${x1} ${y + hgt} ${x1 - dir * rad} ${y + hgt}`,
      `H${x0}`,
      "Z",
    ].join("");
  }

  function barChart(root, cfg) {
    const rowH = 50;
    const barH = 20;
    const labelW = 134;
    const top = 6;
    const rows = cfg.rows;
    const wrap = h("div", { class: "chart-wrap" });
    const tip = h("div", { class: "tip", hidden: true, "aria-live": "polite" });
    root.replaceChildren(wrap);
    let lastWidth = 0;

    function draw() {
      const W = Math.max(260, Math.round(wrap.clientWidth));
      const H = top + rows.length * rowH + 6;
      const vals = rows.map((r) => r.value);
      const minV = Math.min(0, ...vals);
      const maxV = Math.max(0, ...vals);
      const padNeg = minV < 0 ? 76 : 0;
      const padPos = maxV > 0 ? 76 : 0;
      const aw = Math.max(40, W - labelW - 4 - padNeg - padPos);
      const k = aw / (maxV - minV || 1);
      const x0 = labelW + padNeg + -minV * k;

      const kids = [s("line", { class: "ch-axis", x1: x0, x2: x0, y1: top - 2, y2: H - 4 })];

      function showTip(row, rowTop, px) {
        tip.replaceChildren(
          h("div", { class: "tip-title" }, row.label),
          ...row.detail.map((d) => tipRow(h("i"), d.value, d.name)),
        );
        tip.hidden = false;
        const tw = tip.offsetWidth;
        let left = px + 14;
        if (left + tw > W - 4) left = px - tw - 14;
        tip.style.left = `${Math.max(4, left)}px`;
        tip.style.top = `${rowTop + rowH - 6}px`;
      }

      rows.forEach((row, i) => {
        const rowTop = top + i * rowH;
        const yBar = rowTop + (rowH - barH) / 2;
        const x1 = x0 + row.value * k;
        const positive = row.value >= 0;
        const group = s("g", {
          class: "ch-row", "data-slot": row.slot, tabindex: 0, role: "img", "aria-label": row.aria,
        },
          s("rect", { class: "ch-hit", x: 0, y: rowTop, width: W, height: rowH - 2, rx: 4 }),
          s("circle", { class: "ch-key", cx: 6, cy: rowTop + rowH / 2, r: 5 }),
          s("text", { class: "ch-row-label", x: 20, y: rowTop + rowH / 2 + 4.5 }, row.label),
          row.value === 0 ? null : s("path", { class: "ch-bar", d: barRoundedPath(x0, x1, yBar, barH, 4) }),
          s("text", {
            class: `ch-val ${row.value > 0 ? "pos" : row.value < 0 ? "neg" : ""}`,
            x: positive ? Math.max(x0, x1) + 8 : x1 - 8, y: rowTop + rowH / 2 + 4.5,
            "text-anchor": positive ? "start" : "end",
          }, row.valueText),
        );
        group.addEventListener("pointermove", (e) => {
          const r = group.ownerSVGElement.getBoundingClientRect();
          showTip(row, rowTop, ((e.clientX - r.left) * W) / r.width);
        });
        group.addEventListener("pointerleave", () => { if (document.activeElement !== group) tip.hidden = true; });
        group.addEventListener("focus", () => showTip(row, rowTop, x0));
        group.addEventListener("blur", () => { tip.hidden = true; });
        kids.push(group);
      });

      const svg = s("svg", { class: "chart", viewBox: `0 0 ${W} ${H}`, width: W, height: H, role: "group", "aria-label": cfg.ariaLabel }, ...kids);
      wrap.replaceChildren(svg, tip);
    }

    let queued = false;
    const ro = new ResizeObserver(() => {
      if (queued) return;
      queued = true;
      requestAnimationFrame(() => {
        queued = false;
        const w = Math.round(wrap.clientWidth);
        if (w === 0 || w === lastWidth) return;
        lastWidth = w;
        draw();
      });
    });
    ro.observe(wrap);
    return { destroy: () => ro.disconnect() };
  }

  /* ---------------------------------------------------------------- candles
     Candles with the two averages and the signal markers.
       cfg.candles   { t: [ms], o, h, l, c, fast, slow }   (fast/slow may hold null)
       cfg.markers   [{ t: ms, side, traded, note }]       a marker sits on the candle that contains it
       cfg.levels    [{ label, v }]                         dashed lines (entry, target, stop)
     Up candles are hollow and down candles are filled, so direction never depends on colour.
     Markers: a triangle pointing up is a buy, pointing down a sell; hollow means "not traded". */
  function candleChart(root, cfg) {
    const H = cfg.height || 360;
    const C = cfg.candles;
    const n = C.t.length;
    const wrap = h("div", { class: "chart-wrap" });
    const tip = h("div", { class: "tip", hidden: true, "aria-live": "polite" });
    root.replaceChildren(wrap);
    let svg = null;
    let current = -1;
    let lastWidth = 0;
    let api = null;

    // The candle that holds time t: the last one that opened at or before it.
    function candleOf(t) {
      let lo = 0;
      let hi = n - 1;
      if (t < C.t[0]) return -1;
      while (lo < hi) {
        const mid = (lo + hi + 1) >> 1;
        if (C.t[mid] <= t) lo = mid;
        else hi = mid - 1;
      }
      return lo;
    }

    function draw() {
      const W = Math.max(300, Math.round(wrap.clientWidth));
      const narrow = W < 480;
      const M = { t: 12, r: narrow ? 50 : 62, b: 28, l: narrow ? 54 : 64 };
      const iw = W - M.l - M.r;
      const ih = H - M.t - M.b;
      const vis = Math.max(30, Math.floor(iw / 6));
      const i0 = Math.max(0, n - vis);
      const count = n - i0;
      const step = iw / count;
      const cx = (k) => M.l + (k - i0 + 0.5) * step;

      let lo = Infinity;
      let hi = -Infinity;
      const take = (v) => { if (v !== null && v !== undefined) { lo = Math.min(lo, v); hi = Math.max(hi, v); } };
      for (let k = i0; k < n; k++) { take(C.l[k]); take(C.h[k]); take(C.fast[k]); take(C.slow[k]); }
      const wanted = (cfg.levels || []).filter((lv) => cfg.extendForLevels || (lv.v >= lo && lv.v <= hi));
      wanted.forEach((lv) => take(lv.v));
      const scale = niceScale(lo, hi, 5);
      const y = (v) => M.t + ((scale.max - v) / (scale.max - scale.min)) * ih;

      const kids = [];
      for (const tv of scale.ticks) {
        kids.push(s("line", { class: tv === scale.min ? "ch-axis" : "ch-grid", x1: M.l, x2: W - M.r, y1: y(tv), y2: y(tv) }));
        kids.push(s("text", { class: "ch-tick", x: M.l - 8, y: y(tv) + 4, "text-anchor": "end" }, cfg.fmtPrice(tv)));
      }
      const ticks = narrow ? 3 : 6;
      for (let j = 0; j < ticks; j++) {
        const k = i0 + Math.round((j * (count - 1)) / (ticks - 1));
        const anchor = j === 0 ? "start" : j === ticks - 1 ? "end" : "middle";
        kids.push(s("text", { class: "ch-tick", x: j === 0 ? M.l : j === ticks - 1 ? W - M.r : cx(k), y: H - 8, "text-anchor": anchor }, cfg.fmtXTick(new Date(C.t[k]))));
      }

      // Entry, target and stop of the open trade.
      for (const lv of wanted) {
        kids.push(s("line", { class: "ch-level", x1: M.l, x2: W - M.r, y1: y(lv.v), y2: y(lv.v) }));
        kids.push(s("text", { class: "ch-level-label", x: M.l + 6, y: y(lv.v) - 4 }, `${lv.label} ${cfg.fmtPrice(lv.v)}`));
      }

      // Candles.
      const bodyW = Math.max(1, Math.min(12, step * 0.62));
      for (let k = i0; k < n; k++) {
        const up = C.c[k] >= C.o[k];
        const top = y(Math.max(C.o[k], C.c[k]));
        const bot = y(Math.min(C.o[k], C.c[k]));
        kids.push(s("g", { class: up ? "cd cd-up" : "cd cd-dn" },
          s("line", { x1: cx(k), x2: cx(k), y1: y(C.h[k]), y2: y(C.l[k]) }),
          s("rect", { x: cx(k) - bodyW / 2, y: top, width: bodyW, height: Math.max(1, bot - top) })));
      }

      // The two averages. A line stops where the value is missing.
      for (const [key, cls] of [["slow", "slow"], ["fast", "fast"]]) {
        let d = "";
        let pen = false;
        for (let k = i0; k < n; k++) {
          const v = C[key][k];
          if (v === null) { pen = false; continue; }
          d += `${pen ? "L" : "M"}${cx(k).toFixed(1)} ${y(v).toFixed(1)}`;
          pen = true;
        }
        if (d) kids.push(s("path", { class: `ch-line ${cls}`, d }));
      }

      // Signal markers, grouped per candle and side.
      const groups = new Map();
      for (const m of cfg.markers) {
        const k = candleOf(m.t);
        if (k < i0) continue;
        const key = `${k}|${m.side}`;
        if (!groups.has(key)) groups.set(key, { k, side: m.side, n: 0, traded: false });
        const g = groups.get(key);
        g.n += 1;
        g.traded = g.traded || m.traded;
      }
      for (const g of groups.values()) {
        const buy = g.side === "buy";
        const px = cx(g.k);
        const py = buy ? y(C.l[g.k]) + 13 : y(C.h[g.k]) - 13;
        const d = buy ? `M${px} ${py - 6}L${px + 5.5} ${py + 4}L${px - 5.5} ${py + 4}Z` : `M${px} ${py + 6}L${px + 5.5} ${py - 4}L${px - 5.5} ${py - 4}Z`;
        kids.push(s("path", { class: `ch-mark ${g.traded ? "traded" : "skipped"}`, d }));
        if (g.n > 1) kids.push(s("text", { class: "ch-mark-n", x: px + 8, y: py + 4 }, `×${g.n}`));
      }

      // Direct labels at the right edge: both lines and the last close.
      const lastK = n - 1;
      const labels = [{ text: "Slow", cls: "slow", v: C.slow[lastK] }, { text: "Fast", cls: "fast", v: C.fast[lastK] }, { text: cfg.fmtPrice(C.c[lastK]), cls: "last", v: C.c[lastK] }]
        .filter((l) => l.v !== null).map((l) => ({ ...l, py: y(l.v), ly: y(l.v) })).sort((a, b) => a.py - b.py);
      for (let i = 1; i < labels.length; i++) if (labels[i].ly - labels[i - 1].ly < 15) labels[i].ly = labels[i - 1].ly + 15;
      for (const l of labels) kids.push(s("text", { class: `ch-end ${l.cls}`, x: W - M.r + 6, y: l.ly + 4 }, l.text));

      const cross = s("line", { class: "ch-cross", y1: M.t, y2: M.t + ih, visibility: "hidden" });
      kids.push(cross);

      function show(k) {
        current = Math.max(i0, Math.min(n - 1, k));
        const px = cx(current);
        cross.setAttribute("x1", px);
        cross.setAttribute("x2", px);
        cross.setAttribute("visibility", "visible");
        const row = (name, value) => tipRow(h("i"), value, name);
        const f = C.fast[current];
        const sl = C.slow[current];
        const here = cfg.markers.filter((m) => candleOf(m.t) === current);
        tip.replaceChildren(
          h("div", { class: "tip-title" }, cfg.fmtTipTitle(new Date(C.t[current]))),
          row("Open", cfg.fmtPrice(C.o[current])), row("High", cfg.fmtPrice(C.h[current])),
          row("Low", cfg.fmtPrice(C.l[current])), row("Close", cfg.fmtPrice(C.c[current])),
          row("Fast line", f === null ? "not ready" : f.toFixed(2)), row("Slow line", sl === null ? "not ready" : sl.toFixed(2)),
          ...here.slice(-4).map((m) => h("div", { class: "tip-signal" },
            `${m.side === "buy" ? "Buy" : "Sell"} signal at ${cfg.fmtClock(new Date(m.t))}`, m.traded ? ", traded" : `, not traded (${m.note || "skipped"})`)),
          ...(here.length > 4 ? [h("div", { class: "tip-signal" }, `and ${here.length - 4} earlier in this candle`)] : []));
        tip.hidden = false;
        const tw = tip.offsetWidth;
        let left = px + 16;
        if (left + tw > W - 4) left = px - tw - 16;
        tip.style.left = `${Math.max(4, left)}px`;
        tip.style.top = `${M.t + 6}px`;
      }
      function hide() { current = -1; cross.setAttribute("visibility", "hidden"); tip.hidden = true; }

      svg = s("svg", { class: "chart", viewBox: `0 0 ${W} ${H}`, width: W, height: H, role: "img", tabindex: 0, "aria-label": cfg.ariaLabel }, ...kids);
      svg.addEventListener("pointermove", (e) => {
        const r = svg.getBoundingClientRect();
        const px = ((e.clientX - r.left) * W) / r.width;
        if (px < M.l || px > W - M.r) return hide();
        show(i0 + Math.floor((px - M.l) / step));
      });
      svg.addEventListener("pointerleave", () => { if (document.activeElement !== svg) hide(); });
      svg.addEventListener("focus", () => show(n - 1));
      svg.addEventListener("blur", hide);
      svg.addEventListener("keydown", (e) => {
        const move = { ArrowLeft: -1, ArrowRight: 1, PageDown: -10, PageUp: 10 }[e.key];
        if (move !== undefined) { e.preventDefault(); show((current < 0 ? n - 1 : current) + move); }
        else if (e.key === "Home") { e.preventDefault(); show(i0); }
        else if (e.key === "End") { e.preventDefault(); show(n - 1); }
        else if (e.key === "Escape") hide();
      });
      wrap.replaceChildren(svg, tip);
      api = { show, hide };
    }

    let queued = false;
    const ro = new ResizeObserver(() => {
      if (queued) return;
      queued = true;
      requestAnimationFrame(() => {
        queued = false;
        const w = Math.round(wrap.clientWidth);
        if (w === 0 || w === lastWidth) return;
        lastWidth = w;
        const keep = current;
        const hadFocus = document.activeElement === svg;
        draw();
        if (hadFocus) { svg.focus({ preventScroll: true }); if (keep >= 0) api.show(keep); }
      });
    });
    ro.observe(wrap);
    return { destroy: () => ro.disconnect() };
  }

  window.Charts = { lineChart, barChart, candleChart };
})();
