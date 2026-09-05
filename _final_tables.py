"""Final tables from results/real_run_20260826T065155Z + cross-run comparison."""
import json

import numpy as np
import pandas as pd

NEW = "results/real_run_20260826T065155Z"
OLD = "results/real_run_20260826T061655Z"
STRATEGIES = ["SQL_FIRST", "VECTOR_FIRST_HNSW", "HNSW_HYBRID", "IVFFLAT_HYBRID"]

pq = pd.read_csv(f"{NEW}/heldout_per_query.csv")
raw = pd.read_csv(f"{NEW}/heldout_per_execution.csv")
old_pq = pd.read_csv(f"{OLD}/heldout_per_query.csv")
meta = json.load(open(f"{NEW}/run_metadata.json"))

print("=" * 20, "RUN COMPLETION", "=" * 20)
print(json.dumps({k: meta[k] for k in [
    "started_at_utc", "finished_at_utc", "seed", "split_seed",
    "calibration_executions", "heldout_executions", "per_query_records",
    "plans_verified", "sql_first_nondeterministic_queries",
    "decision_overhead_ms"]}, indent=2))

# ---- Table I ----------------------------------------------------------------
print("\n==== TABLE I (strategy comparison) ====")
rows = []
for name in ["Adaptive"] + STRATEGIES:
    sub = pq[pq.is_adaptive_selection.astype(bool)] if name == "Adaptive" \
        else pq[pq.strategy == name]
    lat, rec = sub.median_latency_ms, sub.recall_at_10
    rows.append({"Strategy": name,
                 "Mean_ms": round(lat.mean(), 1), "Median_ms": round(lat.median(), 1),
                 "P95_ms": round(lat.quantile(0.95), 1),
                 "Recall@10": round(rec.mean(), 3),
                 "Min_recall": round(rec.min(), 3),
                 "Frac_ge_.95": round((rec >= 0.95).mean(), 3)})
t1 = pd.DataFrame(rows)
print(t1.to_string(index=False))
t1.to_csv(f"{NEW}/table1_recomputed.csv", index=False)

# ---- Table II ---------------------------------------------------------------
print("\n==== TABLE II (adaptive selections by bucket) ====")
uniq = pq.drop_duplicates("query_id")
order = ["[0.00,0.05)", "[0.05,0.10)", "[0.10,0.25)", "[0.25,0.50)", "[0.50,1.00)"]
t2 = (uniq.groupby(["bucket", "adaptive_selected_strategy"]).size()
      .unstack(fill_value=0).reindex(order, fill_value=0)
      .reindex(columns=STRATEGIES, fill_value=0))
t2["Queries"] = t2.sum(axis=1)
t2.loc["Total"] = t2.sum()
print(t2.to_string())
t2.to_csv(f"{NEW}/table2_recomputed.csv")

# ---- Table III --------------------------------------------------------------
print("\n==== TABLE III (decision overhead, newly instrumented) ====")
oh = pq.decision_overhead_ms
comp = pq[["explain_ms", "decision_ms", "selected_exec_ms"]].mean().round(3)
t3 = pd.DataFrame({
    "Mean_ms": [round(oh.mean(), 2)], "Median_ms": [round(oh.median(), 2)],
    "P95_ms": [round(oh.quantile(0.95), 2)],
    "mean_explain_ms": [comp.explain_ms], "mean_decision_ms": [comp.decision_ms],
    "mean_selected_exec_ms": [comp.selected_exec_ms]})
print(t3.to_string(index=False))
t3.to_csv(f"{NEW}/table3_recomputed.csv", index=False)

# ---- Table IV ---------------------------------------------------------------
print("\n==== TABLE IV (plan verification / access paths) ====")
sel = pq[pq.is_adaptive_selection.astype(bool)]
ann_sel = sel[sel.strategy.isin(["HNSW_HYBRID", "IVFFLAT_HYBRID"])]
rows4 = []
if len(ann_sel):
    rows4.append(("Adaptive ANN selections", int(ann_sel.plan_verified.sum()), len(ann_sel)))
else:
    rows4.append(("Adaptive ANN selections", 0, 0))
for strat in STRATEGIES:
    fixed = pq[pq.strategy == strat]
    rows4.append((f"Fixed {strat}", int(fixed.plan_verified.sum()), len(fixed)))
all_ann = pq[pq.strategy.isin(STRATEGIES[1:])]
rows4.append(("All ANN executions", int(all_ann.plan_verified.sum()), len(all_ann)))
rows4.append(("SQL_FIRST executions (no ANN required)",
              int(sql_first := pq[pq.strategy == "SQL_FIRST"].plan_verified.sum()),
              len(pq[pq.strategy == "SQL_FIRST"])))
t4 = pd.DataFrame(rows4, columns=["Scope", "named_path_verified", "records"])
print(t4.to_string(index=False))
print(pd.crosstab(pq.strategy, pq.access_path).to_string())
t4.to_csv(f"{NEW}/table4_recomputed.csv", index=False)

# ---- cross-run comparison (non-overhead numbers) ----------------------------
print("\n==== CROSS-RUN COMPARISON: T065155 (final) vs T061655 (prior clean) ====")
opq = old_pq
diffs = []
for name in ["Adaptive"] + STRATEGIES:
    for frame, tag in [(pq, "new"), (opq, "old")]:
        pass
    new_sub = pq[pq.is_adaptive_selection.astype(bool)] if name == "Adaptive" \
        else pq[pq.strategy == name]
    old_sub = opq[opq.is_adaptive_selection.astype(bool)] if name == "Adaptive" \
        else opq[opq.strategy == name]
    for metric, fn in [("mean", lambda s: s.mean()), ("median", lambda s: s.median()),
                       ("p95", lambda s: s.quantile(0.95)),
                       ("recall", lambda s: s.mean())]:
        col = "median_latency_ms" if metric != "recall" else "recall_at_10"
        nv, ov = float(fn(new_sub[col])), float(fn(old_sub[col]))
        diffs.append({"strategy": name, "metric": metric,
                      "new": round(nv, 3), "old": round(ov, 3),
                      "abs_diff": round(abs(nv - ov), 3),
                      "pct_diff": round((nv - ov) / ov * 100, 2) if ov else None})
dd = pd.DataFrame(diffs)
print(dd.to_string(index=False))
print(f"\nmax abs diff across all latency/recall cells: {dd.abs_diff.max()}")

# adaptive selections identical?
n_ad = uniq.adaptive_selected_strategy.value_counts().to_dict()
o_uniq = opq.drop_duplicates("query_id")
o_ad = o_uniq.adaptive_selected_strategy.value_counts().to_dict()
print("adaptive distribution: new =", n_ad, "| old =", o_ad)
