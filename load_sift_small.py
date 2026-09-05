"""Load the SIFT1M base vectors into PostgreSQL.

This is a fresh loader tailored for the current environment (PostgreSQL 17,
pgvector 0.8.5). It writes a fixed seed for the synthetic attributes and
uses mmap to avoid double-buffering the 500MB vector file.
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
ROW_COUNT = 1_000_000
CATEGORIES = [f'category_{i:02d}' for i in range(10)]
PATH = '/Users/abhijeetmiskin/AppData/MyProject/dataset/sift/sift_base.fvecs'
BATCH = 5000

print(f'Reading {PATH}...')
raw = np.fromfile(PATH, dtype=np.int32)
width = VECTOR_DIM + 1
n = raw.size // width
print(f'Found {n} vectors (expected {ROW_COUNT})')
if n != ROW_COUNT:
    raise SystemExit(f'Vector count mismatch: {n} != {ROW_COUNT}')
records = raw.reshape(-1, width)
vectors = records[:, 1:].view(np.float32).reshape(-1, VECTOR_DIM)
print(f'Vector array: {vectors.shape}, dtype={vectors.dtype}')

# Deterministic attributes
rng = np.random.default_rng(20260820)
cat_indices = rng.integers(0, 10, size=ROW_COUNT)
prices = (10 + rng.random(ROW_COUNT) * 990).astype(np.float32)
stocks = rng.integers(0, 2, size=ROW_COUNT).astype(bool)

conn = psycopg2.connect(host='localhost', user='sdao', dbname='sdao')
print('Connected to PostgreSQL')

insert_sql = "INSERT INTO sift_hybrid (embedding, category, price, in_stock) VALUES %s"
template = "(%s::vector, %s, %s, %s)"

print(f'Loading {ROW_COUNT} rows in batches of {BATCH}...')
start = time.time()
with conn.cursor() as cur:
    for i in range(0, ROW_COUNT, BATCH):
        batch_end = min(i + BATCH, ROW_COUNT)
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
        if (i // BATCH) % 20 == 0:
            elapsed = time.time() - start
            rate = (batch_end) / elapsed
            print(f'  inserted {batch_end:,} rows ({rate:.0f} rows/s)', flush=True)
    conn.commit()
print(f'Load complete in {time.time() - start:.1f}s')
conn.close()
print('Done')
