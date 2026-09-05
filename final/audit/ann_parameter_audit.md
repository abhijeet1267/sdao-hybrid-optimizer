# ANN Parameter Audit (Phase 4)

**Date:** 2026-08-31
**Goal:** Inspect and report the actual configuration of HNSW, IVFFLAT, and PostgreSQL, as configured for both the original baseline and the current reproduction.

---

## 1. Index definitions on `sift_hybrid` (1M rows, current PG 17.10)

Verified via `SELECT am.amname, c.relname FROM pg_class c JOIN pg_am am ON c.relam=am.oid WHERE c.relname LIKE '%sift%' AND c.relkind='i'`:

| Index | Access method | Purpose |
|---|---|---|
| sift_hybrid_pkey | btree | primary key on id |
| sift_hybrid_category_idx | btree | category column |
| sift_hybrid_price_idx | btree | price column |
| sift_hybrid_in_stock_idx | btree | in_stock column |
| sift_hybrid_embedding_hnsw_idx | hnsw | ANN vector index |
| sift_hybrid_embedding_ivfflat_idx | ivfflat | ANN vector index |

HNSW index options (current build):
- `m = 16`
- `ef_construction = 200`

IVFFLAT index options:
- `lists = 1000`

Runtime parameters (set via `SET LOCAL` before each query):
- `hnsw.ef_search = 100` (original baseline and current default)
- `ivfflat.probes = 10` (original baseline and current default)
- `enable_indexscan = off` for SQL_FIRST (force sequential / bitmap scan)

## 2. Original baseline ANN parameters

From `results/real_run_20260826T065155Z/run_metadata.json`:
- HNSW: `m=16`, `ef_construction=64` (pgvector default), runtime `ef_search=100`
- IVFFLAT: `lists=1000`, runtime `probes=10`
- VECTOR_FIRST_HNSW: `candidate_budget=100`

## 3. PostgreSQL configuration (current, Homebrew 17.10)

To check: `shared_buffers`, `work_mem`, `effective_cache_size`, `max_parallel_workers_per_gather`, `random_page_cost`, `effective_io_concurrency`, `jit`, default_statistics_target.

(Recorded in `final/audit/db_config.json` after running a dedicated capture script.)

## 4. Vector_first budget audit

VECTOR_FIRST_HNSW uses a budget of 100 candidates. At k=10 and selectivity s, the expected number of predicate-matching candidates in the budget is `100 × s`. If `100 × s < 10`, recall is structurally impossible.

- s=0.01 (bucket [0.00,0.05)): 1 candidate expected → recall impossible.
- s=0.05: 5 candidates → recall limited.
- s=0.10: 10 candidates → marginal.
- s=0.50: 50 candidates → recall plausible.

This explains the vector-first failures in low-selectivity buckets. The budget of 100 is too small for low-selectivity hybrid queries.

## 5. Original baseline query statement templates

From `sdao_experiments/baseline_repro.py`:

```python
def _build_statement(query, strategy, vector_literal):
    if strategy == "SQL_FIRST":
        return (f"SELECT id FROM sift_hybrid WHERE {predicate_sql} "
                "ORDER BY embedding <-> %s::vector LIMIT 10",
                ..., {"enable_indexscan": "off"})
    if strategy == "VECTOR_FIRST_HNSW":
        return (f"WITH candidates AS MATERIALIZED ("
                f"SELECT id, embedding <-> %s::vector AS distance "
                f"FROM sift_hybrid ORDER BY embedding <-> %s::vector LIMIT 100) "
                f"SELECT candidates.id FROM candidates JOIN sift_hybrid item ON item.id = candidates.id "
                f"WHERE {predicate_sql} "
                "ORDER BY candidates.distance, candidates.id LIMIT 10",
                ..., {"hnsw.ef_search": 100, "ivfflat.probes": 1000})
    if strategy == "HNSW_HYBRID":
        return (f"SELECT id FROM sift_hybrid WHERE {predicate_sql} "
                "ORDER BY embedding <-> %s::vector LIMIT 10",
                ..., {"hnsw.ef_search": 100, "ivfflat.probes": 1000})
    if strategy == "IVFFLAT_HYBRID":
        return (f"SELECT id FROM sift_hybrid WHERE {predicate_sql} "
                "ORDER BY embedding <-> %s::vector LIMIT 10",
                ..., {"ivfflat.probes": 10, "hnsw.ef_search": 1000})
```

Note: in VECTOR_FIRST_HNSW and HNSW_HYBRID, the alternative index (`ivfflat.probes=1000` and `hnsw.ef_search=1000`) is forced high so it never wins. For IVFFLAT_HYBRID, `hnsw.ef_search=1000` is set to disable HNSW.

## 6. Known issues with the original baseline

1. The candidate budget of 100 is too low for low-selectivity queries → VECTOR_FIRST_HNSW systematically fails on bucket [0.00, 0.05).
2. The hybrid strategies (HNSW_HYBRID, IVFFLAT_HYBRID) require the planner to use the vector index with predicate prefiltering. When EXPLAIN estimates the selectivity incorrectly, the planner may switch to exact bitmap scans. Original metadata shows: HNSW_HYBRID used hnsw 238/250 times, exact_bitmap 12 times; IVFFLAT_HYBRID used ivfflat 240/250, exact_bitmap 10 times. These 22 fallback cases are NOT errors — they are legitimate planner choices when selectivity makes the index scan unprofitable.
3. The min-recall admission rule makes no distinction between "ANN is unsafe" and "ANN was rejected because of one outlier" — both look the same to the policy.

## 7. Parameter-sensitivity plan (Phase 5)

For the final paper we will sweep:

HNSW
- ef_search ∈ {40, 100, 200, 400}
- m ∈ {16, 32} (rebuild required)
- ef_construction ∈ {64, 200} (rebuild required)

IVFFLAT
- probes ∈ {1, 10, 50, 200}
- lists ∈ {1000} (fixed for 1M)

VECTOR_FIRST_HNSW
- candidate_budget ∈ {100, 500, 1000}

This gives a Pareto frontier; we will not pre-select a "best" parameter set.