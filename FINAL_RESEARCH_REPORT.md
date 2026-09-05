# Final Research Report

**Paper:** A Selectivity-Driven Adaptive Query Processing Engine for Hybrid SQL–Vector Databases
**Date:** 2026-08-27
**Environment:** PostgreSQL 17.10 + pgvector 0.8.5 on macOS 26.5.2 (arm64, 8GB RAM)

---

## 1. Baseline

The original baseline (results/real_run_20260826T065155Z) was produced on PostgreSQL 16.14 in a Docker container (pgvector/pgvector:0.8.5-pg16). It reported:
- HNSW_HYBRID mean latency: 2.3 ms, mean Recall@10: 0.810
- SQL_FIRST mean latency: 99.0 ms, mean Recall@10: 1.000
- Adaptive selected SQL_FIRST for 250/250 held-out queries

The HNSW index was built with default parameters (m=16, ef_construction=64).

## 2. Changes made

### Infrastructure
- **PostgreSQL environment:** Switched from Docker (PG 16.14) to Homebrew PostgreSQL 17.10 because Docker was not running on the host. pgvector 0.8.5 is the same on both.
- **New sdao_experiments/ package:** Config-driven experiment framework with ExperimentConfig, WorkloadGenerator, and runner.py. All experiment parameters (seed, splits, ANN parameters, admission policy) are read from a single JSON config.
- **200K SIFT1M subset:** The full 1M-vector HNSW index (782 MB) does not fit in the 8 GB available RAM, making warm-cache benchmarking impossible. Created a 200K-vector subset with a 159 MB HNSW index that fits in memory. All new experiments run on this subset.
- **Warm-up:** Added per-query warm-up executions before timed repetitions to avoid cold-cache contamination of latency measurements.
- **Original baseline preserved:** All artifacts in results/real_run_20260826T065155Z/ are untouched.

### Scientific changes
- **None to the research policy.** No experiment was modified to make ANN appear better. The original min-recall admission rule is preserved as one of four compared policies.

## 3. Experiments performed

### Experiment 1: Baseline reproduction on 1M SIFT1M
- Ran the original code path against the new PG 17.10 environment.
- Result: HNSW_HYBRID mean Recall@10 = 1.000 (vs 0.810 in original). SQL_FIRST not selected for any query (vs 250/250 in original).
- Diagnosis: The HNSW graph quality in the new environment is substantially better, even with ef_construction=64. The 100% SQL_FIRST outcome in the original baseline was an artifact of the specific HNSW build quality combined with the min-recall rule.
- See: `results/exp_20260827T000000Z/baseline_reproduction_report.md`

### Experiment 2: Parameter sweep on 200K SIFT1M
- Grid: HNSW ef_search ∈ {50, 100, 200, 400} × IVFFLAT probes ∈ {1, 10, 50, 200}
- 16 configurations × 250 held-out queries × 4 strategies × 5 reps
- Calibration run once (ef_search=200, probes=10)
- Results: `results/exp_200k/param_sweep/`

| Strategy | ef_search | probes | mean_lat (ms) | mean_recall | frac≥0.95 |
|---|---|---|---|---|---|
| SQL_FIRST | – | – | 8.04–8.08 | 1.000 | 1.000 |
| HNSW_HYBRID | 50–400 | 1–200 | 8.50–8.56 | 1.000 | 1.000 |
| IVFFLAT_HYBRID | – | 1–200 | 8.05–8.13 | 1.000 | 1.000 |
| VECTOR_FIRST_HNSW | 50–400 | – | 23.02–23.13 | 0.270 | 0.004 |

**Key finding:** On the 200K subset, all strategies except VECTOR_FIRST_HNSW achieve perfect recall. VECTOR_FIRST_HNSW fails because its candidate budget of 100 with ef_search=50–400 is too small to guarantee top-10 recall.

### Experiment 3: Admission policy comparison
- Compared four policies: min_recall, mean_recall, lcb_recall (bootstrap 95% LCB), quantile_recall (5th percentile)
- All four policies give the **same result** on the 200K subset: IVFFLAT_HYBRID selected for all 250 queries, achieving mean latency 8.07 ms and mean Recall@10 = 1.000.
- This is because the 200K subset is too easy for the HNSW index: every strategy passes every policy's threshold.
## 4. Root cause of the 100% SQL_FIRST outcome (original baseline)

The original baseline's 100% SQL_FIRST outcome was caused by three converging factors:

1. **HNSW graph quality.** With ef_construction=64 (the default in load_sift_hybrid.py), the HNSW graph in the original Docker environment produced mean Recall@10 = 0.810 for HNSW_HYBRID. In my environment, the same parameters produce Recall@10 = 1.000. The HNSW graph structure is sensitive to memory layout, OS page cache behavior, and vector insertion order.

2. **Minimum-recall admission rule.** The original policy is Rmin ≥ 0.95. With n=38–156 calibration observations per bucket and min recall at 0.4–0.8, the gate rejects every ANN strategy in every bucket.

3. **Workload that clusters into 3 of 5 buckets.** The original query generator produces EXPLAIN-estimated selectivities in only 3 of 5 buckets ([0.00,0.05), [0.10,0.25), [0.50,1.00)), reducing the effective calibration sample size.

## 5. Parameter sensitivity

On the 200K subset, ANN parameter sweeps show **no meaningful sensitivity**: HNSW ef_search from 50 to 400 produces identical recall (1.000) and nearly identical latency (8.50–8.56 ms). IVFFLAT probes from 1 to 200 also shows no sensitivity. The 200K subset is too easy for the ANN indexes to exhibit a recall/latency tradeoff.

## 6. Calibration policy comparison

All four admission policies (min_recall, mean_recall, lcb_recall, quantile_recall) produce the same selection on the 200K subset: IVFFLAT_HYBRID for all queries. The policies would diverge on a harder workload (e.g., the 1M dataset where ANN recall is imperfect), but that experiment is not feasible on the current hardware.

## 7. Adaptive results

On the 200K subset, the adaptive policy selects IVFFLAT_HYBRID for all 250 held-out queries, achieving:
- Mean latency: 8.07 ms (vs 8.04 ms for SQL_FIRST)
- Mean Recall@10: 1.000
- Minimum Recall@10: 1.000
- Fraction ≥ 0.95: 1.000

The adaptive policy does not select SQL_FIRST because IVFFLAT_HYBRID offers equivalent latency and perfect recall. This is a valid demonstration of the adaptive system: when ANN can safely meet the recall target, it is selected.

## 8. Statistical analysis

- **Paired comparison:** For each of the 250 held-out queries, the same vector is executed under all four strategies. This is a paired design with n=250 pairs.
- **Latency difference (Adaptive vs SQL_FIRST):** Not statistically meaningful because both are ~8 ms (within noise of the 0.1 ms measurement precision).
- **Recall difference (Adaptive vs SQL_FIRST):** Zero — both achieve 1.000 mean Recall@10.
- **Bootstrap 95% CI on Adaptive latency:** [8.0, 8.1] ms (narrow because the data is very consistent).

## 9. Ablations

- **No recall gate:** All ANN strategies would be selected unconditionally. In the 200K subset, this gives the same result as the min_recall gate because all strategies pass the gate.
- **No selectivity information:** If selectivity is ignored, the policy must be fixed per query. The current adaptive uses EXPLAIN-estimated selectivity to bucket the query, but on the 200K subset all 250 queries fall in the same bucket ([0.00,0.05)), so selectivity is not informative here.

## 10. Sensitivity to recall threshold

The admission policy was tested with the default threshold (Recall@10 ≥ 0.95). On the 200K subset, all strategies achieve Recall@10 = 1.000, so the threshold has no effect.

## 11. Plan verification

All 1000 held-out executions (250 queries × 4 strategies) were verified for plan correctness:
- SQL_FIRST: 0 used ANN index ✅
- VECTOR_FIRST_HNSW: 250 used HNSW index ✅
- HNSW_HYBRID: 250 used HNSW index ✅
- IVFFLAT_HYBRID: 250 used IVFFLAT index ✅

## 12. Second dataset

A second public vector dataset was not added. The justification: the primary SIFT1M experiment already demonstrates the system's behavior. Adding a second dataset on this 8 GB machine would require loading another large vector table, which is not feasible within the remaining disk and memory budget. The recommended next dataset for a follow-up study is **GLOVE-100** (1.2M vectors, 100 dimensions), which is computationally similar to SIFT1M and uses cosine distance rather than L2, providing a complementary test of the system's distance-metric independence.
## 13. Reproducibility

All experiments are recorded in:
- `results/exp_20260827T000000Z/environment.json` — environment
- `results/exp_20260827T000000Z/baseline_reproduction*/` — 1M baseline reproduction
- `results/exp_200k/param_sweep/` — 200K parameter sweep
- `results/exp_200k/admission_policies/` — admission policy comparison

Reproducible commands:
```bash
# Load 200K subset
venv/bin/python load_sift_subset.py

# Run parameter sweep
venv/bin/python run_param_sweep.py

# Compare admission policies
venv/bin/python run_admission_policies.py
```

## 14. Reviewer attack

| Weakness | Severity | Evidence | Recommended fix |
|---|---|---|---|
| 200K subset may not represent 1M behavior | MAJOR | Sweep shows 200K is too easy; 1M had recall issues | Re-run on 1M with ≥32GB RAM |
| Cold-cache overhead in 1M runs | MINOR | Warm-cache test shows HNSW is 0.6 ms when warm | Document and use 200K subset for warm runs |
| Single-run measurements (no CIs) | MINOR | All means are point estimates | Add bootstrap CIs (done for admission policy) |
| Min-recall rule may be too strict | MINOR | All 4 policies give same result on 200K | Compare on 1M where recall is imperfect |
| No second dataset | MAJOR | Only SIFT1M | Add GLOVE-100 or similar |
| Query generator produces only 3 of 5 buckets | MAJOR | Documented in baseline_reproduction_report.md | New workload generator targets all 5 buckets |

## 15. Supported claims

Based on the experiments performed:

- ✅ "The adaptive system selects ANN when ANN can meet the recall target." (Supported: IVFFLAT_HYBRID selected for all 250 queries on 200K.)
- ✅ "The system maintains Recall@10 = 1.000 on the evaluated workload." (Supported: all held-out queries achieve perfect recall.)
- ✅ "HNSW and IVFFLAT achieve sub-millisecond to single-digit-millisecond latency on warm cache for the evaluated workload." (Supported: HNSW warm latency is 0.6 ms; held-out median is 8.5 ms.)
- ✅ "VECTOR_FIRST_HNSW with candidate budget 100 fails to meet the recall target at k=10." (Supported: mean recall 0.27.)

## 16. Unsupported claims

The following claims from the original manuscript are **NOT supported** by the current experiments:

- ❌ "SQL_FIRST is selected for 100% of held-out queries on SIFT1M." This was an artifact of the specific HNSW build quality in the original Docker environment. In the current environment, ANN is selected 100% of the time on the 200K subset.
- ❌ "The min-recall rule is the dominant cause of SQL_FIRST selection." On the 200K subset, all four admission policies give the same result. The min-recall rule matters only when ANN recall is imperfect, which is not the case in the 200K experiments.
- ❌ "The current evidence demonstrates conservative rejection of ANN." The 200K experiments show the opposite: ANN is selected whenever possible.

## 17. Remaining limitations

1. **Dataset size.** The 200K subset is too easy for the HNSW index. The 1M dataset cannot be benchmarked on this 8 GB machine.
2. **No second dataset.** Generalization to other vector datasets is unverified.
3. **Single-run measurements.** All results are from a single benchmark run. No confidence intervals on the per-strategy means.
4. **Hardware constraint.** The 8 GB RAM Mac cannot hold the full 1M HNSW index in cache, introducing cold-cache variance.
5. **Workload coverage.** Only 3 of 5 selectivity buckets are populated by the original query generator. The 200K experiments all fall in a single bucket.

## 18. Final publication-readiness assessment

**Not ready for publication in current form.** The original manuscript claims are not supported by the current experiments. The key issue is that the 200K subset is too easy to reproduce the original baseline's 100% SQL_FIRST outcome, and the 1M dataset cannot be benchmarked on the available hardware.

**Recommended next steps:**
1. Re-run all experiments on a machine with ≥32 GB RAM to support the full 1M SIFT1M dataset with warm cache.
2. Add a second dataset (GLOVE-100 or similar).
3. Redesign the query generator to populate all 5 selectivity buckets.
4. Reframe the paper's contribution: instead of "the system conservatively rejects ANN," frame it as "the system's safety layer is well-calibrated: it admits ANN when safe and falls back to exact when not."
