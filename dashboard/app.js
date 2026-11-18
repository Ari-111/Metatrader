/* Bot Console mock-up: views, routing, theme.
   Data comes through loadOverview(). Today that returns the sample file; in step 2 this one
   function becomes a fetch of GET /v1/accounts/{id}/overview and nothing else needs to change. */
(function () {
  "use strict";
  const { h, icon } = window.DOM;

  // Opened from a file: sample data. Served by the Bot Console server (http): live data from the bot.
  const LIVE = location.protocol === "http:" || location.protocol === "https:";

  function loadOverview() {
    if (!LIVE) return Promise.resolve(window.SAMPLE_OVERVIEW);
    return fetch("/v1/overview", { credentials: "same-origin" }).then((r) => {
      if (r.status === 401) { location.href = "/login.html"; throw new Error("signed out"); }
      if (!r.ok) return r.json().then((j) => { throw new Error(typeof j.detail === "string" ? j.detail : "The server could not build the overview."); });
      return r.json();
    });
  }

  loadOverview().then(start).catch((err) => {
    document.getElementById("main").replaceChildren(
      h("div", { class: "empty" }, h("strong", null, LIVE ? "Waiting for the bot" : "The data could not be loaded"),
        LIVE ? `${err.message} This page retries by itself.` : "Check that data/sample-overview.js sits next to index.html."));
    if (LIVE) setTimeout(() => location.reload(), 5000);
    console.error(err);
  });

  /* Copy fresh data into the existing objects, so every screen that holds a reference sees the change. */
  function syncInto(target, src) {
    if (Array.isArray(src)) {
      target.length = src.length;
      src.forEach((v, i) => {
        if (v && typeof v === "object" && target[i] && typeof target[i] === "object" && Array.isArray(v) === Array.isArray(target[i])) syncInto(target[i], v);
        else target[i] = v;
      });
      return;
    }
    Object.keys(target).forEach((k) => { if (!(k in src)) delete target[k]; });
    Object.keys(src).forEach((k) => {
      const v = src[k];
      if (v && typeof v === "object" && target[k] && typeof target[k] === "object" && Array.isArray(v) === Array.isArray(target[k])) syncInto(target[k], v);
      else target[k] = v;
    });
  }

  function start(D) {
    /* ------------------------------------------------------------ formatting */
    const moneyFmt = new Intl.NumberFormat("en-US", { style: "currency", currency: D.account.currency });
    const priceFmt = new Intl.NumberFormat("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    const money = (v) => moneyFmt.format(v);
    const signed = (v) => (v < 0 ? "−" : "+") + moneyFmt.format(Math.abs(v));
    const price = (v) => priceFmt.format(v);
    const lots = (v) => v.toFixed(2);
    const pct = (v, digits = 0) => `${(v * 100).toFixed(digits)}%`;
    const net = (d) => d.profit + d.commission + d.swap;
    const sum = (list, fn) => list.reduce((a, x) => a + fn(x), 0);

    const timeZone = Intl.DateTimeFormat().resolvedOptions().timeZone;
    const timeFmt = new Intl.DateTimeFormat("en-GB", { hour: "2-digit", minute: "2-digit", hour12: false });
    const dayFmt = new Intl.DateTimeFormat("en-GB", { weekday: "short", day: "numeric", month: "short" });
    let serverNow = Date.parse(D.server_time);
    const hhmm = (iso) => timeFmt.format(new Date(iso));
    const sameDay = (a, b) => new Date(a).toDateString() === new Date(b).toDateString();
    const dayTime = (iso) => `${sameDay(iso, serverNow) ? "Today" : dayFmt.format(new Date(iso))}, ${hhmm(iso)}`;
    const duration = (fromMs, toMs) => {
      const m = Math.max(0, Math.round((toMs - fromMs) / 60000));
      return m < 60 ? `${m} min` : `${Math.floor(m / 60)} h ${String(m % 60).padStart(2, "0")} min`;
    };
    const heldSince = (iso) => duration(Date.parse(iso), serverNow);
    const heldBetween = (a, b) => duration(Date.parse(a), Date.parse(b));

    const REASON = {
      take_profit: "Target reached", stop_loss: "Stopped out", bot: "Closed by the bot",
      manual: "Closed by hand", stop_out: "Margin stop-out", other: "Other",
    };
    const STATE = {
      in_position: { label: "Trade open", icon: "dot", cls: "open" },
      idle: { label: "Waiting for a signal", icon: "ring", cls: "" },
      paused: { label: "Switched off", icon: "pause", cls: "off" },
      error: { label: "Error", icon: "alert", cls: "err" },
    };

    /* Strategies keep one colour slot for life, taken from their place in the library. */
    const S = {};
    D.strategies.forEach((st, i) => { S[st.id] = Object.assign({}, st, { slot: (i % 8) + 1 }); });

    /* -------------------------------------------------------------- bits */
    const plText = (v) => h("span", { class: v > 0 ? "pos" : v < 0 ? "neg" : null }, signed(v));
    const sideCell = (side) => h("span", { class: "side" }, icon(side === "buy" ? "up" : "down"), side === "buy" ? "Buy" : "Sell");
    const keyDot = (slot) => h("i", { class: "key-dot", "data-slot": slot });

    function stratLink(id) {
      if (!id) return h("span", { class: "dim" }, "Manual or other");
      return h("a", { class: "strategy-cell", href: `#/strategies/${id}` }, keyDot(S[id].slot), S[id].name);
    }

    function statePill(st) {
      const base = STATE[st.state];
      const label = st.state === "in_position" && !st.enabled ? "Closing out, no new trades" : base.label;
      return h("span", { class: `pill ${base.cls}` }, icon(base.icon), label);
    }

    function pageHead(title, sub) {
      return h("div", { class: "page-head" }, h("h1", null, title), sub ? h("p", null, sub) : null);
    }

    function table({ caption, columns, rows }) {
      const head = h("tr", null, columns.map((c) => h("th", { scope: "col", class: c.num ? "num" : null }, c.label)));
      const body = rows.map((r) => h("tr", null, columns.map((c) => h("td", { class: c.num ? "num" : null }, c.cell(r)))));
      const hasFoot = columns.some((c) => c.foot);
      const foot = hasFoot
        ? h("tfoot", null, h("tr", null, columns.map((c, i) =>
          h("td", { class: c.num ? "num" : null }, c.foot ? c.foot(rows) : i === 0 ? "Total" : ""))))
        : null;
      return h("div", { class: "scroll", tabindex: 0, role: "region", "aria-label": caption },
        h("table", { class: "tbl" }, h("caption", { class: "sr-only" }, caption), h("thead", null, head), h("tbody", null, body), foot));
    }

    function emptyBox(title, text) {
      return h("div", { class: "empty" }, h("strong", null, title), text);
    }

    const charts = [];
    const track = (c) => { charts.push(c); return c; };

    /* A sheet that holds a chart and can swap it for an equivalent table. */
    function chartSheet({ title, sub, legend, chartHost, tableNode, tableNote, footer, className }) {
      const tableHost = h("div", { hidden: true }, tableNode, tableNote ? h("p", { class: "table-note" }, tableNote) : null);
      const btn = h("button", { class: "btn", type: "button", "aria-pressed": "false" }, "View as table");
      btn.addEventListener("click", () => {
        const on = btn.getAttribute("aria-pressed") !== "true";
        btn.setAttribute("aria-pressed", String(on));
        btn.textContent = on ? "View as chart" : "View as table";
        chartHost.hidden = on;
        tableHost.hidden = !on;
      });
      return h("section", { class: `sheet ${className || ""}`, "aria-label": title },
        h("div", { class: "sheet-head" },
          h("div", null, h("h2", null, title), sub ? h("p", { class: "sheet-sub" }, sub) : null),
          btn),
        legend ? h("div", { class: "sheet-body", style: "padding-bottom:0" }, legend) : null,
        h("div", { class: "sheet-body" }, chartHost, tableHost),
        footer ? h("div", { class: "sheet-body", style: "padding-top:0" }, footer) : null);
    }

    /* ------------------------------------------------------- status band */
    function renderBand() {
      const b = D.bot;
      const age = Math.max(0, Math.round((serverNow - Date.parse(b.last_report_at)) / 1000));
      const ageText = age < 60 ? `${age} s ago` : `${Math.floor(age / 60)} min ago`;
      const state = {
        online: { icon: "check", text: "Bot is reporting" },
        stale: { icon: "alert", text: "Reports are delayed" },
        offline: { icon: "cross", text: "Bot has gone silent" },
      }[b.status];
      const arrived = b.heartbeat.filter((x) => x.ok).length;
      const minutes = Math.round((b.heartbeat.length * b.report_interval_s) / 60);
      const upToDate = b.version === b.latest_version;
      const caption = `${arrived} of ${b.heartbeat.length} reports arrived in the last ${minutes} minutes`;
      const ticks = b.heartbeat.map((slot) =>
        h("i", { class: slot.ok ? null : "miss", title: `${new Date(slot.t).toLocaleTimeString("en-GB")}: ${slot.ok ? "report received" : "no report"}` }));

      return h("div", { class: "band", role: "status" },
        h("div", { class: `band-state ${b.status}` }, b.status === "online" ? h("span", { class: "pulse", "aria-hidden": "true" }) : icon(state.icon), state.text),
        h("p", { class: "band-item" }, "Last report ", h("strong", null, ageText)),
        h("p", { class: "band-item" }, "Bot version ", h("strong", null, b.version), upToDate ? " (up to date)" : ` (${b.latest_version} is available)`),
        h("div", { class: "hb-group" },
          h("div", { class: "hb", role: "img", "aria-label": caption }, ticks),
          h("p", { class: "hb-caption" }, caption)));
    }

    /* --------------------------------------------------------- overview */
    function fact(label, value) {
      return h("div", null, h("dt", null, label), h("dd", null, value));
    }

    function openColumns(withStrategy) {
      const cols = [];
      if (withStrategy) cols.push({ label: "Strategy", cell: (p) => stratLink(p.strategy_id) });
      // On a strategy's own page the symbol sits in the page heading, so the table drops it.
      if (withStrategy) cols.push({ label: "Symbol", cell: (p) => p.symbol });
      cols.push(
        { label: "Side", cell: (p) => sideCell(p.side) },
        { label: "Lots", num: true, cell: (p) => lots(p.volume), foot: (rows) => lots(sum(rows, (p) => p.volume)) },
        { label: "Opened", cell: (p) => hhmm(p.open_time) },
        { label: "Held", cell: (p) => heldSince(p.open_time) },
        { label: "Entry", num: true, cell: (p) => price(p.open_price) },
        { label: "Now", num: true, cell: (p) => price(p.current_price) },
        { label: "Stop loss", num: true, cell: (p) => (p.sl === null ? "none" : price(p.sl)) },
        { label: "Target", num: true, cell: (p) => (p.tp === null ? "none" : price(p.tp)) },
        { label: "Profit so far", num: true, cell: (p) => plText(p.profit + p.swap + p.commission), foot: (rows) => plText(sum(rows, (p) => p.profit + p.swap + p.commission)) },
      );
      if (!withStrategy) cols[0].foot = () => "Total";
      return cols;
    }

    function openTradesTable(positions, withStrategy) {
      return table({ caption: "Open trades", columns: openColumns(withStrategy), rows: positions });
    }

    function signalRow(sg) {
      const st = S[sg.strategy_id];
      let pill;
      if (sg.kind === "entry") pill = h("span", { class: "pill open" }, icon(sg.side === "buy" ? "up" : "down"), sg.side === "buy" ? "Opened a buy" : "Opened a sell");
      else if (sg.kind === "exit") pill = h("span", { class: "pill" }, icon("ring"), "Closed a trade");
      else pill = h("span", { class: "pill skipped" }, "Skipped");
      return h("li", null,
        h("time", { datetime: sg.time }, hhmm(sg.time)),
        h("div", { class: "feed-who" }, keyDot(st.slot), h("a", { href: `#/strategies/${st.id}` }, st.name)),
        pill,
        h("p", { class: "feed-why" }, sg.reason));
    }

    function viewOverview() {
      const snap = D.snapshot;
      const delta = snap.equity - D.day_start.equity;
      const deltaPct = (delta / D.day_start.equity) * 100;
      const up = delta >= 0;

      const hero = h("section", { class: "hero span-4", "aria-labelledby": "hero-label" },
        h("h2", { id: "hero-label", class: "hero-label" }, "Equity"),
        h("p", { class: "hero-figure" }, money(snap.equity)),
        h("p", { class: `hero-delta ${up ? "pos" : "neg"}` }, icon(up ? "up" : "down"),
          `${signed(delta)} (${up ? "+" : "−"}${Math.abs(deltaPct).toFixed(2)}%) since the start of the day`),
        h("dl", { class: "facts" },
          fact("Balance", money(snap.balance)),
          fact("Floating profit", plText(snap.floating_pl)),
          fact("Margin in use", money(snap.margin)),
          fact("Free margin", money(snap.free_margin)),
          fact("Margin level", snap.margin_level === null ? "none in use" : `${snap.margin_level.toLocaleString("en-US", { maximumFractionDigits: 1 })}%`)));

      // Balance and equity, last 24 hours.
      const series = D.equity_series;
      const chartHost = h("div");
      track(window.Charts.lineChart(chartHost, {
        points: series.map((p) => ({ t: Date.parse(p.t), v: { equity: p.equity, balance: p.balance } })),
        series: [
          { key: "equity", label: "Equity", cls: "eq", step: false },
          { key: "balance", label: "Balance", cls: "bal", step: true },
        ],
        height: 290,
        fmtValue: money,
        fmtTick: (v) => `$${v.toLocaleString("en-US")}`,
        fmtXTick: (d) => (d.getHours() === 0 ? dayFmt.format(d) : timeFmt.format(d)),
        fmtTipTitle: (d) => `${dayFmt.format(d)}, ${timeFmt.format(d)}`,
        extraRows: (p) => [{ name: "Floating profit", value: signed(p.v.equity - p.v.balance) }],
        ariaLabel: `Balance and equity over the last 24 hours. Equity ${money(snap.equity)}, balance ${money(snap.balance)}. Use the arrow keys to step through the values.`,
      }));
      const hourly = series.filter((_, i) => i % 12 === 0 || i === series.length - 1);
      const equityTable = table({
        caption: "Balance and equity, hourly values",
        columns: [
          { label: "Time", cell: (p) => dayTime(p.t) },
          { label: "Equity", num: true, cell: (p) => money(p.equity) },
          { label: "Balance", num: true, cell: (p) => money(p.balance) },
          { label: "Floating profit", num: true, cell: (p) => plText(p.equity - p.balance) },
        ],
        rows: hourly,
      });
      const legend = h("ul", { class: "legend" },
        h("li", null, h("i", { class: "line-key eq" }), "Equity (balance plus open trades)"),
        h("li", null, h("i", { class: "line-key bal" }), "Balance (closed trades only)"));
      const chart = chartSheet({
        title: "Balance and equity", sub: "Last 24 hours", legend, chartHost, tableNode: equityTable,
        tableNote: "Hourly values. The chart has a point every 5 minutes.", className: "span-8",
      });

      // Open trades.
      const open = D.open_positions;
      const openSheet = h("section", { class: "sheet span-12", "aria-labelledby": "open-title" },
        h("div", { class: "sheet-head" },
          h("h2", { id: "open-title" }, `Open trades (${open.length})`),
          h("p", { class: "sheet-sub" }, "Floating profit ", plText(sum(open, (p) => p.profit + p.swap + p.commission)))),
        h("div", { class: "sheet-body flush" },
          open.length ? openTradesTable(open, true) : emptyBox("No open trades", "The bot is waiting for a signal.")));

      // Closed profit today by strategy.
      const barHost = h("div");
      const barRows = D.strategies.map((st) => ({
        id: st.id, label: st.name, value: st.today.net_profit, slot: S[st.id].slot, valueText: signed(st.today.net_profit),
        aria: `${st.name}: ${signed(st.today.net_profit)} from ${st.today.trades} closed trades today`,
        detail: [
          { name: "Net profit today", value: signed(st.today.net_profit) },
          { name: "Closed trades", value: String(st.today.trades) },
          { name: "Won", value: `${st.today.wins} of ${st.today.trades}` },
        ],
      }));
      track(window.Charts.barChart(barHost, { rows: barRows, ariaLabel: "Closed profit today by strategy" }));
      const barTable = table({
        caption: "Closed profit today by strategy",
        columns: [
          { label: "Strategy", cell: (st) => stratLink(st.id) },
          { label: "Closed trades", num: true, cell: (st) => String(st.today.trades) },
          { label: "Won", num: true, cell: (st) => String(st.today.wins) },
          { label: "Net profit", num: true, cell: (st) => plText(st.today.net_profit), foot: (rows) => plText(sum(rows, (st) => st.today.net_profit)) },
        ],
        rows: D.strategies,
      });
      const todayTrades = sum(D.strategies, (st) => st.today.trades);
      const todayWins = sum(D.strategies, (st) => st.today.wins);
      const todayNet = sum(D.strategies, (st) => st.today.net_profit);
      const barFooter = h("dl", { class: "facts", style: "margin-top:8px" },
        fact("Closed trades today", String(todayTrades)),
        fact("Won", todayTrades ? `${todayWins} of ${todayTrades} (${pct(todayWins / todayTrades)})` : "none yet"),
        fact("Net result of closed trades", plText(todayNet)));
      const bars = chartSheet({
        title: "Closed profit today", sub: "By strategy. Open trades are not included.", chartHost: barHost, tableNode: barTable,
        footer: barFooter, className: "span-5",
      });

      // Signals.
      const signals = h("section", { class: "sheet span-7", "aria-labelledby": "sig-title" },
        h("div", { class: "sheet-head" },
          h("h2", { id: "sig-title" }, "Latest signals"),
          h("p", { class: "sheet-sub" }, "Including the ones the bot skipped, and why")),
        h("ul", { class: "feed sheet-body flush" }, D.recent_signals.slice(0, 7).map(signalRow)));

      return h("div", null,
        pageHead("Overview", "A demo account trading gold with three strategies."),
        h("div", { class: "grid" }, hero, chart, openSheet, bars, signals));
    }

    /* ----------------------------------------------------------- trades */
    const tradesState = { tab: "open", strategy: "all", limit: 20 };

    function viewTrades() {
      const root = h("div");
      const content = h("div");
      let focusId = null;

      function strategyFilter(list) {
        return tradesState.strategy === "all" ? list : list.filter((x) => x.strategy_id === tradesState.strategy);
      }

      function paint() {
        const open = strategyFilter(D.open_positions);
        const closed = strategyFilter(D.recent_deals);

        const tabBtn = (id, label) => h("button", {
          type: "button", id: `tab-${id}`, "aria-pressed": String(tradesState.tab === id),
          onclick: () => { tradesState.tab = id; tradesState.limit = 20; focusId = `tab-${id}`; paint(); },
        }, label);
        const select = h("select", {
          id: "strategy-filter",
          onchange: (e) => { tradesState.strategy = e.target.value; tradesState.limit = 20; focusId = "strategy-filter"; paint(); },
        }, h("option", { value: "all" }, "All strategies"),
          D.strategies.map((st) => h("option", Object.assign({ value: st.id }, tradesState.strategy === st.id ? { selected: true } : {}), st.name)));

        const toolbar = h("div", { class: "toolbar" },
          h("div", { class: "seg", role: "group", "aria-label": "Trade list" },
            tabBtn("open", `Open (${open.length})`), tabBtn("history", `Closed (${closed.length})`)),
          h("label", { class: "field", for: "strategy-filter" }, "Show", select));

        let body;
        if (tradesState.tab === "open") {
          body = [
            h("p", { class: "summary-line" }, h("strong", null, `${open.length} open ${open.length === 1 ? "trade" : "trades"}`),
              ", floating profit ", plText(sum(open, (p) => p.profit + p.swap + p.commission))),
            h("section", { class: "sheet", "aria-label": "Open trades" },
              h("div", { class: "sheet-body flush" }, open.length ? openTradesTable(open, true) : emptyBox("No open trades", "Nothing is open for this selection."))),
          ];
        } else {
          const wins = closed.filter((d) => net(d) > 0).length;
          const shown = closed.slice(0, tradesState.limit);
          const cols = [
            { label: "Closed", cell: (d) => dayTime(d.close_time) },
            { label: "Strategy", cell: (d) => stratLink(d.strategy_id) },
            { label: "Side", cell: (d) => sideCell(d.side) },
            { label: "Lots", num: true, cell: (d) => lots(d.volume) },
            { label: "Entry", num: true, cell: (d) => price(d.open_price) },
            { label: "Exit", num: true, cell: (d) => price(d.close_price) },
            { label: "How it ended", cell: (d) => REASON[d.close_reason] },
            { label: "Held", cell: (d) => heldBetween(d.open_time, d.close_time) },
            { label: "Net result", num: true, cell: (d) => plText(net(d)) },
          ];
          body = [
            h("p", { class: "summary-line" }, h("strong", null, `${closed.length} closed ${closed.length === 1 ? "trade" : "trades"}`),
              closed.length ? [`, ${wins} won (${pct(wins / closed.length)}), net result `, plText(sum(closed, net))] : null),
            h("section", { class: "sheet", "aria-label": "Closed trades" },
              h("div", { class: "sheet-body flush" },
                closed.length ? table({ caption: "Closed trades, newest first", columns: cols, rows: shown }) : emptyBox("No closed trades", "Nothing has closed for this selection.")),
              closed.length > shown.length
                ? h("div", { class: "more" }, h("button", {
                  class: "btn", type: "button",
                  onclick: () => { tradesState.limit += 20; focusId = "more-btn"; paint(); }, id: "more-btn",
                }, `Show ${Math.min(20, closed.length - shown.length)} more`))
                : null,
              h("p", { class: "table-note", style: "padding-top:10px" }, `The ${D.recent_deals.length} most recent closed trades are loaded in this mock-up. Full history comes in a later step.`)),
          ];
        }
        content.replaceChildren(toolbar, ...body);
        if (focusId) { const el = document.getElementById(focusId); if (el) el.focus({ preventScroll: true }); focusId = null; }
      }

      root.append(pageHead("Trades", "Everything open now, and what has closed recently."), content);
      paint();
      return root;
    }

    /* ------------------------------------------------------- strategies */
    function viewStrategies(selectedId) {
      const current = S[selectedId] || S[D.strategies[0].id];
      const cards = h("div", { class: "cards" }, D.strategies.map((base) => {
        const st = S[base.id];
        const winRate = st.total.trades ? pct(st.total.wins / st.total.trades) : "none yet";
        return h("a", { class: "card", href: `#/strategies/${st.id}`, "aria-current": st.id === current.id ? "true" : null },
          h("div", { class: "card-top" },
            h("div", { class: "card-name" }, keyDot(st.slot), h("span", null, st.name, " ", h("span", { class: "card-ver" }, `v${st.version}`))),
          ),
          statePill(st),
          h("dl", { class: "card-stats" },
            h("div", null, h("dt", null, "Closed today"), h("dd", null, plText(st.today.net_profit))),
            h("div", null, h("dt", null, "All time"), h("dd", null, plText(st.total.net_profit))),
            h("div", null, h("dt", null, "Win rate"), h("dd", null, winRate)),
            h("div", null, h("dt", null, "Open trades"), h("dd", null, String(st.open_count)))));
      }));

      const positions = D.open_positions.filter((p) => p.strategy_id === current.id);
      const deals = D.recent_deals.filter((d) => d.strategy_id === current.id).slice(0, 8);

      const settings = h("section", { class: "sheet", "aria-labelledby": "set-title" },
        h("div", { class: "sheet-head" }, h("h2", { id: "set-title" }, "Settings"), h("p", { class: "sheet-sub" }, `Revision ${current.settings_rev}`)),
        h("dl", { class: "settings sheet-body" }, current.settings.map((x) =>
          h("div", null, h("dt", null, x.label),
            h("dd", null, x.editable ? null : h("span", { class: "lock", title: "A fixed part of the strategy; it cannot be changed from the dashboard" }, icon("lock"), " "), fmtSetting(x))))));

      const isSma = current.id === "sma_cross";
      const enabledNow = isSma ? sim.auto : current.enabled;
      const control = h("section", { class: "sheet", "aria-labelledby": "ctl-title" },
        h("div", { class: "sheet-head" }, h("h2", { id: "ctl-title" }, "Trading")),
        h("div", { class: "sheet-body" },
          h("div", { class: "switch-row" },
            h("button", { class: "switch", type: "button", role: "switch", "aria-checked": String(enabledNow), disabled: true, "aria-label": `${current.name} is ${enabledNow ? "on" : "off"}` }),
            h("strong", null, enabledNow ? "On" : "Off"),
            statePill(Object.assign({}, current, { enabled: enabledNow }))),
          h("p", { class: "dim", style: "margin-top:10px" },
            enabledNow
              ? "Opens new trades when its rules are met."
              : "Opens no new trades. Anything already open is still managed."),
          isSma
            ? h("p", { class: "dim", style: "margin-top:6px" }, "Switch it on or off from the ", h("a", { href: "#/trade" }, "Trade screen"), " (simulated in this mock-up).")
            : h("p", { class: "dim", style: "margin-top:6px" }, "Controls for the other strategies come in a later step.")));

      const openSheet = h("section", { class: "sheet", "aria-labelledby": "so-title" },
        h("div", { class: "sheet-head" }, h("h2", { id: "so-title" }, `Open trades (${positions.length})`)),
        h("div", { class: "sheet-body flush" }, positions.length ? openTradesTable(positions, false) : emptyBox("No open trades", `${current.name} has nothing open right now.`)));

      const closedCols = [
        { label: "Closed", cell: (d) => dayTime(d.close_time) },
        { label: "Side", cell: (d) => sideCell(d.side) },
        { label: "Lots", num: true, cell: (d) => lots(d.volume) },
        { label: "How it ended", cell: (d) => REASON[d.close_reason] },
        { label: "Net result", num: true, cell: (d) => plText(net(d)) },
      ];
      const closedSheet = h("section", { class: "sheet", "aria-labelledby": "sc-title" },
        h("div", { class: "sheet-head" }, h("h2", { id: "sc-title" }, "Latest closed trades")),
        h("div", { class: "sheet-body flush" }, deals.length ? table({ caption: `Latest closed trades for ${current.name}`, columns: closedCols, rows: deals }) : emptyBox("No closed trades yet", "")));

      return h("div", null,
        pageHead("Strategies", "Each strategy keeps its own results and settings."),
        cards,
        h("div", { class: "page-head" }, h("h2", { style: "font-size:17px;font-weight:600;display:flex;align-items:center;gap:9px" }, keyDot(current.slot), current.name),
          h("p", null, `${current.symbols.join(", ")}, magic number ${current.magic}`)),
        h("div", { class: "detail-grid" },
          h("div", { class: "span-4", style: "display:grid;gap:16px" }, control, settings),
          h("div", { class: "span-8", style: "display:grid;gap:16px;min-width:0" }, openSheet, closedSheet)));
  }

    /* ------------------------------------------------ simulated controls (mock-up only)
       Nothing here talks to a server or a broker. Pressing a control creates a command that walks through
       queued, sent and then applied (or expired / failed, chosen with the mock-up switch on the Trade
       screen). That is the lifecycle the contract describes, so the screens show what a person would see. */
    let loadedAt = Date.now();
    const mockNow = () => serverNow + (Date.now() - loadedAt);
    const sma = D.strategies.find((x) => x.id === "sma_cross");
    const smaVal = (k) => sma.settings.find((x) => x.key === k).value;
    const isoNoMs = (ms) => new Date(ms).toISOString().replace(/\.\d+Z$/, "Z");
    const sim = {
      mode: "normal", // normal | offline | refused
      commands: D.recent_commands.map((c) => Object.assign({}, c)),
      auto: sma.enabled,
      settings: {
        next_lot: smaVal("next_lot"), max_lot: smaVal("max_lot"), take_profit_pips: smaVal("take_profit_pips"),
        stop_loss_pips: smaVal("stop_loss_pips"), near_lines_pips: smaVal("near_lines_pips"),
      },
      levels: {}, // position_id -> { sl, tp } once a level change was applied
      closed: null, // { position_id, price, net } once a close was applied
      alerts: {
        events: Object.fromEntries(D.alerts.events.map((e) => [e.id, e.enabled])),
        channels: Object.fromEntries(D.alerts.channels.map((c) => [c.id, c.enabled])),
      },
      seq: 0,
      // scope names the strategy a command is for, so a change to one strategy never shows up on another's card
      pending(type, scope) { return this.commands.find((c) => c.type === type && (!scope || c.scope === scope) && (c.status === "queued" || c.status === "sent")) || null; },
    };
    // The sample already holds one command on its way to the bot; let it finish a few seconds after the page opens.
    if (!LIVE) sim.commands.filter((c) => c.status === "queued" || c.status === "sent").forEach((c) => setTimeout(() => { c.status = "applied"; refresh(); }, 5000));

    // Live: the same `sim` object is filled from what the bot really reported, so the screens need no second code path.
    const localRejects = []; // "Rejected" answers from the server, kept for a minute because they never reach the bot
    function syncSim() {
      if (!LIVE) return;
      const sm = D.strategies.find((x) => x.id === "sma_cross");
      sim.auto = sm.enabled && !D.bot.trading_paused;
      sim.settings = Object.fromEntries(sm.settings.map((x) => [x.key, x.value]));
      sim.closed = null;
      sim.levels = {};
      const fresh = localRejects.filter((c) => Date.now() - c.at < 60000);
      sim.commands = [...fresh, ...D.recent_commands.map((c) => Object.assign({ scope: "sma_cross" }, c))];
    }
    syncSim();

    function updateNote() {
      const note = document.querySelector(".sample-note");
      if (!LIVE || !note) return;
      const blocks = D.sample_blocks || [];
      note.textContent = `Live: connected to the bot on ${D.account.server} (${D.account.mode} account ${D.account.login}).`
        + (blocks.length ? ` Still sample data: ${blocks.join(", ")}.` : "");
    }
    updateNote();

    function poll() {
      fetch("/v1/overview", { credentials: "same-origin" }).then((r) => {
        if (r.status === 401) { location.href = "/login.html"; return null; }
        return r.ok ? r.json() : null;
      }).then((nd) => {
        if (!nd) return;
        syncInto(D, nd);
        serverNow = Date.parse(D.server_time);
        loadedAt = Date.now();
        D.strategies.forEach((st, i) => { S[st.id] = Object.assign({}, st, { slot: (i % 8) + 1 }); });
        syncSim();
        updateNote();
        document.getElementById("band").replaceChildren(renderBand());
        refresh();
      }).catch(() => { /* the server is restarting or the network blinked: try again next time */ });
    }
    if (LIVE) setInterval(poll, 5000);

    const live = h("div", { class: "sr-only", role: "status", "aria-live": "polite" });
    document.body.append(live);
    const announce = (text) => { live.textContent = ""; setTimeout(() => { live.textContent = text; }, 40); };

    let refreshTimer = null;
    function refresh() {
      const el = document.activeElement;
      if (el && el.tagName === "INPUT" && document.getElementById("main").contains(el)) {
        clearTimeout(refreshTimer); // do not wipe a field while someone is typing in it
        refreshTimer = setTimeout(refresh, 700);
        return;
      }
      render(false);
    }

    function sendLive({ type, summary, payload, scope }) {
      const body = { schema_version: "0.2", client_request_id: `web-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`, type, payload };
      announce(`${summary}: sent to the server.`);
      fetch("/v1/accounts/1/commands", { method: "POST", credentials: "same-origin", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) })
        .then((r) => (r.status === 401 ? (location.href = "/login.html", null) : r.json()))
        .then((rep) => {
          if (rep && rep.status === "rejected") {
            localRejects.unshift({ command_id: `local-${Date.now()}`, type, summary, scope, issued_at: isoNoMs(Date.now()), expires_at: isoNoMs(Date.now()), status: "rejected", reason: rep.reason, at: Date.now() });
            announce(`${summary}: rejected. ${rep.reason}`);
          }
          poll();
        })
        .catch(() => announce(`${summary}: could not reach the server.`));
    }

    function send({ type, summary, apply, scope, payload }) {
      if (LIVE) return sendLive({ type, summary, payload, scope });
      const t0 = mockNow();
      const cmd = {
        command_id: `cmd-sim${String(++sim.seq).padStart(6, "0")}`, type, summary, scope, issued_at: isoNoMs(t0),
        expires_at: isoNoMs(t0 + 120000), status: "queued", reason: null,
      };
      sim.commands.unshift(cmd);
      const later = (ms, fn) => setTimeout(() => { fn(); refresh(); }, ms);
      if (sim.mode === "offline") {
        later(6000, () => {
          cmd.status = "expired";
          cmd.reason = "The bot did not collect it within 2 minutes, so nothing happened. (The mock-up shortens the wait.)";
          announce(`${summary}: expired. Nothing happened.`);
        });
      } else if (sim.mode === "refused") {
        later(1200, () => { cmd.status = "sent"; });
        later(5200, () => {
          cmd.status = "failed";
          cmd.reason = "The broker refused it: market closed. The bot kept retrying until the command expired.";
          announce(`${summary}: failed. The broker refused it.`);
        });
      } else {
        later(1000, () => { cmd.status = "sent"; });
        later(2600, () => { apply(); cmd.status = "applied"; announce(`${summary}: done.`); });
      }
      announce(`${summary}: sent to the server.`);
      refresh();
      return cmd;
    }

    function fmtSetting(x) {
      if (typeof x.value === "boolean") return x.value ? "On" : "Off";
      if (x.key.startsWith("hours_")) return `${String(Math.floor(x.value / 60)).padStart(2, "0")}:${String(x.value % 60).padStart(2, "0")} IST`;
      if (x.key === "near_lines_pips" && x.value === 0) return "Off";
      if (typeof x.value === "number") return /lot/.test(x.key) ? `${x.value.toFixed(2)} lots` : `${x.value}${x.unit ? ` ${x.unit}` : ""}`;
      return `${x.value}${x.unit ? ` ${x.unit}` : ""}`;
    }

    const ctx = {
      D, h, icon, S, money, signed, price, lots, pct, hhmm, dayTime, dayFmt, timeFmt, serverNow, mockNow, sum, plText, sideCell,
      keyDot, stratLink, statePill, pageHead, table, emptyBox, chartSheet, track, fact, signalRow, sim, send, refresh, announce,
      fmtSetting, REASON, LIVE, CONTRACT_SIZE: 100, PIP: 0.1, focus: { id: null },
    };
    const extra = {};
    Object.entries(window.Views || {}).forEach(([name, factory]) => { extra[name] = factory(ctx); });

    /* -------------------------------------------------------- shell/rail */
    const ROUTES = {
      overview: viewOverview, trade: extra.trade.render, chart: extra.chart.render, volatility: extra.volatility.render,
      trades: viewTrades, strategies: viewStrategies, alerts: extra.alerts.render,
    };
    const TITLES = { overview: "Overview", trade: "Trade", chart: "Chart", volatility: "Volatility", trades: "Trades", strategies: "Strategies", alerts: "Alerts" };
    const ORDER = ["overview", "trade", "chart", "volatility", "trades", "strategies", "alerts"];
    const html = document.documentElement;
    const media = window.matchMedia("(prefers-color-scheme: dark)");
    try { const saved = localStorage.getItem("botconsole-theme"); if (saved === "light" || saved === "dark") html.dataset.theme = saved; } catch (e) { /* storage blocked */ }
    const isDark = () => (html.dataset.theme ? html.dataset.theme === "dark" : media.matches);

    const themeBtn = h("button", { class: "btn", type: "button" });
    const syncThemeBtn = () => { themeBtn.textContent = isDark() ? "Light mode" : "Dark mode"; };
    themeBtn.addEventListener("click", () => {
      const next = isDark() ? "light" : "dark";
      html.dataset.theme = next;
      try { localStorage.setItem("botconsole-theme", next); } catch (e) { /* storage blocked */ }
      syncThemeBtn();
    });
    media.addEventListener("change", syncThemeBtn);
    syncThemeBtn();

    const kind = { demo: "Demo account", real: "Real account", contest: "Contest account" }[D.account.mode];
    const navLinks = ORDER.map((view) => {
      const badge = view === "trades" ? h("span", { class: "badge", "aria-label": `${D.open_positions.length} open` }, String(D.open_positions.length)) : null;
      return h("a", { href: `#/${view}`, "data-view": view }, TITLES[view], badge);
    });

    document.getElementById("rail").replaceChildren(
      h("p", { class: "brand" }, "Bot Console"),
      h("div", { class: "account" },
        h("p", { class: "account-kind" }, kind),
        h("p", { class: "account-login" }, String(D.account.login)),
        h("p", { class: "account-meta" }, D.account.server),
        h("p", { class: "account-meta" }, `${D.account.margin_mode === "hedging" ? "Hedging" : "Netting"}, leverage 1:${D.account.leverage}`)),
      h("nav", { class: "nav", "aria-label": "Main" }, navLinks),
      h("div", { class: "rail-foot" }, themeBtn, h("p", { class: "tz" }, `Times are shown in ${timeZone.replace(/_/g, " ")}`)));

    document.getElementById("band").replaceChildren(renderBand());

    function parseHash() {
      const parts = location.hash.replace(/^#\/?/, "").split("/");
      return { view: ROUTES[parts[0]] ? parts[0] : "overview", id: parts[1] };
    }

    const main = document.getElementById("main");
    function render(moved) {
      charts.splice(0).forEach((c) => c.destroy());
      const { view, id } = parseHash();
      main.replaceChildren(ROUTES[view](id));
      navLinks.forEach((a) => {
        if (a.dataset.view === view) a.setAttribute("aria-current", "page");
        else a.removeAttribute("aria-current");
      });
      document.title = `${TITLES[view]} - Bot Console`;
      if (moved) { window.scrollTo(0, 0); main.focus({ preventScroll: true }); }
      if (ctx.focus.id) { // a control that was pressed keeps focus after the screen redraws
        const el = document.getElementById(ctx.focus.id);
        if (el) el.focus({ preventScroll: true });
        ctx.focus.id = null;
      }
    }

    window.addEventListener("hashchange", () => render(true));
    render(false);
  }
})();
