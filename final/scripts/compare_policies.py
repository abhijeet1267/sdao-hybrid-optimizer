"""Compare admission policies on a completed experiment.

Loads calibration_map.json + per_query.csv from a result dir,
re-runs the admission decision with each policy, and reports
selection distribution + simulated adaptive metrics.

Usage:
    python compare_policies.py --results-dir <dir> [--policies min_recall,mean_recall,quantile_recall,lcb_recall,failure_rate]
"""
import argparse
import json
import sys
from ast import literal_eval
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "final" / "scripts"))

from run_calibration import admit  # noqa: E402

POLICIES = ["min_recall", "mean_recall", "quantile_recall", "lcb_recall", "failure_rate"]


def load_calibration(path: Path):
    raw = json.loads(path.read_text())
    cal = {}
    for k_str, v in raw.items():
        key = literal_eval(k_str)
        v["recalls"] = v.get("recalls", [])
        cal[key] = v
    return cal


def load_calibration_with_recalls(path: Path, raw_csv: Path):
    """Load calibration_map.json. If recalls are missing, recover from raw_per_execution.csv."""
    raw_map = json.loads(path.read_text())
    cal = {}
    has_recalls = False
    for k_str, v in raw_map.items():
        key = literal_eval(k_str)
        v["recalls"] = v.get("recalls", [])
        cal[key] = v
        if v.get("recalls"):
            has_recalls = True
    if has_recalls:
        return cal
    # recover from raw CSV
    df = pd.read_csv(raw_csv)
    df = df[df["phase"] == "calibration"]
    cal = defaultdict(lambda: {"recalls": [], "latencies": [], "n": 0})
    for _, row in df.iterrows():
        key = (row["strategy"], row["bucket"])
        cal[key]["recalls"].append(float(row["recall_at_10"]))
        cal[key]["latencies"].append(float(row["latency_ms"]))
        cal[key]["n"] = len(cal[key]["recalls"])
    # compute stats
    out = {}
    for key, v in cal.items():
        import numpy as np
        recs = np.array(v["recalls"])
        lats = np.array(v["latencies"])
        out[key] = {
            "n": v["n"],
            "median_latency_ms": float(np.median(lats)),
            "mean_latency_ms": float(np.mean(lats)),
            "min_recall": float(recs.min()),
            "mean_recall": float(recs.mean()),
            "p05_recall": float(np.quantile(recs, 0.05)),
            "frac_above_target": float((recs >= 0.95).mean()),
            "recalls": v["recalls"],
        }
    return out


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--results-dir", required=True)
    parser.add_argument("--policies", default=",".join(POLICIES))
    parser.add_argument("--target-recall", type=float, default=0.95)
    args = parser.parse_args()

    rd = Path(args.results_dir)
    cal = load_calibration_with_recalls(
        rd / "calibration_map.json", rd / "raw_per_execution.csv"
    )
    pq = pd.read_csv(rd / "per_query.csv")
    # raw decisions per strategy/query
    raw = pd.read_csv(rd / "raw_per_execution.csv")
    policies = args.policies.split(",")
    target = args.target_recall

    print(f"=== Policy comparison: {rd} ===")
    print(f"Calibration entries: {len(cal)}, held-out per-query rows: {len(pq)}")
    rows = []
    for policy in policies:
        sel_rows = []
        for qid, g in pq.groupby("query_id"):
            row = g.iloc[0]
            bucket = row["bucket"]
            try:
                selected, feasible, reason, predicted_lat, per_strat = admit(
                    cal, bucket, policy, target, conf=0.95, q=0.05,
                )
            except Exception as e:
                print(f"  policy={policy} bucket={bucket} qid={qid}: error: {e}")
                continue
            sel_rows.append({
                "query_id": qid, "bucket": bucket,
                "estimated_selectivity": row["estimated_selectivity"],
                "selected": selected, "feasible": feasible,
            })
        sel_df = pd.DataFrame(sel_rows)
        # Per-strategy actual latency/recall for selected queries
        actual_lat, actual_rec = [], []
        unsafe_ann_count = 0
        ann_selections = 0
        for _, sr in sel_df.iterrows():
            sel = sr["selected"]
            qrows = pq[(pq["query_id"] == sr["query_id"]) & (pq["strategy"] == sel)]
            if len(qrows) > 0:
                actual_lat.append(qrows["median_latency_ms"].iloc[0])
                actual_rec.append(qrows["recall_at_10"].iloc[0])
                if sel != "SQL_FIRST":
                    ann_selections += 1
                    if qrows["recall_at_10"].iloc[0] < target:
                        unsafe_ann_count += 1
        sel_counts = sel_df.groupby(["bucket", "selected"]).size().reset_index(name="count")
        rows.append({
            "policy": policy,
            "queries": len(sel_df),
            "ann_selections": ann_selections,
            "ann_pct": 100 * ann_selections / max(len(sel_df), 1),
            "mean_latency_ms": float(np.mean(actual_lat)) if actual_lat else None,
            "mean_recall_at_10": float(np.mean(actual_rec)) if actual_rec else None,
            "min_recall_at_10": float(np.min(actual_rec)) if actual_rec else None,
            "frac_unsafe_ann": (unsafe_ann_count / ann_selections) if ann_selections else None,
            "frac_recall_ge_target": float(np.mean([r >= target for r in actual_rec])) if actual_rec else None,
            "selection_by_bucket": sel_counts.to_dict(orient="records"),
        })
    out_df = pd.DataFrame([{k: v for k, v in r.items() if k != "selection_by_bucket"} for r in rows])
    print("\n=== Policy comparison summary ===")
    print(out_df.to_string(index=False))
    out_df.to_csv(rd / "policy_comparison.csv", index=False)
    with open(rd / "policy_comparison.json", "w") as f:
        json.dump(rows, f, indent=2)
    print(f"\nWrote {rd / 'policy_comparison.csv'} and {rd / 'policy_comparison.json'}")


if __name__ == "__main__":
    main()