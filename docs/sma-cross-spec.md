# Strategy spec: SMA 100 / 5000 cross (gold)

Filled in from `strategy-spec-template.md`. A strategy is ready to build only when a stranger could code it from this page and a second person could check the code against it. Anything marked **(my call)** is a choice I made while drafting and it is not agreed yet; say so and I change it.

| | |
|---|---|
| **Strategy id** | `sma_cross` |
| **Display name** | SMA 100/5000 cross (gold) |
| **Spec version** | 0.1.0 |
| **Author / date** | Draft written by Claude for Abhishek Kholiya, 2026-11-09 |
| **Status** | Draft. The entry and exit rules are the ones the EA already runs and the tester has checked. The new take profit, stop loss and lot rules are **not built and not back-tested**. |

## 1. Idea in two sentences

Gold tends to keep running in one direction after its fast average (100 one-minute candles) crosses its slow average (5,000 one-minute candles, about 3.5 trading days), so the bot follows the new direction and turns around when the lines cross back. It does worst in sideways markets, where the lines cross again and again (11 to 34 times a month in the data below) and each turn-around can lose a little.

## 2. Market

| | |
|---|---|
| **Symbols** | `XAUUSD`. *Pending: the exact name on Dad's account (some brokers add a suffix).* |
| **Chart timeframe** | **Always 1-minute candles.** Both averages are worked out from 1-minute closes. The chart a person looks at (5 s up to 1 month) only changes how it is drawn; it never changes a signal. *Decided by Abhishek, 2026-11-09.* |
| **When it evaluates** | Once per candle: on the first tick of a new 1-minute candle, using the candle that just closed. After a weekend gap that is the first candle that exists. |
| **Trading hours** | New trades only 03:30 to 11:00 IST (IST = UTC + 5:30), changeable. Signals, alerts and the opposite-cross exit work around the clock. *Kept from the current EA (my call).* |
| **Days** | No weekday filter. The bot holds a trade across the weekend. See section 10. |

**Why 1-minute and not "scale the periods per chart"** (measured on 640,903 one-minute bars of XAUUSD, 2025-01-02 to 2026-11-03, with `tools/sma_reference.py`; 451 crosses):

| Chart | Periods if scaled to the same time | Real crosses found within one candle | Extra crosses that do not exist on 1-minute |
|---|---|---|---|
| 5 min | 20 / 1000 | 90% | 47 |
| 15 min | 7 / 333 | 88% | 38 |
| 30 min | 3 / 167 | 89% | 84 |
| 1 hour | 2 / 83 | 82% | 58 |
| 4 hour, day, month | fast average would be shorter than one candle | cannot be built | none |

So scaling gives a different strategy on each chart, and it cannot be built at all from 4 hours up. Anchoring on 1-minute gives the same signals everywhere. What the bigger charts need is a way to **draw** those signals:

| Chart | Candles | Crosses placed | Most crosses in one candle | Crosses whose side disagrees with the two lines drawn at the candle's end |
|---|---|---|---|---|
| 5 min | 128,313 | 451 of 451 | 3 | 3 (1%) |
| 30 min | 21,427 | 451 of 451 | 6 | 11 (2%) |
| 1 hour | 10,724 | 451 of 451 | 6 | 28 (6%) |
| 4 hour | 2,847 | 451 of 451 | 8 | 88 (20%) |
| Day | 475 | 451 of 451 | 11 | 162 (36%) |
| Month | 23 | 451 of 451 | 34 | 222 (49%) |

Rules that follow for the dashboard and for TradingView:

- Each signal is drawn on the candle that **contains** the 1-minute candle that closed it. Several signals can sit in one big candle, so markers stack or show a count.
- Markers come from the 1-minute signal list. They are never re-derived from the two lines on the big chart: on a 4-hour candle the opposite cross may already have happened, and the lines at its close would show the newer state.
- The lines on a bigger chart are the 1-minute averages sampled at each candle's close.
- 5, 15 and 30-second charts are view-only (MT5 has none; they can only be built from ticks recorded since the bot started).

## 3. Entry rules

**Buy when ALL of these are true:**
1. On the last closed 1-minute candle, SMA(100) of closes is **above** SMA(5000) of closes.
2. On the candle before it, SMA(100) was **at or below** SMA(5000). (Together: a fresh upward cross.)
3. **Auto is ON.**
4. The time of the new candle is inside the trading hours.
5. After step "exit on signal" below has closed any opposite trade, this strategy has no open trade.
6. The next-trade lot is valid (section 5).

**Sell when ALL of these are true:** the mirror image: SMA(100) **below** SMA(5000) now, **at or above** it on the candle before, and conditions 3 to 6.

The price does not have to be above or below anything. Only the two averages are compared. *If you also want "the candle must close above the line", that is a different rule and needs a new back-test.*

**Reason shown in the signals feed:**
- Buy: "SMA 100 crossed above SMA 5000 on the 14:32 candle."
- Sell: "SMA 100 crossed below SMA 5000 on the 14:32 candle."

## 4. Exit rules

| | |
|---|---|
| **Stop loss** | Required on every order. Default **100 pips = $10.00** price distance *(your example; to be tuned by back-test)*. Changeable for the next trade. On an open trade it can only be **tightened**, never removed or moved further away than the original. |
| **Take profit** | Default **300 pips = $30.00** price distance, changeable for the next trade. On an open trade it can be moved either way. |
| **Trailing stop** | None. |
| **Exit on signal** | The opposite cross closes the open trade immediately, then the entry rules above may open the other side **on the same candle** (stop-and-reverse). This exit is always active: when Auto is OFF, outside trading hours, and when the lot is invalid. |
| **Manual close** | **Close now** from the dashboard. Afterwards the bot stays flat until the next cross; it never re-enters by itself. |
| **Time exit** | None. |
| **Friday / weekend rule** | None. *Open question, section 10.* |

1 pip = 0.10 price units on XAUUSD, so 300 pips = $30.00. On gold 0.01 lot is 1 ounce, so a $1 move is about $1 of profit or loss at 0.01 lot and about $10 at 0.10 lot. *Verify the symbol's digits and contract size on Dad's account before relying on this.*

**Reason shown in the signals feed:**
- Opposite cross: "Closed: SMA 100 crossed back below SMA 5000."
- Take profit: "Closed at take profit, +$30.00."
- Stop loss: "Closed at stop loss, −$10.00."
- Manual: "Closed by you from the dashboard."

## 5. Trade size

| | |
|---|---|
| **Method** | Fixed lots. |
| **Default size** | 0.01 lot. |
| **Smallest and largest allowed** | Smallest is 0.01 or the broker's minimum if that is higher; steps follow the broker's lot step. Largest is the **max lot** setting (default 0.10, *my call*, to block a typing mistake such as 1.0 instead of 0.1). Raising max lot is a separate, deliberate setting. |
| **Most open trades** | 1. |
| **Pyramiding** | No. |

**Lot rules:**
- An open trade's lot **never changes**. No command can change it, and the bot never closes part of a trade.
- **Next trade lot** can be edited at any time. It is read at the moment the order is sent, so an edit made before the signal applies to that trade; an edit made after applies to the one after.
- The dashboard shows the loss if stopped next to the field (for example 0.05 lot with a $10 stop is about −$50) before the value is saved.

## 6. Filters and safety limits

| | |
|---|---|
| **Maximum spread** | None. *Not part of the tested rules; gold spreads widen sharply around news. Open question.* |
| **News / rollover** | None. The broker's daily trading break matters, see "refused orders" below. |
| **Daily loss limit** | None. |
| **Losing-streak limit** | None. |
| **Minimum margin level** | None. |
| **Slippage** | Up to 50 points accepted (as in the EA). |
| **Refused orders** | **(my call)** A refused **close** is retried every 10 seconds until it succeeds, and an alert is sent on the first failure, because the account is holding the wrong direction. A refused **entry** is retried for up to 5 minutes; after that the signal is reported as "Missed: market closed" and the bot waits for the next cross. |

**Skip reasons** (each shown on the dashboard as a sentence):
- "Auto is off."
- "Outside trading hours (03:30 to 11:00 IST)."
- "Lot 0.50 is above the max lot of 0.10."
- "Broker refused the order: market closed."
- "Missed: market closed for more than 5 minutes."

## 7. Settings the dashboard can change

| Key | Label shown | Type | Default | Min | Max | Unit | Customer may change? |
|---|---|---|---|---|---|---|---|
| `take_profit_pips` | Take profit | whole number | 300 | 20 | 1000 | pips | Yes |
| `stop_loss_pips` | Stop loss | whole number | 100 | 20 | 500 | pips | Yes (cannot be switched off) |
| `next_lot` | Next trade lot | lots | 0.01 | 0.01 | `max_lot` | lots | Yes |
| `max_lot` | Largest lot allowed | lots | 0.10 | 0.01 | 1.00 | lots | Yes |
| `use_trading_hours` | Trade only in set hours | on / off | on | | | | Yes |
| `hours_start_ist` | Hours start | minutes after midnight, IST | 210 (03:30) | 0 | 1439 | minutes | Yes |
| `hours_end_ist` | Hours end | minutes after midnight, IST | 660 (11:00) | 0 | 1439 | minutes | Yes |
| `near_lines_pips` | Heads-up when the lines are this close | whole number, 0 = off | 0 | 0 | 200 | pips | Yes |

**Fixed, not changeable from the dashboard:** fast period 100, slow period 5000, the 1-minute anchor, one trade at a time.

**Auto on/off** is not a setting. It is the existing `strategy.set_enabled` command (this strategy only) and `bot.set_trading_paused` (the whole bot). Off means no new entries; everything in "Exit rules" keeps working.

## 8. Worked example

A real trade from the tester data (MetaQuotes-Demo, XAUUSD, server time GMT+0, lot 0.01), 20 January 2025.

| | |
|---|---|
| Previous candle, 05:19 | close 2700.82, SMA(100) 2696.1142, SMA(5000) 2696.1707. The fast line is **below** the slow line. |
| Signal candle, 05:20 | open 2700.77, high 2700.97, low 2700.69, close 2700.82, SMA(100) 2696.2125, SMA(5000) 2696.1769. The fast line is now **above**. |
| Signal | Buy, confirmed when the 05:20 candle closes, so the bot acts on the first tick of 05:21. |
| Time check | 05:21 GMT = 10:51 IST, inside 03:30 to 11:00. Auto was ON. |
| Stop-and-reverse | A sell from 02:59 (entry 2694.04) was still open. It is closed at 2700.96 for **−6.92** (0.01 lot, 6.92 price move). A buy of 0.01 lot opens at 2700.96 on the same candle. |
| As tested (TP 10, no stop loss) | Take profit at 2710.96, hit at 08:50:29, result **+10.00**. |
| With the new defaults (not tested) | Take profit 2730.96 (+$30.00), stop loss 2690.96 (−$10.00). |

## 9. Tests the build must pass

| # | Situation | Expected |
|---|---|---|
| 1 | A clean cross inside trading hours, Auto on | Opens one trade with the stop loss and take profit from section 4 |
| 2 | The same cross outside trading hours | Skipped, reason "Outside trading hours", alert still sent |
| 3 | Broker refuses the entry (market closed) | Retried up to 5 minutes, then reported as missed |
| 4 | Broker refuses the closing order on an opposite cross | Retried every 10 s until closed, alert on the first failure |
| 5 | Opposite cross with a trade open | Old trade closes, new trade opens on the same candle |
| 6 | Auto switched off with a trade open | No new entries; the trade still reaches stop, target or opposite cross |
| 7 | A setting outside its range | Rejected, previous value kept |
| 8 | Bot restarts with a trade open | Picks the trade up again and manages it |
| 9 | Next lot edited while a trade is open | Open trade unchanged; the next trade uses the new lot |
| 10 | Next lot above max lot | Rejected with the reason |
| 11 | Close now pressed | Trade closes at market, no re-entry until the next cross |
| 12 | A command to move the stop further away, or remove it | Rejected; a move toward the price is applied |
| 13 | A close command that reaches the bot more than 2 minutes late | Expired, trade untouched, dashboard says "not executed" |
| 14 | Same bars viewed on 5m, 30m, 1h, 4h, day, month | Same signals, each placed on the candle that contains it |
| 15 | A cross on the last candle before a weekend | Acted on at the first candle after the gap |

Test 14 and the signal rules are already checked by `tools/sma_reference.py`, see below.

**What has been checked so far** (Phase A, no live account):

- The reference engine (`tools/sma_reference.py`) and the EA agree on every trade in two 21-month tester runs (96 trades each). All 96 entries and every opposite-cross exit land on a reference cross, same minute and same side. The only differences are 5 missed entries and 2 failed closes, each one an order the tester refused with `[Market closed]` between 23:19 and 23:45 server time. A deliberately wrong reference (fast period 99, or slow period 4999) is flagged, so the check can fail.
- 451 crosses in 22 months: 225 buy, 226 sell, 102 inside the trading hours.

## 10. Known weaknesses and open questions

**Evidence so far** (MetaQuotes-Demo data, synthetic ticks from 1-minute bars, 0.01 lot, 2025-01-15 to 2026-11-03, 96 trades). Real Exness prices, spreads and fills will differ.

| Test | Result |
|---|---|
| TP 10, no stop loss | +199.81, profit factor 1.41, worst trade −113.00, balance drawdown 132.90 |
| TP 10, stop loss 10 | +220.99, profit factor 1.63, worst trade −11.27, balance drawdown 40.05 |
| **TP 30, stop loss 10 (the new defaults)** | **Not tested.** Needs a tester run; I will ask before running it. |

- **Choppy markets.** The lines cross 11 to 34 times a month. Each reversal can lose, and a thin edge on 96 trades could be luck.
- **Refused orders at the daily break.** The EA tries once and never retries, so a close refused at 23:19 to 23:45 left a trade open in the wrong direction for about 4 and 16 hours (two cases) until its take profit. Fixed by the retry rule in section 6, in a later EA version.
- **No stop loss in the current EA** (the input is 0). One trade lost 113.00 in the tester.
- **Weekend gaps.** A trade is held over the weekend and a gap can jump past a stop loss.
- **Spread and news.** No spread filter in the tested rules.
- **TradingView feed.** TradingView prices come from a different feed, so its crosses can land a candle away from the bot's. This will be measured when the Pine script is checked.

**Open questions for you:**
1. Is the retry rule for refused orders (close until done, entry up to 5 minutes) what you want?
2. Keep holding trades over the weekend, or close before it?
3. Add a maximum-spread filter?
4. Confirm the pip definition (1 pip = $0.10) on Dad's symbol.
5. Do you want the stricter "candle must also close above the line" rule? It changes the strategy.
