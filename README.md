# Bot Console

A dashboard and a written-down strategy for an MT5 gold bot (SMA 100 / SMA 5000 cross, anchored on 1-minute candles). This is **Phase A**: everything that can be built and checked without a server, a broker account or a live MT5 connection. There is no server and no MT5 bot code beyond the original EA yet.

| Folder | What is in it |
|---|---|
| `docs/sma-cross-spec.md` | **The strategy as a written spec**: entry and exit rules, lot rules, take profit and stop loss, trading hours, a worked example from real prices, tests, known weaknesses. Start here. |
| `docs/data-contract.md` | What the bot, server and dashboard say to each other (v0.2), the five commands and their safety rules. |
| `docs/strategy-spec-template.md` | The blank page for any further strategy. |
| `contract/` | The exact message shapes (JSON Schema) and worked examples. |
| `dashboard/` | The clickable mock-up with seven screens: Overview, **Trade** (Close now, Auto switch, next-trade lot, TP/SL), **Chart** (1 min to month, same signals), **Volatility**, Trades, Strategies, **Alerts**. Double-click `dashboard/index.html`; it needs no server. |
| `tools/` | `sma_reference.py` (the rule as code, and the checks against the EA), `volatility_model.py`, `make_sample_data.py`, `validate_contract.py`, `export_m1.mq5`. |
| `research/` | `data/xauusd_m1.csv` (640,903 one-minute bars, 2 Jan 2025 to 3 Nov 2026, exported from the MT5 tester) and `out/signals.csv` (every cross). |
| `pine/` | TradingView drafts (an indicator to share, a strategy for your own testing). **Not yet run in TradingView.** |

## What is real and what is simulated

- **Real:** the 1-minute gold prices (MetaQuotes-Demo test feed, not Exness), every cross, the volatility model and its scorecard.
- **Simulated:** the account, the trades and results, the news events, and every control on the dashboard. The sample trades follow the written rule on real bars with take profit 300 pips and stop loss 100 pips. That is a replay on 1-minute candles, **not an MT5 tester result and not a promise of future results.** Nothing is connected to a broker.

## Check it

Needs Python 3.11+ with `numpy`, `pandas` and `jsonschema`, and Node for the optional syntax check.

```
python -P tools/sma_reference.py signals      # every cross in the exported prices
python -P tools/sma_reference.py timeframes   # the same signals placed on 5m ... 1 month candles
python -P tools/sma_reference.py scaled       # why "scale the periods per chart" is a different strategy
python -P tools/sma_reference.py parity REPORT.htm --log TESTER.log   # an MT5 tester report against the rule
python -P tools/volatility_model.py           # walk-forward scorecard of the 12 h and 24 h forecast
python -P tools/make_sample_data.py           # regenerate the dashboard sample (same result every time)
python -P tools/validate_contract.py          # 462 checks: shapes plus "do the numbers add up"
```

To refresh the price data: copy `tools/export_m1.mq5` into MT5's `MQL5/Experts`, compile it, and run it once in the Strategy Tester on XAUUSD with a very short date range (it writes the bars before that range to `Common/Files/xauusd_m1.csv`, then stops).

## What is still open

See the end of `docs/sma-cross-spec.md` and `docs/data-contract.md`. In short: your TradingView plan, the exact gold symbol and account type on Dad's account, who hosts the server, the Indian-rules check by a qualified professional before any real account is connected, and your approval before I run a TP 30 / SL 10 back-test in the MT5 tester.
