"""STEP 4: verification statistics from results/real_run_20260826T045832Z only."""
import json

import pandas as pd

RUN = "results/real_run_20260826T045832Z"
raw = pd.read_csv(f"{RUN}/heldout_per_execution.csv")
pq = pd.read_csv(f"{RUN}/heldout_per_query.csv")

# ---------- 1. Spot-check raw rows -----------------------------------------
print("=" * 30, "[1] RAW ROW SPOT-CHECK", "=" * 30)
for strat in ["SQL_FIRST", "VECTOR_FIRST_HNSW", "HNSW_HYBRID", "IVFFLAT_HYBRID"]:
    row = raw[(raw.strategy == strat) & (raw.repetition == 0)].iloc[0]
    print(json.dumps({k: row[k] for k in raw.columns}, default=str)[:700])
    print("-" * 80)

# ---------- 2. Ground-truth provenance for one query ------------------------
print("=" * 30, "[2] PROVENANCE PROOF", "=" * 30)
sel = pq[pq.is_adaptive_selection.astype(bool)]
print("adaptive selection distribution:", sel.strategy.value_counts().to_dict())
ann_rows = sel[sel.strategy != "SQL_FIRST"]
ann_pick = ann_rows.iloc[0] if len(ann_rows) else sel.iloc[0]
qid = int(ann_pick.query_id)
qrows = raw[raw.query_id == qid]
ref_row = qrows[(qrows.strategy == "SQL_FIRST") & (qrows.repetition == 0)].iloc[0]
ref_ids = set(json.loads(ref_row.result_ids))
print(f"query_id={qid} | adaptive chose {ann_pick.strategy}")
print(f"REFERENCE (SQL_FIRST repetition=0) ids: {sorted(ref_ids)}")
print("other strategies' repetition-0 result_ids and recomputed recall:")
for strat in ["VECTOR_FIRST_HNSW", "HNSW_HYBRID", "IVFFLAT_HYBRID"]:
    r = qrows[(qrows.strategy == strat) & (qrows.repetition == 0)].iloc[0]
    ids = json.loads(r.result_ids)
    manual = len(set(ids) & ref_ids) / len(ref_ids)
    print(f"  {strat}: ids={ids}")
    print(f"      |intersection|={len(set(ids) & ref_ids)}/{len(ref_ids)} "
          f"-> manual recall={manual:.1f}; recorded recall_at_10={r.recall_at_10}")
sql_recs = qrows[qrows.strategy == "SQL_FIRST"].sort_values("repetition")
print("SQL_FIRST repetitions 1-4 scored against rep0:")
for r in sql_recs.iloc[1:].itertuples():
    same = json.loads(r.result_ids) == set(ref_ids) or set(json.loads(r.result_ids)) == ref_ids
    print(f"  rep{r.repetition}: recall={r.recall_at_10} (ids identical to rep0: {same})")

# ---------- 3a. Table I ------------------------------------------------------
print("=" * 30, "[3a] TABLE I (strategy comparison)", "=" * 30)
t1_rows = []
for name in ["Adaptive", "SQL_FIRST", "VECTOR_FIRST_HNSW", "HNSW_HYBRID", "IVFFLAT_HYBRID"]:
    sub = pq[pq.is_adaptive_selection] if name == "Adaptive" else pq[pq.strategy == name]
    lat, rec = sub.median_latency_ms, sub.recall_at_10
    t1_rows.append({
        "Strategy": name, "n": len(sub),
        "Mean_ms": round(lat.mean(), 3), "Median_ms": round(lat.median(), 3),
        "P95_ms": round(lat.quantile(0.95), 3),
        "Min_recall": round(rec.min(), 3),
        "Mean_recall": round(rec.mean(), 3),
        "Frac_ge_095": round((rec >= 0.95).mean(), 3),
    })
t1 = pd.DataFrame(t1_rows)
print(t1.to_string(index=False))

# ---------- 3b. Table II -----------------------------------------------------
print("=" * 30, "[3b] TABLE II (adaptive selections by bucket)", "=" * 30)
uniq = pq.drop_duplicates("query_id")
order = ["[0.00,0.05)", "[0.05,0.10)", "[0.10,0.25)", "[0.25,0.50)", "[0.50,1.00)"]
strategies = ["SQL_FIRST", "VECTOR_FIRST_HNSW", "HNSW_HYBRID", "IVFFLAT_HYBRID"]
t2 = (uniq.groupby(["bucket", "adaptive_selected_strategy"]).size()
      .unstack(fill_value=0).reindex(order, fill_value=0)
      .reindex(columns=strategies, fill_value=0))
t2["Queries"] = t2.sum(axis=1)
print(t2.to_string())
print("Totals:", t2[strategies].sum().to_dict(),
      "| queries:", int(t2["Queries"].sum()))

# ---------- 3c. Table III ----------------------------------------------------
print("=" * 30, "[3c] TABLE III (decision overhead)", "=" * 30)
timing_cols = [c for c in pq.columns
               if "overhead" in c or "end_to_end" in c or "explain" in c]
print("columns in heldout_per_query.csv:", list(pq.columns))
print("decision-overhead columns found:", timing_cols or "NONE")

# ---------- 3d. Table IV -----------------------------------------------------
print("=" * 30, "[3d] TABLE IV (plan verification / access paths)", "=" * 30)
adaptive_ann = sel[sel.strategy.isin(["HNSW_HYBRID", "IVFFLAT_HYBRID"])]
rows4 = [("Adaptive ANN selections",
          int(adaptive_ann.plan_verified.sum()), len(adaptive_ann))]
for strat in ["HNSW_HYBRID", "VECTOR_FIRST_HNSW", "IVFFLAT_HYBRID"]:
    fixed = pq[pq.strategy == strat]
    rows4.append((f"Fixed {strat}", int(fixed.plan_verified.sum()), len(fixed)))
sql_first = pq[pq.strategy == "SQL_FIRST"]
rows4.append(("Fixed SQL_FIRST (no ANN required)",
              int(sql_first.plan_verified.sum()), len(sql_first)))
for scope, verified, n in rows4:
    print(f"  {scope:32s} {verified}/{n}")

print("\naccess_path crosstab (counts):")
print(pd.crosstab(pq.strategy, pq.access_path).to_string())

# ---------- 4. Side-by-side vs mock ------------------------------------------
print("=" * 30, "[4] MOCK vs REAL side-by-side", "=" * 30)
mock_t1 = {
    "Adaptive": (52.1, 49.3, 99.2, 1.000),
    "SQL_FIRST": (65.4, 52.1, 155.3, 1.000),
    "VECTOR_FIRST_HNSW": (57.2, 29.5, 205.1, 0.880),
    "HNSW_HYBRID": (11.2, 4.1, 45.1, 0.745),
    "IVFFLAT_HYBRID": (22.1, 18.2, 52.4, 0.812),
}
print("[Table I] strategy | metric | mock -> real (diff, pct)")
for r in t1_rows:
    m = mock_t1[r["Strategy"]]
    for label, mv, rv in [("mean_ms", m[0], r["Mean_ms"]),
                          ("median_ms", m[1], r["Median_ms"]),
                          ("p95_ms", m[2], r["P95_ms"]),
                          ("recall@10", m[3], r["Mean_recall"])]:
        pct = (rv - mv) / mv * 100
        print(f"  {r['Strategy']:18s} {label:9s} {mv:9.3f} -> {rv:9.3f} "
              f"({rv - mv:+9.3f}, {pct:+8.2f}%)")

print("\n[Table II] bucket | mock -> real")
mock_t2 = [
    ("<=0.05", {"Queries": 15, "SQL_FIRST": 15, "HNSW_HYBRID": 0}),
    ("0.05-0.10", {"Queries": 25, "SQL_FIRST": 23, "HNSW_HYBRID": 2}),
    ("0.10-0.25", {"Queries": 110, "SQL_FIRST": 75, "HNSW_HYBRID": 35}),
    ("0.25-0.50", {"Queries": 50, "SQL_FIRST": 20, "HNSW_HYBRID": 30}),
    (">0.50", {"Queries": 50, "SQL_FIRST": 15, "HNSW_HYBRID": 35}),
]
label_map = dict(zip(order, ["<=0.05", "0.05-0.10", "0.10-0.25", "0.25-0.50", ">0.50"]))
assert uniq.bucket.map(label_map).notna().all(), "unmapped bucket label"
for bucket_label, mocks in mock_t2:
    real_bucket = uniq[uniq.bucket.map(label_map) == bucket_label]
    print(f"  {bucket_label:10s} Queries: {mocks['Queries']:3d} -> "
          f"{len(real_bucket):3d} ({len(real_bucket) - mocks['Queries']:+d})")
    for strat in ["SQL_FIRST", "HNSW_HYBRID"]:
        rv = int((real_bucket.adaptive_selected_strategy == strat).sum())
        print(f"     {strat:14s} {mocks[strat]:3d} -> {rv:3d} ({rv - mocks[strat]:+d})")
totals = uniq.adaptive_selected_strategy.value_counts().to_dict()
print(f"  TOTAL      SQL_FIRST 148 -> {totals.get('SQL_FIRST', 0)} | "
      f"HNSW 102 -> {totals.get('HNSW_HYBRID', 0)} | "
      f"VF 0 -> {totals.get('VECTOR_FIRST_HNSW', 0)} | "
      f"IVF 0 -> {totals.get('IVFFLAT_HYBRID', 0)}")

print("\n[Table III] decision overhead: mock 91.14 / 65.12 / 242.52 ms -> NOT MEASURED")

print("\n[Table IV] scope | mock verified/executions -> real")
real_map = {r[0]: (r[1], r[2]) for r in rows4}
for scope, mv_v, mv_n in [("Adaptive ANN selections", 102, 102),
                          ("Fixed HNSW_HYBRID", 250, 250),
                          ("Fixed VECTOR_FIRST_HNSW", 250, 250),
                          ("Fixed IVFFLAT_HYBRID", 250, 250),
                          ("Fixed SQL_FIRST (no ANN required)", 398, 398)]:
    rv_v, rv_n = real_map.get(scope, ("n/a", "n/a"))
    print(f"  {scope:34s} {mv_v}/{mv_n} -> {rv_v}/{rv_n}")

meta = json.load(open(f"{RUN}/run_metadata.json"))
print(f"\n[5] run_metadata.json: started={meta['started_at_utc']} "
      f"finished={meta['finished_at_utc']} "
      f"(postgres={meta['postgres_version'][:30]}, pgvector={meta['pgvector_version']})")
