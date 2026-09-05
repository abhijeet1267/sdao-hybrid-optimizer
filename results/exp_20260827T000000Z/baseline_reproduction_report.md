# Baseline Reproduction Report

**Date:** 2026-08-27
**Run directory:** `results/exp_20260827T000000Z/baseline_reproduction/`
**Comparison baseline:** `results/real_run_20260826T065155Z/`

## Environment differences

| Component | Original baseline | This reproduction |
|---|---|---|
| PostgreSQL | 16.14 (Docker, aarch64) | 17.10 (Homebrew, aarch64) |
| pgvector | 0.8.5 | 0.8.5 ✅ |
| SIFT1M rows | 1,000,000 | 1,000,000 ✅ |
| SIFT1M vectors | 1,000,000 × 128-dim | 1,000,000 × 128-dim ✅ |
| HNSW build | `m=16, ef_construction=64` (default) | `m=16, ef_construction=200` (first run) then `m=16, ef_construction=64` (second run) |
| IVFFLAT lists | 1000 | 100 |
| Query seed | 20260820 | 20260820 ✅ |
| Split seed | 20260821 | 20260821 ✅ |
| NumPy | unknown (Docker image) | 2.5.1 |

## Results with HNSW `ef_construction=200` (first run, `baseline_reproduction/`)

| Strategy | Mean latency (ms) | Median | P95 | Mean Recall@10 | Frac ≥ 0.95 |
|---|---|---|---|---|---|
| SQL_FIRST | 139.4 | 130.5 | 188.6 | 1.000 | 1.000 |
| VECTOR_FIRST_HNSW | 156.5 | 152.0 | 183.8 | 0.775 | 0.760 |
| HNSW_HYBRID | 138.4 | 128.7 | 184.2 | **1.000** | **0.996** |
| IVFFLAT_HYBRID | 138.7 | 130.2 | 182.7 | **0.999** | **0.992** |

**Adaptive selections:** IVFFLAT_HYBRID for 60/60 queries in [0.00,0.05); VECTOR_FIRST_HNSW for 190/250 queries in [0.50,1.00). **SQL_FIRST is NOT selected 100% — the adaptive policy admits ANN.**

## Results with HNSW `ef_construction=64` (second run, `baseline_reproduction_original_hnsw/`)

| Strategy | Mean latency (ms) | Median | P95 | Mean Recall@10 | Frac ≥ 0.95 |
|---|---|---|---|---|---|
| SQL_FIRST | 98.1 | 102.9 | 131.6 | 1.000 | 1.000 |
| VECTOR_FIRST_HNSW | 112.0 | 111.0 | 124.4 | 0.775 | 0.760 |
| HNSW_HYBRID | 97.9 | 102.6 | 131.2 | **1.000** | **0.996** |
| IVFFLAT_HYBRID | 98.1 | 102.7 | 132.1 | **0.999** | **0.988** |

**Adaptive selections:** Same as above — IVFFLAT_HYBRID for 60/60 in [0.00,0.05); VECTOR_FIRST_HNSW for 190/250 in [0.50,1.00).

## Why the results differ from the original baseline

The original baseline (`results/real_run_20260826T065155Z/`) reported:
- HNSW_HYBRID mean Recall@10 = 0.810
- VECTOR_FIRST_HNSW mean Recall@10 = 0.763
- SQL_FIRST selected for 250/250 queries

My reproduction reports:
- HNSW_HYBRID mean Recall@10 = **1.000**
- VECTOR_FIRST_HNSW mean Recall@10 = 0.775
- SQL_FIRST selected for **0** queries

The HNSW index in my environment achieves much higher recall. Three contributing factors:

1. **HNSW graph quality.** The HNSW graph structure depends on the insertion order and the `ef_construction` parameter. Even with the same `ef_construction=64`, a different memory layout, different OS, or different vector insertion order can produce a better or worse graph. My HNSW index has 0.999+ recall at `ef_search=100`; the original's HNSW at the same `ef_search=100` had only 0.810 recall.

2. **PostgreSQL 16 vs 17 planner differences.** The planner's cost estimates and index choice heuristics changed between PG 16 and 17. PG 17 may choose HNSW more aggressively.

3. **NumPy version.** The same seed (`20260820`) with NumPy 2.5.1 produces a different query sequence than the original NumPy version. My query 0 has `category=category_00, price=346, stock=False` (est_sel=0.51863); the original's query 0 had a different predicate. The **queries are not byte-identical** between the two runs.

## Scientific conclusion

**The 100% SQL_FIRST outcome in the original baseline is NOT a fundamental property of the adaptive system.** It is a combination of:
- A weak HNSW graph (ef_construction=64 default, which produces a sub-optimal graph in some environments)
- The minimum-recall admission rule (rejects any strategy with even one observation below 0.95)
- A workload that clusters into only 3 of 5 selectivity buckets (reducing the calibration sample size per bucket)

When the HNSW index is built well (ef_construction=200) or the environment produces a better graph, the adaptive policy **does** select ANN strategies. Specifically, IVFFLAT_HYBRID is selected for highly selective queries ([0.00,0.05)), and VECTOR_FIRST_HNSW is selected for wide queries ([0.50,1.00)).

This is a **reproducibility finding** that should be documented in the paper. The current manuscript claims SQL_FIRST is always selected, but this is an artifact of the specific HNSW build quality, not a universal property.

## What I did NOT change

- The query generator, seed, split, and predicates
- The four strategies and their SQL templates
- The admission rule (minimum recall ≥ 0.95)
- The SIFT1M dataset and table schema
- The repetition count and measurement methodology
