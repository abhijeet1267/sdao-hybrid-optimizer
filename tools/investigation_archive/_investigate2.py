"""Decisive probes: actual selectivity vs candidate-survivors for VF queries,
and predicate-template vs estimate-band relationship. Read-only."""
import json
import os

import numpy as np
import pandas as pd
import psycopg2

from benchmark_hybrid_optimizer import (
    PostgreSQLBenchmark, generate_queries, split_queries, read_fvecs,
    DEFAULT_VECTOR_PATH,
)

RUN = "results/real_run_20260826T045832Z"
pq = pd.read_csv(f"{RUN}/heldout_per_query.csv")
raw0 = pd.read_csv(f"{RUN}/heldout_per_execution.csv")
raw0 = raw0[raw0.repetition == 0]
uniq = pq.drop_duplicates("query_id").merge(
    raw0[["query_id", "target_selectivity"]], on="query_id", how="left")

print("[2b] predicate template (target_selectivity) vs estimate band:")
uniq["template"] = pd.cut(
    uniq.target_selectivity, bins=[0, 0.25, 0.60, 1.01],
    labels=["AND(cat,price,stock)", "OR-mixed", "all-OR"])
print(pd.crosstab(uniq.template, pd.cut(
    uniq.estimated_selectivity, bins=[0, 0.05, 0.10, 0.25, 0.50, 1.01],
    include_lowest=True)).to_string())

vectors = read_fvecs(DEFAULT_VECTOR_PATH)
queries = generate_queries(vectors, 20260820)
_, test_queries = split_queries(queries, 20260821)
by_id = {q.query_id: q for q in test_queries}
conn = psycopg2.connect(
    host=os.getenv("POSTGRES_HOST", "localhost"),
    port=int(os.getenv("POSTGRES_PORT", "5433")),
    dbname=os.getenv("POSTGRES_DB", "sdao"),
    user=os.getenv("POSTGRES_USER", "sdao"),
    password=os.getenv("POSTGRES_PASSWORD", ""),
)
benchmark = PostgreSQLBenchmark(conn, 100)

vf = pq[(pq.strategy == "VECTOR_FIRST_HNSW") & (pq.repetitions == 5)]
picks = vf.sort_values("estimated_selectivity").iloc[
    [0, len(vf) // 4, len(vf) // 2, 3 * len(vf) // 4, len(vf) - 2]]
print("\n[1-probe] per-query actual selectivity vs VF candidate survivors:")
print(f"{'qid':>4} {'est_sel':>8} {'actual_sel':>10} {'cand_match':>10} "
      f"{'vf_len':>6} {'vf_recall':>9}")
for row in picks.itertuples():
    q = by_id[int(row.query_id)]
    cur = conn.cursor()
    cur.execute(f"SELECT COUNT(*) FROM sift_hybrid WHERE {q.predicate_sql}",
                q.predicate_params)
    actual = cur.fetchone()[0]
    vec = benchmark._vector_literal(q.vector)
    cur.execute(
        "WITH candidates AS MATERIALIZED "
        "(SELECT id FROM sift_hybrid ORDER BY embedding <-> %s::vector LIMIT 100) "
        f"SELECT COUNT(*) FROM candidates JOIN sift_hybrid item ON item.id = candidates.id "
        f"WHERE {q.predicate_sql}",
        (vec,) + q.predicate_params)
    cand_matches = cur.fetchone()[0]
    conn.rollback()
    cur.close()
    vf_row = raw0[(raw0.query_id == row.query_id)
                  & (raw0.strategy == "VECTOR_FIRST_HNSW")].iloc[0]
    vf_len = len(json.loads(vf_row.result_ids))
    print(f"{row.query_id:>4} {row.estimated_selectivity:8.4f} "
          f"{actual / 1_000_000:10.4f} {cand_matches:10d} "
          f"{vf_len:>6} {row.recall_at_10:9.2f}")
conn.close()
