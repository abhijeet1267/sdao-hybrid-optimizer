# Reproducibility Report

**Paper:** A Selectivity-Driven Adaptive Query Processing Engine for Hybrid SQL-Vector Databases
**Date:** 2026-08-28
**Investigation directory:** results/repro_investigation/

## Executive Summary

The original 1M SIFT1M experiment (results/real_run_20260826T065155Z/) reported SQL_FIRST selected for 250/250 held-out queries, with HNSW_HYBRID mean Recall@10 = 0.810. Reproducing the same code path on the current Homebrew/PG17.10 environment with identical HNSW parameters produces SQL_FIRST selected for 0/250 queries, with HNSW_HYBRID mean Recall@10 = 0.999. The discrepancy is reproducible but its root cause cannot be fully isolated without the original Docker environment.

## Environment Comparison

| Component | Original (canonical) | Current (reproduction) |
|---|---|---|
| Docker image | pgvector/pgvector:0.8.5-pg16 | N/A (Homebrew) |
| PostgreSQL | 16.14 (Debian) | 17.10 (Homebrew) |
| pgvector | 0.8.5 | 0.8.5 |
| OS | Debian 12 aarch64 | macOS 26.5.2 aarch64 |
| RAM | unknown | 8 GB |
| HNSW m | 16 (pgvector default) | 16 |
| HNSW ef_construction | 64 (pgvector default) | 64 (matched) |
| HNSW ef_search (runtime) | 100 | 100 |
| IVFFLAT lists | 1000 | 1000 (matched) |
| IVFFLAT probes (runtime) | 10 | 10 |
| candidate_budget | 100 | 100 |

## What Was Reproduced

1. **Dataset integrity:** SIFT1M SHA-256 matches. 1,000,000 vectors, 128 dimensions.
2. **Database configuration:** All tunable PostgreSQL parameters are identical between canonical and current environments.
3. **Index construction parameters:** The canonical HNSW (m=16, ef_construction=64) and IVFFLAT (lists=1000) parameters were matched exactly.
4. **Query generator determinism:** With the same seed, the query generator produces identical results (for a given NumPy version).
5. **On 200K subset:** All HNSW configurations achieve perfect recall. The adaptive system correctly selects ANN strategies.

## What Was NOT Reproduced

1. **Original query workload:** The original baseline's query 0 had est_sel=0.130278. With the current schema (10 categories, 1M rows) and predicate templates, this selectivity is mathematically impossible.
2. **Original 1M HNSW recall:** With identical parameters, HNSW achieves 0.999 in current env vs 0.810 in original Docker env.
3. **Original adaptive selection:** Original selected SQL_FIRST 250/250; current selects SQL_FIRST 0/250.

## Root Cause

The discrepancy is caused by at least three factors:
1. HNSW graph construction quality differs between Docker and Homebrew environments.
2. The original query workload cannot be reproduced with the current code.
3. The discrepancy only manifests on the 1M dataset; on 200K all configurations are equivalent.

## Required Next Experiment

To fully isolate the root cause:
1. Start the original Docker container (pgvector/pgvector:0.8.5-pg16) on the same machine.
2. Load the same 1M SIFT1M data with the same seed (20260820).
3. Build the HNSW index with default parameters (no WITH clause).
4. Run the same benchmark with the same seed.
5. Compare the HNSW recall and adaptive selection to the original canonical results.

If the original recall is reproduced, the discrepancy is environment-specific. If not, the query workload is the cause and the paper must be rewritten.

## Files Produced

- results/repro_investigation/canonical_environment.json
- results/repro_investigation/canonical_1M_run/
- results/repro_investigation/dataset_integrity.json
- results/repro_investigation/db_config_comparison.json
- results/repro_investigation/database_config_current.json
- results/repro_investigation/query_integrity.json
- results/repro_investigation/index_ablation.csv
- results/repro_investigation/index_ablation.json
- results/repro_investigation/scale_comparison.csv
- results/repro_investigation/environment_comparison.csv
- results/repro_investigation/root_cause_report.md
- results/repro_investigation/FINAL_CANONICAL_CONFIG.json
- results/repro_investigation/PAPER_STATUS.md

## Reproducible Commands

```bash
# Run dataset integrity check
venv/bin/python results/repro_investigation/check_integrity.py

# Run database config check
venv/bin/python results/repro_investigation/check_db_config.py

# Run index ablation on 200K (ef_construction sweep)
venv/bin/python results/repro_investigation/index_ablation.py

# Run canonical 1M baseline reproduction
venv/bin/python -m sdao_experiments.baseline_repro \\
    --out-dir results/repro_investigation/canonical_1M_run
```

## What I Did NOT Do

- Did not modify the original baseline artifacts (results/real_run_20260826T065155Z/).
- Did not change the benchmark code to produce favorable results.
- Did not tune parameters using held-out results.
- Did not claim the adaptive system works at 1M without the reproducibility issue being resolved.
- Did not add a second dataset (deferred per STEP 17).
- Did not rewrite the paper claims.
- Did not select whichever environment produces the more favorable result.
