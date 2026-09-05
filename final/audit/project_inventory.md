# Project Inventory (Phase 0)

**Generated:** 2026-08-31
**Protocol:** SDAO Paper Complete Resolution Protocol
**Scope:** Catalog every artifact in the project, classify reproducibility, and identify provenance for the originally reported paper.

---

## 1. Top-level layout

```
/Users/abhijeetmiskin/AppData/MyProject/
├── paper/                        # The original paper source
├── sdao/                         # Original SDAO prototype code (older revision)
├── sdao_experiments/             # Config-driven experiment framework (newer)
├── sql/                          # SQL schema / index DDL
├── tests/                        # Unit tests
├── tools/                        # Investigation scripts
├── dataset/sift/                 # SIFT1M vectors (sift_base.fvecs etc.)
├── results/                      # All experiment outputs (raw CSVs, summaries)
├── results/repro_investigation/  # 1M baseline reproduction on PG17.10
├── results/real_run_20260826T065155Z/  # ORIGINAL 1M baseline (PG16.14 Docker)
├── results/exp_20260827T000000Z/       # 1M reproduction + 200K first pass
├── results/exp_200k/                    # 200K subset experiments + 16-config param sweep
├── FINAL_RESEARCH_REPORT.md             # Last summary of state
├── FINAL_RESULTS.csv, FINAL_RESULTS.json
├── FINAL_EXPERIMENT_MANIFEST.json       # Experiment provenance manifest
├── REPRODUCIBILITY_REPORT.md            # Reproducibility notes
├── benchmark_hybrid_optimizer.py        # Legacy benchmark driver
├── generate_queries.py, build_index.py, load_sift_subset.py
├── run_experiment.py, run_admission_policies.py, run_param_sweep.py
└── final/                               # NEW: this protocol's deliverables
```

## 2. Database state (current)

- PostgreSQL 17.10 (Homebrew), pgvector 0.8.5
- Database `sdao`, host localhost:5432
- Table `sift_hybrid` (1,000,000 rows) + `sift_hybrid_200k` (200,000 rows)
- Indexes on sift_hybrid: category/price/in_stock btree, embedding HNSW, embedding IVFFLAT
- Default `hnsw.ef_search=100`, `ivfflat.probes=10` (per session, baseline)
- HNSW build params: m=16, ef_construction=200 (current); m=16, ef_construction=64 (original baseline)

## 3. Files that produced the originally reported numbers

The original paper PDF (`paper/main.pdf` / `paper/main_upgraded.pdf`) was produced from:
- `paper/main.tex` / `paper/main_upgraded.tex`
- `paper/references.bib`
- Figures in `paper/figures/`
- Tables in `paper/tables/`

Numerical results came from `results/real_run_20260826T065155Z/`.

## 4. Files used by current `sdao_experiments/` framework

| File | Purpose |
|---|---|
| `sdao_experiments/config.py` | Single ExperimentConfig dataclass. Seeds, splits, ANN params, admission policy. |
| `sdao_experiments/workload.py` | WorkloadGenerator: bucket-targeted predicate generation with EXPLAIN probes. |
| `sdao_experiments/runner.py` | Config-driven benchmark runner: calibration → admission → held-out. |
| `sdao_experiments/baseline_repro.py` | Earlier reproduction script. |
| `run_experiment.py` | Top-level driver. |
| `run_admission_policies.py` | Compares 4 admission policies. |
| `run_param_sweep.py` | Sweeps HNSW ef_search × IVFFLAT probes. |

## 5. Files preserved (must NOT be modified)

The original baseline artifacts in `results/real_run_20260826T065155Z/` MUST remain untouched.

## 6. Dependency status

All required packages (numpy, pandas, psycopg2, scipy, scikit-learn, matplotlib, seaborn) are present in `/Users/abhijeetmiskin/AppData/MyProject/venv/`.

## 7. Reproducibility classification

| Artifact | Reproducible today? | Notes |
|---|---|---|
| Original 1M baseline (real_run_20260826T065155Z) | NO (different env) | PG 16.14 Docker container not currently running. |
| 1M reproduction on PG 17.10 (repro_investigation/canonical_1M_run) | YES | Different HNSW recall (0.999 vs 0.810). |
| 200K subset experiments (exp_200k) | YES | Recall 1.0 across all params -- workload too easy. |

## 8. Original reported numbers (preserved verbatim)

From `results/real_run_20260826T065155Z/summary.csv`:

| Strategy | Mean ms | Median ms | P95 ms | Mean Recall@10 | Frac ≥ 0.95 |
|---|---|---|---|---|---|
| SQL_FIRST | 99.04 | 94.71 | 179.04 | 1.000 | 1.000 |
| VECTOR_FIRST_HNSW | 3.47 | 2.36 | 9.18 | 0.763 | 0.656 |
| HNSW_HYBRID | 2.28 | 1.42 | 3.80 | 0.810 | 0.700 |
| IVFFLAT_HYBRID | 5.74 | 4.74 | 13.93 | 0.813 | 0.352 |
| Adaptive | 99.04 | 94.71 | 179.04 | 1.000 | 1.000 |

## 9. Gaps in the original paper

1. **No held-out validity** -- 250/250 SQL_FIRST selected by adaptive policy.
2. **No ANN success story** -- paper had to admit ANN was rejected.
3. **No statistical analysis** -- no CIs, no significance tests.
4. **No sensitivity analysis** -- no parameter sweeps shown.
5. **No multi-seed** -- single run.
6. **No second dataset** -- SIFT1M only.
7. **Bucket coverage is sparse** -- only 3 of 5 buckets populated.
8. **No ablation of admission rules** -- only the min-recall rule tested.
9. **No discussion of when safety rule is over-conservative.**
10. **Workload generator design not defended.**