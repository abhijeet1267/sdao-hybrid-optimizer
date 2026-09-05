"""Build IVFFLAT index on sift_hybrid_200k if missing."""
import time
import psycopg2

conn = psycopg2.connect(host="localhost", user="sdao", dbname="sdao")
conn.autocommit = True
with conn.cursor() as c:
    c.execute("SELECT amname FROM pg_class c JOIN pg_am am ON c.relam=am.oid WHERE c.relname='sift_hybrid_200k_embedding_ivfflat_idx'")
    row = c.fetchone()
    if row:
        print(f"Index already exists: am={row[0]}")
    else:
        print("Building IVFFLAT index on sift_hybrid_200k (lists=100)...")
        t0 = time.time()
        c.execute("SET maintenance_work_mem = '2GB';")
        c.execute("CREATE INDEX sift_hybrid_200k_embedding_ivfflat_idx ON sift_hybrid_200k USING ivfflat (embedding vector_l2_ops) WITH (lists = 100);")
        print(f"  Done in {time.time()-t0:.1f}s")
conn.close()