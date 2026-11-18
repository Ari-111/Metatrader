# Your gold bot and dashboard: what you asked for, what exists, what happens next

Dated 2026-11-15. Plain-language reply to your 15-point list. Nothing here is a promise of profit.

## What you will receive

A working service, not a folder of files:

1. **The bot** (a compiled MT5 file) that runs inside your own MetaTrader 5, logged in to your own Exness account. You type your own password. I never see it.
2. **A dashboard** for your laptop and phone, for one person, with a login. You can see trades, switch Auto on and off, set the lot for the next trade, and close a trade by hand.
3. **A TradingView indicator** that shows the buy and sell signals and sends alerts. It does not place trades.

You will **not** receive the strategy's source files. The TradingView indicator is shared as an invite-only script so you can use it but not read it.

## Your points, one by one

| Your point | Where it stands today |
|---|---|
| 1. Same strategy on every timeframe | **Designed and checked on past prices.** The signals always come from 1-minute candles. A bigger chart only redraws the same signals, so a 5-minute, 1-hour or monthly chart shows the same buys and sells (451 crosses checked, all placed). **Not possible:** 5, 15 and 30-second charts. MT5 has none, so they could only be view-only drawings. |
| 2. Volatility forecast (VIX-style) | **Built and tested on past data** for the next 12 and 24 hours. It is a gold-volatility forecast, **not the real VIX**, which measures the US stock market. A scorecard on the dashboard shows whether it beats simple guesses. It may not. |
| 3. Alerts on the 100 / 5,000 lines, buy and sell, take profit about $30 (300 pips), stop early by hand | **Written down and shown in the demo.** The bot you can test today uses a $10 take profit and cannot be closed from a screen. The new version is not built yet. |
| 5. Stop loss about $10, closable by hand | **Written down and shown in the demo.** Today's bot has **no stop loss**. The new version will always set one. |
| 7. Lot fixed once a trade is open | **Written down.** Nothing can change the lot of an open trade. |
| 9. On/off switch and lot box | **Shown in the demo only.** Today's bot has an ON/OFF button on the chart. |
| 11. Exness and TradingView alerts; lot editable before the trigger | **TradingView:** the indicator is written but has not yet been run in TradingView. **Exness side:** see question 2 below. Editing the lot before a signal is in the written rules. |
| 13. Laptop and phone dashboard, one person | **Demo only** (7 screens, simulated data, not connected to anything). The server and login are the next build. |
| 13. Lock the TradingView strategy | Done with an **invite-only** script. It hides the code. It does **not** make the behaviour secret: someone watching the markers for long enough could work out it is two moving averages. |
| 15. Minimum lot 0.01, editable | **Written down.** A cap on the largest lot (suggested 0.10) stops typing mistakes. |

## What the tests say so far, and their limits

- Tested on a MetaTrader demo price feed (not Exness prices), 21 months, 0.01 lot, 96 trades. With a $10 take profit and a $10 stop loss the test made +220.99, with the worst single trade −11.27. With no stop loss one trade lost 113.00.
- **Your settings, $30 take profit and $10 stop loss, have not been tested yet.** I will not run that test without agreeing it with you first.
- Real Exness prices, spreads and fills will differ. The averages cross 11 to 34 times a month, and in sideways markets each turn-around can lose a little.
- In the tests, two trades stayed open in the wrong direction for 4 and 16 hours because the broker refused the closing order at its daily break and the bot did not try again. The new version will keep retrying.

## The order of work

1. **Now:** you read this, look at the demo, and answer the three questions.
2. **Demo-account trial, 2 to 4 weeks:** the full system on an Exness **demo** account, with no real money.
3. **Live account, 0.01 lot:** only after your written OK and after the check described next.

## Before any real money

Exness appears on the Reserve Bank of India's "alert list" of forex platforms not authorised for Indian residents (listed since September 2022; I could only confirm the November 2025 update through a reproduction of the press release, not the RBI page itself). The RBI says people using unauthorised platforms can face action under FEMA. I am not a lawyer. **A qualified Indian professional should confirm your position before the live stage.**

## Three questions for you

1. You wrote that the trade should start once "the candle closes above that line". The bot today uses the two averages crossing, checked when each 1-minute candle closes. Do you mean that, or must the **price** also close above both lines? The second is a different strategy and would need a new test.
2. "Exness alerts": do you mean phone or Telegram messages from the bot when a trade opens or closes?
3. Will anyone besides you use the TradingView indicator? Invite-only scripts need a Premium or Ultimate TradingView plan to publish, and a privately shared one is limited to 5 people.

## What the bot needs from you

- A computer or a Windows VPS that keeps MT5 running whenever gold trades. Exness offers a free VPS on some accounts, with conditions that vary by client and are shown in your Exness Personal Area, so check there.
- Your TradingView plan must load enough history for a 5,000-bar average and allow alerts.
