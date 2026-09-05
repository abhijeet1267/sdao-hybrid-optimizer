"""Clause-by-clause isolation of the VF zero-row anomaly for query_id=24."""
import os

import psycopg2

from benchmark_hybrid_optimizer import (
    PostgreSQLBenchmark, generate_queries, split_queries, read_fvecs,
    DEFAULT_VECTOR_PATH,
)

vectors = read_fvecs(DEFAULT_VECTOR_PATH)
queries = generate_queries(vectors, 20260820)
_, test_queries = split_queries(queries, 20260821)
q = {query.query_id: query for query in test_queries}[24]

conn = psycopg2.connect(
    host=os.getenv("POSTGRES_HOST", "localhost"),
    port=int(os.getenv("POSTGRES_PORT", "5433")),
    dbname=os.getenv("POSTGRES_DB", "sdao"),
    user=os.getenv("POSTGRES_USER", "sdao"),
    password=os.getenv("POSTGRES_PASSWORD", ""),
)
benchmark = PostgreSQLBenchmark(conn, 100)
statement, params, settings = benchmark._statement(q, "VECTOR_FIRST_HNSW")
print("predicate:", q.predicate_sql)
print("params types:", [(type(p).__name__, str(p)[:40]) for p in params])
print("\nexecuted statement:\n", statement)

cur = conn.cursor()
for key, value in settings.items():
    cur.execute("SELECT set_config(%s, %s, true)", (key, str(value)))

def run(label, sql, prms):
    cur.execute(sql, prms)
    first = cur.fetchone()
    n = first[0] if first is not None and len(first) == 1 else (
        1 + cur.rowcount if first is None else 1)
    if first is not None and len(first) != 1:
        # multi-column result: re-execute to count properly is avoided;
        # report first row instead
        n = f"first_row={first}"
    print(f"{label}: {n}")

run("A. verbatim executed statement", statement, params)

cte = ("WITH candidates AS MATERIALIZED "
       "(SELECT id, embedding <-> %s::vector AS distance "
       "FROM sift_hybrid ORDER BY embedding <-> %s::vector LIMIT 100) ")
run("B. candidate CTE alone", cte + "SELECT count(*) FROM candidates",
    (params[0], params[1]))
run("C. CTE + join, no WHERE", cte +
    "SELECT count(*) FROM candidates JOIN sift_hybrid item ON item.id = candidates.id",
    (params[0], params[1]))
for label, cond in [("category", "item.category = %s"),
                    ("price", "item.price < %s"),
                    ("in_stock", "item.in_stock = %s")]:
    run(f"D. CTE + join + WHERE {label} only", cte +
        f"SELECT count(*) FROM candidates JOIN sift_hybrid item "
        f"ON item.id = candidates.id WHERE {cond}",
        (params[0], params[1], params[2] if label == "category"
         else params[3] if label == "price" else params[4]))
run("E. full WHERE, no ORDER/LIMIT", cte +
    "SELECT count(*) FROM candidates JOIN sift_hybrid item ON item.id = candidates.id "
    "WHERE item.category = %s AND item.price < %s AND item.in_stock = %s",
    params[:5])
print("\n--- decisive probes ---")
mogrified = cur.mogrify(statement, params).decode()
print("G. mogrified SQL actually sent:\n", mogrified)
for attempt in range(3):
    cur.execute(statement, params)
    print(f"A{attempt}. verbatim re-execution rows={len(cur.fetchall())}")
cur.execute("EXPLAIN (ANALYZE, FORMAT JSON) " + statement, params)
plan = cur.fetchone()[0]

def walk(node, depth):
    print("  " * depth +
          f"{node.get('Node Type')} actual_rows={node.get('Actual Rows')} "
          f"loops={node.get('Actual Loops')} index={node.get('Index Name')}")
    for child in node.get("Plans", []):
        walk(child, depth + 1)

walk(plan[0]["Plan"], 0)

conn.rollback()
conn.close()
