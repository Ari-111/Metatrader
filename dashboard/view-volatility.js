/* Volatility screen: how big gold's moves are now, and what the next 12 and 24 trading hours may bring.
   "Volatility" is the typical gold move per hour in dollars. It is not the VIX. The scorecard shows how the
   forecast did on past data it had not seen, next to simple guesses (tools/volatility_model.py). */
(function () {
  "use strict";
  window.Views = window.Views || {};

  window.Views.volatility = function (ctx) {
    const { D, h, icon } = ctx;
    const V = D.volatility;
    const dateFmt = new Intl.DateTimeFormat("en-GB", { day: "numeric", month: "short", year: "numeric" });
    const usd = (v) => `$${v.toFixed(2)}`;
    const pc = (v) => `${Math.round(v * 100)}%`;
    const pc1 = (v) => `${v.toFixed(1)}%`;

    const LEVEL = { calm: "Calm", normal: "Normal", high: "High", extreme: "Extreme" };
    const words = (p) => (p < 0.25 ? "unlikely" : p < 0.45 ? "less likely than not" : p <= 0.55 ? "close to a coin toss" : p <= 0.75 ? "more likely than not" : "likely");

    function nowTile() {
      const n = V.now;
      const rank = n.percentile < 0.5 ? `Quieter than ${Math.round((1 - n.percentile) * 100)}%` : `Busier than ${Math.round(n.percentile * 100)}%`;
      return h("section", { class: "tile", "aria-labelledby": "now-t" },
        h("h2", { id: "now-t" }, "Right now (last 6 trading hours)"),
        h("p", { class: "figure" }, usd(n.value), " ", h("small", null, "per hour")),
        h("p", null, h("span", { class: "pill" }, LEVEL[n.level])),
        h("p", { class: "dim" }, `${rank} of the same time of day over the last 90 days.`));
    }

    function forecastTile(f) {
      const id = `fc-${f.horizon_h}`;
      return h("section", { class: "tile", "aria-labelledby": id },
        h("h2", { id }, `Next ${f.horizon_h} trading hours`),
        h("p", { class: "figure" }, usd(f.expected), " ", h("small", null, "per hour expected")),
        h("p", { class: "dim" }, `Likely range ${usd(f.low)} to ${usd(f.high)}. The last ${f.horizon_h} hours averaged ${usd(f.last_period)} per hour, so this is ${Math.abs(f.change_pct).toFixed(0)}% ${f.change_pct >= 0 ? "higher" : "lower"}.`),
        h("div", null,
          h("p", { class: "dim", style: "margin-bottom:6px" }, `Chance it is more volatile than the last ${f.horizon_h} hours`),
          h("div", { class: "prob", role: "img", "aria-label": `${pc(f.prob_higher)} chance` }, h("i", { style: `width:${Math.round(f.prob_higher * 100)}%` })),
          h("p", { style: "margin-top:6px" }, h("strong", null, pc(f.prob_higher)), ` (${words(f.prob_higher)})`)));
    }

    function historySheet() {
      const host = h("div");
      ctx.track(window.Charts.lineChart(host, {
        points: V.history.t.map((t, i) => ({ t: Date.parse(t), v: { vol: V.history.value[i] } })),
        series: [{ key: "vol", label: "Per hour", cls: "vol", step: false }],
        height: 250, xStepHours: 24, gapMs: 3 * 3600e3,
        fmtValue: (v) => usd(v), fmtTick: (v) => `$${+v.toFixed(1)}`,
        fmtXTick: (d) => (d.getHours() === 0 ? ctx.dayFmt.format(d) : ctx.timeFmt.format(d)),
        fmtTipTitle: (d) => `${ctx.dayFmt.format(d)}, ${ctx.timeFmt.format(d)}`,
        ariaLabel: "Typical gold move per hour in dollars, one point per trading hour over the last week. Use the arrow keys to step through the values.",
      }));
      const rows = V.history.t.map((t, i) => ({ t, v: V.history.value[i] })).slice(-24).reverse();
      const tableNode = ctx.table({
        caption: "Typical move per hour, newest 24 trading hours",
        columns: [{ label: "Hour", cell: (r) => ctx.dayTime(r.t) }, { label: "Typical move per hour", num: true, cell: (r) => usd(r.v) }],
        rows,
      });
      return ctx.chartSheet({
        title: "Last week", sub: "One point per trading hour. Weekends and the daily break are skipped.", chartHost: host, tableNode,
        tableNote: "Newest 24 trading hours, newest first.", className: "span-12",
      });
    }

    const verdictPill = (v) => ({
      better: h("span", { class: "pill good" }, icon("check"), "Better than every simple guess"),
      mixed: h("span", { class: "pill mixed" }, icon("alert"), "Mixed: better on some measures"),
      "no better": h("span", { class: "pill bad" }, icon("alert"), "No better than simple guesses"),
    })[v];

    function scoreBlock(r) {
      const lowest = (vals) => Math.min(...vals.filter((x) => x !== null));
      const highest = (vals) => Math.max(...vals.filter((x) => x !== null));
      const cell = (val, best, fmt) => (val === null ? "—" : h("span", { class: val === best ? "best" : null }, fmt(val)));
      const size = [r.error_model_pct, r.error_tod_pct, r.error_persist_pct, r.error_avg90_pct, null];
      const call = [r.hit_rate, r.hit_rate_tod, null, null, r.base_rate];
      const brier = [r.brier_model, r.brier_tod, null, null, r.brier_base];
      const rowsDef = [
        { name: "Average size error (lower is better)", vals: size, best: lowest(size), fmt: pc1 },
        { name: "Called “more volatile or not” right (higher is better)", vals: call, best: highest(call), fmt: (v) => pc1(v * 100) },
        { name: "Probability score (lower is better)", vals: brier, best: lowest(brier), fmt: (v) => v.toFixed(3) },
      ];
      const t = ctx.table({
        caption: `Scorecard for the next ${r.horizon_h} trading hours`,
        columns: [
          { label: "Measure", cell: (x) => x.name },
          { label: "Model", num: true, cell: (x) => cell(x.vals[0], x.best, x.fmt) },
          { label: "Time of day only", num: true, cell: (x) => cell(x.vals[1], x.best, x.fmt) },
          { label: "Last period repeated", num: true, cell: (x) => cell(x.vals[2], x.best, x.fmt) },
          { label: "90-day average", num: true, cell: (x) => cell(x.vals[3], x.best, x.fmt) },
          { label: "Always the common answer", num: true, cell: (x) => cell(x.vals[4], x.best, x.fmt) },
        ],
        rows: rowsDef,
      });
      const rhythm = r.hit_rate - r.hit_rate_tod < 0.05;
      const sentence = rhythm
        ? `Most of the “more volatile or not” skill is the usual daily rhythm: the time of day alone gets ${pc(r.hit_rate_tod)} right against the model's ${pc(r.hit_rate)}. The model's gain is mainly in the size and the probabilities.`
        : `The model adds real information on top of the daily rhythm: ${pc(r.hit_rate)} right against ${pc(r.hit_rate_tod)} from the time of day alone.`;
      const cal = ctx.table({
        caption: `When the model said a chance, how often it happened (${r.horizon_h} hours)`,
        columns: [
          { label: "The model said", cell: (b) => b.label },
          { label: "Average chance said", num: true, cell: (b) => (b.said === null ? "—" : pc(b.said)) },
          { label: "How often it happened", num: true, cell: (b) => (b.happened === null ? "—" : pc(b.happened)) },
          { label: "Cases", num: true, cell: (b) => String(b.n) },
        ],
        rows: r.calibration,
      });
      return h("div", { class: "stack-lg", style: "padding-bottom:18px" },
        h("div", { class: "stack", style: "padding:0 16px" },
          h("h3", { style: "font-size:14px;font-weight:600" }, `Next ${r.horizon_h} trading hours, ${r.samples.toLocaleString("en-US")} forecasts`),
          h("p", null, verdictPill(r.verdict)), h("p", { class: "dim" }, sentence)),
        t, cal);
    }

    function scorecardSheet() {
      const sc = V.scorecard;
      return h("section", { class: "sheet span-12", "aria-labelledby": "sc-t" },
        h("div", { class: "sheet-head" }, h("h2", { id: "sc-t" }, "How good has this forecast been?"),
          h("p", { class: "sheet-sub" }, `Tested on past data it had not seen, ${dateFmt.format(new Date(sc.tested_from))} to ${dateFmt.format(new Date(sc.tested_to))}`)),
        h("div", { class: "stack-lg", style: "padding-top:14px" }, ...sc.rows.map(scoreBlock)),
        h("p", { class: "table-note", style: "padding-top:4px" }, sc.note),
        h("p", { class: "table-note" }, "“Time of day only” is the last period adjusted for the usual rhythm (quiet Asian hours, then London and New York). A forecast has to beat that to be worth anything."));
    }

    function eventsSheet() {
      const rows = V.events.map((e) => h("li", null,
        h("time", { datetime: e.time }, ctx.dayTime(e.time)),
        h("span", null, e.title),
        h("span", { class: "pill" }, `${e.impact[0].toUpperCase()}${e.impact.slice(1)} impact, ${e.currency}`)));
      return h("section", { class: "sheet span-12", "aria-labelledby": "ev-t" },
        h("div", { class: "sheet-head" }, h("h2", { id: "ev-t" }, "Scheduled news"),
          h("p", { class: "sheet-sub" }, "Sample items. The bot will send MT5's economic calendar.")),
        rows.length ? h("ul", { class: "events sheet-body flush" }, rows) : ctx.emptyBox("No calendar connected", "Scheduled news will appear here once the bot sends it."));
    }

    function render() {
      return h("div", null,
        ctx.pageHead("Volatility", "How big gold's moves are, and what the next day may bring."),
        h("div", { class: "callout", style: "margin-bottom:16px" },
          h("p", null, h("strong", null, "A probability, not a promise."), " This says how big the moves may be, not which way gold goes. It is worked out from the bot's own 1-minute candles, so it is not the VIX or CBOE's gold index (GVZ). Hours are trading hours: weekends and the daily break do not count.")),
        h("div", { class: "tiles" }, nowTile(), ...V.forecasts.map(forecastTile)),
        h("div", { class: "grid" }, historySheet(), scorecardSheet(), eventsSheet()));
    }

    return { render };
  };
})();
