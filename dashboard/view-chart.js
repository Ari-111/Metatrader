/* Chart screen: candles on any timeframe, the two averages, and every signal.
   The strategy works from 1-minute candles only. A timeframe here just regroups the same candles,
   so a Buy or Sell sits at the same moment on every chart (see docs/sma-cross-spec.md, section 2). */
(function () {
  "use strict";
  window.Views = window.Views || {};

  window.Views.chart = function (ctx) {
    const { D, h, icon, sim } = ctx;
    const { s } = window.DOM;
    const C = D.chart;
    const TF = [["1m", "1 min"], ["5m", "5 min"], ["30m", "30 min"], ["1h", "1 hour"], ["4h", "4 hour"], ["1d", "Day"], ["1mo", "Month"]];
    const LABEL = Object.fromEntries(TF);
    let tf = "1m";

    let markers = [];
    let cache = {};
    let cacheAsOf = null;
    function refreshData() { // live data replaces the chart contents in place, so redo what was derived from them
      if (cacheAsOf === C.as_of) return;
      cacheAsOf = C.as_of;
      cache = {};
      markers = C.markers.map((m) => Object.assign({}, m, { t: Date.parse(m.t) }));
    }
    function candles(key) {
      refreshData();
      if (!cache[key]) {
        const cs = C.timeframes[key];
        cache[key] = Object.assign({}, cs, { t: cs.t.map((t) => Date.parse(t)) });
      }
      return cache[key];
    }

    const mon = new Intl.DateTimeFormat("en-GB", { month: "short" });
    const longMonth = new Intl.DateTimeFormat("en-GB", { month: "long", year: "numeric" });
    const dayNum = new Intl.DateTimeFormat("en-GB", { day: "numeric", month: "short" });
    const fmtPrice = (v) => v.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    const intraday = () => ["1m", "5m", "30m", "1h", "4h"].includes(tf);
    const fmtXTick = (d) => {
      if (tf === "1m" || tf === "5m") return ctx.timeFmt.format(d);
      if (tf === "30m" || tf === "1h" || tf === "4h") return `${dayNum.format(d)}, ${ctx.timeFmt.format(d)}`;
      if (tf === "1d") return dayNum.format(d);
      return `${mon.format(d)} ${String(d.getFullYear()).slice(2)}`;
    };
    const fmtTipTitle = (d) => (intraday() ? `${LABEL[tf]} candle, ${ctx.dayFmt.format(d)} ${ctx.timeFmt.format(d)}`
      : tf === "1d" ? `Day candle, ${ctx.dayFmt.format(d)}` : `Month candle, ${longMonth.format(d)}`);

    const glyph = (traded, buy) => s("svg", { class: "glyph", viewBox: "0 0 14 14", "aria-hidden": "true" },
      s("path", { class: traded ? "traded" : "skipped", d: buy ? "M7 2 L12 11.5 H2 Z" : "M7 12 L12 2.5 H2 Z" }));

    function levels() {
      const pos = D.open_positions.find((p) => p.strategy_id === "sma_cross");
      if (!pos || (sim.closed && sim.closed.position_id === pos.position_id)) return [];
      const lv = sim.levels[pos.position_id] || {};
      return [
        { label: "Target", v: lv.tp !== undefined ? lv.tp : pos.tp },
        { label: "Entry", v: pos.open_price },
        { label: "Stop", v: lv.sl !== undefined ? lv.sl : pos.sl },
      ];
    }

    function chartSection() {
      const cs = candles(tf); // also refreshes markers when the data changed
      const host = h("div");
      ctx.track(window.Charts.candleChart(host, {
        // Entry, stop and target are about $40 wide: useful on short timeframes, only clutter on a daily or monthly chart.
        candles: cs, markers, height: 380, levels: ["1m", "5m", "30m", "1h"].includes(tf) ? levels() : [], extendForLevels: tf === "1m" || tf === "5m",
        fmtPrice, fmtXTick, fmtTipTitle, fmtClock: (d) => ctx.timeFmt.format(d),
        ariaLabel: `${LABEL[tf]} gold candles with the fast and slow lines and the buy and sell signals. Latest close ${fmtPrice(cs.c[cs.c.length - 1])}. Use the arrow keys to step through the candles.`,
      }));

      const legend = h("ul", { class: "legend" },
        h("li", null, h("i", { class: "line-key fast" }), "Fast line (last 100 one-minute closes)"),
        h("li", null, h("i", { class: "line-key slow" }), "Slow line (last 5,000)"),
        h("li", null, glyph(true, true), "Buy"),
        h("li", null, glyph(true, false), "Sell"),
        h("li", null, glyph(false, true), "Hollow: not traded"),
        h("li", null, h("i", { class: "candle-key" }), "Closed up"),
        h("li", null, h("i", { class: "candle-key dn" }), "Closed down"));

      // Table version of the newest candles.
      const n = cs.t.length;
      const rows = [];
      for (let i = n - 1; i >= Math.max(0, n - 20); i--) {
        const next = i + 1 < n ? cs.t[i + 1] : Infinity;
        rows.push({
          t: cs.t[i], o: cs.o[i], h: cs.h[i], l: cs.l[i], c: cs.c[i], fast: cs.fast[i], slow: cs.slow[i],
          sig: markers.filter((m) => m.t >= cs.t[i] && m.t < next),
        });
      }
      const tableNode = ctx.table({
        caption: `Newest ${LABEL[tf]} candles`,
        columns: [
          { label: "Candle", cell: (r) => (tf === "1d" ? ctx.dayFmt.format(new Date(r.t)) : tf === "1mo" ? longMonth.format(new Date(r.t)) : `${ctx.dayFmt.format(new Date(r.t))} ${ctx.timeFmt.format(new Date(r.t))}`) },
          { label: "Open", num: true, cell: (r) => fmtPrice(r.o) }, { label: "High", num: true, cell: (r) => fmtPrice(r.h) },
          { label: "Low", num: true, cell: (r) => fmtPrice(r.l) }, { label: "Close", num: true, cell: (r) => fmtPrice(r.c) },
          { label: "Fast line", num: true, cell: (r) => (r.fast === null ? "—" : r.fast.toFixed(2)) },
          { label: "Slow line", num: true, cell: (r) => (r.slow === null ? "—" : r.slow.toFixed(2)) },
          { label: "Signals", cell: (r) => (r.sig.length ? r.sig.map((m) => `${m.side === "buy" ? "Buy" : "Sell"}${m.traded ? "" : " (not traded)"}`).join(", ") : "") },
        ],
        rows,
      });

      const inRange = markers.filter((m) => m.t >= cs.t[0]);
      const buys = inRange.filter((m) => m.side === "buy").length;
      const traded = inRange.filter((m) => m.traded).length;
      const footer = h("dl", { class: "facts", style: "margin-top:8px" },
        ctx.fact("Candles loaded", `${n} (${LABEL[tf]})`),
        ctx.fact("Signals in the loaded candles", `${inRange.length} (${buys} buy, ${inRange.length - buys} sell), ${traded} traded`),
        ctx.fact("Latest, from 1-minute candles", `fast ${C.latest.fast.toFixed(2)}, slow ${C.latest.slow.toFixed(2)}`));

      return ctx.chartSheet({
        title: `Gold, ${LABEL[tf]} candles`, sub: "Newest on the right. The last candle is still forming.", legend, chartHost: host,
        tableNode, tableNote: "The newest 20 candles, newest first.", footer, className: "span-12",
      });
    }

    function render() {
      const tfButtons = TF.map(([id, label]) => h("button", {
        type: "button", id: `tf-${id}`, "aria-pressed": String(tf === id),
        onclick: () => { tf = id; ctx.focus.id = `tf-${id}`; ctx.refresh(); },
      }, label));
      const seconds = ["5 s", "15 s", "30 s"].map((label) => h("button", {
        type: "button", disabled: true, title: "Not in this mock-up. MT5 has no seconds charts; they could only be drawn from ticks recorded since the bot started.",
      }, label));

      return h("div", null,
        ctx.pageHead("Chart", "Gold with the two averages and every signal."),
        h("div", { class: "tf-wrap" },
          h("div", { class: "seg scrolls", role: "group", "aria-label": "Chart timeframe" }, ...tfButtons, ...seconds)),
        h("div", { class: "grid" },
          chartSection(),
          h("section", { class: "sheet span-7", "aria-labelledby": "same-title" },
            h("div", { class: "sheet-head" }, h("h2", { id: "same-title" }, "Why the signals do not change with the timeframe")),
            h("div", { class: "sheet-body stack" },
              h("p", null, "The strategy always works from 1-minute candles: the fast line is the average of the last 100 one-minute closes and the slow line the last 5,000. The timeframe above only changes how those candles are grouped for drawing, so a Buy or a Sell appears at the same moment on every chart."),
              h("p", { class: "dim" }, "A bigger candle can hold several signals, and the opposite cross can happen later inside the same candle, so the two lines at the end of a big candle may show the newer state. That is why markers come from the signal list and are never worked out from the lines on the big chart."),
              h("p", { class: "dim" }, "Same signals does not mean accurate signals. It means the chart you look at never changes what the bot does."))),
          h("section", { class: "sheet span-5", "aria-labelledby": "sec-title" },
            h("div", { class: "sheet-head" }, h("h2", { id: "sec-title" }, "5, 15 and 30-second charts")),
            h("div", { class: "sheet-body stack" },
              h("p", null, "Not in this mock-up. MT5 has no seconds charts, so they could only be drawn from ticks the bot has recorded since it started, with no earlier history."),
              h("p", { class: "dim" }, "They would be for looking only. They could not change a signal, because the strategy does not use them.")))));
    }

    return { render };
  };
})();
