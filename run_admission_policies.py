"""Compare admission policies on the 200K SIFT1M subset."""
import json
from collections import defaultdict
from pathlib import Path
import numpy as np
import pandas as pd

POLICIES = ["min_recall", "mean_recall", "lcb_recall", "quantile_recall"]
SWEEP_DIR = Path("results/exp_200k/param_sweep")
CONFIG = "config_ef200_probes10"
TARGET = 0.95

cal = pd.read_csv(SWEEP_DIR / "calibration_observations.csv")
print(f"Calibration: {len(cal)} observations")
cal_map = {}
for (strat, bucket), group in cal.groupby(["strategy", "bucket"]):
    cal_map[(strat, bucket)] = {
        "recalls": group["recall_at_10"].values.tolist(),
        "median_latency_ms": float(group["latency_ms"].median()),
        "n": len(group),
    }
print(f"Calibration map: {len(cal_map)} keys")
pq = pd.read_csv(SWEEP_DIR / CONFIG / "per_query.csv")
print(f"Held-out: {len(pq)} per-query records")

for policy in POLICIES:
    selections = []
    for qid, group in pq.groupby("query_id"):
        row = group.iloc[0]
        bucket = row["bucket"]
        feasible = ["SQL_FIRST"]
        for strat in ["VECTOR_FIRST_HNSW", "HNSW_HYBRID", "IVFFLAT_HYBRID"]:
            stats = cal_map.get((strat, bucket))
            if stats is None or stats["n"] == 0:
                continue
            recalls = np.asarray(stats["recalls"])
            n = len(recalls)
            if policy == "min_recall":
                stat = float(recalls.min())
                ok = stat >= TARGET
            elif policy == "mean_recall":
                stat = float(recalls.mean())
                ok = stat >= TARGET
            elif policy == "lcb_recall":
                rng = np.random.default_rng(42)
                boot_means = np.array([rng.choice(recalls, size=n, replace=True).mean() for _ in range(1000)])
                stat = float(np.quantile(boot_means, 0.05))
                ok = stat >= TARGET
            elif policy == "quantile_recall":
                stat = float(np.quantile(recalls, 0.05))
                ok = stat >= TARGET
            if ok:
                feasible.append(strat)
        best = "SQL_FIRST"
        best_lat = cal_map.get(("SQL_FIRST", bucket), {}).get("median_latency_ms", float("inf"))
        for s in feasible:
            lat = cal_map.get((s, bucket), {}).get("median_latency_ms", float("inf"))
            if lat < best_lat:
                best_lat = lat
                best = s
        selections.append({
            "query_id": qid, "bucket": bucket,
            "feasible": feasible, "selected": best,
        })
    sel_df = pd.DataFrame(selections)
    counts = sel_df.groupby(["bucket", "selected"]).size().reset_index(name="count")
    print(f"\n=== Policy: {policy} ===")
    print(counts.to_string(index=False))
    total_ann = (sel_df["selected"] != "SQL_FIRST").sum()
    print(f"ANN selected: {total_ann}/{len(sel_df)} ({100*total_ann/len(sel_df):.1f}%)")
    actual_lat = []
    actual_rec = []
    for _, s in sel_df.iterrows():
        sel = s["selected"]
        qrows = pq[(pq["query_id"] == s["query_id"]) & (pq["strategy"] == sel)]
        if len(qrows) > 0:
            actual_lat.append(qrows["median_latency_ms"].iloc[0])
            actual_rec.append(qrows["recall_at_10"].iloc[0])
    print(f"Adaptive: mean_lat={np.mean(actual_lat):.2f}ms, "
          f"mean_recall={np.mean(actual_rec):.3f}, "
          f"min_recall={np.min(actual_rec):.3f}, "
          f"frac>=0.95={np.mean([r >= 0.95 for r in actual_rec]):.3f}")
