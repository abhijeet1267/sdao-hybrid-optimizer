"""Build the HNSW, IVFFLAT, and B-tree indexes for sift_hybrid.

Tuned for an 8GB-RAM Mac. HNSW build is memory-intensive, so we let
PostgreSQL use its default (1GB) and accept slower build times. B-tree
indexes are small and fast.
"""
import os
os.environ['PGHOST'] = 'localhost'
os.environ['PGUSER'] = 'sdao'
os.environ['PGDATABASE'] = 'sdao'
import time
import psycopg2

print('ANALYZE...')
conn = psycopg2.connect(host='localhost', user='sdao', dbname='sdao')
conn.autocommit = True
with conn.cursor() as c:
    c.execute('ANALYZE sift_hybrid;')
print('Building B-tree indexes...')
start = time.time()
with conn.cursor() as c:
    c.execute('CREATE INDEX IF NOT EXISTS sift_hybrid_category_idx ON sift_hybrid (category);')
    c.execute('CREATE INDEX IF NOT EXISTS sift_hybrid_price_idx ON sift_hybrid (price);')
    c.execute('CREATE INDEX IF NOT EXISTS sift_hybrid_in_stock_idx ON sift_hybrid (in_stock);')
print(f'  done in {time.time()-start:.1f}s')

print('Building HNSW index (m=16, ef_construction=200)...')
start = time.time()
with conn.cursor() as c:
    c.execute('SET maintenance_work_mem = "2GB";')
    c.execute('CREATE INDEX IF NOT EXISTS sift_hybrid_embedding_hnsw_idx ON sift_hybrid USING hnsw (embedding vector_l2_ops) WITH (m = 16, ef_construction = 200);')
print(f'  HNSW done in {time.time()-start:.1f}s')

print('Building IVFFLAT index (lists=100)...')
start = time.time()
with conn.cursor() as c:
    c.execute('SET maintenance_work_mem = "2GB";')
    c.execute('CREATE INDEX IF NOT EXISTS sift_hybrid_embedding_ivfflat_idx ON sift_hybrid USING ivfflat (embedding vector_l2_ops) WITH (lists = 100);')
print(f'  IVFFLAT done in {time.time()-start:.1f}s')

print('All indexes built.')
with conn.cursor() as c:
    c.execute("SELECT indexname, pg_size_pretty(pg_relation_size(indexname::regclass)) FROM pg_indexes WHERE tablename='sift_hybrid' ORDER BY 2 DESC;")
    for row in c.fetchall():
        print(f'  {row[0]}: {row[1]}')
conn.close()
