# Strategy spec: [Strategy name]

Copy this file for each strategy and fill in every section. A strategy is ready to build only when a stranger could code it from this page and a second person could check the code against it. Where a section does not apply, write "None" rather than leaving it blank. Text in *italics* is guidance; delete it as you go.

| | |
|---|---|
| **Strategy id** | *lowercase with underscores, never reused. Example: `sma_cross`* |
| **Display name** | *what customers see* |
| **Spec version** | 0.1.0 |
| **Author / date** | |
| **Status** | Draft / Agreed / Built / Tested on demo / Live |

## 1. Idea in two sentences

*What market behaviour does this try to profit from, and when does it tend to fail? Plain words. This also becomes the strategy description customers read.*

## 2. Market

| | |
|---|---|
| **Symbols** | *Exact broker names, for example `XAUUSD`. Pending: the real name on Dad's account.* |
| **Chart timeframe** | *M5, M15, H1 ...* |
| **When it evaluates** | *On the close of each bar (recommended, easier to test) or on every price tick* |
| **Trading hours** | *Start and end, and which time zone. Example: 07:00 to 18:00 UTC.* |
| **Days** | *Mon to Fri, or exclusions such as Friday after 18:00 UTC* |

## 3. Entry rules

*Write each condition as something that is true or false on a given bar. Give every number.*

**Buy when ALL of these are true:**
1. 
2. 

**Sell when ALL of these are true:**
1. 
2. 

*Name every indicator with its exact settings and price used (close, median ...). If the strategy only trades one direction, say so.*

**Plain-language reason for the dashboard**, one short line for each entry type. These appear in the signals feed. Example: "Fast SMA (20) crossed above slow SMA (50)".

## 4. Exit rules

| | |
|---|---|
| **Stop loss** | *Required on every order. Distance or formula. A strategy without a stop loss is not accepted into the library.* |
| **Take profit** | *Distance, formula, or "none"* |
| **Trailing stop** | *None, or when it starts and how far it trails* |
| **Exit on signal** | *Which condition closes the trade early. Example: fast SMA crosses back below slow SMA* |
| **Time exit** | *Close after N hours, or at a fixed time of day, or none* |
| **Friday / weekend rule** | *Close before the weekend close, or hold* |

**Plain-language reason for the dashboard** for each exit type.

## 5. Trade size

| | |
|---|---|
| **Method** | *Fixed lots, or percent of balance risked per trade (then give the formula)* |
| **Default size** | |
| **Smallest and largest allowed** | *Also check the broker's lot step and minimum* |
| **Most open trades for this strategy** | |
| **Pyramiding allowed?** | *May it add to a winning trade? Under what rule?* |

## 6. Filters and safety limits

| | |
|---|---|
| **Maximum spread** | *No entry if the spread is wider. Gold spreads widen sharply around news.* |
| **News / rollover** | *Pause around which events or times, if any* |
| **Daily loss limit** | *Stop new entries for the day after losing this much* |
| **Losing-streak limit** | *Stop after N losses in a row, until reset* |
| **Minimum margin level** | *No new entry if margin level falls below this percent* |
| **Slippage / requote** | *Maximum slippage accepted, and what to do if the order is refused* |

Every skipped signal is reported to the dashboard with its reason, so write each reason as a sentence a customer can read.

## 7. Settings the dashboard can change

*Every number a customer may adjust. The bot refuses any value outside the range, so the range protects customers from a typo or a wrong command.*

| Key | Label shown | Type | Default | Min | Max | Unit | Customer may change? |
|---|---|---|---|---|---|---|---|
| `fast_period` | Fast SMA period | whole number | 20 | 5 | 100 | bars | Yes |
| | | | | | | | |

*Example row shown for format only. Keys are lowercase with underscores (2 to 32 characters). Anything not listed here cannot be changed from the dashboard.*

## 8. Worked example

*One complete trade calculated by hand, so the code can be checked against it.*

| | |
|---|---|
| Bar data (time, open, high, low, close) | |
| Indicator values | |
| Signal | |
| Entry price, stop loss, take profit | |
| What happens next, and the result in account currency | |

## 9. Tests the build must pass

*Each test is: given these bars, the strategy does this. Include at least:*

| # | Situation | Expected |
|---|---|---|
| 1 | A clean entry signal inside trading hours | Opens one trade with the stop loss and take profit from section 4 |
| 2 | The same signal outside trading hours | Skipped, reason "Outside trading hours" |
| 3 | Spread wider than the limit | Skipped, reason names the spread |
| 4 | Already at the most open trades allowed | Skipped, reason says so |
| 5 | Exit condition occurs | Trade closes, reason reported |
| 6 | Strategy switched off while a trade is open | No new entries; the open trade still reaches its stop, target or exit |
| 7 | A setting outside its allowed range | Rejected, previous value kept |
| 8 | Bot restarts with a trade open | Picks the trade up again and manages it |

## 10. Known weaknesses and open questions

*Where this strategy loses money (choppy markets, news spikes, wide spreads). Anything undecided goes here, so it is not silently decided in code.*
