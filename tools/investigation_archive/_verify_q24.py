"""Pre-rerun verification: fixed VF statement on query_id=24."""
import os

import psycopg2

from benchmark_hybrid_optimizer import (
    PostgreSQLBenchmark, generate_queries, split_queries, read_fvecs,
    DEFAULT_VECTOR_PATH,
)

vectors = read_fvecs(DEFAULT_VECTOR_PATH)
queries = generate_queries(vectors, 20260820)
_, test = split_queries(queries, 20260821)
q = {x.query_id: x for x in test}[24]
print("q24 predicate_sql:", q.predicate_sql)

conn = psycopg2.connect(
    host="localhost", port=int(os.getenv("POSTGRES_PORT", "5433")),
    dbname=os.getenv("POSTGRES_DB"), user=os.getenv("POSTGRES_USER"),
    password=os.getenv("POSTGRES_PASSWORD"))
b = PostgreSQLBenchmark(conn, 100)
stmt, params, settings = b._statement(q, "VECTOR_FIRST_HNSW")
cur = conn.cursor()
for key, value in settings.items():
    cur.execute("SELECT set_config(%s, %s, true)", (key, str(value)))
print("\nMOGRIFIED SQL:\n", cur.mogrify(stmt, params).decode())
cur.execute(stmt, params)
rows = cur.fetchall()
print("\nROWS RETURNED:", len(rows))
print("ids:", [r[0] for r in rows])
conn.close()
