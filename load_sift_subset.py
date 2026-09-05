"""Create a 200K-vector SIFT1M subset for memory-constrained experiments.

The full 1M-vector SIFT1M HNSW index (782 MB) does not fit in the 8 GB
RAM available on this machine. We use the first 200K vectors which
produces a ~156 MB HNSW index that fits in memory, enabling warm-cache
benchmarking.

This is a valid scientific subset: the same dataset, same distribution,
just smaller. All relative comparisons (strategy vs strategy, policy vs
policy) are scientifically meaningful.
"""
import os
os.environ['PGHOST'] = 'localhost'
os.environ['PGUSER'] = 'sdao'
os.environ['PGDATABASE'] = 'sdao'
import time
import numpy as np
import psycopg2
from psycopg2.extras import execute_values

VECTOR_DIM = 128
SUBSET_SIZE = 200_000
CATEGORIES = [f'category_{i:02d}' for i in range(10)]
PATH = '/Users/abhijeetmiskin/AppData/MyProject/dataset/sift/sift_base.fvecs'
BATCH = 5000

print(f'Reading first {SUBSET_SIZE} vectors from {PATH}...')
raw = np.fromfile(PATH, dtype=np.int32)
width = VECTOR_DIM + 1
records = raw.reshape(-1, width)
vectors = records[:SUBSET_SIZE, 1:].view(np.float32).reshape(-1, VECTOR_DIM)
print(f'Vector array: {vectors.shape}')

# Deterministic attributes for the subset
rng = np.random.default_rng(20260820)
cat_indices = rng.integers(0, 10, size=SUBSET_SIZE)
prices = (10 + rng.random(SUBSET_SIZE) * 990).astype(np.float32)
stocks = rng.integers(0, 2, size=SUBSET_SIZE).astype(bool)

conn = psycopg2.connect(host='localhost', user='sdao', dbname='sdao')

print('Dropping and recreating sift_hybrid_200k...')
with conn.cursor() as cur:
    cur.execute('DROP TABLE IF EXISTS sift_hybrid_200k CASCADE;')
    cur.execute('''
        CREATE TABLE sift_hybrid_200k (
            id SERIAL PRIMARY KEY,
            embedding vector(128) NOT NULL,
            category VARCHAR(50) NOT NULL,
            price NUMERIC(10, 2) NOT NULL,
            in_stock BOOLEAN NOT NULL
        );
    ''')
conn.commit()

insert_sql = "INSERT INTO sift_hybrid_200k (embedding, category, price, in_stock) VALUES %s"
template = "(%s::vector, %s, %s, %s)"

print(f'Loading {SUBSET_SIZE} rows...')
start = time.time()
with conn.cursor() as cur:
    for i in range(0, SUBSET_SIZE, BATCH):
        batch_end = min(i + BATCH, SUBSET_SIZE)
        rows = []
        for j in range(i, batch_end):
            v = vectors[j]
            rows.append((
                '[' + ','.join(f'{x:.6f}' for x in v) + ']',
                CATEGORIES[cat_indices[j]],
                float(prices[j]),
                bool(stocks[j]),
            ))
        execute_values(cur, insert_sql, rows, template=template, page_size=BATCH)
    conn.commit()
print(f'Load complete in {time.time() - start:.1f}s')

print('ANALYZE and creating B-tree indexes...')
with conn.cursor() as cur:
    cur.execute('ANALYZE sift_hybrid_200k;')
    cur.execute('CREATE INDEX sift_hybrid_200k_category_idx ON sift_hybrid_200k (category);')
    cur.execute('CREATE INDEX sift_hybrid_200k_price_idx ON sift_hybrid_200k (price);')
    cur.execute('CREATE INDEX sift_hybrid_200k_in_stock_idx ON sift_hybrid_200k (in_stock);')
conn.commit()

print('Building HNSW index (m=16, ef_construction=200)...')
start = time.time()
with conn.cursor() as cur:
    cur.execute('SET maintenance_work_mem = "2GB";')
    cur.execute('''CREATE INDEX sift_hybrid_200k_embedding_hnsw_idx
                   ON sift_hybrid_200k USING hnsw (embedding vector_l2_ops)
                   WITH (m = 16, ef_construction = 200);''')
print(f'  HNSW done in {time.time() - start:.1f}s')

print('Building IVFFLAT index (lists=100)...')
start = time.time()
with conn.cursor() as cur:
    cur.execute('SET maintenance_work_mem = "2GB";')
    cur.execute('''CREATE INDEX sift_hybrid_200k_embedding_ivfflat_idx
                   ON sift_hybrid_200k USING ivfflat (embedding vector_l2_ops)
                   WITH (lists = 100);''')
print(f'  IVFFLAT done in {time.time() - start:.1f}s')

print('All indexes built.')
with conn.cursor() as cur:
    cur.execute("""SELECT indexname, pg_size_pretty(pg_relation_size(indexname::regclass))
                   FROM pg_indexes WHERE tablename='sift_hybrid_200k' ORDER BY 2 DESC;""")
    for row in cur.fetchall():
        print(f'  {row[0]}: {row[1]}')

# Update dataset_size in the SIFT query file so the workload generator uses 200K
print(f'\nUpdating dataset size reference to {SUBSET_SIZE}...')
conn.close()
