# -*- coding: utf-8 -*-
"""
Horus Flow API — monthly order-book value test (standalone script, prints JSON).

Does the archived spot order book still tell us about the next move? For one calendar month of
calibration_data/flow_history (15-second snapshots), every field below is ranked against the return
that followed (1, 5 and 15 minutes), on non-overlapping samples, separately in each half of the month.
A field counts only when both halves agree in sign with |t| >= 2. Each month is a fresh out-of-sample
check; first result (2026-10-23..27): top5_imbalance IC ~0.07 at 1 minute, Horus's direction label none.

Run by the status monitor once a month in its own low-priority process:
    python3 -I app/book_value_test.py --month 2026-10 [--dir calibration_data/flow_history]
"""
import argparse
import glob
import gzip
import json
import os

import numpy as np
import pandas as pd

FEATURES = ["top5_imbalance", "bid_ask_ratio", "buy_sell_ratio", "delta_30s", "delta_5s", "bid_depth_change_pct",
            "ask_depth_change_pct", "dir"]
HORIZONS = ((60, "1m"), (300, "5m"), (900, "15m"))
MIN_SAMPLES = 100


def load_month(base: str, month: str) -> pd.DataFrame:
    """First snapshot of each symbol in each minute (prices every minute are enough for 1-15 minute returns)."""
    keep = {}
    for path in sorted(glob.glob(os.path.join(base, f"{month}-*", "*.jsonl.gz"))):
        with gzip.open(path, "rt") as f:
            for line in f:
                d = json.loads(line)
                k = (d.get("symbol"), int(d.get("_ts", 0) // 60))
                if k not in keep:
                    keep[k] = d
    df = pd.DataFrame(list(keep.values()))
    if df.empty:
        return df
    for c in set(FEATURES + ["price", "_ts"]) - {"dir"}:
        df[c] = pd.to_numeric(df.get(c), errors="coerce")
    df["dir"] = df["direction_bias"].map({"BULLISH": 1, "BEARISH": -1}).fillna(0) if "direction_bias" in df else 0
    return df[df["price"] > 0]


def evaluate(df: pd.DataFrame) -> list:
    mid = (df["_ts"].min() + df["_ts"].max()) / 2
    out = []
    for H, label in HORIZONS:
        parts = []
        for _, g in df.groupby("symbol"):
            g = g.sort_values("_ts")
            fut = g[["_ts", "price"]].rename(columns={"_ts": "ts_f", "price": "price_f"})
            m = pd.merge_asof(g.assign(target=g["_ts"] + H), fut, left_on="target", right_on="ts_f",
                              direction="forward", tolerance=45)
            m["ret"] = m["price_f"] / m["price"] - 1
            m = m.dropna(subset=["ret"])
            m["slot"] = (m["_ts"] // H).astype(int)
            parts.append(m.drop_duplicates("slot"))
        s = pd.concat(parts)
        s = s[s["ret"] != 0]
        for f in FEATURES:
            row = {"feature": f, "horizon": label}
            for half, g in (("h1", s[s["_ts"] < mid]), ("h2", s[s["_ts"] >= mid])):
                x = g[[f, "ret"]].dropna()
                if len(x) < MIN_SAMPLES or x[f].nunique() < 3:
                    row[f"ic_{half}"] = row[f"t_{half}"] = None
                    continue
                ic = float(x[f].rank().corr(x["ret"].rank()))
                row[f"ic_{half}"] = round(ic, 4)
                row[f"t_{half}"] = round(ic * np.sqrt((len(x) - 2) / max(1e-12, 1 - ic ** 2)), 2)
                row[f"n_{half}"] = int(len(x))
            a, b, ta, tb = row.get("ic_h1"), row.get("ic_h2"), row.get("t_h1"), row.get("t_h2")
            row["consistent"] = bool(a is not None and b is not None and np.sign(a) == np.sign(b) and abs(ta) >= 2 and abs(tb) >= 2)
            out.append(row)
    return out


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--month", required=True)
    p.add_argument("--dir", default=os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                                 "calibration_data", "flow_history"))
    a = p.parse_args()
    df = load_month(a.dir, a.month)
    res = {"month": a.month, "snapshots": int(len(df)), "symbols": int(df["symbol"].nunique()) if len(df) else 0}
    if len(df):
        res["start"] = pd.to_datetime(df["_ts"].min(), unit="s", utc=True).strftime("%Y-%m-%d")
        res["end"] = pd.to_datetime(df["_ts"].max(), unit="s", utc=True).strftime("%Y-%m-%d")
        res["results"] = evaluate(df)
    print(json.dumps(res))


if __name__ == "__main__":
    main()
