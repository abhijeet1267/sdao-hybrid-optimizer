"""Direct verification of the live PostgreSQL/pgvector environment (STEP 2)."""
import os

import psycopg2

conn = psycopg2.connect(
    host=os.getenv("POSTGRES_HOST", "localhost"),
    port=int(os.getenv("POSTGRES_PORT", "5433")),
    dbname=os.getenv("POSTGRES_DB", "sdao"),
    user=os.getenv("POSTGRES_USER", "sdao"),
    password=os.getenv("POSTGRES_PASSWORD", ""),
)
cur = conn.cursor()

cur.execute("SELECT version()")
print("postgres:", cur.fetchone()[0])

cur.execute("SELECT extname, extversion FROM pg_extension ORDER BY extname")
print("extensions:", cur.fetchall())

cur.execute("SELECT COUNT(*) FROM sift_hybrid")
print("sift_hybrid row count:", cur.fetchone()[0])

cur.execute("SELECT vector_dims(embedding) FROM sift_hybrid LIMIT 1")
print("embedding dimensions:", cur.fetchone()[0])

cur.execute("SELECT COUNT(*) FROM sift_hybrid WHERE embedding IS NULL")
print("null embeddings:", cur.fetchone()[0])

cur.execute("""
    SELECT indexname, indexdef FROM pg_indexes
    WHERE tablename = 'sift_hybrid' ORDER BY indexname
""")
print("\nindexes on sift_hybrid:")
for name, definition in cur.fetchall():
    print(f"  {name}: {definition}")

# Prove the HNSW index is actually usable by the planner right now:
cur.execute("SELECT embedding::text FROM sift_hybrid LIMIT 1")
vec = cur.fetchone()[0]
cur.execute(
    "EXPLAIN (FORMAT JSON) SELECT id FROM sift_hybrid "
    f"ORDER BY embedding <-> '{vec}'::vector LIMIT 10"
)
plan = cur.fetchone()[0]

def walk(node, out):
    if node.get("Index Name"):
        out.append((node["Node Type"], node["Index Name"]))
    for child in node.get("Plans", []):
        walk(child, out)

used = []
walk(plan[0]["Plan"], used)
print("\nplanner nodes/indexes for pure vector KNN on sift_hybrid:", used)

conn.close()
print("\nDB-CHECK-DONE")
