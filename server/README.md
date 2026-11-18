# Bot Console server

One small Python server: it receives the MT5 bot's reports, holds the dashboard's commands for the bot, shows the live dashboard, and sends Telegram messages.

## Run it

```
cd D:\Zerodha
python -m uvicorn server.app:app --host 127.0.0.1 --port 8000
```

Or double-click `server/start.ps1`. Then open http://127.0.0.1:8000 and sign in.

First start creates `server/config.json` and prints the dashboard password **once** (in the window, or in the log file if you ran it hidden). If you lose it, delete `config.json` and the server makes a new one (the bot key changes too).

## Connect the bot (EA v2)

1. MT5: Tools > Options > Expert Advisors > tick **Allow WebRequest** and add `http://127.0.0.1:8000`.
2. Copy `bot/XAUUSD_SMA_Cross_EA_v2.mq5` into MT5's `MQL5/Experts` folder, compile it in MetaEditor (F7), and drag it onto an **XAUUSD M1** chart.
3. In the EA's inputs set **BotKey** to the `bot_key` value in `server/config.json`. Leave ServerUrl as it is for a local test.
4. Switch **Algo Trading** on (the button on the toolbar). The dashboard's top bar should say "Bot is reporting" within a few seconds.

## Telegram

1. In Telegram message `@BotFather`, send `/newbot`, and copy the token.
2. Paste it into `server/config.json` as `telegram_token` (never into chat or code).
3. Send your new bot any message, then run `python server/telegram_setup.py` and restart the server.

You get: every buy/sell signal (and whether it was traded), every closed trade with its profit, refused orders, and a warning if the bot goes silent for 3 minutes.

## What is live and what is not yet

Live: account, balance and equity, open trade, closed trades, signals, controls (Auto, next lot, Close now, move TP/stop), Telegram, the chart once the bot has sent 5,000+ one-minute candles.
Still sample data (the dashboard says so at the top): the volatility screen (it needs months of history), and the chart until the history has arrived.

## Safety notes

- The dashboard needs the password; the bot needs the bot key. Neither is stored in the code.
- Listening on 127.0.0.1 means only this PC can reach it. To put it online, run it behind HTTPS (a reverse proxy such as Caddy or nginx), set `"secure_cookie": true`, and keep the firewall closed except for 443. Do not expose port 8000 directly.
- Every report is checked against `contract/bot-report.schema.json`, and every control against the same range checks the bot applies.
- `python -P tools/server_selftest.py http://127.0.0.1:8000 <password>` runs 25 checks with a fake bot (it uses the real database, so run it on a throwaway copy).
