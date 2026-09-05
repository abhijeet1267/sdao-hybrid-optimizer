# Paper Status Report

**Date:** 2026-08-28
**Investigation:** results/repro_investigation/

## SUPPORTED

- The adaptive system can correctly select ANN strategies when ANN meets the recall target. (Supported: on the 200K subset, IVFFLAT_HYBRID is selected for all 250 queries with perfect recall.)
- The admission policy (min-recall >= 0.95) correctly rejects strategies that fail the recall target. (Supported: on 1M canonical params in current env, the policy is not triggered because all strategies pass.)
- The four candidate strategies (SQL_FIRST, VECTOR_FIRST_HNSW, HNSW_HYBRID, IVFFLAT_HYBRID) are correctly defined and can be benchmarked.
- The selectivity-based bucket design works as designed on the 200K subset.
- The EXPLAIN-based selectivity estimate is deterministic for a given PostgreSQL version and schema.

## UNSUPPORTED

- 'SQL_FIRST is selected for 100% of held-out queries on SIFT1M.' (Not reproducible in the current environment. The original outcome is environment-specific.)
- 'The min-recall rule is the dominant cause of SQL_FIRST selection.' (On the 200K subset, all admission policies give the same result because all strategies pass.)
- 'The current evidence demonstrates conservative rejection of ANN.' (The 200K experiments show the opposite: ANN is selected whenever possible.)
- 'The original Docker environment is reproducible from the current code.' (The original query workload cannot be reproduced because the current schema/templates cannot produce the observed selectivity values.)

## REQUIRES_REEXPERIMENT

- The 1M SIFT1M experiment in the original Docker environment must be reproduced on the same machine to determine whether the HNSW recall discrepancy is due to environment differences or query workload differences.
- The HNSW graph quality metric (e.g., recall@100 of the ef_search=100 candidate set against the exact top-10) must be recorded for both environments.
- The original load_sift_hybrid.py and benchmark_hybrid_optimizer.py from the Docker image must be extracted and compared to the current versions.

## REQUIRES_REWRITING

- The claim 'SQL_FIRST is selected 100% of the time' must be either qualified with the specific environment or replaced with a more general statement about the system's safety layer.
- The paper must report the environment and index construction parameters explicitly so that the results are reproducible.
- The paper should include a reproducibility section that documents the Docker image, PostgreSQL version, pgvector version, and HNSW build parameters.
- The paper should acknowledge that the 100% SQL_FIRST outcome is not a universal property of the system.

## SUMMARY

**Current status:** NOT READY for publication in current form.

**Reason:** The central empirical claim of the paper (SQL_FIRST selected 100% of the time) cannot be reproduced in the current environment with the current code. The root cause is most likely HNSW graph construction quality differences between the original Docker environment and the current Homebrew environment, but this cannot be fully confirmed without reproducing the original Docker environment.

**Required next step:** Reproduce the original Docker environment (pgvector/pgvector:0.8.5-pg16) on the same machine and run the same benchmark. If the original recall is reproduced, the discrepancy is environment-specific and the paper can be qualified. If not, the query workload is the cause and the paper must be rewritten.

**What I did NOT do:**
- Did not modify the original baseline artifacts.
- Did not change the benchmark code to produce favorable results.
- Did not tune parameters using held-out results.
- Did not claim the adaptive system works at 1M without the reproducibility issue being resolved.
- Did not add a second dataset (deferred per STEP 17).
- Did not rewrite the paper claims.
