# Data contract: bot, server and dashboard

**Status: draft v0.2.** This is the agreement between the three parts of the system. The exact shapes live in `contract/*.schema.json`; this page explains what they mean and the rules around them. Working examples are in `contract/examples/` and `dashboard/data/`.

**What changed from v0.1** (for the gold SMA bot, one person, laptop and phone): the dashboard can now **close a trade, move its stop loss and take profit, change the next trade's lot, and switch Auto on and off** (v0.1 deliberately had no close or modify commands, see "Commands"); the overview carries **chart data for every timeframe, a volatility outlook, alert settings and the status of every control pressed**; the bot sends its **1-minute candles** so the server draws every chart from one source; signals say which candle produced them and which lot they used.

Anything marked **(my call)** is a design choice I made while drafting. It is not agreed yet; say so and I change it.

## The three conversations

```
 MetaTrader 5 (customer's PC)            Your server                      Browser
┌───────────────────────────┐        ┌───────────────────┐        ┌──────────────────┐
│  Bot (one Expert Advisor) │ report │                   │overview│                  │
│  strategy A, B, C ...     │───────▶│  stores reports,  │───────▶│    Dashboard     │
│                           │◀───────│  holds commands   │◀───────│                  │
└───────────────────────────┘response└───────────────────┘ command└──────────────────┘
```

| # | Message | Direction | Schema | Example |
|---|---|---|---|---|
| 1 | **Report** | bot to server, every ~5 s | `bot-report.schema.json` | `contract/examples/bot-report.example.json` |
| 2 | **Response** | server to bot, as the reply to every report | `server-response.schema.json` | `contract/examples/server-response.example.json` |
| 3 | **Overview** | server to dashboard | `dashboard-overview.schema.json` | `dashboard/data/sample-overview.json` |
| 4 | **Dashboard command** | dashboard to server, when a person presses a control | `dashboard-command.schema.json` | `contract/examples/dashboard-command.example.json` |
| 5 | **Command reply** | server to dashboard, straight away | `dashboard-command-reply.schema.json` | `contract/examples/dashboard-command-reply*.example.json` |

The bot only ever talks to the server. The dashboard only ever talks to the server. MetaTrader 5 cannot receive incoming connections, so everything the bot learns comes back inside the response to its own report.

**One round trip, not two (my call).** Your build plan has the bot report and also poll for commands. I have combined them: the response to each report carries any waiting commands. That halves the web requests the bot makes, which matters because a web request freezes the Expert Advisor until it returns.

## Rules that apply everywhere

- **Format:** JSON, UTF-8, over HTTPS only.
- **Time:** always UTC, ISO 8601, ending in `Z` (`2026-11-06T14:32:07Z`). The dashboard converts to the viewer's time zone.
- **Money:** a plain number in the account currency, signed, 2 decimals. Prices use the symbol's own precision.
- **Net result of a trade** = `profit + commission + swap`. Commission and swap are normally negative or zero.
- **Strictness:** while the contract is a draft, the schemas reject unknown fields. This catches typos early. Once the bot is in customers' hands, the server will have to tolerate fields it does not know (an older bot talking to a newer server), so this will be loosened at v1.0.

## Report (bot to server)

Sent about every 5 seconds. The server may change the pace through `poll_interval_s` in its response (allowed range 2 to 60 s).

| Field | Meaning |
|---|---|
| `seq`, `boot_id` | `seq` counts up by one per report. `boot_id` is a random value picked when the bot starts, and `seq` restarts at 1. A gap in `seq` means a report was lost; a new `boot_id` means the bot restarted. |
| `bot` | Bot version and the MetaTrader 5 build. This is how you see who is out of date. |
| `account` | Login number, server name, currency, demo or real, netting or hedging, leverage. Never a password. |
| `snapshot` | Balance, equity, margin, free margin, margin level (null when no margin is used) and floating profit. |
| `trading_paused` | The whole-bot Auto switch. True means no new entries on any strategy. |
| `strategies` | Every strategy compiled into the bot, on or off: id, version, `magic` number, `enabled`, state, and the `settings_rev` it is running. |
| `open_positions` | Every open position on the account, including ones the bot does not own (`strategy_id` is null for those, for example manual trades). Each carries `volume_locked` (true for every position the bot owns) and `sl_original` (the stop it opened with). |
| `closed_deals` | Closing deals since the last cursor the server acknowledged. Safe to resend: the server drops duplicates by `deal_id`. |
| `signals` | Signals raised since the last report, **including ones the bot skipped and why** ("Outside trading hours"). Each names the 1-minute candle that produced it (`candle_close`) and the `lot` if an order was sent. |
| `bars` | Closed 1-minute candles after the cursor `ack.bars_through`, at most 1000 per report. The server draws every chart timeframe and both averages from these. The first connection sends the history the slow average needs (5,000 candles or more) in chunks. |
| `command_results` | Outcomes of earlier commands, sent until the server confirms it stored them. Status is `applied`, `rejected`, `failed` (valid, but the broker refused it) or `expired`. |

Points that are easy to get wrong:

- **Strategy ownership** comes from the `magic` number stamped on each order. The bot reports its `magic` to strategy mapping, so the server can attribute every trade. Trades with an unknown magic number belong to nobody (`strategy_id: null`).
- **`closed_deals` has one record per closing deal.** A position closed in parts produces several records sharing one `position_id`.
- **`enabled: false` means no new entries.** Open positions of that strategy are still managed (stop loss, take profit, exit rules). Switching a strategy off never abandons a trade.
- **Positions and deals use the position's direction in `side`**, not the direction of the closing order.
- **Close reason:** `take_profit`, `stop_loss`, `bot` (the Expert Advisor closed it on an exit rule), `manual`, `stop_out`, `other`.

## Response (server to bot)

| Field | Meaning |
|---|---|
| `server_time` | The bot checks command expiry against this, never against the customer's PC clock. |
| `ack` | The `seq` received, `closed_through` (the newest close time stored, so the bot sends only later deals), `bars_through` (the newest 1-minute candle stored, so the bot sends only later ones; null asks for the full history), and the `command_results` ids stored. |
| `license` | `active`, `grace`, `expired` or `revoked`, with `valid_until`. A fresh `token` appears when the server rotates it. |
| `update` | `latest_version` and `min_supported_version`. A bot below the minimum shows a warning on the dashboard. |
| `commands` | Commands waiting for this bot (below). |

## Commands

Five types in v0.2:

| Type | Does | Payload | Dashboard control |
|---|---|---|---|
| `strategy.set_enabled` | Turns one strategy on (allows new entries) or off (no new entries) | `strategy_id`, `enabled` | Auto switch for one strategy |
| `strategy.update_settings` | Changes settings of one strategy | `strategy_id`, `settings_rev` (the new revision), `settings` (key to value) | Next trade lot, take profit, stop loss, hours, max lot |
| `bot.set_trading_paused` | Pauses or resumes new entries on every strategy at once | `paused` | Auto switch for the whole bot |
| `position.close` | Closes one open position at market | `position_id` | Close now |
| `position.set_levels` | Moves the stop loss and/or take profit of one open position | `position_id`, `sl` and/or `tp` | Move TP / tighten SL |

**This reverses a v0.1 decision.** v0.1 deliberately had no close or modify commands, because a wrong command is riskier than a wrong chart. They were added because the strategy needs a human override ("I want to stop this trade at $15, not wait for $30"). The safeguards are below. What is still **not** possible from the dashboard: opening a trade, changing an open trade's lot, closing part of a trade, closing trades the bot does not own, and anything about the account.

**What the bot must check before applying any command** (all of these, every time):

1. Not expired: `expires_at` is later than the response's `server_time`. Commands live about 2 minutes, so a stale "close" is never executed late. A late command is reported `expired` and the trade is untouched.
2. Not seen before: each `command_id` is applied at most once, even after a restart (the bot keeps the ids it has handled).
3. Known target: the `strategy_id` exists in this bot; the `position_id` is an open position **the bot owns** (known magic number). A manual trade is refused.
4. In range: every setting is inside the `min` and `max` the strategy spec defines for it. **One bad value rejects the whole command**, so settings never apply half-way. For `next_lot` the maximum is the current `max_lot`, and the value must be a whole number of the broker's lot steps.
5. Newer: `settings_rev` is higher than the one the bot already runs.
6. Applied atomically, written to disk as the new "last safe settings", and reported back in `command_results` as `applied`, `rejected` (with a reason), `failed` (the broker refused, for example market closed) or `expired`.

**Rules specific to the trade controls:**

- **Lot is fixed once a trade is open.** No command can change an open position's volume, and the bot never closes part of a position. `next_lot` is an ordinary setting that is read at the moment the next order is sent, so editing it never touches an open trade.
- **`position.set_levels` may only tighten the stop.** For a buy the new stop must be at or above the current one (and so never below `sl_original`); for a sell, at or below. A stop cannot be removed. A take profit may move either way but cannot be removed. Both must sit on the correct side of the current price and respect the broker's minimum distance.
- **`position.close` retries until it succeeds or expires.** If the broker refuses (market closed), the bot retries every 10 seconds until the command expires, then reports `failed` with the broker's reason. After a manual close the strategy stays flat until its next signal; it never re-enters by itself.
- **Auto off keeps the safety net.** `enabled: false` or `paused: true` stops new entries only. An open trade still has its stop and target at the broker and still closes on the opposite cross.

## Dashboard writes (dashboard to server)

When a person presses a control the dashboard sends `POST /v1/accounts/{id}/commands` with the command (`type` and `payload`, same shapes as above) and a `client_request_id`. The server:

1. checks the person's session (one account, one person; login details are decided in the server phase),
2. applies the same range checks the bot will (so "Lot 0.50 is above the largest lot allowed (0.10)" comes back at once, as a `rejected` reply),
3. queues a command for the bot with `expires_at` about 2 minutes ahead, and replies `queued` with its `command_id`.

The same `client_request_id` sent twice (a double tap, a retry) gives `duplicate` and the original `command_id`, so a control never fires twice. `queued` only means the server accepted it. The dashboard then follows the command in `recent_commands`: `queued`, `sent` (handed to the bot), `applied`, `rejected`, `failed` or `expired`. It must say plainly when something did **not** happen ("The bot did not collect it within 2 minutes, so nothing was closed"). Closing is not instant: expect up to one report interval (about 5 s) plus the broker. The MT5 phone app stays the fast fallback.

## When things go wrong

| Situation | What the bot does |
|---|---|
| Server unreachable | Keeps running on its **last safe settings**. Manages open trades. Retries with growing delays (5 s, 10 s, 20 s, up to 60 s). Trading code never waits on the network. |
| Server unreachable for a long time | **My call, needs your decision:** keep opening new trades for up to 24 hours, then stop new entries and keep managing open ones. 24 hours is a placeholder. |
| Licence `expired` or `revoked` | Stops new entries. **Still manages and closes open trades.** It never force-closes anything. |
| Licence `grace` | Works normally and shows a notice in the terminal. |
| A command fails a check | Rejects it, reports why, carries on. |
| The broker refuses a **closing** order on an opposite cross (for example market closed) | Retries every 10 s until it works and sends an alert on the first failure, because the account is holding the wrong direction. Found in the tester data: two such closes were refused at 23:19 to 23:45 server time and the trades then stayed open for about 4 and 16 hours. |
| The broker refuses an **entry** order | Retries for up to 5 minutes, then reports the signal as "Missed: market closed" and waits for the next cross. |
| Not enough 1-minute history for the slow average | No signals are raised until 5,000 candles exist. The dashboard shows "Waiting for history". |
| Bot restarts | New `boot_id`, `seq` back to 1, loads last safe settings from disk, reports as normal. |
| Report lost in transit | Next report carries the same unacknowledged deals and command results; nothing is lost and nothing is counted twice. |
| Customer's clock is wrong | No effect on commands (server time is used). |

Every library strategy must put a **stop loss on every order** (this is a rule in the strategy spec template). Stop losses sit at the broker, so the account is still protected while the bot, the server or the customer's PC is down.

## Bot status on the dashboard

The server decides, from the age of the last report:

| Status | Rule (report interval 5 s) |
|---|---|
| `online` | last report within 3 intervals (15 s) |
| `stale` | within 60 s |
| `offline` | older than 60 s |

`offline` for longer than a set time raises a Telegram or email alert ("bot went silent"). How long is a decision for you; I suggest 3 minutes (my call). The `heartbeat` list in the overview shows the last 60 expected report slots, so a flaky connection is visible before it becomes an outage.

## Overview (server to dashboard)

Built by the server from stored reports. Notes on the fields the dashboard shows:

- `snapshot` is the latest report. `day_start` gives balance and equity at 00:00 UTC for the "since start of day" change.
- `equity_series` is balance and equity for the last 24 hours, about one point every 5 minutes, ending with the live values.
- `strategies[].today` and `.total` are closed-trade tallies: `net_profit`, `trades` (closing deals) and `wins` (deals with a positive net result). Floating profit is kept separately in `floating_pl`.
- `strategies[].name` and `settings[].label` come from the strategy library on the server, not from the bot.
- `recent_deals` (newest first) and `recent_signals` (newest first) are capped lists for the first screen. Full history is a later endpoint.
- `strategies[].settings` now carry `min`, `max`, `step` and `editable`, so the dashboard builds its controls from them. `next_lot`'s `max` is the current `max_lot`.
- `bot.trading_paused` is the whole-bot Auto switch. Auto is ON for a strategy only when the strategy is `enabled` and the bot is not paused.
- `recent_commands` lists the controls pressed, newest first, with what became of each (see "Dashboard writes").

### Chart (`chart`)

The strategy is anchored on **1-minute candles**: both averages always come from 1-minute closes, and a chart timeframe only regroups the same candles. `chart.timeframes` holds `1m`, `5m`, `30m`, `1h`, `4h`, `1d` and `1mo` as columns (`t`, `o`, `h`, `l`, `c`, `fast`, `slow`, oldest first, the last candle still forming). `fast` and `slow` are the 1-minute averages at each candle's last 1-minute close.

- `markers` lists **every cross**, and a marker is drawn on the candle that contains it, on every timeframe. Several can share one big candle (up to 34 in one month in the real data).
- **Markers come from this list and are never re-derived from the lines on the big chart**: on a 4-hour candle the opposite cross may already have happened, so the lines at its close can show the newer state. Measured on the real data, the lines disagree with the cross that happened in the candle for 20% of crosses on the 4-hour chart, 36% on the day chart and 49% on the month chart.
- `latest` gives the two averages now, their `gap` (fast minus slow) and the `last_cross`.
- The validator checks that the lines on the 1-minute chart reproduce the marker list exactly, and that the newest candle of every timeframe carries the same latest averages.
- 5, 15 and 30-second charts are not in the contract yet: MT5 has none, and they could only be built from ticks recorded since the bot started.

### Volatility (`volatility`)

"Volatility" is the **typical gold move per hour in dollars** (from squared 1-minute price changes). It is not the VIX. It carries `now` (the last 6 trading hours, with the percentile against the same time of day over 90 days), a 12-hour and a 24-hour `forecast` (expected value, a 10th-to-90th-percentile range, and the chance the next period is more volatile than the one just gone), an hourly `history`, a `scorecard` and the news `events`. Horizons count **trading hours**, so weekends and the daily break do not.

The `scorecard` is the honesty part. It shows how the model did on past data it had not seen, next to three simple guesses (the next period equals the last one; the last period adjusted only for the usual time-of-day pattern; the last 90 days' average), and a `verdict` of `better` only when the model beats every guess on both size and probability. It also shows whether the probabilities came true (`calibration`). The 12-hour forecast partly rests on the daily rhythm (quiet Asian hours, then London and New York), which a time-of-day-only guess also captures, so the scorecard shows that guess separately.

### Alerts (`alerts`)

`events` are what can trigger an alert (buy signal, sell signal, trade closed, lines getting close, broker refused an order, bot went silent), each switchable. `channels` are where alerts go. TradingView alerts are made inside TradingView, so that channel is always `external`. A channel that still `needs_setup` cannot be switched on. `recent` lists the last alerts sent.

## Not in v0.2 (comes in the server phase or later)

- **Activation**: how a customer's licence key becomes a short-lived token (`POST /v1/activate`) and how tokens are signed. Not needed while the dashboard is for one person.
- **Login**: how the one person signs in (a long passphrase plus an authenticator code is the plan) and how the session is protected.
- **Full history** endpoints beyond the first screen.
- **Telegram delivery**: the server-side sender and its token.
- **Settings definitions**: each strategy spec lists its settings with `min`, `max` and default (see `sma-cross-spec.md` for the gold strategy); the server stores them and the bot enforces them.

## Check it yourself

```
python -P tools/make_sample_data.py     # regenerate the sample data (fixed seed, same result every time)
python -P tools/validate_contract.py    # 462 checks: shapes plus "do the numbers add up"
```

The sample data uses **real 1-minute XAUUSD prices** exported from the MT5 tester (`research/data/xauusd_m1.csv`, made with `tools/export_m1.mq5`) and the written strategy rule in `tools/sma_reference.py`. The account around them is simulated. Without that CSV, `make_sample_data.py` stops and says how to export it.

The validator checks, among other things, that equity equals balance plus floating profit, that each strategy's totals equal the sum of its deals, that every position's profit matches its prices, that no command is already expired, **that a bot-owned position's lot is locked and its stop never wider than the one it opened with, that `next_lot` stays inside `max_lot` and the broker's lot step, that the lines on the 1-minute chart reproduce the cross markers exactly, and that a volatility verdict follows its stated rule**. A separate set of 33 deliberate breakages (a widened stop, a lot above the maximum, a deleted marker, a wrong verdict and so on) confirmed that each one is caught.

## Decisions I need from you

1. **Combined round trip** (report and command poll in one request): keep it?
2. **Long outage**: how long may the bot keep opening new trades without the server? (placeholder: 24 hours)
3. **Silence alert**: how long before "bot went silent" is sent? (placeholder: 3 minutes)
4. **Account type**: netting or hedging on Dad's account, and the exact gold symbol name. The contract supports both, but the strategy rules differ.
5. **Refused orders (new)**: retry a refused close every 10 s until it works, and retry a refused entry for up to 5 minutes? (my call)
6. **Stop loss moves (new)**: tighten only, never widen or remove? (my call)
7. **Largest lot (new)**: default cap 0.10, raised only by a deliberate setting? (my call)
8. **Pip definition (new)**: 1 pip = $0.10 on gold, so 300 pips = $30. Check the symbol's digits and contract size on Dad's account.
