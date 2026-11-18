/* Trade screen: the controls for the SMA 100/5000 strategy.
   Everything on it is simulated in this mock-up: a press creates a command that walks through
   queued, sent and applied (or expired / failed) exactly as docs/data-contract.md describes.
   The rules shown here come from docs/sma-cross-spec.md. */
(function () {
  "use strict";
  window.Views = window.Views || {};

  window.Views.trade = function (ctx) {
    const { D, h, icon, sim } = ctx;
    const sma = D.strategies.find((s) => s.id === "sma_cross");
    const spec = (k) => sma.settings.find((x) => x.key === k);
    const dollars = (dist, volume) => dist * volume * ctx.CONTRACT_SIZE;
    const num = (str) => (String(str).trim() === "" ? NaN : Number(String(str).trim().replace(",", ".")));
    const fixed2 = (v) => v.toFixed(2);
    const typed = (v) => String(+v.toFixed(3)); // what the person typed, not rounded to 2 places

    // What the person has typed but not saved. It survives the screen redrawing while a command is in flight.
    const draft = { lot: null, tp: null, sl: null, maxLot: null, tpPrice: null, slPrice: null, panel: null };
    const errors = { lot: null, tp: null, sl: null, maxLot: null, tpPrice: null, slPrice: null };

    /* ------------------------------------------------------------ rules (same ones the bot applies) */
    function checkLot(v, max) {
      const sp = spec("next_lot");
      if (!Number.isFinite(v)) return "Enter a lot size, for example 0.01.";
      if (v < sp.min - 1e-9) return `Lot ${typed(v)} is below the smallest allowed (${fixed2(sp.min)}).`;
      if (v > max + 1e-9) return `Lot ${typed(v)} is above the largest lot allowed (${fixed2(max)}).`;
      const n = (v - sp.min) / sp.step;
      if (Math.abs(n - Math.round(n)) > 1e-6) return `Lots move in steps of ${fixed2(sp.step)}.`;
      return null;
    }
    function checkPips(key, label, v) {
      const sp = spec(key);
      if (!Number.isFinite(v) || !Number.isInteger(v)) return `Enter a whole number of pips for the ${label}.`;
      if (v < sp.min) return `The ${label} must be at least ${sp.min} pips.`;
      if (v > sp.max) return `The ${label} can be at most ${sp.max} pips.`;
      if ((v - sp.min) % sp.step !== 0) return `The ${label} moves in steps of ${sp.step} pips.`;
      return null;
    }
    function checkMaxLot(v) {
      const sp = spec("max_lot");
      if (!Number.isFinite(v)) return "Enter a lot size, for example 0.10.";
      if (v < sp.min - 1e-9 || v > sp.max + 1e-9) return `The largest lot must be between ${fixed2(sp.min)} and ${fixed2(sp.max)}.`;
      const n = (v - sp.min) / sp.step;
      if (Math.abs(n - Math.round(n)) > 1e-6) return `Lots move in steps of ${fixed2(sp.step)}.`;
      if (v < sim.settings.next_lot - 1e-9) return `The largest lot cannot be below the next trade lot (${fixed2(sim.settings.next_lot)}).`;
      return null;
    }

    /* ------------------------------------------------------------------ small pieces */
    const card = (cls, id, title, sub, ...body) => h("section", { class: `sheet ${cls}`, "aria-labelledby": id },
      h("div", { class: "sheet-head" }, h("h2", { id }, title), sub ? h("p", { class: "sheet-sub" }, sub) : null),
      h("div", { class: "sheet-body" }, ...body));

    function errorLine(id, text) {
      return h("p", { class: "error", id, role: "alert", hidden: !text }, icon("alert"), h("span", null, text || ""));
    }
    function setError(el, input, text) {
      el.hidden = !text;
      el.lastChild.textContent = text || "";
      if (input) { if (text) input.setAttribute("aria-invalid", "true"); else input.removeAttribute("aria-invalid"); }
    }

    function cmdPill(c) {
      const map = {
        queued: ["ring", "wait", "Waiting for the server"], sent: ["ring", "wait", "Sent to the bot"], applied: ["check", "ok", "Done"],
        rejected: ["alert", "bad", "Rejected"], failed: ["alert", "bad", "Failed at the broker"], expired: ["alert", "bad", "Not done (expired)"],
      };
      const [ic, cls, label] = map[c.status];
      return h("span", { class: `pill ${cls}` }, icon(ic), label);
    }

    // The newest command of a kind, if it ended badly or is still on its way, so the card can say so.
    function latestOutcome(type) {
      const c = sim.commands.find((x) => x.type === type && x.scope === "sma_cross");
      if (!c) return null;
      if (c.status === "queued" || c.status === "sent") return c;
      if ((c.status === "failed" || c.status === "expired" || c.status === "rejected") && ctx.mockNow() - Date.parse(c.issued_at) < 15 * 60 * 1000) return c;
      return null;
    }
    function outcomeBox(c, what) {
      if (!c) return null;
      if (c.status === "queued" || c.status === "sent") {
        return h("div", { class: "callout", role: "status" }, h("p", null, h("strong", null, `${what} sent.`), " Waiting for the bot to collect it. This takes a few seconds."));
      }
      return h("div", { class: "callout crit", role: "alert" }, h("p", null, h("strong", null, `${what} did not happen.`)), h("p", null, c.reason));
    }

    function hoursInfo() {
      const use = spec("use_trading_hours").value;
      const start = spec("hours_start_ist").value;
      const end = spec("hours_end_ist").value;
      const ist = new Date(ctx.mockNow() + 5.5 * 3600e3);
      const mins = ist.getUTCHours() * 60 + ist.getUTCMinutes();
      const inside = !use || (start < end ? mins >= start && mins < end : mins >= start || mins < end);
      const fmt = (m) => `${String(Math.floor(m / 60)).padStart(2, "0")}:${String(m % 60).padStart(2, "0")}`;
      return { use, inside, start: fmt(start), end: fmt(end), now: fmt(mins) };
    }

    /* ---------------------------------------------------------------------- open trade */
    function openTradeCard() {
      const pos = D.open_positions.find((p) => p.strategy_id === "sma_cross");
      const closed = pos && sim.closed && sim.closed.position_id === pos.position_id ? sim.closed : null;
      if (!pos || closed) {
        return card("span-7", "ot-title", "Open trade", null,
          ctx.emptyBox("No open trade",
            closed
              ? `You closed the ${pos.side} from the dashboard at ${ctx.price(closed.price)}. The bot now waits for the next cross and does not re-enter by itself.`
              : "The bot is waiting for the next cross."));
      }
      const lv = sim.levels[pos.position_id] || {};
      const sl = lv.sl !== undefined ? lv.sl : pos.sl;
      const tp = lv.tp !== undefined ? lv.tp : pos.tp;
      const dir = pos.side === "buy" ? 1 : -1;
      const floating = pos.profit + pos.swap + pos.commission;
      const at = (p) => dollars((p - pos.open_price) * dir, pos.volume);
      const frac = (p) => Math.max(0, Math.min(1, (p - sl) / (tp - sl))) * 100;
      const busy = !!(sim.pending("position.close", "sma_cross") || sim.pending("position.set_levels", "sma_cross"));

      const meter = h("div", { class: "range", style: "height:52px", role: "img",
        "aria-label": `Stop ${ctx.price(sl)}, entry ${ctx.price(pos.open_price)}, now ${ctx.price(pos.current_price)}, target ${ctx.price(tp)}` },
      h("div", { class: "range-track" }),
      h("span", { class: "range-cap start", style: "top:34px;left:0" }, "Stop"),
      h("span", { class: "range-cap end", style: "top:34px;left:100%" }, "Target"),
      h("i", { class: "range-mark", style: `left:${frac(pos.open_price)}%` }),
      h("span", { class: "range-cap", style: `left:${frac(pos.open_price)}%` }, "Entry"),
      h("i", { class: "range-now", style: `left:${frac(pos.current_price)}%` }),
      h("span", { class: "range-cap", style: `left:${frac(pos.current_price)}%;top:34px` }, "Now"));

      const lastClose = latestOutcome("position.close");
      const lastLevels = latestOutcome("position.set_levels");

      let panel = null;
      if (draft.panel === "close") {
        panel = h("div", { class: "panel", role: "group", "aria-labelledby": "close-q" },
          h("p", { id: "close-q" }, h("strong", null, `Close this ${pos.side} of ${ctx.lots(pos.volume)} lot at market?`)),
          h("p", { class: "dim" }, `It is ${floating >= 0 ? "up" : "down"} about ${ctx.signed(floating)} right now, after commission. The final figure depends on the price when the broker fills it.`),
          h("p", { class: "dim" }, "It is not instant: the bot collects the command at its next report. If the bot is offline for more than 2 minutes the command expires and nothing is closed. The MT5 phone app is the fast fallback."),
          h("div", { class: "btn-row" },
            h("button", { class: "btn lg danger-solid", type: "button", id: "close-yes", onclick: () => {
              draft.panel = null;
              ctx.focus.id = "close-btn";
              ctx.send({ scope: "sma_cross", type: "position.close", summary: `Close ${pos.side} ${ctx.lots(pos.volume)} lot`, payload: { position_id: pos.position_id },
                apply: () => { sim.closed = { position_id: pos.position_id, price: pos.current_price, net: floating }; } });
            } }, "Yes, close it"),
            h("button", { class: "btn lg", type: "button", onclick: () => { draft.panel = null; ctx.focus.id = "close-btn"; ctx.refresh(); } }, "No, keep it open")));
      } else if (draft.panel === "levels") {
        panel = levelsPanel(pos, sl, tp, dir, at);
      }

      return card("span-7", "ot-title", "Open trade", `Opened ${ctx.dayTime(pos.open_time)}, held ${heldFor(pos.open_time)}`,
        h("div", { class: "stack" },
          h("div", { class: "trade-top" },
            h("span", { class: "trade-side" }, icon(pos.side === "buy" ? "up" : "down"), `${pos.side === "buy" ? "Buy" : "Sell"} ${ctx.lots(pos.volume)} lot`),
            h("span", { class: "lock" }, icon("lock"), "Lot is fixed while this trade is open")),
          h("p", { class: `pl-big ${floating > 0 ? "pos" : floating < 0 ? "neg" : ""}` }, ctx.signed(floating),
            h("span", { class: "dim", style: "font-size:13px;font-weight:400;margin-left:8px" }, "so far, after commission")),
          meter,
          h("dl", { class: "levels" },
            h("div", null, h("dt", null, "Entry"), h("dd", null, ctx.price(pos.open_price))),
            h("div", null, h("dt", null, "Now"), h("dd", null, ctx.price(pos.current_price))),
            h("div", null, h("dt", null, "Stop loss"), h("dd", null, ctx.price(sl), h("small", null, `${ctx.signed(at(sl))} if hit`))),
            h("div", null, h("dt", null, "Target"), h("dd", null, ctx.price(tp), h("small", null, `${ctx.signed(at(tp))} if hit`)))),
          outcomeBox(lastClose, "Close"),
          outcomeBox(lastLevels, "Level change"),
          panel,
          panel ? null : h("div", { class: "btn-row" },
            h("button", { class: "btn lg danger", type: "button", id: "close-btn", "aria-disabled": busy ? "true" : null, onclick: () => {
              if (busy) return;
              draft.panel = "close"; ctx.focus.id = "close-yes"; ctx.refresh();
            } }, "Close now"),
            h("button", { class: "btn lg", type: "button", id: "levels-btn", "aria-disabled": busy ? "true" : null, onclick: () => {
              if (busy) return;
              draft.panel = "levels"; draft.tpPrice = null; draft.slPrice = null; ctx.focus.id = "tp-price"; ctx.refresh();
            } }, "Change target or stop")),
          h("p", { class: "hint" }, "The stop can only move toward the price, never further away or off. The target can move either way.")));
    }

    function heldFor(iso) {
      const m = Math.max(0, Math.round((ctx.mockNow() - Date.parse(iso)) / 60000));
      return m < 60 ? `${m} min` : `${Math.floor(m / 60)} h ${String(m % 60).padStart(2, "0")} min`;
    }

    function levelsPanel(pos, sl, tp, dir, at) {
      if (draft.tpPrice === null) draft.tpPrice = ctx.price(tp).replace(/,/g, "");
      if (draft.slPrice === null) draft.slPrice = ctx.price(sl).replace(/,/g, "");
      const tpInput = h("input", { class: "input", id: "tp-price", type: "text", inputmode: "decimal", autocomplete: "off", value: draft.tpPrice, "aria-describedby": "tp-err" });
      const slInput = h("input", { class: "input", id: "sl-price", type: "text", inputmode: "decimal", autocomplete: "off", value: draft.slPrice, "aria-describedby": "sl-err" });
      const tpErr = errorLine("tp-err", errors.tpPrice);
      const slErr = errorLine("sl-err", errors.slPrice);
      const outcome = h("p", { class: "dim", "aria-live": "polite" });

      function check() {
        const t = num(tpInput.value);
        const s = num(slInput.value);
        let tpMsg = null;
        let slMsg = null;
        const cur = pos.current_price;
        if (!Number.isFinite(t)) tpMsg = "Enter the target as a price, for example 4190.00.";
        else if (dir * (t - cur) <= 0.5) tpMsg = `The target must be ${dir > 0 ? "above" : "below"} the current price (${ctx.price(cur)}) by at least 0.50.`;
        if (!Number.isFinite(s)) slMsg = "Enter the stop as a price, for example 4155.00.";
        else if (dir * (s - sl) < -1e-9) slMsg = `A stop can only move toward the price. It is ${ctx.price(sl)}; enter ${ctx.price(sl)} or ${dir > 0 ? "higher" : "lower"}.`;
        else if (dir * (cur - s) <= 0.5) slMsg = `The stop must stay ${dir > 0 ? "below" : "above"} the current price (${ctx.price(cur)}) by at least 0.50.`;
        setError(tpErr, tpInput, tpMsg);
        setError(slErr, slInput, slMsg);
        if (!tpMsg && !slMsg) {
          const locked = dir * (s - pos.open_price) > 0;
          outcome.textContent = `If the target is hit: ${ctx.signed(at(t))}. If the stop is hit: ${ctx.signed(at(s))}${locked ? " (a locked-in profit)" : ""}.`;
        } else outcome.textContent = "";
        return { t, s, tpMsg, slMsg };
      }
      tpInput.addEventListener("input", () => { draft.tpPrice = tpInput.value; check(); });
      slInput.addEventListener("input", () => { draft.slPrice = slInput.value; check(); });
      setTimeout(check, 0);

      return h("div", { class: "panel", role: "group", "aria-labelledby": "lv-q" },
        h("p", { id: "lv-q" }, h("strong", null, "Move the target or the stop")),
        h("div", { class: "two" },
          h("div", { class: "field-block" }, h("label", { for: "tp-price" }, "Target price"), tpInput, tpErr),
          h("div", { class: "field-block" }, h("label", { for: "sl-price" }, "Stop price"), slInput, slErr)),
        h("div", { class: "btn-row" },
          h("button", { class: "btn", type: "button", onclick: () => {
            slInput.value = ctx.price(pos.open_price).replace(/,/g, "");
            draft.slPrice = slInput.value;
            check();
          } }, "Stop at break-even (the entry price)")),
        outcome,
        h("div", { class: "btn-row" },
          h("button", { class: "btn lg primary", type: "button", onclick: () => {
            const r = check();
            if (r.tpMsg) return tpInput.focus();
            if (r.slMsg) return slInput.focus();
            const change = {};
            if (Math.abs(r.t - tp) > 1e-9) change.tp = r.t;
            if (Math.abs(r.s - sl) > 1e-9) change.sl = r.s;
            if (!Object.keys(change).length) { ctx.announce("Nothing changed."); draft.panel = null; ctx.focus.id = "levels-btn"; return ctx.refresh(); }
            draft.panel = null;
            ctx.focus.id = "levels-btn";
            const bits = [];
            if (change.tp !== undefined) bits.push(`target ${ctx.price(change.tp)}`);
            if (change.sl !== undefined) bits.push(`stop ${ctx.price(change.sl)}`);
            ctx.send({ scope: "sma_cross", type: "position.set_levels", summary: `Move ${bits.join(" and ")} (${pos.side} ${ctx.lots(pos.volume)} lot)`, payload: Object.assign({ position_id: pos.position_id }, change),
              apply: () => { sim.levels[pos.position_id] = Object.assign({}, sim.levels[pos.position_id], change); } });
          } }, "Save levels"),
          h("button", { class: "btn lg", type: "button", onclick: () => { draft.panel = null; ctx.focus.id = "levels-btn"; ctx.refresh(); } }, "Cancel")));
    }

    /* ---------------------------------------------------------------------- right now */
    function rightNowCard() {
      const pending = sim.pending("strategy.set_enabled", "sma_cross");
      const hours = hoursInfo();
      const chart = D.chart;
      const last = chart.latest.last_cross;
      const gapPips = Math.abs(chart.latest.gap) / ctx.PIP;
      const above = chart.latest.gap > 0;
      const lastOutcome = latestOutcome("strategy.set_enabled");

      const sw = h("button", {
        class: "switch lg", type: "button", role: "switch", id: "auto-switch", "aria-checked": String(sim.auto),
        "aria-busy": pending ? "true" : null, "aria-disabled": pending ? "true" : null, "aria-labelledby": "auto-label",
        onclick: () => {
          if (pending) return; // aria-disabled instead of disabled, so keyboard focus is not lost while the command is on its way
          const to = !sim.auto;
          ctx.focus.id = "auto-switch";
          ctx.send({ scope: "sma_cross", type: "strategy.set_enabled", summary: `Switch ${to ? "on" : "off"} Auto for ${sma.name}`, payload: { strategy_id: "sma_cross", enabled: to }, apply: () => { sim.auto = to; } });
        },
      });
      return card("span-5", "rn-title", "Auto trading", null,
        h("div", { class: "stack" },
          h("div", { class: "switch-line" }, sw,
            h("span", { class: "state", id: "auto-label" }, `Auto is ${pending ? "changing…" : sim.auto ? "on" : "off"}`)),
          h("p", { class: "dim" }, sim.auto
            ? (hours.inside ? "The bot opens a trade at the next cross." : "The bot opens a trade at the next cross inside trading hours. Crosses outside them are shown but not traded.")
            : "No new trades. An open trade keeps its stop and target and still closes on the opposite cross. Signals and alerts carry on."),
          outcomeBox(lastOutcome, "The switch"),
          h("p", { class: "dim" }, icon("clock"), ` Trading hours ${hours.start} to ${hours.end} IST. It is ${hours.now} IST now: `,
            h("strong", null, hours.inside ? "inside the hours." : "outside the hours.")),
          h("dl", { class: "facts", style: "margin-top:0" },
            ctx.fact("Fast line (100)", chart.latest.fast.toFixed(2)),
            ctx.fact("Slow line (5000)", chart.latest.slow.toFixed(2)),
            ctx.fact("Fast is", `${above ? "above" : "below"} by ${gapPips.toFixed(0)} pips`),
            ctx.fact("Last cross", last ? `${last.side === "buy" ? "Buy" : "Sell"}, ${ctx.dayTime(last.time)}` : "none yet")),
          h("p", { class: "dim" }, "The next signal comes when the fast line crosses ", above ? "back below" : "back above", " the slow line. ",
            h("a", { href: "#/chart" }, "See it on the chart"), ".")));
    }

    /* ---------------------------------------------------------------------- next trade */
    function nextTradeCard() {
      if (draft.lot === null) draft.lot = fixed2(sim.settings.next_lot);
      if (draft.tp === null) draft.tp = String(sim.settings.take_profit_pips);
      if (draft.sl === null) draft.sl = String(sim.settings.stop_loss_pips);
      if (draft.maxLot === null) draft.maxLot = fixed2(sim.settings.max_lot);

      const lotIn = h("input", { class: "input", id: "lot-in", type: "text", inputmode: "decimal", autocomplete: "off", value: draft.lot, "aria-describedby": "lot-hint lot-err" });
      const tpIn = h("input", { class: "input", id: "tp-in", type: "text", inputmode: "numeric", autocomplete: "off", value: draft.tp, "aria-describedby": "tp-hint tp-in-err" });
      const slIn = h("input", { class: "input", id: "sl-in", type: "text", inputmode: "numeric", autocomplete: "off", value: draft.sl, "aria-describedby": "sl-hint sl-in-err" });
      const lotErr = errorLine("lot-err", errors.lot);
      const tpErr = errorLine("tp-in-err", errors.tp);
      const slErr = errorLine("sl-in-err", errors.sl);
      const risk = h("dl", { class: "facts", style: "margin-top:0", "aria-live": "polite" });

      function check() {
        const lot = num(lotIn.value);
        const tp = num(tpIn.value);
        const sl = num(slIn.value);
        const lotMsg = checkLot(lot, sim.settings.max_lot);
        const tpMsg = checkPips("take_profit_pips", "take profit", tp);
        const slMsg = checkPips("stop_loss_pips", "stop loss", sl);
        setError(lotErr, lotIn, lotMsg);
        setError(tpErr, tpIn, tpMsg);
        setError(slErr, slIn, slMsg);
        risk.replaceChildren(
          ctx.fact("If stopped out", !lotMsg && !slMsg ? ctx.signed(-dollars(sl * ctx.PIP, lot)) : "—"),
          ctx.fact("If the target is hit", !lotMsg && !tpMsg ? ctx.signed(dollars(tp * ctx.PIP, lot)) : "—"));
        return { lot, tp, sl, lotMsg, tpMsg, slMsg };
      }
      lotIn.addEventListener("input", () => { draft.lot = lotIn.value; check(); });
      tpIn.addEventListener("input", () => { draft.tp = tpIn.value; check(); });
      slIn.addEventListener("input", () => { draft.sl = slIn.value; check(); });
      setTimeout(check, 0);

      const bump = (dir) => {
        const sp = spec("next_lot");
        const cur = Number.isFinite(num(lotIn.value)) ? num(lotIn.value) : sim.settings.next_lot;
        const v = Math.round((cur + dir * sp.step) * 100) / 100;
        lotIn.value = fixed2(Math.max(sp.min, Math.min(sim.settings.max_lot, v)));
        draft.lot = lotIn.value;
        check();
        lotIn.focus();
      };

      const pending = sim.pending("strategy.update_settings", "sma_cross");
      const outcome = latestOutcome("strategy.update_settings");

      const maxIn = h("input", { class: "input", id: "max-in", type: "text", inputmode: "decimal", autocomplete: "off", value: draft.maxLot, "aria-describedby": "max-err" });
      const maxErr = errorLine("max-err", errors.maxLot);
      maxIn.addEventListener("input", () => { draft.maxLot = maxIn.value; setError(maxErr, maxIn, checkMaxLot(num(maxIn.value))); });

      return card("span-5", "nt-title", "Next trade", "Applies to the next trade the bot opens",
        h("div", { class: "stack" },
          h("p", { class: "lock" }, icon("lock"), "An open trade's lot never changes. Edit this any time before the bot opens the next one."),
          h("div", { class: "field-block" },
            h("label", { for: "lot-in" }, "Lot size"),
            h("div", { class: "stepper" },
              h("button", { class: "btn", type: "button", "aria-label": "Smaller lot", onclick: () => bump(-1) }, "−"),
              lotIn,
              h("button", { class: "btn", type: "button", "aria-label": "Larger lot", onclick: () => bump(1) }, "+")),
            h("p", { class: "hint", id: "lot-hint" }, `Smallest ${fixed2(spec("next_lot").min)}, largest allowed ${fixed2(sim.settings.max_lot)}, steps of ${fixed2(spec("next_lot").step)}.`),
            lotErr),
          h("div", { class: "two" },
            h("div", { class: "field-block" }, h("label", { for: "tp-in" }, "Take profit (pips)"), tpIn,
              h("p", { class: "hint", id: "tp-hint" }, `300 pips = $30 price move.`), tpErr),
            h("div", { class: "field-block" }, h("label", { for: "sl-in" }, "Stop loss (pips)"), slIn,
              h("p", { class: "hint", id: "sl-hint" }, "Always required. 100 pips = $10."), slErr)),
          risk,
          outcomeBox(outcome, "The change"),
          h("div", { class: "btn-row" },
            h("button", { class: "btn lg primary", type: "button", "aria-disabled": pending ? "true" : null, onclick: () => {
              if (pending) return;
              const r = check();
              if (r.lotMsg) return lotIn.focus();
              if (r.tpMsg) return tpIn.focus();
              if (r.slMsg) return slIn.focus();
              const diff = {};
              if (Math.abs(r.lot - sim.settings.next_lot) > 1e-9) diff.next_lot = Math.round(r.lot * 100) / 100;
              if (r.tp !== sim.settings.take_profit_pips) diff.take_profit_pips = r.tp;
              if (r.sl !== sim.settings.stop_loss_pips) diff.stop_loss_pips = r.sl;
              if (!Object.keys(diff).length) return ctx.announce("Nothing changed.");
              const bits = [];
              if (diff.next_lot !== undefined) bits.push(`next trade lot ${fixed2(diff.next_lot)}`);
              if (diff.take_profit_pips !== undefined) bits.push(`take profit ${diff.take_profit_pips} pips`);
              if (diff.stop_loss_pips !== undefined) bits.push(`stop loss ${diff.stop_loss_pips} pips`);
              ctx.focus.id = "save-next";
              ctx.send({ scope: "sma_cross", type: "strategy.update_settings", summary: `Set ${bits.join(", ")}`, payload: { strategy_id: "sma_cross", settings_rev: sma.settings_rev + 1, settings: diff },
                apply: () => { Object.assign(sim.settings, diff); draft.lot = draft.tp = draft.sl = null; } });
            }, id: "save-next" }, "Save for the next trade")),
          h("details", { class: "more-opts" },
            h("summary", null, `Largest lot allowed: ${fixed2(sim.settings.max_lot)}`),
            h("div", { class: "stack" },
              h("p", { class: "hint" }, "A cap that stops a typing mistake, such as 1.0 instead of 0.1. Raise it only on purpose."),
              h("div", { class: "field-block" }, h("label", { for: "max-in" }, "Largest lot allowed"), maxIn, maxErr),
              h("button", { class: "btn", type: "button", onclick: () => {
                const msg = checkMaxLot(num(maxIn.value));
                setError(maxErr, maxIn, msg);
                if (msg) return maxIn.focus();
                const v = Math.round(num(maxIn.value) * 100) / 100;
                if (Math.abs(v - sim.settings.max_lot) < 1e-9) return ctx.announce("Nothing changed.");
                ctx.send({ scope: "sma_cross", type: "strategy.update_settings", summary: `Set the largest lot allowed to ${fixed2(v)}`, payload: { strategy_id: "sma_cross", settings_rev: sma.settings_rev + 1, settings: { max_lot: v } },
                  apply: () => { sim.settings.max_lot = v; draft.maxLot = null; } });
              } }, "Save largest lot")))));
    }

    /* ----------------------------------------------------------------- recent controls */
    function recentCard() {
      const items = sim.commands.slice(0, 6).map((c) => h("li", null,
        h("time", { datetime: c.issued_at }, ctx.hhmm(c.issued_at)),
        h("div", { class: "feed-who" }, c.summary),
        cmdPill(c),
        c.reason ? h("p", { class: "feed-why" }, c.reason) : null));
      const signals = D.recent_signals.filter((s) => s.strategy_id === "sma_cross").slice(0, 4);
      return h("div", { class: "span-7", style: "display:grid;gap:16px;align-content:start;min-width:0" },
        h("section", { class: "sheet", "aria-labelledby": "rc-title" },
          h("div", { class: "sheet-head" }, h("h2", { id: "rc-title" }, "Controls you pressed"),
            h("p", { class: "sheet-sub" }, "What became of each one")),
          h("ul", { class: "feed sheet-body flush" }, items)),
        h("section", { class: "sheet", "aria-labelledby": "ls-title" },
          h("div", { class: "sheet-head" }, h("h2", { id: "ls-title" }, "Latest signals"),
            h("p", { class: "sheet-sub" }, "Including crosses outside trading hours, which are not traded")),
          h("ul", { class: "feed sheet-body flush" }, signals.map(ctx.signalRow))));
    }

    function mockControls() {
      if (ctx.LIVE) return null; // live: the controls are real, there is nothing to simulate
      return h("details", { class: "mock" },
        h("summary", null, "Mock-up controls: nothing is really sent"),
        h("label", { class: "field" }, "What happens to the next control you press",
          h("select", { id: "mock-mode", onchange: (e) => { sim.mode = e.target.value; } },
            h("option", Object.assign({ value: "normal" }, sim.mode === "normal" ? { selected: true } : {}), "It works"),
            h("option", Object.assign({ value: "offline" }, sim.mode === "offline" ? { selected: true } : {}), "The bot is offline, so it expires"),
            h("option", Object.assign({ value: "refused" }, sim.mode === "refused" ? { selected: true } : {}), "The broker refuses (market closed)"))),
        h("p", { class: "hint", style: "margin-top:6px" }, "Changes made here stay on this screen only. The other screens keep the original sample data."));
    }

    function render() {
      return h("div", null,
        ctx.pageHead("Trade", "Controls for the SMA 100/5000 cross strategy on gold."),
        mockControls(),
        h("div", { class: "grid" }, openTradeCard(), rightNowCard(), nextTradeCard(), recentCard()));
    }

    return { render };
  };
})();
