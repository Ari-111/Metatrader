"""Reference signal engine for the SMA 100 / SMA 5000 cross strategy.

The strategy is anchored on 1-minute candles: both averages are always worked out
from 1-minute closes, whatever chart the person is looking at. This file is the
written-in-code version of the rule in docs/sma-cross-spec.md, so the EA, the Pine
script and the dashboard can each be checked against it.

    python -P tools/sma_reference.py signals              # list every cross, write research/out/signals.csv
    python -P tools/sma_reference.py parity REPORT.htm ... [--log TESTER.log]   # EA tester report(s) against the reference
    python -P tools/sma_reference.py timeframes           # same signals on 5m ... 1 month charts
    python -P tools/sma_reference.py scaled               # why "scale the periods per chart" is not the same strategy

Needs numpy and pandas. Times are the broker server time of the tester data, which
was GMT+0 for this export, so they are treated as UTC.
"""
import argparse
import html
import re
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CSV = ROOT / "research" / "data" / "xauusd_m1.csv"
OUT_DIR = ROOT / "research" / "out"

FAST, SLOW = 100, 5000
IST_OFFSET = pd.Timedelta(hours=5, minutes=30)
SESSION_START = (3, 30)   # IST, new trades only
SESSION_END = (11, 0)


# ---------------------------------------------------------------- data and signals

def load_m1(path=DEFAULT_CSV):
    df = pd.read_csv(path)
    df["time"] = pd.to_datetime(df["time"], format="%Y.%m.%d %H:%M:%S")
    return df.set_index("time")


def averages(close, fast=FAST, slow=SLOW):
    return close.rolling(fast).mean(), close.rolling(slow).mean()


def find_signals(df, fast=FAST, slow=SLOW):
    """Every cross, exactly as the EA tests it on the last closed candle.

    Buy  : fast[prev] <= slow[prev] and fast[now] >  slow[now]
    Sell : fast[prev] >= slow[prev] and fast[now] <  slow[now]
    'bar'     is the open time of the candle that just closed.
    'act_at'  is the open time of the NEXT candle (the first tick of it is when the
              EA acts). Across a weekend gap this is the next bar that exists.
    """
    f, s = averages(df["close"], fast, slow)
    up = (f.shift(1) <= s.shift(1)) & (f > s)
    dn = (f.shift(1) >= s.shift(1)) & (f < s)
    idx = df.index
    nxt = pd.Series(idx[1:].append(pd.DatetimeIndex([pd.NaT])), index=idx)
    rows = []
    for side, mask in (("buy", up), ("sell", dn)):
        sel = mask[mask].index
        rows.append(pd.DataFrame({"bar": sel, "act_at": nxt.loc[sel].values, "side": side,
                                  "fast": f.loc[sel].values, "slow": s.loc[sel].values}))
    out = pd.concat(rows).sort_values("bar").reset_index(drop=True)
    return out.dropna(subset=["act_at"]).reset_index(drop=True)


def in_session(ts):
    ist = ts + IST_OFFSET
    now = ist.hour * 60 + ist.minute
    a = SESSION_START[0] * 60 + SESSION_START[1]
    b = SESSION_END[0] * 60 + SESSION_END[1]
    return (a <= now < b) if a < b else (now >= a or now < b)


# ---------------------------------------------------------------- tester reports

def read_deals(path):
    """Pair up in/out deals from an MT5 tester HTML report."""
    raw = Path(path).read_bytes()
    text = raw.decode("utf-16") if raw[:2] in (b"\xff\xfe", b"\xfe\xff") else raw.decode("utf-8", "replace")
    rows = []
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", text, flags=re.S | re.I):
        cells = [re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", "", c))).strip()
                 for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", tr, flags=re.S | re.I)]
        if any(cells):
            rows.append(cells)
    start = next(i for i, c in enumerate(rows) if c and c[0] == "Time" and "Deal" in c)
    num = lambda x: float(re.sub(r"[\s ]", "", x))
    trades, cur = [], None
    for c in rows[start + 1:]:
        if len(c) < 13 or c[3] not in ("buy", "sell"):
            continue
        t = pd.Timestamp(pd.to_datetime(c[0], format="%Y.%m.%d %H:%M:%S"))
        if c[4] == "in":
            cur = {"side": "buy" if c[3] == "buy" else "sell", "open": t, "open_price": num(c[6])}
        elif c[4] == "out" and cur:
            comment = c[12].lower()
            cur["close"] = t
            cur["close_price"] = num(c[6])
            cur["net"] = num(c[10]) + num(c[8]) + num(c[9])
            cur["reason"] = "tp" if comment.startswith("tp") else "sl" if comment.startswith("sl") else "cross"
            trades.append(cur)
            cur = None
    return pd.DataFrame(trades)


def read_failed_orders(log_path):
    """Minutes (and order side) at which the tester refused an order, e.g. '[Market closed]'.

    The log may hold several test runs, so this is a union over all of them.
    """
    raw = Path(log_path).read_bytes()
    text = raw.decode("utf-16") if raw[:2] in (b"\xff\xfe", b"\xfe\xff") else raw.decode("utf-8", "replace")
    found = {}
    for m in re.finditer(r"(\d{4}\.\d\d\.\d\d \d\d:\d\d):\d\d\s+failed market (buy|sell) [^\[\r\n]*\[([^\]\r\n]+)\]", text):
        found[(pd.Timestamp(pd.to_datetime(m.group(1), format="%Y.%m.%d %H:%M")), m.group(2))] = m.group(3)
    return found


def cmd_parity(args):
    df = load_m1(args.csv)
    sig = find_signals(df)
    failed = read_failed_orders(args.log) if args.log else {}
    for report in args.reports:
        tr = read_deals(report)
        lo = tr["open"].min().floor("D")
        hi = tr["close"].max()
        # The EA starts on the first tick of the test, so ignore crosses before the first day
        sg = sig[(sig["act_at"] >= lo) & (sig["act_at"] <= hi)].copy()
        sg["in_session"] = sg["act_at"].map(in_session)
        tr["open_m"] = tr["open"].dt.floor("min")
        tr["close_m"] = tr["close"].dt.floor("min")
        key = lambda a, b: set(zip(a, b))
        sig_all = key(sg["act_at"], sg["side"])
        sig_ses = key(sg.loc[sg["in_session"], "act_at"], sg.loc[sg["in_session"], "side"])
        entries = key(tr["open_m"], tr["side"])
        cross_exits = tr[tr["reason"] == "cross"]
        # a long is closed by a sell cross and vice versa
        exit_keys = key(cross_exits["close_m"], cross_exits["side"].map({"buy": "sell", "sell": "buy"}))

        entries_not_signals = sorted(entries - sig_all)
        missing_all = sorted(sig_ses - entries)
        exits_not_signals = sorted(exit_keys - sig_all)
        # a position must never be open across an opposite cross
        spanning_all = []
        for _, t in tr.iterrows():
            opp = "sell" if t["side"] == "buy" else "buy"
            hit = sg[(sg["side"] == opp) & (sg["act_at"] > t["open_m"]) & (sg["act_at"] < t["close_m"])]
            spanning_all += [(x, opp) for x in hit["act_at"]]
        # an order the tester refused (an entry order or a close order, both are sent on the cross candle)
        missing_entries = [k for k in missing_all if k not in failed]
        spanning = [k for k in spanning_all if k not in failed]
        explained_entries = [k for k in missing_all if k in failed]
        explained_spans = [k for k in spanning_all if k in failed]
        print(f"=== {Path(report).name} ===")
        print(f"  reference crosses in range {sg['act_at'].min()} .. {sg['act_at'].max()}: {len(sg)} "
              f"({int(sg['in_session'].sum())} inside the 03:30-11:00 IST window)")
        print(f"  EA trades: {len(tr)}  (closed by TP {int((tr['reason']=='tp').sum())}, SL {int((tr['reason']=='sl').sum())}, "
              f"opposite cross {int((tr['reason']=='cross').sum())})")
        print(f"  EA entries that are NOT a reference cross (same minute, same side): {len(entries_not_signals)}")
        print(f"  EA cross-exits that are NOT an opposite reference cross:            {len(exits_not_signals)}")
        print(f"  in-window crosses with no EA entry, unexplained:                    {len(missing_entries)}")
        print(f"  trades left open across an opposite cross, unexplained:             {len(spanning)}")
        print(f"  explained by the broker refusing the order:                         "
              f"{len(explained_entries)} missed entries, {len(explained_spans)} failed closes")
        for k in explained_entries + explained_spans:
            print(f"    {k[0]} {k[1]}: {failed[k]}")
        for name, items in (("entry not a cross", entries_not_signals), ("cross without entry", missing_entries),
                            ("exit not a cross", exits_not_signals), ("open across a cross", spanning)):
            for it in items[:5]:
                print(f"    UNEXPLAINED {name}: {it}")
        ok = not (entries_not_signals or missing_entries or exits_not_signals or spanning)
        print("  RESULT:", "MATCH (every difference is a refused order)" if ok else "MISMATCH")
        print()


# ---------------------------------------------------------------- the same signals on every chart

TIMEFRAMES = [("5m", "5min"), ("30m", "30min"), ("1h", "1h"), ("4h", "4h"), ("1d", "1D"), ("1mo", "MS")]


def coarse(df, rule):
    return df.resample(rule, closed="left", label="left").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last"}).dropna()


def cmd_signals(args):
    df = load_m1(args.csv)
    sig = find_signals(df)
    sig["in_session"] = sig["act_at"].map(in_session)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    sig.to_csv(OUT_DIR / "signals.csv", index=False, date_format="%Y-%m-%dT%H:%M:%SZ")
    n = len(sig)
    print(f"bars {len(df)}  {df.index[0]} .. {df.index[-1]}")
    print(f"first valid SMA {SLOW} at {df.index[SLOW - 1]}")
    print(f"crosses: {n}  buy {int((sig['side']=='buy').sum())}  sell {int((sig['side']=='sell').sum())}  "
          f"inside window {int(sig['in_session'].sum())}")
    print("by month:", dict(sig.groupby(sig["bar"].dt.to_period("M")).size()))
    print(f"written {OUT_DIR / 'signals.csv'}")


def cmd_timeframes(args):
    df = load_m1(args.csv)
    sig = find_signals(df)
    f, s = averages(df["close"])
    state = pd.DataFrame({"f": f, "s": s})
    print(f"{len(sig)} crosses from 1-minute closes. Where each one lands on a bigger chart:\n")
    print(f"{'chart':<6}{'bars':>8}{'crosses placed':>16}{'busiest bar':>13}{'overlay disagrees':>19}")
    for name, rule in TIMEFRAMES:
        cb = coarse(df, rule)
        pos = cb.index.searchsorted(sig["bar"], side="right") - 1
        placed = int((pos >= 0).sum())
        per_bar = pd.Series(pos).value_counts()
        # value of both averages at the close of each big candle = their value at its last 1-minute bar
        end_state = state.resample(rule, closed="left", label="left").last().loc[cb.index]
        sgn = (end_state["f"] > end_state["s"]).iloc[pos]
        want = (sig["side"] == "buy").values
        disagree = int(((sgn.values != want) & ~end_state["f"].iloc[pos].isna().values).sum())
        print(f"{name:<6}{len(cb):>8}{placed:>13}/{len(sig):<3}{int(per_bar.max()):>10}{disagree:>13} ({disagree/len(sig):.0%})")
    print("\ncrosses placed : every cross lands on exactly one candle of that chart (the one holding the 1-minute candle that closed it).")
    print("busiest bar    : most crosses inside a single candle, so markers there need stacking or a count.")
    print("overlay disagrees: crosses whose side differs from the two lines drawn at the END of the big candle, because the")
    print("                 opposite cross happened later inside the same candle. Markers must come from the 1-minute signal list,")
    print("                 not be re-derived from the lines drawn on the big chart.")


def cmd_scaled(args):
    df = load_m1(args.csv)
    ref = find_signals(df)
    print("Alternative: shrink the periods so they cover the same TIME on each chart (100 min and 5000 min).\n")
    print(f"{'chart':<6}{'periods':>12}{'crosses':>9}{'within 1 bar of a real one':>30}{'extra crosses':>15}")
    for name, rule, minutes in (("5m", "5min", 5), ("15m", "15min", 15), ("30m", "30min", 30), ("1h", "1h", 60)):
        fp, sp_ = round(FAST / minutes), round(SLOW / minutes)
        cb = coarse(df, rule)
        sc = find_signals(cb, fp, sp_)
        tol = pd.Timedelta(minutes=minutes)
        hit = 0
        used = set()
        for _, r in ref.iterrows():
            cand = sc[(sc["side"] == r["side"]) & ((sc["act_at"] - r["act_at"]).abs() <= tol)]
            if len(cand):
                hit += 1
                used.add(int(cand.index[0]))
        extra = len(sc) - len(used)
        print(f"{name:<6}{f'{fp}/{sp_}':>12}{len(sc):>9}{f'{hit}/{len(ref)} ({hit/len(ref):.0%})':>30}{extra:>15}")
    for name, minutes in (("4h", 240), ("1d", 1440), ("1mo", 43200)):
        print(f"{name:<6}{f'{FAST/minutes:.2f}/{SLOW/minutes:.1f}':>12}   cannot be built: the fast average would be shorter than one candle")
    print(f"\nReference: {len(ref)} crosses from 1-minute closes.")


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--csv", default=str(DEFAULT_CSV), help="1-minute bars exported by tools/export_m1.mq5")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("signals").set_defaults(fn=cmd_signals)
    p = sub.add_parser("parity")
    p.add_argument("reports", nargs="+")
    p.add_argument("--log", help="tester log holding the run(s), to account for refused orders")
    p.set_defaults(fn=cmd_parity)
    sub.add_parser("timeframes").set_defaults(fn=cmd_timeframes)
    sub.add_parser("scaled").set_defaults(fn=cmd_scaled)
    args = ap.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
