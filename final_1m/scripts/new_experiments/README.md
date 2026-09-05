# pgvector Hybrid-Benchmark — New Experiments

This directory contains the four Python benchmark scripts required for the
new experiments in the manuscript:

| Script                        | Experiment                          | Output CSV                       |
|-------------------------------|-------------------------------------|----------------------------------|
| `benchmark_scale.py`          | N × selectivity scale sweep         | `results_scale.csv`              |
| `benchmark_q_error.py`        | Cardinality q-error injection       | `results_q_error.csv`            |
| `benchmark_cold_cache.py`     | Hot vs cold buffer-cache I/O        | `results_cold_cache.csv`         |
| `benchmark_pac_bounds.py`     | PAC-bounds validation (T seeds)     | `results_pac.csv` + `results_pac_raw.csv` |

All scripts:
- Read credentials from `final/audit/db_config.json` (no hardcoding).
- Load query vectors from a local SIFT-1M `.fvecs` file (preferred) or fall
  back to the SIFT-10M HDF5 download (used for `--scale > 1M`).
- Run real SQL queries against PostgreSQL 17.10 + pgvector 0.7+.
- Export clean CSVs into `final/results/new_experiments/`.
- Use the four query strategies `SQL_FIRST`, `VECTOR_FIRST_HNSW`,
  `HNSW_HYBRID`, `IVFFLAT_HYBRID` defined in `_common.py`.

## Prerequisites

```
pip install psycopg2-binary numpy h5py pgvector
```

The `pgvector` package is used for client-side vector adapters so the
embedding parameter is sent as a `vector` literal (not `numeric[]`).

## Environment

macOS 14.6 (Apple Silicon), PostgreSQL 17.10 (native or Docker),
pgvector 0.7+.

The schema is **configurable** via `db_config.json`:
- `table_name` — any SIFT-1M-shaped table with columns
  `id, embedding, category (varchar), price (numeric), in_stock (bool)`.
- `distance_op` — `<->` (L2), `<=>` (cosine), or `<#>` (inner product).
- `distance_name` — used only in CSV output / logging.
- `container_name` — set to your Docker container name **or leave empty**
  for a native Postgres install.  The cold-cache script branches on this.

To create the indexes manually (only needed if not already present):

```sql
CREATE TABLE sift_hybrid (                  -- or `items` for a from-scratch run
    id integer PRIMARY KEY,
    embedding vector(128),
    category varchar(16),
    price numeric(10,2),
    in_stock boolean
);
CREATE INDEX ON sift_hybrid USING btree (category);
CREATE INDEX ON sift_hybrid USING btree (price);
CREATE INDEX ON sift_hybrid USING btree (in_stock);
CREATE INDEX ON sift_hybrid USING hnsw (embedding vector_l2_ops)        -- L2
    WITH (m = 16, ef_construction = 200);
CREATE INDEX ON sift_hybrid USING ivfflat (embedding vector_l2_ops)
    WITH (lists = 1000);
```

## Usage

```bash
# From the directory containing the scripts
cd final/scripts/new_experiments

# Default mode: create + populate an `items` table from SIFT-10M.
#   - benchmark_scale.py sweeps N ∈ {100K, 1M, 10M}
#   - benchmark_q_error.py runs 7 q-error factors × 5 buckets × 4 strategies
#   - benchmark_cold_cache.py runs 3 phases: hot, cold, hot-again
#   - benchmark_pac_bounds.py runs 30 seeds × 5 buckets × 4 strategies
python3 benchmark_scale.py
python3 benchmark_q_error.py
python3 benchmark_cold_cache.py
python3 benchmark_pac_bounds.py --n-seeds 30 --queries-per-bucket 20
```

### Reuse-table mode (run against an existing populated table)

If the table already exists and is pre-loaded (e.g. the lab's
`sift_hybrid` with 1M rows), pass `--reuse-table` to skip truncate /
bulk-insert / ANALYZE and read the row count from the existing data:

```bash
# Quick smoke test (~14 s): 1 seed, 1 query per bucket, all 4 strategies
python3 benchmark_pac_bounds.py --n-seeds 1 --queries-per-bucket 1 --reuse-table

# Full q-error sweep
python3 benchmark_q_error.py --queries-per-bucket 5 --reuse-table

# Full scale sweep (single N, but with the actual row count)
python3 benchmark_scale.py --queries-per-bucket 5 --repeats 3 --reuse-table

# Full cold-cache experiment
python3 benchmark_cold_cache.py --queries-per-bucket 5 --repeats 3 --reuse-table
```

In reuse mode:
- `truncate_items` is skipped.
- `bulk_insert` is skipped.
- `load_sift_vectors` (HDF5) is skipped.
- Queries are loaded from a local SIFT-1M `.fvecs` file (point
  `$SIFT_QUERY_FVECS` at your copy of `sift_query.fvecs`, or place it
  under `./data/` or `/tmp/`), avoiding the 3.3 GB download.
- `create_vector_indexes` is idempotent — it only creates an index if no
  HNSW/IVFFlat index on `embedding` already exists.

## `db_config.json` schema

```jsonc
{
  // Connection
  "host": "localhost", "port": 5432, "dbname": "sdao",
  "user": "sdao", "password": "...", "schema": "public",

  // Cold-cache control
  "container_name": "",           // empty → macOS 'purge' fallback
                                  // non-empty → 'docker restart <name>'

  // Table & distance
  "table_name": "sift_hybrid",
  "distance_op": "<->",            // "<->" L2, "<=>" cosine, "<#>" IP
  "distance_name": "L2",

  // pgvector index parameters
  "ivfflat_lists": 1000,
  "hnsw_m": 16,
  "hnsw_ef_construction": 200,
  "hnsw_ef_search": 100,           // applied via SET LOCAL hnsw.ef_search
  "ivfflat_probes": 10             // applied via SET LOCAL ivfflat.probes
}
```

## Notes on the Cold-Cache Script

Because macOS does not expose `/proc/sys/vm/drop_caches`, the script
falls back to one of two strategies based on `container_name`:

- **`container_name` set** — `docker restart <name>` and wait for
  PostgreSQL to accept connections again.  Buffer cache and macOS
  filesystem cache are fully dropped.
- **`container_name` empty** — invoke `sync` + `purge` to drop the macOS
  filesystem cache, and call `pg_prewarm` if available.  This is a
  best-effort drop on a native install.

The pgvector extension is preferred to be available for `pg_prewarm`.

associated with the container are cleared on restart.

The script runs **three** phases per workload: HOT, COLD, and HOT (2nd)
to demonstrate the warm-up effect of bringing data back into the buffer
pool.

## Notes on the q-Error Script

PostgreSQL does not provide a direct knob to set the planner's row-count
estimate. We approximate q-error injection by:

1. Adjusting `default_statistics_target` via `ALTER TABLE … SET STATISTICS`
   and re-ANALYZE — lower target → coarser histograms → larger
   mis-estimation.
2. Setting `random_page_cost` and `seq_page_cost` via `SET LOCAL` to
   bias the optimizer toward index or sequential plans, as it would do
   for an over- or under-estimated row count.

We then measure the **observed** q-error by comparing the planner's
`Plan Rows` (from `EXPLAIN`) with the actual row count. This observed
q-error is logged alongside the configured factor for each run.

## Notes on the PAC-Bounds Script

For each of T independent RNG seeds, the script reloads the dataset with
different synthetic relational columns (category/price/in_stock) and
measures per-query Recall@10. Across all seeds, it computes:

- Per-seed mean Recall@10.
- Empirical 95% confidence interval (percentile bootstrap, 2000
  resamples).
- Bernstein PAC half-width at confidence `1 − δ`.
- A `ci_within_pac` boolean flag: `True` if the empirical CI is
  contained within the PAC bound.
