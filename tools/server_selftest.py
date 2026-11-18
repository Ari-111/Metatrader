"""Self-test for server/app.py using a fake bot. Run with the server already started:

    python -P tools/server_selftest.py http://127.0.0.1:8000 <dashboard-password>

It uses the bot key from server/config.json. It places no trades; it only talks to the server.
"""
import copy
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
base, password = sys.argv[1], sys.argv[2]
cfg = json.loads((ROOT / "server" / "config.json").read_text(encoding="utf-8"))
example = json.loads((ROOT / "contract" / "examples" / "bot-report.example.json").read_text(encoding="utf-8"))
ok = fail = 0


def check(cond, label, detail=""):
    global ok, fail
    if cond:
        ok += 1
    else:
        fail += 1
        print("  FAIL", label, detail)


def iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


bot = httpx.Client(base_url=base, headers={"X-Bot-Key": cfg["bot_key"]})
web = httpx.Client(base_url=base, follow_redirects=False)
seq = 1


def send_report(results=None, bars=None):
    global seq
    r = copy.deepcopy(example)
    r["sent_at"], r["seq"], r["boot_id"] = iso(), seq, "selftest0001"
    r["command_results"] = results or []
    r["closed_deals"], r["signals"] = [], []
    if bars is not None:
        r["bars"] = bars
    seq += 1
    return bot.post("/v1/report", json=r)


# --- access control
check(web.get("/v1/overview").status_code == 401, "overview needs a sign-in")
check(web.get("/").status_code in (302, 307), "dashboard page redirects to the login page when signed out")
check(httpx.post(base + "/v1/report", json=example, headers={"X-Bot-Key": "wrong"}).status_code == 401, "wrong bot key is refused")
check(web.post("/login", json={"password": "nope"}).status_code == 401, "wrong password is refused")
check(web.post("/login", json={"password": password}).status_code == 200, "right password signs in")

# --- report intake
bad = copy.deepcopy(example)
bad["snapshot"]["balance"] = "lots"
check(bot.post("/v1/report", json=bad).status_code == 422, "a report that breaks the contract is refused")
r = send_report()
check(r.status_code == 200, "a valid report is accepted", r.text[:200])
check(r.json()["ack"]["seq"] == 1 and r.json()["commands"] == [], "ack echoes seq; no commands waiting")
ov = web.get("/v1/overview")
check(ov.status_code == 200, "overview is served", ov.text[:300])
o = ov.json()
check(o["bot"]["status"] == "online" and o["snapshot"]["balance"] == example["snapshot"]["balance"], "overview reflects the report")
check("volatility" in o["sample_blocks"], "volatility is labelled as sample data")

# the overview must also pass every consistency check used on the sample
sys.path.insert(0, str(ROOT / "tools"))
import validate_contract as vc  # noqa: E402

rep = vc.check_documents({"overview": o})
real = [f for f in rep.failures if "covers about 24 hours" not in f]  # a brand-new server has no 24 h of history yet
check(not real, "live overview passes the contract checks", "; ".join(real[:3]))

# --- commands
pos_id = example["open_positions"][0]["position_id"]
sid = 0


def cmd(body):
    global sid
    sid += 1
    return web.post("/v1/accounts/1/commands", json={"schema_version": "0.2", "client_request_id": f"selftest-req-{sid:04d}-{datetime.now().timestamp()}", **body}).json()


bad_lot = cmd({"type": "strategy.update_settings", "payload": {"strategy_id": "sma_cross", "settings_rev": 1, "settings": {"next_lot": 0.5}}})
check(bad_lot["status"] == "rejected" and "above the largest lot" in bad_lot["reason"], "a lot above the cap is rejected at once", str(bad_lot))
bad_step = cmd({"type": "strategy.update_settings", "payload": {"strategy_id": "sma_cross", "settings_rev": 1, "settings": {"next_lot": 0.015}}})
check(bad_step["status"] == "rejected", "an off-step lot is rejected")
fixed = cmd({"type": "strategy.update_settings", "payload": {"strategy_id": "sma_cross", "settings_rev": 1, "settings": {"fast_period": 50}}})
check(fixed["status"] == "rejected", "a fixed setting cannot be changed")
pos = example["open_positions"][0]
widen = cmd({"type": "position.set_levels", "payload": {"position_id": pos_id, "sl": round(pos["sl"] - 3, 2)}})
check(widen["status"] == "rejected" and "toward the price" in widen["reason"], "widening a stop is rejected", str(widen))
ghost = cmd({"type": "position.close", "payload": {"position_id": 1}})
check(ghost["status"] == "rejected", "closing a trade that is not open is rejected")

good = cmd({"type": "strategy.update_settings", "payload": {"strategy_id": "sma_cross", "settings_rev": 1, "settings": {"next_lot": 0.02}}})
check(good["status"] == "queued", "a valid lot change is queued", str(good))
dup_body = {"schema_version": "0.2", "client_request_id": f"selftest-dup-{datetime.now().timestamp()}", "type": "position.close", "payload": {"position_id": pos_id}}
a = web.post("/v1/accounts/1/commands", json=dup_body).json()
b = web.post("/v1/accounts/1/commands", json=dup_body).json()
check(a["status"] == "queued" and b["status"] == "duplicate" and a["command_id"] == b["command_id"], "a double press queues one command")

r = send_report().json()
types = sorted(c["type"] for c in r["commands"])
check(types == ["position.close", "strategy.update_settings"], "the bot receives both waiting commands", str(types))
results = [{"command_id": c["command_id"], "status": "applied", "reason": None, "at": iso()} for c in r["commands"]]
r2 = send_report(results).json()
check(sorted(r2["ack"]["command_results"]) == sorted(c["command_id"] for c in r["commands"]), "results are acknowledged")
check(r2["commands"] == [], "nothing is delivered twice once applied")
o = web.get("/v1/overview").json()
lot = next(s for s in o["strategies"][0]["settings"] if s["key"] == "next_lot")["value"]
check(lot == 0.02, "an applied lot change shows in the overview", str(lot))
check(all(c["status"] == "applied" for c in o["recent_commands"][:2]), "overview shows both commands as applied")
rep = vc.check_documents({"overview": o})
real = [f for f in rep.failures if "covers about 24 hours" not in f]
check(not real, "overview still passes the contract checks after commands", "; ".join(real[:3]))

print(f"{ok} passed, {fail} failed")
sys.exit(1 if fail else 0)
