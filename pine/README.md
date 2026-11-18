# TradingView scripts (drafts, not yet run)

I cannot run TradingView, so **neither script has been compiled or tested.** Paste each into the Pine editor and tell me what it says; expect a round or two of fixes.

| File | For | Share it? |
|---|---|---|
| `sma_cross_indicator.pine` | Buy and Sell markers plus two alert conditions. No inputs for the periods, no lines drawn. | Yes, as an **invite-only** script (see below). |
| `sma_cross_strategy.pine` | Your own checking: trades in the Strategy Tester, both lines drawn, TP and SL as inputs. | **No.** It lists every trade and shows the settings. |

## Same signals on every timeframe

Both scripts work from 1-minute candles, like the MT5 bot (`docs/sma-cross-spec.md`). The indicator checks every 1-minute candle inside each bar on bigger charts, so a cross is never missed. **Make the alerts from a 1-minute chart** ("Once Per Bar Close"), so they fire the moment a 1-minute candle closes.

## Setting it up

1. Open an XAUUSD chart on a **1-minute** timeframe. SMA 5000 needs at least 5,000 loaded bars to start; TradingView loads 5,000 on Basic, 10,000 on Essential/Plus, 20,000 on Premium and 40,000 on Ultimate (per TradingView's help page, check the live pricing page). On a small plan the first signals appear only after the warm-up, and the history you can test is short.
2. Pine editor, new indicator, paste `sma_cross_indicator.pine`, **Add to chart**. Do the same with the strategy file in a separate chart layout.
3. Alerts: **Create alert**, condition "Gold cross signals", choose "Gold: Buy signal" (then repeat for Sell), trigger **Once Per Bar Close**.
4. Webhooks are not needed. The MT5 bot is the only thing that trades; TradingView only notifies. (Webhooks need a paid plan, two-factor authentication, port 80 or 443 and a reply within 3 seconds, if you ever want them.)

## Checking it against the MT5 bot

1. Put the strategy file on a 1-minute XAUUSD chart. In the Strategy Tester, open **List of Trades** and export it.
2. Send me the export. I will compare entry and exit times with `research/out/signals.csv` (made by `tools/sma_reference.py` from the MT5 prices) and report how many crosses match to the minute and how many land a candle away. TradingView and Exness use different price feeds, so some difference is expected; this measures how much.
3. Use the same period and set TradingView's chart time zone to UTC before reading times.

## Keeping the strategy hidden (what TradingView allows)

From TradingView's help pages; check them again before relying on this, because plans and rules change.

- Hidden source means an **invite-only** script, which needs a **Premium or Ultimate** plan to publish. Open and "protected" scripts can be published on lower plans, but a protected script is visible to everyone.
- **Private** invite-only scripts are not moderated while they stay private, but are limited to **5 users**, cannot be sold, and cannot be linked from public posts. A **public** invite-only script is moderated, needs a description that says what it does and why it is worth using, cannot show prices, and its description cannot be edited after publishing.
- Publish only the **indicator**. Do not publish the strategy script.
- The indicator has no inputs for the periods and draws no lines, and its alert text has no numbers. The markers still show when it signals, so over time someone can guess it is two moving averages; this deters copying, it is not secrecy.
- Whoever you invite can use the script but cannot see or copy the code.

## What I do not know yet

- Whether `request.security_lower_tf` behaves as I expect on every chart (the code is written from the documentation, not run).
- How TradingView's alert history depth applies to a 5,000-bar average when an alert runs on their servers.
- How far TradingView's gold prices drift from the MT5 feed on crosses. The comparison above answers that.
