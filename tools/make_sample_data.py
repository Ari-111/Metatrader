#!/usr/bin/env python3
"""Generate the sample data used by the dashboard mock-up and the contract examples (contract v0.2).

Run from anywhere:  python -P tools/make_sample_data.py

The market is real: 1-minute XAUUSD bars exported from the MT5 tester (research/data/xauusd_m1.csv, made
with tools/export_m1.mq5). The account is simulated and deterministic:

  - sma_cross follows the written rule in docs/sma-cross-spec.md on those real bars. Every cross comes from
    tools/sma_reference.py; trades open only inside the trading hours, close on the opposite cross, or at the
    take profit (300 pips) or stop loss (100 pips) using each bar's high and low. This is a replay on
    1-minute bars, NOT an MT5 tester result and NOT a promise of future results.
  - rsi_revert and range_break are invented strategies that enter at random times on the same real prices.
    They only exist to show a library with more than one strategy.

Because everything comes from one simulation, the totals add up exactly, which tools/validate_contract.py
checks. The volatility block comes from tools/volatility_model.py (a real model run on the same bars).

Writes:
  dashboard/data/sample-overview.json   (what the dashboard reads)
  dashboard/data/sample-overview.js     (same data as a script, so index.html opens from disk)
  contract/examples/*.example.json      (one example per message type)
"""
from __future__ import annotations

import json
import math
import random
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
import sma_reference as ref          # noqa: E402  (the written rule, as code)
import volatility_model as vol       # noqa: E402

UTC = timezone.utc

# ---- The world ------------------------------------------------------------------
SYMBOL = "XAUUSD"            # real name depends on the Exness account type (still to be confirmed)
CONTRACT_SIZE = 100          # 1 lot = 100 oz
SPREAD = 0.30                # ask = bid + 0.30 (sample value; real spreads vary and widen on news)
LEVERAGE = 200
START_BALANCE = 10_000.00
COMMISSION_PER_LOT_SIDE = 3.00
LOGIN = 70234561
SERVER = "Exness-MT5Trial"
BOT_VERSION = "0.5.0"
PLATFORM_BUILD = 6308

NOW = datetime(2026, 10, 15, 23, 30, 10, tzinfo=UTC)         # a Thursday evening: 05:00 IST Friday, inside the trading hours
LAST_REPORT = datetime(2026, 10, 15, 23, 30, 7, tzinfo=UTC)
PATH_START = datetime(2026, 8, 24, tzinfo=UTC)                # a Monday
DAY_START = datetime(2026, 10, 15, tzinfo=UTC)
REPORT_INTERVAL_S = 5
NAIVE_NOW = NOW.replace(tzinfo=None)

SEED = 9  # found by the search (set to None to search again); pinned so the sample never changes by accident


@dataclass(frozen=True)
class Strat:
    id: str
    name: str
    version: str
    magic: int
    lots: float
    sl: float            # stop distance in dollars of gold price
    tp: float
    hold_min: int        # longest a random trade is held (unused for sma_cross)
    per_day: tuple[int, ...]
    # key, label, value, unit, min, max, step, editable
    settings: tuple[tuple[str, str, object, str | None, float | None, float | None, float | None, bool], ...]


STRATS = (
    Strat("sma_cross", "SMA 100/5000 cross (gold)", "0.1.0", 550011, 0.01, 10.0, 30.0, 0, (0,),
          (("fast_period", "Fast average", 100, "1-min bars", None, None, None, False),
           ("slow_period", "Slow average", 5000, "1-min bars", None, None, None, False),
           ("take_profit_pips", "Take profit", 300, "pips", 20, 1000, 10, True),
           ("stop_loss_pips", "Stop loss", 100, "pips", 20, 500, 10, True),
           ("next_lot", "Next trade lot", 0.01, "lots", 0.01, 0.10, 0.01, True),
           ("max_lot", "Largest lot allowed", 0.10, "lots", 0.01, 1.00, 0.01, True),
           ("use_trading_hours", "Trade only in set hours", True, None, None, None, None, True),
           ("hours_start_ist", "Hours start (IST)", 210, "min", 0, 1439, 1, True),
           ("hours_end_ist", "Hours end (IST)", 660, "min", 0, 1439, 1, True),
           ("near_lines_pips", "Heads-up when lines are this close", 0, "pips", 0, 200, 5, True))),
    Strat("rsi_revert", "RSI Reversion", "0.9.1", 102001, 0.05, 6.0, 4.0, 240, (2, 3),
          (("rsi_period", "RSI period", 14, "bars", 2, 50, 1, True),
           ("oversold_level", "Buy below RSI", 30, None, 5, 45, 1, True),
           ("overbought_level", "Sell above RSI", 70, None, 55, 95, 1, True),
           ("lots", "Trade size", 0.05, "lots", 0.01, 1.00, 0.01, True),
           ("stop_loss", "Stop loss distance", 6.00, "USD", 1, 50, 0.5, True),
           ("take_profit", "Take profit distance", 4.00, "USD", 1, 100, 0.5, True),
           ("max_open", "Most open trades", 2, None, 1, 5, 1, True))),
    Strat("range_break", "Range Breakout", "1.0.0", 103001, 0.05, 5.0, 10.0, 360, (1, 2),
          (("range_start", "Range starts", "07:00 UTC", None, None, None, None, False),
           ("range_end", "Range ends", "08:00 UTC", None, None, None, None, False),
           ("lots", "Trade size", 0.05, "lots", 0.01, 1.00, 0.01, True),
           ("stop_loss", "Stop loss distance", 5.00, "USD", 1, 50, 0.5, True),
           ("take_profit", "Take profit distance", 10.00, "USD", 1, 100, 0.5, True),
           ("max_open", "Most open trades", 1, None, 1, 5, 1, True))),
)
BY_ID = {s.id: s for s in STRATS}
SMA = BY_ID["sma_cross"]
RANDOM_STRATS = tuple(s for s in STRATS if s.id != "sma_cross")
SETTINGS_REV = {"sma_cross": 3, "rsi_revert": 4, "range_break": 2}

# Today's story for the invented strategies (UTC): trades that already closed.
TODAY_CLOSED = (
    ("rsi_revert", "08:20", "buy"), ("rsi_revert", "10:40", "sell"),
    ("range_break", "07:20", "buy"),
)


# ---- Helpers --------------------------------------------------------------------
def iso(dt) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def money(x: float) -> float:
    return round(x, 2) + 0.0  # + 0.0 turns -0.0 into 0.0


def idx(t: datetime) -> int:
    return int((t - PATH_START).total_seconds() // 60)


def at(day: datetime, hhmm: str) -> datetime:
    h, m = hhmm.split(":")
    return day.replace(hour=int(h), minute=int(m))


def minute_time(i: int) -> datetime:
    return PATH_START + timedelta(minutes=i)


# ---- Real market data ------------------------------------------------------------
def load_market() -> dict:
    csv = ref.DEFAULT_CSV
    if not csv.exists():
        sys.exit(f"missing {csv}\nexport the bars first: run tools/export_m1.mq5 in the MT5 Strategy Tester (see README.md)")
    df = ref.load_m1(csv)
    df = df[df.index < pd.Timestamp(NAIVE_NOW)]
    grid = pd.date_range(PATH_START.replace(tzinfo=None), NAIVE_NOW, freq="min")
    b = df.reindex(grid)
    close = b["close"].ffill().bfill()
    for col in ("open", "high", "low"):
        b[col] = b[col].fillna(close)
    b["close"] = close
    return {"df": df, "O": b["open"].to_numpy(), "H": b["high"].to_numpy(), "L": b["low"].to_numpy(), "C": b["close"].to_numpy()}


MARKET = load_market()
O, H, L, C = MARKET["O"], MARKET["H"], MARKET["L"], MARKET["C"]
PATH = [float(x) for x in C]       # minute-by-minute close, used by the invented strategies


# ---- Trade simulation ------------------------------------------------------------
def simulate(s: Strat, side: str, lots: float, t_open: datetime, force_close: datetime | None) -> dict:
    """Invented strategies: open at t_open, walk the close path until stop, target, or the forced close."""
    i0 = idx(t_open)
    bid0 = PATH[i0]
    open_price = round(bid0 + SPREAD, 2) if side == "buy" else round(bid0, 2)
    if side == "buy":
        sl, tp = round(open_price - s.sl, 2), round(open_price + s.tp, 2)
    else:
        sl, tp = round(open_price + s.sl, 2), round(open_price - s.tp, 2)
    last = idx(NOW) if force_close is None else min(idx(force_close), idx(NOW))
    trade = {"strat": s, "side": side, "lots": lots, "open_time": t_open, "open_price": open_price,
             "sl": sl, "sl_original": sl, "tp": tp, "close_time": None, "close_price": None, "reason": None}
    for j in range(i0 + 1, last + 1):
        bid = PATH[j]
        ask = round(bid + SPREAD, 2)
        t = minute_time(j)
        hit_sl, hit_tp = (bid <= sl, bid >= tp) if side == "buy" else (ask >= sl, ask <= tp)
        if hit_sl:
            trade.update(close_time=t, close_price=sl, reason="stop_loss")
            return trade
        if hit_tp:
            trade.update(close_time=t, close_price=tp, reason="take_profit")
            return trade
    if force_close is not None:
        j = min(idx(force_close), idx(NOW))
        bid = PATH[j]
        price = bid if side == "buy" else round(bid + SPREAD, 2)
        trade.update(close_time=minute_time(j), close_price=price, reason="bot")
    return trade


def simulate_real(side: str, t_open: datetime, i_cross: int | None) -> dict:
    """sma_cross on real bars. Opens at the open of its minute. Each later bar is checked with its high and low
    (stop first if both fall inside one bar). The opposite cross closes it at the open of the cross bar."""
    i0 = idx(t_open)
    open_price = round(O[i0] + SPREAD, 2) if side == "buy" else round(O[i0], 2)
    sl_d, tp_d = SMA.sl, SMA.tp
    if side == "buy":
        sl, tp = round(open_price - sl_d, 2), round(open_price + tp_d, 2)
    else:
        sl, tp = round(open_price + sl_d, 2), round(open_price - tp_d, 2)
    trade = {"strat": SMA, "side": side, "lots": SMA.lots, "open_time": t_open, "open_price": open_price,
             "sl": sl, "sl_original": sl, "tp": tp, "close_time": None, "close_price": None, "reason": None}
    end = (i_cross - 1) if i_cross is not None else idx(NOW) - 1
    if end >= i0:
        seg = slice(i0, end + 1)
        if side == "buy":
            hit_sl, hit_tp = L[seg] <= sl, H[seg] >= tp
        else:
            hit_sl, hit_tp = H[seg] + SPREAD >= sl, L[seg] + SPREAD <= tp
        j_sl = int(np.argmax(hit_sl)) if hit_sl.any() else None
        j_tp = int(np.argmax(hit_tp)) if hit_tp.any() else None
        if j_sl is not None or j_tp is not None:
            stop_first = j_tp is None or (j_sl is not None and j_sl <= j_tp)
            j = j_sl if stop_first else j_tp
            trade.update(close_time=minute_time(i0 + j) + timedelta(seconds=30), close_price=sl if stop_first else tp,
                         reason="stop_loss" if stop_first else "take_profit")
            return trade
    if i_cross is not None:
        bid = O[i_cross]
        price = round(bid, 2) if side == "buy" else round(bid + SPREAD, 2)
        trade.update(close_time=minute_time(i_cross), close_price=price, reason="bot")
    return trade


def gross(t: dict, price: float) -> float:
    direction = 1 if t["side"] == "buy" else -1
    return (price - t["open_price"]) * direction * t["lots"] * CONTRACT_SIZE


def net_closed(t: dict) -> float:
    return gross(t, t["close_price"]) - 2 * COMMISSION_PER_LOT_SIDE * t["lots"]


def real_crosses() -> pd.DataFrame:
    sig = ref.find_signals(MARKET["df"])
    return sig[(sig["act_at"] >= pd.Timestamp(PATH_START.replace(tzinfo=None))) & (sig["act_at"] < pd.Timestamp(NAIVE_NOW))].reset_index(drop=True)


def sma_world() -> tuple[list[dict], list[dict]]:
    """The real strategy on real bars: its trades and the signals that came with them."""
    crosses = real_crosses()
    jitter = random.Random(7)
    trades: list[dict] = []
    signals: list[dict] = []
    rows = list(crosses.itertuples(index=False))
    for k, c in enumerate(rows):
        act = c.act_at.to_pydatetime().replace(tzinfo=UTC)
        when = act + timedelta(seconds=jitter.randint(0, 2))
        nxt = idx(rows[k + 1].act_at.to_pydatetime().replace(tzinfo=UTC)) if k + 1 < len(rows) else None
        word = "above" if c.side == "buy" else "below"
        if ref.in_session(c.act_at):
            tr = simulate_real(c.side, when, nxt)
            tr["entry_candle"] = act
            trades.append(tr)
            signals.append({"strategy_id": "sma_cross", "time": when, "candle": act, "kind": "entry", "side": c.side, "acted": True,
                            "lot": SMA.lots, "reason": f"SMA 100 crossed {word} SMA 5000 on the {act:%H:%M} candle."})
        else:
            signals.append({"strategy_id": "sma_cross", "time": when, "candle": act, "kind": "skipped", "side": c.side, "acted": False,
                            "lot": None, "reason": "Outside trading hours (03:30 to 11:00 IST)."})
    for tr in trades:
        if tr["reason"] == "bot":
            back = "below" if tr["side"] == "buy" else "above"
            signals.append({"strategy_id": "sma_cross", "time": tr["close_time"], "candle": tr["close_time"].replace(second=0), "kind": "exit",
                            "side": None, "acted": True, "lot": None, "reason": f"Closed: SMA 100 crossed back {back} SMA 5000."})
    return trades, signals


# ---- Build one world ---------------------------------------------------------------
def build(seed: int) -> dict | None:
    """Simulate everything for one seed. Returns None if the story does not hold."""
    rng = random.Random(seed)
    sma_trades, sma_signals = sma_world()
    trades: list[dict] = list(sma_trades)

    day = PATH_START
    while day < DAY_START:
        if day.weekday() < 5:
            for s in RANDOM_STRATS:
                n = rng.choice(s.per_day)
                for m in sorted(rng.sample(range(7 * 60, 17 * 60), n)):
                    t_open = day + timedelta(minutes=m)
                    side = rng.choice(("buy", "sell"))
                    hold = rng.randint(30, s.hold_min)
                    force = min(t_open + timedelta(minutes=hold), day + timedelta(hours=20))
                    trades.append(simulate(s, side, s.lots, t_open, force))
        day += timedelta(days=1)
    for sid, hhmm, side in TODAY_CLOSED:
        s = BY_ID[sid]
        t_open = at(DAY_START, hhmm)
        hold = rng.randint(45, 200)
        force = min(t_open + timedelta(minutes=hold), NOW - timedelta(minutes=5))
        trades.append(simulate(s, side, s.lots, t_open, force))

    opens = [t for t in trades if t["close_time"] is None]
    closed = [t for t in trades if t["close_time"] is not None]
    if len(opens) != 1 or opens[0]["strat"].id != "sma_cross":
        return None

    bid_now = float(C[idx(NOW)])

    def current(t: dict) -> float:
        return round(bid_now, 2) if t["side"] == "buy" else round(bid_now + SPREAD, 2)

    totals = {s.id: sum(net_closed(t) for t in closed if t["strat"] is s) for s in STRATS}
    today = {s.id: sum(net_closed(t) for t in closed if t["strat"] is s and t["close_time"] >= DAY_START) for s in STRATS}
    ok = (totals["rsi_revert"] > 30 and totals["range_break"] < -40 and today["rsi_revert"] < 0
          and sum(1 for t in closed if t["strat"] is SMA) >= 5)
    if not ok:
        return None
    return {"seed": seed, "trades": trades, "opens": opens, "closed": closed, "current": current, "sma_signals": sma_signals}


def find_world() -> dict:
    if SEED is not None:
        world = build(SEED)
        if world is None:
            sys.exit(f"SEED {SEED} no longer produces the intended story; clear SEED to search again")
        return world
    for seed in range(1, 20_000):
        world = build(seed)
        if world is not None:
            print(f"story found with seed {seed}; set SEED = {seed} to pin it")
            return world
    sys.exit("no seed produced the intended story")


# ---- Chart and volatility blocks (all real) -------------------------------------
TIMEFRAMES = (("1m", "1min", 240), ("5m", "5min", 240), ("30m", "30min", 240), ("1h", "1h", 240), ("4h", "4h", 240), ("1d", "1D", 240), ("1mo", "MS", None))


def num_or_none(x, nd=3):
    return None if (x is None or (isinstance(x, float) and math.isnan(x))) else round(float(x), nd)


def chart_block() -> dict:
    df = MARKET["df"]
    fast, slow = ref.averages(df["close"])
    state = pd.DataFrame({"f": fast, "s": slow})
    sets = {}
    for key, rule, n in TIMEFRAMES:
        cb = ref.coarse(df, rule)
        st = state.resample(rule, closed="left", label="left").last().reindex(cb.index)
        if n:
            cb, st = cb.tail(n), st.tail(n)
        sets[key] = {
            "t": [iso(t) for t in cb.index],
            "o": [round(float(x), 2) for x in cb["open"]], "h": [round(float(x), 2) for x in cb["high"]],
            "l": [round(float(x), 2) for x in cb["low"]], "c": [round(float(x), 2) for x in cb["close"]],
            "fast": [num_or_none(x) for x in st["f"]], "slow": [num_or_none(x) for x in st["s"]],
        }
    crosses = ref.find_signals(df)
    crosses = crosses[crosses["act_at"] < pd.Timestamp(NAIVE_NOW)]
    markers = []
    for c in crosses.itertuples(index=False):
        traded = ref.in_session(c.act_at)
        markers.append({"t": iso(c.act_at), "side": c.side, "traded": bool(traded), "note": None if traded else "Outside trading hours"})
    last = crosses.iloc[-1]
    f_now, s_now = float(fast.iloc[-1]), float(slow.iloc[-1])
    return {
        "symbol": SYMBOL, "anchor": "1m", "fast_period": ref.FAST, "slow_period": ref.SLOW,
        "as_of": iso(df.index[-1] + pd.Timedelta(minutes=1)),
        "latest": {"fast": round(f_now, 3), "slow": round(s_now, 3), "gap": round(f_now - s_now, 3),
                   "last_cross": {"time": iso(last["act_at"]), "side": last["side"]}},
        "timeframes": sets, "markers": markers,
    }


def volatility_doc() -> dict:
    v = vol.volatility_block(MARKET["df"], pd.Timestamp(NAIVE_NOW))
    rows = []
    for sc in v["scorecard"]:
        rows.append({
            "horizon_h": sc["horizon_h"], "samples": sc["samples"],
            "error_model_pct": round(sc["error_model_pct"], 1), "error_persist_pct": round(sc["error_persist_pct"], 1),
            "error_tod_pct": round(sc["error_tod_pct"], 1), "error_avg90_pct": round(sc["error_avg90_pct"], 1),
            "hit_rate": round(sc["hit_rate"], 3), "hit_rate_tod": round(sc["hit_rate_tod"], 3), "base_rate": round(sc["base_rate"], 3),
            "brier_model": round(sc["brier_model"], 3), "brier_tod": round(sc["brier_tod"], 3), "brier_base": round(sc["brier_base"], 3),
            "verdict": vol.verdict(sc),
            "calibration": [{"label": b["label"], "n": b["n"], "said": None if b["said"] is None else round(b["said"], 2),
                             "happened": None if b["happened"] is None else round(b["happened"], 2)} for b in sc["buckets"]],
        })
    return {
        "as_of": iso(v["as_of"]), "unit": v["unit"], "now": v["now"], "forecasts": v["forecasts"],
        "history": {"t": [iso(t) for t in v["history"]["t"]], "value": v["history"]["value"]},
        "scorecard": {"tested_from": iso(min(sc["from"] for sc in v["scorecard"])), "tested_to": iso(max(sc["to"] for sc in v["scorecard"])),
                      "note": "Each forecast uses only data from before it. The model is refitted every month, and a forecast is made every 3 hours, so neighbouring forecasts overlap.",
                      "rows": rows},
        "events": [
            {"time": "2026-10-16T12:30:00Z", "title": "Sample event: US data release", "impact": "high", "currency": "USD"},
            {"time": "2026-10-16T18:00:00Z", "title": "Sample event: central bank speaker", "impact": "medium", "currency": "USD"},
        ],
    }


# ---- Turn the simulation into contract messages -----------------------------------
def make_documents(world: dict) -> dict:
    trades, opens, closed, current = world["trades"], world["opens"], world["closed"], world["current"]
    rng = random.Random(world["seed"] * 7 + 1)

    position_ids: dict[int, int] = {}
    pid = 4_205_117_301
    for t in sorted(trades, key=lambda t: t["open_time"]):
        pid += rng.randint(1, 6)
        position_ids[id(t)] = pid
    deal_ids: dict[int, int] = {}
    did = 3_908_220_044
    for t in sorted(closed, key=lambda t: t["close_time"]):
        did += rng.randint(1, 5)
        deal_ids[id(t)] = did

    def deal_doc(t: dict) -> dict:
        s = t["strat"]
        return {
            "deal_id": deal_ids[id(t)], "position_id": position_ids[id(t)], "strategy_id": s.id, "magic": s.magic,
            "symbol": SYMBOL, "side": t["side"], "volume": t["lots"],
            "open_time": iso(t["open_time"]), "close_time": iso(t["close_time"]),
            "open_price": t["open_price"], "close_price": t["close_price"],
            "profit": money(gross(t, t["close_price"])), "commission": money(-2 * COMMISSION_PER_LOT_SIDE * t["lots"]),
            "swap": 0.0, "close_reason": t["reason"],
        }

    def position_doc(t: dict) -> dict:
        s = t["strat"]
        price = current(t)
        return {
            "position_id": position_ids[id(t)], "strategy_id": s.id, "magic": s.magic, "symbol": SYMBOL,
            "side": t["side"], "volume": t["lots"], "volume_locked": True, "open_time": iso(t["open_time"]),
            "open_price": t["open_price"], "current_price": price, "sl": t["sl"], "sl_original": t["sl_original"], "tp": t["tp"],
            "profit": money(gross(t, price)), "swap": 0.0, "commission": money(-COMMISSION_PER_LOT_SIDE * t["lots"]),
        }

    deals_all = sorted((deal_doc(t) for t in closed), key=lambda d: d["close_time"], reverse=True)
    positions = [position_doc(t) for t in sorted(opens, key=lambda t: t["open_time"])]

    def net_of(d: dict) -> float:
        return d["profit"] + d["commission"] + d["swap"]

    deal_by_time = sorted(((datetime.fromisoformat(d["close_time"]), net_of(d)) for d in deals_all), key=lambda x: x[0])

    def balance_at(t: datetime) -> float:
        return START_BALANCE + sum(n for ts, n in deal_by_time if ts <= t)

    def floating_at(t: datetime) -> float:
        total = 0.0
        bid = float(C[idx(t)])
        for tr in trades:
            if tr["open_time"] <= t and (tr["close_time"] is None or tr["close_time"] > t):
                price = bid if tr["side"] == "buy" else bid + SPREAD
                total += gross(tr, price) - COMMISSION_PER_LOT_SIDE * tr["lots"]
        return total

    balance = money(balance_at(NOW))
    floating = money(sum(p["profit"] + p["swap"] + p["commission"] for p in positions))
    equity = money(balance + floating)
    mid = float(C[idx(NOW)]) + SPREAD / 2
    margin = money(sum(p["volume"] * CONTRACT_SIZE * mid / LEVERAGE for p in positions))
    snapshot = {"balance": balance, "equity": equity, "margin": margin, "free_margin": money(equity - margin),
                "margin_level": round(equity / margin * 100, 1), "floating_pl": floating}

    series: list[dict] = []
    t = NOW.replace(minute=30, second=0) - timedelta(hours=24)
    while t <= NOW.replace(minute=30, second=0):
        bal = balance_at(t)
        series.append({"t": iso(t), "balance": money(bal), "equity": money(bal + floating_at(t))})
        t += timedelta(minutes=5)
    series.append({"t": iso(LAST_REPORT), "balance": balance, "equity": equity})

    start_bal = money(balance_at(DAY_START))
    day_start = {"time": iso(DAY_START), "balance": start_bal, "equity": money(start_bal + floating_at(DAY_START))}

    # Strategy tallies and settings.
    strategies_overview, strategies_report = [], []
    for s in STRATS:
        mine = [d for d in deals_all if d["strategy_id"] == s.id]
        todays = [d for d in mine if d["close_time"] >= iso(DAY_START)]
        my_pos = [p for p in positions if p["strategy_id"] == s.id]
        enabled = s.id != "range_break"
        state = "in_position" if my_pos else ("idle" if enabled else "paused")
        strategies_overview.append({
            "id": s.id, "name": s.name, "version": s.version, "magic": s.magic, "enabled": enabled, "state": state,
            "symbols": [SYMBOL], "settings_rev": SETTINGS_REV[s.id],
            "settings": [{"key": k, "label": label, "value": v, "unit": u, "min": lo, "max": hi, "step": st, "editable": ed}
                         for k, label, v, u, lo, hi, st, ed in s.settings],
            "today": {"net_profit": money(sum(net_of(d) for d in todays)), "trades": len(todays), "wins": sum(1 for d in todays if net_of(d) > 0)},
            "total": {"net_profit": money(sum(net_of(d) for d in mine)), "trades": len(mine), "wins": sum(1 for d in mine if net_of(d) > 0)},
            "open_count": len(my_pos),
            "floating_pl": money(sum(p["profit"] + p["swap"] + p["commission"] for p in my_pos)),
        })
        strategies_report.append({
            "id": s.id, "version": s.version, "magic": s.magic, "enabled": enabled, "state": state,
            "settings_rev": SETTINGS_REV[s.id], "symbols": [SYMBOL], "error": None,
        })

    # Signals: the real ones for sma_cross, plus entries, bot exits and skips for the invented strategies.
    raw: list[dict] = list(world["sma_signals"])

    def entry_reason(sid: str, side: str) -> str:
        if sid == "rsi_revert":
            return f"RSI (14) fell to {rng.randint(22, 29)}, below 30" if side == "buy" else f"RSI (14) rose to {rng.randint(71, 78)}, above 70"
        return "Price broke above the 07:00 to 08:00 range high" if side == "buy" else "Price broke below the 07:00 to 08:00 range low"

    exit_reason = {"rsi_revert": "RSI returned to 50", "range_break": "Price fell back inside the opening range"}
    for tr in trades:
        sid = tr["strat"].id
        if sid == "sma_cross":
            continue
        raw.append({"strategy_id": sid, "time": tr["open_time"], "candle": tr["open_time"], "kind": "entry", "side": tr["side"], "acted": True,
                    "lot": tr["lots"], "reason": entry_reason(sid, tr["side"])})
        if tr["close_time"] is not None and tr["reason"] == "bot":
            raw.append({"strategy_id": sid, "time": tr["close_time"], "candle": tr["close_time"], "kind": "exit", "side": None, "acted": True,
                        "lot": None, "reason": exit_reason[sid]})
    for sid, when, side, why in (("range_break", datetime(2026, 10, 15, 11, 5, tzinfo=UTC), "buy", "Strategy is switched off"),
                                 ("rsi_revert", datetime(2026, 10, 15, 12, 30, tzinfo=UTC), "sell", "Spread of 3.8 is above the limit of 3.0")):
        raw.append({"strategy_id": sid, "time": when, "candle": when, "kind": "skipped", "side": side, "acted": False, "lot": None, "reason": why})
    raw = [r for r in raw if r["time"] <= LAST_REPORT]
    raw.sort(key=lambda r: r["time"], reverse=True)
    signals = [{"signal_id": f"sig-{r['time']:%Y%m%d-%H%M%S}-{i:03d}", "strategy_id": r["strategy_id"], "time": iso(r["time"]),
                "candle_close": iso(r["candle"].replace(second=0)), "symbol": SYMBOL, "kind": r["kind"], "side": r["side"],
                "acted": r["acted"], "lot": r["lot"], "reason": r["reason"]} for i, r in enumerate(raw)]

    # Controls pressed on the dashboard.
    recent_commands = [
        {"command_id": "cmd-c41d0b7a95e2", "type": "strategy.update_settings", "summary": "Buy below RSI 28, sell above RSI 72 (RSI Reversion)",
         "issued_at": "2026-10-15T23:30:01Z", "expires_at": "2026-10-15T23:32:01Z", "status": "sent", "reason": None},
        {"command_id": "cmd-5be07a31d9c4", "type": "strategy.update_settings", "summary": "Next trade lot 0.01 (SMA 100/5000 cross)",
         "issued_at": "2026-10-15T22:05:03Z", "expires_at": "2026-10-15T22:07:03Z", "status": "applied", "reason": None},
        {"command_id": "cmd-8a12f6c0e7b3", "type": "strategy.set_enabled", "summary": "Switch off Range Breakout",
         "issued_at": "2026-10-15T21:15:40Z", "expires_at": "2026-10-15T21:17:40Z", "status": "applied", "reason": None},
        {"command_id": "cmd-2e90d4b8a617", "type": "position.close", "summary": "Close buy 0.05 lot (RSI Reversion)",
         "issued_at": "2026-10-15T14:40:12Z", "expires_at": "2026-10-15T14:42:12Z", "status": "expired",
         "reason": "The bot did not collect it within 2 minutes, so nothing was closed."},
    ]

    # Alerts that went out for the newest real events.
    alert_rows = []
    for sg in signals:
        if sg["strategy_id"] == "sma_cross" and sg["kind"] == "entry":
            ev = "buy_signal" if sg["side"] == "buy" else "sell_signal"
            for ch in ("mt5_push", "dashboard"):
                alert_rows.append({"time": sg["time"], "event": ev, "channel": ch, "delivered": True, "text": sg["reason"] + f" Opened {sg['lot']:.2f} lot."})
    for d in deals_all:
        if d["strategy_id"] == "sma_cross":
            word = {"take_profit": "take profit", "stop_loss": "stop loss", "bot": "the opposite cross"}.get(d["close_reason"], "manual close")
            alert_rows.append({"time": d["close_time"], "event": "trade_closed", "channel": "mt5_push", "delivered": True,
                               "text": f"{d['side'].capitalize()} {d['volume']:.2f} lot closed at {word}: {net_of(d):+.2f}."})
    alert_rows.sort(key=lambda a: a["time"], reverse=True)
    alerts = {
        "events": [
            {"id": "buy_signal", "label": "Buy signal", "enabled": True},
            {"id": "sell_signal", "label": "Sell signal", "enabled": True},
            {"id": "trade_closed", "label": "Trade closed", "enabled": True},
            {"id": "heads_up", "label": "Lines getting close", "enabled": False},
            {"id": "order_failed", "label": "Broker refused an order", "enabled": True},
            {"id": "bot_offline", "label": "Bot stopped reporting", "enabled": True},
        ],
        "channels": [
            {"id": "mt5_push", "label": "MT5 phone app", "status": "ready", "enabled": True, "note": "Sent by the bot itself. Needs your MetaQuotes ID in MT5, Tools, Options, Notifications."},
            {"id": "mt5_email", "label": "Email from MT5", "status": "needs_setup", "enabled": False, "note": "Add your email address in MT5, Tools, Options, Email."},
            {"id": "telegram", "label": "Telegram", "status": "needs_setup", "enabled": False, "note": "Needs the server and a bot token from BotFather."},
            {"id": "dashboard", "label": "This dashboard", "status": "ready", "enabled": True, "note": None},
            {"id": "tradingview", "label": "TradingView", "status": "external", "enabled": False, "note": "Create the alerts inside TradingView from the indicator."},
        ],
        "recent": alert_rows[:8],
    }

    missed = {11, 12, 37}
    heartbeat = [{"t": iso(LAST_REPORT - timedelta(seconds=REPORT_INTERVAL_S * (59 - i))), "ok": i not in missed} for i in range(60)]
    account = {"login": LOGIN, "server": SERVER, "currency": "USD", "mode": "demo", "margin_mode": "hedging", "leverage": LEVERAGE}

    overview = {
        "schema_version": "0.2", "server_time": iso(NOW), "account": account,
        "bot": {"status": "online", "version": BOT_VERSION, "latest_version": BOT_VERSION, "last_report_at": iso(LAST_REPORT),
                "report_interval_s": REPORT_INTERVAL_S, "trading_paused": False, "heartbeat": heartbeat},
        "snapshot": snapshot, "day_start": day_start, "equity_series": series, "open_positions": positions,
        "strategies": strategies_overview, "recent_deals": deals_all[:40], "recent_signals": signals[:10],
        "recent_commands": recent_commands, "chart": chart_block(), "volatility": volatility_doc(), "alerts": alerts,
    }

    # The matching bot report: what the bot would have sent at LAST_REPORT.
    cursor_deal = deals_all[2] if len(deals_all) > 2 else deals_all[-1]
    new_deals = [d for d in deals_all if d["close_time"] > cursor_deal["close_time"]]
    df = MARKET["df"]
    last_bars = [{"t": iso(t), "o": round(float(r.open), 2), "h": round(float(r.high), 2), "l": round(float(r.low), 2),
                  "c": round(float(r.close), 2), "v": int(r.tick_volume)} for t, r in df.tail(3).iterrows()]
    report = {
        "schema_version": "0.2", "sent_at": iso(LAST_REPORT), "seq": 48210, "boot_id": "b7c1e9d4a2f04e83",
        "bot": {"version": BOT_VERSION, "platform": "MT5", "platform_build": PLATFORM_BUILD},
        "account": account, "snapshot": snapshot, "trading_paused": False, "strategies": strategies_report, "open_positions": positions,
        "closed_deals": sorted(new_deals, key=lambda d: d["close_time"]),
        "signals": [],
        "bars": last_bars,
        "command_results": [{"command_id": "cmd-5be07a31d9c4", "status": "applied", "reason": None, "at": "2026-10-15T22:05:05Z"}],
    }
    response = {
        "schema_version": "0.2", "server_time": iso(LAST_REPORT),
        "ack": {"seq": report["seq"], "closed_through": max(d["close_time"] for d in deals_all), "bars_through": last_bars[-1]["t"],
                "command_results": ["cmd-5be07a31d9c4"]},
        "license": {"status": "active", "valid_until": "2026-11-15T00:00:00Z", "token": None},
        "update": {"latest_version": BOT_VERSION, "min_supported_version": "0.4.0"},
        "poll_interval_s": REPORT_INTERVAL_S,
        "commands": [{
            "command_id": "cmd-c41d0b7a95e2", "type": "strategy.update_settings",
            "issued_at": "2026-10-15T23:30:01Z", "expires_at": "2026-10-15T23:32:01Z", "issued_by": "usr_2f81c0",
            "payload": {"strategy_id": "rsi_revert", "settings_rev": 5, "settings": {"oversold_level": 28, "overbought_level": 72}},
        }],
    }
    open_id = positions[0]["position_id"]
    command = {"schema_version": "0.2", "client_request_id": "req-7d2f19c4e0a3", "type": "position.close", "payload": {"position_id": open_id}}
    reply = {"schema_version": "0.2", "status": "queued", "command_id": "cmd-e1a64f20b9d7", "expires_at": "2026-10-15T23:32:30Z", "reason": None}
    reply_rejected = {"schema_version": "0.2", "status": "rejected", "command_id": None, "expires_at": None,
                      "reason": "Lot 0.50 is above the largest lot allowed (0.10)."}
    return {"overview": overview, "report": report, "response": response, "command": command, "reply": reply, "reply_rejected": reply_rejected}


def write_json(path: Path, doc: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    world = find_world()
    docs = make_documents(world)
    data = ROOT / "dashboard" / "data"
    write_json(data / "sample-overview.json", docs["overview"])
    header = "// Generated by tools/make_sample_data.py from sample-overview.json. Do not edit by hand.\n"
    (data / "sample-overview.js").write_text(header + "window.SAMPLE_OVERVIEW = " + json.dumps(docs["overview"], indent=1) + ";\n", encoding="utf-8")
    ex = ROOT / "contract" / "examples"
    write_json(ex / "bot-report.example.json", docs["report"])
    write_json(ex / "server-response.example.json", docs["response"])
    write_json(ex / "dashboard-command.example.json", docs["command"])
    write_json(ex / "dashboard-command-reply.example.json", docs["reply"])
    write_json(ex / "dashboard-command-reply-rejected.example.json", docs["reply_rejected"])
    overview = docs["overview"]
    snap = overview["snapshot"]
    print(f"balance {snap['balance']:.2f}  equity {snap['equity']:.2f}  floating {snap['floating_pl']:+.2f}")
    for s in overview["strategies"]:
        print(f"  {s['id']:<12} today {s['today']['net_profit']:+8.2f} ({s['today']['trades']} trades)  total {s['total']['net_profit']:+9.2f} ({s['total']['trades']} trades)  {s['state']}")
    pos = overview["open_positions"][0]
    print(f"open: {pos['side']} {pos['volume']} {pos['symbol']} from {pos['open_price']} now {pos['current_price']}  sl {pos['sl']} tp {pos['tp']}  floating {pos['profit']:+.2f}")
    v = overview["volatility"]
    print(f"volatility now {v['now']['value']} USD/h ({v['now']['level']}, {v['now']['percentile']:.0%});  "
          + "; ".join(f"next {f['horizon_h']}h expected {f['expected']} (range {f['low']} to {f['high']}), higher than last: {f['prob_higher']:.0%}" for f in v["forecasts"]))
    print(f"{len(overview['recent_deals'])} recent deals, {len(overview['open_positions'])} open, {len(overview['equity_series'])} equity points, "
          f"{len(overview['recent_signals'])} signals, {len(overview['chart']['markers'])} chart markers")


if __name__ == "__main__":
    main()
