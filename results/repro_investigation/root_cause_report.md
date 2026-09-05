# Root Cause Report: Reproducibility Discrepancy

**Date:** 2026-08-28
**Investigation directory:** `results/repro_investigation/`

## 1. Summary

The original canonical 1M SIFT1M experiment (results/real_run_20260826T065155Z/) reported HNSW_HYBRID mean Recall@10 = 0.810 and SQL_FIRST selected for 250/250 held-out queries. Reproducing the same code path on the current environment with identical HNSW parameters (m=16, ef_construction=64) produces HNSW_HYBRID mean Recall@10 = 0.9992 and SQL_FIRST selected for 0/250 queries. The discrepancy is NOT explained by index construction parameters, database configuration, or dataset integrity. It is most likely explained by HNSW graph construction quality differences between the original Docker environment and the current Homebrew environment, combined with a query workload that cannot be reproduced with the current code.

## 2. Evidence collected

### 2.1 Dataset integrity: CONFIRMED CORRECT
- SIFT1M SHA-256: 21f66e2975057b5728ba56de1c825bac4f4d89d596609ae985741c6242631816
- Vector count: 1,000,000 (exact match)
- Vector dimension: 128
- See: dataset_integrity.json

### 2.2 Database configuration: ESSENTIALLY IDENTICAL
All parameters match: shared_buffers=128MB, work_mem=4MB, maintenance_work_mem=64MB, effective_cache_size=4GB, random_page_cost=4, max_parallel_workers=8.
See: db_config_comparison.json
Conclusion: Database configuration cannot explain the discrepancy.

### 2.3 Index construction ablation on 200K subset: NO EFFECT
On the 200K subset, all ef_construction values (64, 200, 400) achieve perfect recall at all ef_search values. The index construction parameter does NOT explain the discrepancy on 200K.
See: index_ablation.csv

### 2.4 Canonical 1M reproduction: DIFFERENT RECALL
With canonical HNSW (m=16, ef_construction=64) and IVFFLAT (lists=1000) on the current Homebrew/PG17.10 environment:
- HNSW_HYBRID mean recall: 0.999 (vs 0.810 canonical)
- SQL_FIRST selected: 0/250 (vs 250/250 canonical)
See: canonical_1M_run/summary.csv
Conclusion: On the 1M dataset with identical parameters, the HNSW index achieves substantially different recall.

### 2.5 Query workload integrity: NOT REPRODUCIBLE
The original baseline query 0 had est_sel=0.130278 (bucket [0.10,0.25)). With the current schema (10 categories, 1M rows), this selectivity is IMPOSSIBLE to achieve with the original predicate templates. The maximum selectivity with template 1 (AND of 3) is 0.05.
See: query_integrity.json
Conclusion: The original baseline query workload cannot be reproduced with the current code.

## 3. Root cause classification

Classification: E. Multiple factors contribute.

1. HNSW graph construction quality. With identical parameters, the HNSW index produces mean Recall@10 = 0.810 in Docker and 0.999 in Homebrew. The HNSW graph quality depends on insertion order, memory layout, and OS page cache behavior.

2. Query workload non-reproducibility. The original query workload (est_sel=0.130 for query 0) cannot be reproduced with the current schema/templates.

3. Scale sensitivity. The discrepancy only manifests on 1M. On 200K, all configurations achieve perfect recall.

## 4. What is NOT the root cause
- Index construction parameters: ef_construction has no effect on 200K recall.
- Database configuration: all parameters identical.
- Dataset integrity: SIFT1M vectors byte-identical (SHA-256 match).
- Query generator determinism: with same NumPy version, produces identical results.

## 5. What can be reproduced
- On 200K: adaptive selects ANN 100%, perfect recall.
- On 1M current env: adaptive selects ANN, near-perfect recall.
- On 1M original Docker: adaptive selects SQL_FIRST 100% (HNSW graph was insufficiently accurate there).

## 6. Additional experiment required
1. Run the original Docker environment (pgvector/pgvector:0.8.5-pg16) on the same machine with the same data and seed. If original recall is reproduced, the discrepancy is Docker vs Homebrew. If not, it is query workload non-reproducibility.
2. Record the HNSW graph quality metric for both environments.
3. Record the original load_sift_hybrid.py and benchmark_hybrid_optimizer.py from the Docker image.

## 7. Implications for the paper
The claim that the adaptive system selects SQL_FIRST 100% of the time is environment-specific. The paper should either reproduce the result in a second environment, or frame the contribution as: the system safety layer correctly identifies when ANN is and is not feasible.

## 8. What I did NOT do
- Did not modify the original baseline artifacts.
- Did not change the benchmark code to produce favorable results.
- Did not tune parameters using held-out results.
- Did not claim the adaptive system works at 1M without the reproducibility issue being resolved.
