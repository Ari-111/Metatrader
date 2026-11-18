"""Gold volatility outlook from 1-minute bars: what it is now, and what the next 12 and 24 trading hours may bring.

    python -P tools/volatility_model.py            # walk-forward scorecard against simple baselines

What it measures. Volatility here is "typical gold move per hour in dollars": the square root of the
sum of squared 1-minute price changes inside an hour, times the price. It is not the VIX. The real VIX
comes from S&P 500 options; the gold equivalent (CBOE GVZ) is daily and slow, so it cannot answer a
12-hour question.

The model (a "HAR" regression, a standard way to forecast realised volatility):
  - take the log of recent volatility over the last hour, 6 hours, 24 hours and 5 days (trading hours),
    after removing the usual time-of-day pattern;
  - fit a straight line from those four numbers to the next 12 (or 24) trading hours;
  - put the time-of-day pattern for the hours ahead back in.
It is refitted every month on data that existed before that month, so every score below is out of sample.

Baselines it must beat: "next period equals the last period" (persistence) and "the last 90 days' average".
If it does not beat them the dashboard says so.

Needs numpy and pandas.
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CSV = ROOT / "research" / "data" / "xauusd_m1.csv"
HORIZONS = (12, 24)
LAGS = (1, 6, 24, 120)          # trading hours
MIN_BARS_PER_HOUR = 40
FIRST_TEST = pd.Timestamp("2025-07-01")


def load_m1(path=DEFAULT_CSV) -> pd.DataFrame:
    df = pd.read_csv(path)
    df["time"] = pd.to_datetime(df["time"], format="%Y.%m.%d %H:%M:%S")
    return df.set_index("time")


def norm_cdf(x):
    return 0.5 * (1.0 + np.vectorize(math.erf)(np.asarray(x) / math.sqrt(2.0)))


# ------------------------------------------------------------------ hourly series

def hourly(df: pd.DataFrame) -> pd.DataFrame:
    """One row per trading hour: rv2 (sum of squared 1-minute log changes), close, bars."""
    close = df["close"]
    r = np.log(close).diff()
    gap = df.index.to_series().diff() > pd.Timedelta(minutes=5)       # weekend or daily break: not a real move
    r[gap] = np.nan
    g = r.groupby(df.index.floor("h"))
    out = pd.DataFrame({"rv2": (r ** 2).groupby(df.index.floor("h")).sum(),
                        "bars": g.count(), "close": close.groupby(df.index.floor("h")).last()})
    out = out[out["bars"] >= MIN_BARS_PER_HOUR].copy()
    out["rv2"] = out["rv2"].clip(lower=1e-12)
    return out


def seasonal_factors(h: pd.DataFrame) -> pd.Series:
    """Average variance in each UTC hour of the day, relative to the overall average."""
    by = h["rv2"].groupby(h.index.hour).mean()
    return (by / by.mean()).reindex(range(24)).fillna(1.0)


def trading_schedule(h: pd.DataFrame) -> set[tuple[int, int]]:
    """(weekday, hour) pairs that normally trade, learned from the data."""
    cnt = h.groupby([h.index.weekday, h.index.hour]).size()
    days = h.groupby([h.index.weekday]).apply(lambda x: x.index.normalize().nunique())
    return {(wd, hr) for (wd, hr), n in cnt.items() if n >= 0.5 * days[wd]}


def future_hours(origin_end: pd.Timestamp, n: int, schedule: set[tuple[int, int]]) -> list[pd.Timestamp]:
    out, t = [], origin_end
    while len(out) < n:
        if (t.weekday(), t.hour) in schedule:
            out.append(t)
        t += pd.Timedelta(hours=1)
    return out


# ------------------------------------------------------------------ features and model

def features(h: pd.DataFrame, seas: pd.Series) -> pd.DataFrame:
    sv = h.index.hour.map(seas).values
    rv2s = h["rv2"].values / sv                                       # time-of-day removed
    s = pd.Series(rv2s, index=h.index)
    f = pd.DataFrame(index=h.index)
    for lag in LAGS:
        f[f"x{lag}"] = 0.5 * np.log(s.rolling(lag).mean())
    return f


def targets(h: pd.DataFrame, seas: pd.Series, horizon: int) -> pd.DataFrame:
    sv = pd.Series(h.index.hour.map(seas).values, index=h.index)
    rv2s = h["rv2"] / sv
    out = pd.DataFrame(index=h.index)
    out["y"] = 0.5 * np.log(rv2s.rolling(horizon).mean().shift(-horizon))                  # next H, deseasonalised
    out["actual"] = np.sqrt(h["rv2"].rolling(horizon).mean().shift(-horizon))             # next H, raw
    out["prev"] = np.sqrt(h["rv2"].rolling(horizon).mean())                               # last H, raw
    out["sv_next"] = np.sqrt(sv.rolling(horizon).mean().shift(-horizon))                  # seasonal factor ahead (offline)
    out["sv_prev"] = np.sqrt(sv.rolling(horizon).mean())                                  # seasonal factor of the last H hours
    return out


def fit(X: pd.DataFrame, y: pd.Series):
    ok = X.notna().all(axis=1) & y.notna()
    A = np.column_stack([np.ones(ok.sum()), X[ok].values])
    beta, *_ = np.linalg.lstsq(A, y[ok].values, rcond=None)
    resid = y[ok].values - A @ beta
    return beta, float(resid.std(ddof=A.shape[1]))


def predict(beta, X: pd.DataFrame):
    return beta[0] + X.values @ beta[1:]


# ------------------------------------------------------------------ walk-forward scorecard

def scorecard(h: pd.DataFrame, horizon: int) -> dict:
    months = pd.date_range(FIRST_TEST, h.index[-1].normalize(), freq="MS")
    rows = []
    for m0 in months:
        m1 = m0 + pd.offsets.MonthBegin(1)
        train = h[h.index < m0 - pd.Timedelta(hours=horizon * 2)]
        if len(train) < 24 * 60:
            continue
        seas = seasonal_factors(train)
        X, T = features(h, seas), targets(h, seas, horizon)
        trainmask = (h.index < m0 - pd.Timedelta(hours=horizon * 2))
        beta, sd = fit(X[trainmask], T.loc[trainmask, "y"])
        test = (h.index >= m0) & (h.index < m1) & (np.arange(len(h)) % 3 == 0) & X.notna().all(axis=1) & T["actual"].notna()
        if not test.any():
            continue
        yhat = predict(beta, X[test])
        sv = T.loc[test, "sv_next"].values
        est = np.exp(yhat) * sv
        avg90 = np.sqrt(h["rv2"].rolling(90 * 22).mean().shift(1)[test]).values            # last ~90 days of trading hours
        prev = T.loc[test, "prev"].values
        tod = prev * sv / T.loc[test, "sv_prev"].values          # "same as last period, adjusted only for the time-of-day pattern"
        part = pd.DataFrame({"actual": T.loc[test, "actual"].values, "prev": prev,
                             "est": est, "avg90": avg90, "tod": tod, "sd": sd, "yhat": yhat}, index=h.index[test])
        part["p_higher"] = norm_cdf((np.log(part["est"]) - np.log(part["prev"])) / sd)
        rows.append(part)
    r = pd.concat(rows).dropna()
    pe = lambda a, b: float(np.mean(np.abs(a - b) / b)) * 100
    higher = (r["actual"] > r["prev"]).astype(float)
    base_rate = float(higher.mean())
    call = (r["est"] > r["prev"]).astype(float)
    # The time-of-day baseline gets its own probability, using the spread of ITS errors measured on the test
    # itself, which is generous to the baseline and so makes the comparison harder for the model.
    tod_sd = float(np.std(np.log(r["actual"] / r["tod"])))
    p_tod = norm_cdf((np.log(r["tod"]) - np.log(r["prev"])) / tod_sd)
    tod_call = (r["tod"] > r["prev"]).astype(float)
    buckets = []
    for lo, hi in ((0, 0.4), (0.4, 0.6), (0.6, 1.01)):
        sel = (r["p_higher"] >= lo) & (r["p_higher"] < hi)
        buckets.append({"label": f"{int(lo*100)}-{min(int(hi*100),100)}%", "n": int(sel.sum()),
                        "said": float(r.loc[sel, "p_higher"].mean()) if sel.any() else None,
                        "happened": float(higher[sel].mean()) if sel.any() else None})
    return {
        "horizon_h": horizon, "samples": int(len(r)), "from": r.index[0], "to": r.index[-1],
        "error_model_pct": pe(r["est"], r["actual"]), "error_persist_pct": pe(r["prev"], r["actual"]),
        "error_avg90_pct": pe(r["avg90"], r["actual"]), "error_tod_pct": pe(r["tod"], r["actual"]),
        "hit_rate": float((call == higher).mean()), "base_rate": max(base_rate, 1 - base_rate),
        "hit_rate_tod": float((tod_call == higher).mean()),
        "brier_model": float(np.mean((r["p_higher"] - higher) ** 2)), "brier_base": float(np.mean((base_rate - higher) ** 2)),
        "brier_tod": float(np.mean((p_tod - higher) ** 2)),
        "buckets": buckets,
    }


def verdict(sc: dict) -> str:
    """'better' only if the model beats EVERY baseline on size error and on the probability score."""
    best_err = min(sc["error_persist_pct"], sc["error_avg90_pct"], sc["error_tod_pct"])
    best_brier = min(sc["brier_base"], sc["brier_tod"])
    better_err = sc["error_model_pct"] < best_err - 1.0
    better_dir = sc["brier_model"] < best_brier - 0.005
    if better_err and better_dir:
        return "better"
    if better_err or better_dir:
        return "mixed"
    return "no better"


# ------------------------------------------------------------------ live forecast block for the dashboard

def level_name(pct: float) -> str:
    return "calm" if pct < 0.25 else "normal" if pct < 0.75 else "high" if pct < 0.95 else "extreme"


def volatility_block(df: pd.DataFrame, now: pd.Timestamp, history_hours: int = 168) -> dict:
    """Everything the Volatility screen shows, using only bars that closed before `now`."""
    df = df[df.index < now]
    h_all = hourly(df)
    last_hour_end = df.index[-1].floor("h") + pd.Timedelta(hours=1)
    h = h_all[h_all.index + pd.Timedelta(hours=1) <= max(last_hour_end, now.floor("h"))]
    schedule = trading_schedule(h_all)
    price = float(df["close"].iloc[-1])

    forecasts, cards = [], []
    for H in HORIZONS:
        seas = seasonal_factors(h)
        X, T = features(h, seas), targets(h, seas, H)
        beta, sd = fit(X[T["y"].notna()], T.loc[T["y"].notna(), "y"])
        x_now = X.iloc[[-1]]
        yhat = float(predict(beta, x_now)[0])
        ahead = future_hours(h.index[-1] + pd.Timedelta(hours=1), H, schedule)
        sv = math.sqrt(float(np.mean([seas[t.hour] for t in ahead])))
        est = math.exp(yhat) * sv
        prev = float(np.sqrt(h["rv2"].iloc[-H:].mean()))
        z10, z90 = -1.2816, 1.2816
        forecasts.append({
            "horizon_h": H, "expected": round(est * price, 2),
            "low": round(math.exp(yhat + z10 * sd) * sv * price, 2), "high": round(math.exp(yhat + z90 * sd) * sv * price, 2),
            "change_pct": round((est / prev - 1) * 100, 1),
            "prob_higher": round(float(norm_cdf((math.log(est) - math.log(prev)) / sd)), 2),
            "last_period": round(prev * price, 2),
        })
        cards.append(scorecard(h_all[h_all.index < now - pd.Timedelta(hours=H)], H))

    last6 = float(np.sqrt(h["rv2"].iloc[-6:].mean()))
    same_hour = []
    trail = np.sqrt(h["rv2"].rolling(6).mean())
    for t, v in trail.items():
        if t.hour == h.index[-1].hour and t < h.index[-1] and (h.index[-1] - t) <= pd.Timedelta(days=90):
            same_hour.append(v)
    pct = float(np.mean(np.array(same_hour) <= last6)) if same_hour else 0.5
    tail = h.iloc[-history_hours:]
    return {
        "as_of": now,
        "unit": "USD per hour",
        "now": {"value": round(last6 * price, 2), "percentile": round(pct, 2), "level": level_name(pct)},
        "forecasts": forecasts,
        "history": {"t": list(tail.index), "value": [round(math.sqrt(float(v)) * float(c), 2) for v, c in zip(tail["rv2"], tail["close"])]},
        "scorecard": cards,
    }


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    h = hourly(load_m1())
    print(f"{len(h)} trading hours, {h.index[0]} .. {h.index[-1]}")
    print(f"typical move per hour: median {np.sqrt(h['rv2']).median() * h['close'].median():.2f} USD\n")
    for H in HORIZONS:
        sc = scorecard(h, H)
        print(f"== next {H} trading hours, tested {sc['from'].date()} .. {sc['to'].date()}, {sc['samples']} forecasts ==")
        print(f"  average size error   model {sc['error_model_pct']:.1f}%   persistence {sc['error_persist_pct']:.1f}%   "
              f"time-of-day only {sc['error_tod_pct']:.1f}%   90-day average {sc['error_avg90_pct']:.1f}%")
        print(f"  'higher than the last {H} h' called right   model {sc['hit_rate']:.1%}   time-of-day only {sc['hit_rate_tod']:.1%}   "
              f"always-the-common-answer {sc['base_rate']:.1%}")
        print(f"  Brier score (lower is better)   model {sc['brier_model']:.3f}   time-of-day only {sc['brier_tod']:.3f}   no-skill {sc['brier_base']:.3f}")
        for b in sc["buckets"]:
            if b["n"]:
                print(f"    model said {b['label']:>8} (avg {b['said']:.0%}), happened {b['happened']:.0%}  [{b['n']} cases]")
        print(f"  verdict: {verdict(sc)}\n")


if __name__ == "__main__":
    main()
