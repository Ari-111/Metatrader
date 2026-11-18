/* Alerts screen: what triggers an alert, where it goes, and how TradingView fits in.
   Switches here only change this mock-up. In the real system they become server settings. */
(function () {
  "use strict";
  window.Views = window.Views || {};

  window.Views.alerts = function (ctx) {
    const { D, h, icon, sim } = ctx;
    const A = D.alerts;
    const EV = Object.fromEntries(A.events.map((e) => [e.id, e.label]));
    const CH = Object.fromEntries(A.channels.map((c) => [c.id, c.label]));
    const sp = D.strategies.find((x) => x.id === "sma_cross").settings.find((x) => x.key === "near_lines_pips");
    const draft = { near: null };

    function toggle(id, on, label, disabled, onChange) {
      return h("button", {
        class: "switch", type: "button", role: "switch", id, "aria-checked": String(on), "aria-label": label, disabled: disabled || null,
        onclick: () => { ctx.focus.id = id; onChange(!on); ctx.announce(`${label}: ${!on ? "on" : "off"}.`); ctx.refresh(); },
      });
    }

    function eventsSheet() {
      const rows = A.events.map((e) => {
        const needsDistance = e.id === "heads_up" && sim.settings.near_lines_pips === 0;
        return h("li", null,
          h("div", { class: "label" }, e.label,
            needsDistance ? h("span", null, "Set a distance below first.") : null),
          h("div", { class: "right" },
            toggle(`ev-${e.id}`, sim.alerts.events[e.id] && !needsDistance, e.label, needsDistance, (v) => { sim.alerts.events[e.id] = v; })));
      });
      return h("section", { class: "sheet span-6", "aria-labelledby": "ae-t" },
        h("div", { class: "sheet-head" }, h("h2", { id: "ae-t" }, "What sends an alert")),
        h("ul", { class: "rows sheet-body flush", style: "margin-top:8px" }, rows));
    }

    function channelsSheet() {
      const rows = A.channels.map((c) => {
        let right;
        if (c.status === "needs_setup") right = h("span", { class: "pill off" }, "Needs setup");
        else if (c.status === "external") right = h("span", { class: "pill" }, "Set up in TradingView");
        else right = toggle(`ch-${c.id}`, sim.alerts.channels[c.id], c.label, false, (v) => { sim.alerts.channels[c.id] = v; });
        return h("li", null, h("div", { class: "label" }, c.label, c.note ? h("span", null, c.note) : null), h("div", { class: "right" }, right));
      });
      return h("section", { class: "sheet span-6", "aria-labelledby": "ac-t" },
        h("div", { class: "sheet-head" }, h("h2", { id: "ac-t" }, "Where alerts go")),
        h("ul", { class: "rows sheet-body flush", style: "margin-top:8px" }, rows));
    }

    function distanceSheet() {
      if (draft.near === null) draft.near = String(sim.settings.near_lines_pips);
      const input = h("input", { class: "input", id: "near-in", type: "text", inputmode: "numeric", autocomplete: "off", value: draft.near, "aria-describedby": "near-err near-hint" });
      const err = h("p", { class: "error", id: "near-err", role: "alert", hidden: true }, icon("alert"), h("span", null, ""));
      const check = () => {
        const v = Number(String(input.value).trim());
        let msg = null;
        if (String(input.value).trim() === "" || !Number.isInteger(v)) msg = "Enter a whole number of pips, or 0 to switch it off.";
        else if (v < sp.min || v > sp.max) msg = `Use a number between ${sp.min} and ${sp.max}.`;
        else if (v % sp.step !== 0) msg = `Use steps of ${sp.step} pips.`;
        err.hidden = !msg;
        err.lastChild.textContent = msg || "";
        if (msg) input.setAttribute("aria-invalid", "true"); else input.removeAttribute("aria-invalid");
        return { v, msg };
      };
      input.addEventListener("input", () => { draft.near = input.value; check(); });
      const pending = sim.pending("strategy.update_settings", "sma_cross");
      return h("section", { class: "sheet span-5", "aria-labelledby": "ad-t" },
        h("div", { class: "sheet-head" }, h("h2", { id: "ad-t" }, "Lines getting close")),
        h("div", { class: "sheet-body stack" },
          h("p", { class: "dim" }, "An optional heads-up before a cross: it fires when the fast and slow lines are this close. It never opens a trade."),
          h("div", { class: "field-block" }, h("label", { for: "near-in" }, "Heads-up distance (pips, 0 is off)"), input,
            h("p", { class: "hint", id: "near-hint" }, "10 pips is $1.00 of gold price."), err),
          h("div", { class: "btn-row" },
            h("button", { class: "btn lg primary", type: "button", "aria-disabled": pending ? "true" : null, onclick: () => {
              if (pending) return;
              const r = check();
              if (r.msg) return input.focus();
              if (r.v === sim.settings.near_lines_pips) return ctx.announce("Nothing changed.");
              ctx.focus.id = "near-save";
              ctx.send({ scope: "sma_cross", type: "strategy.update_settings", summary: r.v === 0 ? "Switch the lines-getting-close heads-up off" : `Heads-up when the lines are within ${r.v} pips`,
                payload: { strategy_id: "sma_cross", settings_rev: D.strategies.find((x) => x.id === "sma_cross").settings_rev + 1, settings: { near_lines_pips: r.v } },
                apply: () => { sim.settings.near_lines_pips = r.v; draft.near = null; } });
            }, id: "near-save" }, "Save distance"))));
    }

    function tradingViewSheet() {
      return h("section", { class: "sheet span-7", "aria-labelledby": "tv-t" },
        h("div", { class: "sheet-head" }, h("h2", { id: "tv-t" }, "TradingView")),
        h("div", { class: "sheet-body stack" },
          h("p", null, "TradingView alerts are made inside TradingView, not here. The plan is an indicator that draws the same Buy and Sell signals on any timeframe, because it also works from 1-minute candles, and sends an alert when one appears. The MT5 bot stays the only thing that trades."),
          h("ul", { class: "stack", style: "list-style:disc;padding-left:20px" },
            h("li", null, "Hiding the strategy needs a TradingView plan that allows invite-only scripts (Premium or Ultimate, per TradingView's help pages). A private invite-only script can be shared with at most 5 people."),
            h("li", null, "TradingView's prices come from a different feed, so a cross can land a candle away from the bot's. This will be measured before you rely on it."),
            h("li", null, "The indicator is not written yet, and until you paste it into TradingView it is untested.")),
          h("p", { class: "dim" }, "Alerts from the bot on your Exness account go out through MT5 (and later Telegram). Exness itself has no alert service for a custom strategy.")));
    }

    function recentSheet() {
      const rows = A.recent.map((a) => h("li", null,
        h("time", { datetime: a.time }, ctx.hhmm(a.time)),
        h("div", { class: "feed-who" }, EV[a.event], h("span", { class: "dim", style: "font-weight:400" }, ` via ${CH[a.channel]}`)),
        h("span", { class: `pill ${a.delivered ? "ok" : "bad"}` }, icon(a.delivered ? "check" : "alert"), a.delivered ? "Delivered" : "Not delivered"),
        h("p", { class: "feed-why" }, a.text)));
      return h("section", { class: "sheet span-12", "aria-labelledby": "ar-t" },
        h("div", { class: "sheet-head" }, h("h2", { id: "ar-t" }, "Recent alerts"), h("p", { class: "sheet-sub" }, "Newest first")),
        h("ul", { class: "feed sheet-body flush" }, rows));
    }

    function render() {
      return h("div", null,
        ctx.pageHead("Alerts", "Be told about every buy and sell signal, and every trade that closes."),
        h("div", { class: "grid" }, eventsSheet(), channelsSheet(), distanceSheet(), tradingViewSheet(), recentSheet()));
    }

    return { render };
  };
})();
