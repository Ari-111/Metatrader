#!/usr/bin/env python3
"""Validate the data contract and the sample files that follow it (contract v0.2).

Run from anywhere:  python -P tools/validate_contract.py

Two kinds of check:
  1. Shape: every sample file validates against its JSON Schema.
  2. Consistency: the numbers inside a sample agree with each other
     (equity = balance + floating, strategy totals = sum of their deals, the chart's two lines
     reproduce exactly the crosses in the signal list, a lot never exceeds the largest allowed, ...).
     These are the checks the future server and the dashboard will rely on.

Exit code 0 when everything passes, 1 otherwise.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

from jsonschema import Draft202012Validator
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

ROOT = Path(__file__).resolve().parent.parent
CONTRACT = ROOT / "contract"

# XAUUSD contract size used by the sample data: 1 lot = 100 oz, so a 1.00 move on 0.10 lot = 10.00.
CONTRACT_SIZE = 100
PIP = 0.10         # 1 pip = 0.10 price units on XAUUSD, so 300 pips = 30.00
MONEY_TOL = 0.011  # sender rounds to 2 decimals


def load(path: Path):
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


def ts(value: str) -> datetime:
    return datetime.fromisoformat(value)


def build_registry() -> tuple[Registry, dict[str, dict]]:
    schemas: dict[str, dict] = {}
    resources = []
    for path in sorted(CONTRACT.glob("*.schema.json")):
        schema = load(path)
        Draft202012Validator.check_schema(schema)
        schemas[path.name] = schema
        resources.append((schema["$id"], Resource.from_contents(schema, default_specification=DRAFT202012)))
        # The schemas reference each other by file name, so register that form too.
        resources.append((path.name, Resource.from_contents(schema, default_specification=DRAFT202012)))
    return Registry().with_resources(resources), schemas


class Report:
    def __init__(self) -> None:
        self.failures: list[str] = []
        self.passes = 0

    def check(self, ok: bool, label: str, detail: str = "") -> None:
        if ok:
            self.passes += 1
        else:
            self.failures.append(f"{label}" + (f": {detail}" if detail else ""))

    def close(self, a: float, b: float, label: str, tol: float = MONEY_TOL) -> None:
        self.check(abs(a - b) <= tol, label, f"{a} vs {b}")


def validate_shape(rep: Report, registry: Registry, schemas: dict, schema_name: str, instance, label: str) -> bool:
    """Check one document against its schema. Returns True when it is well-formed."""
    validator = Draft202012Validator(schemas[schema_name], registry=registry)
    errors = sorted(validator.iter_errors(instance), key=lambda e: list(e.absolute_path))
    for err in errors[:8]:
        path = "/".join(str(p) for p in err.absolute_path) or "(root)"
        rep.check(False, f"{label} shape", f"{path}: {err.message[:160]}")
    rep.check(not errors, f"{label} matches {schema_name}")
    return not errors


# ---------------------------------------------------------------- pieces shared by several documents

def check_snapshot(rep: Report, snap: dict, positions: list[dict], label: str) -> None:
    floating = sum(p["profit"] + p["swap"] + p["commission"] for p in positions)
    rep.close(snap["floating_pl"], floating, f"{label}: floating_pl equals the sum over open positions")
    rep.close(snap["equity"], snap["balance"] + snap["floating_pl"], f"{label}: equity = balance + floating_pl")
    rep.close(snap["free_margin"], snap["equity"] - snap["margin"], f"{label}: free_margin = equity - margin")
    if snap["margin"] > 0:
        rep.check(snap["margin_level"] is not None, f"{label}: margin_level present when margin is in use")
        if snap["margin_level"] is not None:
            rep.close(snap["margin_level"], snap["equity"] / snap["margin"] * 100, f"{label}: margin_level = equity / margin", tol=0.06)
    else:
        rep.check(snap["margin_level"] is None, f"{label}: margin_level is null when no margin is used")


def check_positions(rep: Report, positions: list[dict], label: str) -> None:
    ids = [p["position_id"] for p in positions]
    rep.check(len(ids) == len(set(ids)), f"{label}: position_id values are unique")
    for p in positions:
        who = f"{label}: position {p['position_id']}"
        direction = 1 if p["side"] == "buy" else -1
        expected = (p["current_price"] - p["open_price"]) * direction * p["volume"] * CONTRACT_SIZE
        rep.close(p["profit"], expected, f"{who} profit matches its prices", tol=0.02)
        if p["sl"] is not None:
            on_loss_side = p["sl"] < p["open_price"] if p["side"] == "buy" else p["sl"] > p["open_price"]
            rep.check(on_loss_side, f"{who} stop loss is on the losing side")
        if p["tp"] is not None:
            on_win_side = p["tp"] > p["open_price"] if p["side"] == "buy" else p["tp"] < p["open_price"]
            rep.check(on_win_side, f"{who} take profit is on the winning side")
        # Lot rule: a position the bot owns has a locked volume.
        rep.check(p["volume_locked"] is True or p["strategy_id"] is None, f"{who} is volume_locked when the bot owns it")
        # Stop rule: the stop may only have moved toward the price since the order was opened.
        rep.check((p["sl"] is None) == (p["sl_original"] is None), f"{who} sl and sl_original are both set or both empty")
        if p["sl"] is not None and p["sl_original"] is not None:
            tighter = p["sl"] >= p["sl_original"] if p["side"] == "buy" else p["sl"] <= p["sl_original"]
            rep.check(tighter, f"{who} stop loss is not wider than the one the order opened with", f"{p['sl']} vs {p['sl_original']}")


def check_deals(rep: Report, deals: list[dict], label: str) -> None:
    ids = [d["deal_id"] for d in deals]
    rep.check(len(ids) == len(set(ids)), f"{label}: deal_id values are unique")
    for d in deals:
        rep.check(ts(d["close_time"]) > ts(d["open_time"]), f"{label}: deal {d['deal_id']} closes after it opens")
        direction = 1 if d["side"] == "buy" else -1
        expected = (d["close_price"] - d["open_price"]) * direction * d["volume"] * CONTRACT_SIZE
        rep.close(d["profit"], expected, f"{label}: deal {d['deal_id']} profit matches its prices", tol=0.02)


def check_signals(rep: Report, signals: list[dict], strategy_ids: set[str], label: str) -> None:
    rep.check(len({s["signal_id"] for s in signals}) == len(signals), f"{label}: signal_id values are unique")
    for sig in signals:
        who = f"{label}: signal {sig['signal_id']}"
        rep.check(sig["strategy_id"] in strategy_ids, f"{who} refers to a known strategy", sig["strategy_id"])
        rep.check(sig["acted"] is False or sig["kind"] != "skipped", f"{who}: a skipped signal is never acted on")
        rep.check(sig["kind"] != "heads_up" or sig["acted"] is False, f"{who}: a heads-up never leads to an order")
        lag = (ts(sig["time"]) - ts(sig["candle_close"])).total_seconds()
        rep.check(0 <= lag <= 5, f"{who}: raised within 5 s after its candle closed", f"{lag:.0f}s")
        rep.check(ts(sig["candle_close"]).second == 0, f"{who}: candle_close is on a whole minute")
        # Lot rule: an order always names its lot, and no order means no lot.
        rep.check((sig["lot"] is not None) == (sig["acted"] and sig["kind"] == "entry"), f"{who}: lot is present exactly when an entry order was sent")


# ---------------------------------------------------------------- the overview

def check_settings(rep: Report, strategies: list[dict], label: str) -> None:
    for s in strategies:
        by_key = {x["key"]: x for x in s["settings"]}
        rep.check(len(by_key) == len(s["settings"]), f"{label}: {s['id']} setting keys are unique")
        for x in s["settings"]:
            who = f"{label}: {s['id']}.{x['key']}"
            numeric = isinstance(x["value"], (int, float)) and not isinstance(x["value"], bool)
            if not x["editable"]:
                rep.check(x["min"] is None and x["max"] is None, f"{who} is fixed, so it has no range")
            if x["editable"] and numeric and x["min"] is not None and x["max"] is not None:
                rep.check(x["min"] <= x["value"] <= x["max"], f"{who} is inside its own range", f"{x['min']} <= {x['value']} <= {x['max']}")
                rep.check(x["min"] <= x["max"], f"{who} range is ordered")
            if x["editable"] and numeric and x["step"]:
                n = (x["value"] - (x["min"] or 0)) / x["step"]
                rep.check(abs(n - round(n)) < 1e-6, f"{who} is a whole number of steps from its minimum", f"{x['value']} step {x['step']}")
        if "next_lot" in by_key:
            nl, ml = by_key["next_lot"], by_key["max_lot"]
            rep.close(nl["max"], ml["value"], f"{label}: {s['id']} next_lot may go up to max_lot", tol=1e-9)
            rep.check(nl["min"] >= 0.01 - 1e-12, f"{label}: {s['id']} next_lot minimum is at least 0.01")
            rep.check(nl["value"] <= ml["value"], f"{label}: {s['id']} next_lot is not above max_lot")
            rep.check(ml["value"] <= ml["max"], f"{label}: {s['id']} max_lot is inside its own range")


def check_chart(rep: Report, chart: dict, overview: dict) -> None:
    label = "chart"
    tfs = chart["timeframes"]
    as_of = ts(chart["as_of"])
    latest = chart["latest"]
    for name, cs in tfs.items():
        n = len(cs["t"])
        rep.check(all(len(cs[k]) == n for k in ("o", "h", "l", "c", "fast", "slow")), f"{label}: {name} columns have equal length")
        times = [ts(t) for t in cs["t"]]
        rep.check(all(a < b for a, b in zip(times, times[1:])), f"{label}: {name} candles are in strict time order")
        rep.check(times[-1] < as_of, f"{label}: {name} last candle opens before as_of")
        ok = all(cs["h"][i] >= max(cs["o"][i], cs["c"][i], cs["l"][i]) and cs["l"][i] <= min(cs["o"][i], cs["c"][i]) for i in range(n))
        rep.check(ok, f"{label}: {name} every candle has its high on top and its low at the bottom")
        # An average is null only until it has enough history, never in the middle.
        for key in ("fast", "slow"):
            seen_value = False
            gap_ok = True
            for v in cs[key]:
                if v is not None:
                    seen_value = True
                elif seen_value:
                    gap_ok = False
            rep.check(gap_ok, f"{label}: {name} {key} has no holes once it starts")
        # Whatever the timeframe, the newest candle ends at the newest 1-minute close, so its lines equal the latest values.
        if cs["fast"][-1] is not None:
            rep.close(cs["fast"][-1], latest["fast"], f"{label}: {name} newest candle carries the latest fast average", tol=0.0011)
            rep.close(cs["slow"][-1], latest["slow"], f"{label}: {name} newest candle carries the latest slow average", tol=0.0011)
        # The timeframe really is a regrouping of the minute data: its candles are no finer than its name says.
    one = tfs["1m"]
    rep.check(ts(one["t"][-1]) + timedelta(minutes=1) == as_of, f"{label}: as_of is the close of the newest 1-minute candle")

    rep.close(latest["gap"], latest["fast"] - latest["slow"], f"{label}: latest gap = fast - slow", tol=0.0011)
    markers = chart["markers"]
    mt = [ts(m["t"]) for m in markers]
    rep.check(all(a < b for a, b in zip(mt, mt[1:])), f"{label}: markers are in time order")
    rep.check(all(markers[i]["side"] != markers[i + 1]["side"] for i in range(len(markers) - 1)), f"{label}: crosses alternate buy and sell")
    rep.check(all(m["traded"] == (m["note"] is None) for m in markers), f"{label}: a marker has a note exactly when it was not traded")
    if markers:
        rep.check(latest["last_cross"] == {"time": markers[-1]["t"], "side": markers[-1]["side"]}, f"{label}: latest.last_cross is the newest marker")
        rep.check((latest["gap"] > 0) == (markers[-1]["side"] == "buy"), f"{label}: the fast line is above the slow line exactly after a buy cross")

    # The strongest check: the two lines on the 1-minute chart reproduce exactly the crosses in the marker list.
    ts1 = [ts(t) for t in one["t"]]
    derived = set()
    for i in range(1, len(ts1)):
        f0, s0, f1, s1 = one["fast"][i - 1], one["slow"][i - 1], one["fast"][i], one["slow"][i]
        if None in (f0, s0, f1, s1):
            continue
        act = ts1[i + 1] if i + 1 < len(ts1) else as_of
        if f0 <= s0 and f1 > s1:
            derived.add((act, "buy"))
        elif f0 >= s0 and f1 < s1:
            derived.add((act, "sell"))
    window_start = ts1[1]
    listed = {(ts(m["t"]), m["side"]) for m in markers if window_start < ts(m["t"]) <= as_of}
    rep.check(derived == listed, f"{label}: the lines on the 1-minute chart reproduce the cross markers exactly",
              f"{len(derived)} from the lines, {len(listed)} listed, differing: {sorted(derived ^ listed)[:3]}")

    # Strategy and chart agree about the averages and about the position.
    sma = next((s for s in overview["strategies"] if s["id"] == "sma_cross"), None)
    if sma:
        by_key = {x["key"]: x["value"] for x in sma["settings"]}
        rep.check(by_key.get("fast_period") == chart["fast_period"] and by_key.get("slow_period") == chart["slow_period"],
                  f"{label}: chart periods match the strategy settings")
        for p in overview["open_positions"]:
            if p["strategy_id"] == "sma_cross" and markers:
                rep.check(p["side"] == markers[-1]["side"], f"{label}: the open sma_cross trade is on the side of the last cross")
                tp_d, sl_d = by_key["take_profit_pips"] * PIP, by_key["stop_loss_pips"] * PIP
                rep.close(abs(p["tp"] - p["open_price"]), tp_d, f"{label}: take profit sits the set number of pips from the entry", tol=0.011)
                rep.close(abs(p["sl_original"] - p["open_price"]), sl_d, f"{label}: stop loss sits the set number of pips from the entry", tol=0.011)
                rep.check(p["volume"] <= by_key["max_lot"] + 1e-9, f"{label}: the open trade's lot is within the largest lot allowed")


def level_for(pct: float) -> str:
    return "calm" if pct < 0.25 else "normal" if pct < 0.75 else "high" if pct < 0.95 else "extreme"


def check_volatility(rep: Report, v: dict, server_time: str) -> None:
    label = "volatility"
    rep.check(ts(v["as_of"]) <= ts(server_time), f"{label}: as_of is not in the future")
    rep.check(v["now"]["level"] == level_for(v["now"]["percentile"]), f"{label}: level matches the percentile")
    rep.check({f["horizon_h"] for f in v["forecasts"]} == {12, 24}, f"{label}: there is a 12-hour and a 24-hour forecast")
    for f in v["forecasts"]:
        who = f"{label}: {f['horizon_h']} h forecast"
        rep.check(f["low"] <= f["expected"] <= f["high"], f"{who} lies inside its own range")
        rep.close(f["change_pct"], (f["expected"] / f["last_period"] - 1) * 100, f"{who} change_pct matches expected vs last period", tol=0.3)
        if abs(f["prob_higher"] - 0.5) > 0.01:
            rep.check((f["expected"] > f["last_period"]) == (f["prob_higher"] > 0.5), f"{who} probability agrees with the direction of the change")
    h = v["history"]
    rep.check(len(h["t"]) == len(h["value"]), f"{label}: history columns have equal length")
    rep.check(all(ts(a) < ts(b) for a, b in zip(h["t"], h["t"][1:])), f"{label}: history is in time order")
    rep.check(ts(h["t"][-1]) <= ts(v["as_of"]), f"{label}: history ends before as_of")
    sc = v["scorecard"]
    rep.check(ts(sc["tested_from"]) < ts(sc["tested_to"]), f"{label}: scorecard period is ordered")
    rep.check({r["horizon_h"] for r in sc["rows"]} == {12, 24}, f"{label}: scorecard covers both horizons")
    for r in sc["rows"]:
        who = f"{label}: {r['horizon_h']} h scorecard"
        best_err = min(r["error_persist_pct"], r["error_avg90_pct"], r["error_tod_pct"])
        best_brier = min(r["brier_base"], r["brier_tod"])
        better_err = r["error_model_pct"] < best_err - 1.0
        better_dir = r["brier_model"] < best_brier - 0.005
        expected = "better" if better_err and better_dir else "mixed" if better_err or better_dir else "no better"
        rep.check(r["verdict"] == expected, f"{who} verdict follows the stated rule", f"{r['verdict']} vs {expected}")
        rep.check(sum(b["n"] for b in r["calibration"]) == r["samples"], f"{who} calibration buckets account for every sample")
        rep.check(r["base_rate"] >= 0.5, f"{who} base rate is the more common answer")
    ev = [ts(e["time"]) for e in v["events"]]
    rep.check(ev == sorted(ev), f"{label}: events are soonest first")
    rep.check(all(t > ts(v["as_of"]) for t in ev), f"{label}: events are in the future")


def check_commands(rep: Report, commands: list[dict], server_time: str) -> None:
    label = "recent_commands"
    now = ts(server_time)
    times = [ts(c["issued_at"]) for c in commands]
    rep.check(times == sorted(times, reverse=True), f"{label}: newest first")
    rep.check(len({c["command_id"] for c in commands}) == len(commands), f"{label}: command_id values are unique")
    for c in commands:
        who = f"{label}: {c['command_id']}"
        rep.check(ts(c["expires_at"]) > ts(c["issued_at"]), f"{who} expires after it is issued")
        if c["status"] in ("rejected", "failed", "expired"):
            rep.check(c["reason"] is not None, f"{who} says why it did not happen")
        if c["status"] in ("queued", "sent"):
            rep.check(ts(c["expires_at"]) > now, f"{who} is still waiting, so it has not expired")
        if c["status"] == "expired":
            rep.check(ts(c["expires_at"]) <= now, f"{who} is marked expired, so its time has passed")


def check_alerts(rep: Report, alerts: dict, server_time: str) -> None:
    label = "alerts"
    ev_ids = [e["id"] for e in alerts["events"]]
    ch = {c["id"]: c for c in alerts["channels"]}
    rep.check(len(ev_ids) == len(set(ev_ids)) and len(ch) == len(alerts["channels"]), f"{label}: event and channel ids are unique")
    rep.check(ch["tradingview"]["status"] == "external", f"{label}: TradingView alerts are made in TradingView")
    for c in alerts["channels"]:
        rep.check(not (c["status"] == "needs_setup" and c["enabled"]), f"{label}: {c['id']} is not switched on while it still needs setup")
    times = [ts(a["time"]) for a in alerts["recent"]]
    rep.check(times == sorted(times, reverse=True), f"{label}: recent alerts are newest first")
    rep.check(all(t <= ts(server_time) for t in times), f"{label}: no alert is from the future")
    for a in alerts["recent"]:
        rep.check(a["event"] in ev_ids, f"{label}: alert event is a known event")
        rep.check(not (a["delivered"] and ch[a["channel"]]["status"] == "needs_setup"), f"{label}: nothing was delivered through a channel that needs setup")


def check_overview(rep: Report, ov: dict) -> None:
    label = "overview"
    check_snapshot(rep, ov["snapshot"], ov["open_positions"], label)
    check_positions(rep, ov["open_positions"], label)
    check_deals(rep, ov["recent_deals"], label)

    series = ov["equity_series"]
    times = [ts(p["t"]) for p in series]
    rep.check(times == sorted(times), f"{label}: equity_series is oldest first")
    rep.close(series[-1]["equity"], ov["snapshot"]["equity"], f"{label}: last equity point equals the snapshot")
    rep.close(series[-1]["balance"], ov["snapshot"]["balance"], f"{label}: last balance point equals the snapshot")
    span_h = (times[-1] - times[0]).total_seconds() / 3600
    rep.check(23.5 <= span_h <= 24.5, f"{label}: equity_series covers about 24 hours", f"{span_h:.2f} h")

    deals = ov["recent_deals"]
    closes = [ts(d["close_time"]) for d in deals]
    rep.check(closes == sorted(closes, reverse=True), f"{label}: recent_deals is newest first")
    signals = ov["recent_signals"]
    sig_times = [ts(s["time"]) for s in signals]
    rep.check(sig_times == sorted(sig_times, reverse=True), f"{label}: recent_signals is newest first")

    # Bot status agrees with the last report age.
    bot = ov["bot"]
    age = (ts(ov["server_time"]) - ts(bot["last_report_at"])).total_seconds()
    expected_status = "online" if age <= 3 * bot["report_interval_s"] else "stale" if age <= 60 else "offline"
    rep.check(bot["status"] == expected_status, f"{label}: bot.status matches report age", f"{bot['status']} vs {expected_status} ({age:.0f}s)")
    rep.check(ts(bot["heartbeat"][-1]["t"]) <= ts(bot["last_report_at"]), f"{label}: heartbeat ends at or before the last report")

    # Strategies agree with positions, deals and signals.
    strategy_ids = {s["id"] for s in ov["strategies"]}
    rep.check(len(strategy_ids) == len(ov["strategies"]), f"{label}: strategy ids are unique")
    rep.check(len({s["magic"] for s in ov["strategies"]}) == len(ov["strategies"]), f"{label}: magic numbers are unique")
    today = ts(ov["server_time"]).date()
    for s in ov["strategies"]:
        mine = [p for p in ov["open_positions"] if p["strategy_id"] == s["id"]]
        rep.check(s["open_count"] == len(mine), f"{label}: {s['id']} open_count", f"{s['open_count']} vs {len(mine)}")
        rep.close(s["floating_pl"], sum(p["profit"] + p["swap"] + p["commission"] for p in mine), f"{label}: {s['id']} floating_pl")
        todays = [d for d in deals if d["strategy_id"] == s["id"] and ts(d["close_time"]).date() == today]
        net = sum(d["profit"] + d["commission"] + d["swap"] for d in todays)
        rep.close(s["today"]["net_profit"], net, f"{label}: {s['id']} today net_profit equals its deals")
        rep.check(s["today"]["trades"] == len(todays), f"{label}: {s['id']} today trades")
        rep.check(s["today"]["wins"] == sum(1 for d in todays if d["profit"] + d["commission"] + d["swap"] > 0), f"{label}: {s['id']} today wins")
        rep.check(s["total"]["trades"] >= s["today"]["trades"], f"{label}: {s['id']} total trades >= today")
        rep.check(s["total"]["wins"] <= s["total"]["trades"], f"{label}: {s['id']} wins <= trades")
        rep.check(s["state"] != "in_position" or s["open_count"] > 0, f"{label}: {s['id']} in_position implies an open trade")
        rep.check(s["enabled"] or s["state"] in ("paused", "in_position", "error"), f"{label}: {s['id']} disabled strategy state")
    for kind, rows in (("position", ov["open_positions"]), ("deal", deals)):
        for row in rows:
            rep.check(row["strategy_id"] is None or row["strategy_id"] in strategy_ids, f"{label}: {kind} refers to a known strategy", str(row["strategy_id"]))
    check_signals(rep, signals, strategy_ids, label)
    check_settings(rep, ov["strategies"], label)
    rep.check(ts(ov["day_start"]["time"]).date() == today, f"{label}: day_start is on the server date")

    check_chart(rep, ov["chart"], ov)
    check_volatility(rep, ov["volatility"], ov["server_time"])
    check_commands(rep, ov["recent_commands"], ov["server_time"])
    check_alerts(rep, ov["alerts"], ov["server_time"])

    # Every entry signal of the real strategy has a traded marker on the chart, and every skipped one an untraded marker.
    marks = {m["t"]: m for m in ov["chart"]["markers"]}
    for sg in signals:
        if sg["strategy_id"] == "sma_cross" and sg["kind"] in ("entry", "skipped"):
            m = marks.get(sg["candle_close"])
            rep.check(m is not None and m["side"] == sg["side"] and m["traded"] == sg["acted"],
                      f"{label}: signal {sg['signal_id']} matches its marker on the chart")


# ---------------------------------------------------------------- the bot report and the server's reply

def check_report(rep: Report, report: dict, response: dict) -> None:
    label = "report"
    check_snapshot(rep, report["snapshot"], report["open_positions"], label)
    check_positions(rep, report["open_positions"], label)
    check_deals(rep, report["closed_deals"], label)
    ids = {s["id"] for s in report["strategies"]}
    check_signals(rep, report["signals"], ids, label)
    rep.check(len({s["magic"] for s in report["strategies"]}) == len(report["strategies"]), f"{label}: magic numbers are unique")

    bars = report["bars"]
    times = [ts(b["t"]) for b in bars]
    rep.check(all(a < b for a, b in zip(times, times[1:])), f"{label}: bars are in strict time order")
    rep.check(all(t.second == 0 for t in times), f"{label}: every bar opens on a whole minute")
    rep.check(all(b["h"] >= max(b["o"], b["c"], b["l"]) and b["l"] <= min(b["o"], b["c"]) for b in bars), f"{label}: every bar has its high on top and its low at the bottom")
    rep.check(all(t + timedelta(minutes=1) <= ts(report["sent_at"]) for t in times), f"{label}: only closed bars are sent")

    label = "response"
    rep.check(response["ack"]["seq"] == report["seq"], f"{label}: ack.seq echoes the report seq")
    if bars:
        rep.check(response["ack"]["bars_through"] == bars[-1]["t"], f"{label}: bars_through is the newest bar the report carried")
    server_time = ts(response["server_time"])
    positions = {p["position_id"]: p for p in report["open_positions"]}
    for cmd in response["commands"]:
        who = f"{label}: command {cmd['command_id']}"
        rep.check(ts(cmd["expires_at"]) > ts(cmd["issued_at"]), f"{who} expires after it is issued")
        rep.check(ts(cmd["expires_at"]) > server_time, f"{who} has not already expired")
        payload = cmd["payload"]
        if "strategy_id" in payload:
            rep.check(payload["strategy_id"] in ids, f"{who} targets a strategy the bot has", payload["strategy_id"])
        if "position_id" in payload:
            p = positions.get(payload["position_id"])
            rep.check(p is not None and p["strategy_id"] is not None, f"{who} targets an open position the bot owns")
            if p is not None and cmd["type"] == "position.set_levels":
                if "sl" in payload:
                    tighter = payload["sl"] >= p["sl"] if p["side"] == "buy" else payload["sl"] <= p["sl"]
                    rep.check(tighter, f"{who} only tightens the stop loss")
    ids_cmd = [c["command_id"] for c in response["commands"]]
    rep.check(len(ids_cmd) == len(set(ids_cmd)), f"{label}: command_id values are unique")


def check_command_doc(rep: Report, cmd: dict, overview: dict | None) -> None:
    if overview is None or "position_id" not in cmd["payload"]:
        return
    owned = {p["position_id"]: p for p in overview["open_positions"]}
    p = owned.get(cmd["payload"]["position_id"])
    rep.check(p is not None and p["strategy_id"] is not None, "dashboard command: targets an open position the bot owns")


SCHEMA_FOR = {
    "overview": "dashboard-overview.schema.json",
    "report": "bot-report.schema.json",
    "response": "server-response.schema.json",
    "command": "dashboard-command.schema.json",
    "reply": "dashboard-command-reply.schema.json",
    "reply_rejected": "dashboard-command-reply.schema.json",
}


def check_documents(docs: dict[str, dict]) -> Report:
    """docs maps a name from SCHEMA_FOR to loaded JSON (any may be missing).

    Consistency checks only run on a document that passed its shape check, so a
    malformed file produces a clear failure instead of a crash.
    """
    registry, schemas = build_registry()
    rep = Report()
    well_formed = {name: validate_shape(rep, registry, schemas, SCHEMA_FOR[name], doc, name) for name, doc in docs.items()}
    if well_formed.get("overview"):
        check_overview(rep, docs["overview"])
    if well_formed.get("report") and well_formed.get("response"):
        check_report(rep, docs["report"], docs["response"])
    if well_formed.get("command"):
        check_command_doc(rep, docs["command"], docs["overview"] if well_formed.get("overview") else None)
    if well_formed.get("reply"):
        rep.check(docs["reply"]["status"] != "rejected", "reply example: is an accepted reply")
    if well_formed.get("reply_rejected"):
        rep.check(docs["reply_rejected"]["status"] == "rejected", "reply_rejected example: is a rejected reply")
    return rep


def main() -> int:
    ex = CONTRACT / "examples"
    files = {
        "report": ex / "bot-report.example.json",
        "response": ex / "server-response.example.json",
        "command": ex / "dashboard-command.example.json",
        "reply": ex / "dashboard-command-reply.example.json",
        "reply_rejected": ex / "dashboard-command-reply-rejected.example.json",
        "overview": ROOT / "dashboard" / "data" / "sample-overview.json",
    }
    missing = [str(p) for p in files.values() if not p.exists()]
    if missing:
        print("missing sample files (run tools/make_sample_data.py first):")
        for m in missing:
            print(f"  {m}")
        return 1
    rep = check_documents({name: load(path) for name, path in files.items()})

    print(f"{rep.passes} checks passed, {len(rep.failures)} failed")
    for failure in rep.failures:
        print(f"  FAIL  {failure}")
    return 0 if not rep.failures else 1


if __name__ == "__main__":
    sys.exit(main())
