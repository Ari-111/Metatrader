"""Bot Console server (one person, one bot).

    cd D:\\Zerodha
    python -m uvicorn server.app:app --host 127.0.0.1 --port 8000

What it does
  - The MT5 bot posts a report every ~5 s to POST /v1/report (header X-Bot-Key). The reply carries the
    commands waiting for the bot. Every report is checked against contract/bot-report.schema.json.
  - The dashboard (served at /) reads GET /v1/overview and sends controls with POST /v1/accounts/1/commands.
    You must sign in first (password in server/config.json, session cookie).
  - Telegram messages go out for signals, closed trades, failed orders and a silent bot.
Contract: docs/data-contract.md (v0.2). Nothing here ever holds a broker password.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import queue
import secrets
import sqlite3
import sys
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import pandas as pd
from fastapi import Body, FastAPI, Header, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import sma_reference as ref  # noqa: E402
import validate_contract as vc  # noqa: E402

UTC = timezone.utc
DATA = ROOT / "server" / "data"
CONFIG_PATH = ROOT / "server" / "config.json"
DASH = ROOT / "dashboard"
PIP = 0.10
REPORT_INTERVAL_S = 5
COMMAND_LIFE_S = 120
BOT_LATEST = "0.6.0"
MAGIC = 550011
SYMBOL_FALLBACK = "XAUUSD"
lock = threading.RLock()


def now() -> datetime:
    return datetime.now(UTC)


def iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def parse(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


# ------------------------------------------------------------------ config
def load_config() -> dict:
    DATA.mkdir(parents=True, exist_ok=True)
    if CONFIG_PATH.exists():
        return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    password = secrets.token_urlsafe(12)
    salt = secrets.token_hex(16)
    cfg = {
        "bot_key": secrets.token_urlsafe(24),
        "password_salt": salt,
        "password_hash": hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 200_000).hex(),
        "telegram_token": "",
        "telegram_chat_id": "",
        "secure_cookie": False,
    }
    CONFIG_PATH.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    print("=" * 70, flush=True)
    print("First start. A config file was created: server/config.json", flush=True)
    print(f"  Dashboard password (shown once, write it down): {password}", flush=True)
    print("  The bot key in that file goes into the EA input 'BotKey'.", flush=True)
    print("  Telegram: put telegram_token in that file, then run  python server/telegram_setup.py", flush=True)
    print("=" * 70, flush=True)
    return cfg


CFG = load_config()

# ------------------------------------------------------------------ strategy library (from docs/sma-cross-spec.md)
SETTINGS = (  # key, label, default, unit, min, max, step, editable
    ("fast_period", "Fast average", 100, "1-min bars", None, None, None, False),
    ("slow_period", "Slow average", 5000, "1-min bars", None, None, None, False),
    ("take_profit_pips", "Take profit", 300, "pips", 20, 1000, 10, True),
    ("stop_loss_pips", "Stop loss", 100, "pips", 20, 500, 10, True),
    ("next_lot", "Next trade lot", 0.01, "lots", 0.01, 0.10, 0.01, True),
    ("max_lot", "Largest lot allowed", 0.10, "lots", 0.01, 1.00, 0.01, True),
    ("use_trading_hours", "Trade only in set hours", True, None, None, None, None, True),
    ("hours_start_ist", "Hours start (IST)", 210, "min", 0, 1439, 1, True),
    ("hours_end_ist", "Hours end (IST)", 660, "min", 0, 1439, 1, True),
    ("near_lines_pips", "Heads-up when lines are this close", 0, "pips", 0, 200, 5, True),
)
SPEC = {k: dict(label=l, default=d, unit=u, min=lo, max=hi, step=st, editable=ed) for k, l, d, u, lo, hi, st, ed in SETTINGS}
STRATEGY = {"id": "sma_cross", "name": "SMA 100/5000 cross (gold)", "version": "0.1.0", "magic": MAGIC}

# ------------------------------------------------------------------ storage
_db = sqlite3.connect(DATA / "console.db", check_same_thread=False)
_db.row_factory = sqlite3.Row
for stmt in (
    "CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT)",
    "CREATE TABLE IF NOT EXISTS deals(deal_id INTEGER PRIMARY KEY, close_time TEXT, body TEXT)",
    "CREATE TABLE IF NOT EXISTS signals(signal_id TEXT PRIMARY KEY, time TEXT, body TEXT)",
    "CREATE TABLE IF NOT EXISTS commands(command_id TEXT PRIMARY KEY, issued_at TEXT, body TEXT)",
    "CREATE TABLE IF NOT EXISTS bars(t TEXT PRIMARY KEY, o REAL, h REAL, l REAL, c REAL, v INTEGER)",
    "CREATE TABLE IF NOT EXISTS equity(t TEXT PRIMARY KEY, balance REAL, equity REAL)",
    "CREATE TABLE IF NOT EXISTS alerts(id INTEGER PRIMARY KEY AUTOINCREMENT, key TEXT UNIQUE, time TEXT, body TEXT)",
    "CREATE TABLE IF NOT EXISTS sessions(token TEXT PRIMARY KEY, expires REAL)",
    "CREATE TABLE IF NOT EXISTS requests(client_request_id TEXT PRIMARY KEY, command_id TEXT)",
):
    _db.execute(stmt)
_db.commit()


def q(sql: str, args=()):
    with lock:
        return _db.execute(sql, args).fetchall()


def x(sql: str, args=()):
    with lock:
        cur = _db.execute(sql, args)
        _db.commit()
        return cur


def meta_get(key, default=None):
    r = q("SELECT value FROM meta WHERE key=?", (key,))
    return json.loads(r[0]["value"]) if r else default


def meta_set(key, value):
    x("INSERT INTO meta(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, json.dumps(value)))


def current_settings() -> dict:
    s = {k: v["default"] for k, v in SPEC.items()}
    s.update(meta_get("settings", {}))
    return s


# ------------------------------------------------------------------ contract validation
REGISTRY, SCHEMAS = vc.build_registry()


def check_shape(schema_name: str, doc) -> list[str]:
    v = Draft202012Validator(SCHEMAS[schema_name], registry=REGISTRY)
    return [f"{'/'.join(map(str, e.absolute_path)) or '(root)'}: {e.message[:140]}" for e in sorted(v.iter_errors(doc), key=lambda e: list(e.absolute_path))[:6]]


# ------------------------------------------------------------------ Telegram + alerts
tg_queue: "queue.Queue[str]" = queue.Queue()
EVENT_LABEL = {"buy_signal": "Buy signal", "sell_signal": "Sell signal", "trade_closed": "Trade closed", "heads_up": "Lines getting close",
               "order_failed": "Broker refused an order", "bot_offline": "Bot stopped reporting"}


def telegram_ready() -> bool:
    return bool(CFG.get("telegram_token") and CFG.get("telegram_chat_id"))


def _tg_worker():
    while True:
        text = tg_queue.get()
        try:
            httpx.post(f"https://api.telegram.org/bot{CFG['telegram_token']}/sendMessage",
                       json={"chat_id": CFG["telegram_chat_id"], "text": text}, timeout=10)
        except Exception as e:  # noqa: BLE001  (never let a notification failure touch trading)
            print("telegram send failed:", type(e).__name__)


threading.Thread(target=_tg_worker, daemon=True).start()


def alert(key: str, event: str, text: str, when: datetime | None = None) -> None:
    """Store an alert once (key makes it idempotent) and send it to Telegram and the dashboard."""
    when = when or now()
    try:
        x("INSERT INTO alerts(key,time,body) VALUES(?,?,?)", (key, iso(when), json.dumps({"event": event, "text": text})))
    except sqlite3.IntegrityError:
        return
    if telegram_ready():
        tg_queue.put(f"{EVENT_LABEL[event]}: {text}")


# ------------------------------------------------------------------ report intake
def money_fmt(v: float) -> str:
    return f"{'+' if v >= 0 else '-'}${abs(v):,.2f}"


def ingest(report: dict) -> None:
    t = now()
    prev = meta_get("report")
    meta_set("report", report)
    meta_set("last_arrival", t.timestamp())
    arrivals = (meta_get("arrivals", []) + [t.timestamp()])[-120:]
    meta_set("arrivals", arrivals)
    if meta_get("silent_alerted"):
        meta_set("silent_alerted", False)
        alert(f"online-{int(t.timestamp())}", "bot_offline", "The bot is reporting again.")
    snap = report["snapshot"]
    slot = parse(report["sent_at"]).replace(second=0, microsecond=0)
    slot = slot - timedelta(minutes=slot.minute % 5)
    x("INSERT OR REPLACE INTO equity(t,balance,equity) VALUES(?,?,?)", (iso(slot), snap["balance"], snap["equity"]))

    for d in report["closed_deals"]:
        try:
            x("INSERT INTO deals(deal_id,close_time,body) VALUES(?,?,?)", (d["deal_id"], d["close_time"], json.dumps(d)))
        except sqlite3.IntegrityError:
            continue
        if d["strategy_id"] == "sma_cross":
            net = d["profit"] + d["commission"] + d["swap"]
            how = {"take_profit": "take profit", "stop_loss": "stop loss", "bot": "the opposite cross", "manual": "a manual close"}.get(d["close_reason"], d["close_reason"])
            alert(f"deal-{d['deal_id']}", "trade_closed",
                  f"{d['side'].capitalize()} {d['volume']:.2f} lot closed at {how}: {money_fmt(net)}. Balance {snap['balance']:,.2f}.", parse(d["close_time"]))
    for s in report["signals"]:
        try:
            x("INSERT INTO signals(signal_id,time,body) VALUES(?,?,?)", (s["signal_id"], s["time"], json.dumps(s)))
        except sqlite3.IntegrityError:
            continue
        if s["kind"] in ("entry", "skipped") and s["side"]:
            ev = "buy_signal" if s["side"] == "buy" else "sell_signal"
            extra = f" Opened {s['lot']:.2f} lot." if s["acted"] else " Not traded."
            alert(f"sig-{s['signal_id']}", ev, s["reason"] + extra, parse(s["time"]))
        elif s["kind"] == "skipped" and "refused" in s["reason"].lower():
            alert(f"fail-{s['signal_id']}", "order_failed", s["reason"], parse(s["time"]))
        if s["kind"] == "heads_up":
            alert(f"sig-{s['signal_id']}", "heads_up", s["reason"], parse(s["time"]))
    for b in report["bars"]:
        x("INSERT OR IGNORE INTO bars(t,o,h,l,c,v) VALUES(?,?,?,?,?,?)", (b["t"], b["o"], b["h"], b["l"], b["c"], b["v"]))

    settings = current_settings()
    for r in report["command_results"]:
        row = q("SELECT body FROM commands WHERE command_id=?", (r["command_id"],))
        if not row:
            continue
        c = json.loads(row[0]["body"])
        if c["status"] in ("applied", "rejected", "failed", "expired"):
            continue
        c["status"], c["reason"] = r["status"], r["reason"]
        x("UPDATE commands SET body=? WHERE command_id=?", (json.dumps(c), r["command_id"]))
        if r["status"] == "applied" and c["type"] == "strategy.update_settings":
            settings.update(c["payload"]["settings"])
            meta_set("settings", {k: v for k, v in settings.items() if SPEC[k]["editable"]})
            meta_set("settings_rev", max(meta_get("settings_rev", 0), c["payload"]["settings_rev"]))
        if r["status"] == "failed":
            alert(f"cmdfail-{r['command_id']}", "order_failed", f"{c['summary']} did not happen: {r['reason']}")


def bot_status(t: datetime) -> str:
    last = meta_get("last_arrival")
    if last is None:
        return "offline"
    age = t.timestamp() - last
    return "online" if age <= 3 * REPORT_INTERVAL_S else "stale" if age <= 60 else "offline"


def _watchdog():
    while True:
        time.sleep(15)
        last = meta_get("last_arrival")
        if last and time.time() - last > 180 and not meta_get("silent_alerted"):
            meta_set("silent_alerted", True)
            alert(f"silent-{int(last)}", "bot_offline", "No report from the bot for 3 minutes. Check the PC and MT5.")


threading.Thread(target=_watchdog, daemon=True).start()


# ------------------------------------------------------------------ commands
def new_command(ctype: str, payload: dict, summary: str, by: str = "dashboard") -> dict:
    t = now()
    c = {"command_id": "cmd-" + secrets.token_hex(6), "type": ctype, "payload": payload, "summary": summary, "issued_at": iso(t),
         "expires_at": iso(t + timedelta(seconds=COMMAND_LIFE_S)), "issued_by": by, "status": "queued", "reason": None}
    x("INSERT INTO commands(command_id,issued_at,body) VALUES(?,?,?)", (c["command_id"], c["issued_at"], json.dumps(c)))
    return c


def expire_commands() -> None:
    t = iso(now())
    for r in q("SELECT command_id, body FROM commands ORDER BY issued_at DESC LIMIT 60"):
        c = json.loads(r["body"])
        if c["status"] in ("queued", "sent") and c["expires_at"] <= t:
            c["status"], c["reason"] = "expired", "The bot did not collect it within 2 minutes, so nothing happened."
            x("UPDATE commands SET body=? WHERE command_id=?", (json.dumps(c), r["command_id"]))


def pending_for_bot() -> list[dict]:
    expire_commands()
    out = []
    for r in q("SELECT command_id, body FROM commands ORDER BY issued_at"):
        c = json.loads(r["body"])
        if c["status"] in ("queued", "sent"):
            if c["status"] == "queued":
                c["status"] = "sent"
                x("UPDATE commands SET body=? WHERE command_id=?", (json.dumps(c), r["command_id"]))
            out.append({k: c[k] for k in ("command_id", "type", "issued_at", "expires_at", "issued_by", "payload")})
    return out


def check_lot(v, mx) -> str | None:
    sp = SPEC["next_lot"]
    if not isinstance(v, (int, float)):
        return "Enter a lot size, for example 0.01."
    if v < sp["min"] - 1e-9:
        return f"Lot {v:g} is below the smallest allowed ({sp['min']:.2f})."
    if v > mx + 1e-9:
        return f"Lot {v:g} is above the largest lot allowed ({mx:.2f})."
    n = (v - sp["min"]) / sp["step"]
    return None if abs(n - round(n)) < 1e-6 else f"Lots move in steps of {sp['step']:.2f}."


def validate_command(body: dict) -> tuple[str | None, str]:
    """Same range checks the bot applies, so a bad value is rejected at once. Returns (reason, summary)."""
    t, p = body["type"], body["payload"]
    settings = current_settings()
    report = meta_get("report") or {}
    if t == "strategy.set_enabled":
        if p["strategy_id"] != "sma_cross":
            return "Unknown strategy.", ""
        return None, f"Switch {'on' if p['enabled'] else 'off'} Auto for {STRATEGY['name']}"
    if t == "bot.set_trading_paused":
        return None, "Pause all new trades" if p["paused"] else "Resume new trades"
    if t == "strategy.update_settings":
        s = p["settings"]
        bits = []
        for k, v in s.items():
            if k not in SPEC or not SPEC[k]["editable"]:
                return f"'{k}' cannot be changed from the dashboard.", ""
            sp = SPEC[k]
            if isinstance(sp["default"], bool):
                if not isinstance(v, bool):
                    return f"'{k}' must be on or off.", ""
                continue
            if not isinstance(v, (int, float)) or isinstance(v, bool):
                return f"'{k}' must be a number.", ""
            if k == "next_lot":
                msg = check_lot(v, settings["max_lot"] if "max_lot" not in s else s["max_lot"])
                if msg:
                    return msg, ""
                bits.append(f"next trade lot {v:.2f}")
                continue
            hi = sp["max"]
            if k == "max_lot" and v < settings["next_lot"] - 1e-9 and "next_lot" not in s:
                return f"The largest lot cannot be below the next trade lot ({settings['next_lot']:.2f}).", ""
            if v < sp["min"] - 1e-9 or v > hi + 1e-9:
                return f"{sp['label']} must be between {sp['min']:g} and {hi:g}.", ""
            n = (v - sp["min"]) / sp["step"]
            if abs(n - round(n)) > 1e-6:
                return f"{sp['label']} moves in steps of {sp['step']:g}.", ""
            bits.append(f"{sp['label'].lower()} {v:g}" + (f" {sp['unit']}" if sp["unit"] else ""))
        return None, "Set " + ", ".join(bits or ["settings"])
    pos = {x_["position_id"]: x_ for x_ in report.get("open_positions", [])}
    pp = pos.get(p.get("position_id"))
    if pp is None or pp["strategy_id"] is None:
        return "That is not an open trade the bot owns.", ""
    if t == "position.close":
        return None, f"Close {pp['side']} {pp['volume']:.2f} lot"
    if t == "position.set_levels":
        buy = pp["side"] == "buy"
        cur = pp["current_price"]
        if "sl" in p:
            if pp["sl"] is not None and ((p["sl"] < pp["sl"]) if buy else (p["sl"] > pp["sl"])):
                return f"A stop can only move toward the price. It is {pp['sl']:.2f}.", ""
            if (cur - p["sl"] if buy else p["sl"] - cur) <= 0.5:
                return f"The stop must stay {'below' if buy else 'above'} the current price ({cur:.2f}) by at least 0.50.", ""
        if "tp" in p and (p["tp"] - cur if buy else cur - p["tp"]) <= 0.5:
            return f"The target must be {'above' if buy else 'below'} the current price ({cur:.2f}) by at least 0.50.", ""
        return None, f"Move {' and '.join(k for k in ('target', 'stop') if (k == 'target' and 'tp' in p) or (k == 'stop' and 'sl' in p))} ({pp['side']} {pp['volume']:.2f} lot)"
    return "Unknown command.", ""


# ------------------------------------------------------------------ overview
def chart_block(sample: dict) -> tuple[dict, bool]:
    rows = q("SELECT t,o,h,l,c,v FROM bars ORDER BY t")
    if len(rows) < ref.SLOW + 50:
        return sample["chart"], True
    df = pd.DataFrame([dict(r) for r in rows])
    df["time"] = pd.to_datetime(df["t"], format="%Y-%m-%dT%H:%M:%SZ")
    df = df.set_index("time").rename(columns={"o": "open", "h": "high", "l": "low", "c": "close"})
    fast, slow = ref.averages(df["close"])
    state = pd.DataFrame({"f": fast, "s": slow})
    nn = lambda v: None if pd.isna(v) else round(float(v), 3)  # noqa: E731
    sets = {}
    for key, rule, n in (("1m", "1min", 240), ("5m", "5min", 240), ("30m", "30min", 240), ("1h", "1h", 240), ("4h", "4h", 240), ("1d", "1D", 240), ("1mo", "MS", None)):
        cb = ref.coarse(df, rule)
        st = state.resample(rule, closed="left", label="left").last().reindex(cb.index)
        if n:
            cb, st = cb.tail(n), st.tail(n)
        sets[key] = {"t": [iso(t) for t in cb.index], "o": [round(float(v), 2) for v in cb["open"]], "h": [round(float(v), 2) for v in cb["high"]],
                     "l": [round(float(v), 2) for v in cb["low"]], "c": [round(float(v), 2) for v in cb["close"]],
                     "fast": [nn(v) for v in st["f"]], "slow": [nn(v) for v in st["s"]]}
    crosses = ref.find_signals(df)
    markers = [{"t": iso(c.act_at), "side": c.side, "traded": bool(ref.in_session(c.act_at)),
                "note": None if ref.in_session(c.act_at) else "Outside trading hours"} for c in crosses.itertuples(index=False)]
    f_now, s_now = float(fast.iloc[-1]), float(slow.iloc[-1])
    last = markers[-1] if markers else None
    if not markers:
        return sample["chart"], True
    return {"symbol": (meta_get("report") or {}).get("open_positions", [{}])[0].get("symbol", SYMBOL_FALLBACK), "anchor": "1m",
            "fast_period": ref.FAST, "slow_period": ref.SLOW, "as_of": iso(df.index[-1] + pd.Timedelta(minutes=1)),
            "latest": {"fast": round(f_now, 3), "slow": round(s_now, 3), "gap": round(f_now - s_now, 3), "last_cross": {"time": last["t"], "side": last["side"]}},
            "timeframes": sets, "markers": markers}, False


SAMPLE_PATH = DASH / "data" / "sample-overview.json"


def build_overview() -> dict:
    report = meta_get("report")
    if not report:
        raise HTTPException(503, "Waiting for the first report from the bot.")
    sample = json.loads(SAMPLE_PATH.read_text(encoding="utf-8"))
    t = now()
    settings = current_settings()
    rev = meta_get("settings_rev", 0)
    rep_s = next((s for s in report["strategies"] if s["id"] == "sma_cross"), None)
    day0 = t.replace(hour=0, minute=0, second=0, microsecond=0)
    deals = [json.loads(r["body"]) for r in q("SELECT body FROM deals ORDER BY close_time DESC LIMIT 400")]
    net = lambda d: d["profit"] + d["commission"] + d["swap"]  # noqa: E731
    today = [d for d in deals if parse(d["close_time"]) >= day0]
    my_pos = [p for p in report["open_positions"] if p["strategy_id"] == "sma_cross"]
    all_total = q("SELECT body FROM deals")
    tot_deals = [json.loads(r["body"]) for r in all_total]
    tally = lambda ds: {"net_profit": round(sum(net(d) for d in ds), 2), "trades": len(ds), "wins": sum(1 for d in ds if net(d) > 0)}  # noqa: E731

    lots_max = settings["max_lot"]
    srows = []
    for k, label, _d, unit, lo, hi, st, ed in SETTINGS:
        mx = lots_max if k == "next_lot" else hi
        srows.append({"key": k, "label": label, "value": settings[k], "unit": unit, "min": lo, "max": mx, "step": st, "editable": ed})
    state = "paused" if not (rep_s and rep_s["enabled"]) else ("in_position" if my_pos else "idle")
    if my_pos:
        state = "in_position"
    strategies = [{"id": "sma_cross", "name": STRATEGY["name"], "version": STRATEGY["version"], "magic": MAGIC, "enabled": bool(rep_s and rep_s["enabled"]),
                   "state": state, "symbols": rep_s["symbols"] if rep_s else [SYMBOL_FALLBACK], "settings_rev": rev, "settings": srows,
                   "today": tally([d for d in today if d["strategy_id"] == "sma_cross"]), "total": tally([d for d in tot_deals if d["strategy_id"] == "sma_cross"]),
                   "open_count": len(my_pos), "floating_pl": round(sum(p["profit"] + p["swap"] + p["commission"] for p in my_pos), 2)}]

    eq = [{"t": r["t"], "balance": r["balance"], "equity": r["equity"]} for r in q("SELECT * FROM equity WHERE t >= ? ORDER BY t", (iso(t - timedelta(hours=24)),))]
    snap = report["snapshot"]
    eq.append({"t": report["sent_at"], "balance": snap["balance"], "equity": snap["equity"]})
    if len(eq) < 2:
        eq.insert(0, dict(eq[0], t=iso(t - timedelta(minutes=5))))
    first_today = next((r for r in q("SELECT * FROM equity WHERE t >= ? ORDER BY t LIMIT 1", (iso(day0),))), None)
    day_start = {"time": iso(day0), "balance": first_today["balance"] if first_today else snap["balance"], "equity": first_today["equity"] if first_today else snap["equity"]}

    expire_commands()
    cmds = []
    for r in q("SELECT body FROM commands ORDER BY issued_at DESC LIMIT 8"):
        c = json.loads(r["body"])
        cmds.append({k: c[k] for k in ("command_id", "type", "summary", "issued_at", "expires_at", "status", "reason")})
    signals = [json.loads(r["body"]) for r in q("SELECT body FROM signals ORDER BY time DESC LIMIT 10")]

    ch, ch_sample = chart_block(sample)
    sample_blocks = ["volatility"] + (["chart"] if ch_sample else [])
    ev_enabled = {e["id"]: e["enabled"] for e in sample["alerts"]["events"]}
    alerts_recent = []
    for r in q("SELECT time, body FROM alerts ORDER BY id DESC LIMIT 8"):
        b = json.loads(r["body"])
        alerts_recent.append({"time": r["time"], "event": b["event"], "channel": "telegram" if telegram_ready() else "dashboard", "delivered": True, "text": b["text"]})
    channels = []
    for c in sample["alerts"]["channels"]:
        c = dict(c)
        if c["id"] == "telegram":
            c.update(status="ready" if telegram_ready() else "needs_setup", enabled=telegram_ready(),
                     note=None if telegram_ready() else "Put the bot token and chat id in server/config.json, then run server/telegram_setup.py.")
        elif c["id"] == "mt5_push":
            c.update(status="needs_setup", enabled=False, note="Not used by this version; Telegram carries the alerts.")
        channels.append(c)
    arrivals = meta_get("arrivals", [])
    last_arr = arrivals[-1] if arrivals else t.timestamp()
    hb = [{"t": iso(datetime.fromtimestamp(last_arr - REPORT_INTERVAL_S * (59 - i), UTC)),
           "ok": any(abs(a - (last_arr - REPORT_INTERVAL_S * (59 - i))) <= REPORT_INTERVAL_S / 2 + 0.5 for a in arrivals[-70:])} for i in range(60)]

    ov = {"schema_version": "0.2", "server_time": iso(t), "account": report["account"], "sample_blocks": sample_blocks,
          "bot": {"status": bot_status(t), "version": report["bot"]["version"], "latest_version": BOT_LATEST, "last_report_at": iso(datetime.fromtimestamp(last_arr, UTC)),
                  "report_interval_s": REPORT_INTERVAL_S, "trading_paused": report["trading_paused"], "heartbeat": hb},
          "snapshot": snap, "day_start": day_start, "equity_series": eq, "open_positions": report["open_positions"], "strategies": strategies,
          "recent_deals": deals[:40], "recent_signals": signals, "recent_commands": cmds, "chart": ch, "volatility": sample["volatility"],
          "alerts": {"events": [{"id": i, "label": EVENT_LABEL[i], "enabled": ev_enabled.get(i, True)} for i in EVENT_LABEL], "channels": channels, "recent": alerts_recent}}
    return ov


# ------------------------------------------------------------------ app + auth
app = FastAPI(title="Bot Console", docs_url=None, redoc_url=None)
login_fail: dict[str, list[float]] = {}


def hash_pw(pw: str) -> str:
    return hashlib.pbkdf2_hmac("sha256", pw.encode(), CFG["password_salt"].encode(), 200_000).hex()


def session_ok(request: Request) -> bool:
    tok = request.cookies.get("bc_session")
    if not tok:
        return False
    r = q("SELECT expires FROM sessions WHERE token=?", (tok,))
    return bool(r) and r[0]["expires"] > time.time()


OPEN_PATHS = ("/login", "/login.html", "/v1/report", "/styles.css", "/dom.js")


@app.middleware("http")
async def guard(request: Request, call_next):
    p = request.url.path
    if p in OPEN_PATHS or session_ok(request):
        return await call_next(request)
    if p.startswith("/v1/"):
        return JSONResponse({"detail": "Sign in first."}, status_code=401)
    return RedirectResponse("/login.html")


@app.post("/login")
def login(request: Request, response: Response, body: dict = Body(...)):
    ip = request.client.host if request.client else "?"
    fails = [t for t in login_fail.get(ip, []) if time.time() - t < 900]
    if len(fails) >= 5:
        raise HTTPException(429, "Too many tries. Wait 15 minutes.")
    if not hmac.compare_digest(hash_pw(str(body.get("password", ""))), CFG["password_hash"]):
        login_fail[ip] = fails + [time.time()]
        raise HTTPException(401, "That password is not right.")
    tok = secrets.token_urlsafe(32)
    x("INSERT INTO sessions(token,expires) VALUES(?,?)", (tok, time.time() + 14 * 86400))
    response.set_cookie("bc_session", tok, httponly=True, samesite="strict", secure=bool(CFG.get("secure_cookie")), max_age=14 * 86400)
    return {"ok": True}


@app.post("/logout")
def logout(request: Request, response: Response):
    tok = request.cookies.get("bc_session")
    if tok:
        x("DELETE FROM sessions WHERE token=?", (tok,))
    response.delete_cookie("bc_session")
    return {"ok": True}


@app.post("/v1/report")
def report_in(body: dict = Body(...), x_bot_key: str = Header(None)):
    if not x_bot_key or not hmac.compare_digest(x_bot_key, CFG["bot_key"]):
        raise HTTPException(401, "Bad bot key.")
    errs = check_shape("bot-report.schema.json", body)
    if errs:
        print("REPORT REJECTED:", errs)
        raise HTTPException(422, {"errors": errs})
    ingest(body)
    closed = q("SELECT MAX(close_time) m FROM deals")[0]["m"]
    bars = q("SELECT MAX(t) m FROM bars")[0]["m"]
    results = [r["command_id"] for r in body["command_results"]]
    resp = {"schema_version": "0.2", "server_time": iso(now()),
            "ack": {"seq": body["seq"], "closed_through": closed, "bars_through": bars, "command_results": results},
            "license": {"status": "active", "valid_until": iso(now() + timedelta(days=30)), "token": None},
            "update": {"latest_version": BOT_LATEST, "min_supported_version": "0.6.0"}, "poll_interval_s": REPORT_INTERVAL_S,
            "commands": pending_for_bot()}
    errs = check_shape("server-response.schema.json", resp)
    if errs:
        raise HTTPException(500, {"errors": errs})
    return resp


@app.get("/v1/overview")
def overview():
    ov = build_overview()
    errs = check_shape("dashboard-overview.schema.json", ov)
    if errs:
        print("OVERVIEW INVALID:", errs)
        raise HTTPException(500, {"errors": errs})
    return ov


@app.post("/v1/accounts/1/commands")
def command_in(body: dict = Body(...)):
    def reply(status, cid=None, exp=None, reason=None):
        return {"schema_version": "0.2", "status": status, "command_id": cid, "expires_at": exp, "reason": reason}
    errs = check_shape("dashboard-command.schema.json", body)
    if errs:
        return reply("rejected", reason="That request was not understood: " + errs[0])
    done = q("SELECT command_id FROM requests WHERE client_request_id=?", (body["client_request_id"],))
    if done:
        c = json.loads(q("SELECT body FROM commands WHERE command_id=?", (done[0]["command_id"],))[0]["body"])
        return reply("duplicate", c["command_id"], c["expires_at"])
    bot = bot_status(now())
    if bot == "offline" and not meta_get("report"):
        return reply("rejected", reason="The bot has not connected yet.")
    reason, summary = validate_command(body)
    if reason:
        return reply("rejected", reason=reason)
    payload = dict(body["payload"])
    if body["type"] == "strategy.update_settings":
        rev = meta_get("settings_rev", 0) + 1 + sum(1 for r in q("SELECT body FROM commands") if json.loads(r["body"])["status"] in ("queued", "sent") and json.loads(r["body"])["type"] == "strategy.update_settings")
        payload["settings_rev"] = rev
    c = new_command(body["type"], payload, summary)
    x("INSERT INTO requests(client_request_id,command_id) VALUES(?,?)", (body["client_request_id"], c["command_id"]))
    return reply("queued", c["command_id"], c["expires_at"])


@app.post("/v1/telegram/test")
def telegram_test():
    if not telegram_ready():
        raise HTTPException(400, "Telegram is not set up yet (server/config.json).")
    tg_queue.put("Bot Console: Telegram is connected. You will get signals, closed trades and warnings here.")
    return {"ok": True}


@app.get("/")
def home():
    return FileResponse(DASH / "index.html")


app.mount("/", StaticFiles(directory=DASH), name="dashboard")
