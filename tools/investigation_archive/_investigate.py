"""Evidence-only investigation: VECTOR_FIRST recall, bucket histogram,
calibration gate numbers. Reads only the real run's artifacts."""
import json

import numpy as np
import pandas as pd

RUN = "results/real_run_20260826T045832Z"
raw = pd.read_csv(f"{RUN}/heldout_per_execution.csv")
calib = pd.read_csv(f"{RUN}/calibration_per_execution.csv")
pq = pd.read_csv(f"{RUN}/heldout_per_query.csv")
uniq = pq.drop_duplicates("query_id")

# ---- 1. VECTOR_FIRST_HNSW across the selectivity range ---------------------
print("=" * 25, "[1] VECTOR_FIRST_HNSW rows across selectivity", "=" * 25)
vf0 = raw[(raw.strategy == "VECTOR_FIRST_HNSW") & (raw.repetition == 0)].copy()
vf0["n_results"] = vf0.result_ids.map(lambda s: len(json.loads(s)))
vf0["budget_constant"] = 100  # --vector-first-budget default; see main()
span = vf0.sort_values("estimated_selectivity")
idx = np.linspace(0, len(span) - 1, 14).astype(int)
print(span.iloc[idx][["query_id", "estimated_selectivity", "bucket",
                      "n_results", "recall_at_10"]].to_string(index=False))
print("\ndistribution of post-filter result-set sizes (all 250 VF executions, rep 0):")
print(vf0.n_results.describe().to_string())
print("empty results:", int((vf0.n_results == 0).sum()),
      "| <=2 results:", int((vf0.n_results <= 2).sum()))
print("\nrecall / emptiness by selectivity band:")
bands = [(0.0, 0.05), (0.05, 0.10), (0.10, 0.25), (0.25, 0.50), (0.50, 1.01)]
for low, high in bands:
    sub = vf0[(vf0.estimated_selectivity >= low) & (vf0.estimated_selectivity < high)]
    if sub.empty:
        print(f"  [{low:.2f},{high:.2f}): no queries")
        continue
    print(f"  [{low:.2f},{high:.2f}): n={len(sub)} "
          f"empty={int((sub.n_results == 0).sum())} "
          f"mean_len={sub.n_results.mean():.2f} "
          f"mean_recall={sub.recall_at_10.mean():.3f} "
          f"max_recall={sub.recall_at_10.max():.2f}")

# ---- 2. bucket_for() boundaries + raw selectivity histogram ----------------
print("\n" + "=" * 25, "[2] BUCKET BOUNDARIES + HISTOGRAM", "=" * 25)
print("(a) bucket_for() source:")
import inspect
from benchmark_hybrid_optimizer import bucket_for, BUCKETS
print(inspect.getsource(bucket_for))
print("BUCKETS constant:", BUCKETS)
print("(b) 20-bin histogram of estimated_selectivity, 250 held-out queries:")
counts, edges = np.histogram(uniq.estimated_selectivity, bins=20, range=(0.0, 1.0))
for i in range(20):
    bar = "#" * int(counts[i])
    print(f"  {edges[i]:.2f}-{edges[i+1]:.2f}: {counts[i]:3d} {bar}")
print("exact five-bucket counts:",
      uniq.bucket.value_counts().reindex(
          ["[0.00,0.05)", "[0.05,0.10)", "[0.10,0.25)", "[0.25,0.50)",
           "[0.50,1.00)"]).to_dict())
s = np.sort(uniq.estimated_selectivity.values)
print(f"min={s[0]:.4f} max={s[-1]:.4f}")
print("values nearest the 0.05 boundary:",
      s[np.abs(s - 0.05).argsort()[:6]].round(4).tolist())
print("values nearest the 0.25 boundary:",
      s[np.abs(s - 0.25).argsort()[:6]].round(4).tolist())
print("deciles:", np.percentile(s, np.arange(0, 101, 10)).round(4).tolist())

# ---- 3. Calibration gate inputs --------------------------------------------
print("\n" + "=" * 25, "[3] CALIBRATION GATE INPUTS", "=" * 25)
g = calib.groupby(["bucket", "strategy"]).agg(
    n_obs=("recall_at_10", "size"),
    min_recall=("recall_at_10", "min"),
    mean_recall=("recall_at_10", "mean"),
).round(4)
print(g.to_string())
