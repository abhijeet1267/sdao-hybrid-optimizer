"""Root-cause analysis of the 336 failed plan_verified checks (evidence only)."""
import json
import os

import pandas as pd
import psycopg2

RUN = "results/real_run_20260826T043606Z"

# ---- 1. Failure breakdown by strategy -------------------------------------
pq = pd.read_csv(f"{RUN}/heldout_per_query.csv")
fail = pq[~pq.plan_verified.astype(bool)]
print(f"total per-query records : {len(pq)}")
print(f"failed plan_verified    : {len(fail)}")
print("\n[1] failures by strategy:")
print(fail.groupby("strategy").size().to_string())
print("\npassed-by-strategy for contrast:")
print(pq[pq.plan_verified.astype(bool)].groupby("strategy").size().to_string())

print("\n[1b] sample failing rows (query_id -> plan_index_names):")
for strat, group in fail.groupby("strategy"):
    samples = "; ".join(
        f"q{row.query_id}:{row.plan_index_names}" for row in group.head(3).itertuples()
    )
    print(f"  {strat} ({len(group)}): {samples}")

# ---- 2. Live index inventory ----------------------------------------------
conn = psycopg2.connect(
    host=os.getenv("POSTGRES_HOST", "localhost"),
    port=int(os.getenv("POSTGRES_PORT", "5433")),
    dbname=os.getenv("POSTGRES_DB", "sdao"),
    user=os.getenv("POSTGRES_USER", "sdao"),
    password=os.getenv("POSTGRES_PASSWORD", ""),
)
cur = conn.cursor()
cur.execute("SELECT indexname, indexdef FROM pg_indexes WHERE tablename = 'sift_hybrid'")
rows = cur.fetchall()
print(f"\n[2] live indexes on sift_hybrid ({len(rows)}):")
for name, definition in rows:
    print(f"  {name}\n      {definition}")
has_ivf = any("ivfflat" in (n or "").lower() or "ivfflat" in d.lower() for n, d in rows)
print(f"ivfflat index exists: {has_ivf}")

# ---- 4. Live EXPLAIN dumps for non-IVFFLAT failures -----------------------
other = fail[(fail.strategy != "IVFFLAT_HYBRID")]
if len(other):
    print(f"\n[4] live EXPLAIN evidence for {len(other)} non-IVFFLAT failures:")

    import numpy as np
    from benchmark_hybrid_optimizer import (
        PostgreSQLBenchmark, generate_queries, split_queries, read_fvecs,
        DEFAULT_VECTOR_PATH,
    )

    vectors = read_fvecs(DEFAULT_VECTOR_PATH)
    queries = generate_queries(vectors, 20260820)
    _, test_queries = split_queries(queries, 20260821)
    by_id = {q.query_id: q for q in test_queries}
    benchmark = PostgreSQLBenchmark(conn, 100)

    for strat, group in other.groupby("strategy"):
        print(f"\n  == {strat}: {len(group)} failing records ==")
        for row in group.head(3).itertuples():
            q = by_id[row.query_id]
            statement, params, settings = benchmark._statement(q, strat)
            with conn.cursor() as cursor:
                for key, value in settings.items():
                    cursor.execute("SELECT set_config(%s, %s, true)", (key, str(value)))
                cursor.execute("EXPLAIN (FORMAT JSON) " + statement, params)
                plan = cursor.fetchone()[0]
                if isinstance(plan, str):
                    plan = json.loads(plan)
            print(f"   query_id={row.query_id} recorded plan_index_names={row.plan_index_names}")
            print("   live EXPLAIN top nodes:")
            stack = [(plan[0]["Plan"], 0)]
            while stack:
                node, depth = stack.pop()
                print("     " * (depth + 1)
                      + f"{node.get('Node Type')} index={node.get('Index Name')}")
                for child in reversed(node.get("Plans", [])):
                    stack.append((child, depth + 1))

conn.close()
print("\nANALYSIS-DONE")
