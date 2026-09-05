"""Evidence-only: estimate-distribution feasibility + per-observation recall lists."""
import os

import numpy as np
import pandas as pd

RUN = "results/real_run_20260826T061655Z"
calib = pd.read_csv(f"{RUN}/calibration_per_execution.csv")
pq = pd.read_csv(f"{RUN}/heldout_per_query.csv")
uniq = pq.drop_duplicates("query_id")

# regenerate deterministic workload to recover each query's predicate params
from benchmark_hybrid_optimizer import (
    generate_queries, split_queries, read_fvecs, DEFAULT_VECTOR_PATH,
)
vectors = read_fvecs(DEFAULT_VECTOR_PATH)
queries = generate_queries(vectors, 20260820)
_, test_queries = split_queries(queries, 20260821)
params_by_id = {
    q.query_id: {"target": q.target_selectivity,
                 "category": q.category,
                 "in_stock": q.in_stock}
    for q in test_queries
}
uniq["in_stock"] = uniq.query_id.map(lambda i: params_by_id[i]["in_stock"])
uniq["target"] = uniq.query_id.map(lambda i: params_by_id[i]["target"])
uniq["template"] = pd.cut(
    uniq.target, bins=[0, 0.25, 0.60, 1.01], include_lowest=True,
    labels=["AND", "OR-mixed", "all-OR"])

# ---- 1. estimate distribution + feasibility -------------------------------
print("=" * 25, "[1] ESTIMATE DISTRIBUTION & FEASIBILITY", "=" * 25)
print("\nestimated_selectivity by template x demanded in_stock:")
for tpl in ["AND", "OR-mixed", "all-OR"]:
    for flag in [True, False]:
        sub = uniq[(uniq.template == tpl) & (uniq.in_stock == flag)]
        if sub.empty:
            print(f"  {tpl:8s} in_stock={flag}: n=0")
            continue
        e = sub.estimated_selectivity
        print(f"  {tpl:8s} in_stock={flag}: n={len(sub):3d} "
              f"min={e.min():.4f} median={e.median():.4f} max={e.max():.4f}")

print("\nper-template: does target_selectivity move the estimate at all?")
for tpl in ["AND", "OR-mixed", "all-OR"]:
    sub = uniq[uniq.template == tpl]
    low, high = sub[sub.target <= sub.target.median()], sub[sub.target > sub.target.median()]
    print(f"  {tpl:8s} lower-half targets [{sub.target.min():.2f}-{low.target.max():.2f}] "
          f"est range [{low.estimated_selectivity.min():.3f},{low.estimated_selectivity.max():.3f}] | "
          f"upper-half [{high.target.min():.2f}-{sub.target.max():.2f}] "
          f"est range [{high.estimated_selectivity.min():.3f},{high.estimated_selectivity.max():.3f}]")

print("\ncorrelation(target, estimate) per template:")
for tpl in ["AND", "OR-mixed", "all-OR"]:
    sub = uniq[uniq.template == tpl]
    print(f"  {tpl:8s} pearson r = "
          f"{np.corrcoef(sub.target, sub.estimated_selectivity)[0, 1]:+.3f}")

print("\nsame relationship on the CALIBRATION half (other 250 queries):")
calib_u = calib.drop_duplicates("query_id")
calib_u["in_stock"] = None
import psycopg2  # noqa: E402
conn = psycopg2.connect(
    host="localhost", port=int(os.getenv("POSTGRES_PORT", "5433")),
    dbname=os.getenv("POSTGRES_DB"), user=os.getenv("POSTGRES_USER"),
    password=os.getenv("POSTGRES_PASSWORD"))
cur = conn.cursor()
cur.execute("SELECT id FROM sift_hybrid LIMIT 0")  # sanity touch
conn.rollback()
_, calib_queries = None, None
all_cal_ids = set(calib_u.query_id.astype(int))
# recover calibration queries from the full 500 generated set
_, _ = split_queries(queries, 20260821)
from benchmark_hybrid_optimizer import CALIBRATION_COUNT  # noqa: E402
rng = np.random.default_rng(20260821)
order = rng.permutation(500)
cal_ids = set(int(v) for v in order[:CALIBRATION_COUNT])
cal_q = {q.query_id: q for q in queries if q.query_id in cal_ids}
rows = []
for qid, q in cal_q.items():
    rows.append({"query_id": qid, "template": pd.cut(
        [q.target_selectivity], bins=[0, 0.25, 0.60, 1.01], include_lowest=True,
        labels=["AND", "OR-mixed", "all-OR"])[0],
        "estimated_selectivity": float(calib_u.set_index("query_id")
                                       .estimated_selectivity.get(qid, np.nan)),
        "in_stock": q.in_stock})
cdf = pd.DataFrame(rows).dropna()
print(cdf.groupby(["template", "in_stock"]).estimated_selectivity
         .agg(["count", "min", "median", "max"]).round(4).to_string())
# ---- 2. per-observation recall lists in the two populated buckets ---------
print("=" * 25, "[2] PER-OBSERVATION RECALL LISTS", "=" * 25)
for bucket in ["[0.00,0.05)", "[0.10,0.25)"]:
    for strat in ["HNSW_HYBRID", "IVFFLAT_HYBRID"]:
        sub = calib[(calib.bucket == bucket) & (calib.strategy == strat)]
        rec = np.sort(sub.recall_at_10.values)
        n = len(rec)
        print(f"\n{bucket} {strat} (n={n} calibration observations)")
        print("  sorted recalls:", np.array2string(rec, precision=2, max_line_width=100))
        print(f"  min={rec.min():.2f} p25={np.percentile(rec,25):.2f} "
              f"median={np.median(rec):.2f} mean={rec.mean():.3f} "
              f"p75={np.percentile(rec,75):.2f} max={rec.max():.2f}")
        print(f"  count==1.0: {int((rec == 1.0).sum())}/{n} | "
              f"count>=0.95: {int((rec >= 0.95).sum())}/{n} | "
              f"count<0.5: {int((rec < 0.5).sum())}/{n}")
