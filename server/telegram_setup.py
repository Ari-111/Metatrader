"""Find your Telegram chat id and save it.

1. In server/config.json put the token from @BotFather in "telegram_token".
2. In Telegram, open your new bot and send it any message (for example "hi").
3. Run:  python server/telegram_setup.py
It reads the chat id from the bot's recent messages, saves it, and sends a test message.
The token is only ever read from the config file; it is never printed.
"""
import json
from pathlib import Path

import httpx

path = Path(__file__).resolve().parent / "config.json"
cfg = json.loads(path.read_text(encoding="utf-8"))
tok = cfg.get("telegram_token", "")
if not tok:
    raise SystemExit("telegram_token is empty in server/config.json")
r = httpx.get(f"https://api.telegram.org/bot{tok}/getUpdates", timeout=15).json()
if not r.get("ok"):
    raise SystemExit("Telegram refused the token. Check it with @BotFather.")
chats = {u["message"]["chat"]["id"]: u["message"]["chat"].get("first_name", "") for u in r["result"] if "message" in u}
if not chats:
    raise SystemExit("No messages found. Send your bot a message in Telegram first, then run this again.")
chat_id, name = list(chats.items())[-1]
cfg["telegram_chat_id"] = str(chat_id)
path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
httpx.post(f"https://api.telegram.org/bot{tok}/sendMessage", json={"chat_id": chat_id, "text": "Bot Console is connected."}, timeout=15)
print(f"Saved chat id for '{name}'. A test message was sent. Restart the server.")
