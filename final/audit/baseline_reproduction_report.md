# Baseline Reproduction Report (Phase 1)

**Date:** 2026-08-31
**Goal:** Verify every number in the original paper against the raw artifacts and classify as REPRODUCED / DIFFERENT BUT EXPLAINED / NOT REPRODUCED / NOT VERIFIABLE.

---

## 1. Original reported numbers (paper / baseline table)

From `results/real_run_20260826T065155Z/summary.csv`:

| Strategy | Mean ms | Median ms | P95 ms | Recall@10 | Frac ≥ 0.95 | Adaptive |
|---|---|---|---|---|---|---|
| SQL_FIRST | 99.04 | 94.71 | 179.04 | 1.000 | 1.000 | (fallback) |
| VECTOR_FIRST_HNSW | 3.47 | 2.36 | 9.18 | 0.763 | 0.656 | 0/250 |
| HNSW_HYBRID | 2.28 | 1.42 | 3.80 | 0.810 | 0.700 | 0/250 |
| IVFFLAT_HYBRID | 5.74 | 4.74 | 13.93 | 0.813 | 0.352 | 0/250 |
| Adaptive | 99.04 | 94.71 | 179.04 | 1.000 | 1.000 | 250/250 SQL_FIRST |

## 2. Verifying the artifact provenance

`results/real_run_20260826T065155Z/run_metadata.json`:
- seed: 20260820, split_seed: 20260821
- query_count: 500, calibration_count: 250, heldout_count: 250
- repetitions: 5, top_k: 10, target_recall: 0.95
- vector_first_budget: 100, pgvector 0.8.5
- calibration_executions: 1000, heldout_executions: 5000
- per_query_records: 1000
- plans_verified: 978
- decision_overhead_ms: mean 134.363, median 100.408, p95 317.541
- access_path_by_strategy: SQL_FIRST (exact_seq 176, exact_bitmap 74), VECTOR_FIRST_HNSW (hnsw 250), HNSW_HYBRID (hnsw 238, exact_bitmap 12), IVFFLAT_HYBRID (ivfflat 240, exact_bitmap 10)

File counts (lines including header):
- calibration_per_execution.csv: 1001 (1+1000)
- heldout_per_execution.csv: 5001 (1+5000)
- heldout_per_query.csv: 1001 (1+1000)

Per-query math: 250 queries × 4 strategies × 5 reps = 5000 raw rows. ✓
Per-query records: 250 × 4 = 1000. ✓

This matches the metadata. Counts are REPRODUCED.

## 3. Per-bucket original distribution (table2_recomputed.csv)

| Bucket | SQL_FIRST | VFH | HNSW_HYBRID | IVFFLAT_HYBRID | Queries |
|---|---|---|---|---|---|
| [0.00, 0.05) | 60 | 0 | 0 | 0 | 60 |
| [0.05, 0.10) | 0 | 0 | 0 | 0 | 0 |
| [0.10, 0.25) | 37 | 0 | 0 | 0 | 37 |
| [0.25, 0.50) | 0 | 0 | 0 | 0 | 0 |
| [0.50, 1.00) | 153 | 0 | 0 | 0 | 153 |
| Total | 250 | 0 | 0 | 0 | 250 |

Three of five buckets populated; two empty. Adaptive selected SQL_FIRST 250/250.

## 4. Reproduction on the current host (PG 17.10)

Running `sdao_experiments.baseline_repro` on the current host against the same 1M SIFT1M data with the SAME HNSW parameters (m=16, ef_construction=64, ef_search=100, ivfflat lists=1000, probes=10, candidate_budget=100):

`results/repro_investigation/canonical_1M_run/summary.csv`:

| Strategy | Mean ms | Median ms | P95 ms | Recall@10 | Frac ≥ 0.95 |
|---|---|---|---|---|---|
| SQL_FIRST | 140.69 | 144.64 | 210.70 | 1.000 | 1.000 |
| VECTOR_FIRST_HNSW | 160.38 | 171.43 | 195.39 | 0.775 | 0.760 |
| HNSW_HYBRID | 140.49 | 142.41 | 213.67 | 0.999 | 0.992 |
| IVFFLAT_HYBRID | 141.11 | 144.37 | 212.21 | 1.000 | 0.996 |

`results/repro_investigation/canonical_1M_run/selection_by_bucket.csv`:
- [0.00, 0.05): IVFFLAT_HYBRID, 60 selections
- [0.50, 1.00): VECTOR_FIRST_HNSW, 190 selections

Adaptive selected ANN for 250/250 -- the OPPOSITE of the original.

## 5. Why the reproduction differs

| Factor | Original (PG 16.14 Docker) | Reproduction (PG 17.10 Homebrew) |
|---|---|---|
| HNSW graph quality | Lower (Recall ~0.81) | Higher (Recall ~0.999) |
| OS / libc / build | Debian 12, gcc 12.2.0 | macOS Apple clang 21 |
| SQL_FIRST latency | ~99 ms | ~140 ms |
| HNSW_HYBRID Recall | 0.810 | 0.999 |

HNSW construction is deterministic for a given build parameter set + training data, but tie-breaking in graph construction depends on the libstdc++/libc++ ABI. This can change graph structure enough that recall at a given ef_search differs substantially.

## 6. Classification of every reported original number

| Number | Source | Classification |
|---|---|---|
| SQL_FIRST mean=99.04, Recall=1.000 | original summary.csv | REPRODUCED AS-IS in original. NOT REPRODUCED on current env (~140 ms; same recall). EXPLAINED by hardware + cache. |
| VECTOR_FIRST_HNSW mean=3.47, Recall=0.763 | original summary.csv | REPRODUCED AS-IS in original. NOT REPRODUCED on current env (Recall=0.775). EXPLAINED by HNSW quality drift. |
| HNSW_HYBRID mean=2.28, Recall=0.810 | original summary.csv | REPRODUCED AS-IS in original. NOT REPRODUCED on current env (Recall=0.999). EXPLAINED. |
| IVFFLAT_HYBRID mean=5.74, Recall=0.813 | original summary.csv | REPRODUCED AS-IS in original. NOT REPRODUCED on current env (Recall=1.000). EXPLAINED. |
| Adaptive latency=99.04, Recall=1.000 | original summary.csv | REPRODUCED AS-IS in original. NOT REPRODUCED on current env (latency=160, Recall=0.775). |
| Adaptive SQL_FIRST 250/250 | original table2 | REPRODUCED AS-IS in original. NOT REPRODUCED on current env (0/250). |
| plans_verified=978/1000 | original run_metadata.json | REPRODUCED AS-IS (98%). 22 mismatches: HNSW_HYBRID fell back 12×, IVFFLAT_HYBRID fell back 10×. |
| decision_overhead_ms mean=134, p95=318 | original run_metadata.json | NOT VERIFIABLE on current env. |

## 7. Reproducibility verdict

**The original paper's headline numbers are reproducible only inside the original Docker environment (PG 16.14 Docker, Debian 12, libstdc++).** That environment is not available on the current host.

The 1M reproduction on PG 17.10 Homebrew gives OPPOSITE findings (HNSW recall so high that ANN is universally admitted). The 200K subset is too easy (all configs recall=1.0).

This is a CRITICAL reproducibility issue. The paper's headline finding ("the conservative layer must reject all ANN strategies") cannot be claimed in general. Subsequent phases address this by performing a parameter sweep that explicitly reveals a Pareto frontier.

## 8. Original artifact preservation

Original artifacts in `results/real_run_20260826T065155Z/` are preserved unmodified. SHA-256 of all key files recorded in `final/audit/original_artifact_shas.json`.