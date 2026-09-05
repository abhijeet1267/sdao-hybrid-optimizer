# REPRODUCE.md

This document accompanies the SDAO paper:
**"A Selectivity-Driven Adaptive Strategy-Selection Framework with Recall-Aware Admission for Hybrid SQL–Vector Databases"** (IEEE submission, `final/paper/ieee/main.pdf`, 6 pages).

It describes how an independent party can **verify** the paper's reported numbers from the frozen artifacts already on disk, and how to **build** the IEEE PDF from the LaTeX source. It is **not** a recipe for re-running the benchmarks — those artifacts are frozen and must not be regenerated.

---

## 1. What you can verify (no re-running required)

All quantitative claims in the paper are derived from the frozen artifacts under `final/results/` and the frozen configuration `final/frozen_configuration.yaml`. You can verify the paper's numbers by reading these artifacts directly:

| Paper artifact | Source artifact |
|---|---|
| Table I — Headline results (latency, Recall@10, 95% bootstrap CIs) | `final/results/tables/main_summary.csv` |
| Table II — Admission policy comparison | `final/results/tables/policy_table.csv` |
| Table III — Selection counts by selectivity bucket | `final/results/tables/bucket_table.csv` |
| Table IV — Vector-First HNSW candidate-budget sweep | `final/results/tables/budget_table.csv` |
| Table V — Multi-seed Recall@10 | `final/results/tables/seed_table.csv` |
| Figures 1–8 (decision flow, per-query scatter, bucket selection, latency/recall Pareto, calibration size, safety-coverage, parameter sensitivity, plan verification) | `final/figures/*.pdf` and `*.png` |
| Recall@10 reference construction (brute-force exact L2 on the same 200 000-vector subset) | `final/results/main_run/raw_per_execution.csv` (column `recall@10`, `strategy` = `brute_force`) |
| Calibration / held-out disjointness (125 ∩ 125 = ∅) | `final/results/main_run/calibration_map.json` (query IDs) |
| Plan verification (intended vs. actual access path) | `final/results/main_run/plan_verification.csv` |
| 9 original-baseline SHAs preserved bit-for-bit | `final/audit/original_artifact_shas.json` vs. `results/real_run_20260826T065155Z/` |

---

## 2. Environment that produced the frozen numbers

| Component | Version / value |
|---|---|
| OS | macOS 14.6 (Apple silicon) |
| PostgreSQL | 17.10 (Homebrew) |
| pgvector | 0.8.x |
| SIFT1M subset | 200 000 vectors, 128 dimensions, L2 distance |
| k | 10 |
| `ef_construction` | 200 (deliberately raised from the original 64 — see §2-F of `final/audit/IEEE_FORMAT_FINAL_REPORT.md`) |
| `ef_search` | 100 |
| IVFFlat `lists` / `probes` | 100 / 1 |
| Vector-First HNSW candidate budget | 100 (sensitivity sweep 50–1000, Table IV) |
| Warm-cache protocol | yes (single warm-up pass per strategy, 3 measurement reps, no cold-cache control) |
| Recall target | 0.95 |
| Calibration set | 125 queries, disjoint from held-out |
| Held-out set | 125 queries, 3 reps × 4 strategies = 375 rows/strategy |
| Seeds | main run seed `20260820`; multi-seed sweep `20260820`, `20260822`, `20260823` |
| Admission policy (frozen) | min-recall (admit iff min observed Recall@10 ≥ 0.95 on calibration) |

These are the values used in the paper. The full frozen config is at `final/frozen_configuration.yaml` and the machine-readable copy is at `final/reproducibility/final_config.json`.

---

## 3. Verifying the IEEE PDF

### 3.1 Build the IEEE PDF from source

```bash
cd final/paper/ieee
/opt/homebrew/bin/tectonic -X compile main.tex
```

This produces `final/paper/ieee/main.pdf`. On a TeX-enabled host without `tectonic`, an equivalent sequence is `pdflatex main.tex` ×2 + `bibtex main` + `pdflatex main.tex` ×2.

**The build must use the figures that already exist in `final/figures/`** (copied to `final/paper/ieee/figures/` during the IEEE conversion). Do not regenerate figures.

### 3.2 Run the validators

```bash
# Check the IEEE PDF (frozen-text, SHA-256, page count, figures, tables, references)
python3 final/scripts/validate_ieee.py

# Check the 7p reproducibility report (figures + CSV integrity + original SHAs)
python3 final/scripts/validate.py
```

A successful run of each prints `=== ALL VALIDATION CHECKS PASSED ===`.

The two validators are **read-only** and **non-destructive**:
- `validate_ieee.py` opens the PDF with PyMuPDF, extracts text, and compares it against the frozen values in `final/results/tables/`. It does not write to the PDF.
- `validate.py` checks the 7p PDF, the 8 figure files, the 5 aggregate tables, the 9 original-baseline SHAs, and the per-table cell values. It does not modify any artifact.

If either validator reports a failure, **do not** edit the paper to make it pass — the failure indicates a real drift and should be reported back to the authors.

### 3.3 Verify the original-baseline SHA-256s

```bash
cd results/real_run_20260826T065155Z
shasum -a 256 *
```

Every hash must match the entry in `final/audit/original_artifact_shas.json`. The audit's `validate.py` performs this comparison automatically and exits non-zero on any mismatch.

---

## 4. What is **not** required (and must not be done)

- **Do not re-run the benchmark.** The frozen artifacts are the source of truth. Re-running will not reproduce the exact numbers (timing is environment-dependent; HNSW construction is not bit-exact across libc).
- **Do not rebuild the 200K-vector SIFT1M subset** or the HNSW index. The frozen config used `ef_construction=200`, which differs from the original `pgvector/pgvector:0.8.5-pg16` baseline's `ef_construction=64`; rebuilding the index changes the recall numbers.
- **Do not change the admission policy** or the recall target. The frozen policy is `min_recall @ 0.95`; changing it invalidates the head-to-head comparison with the four alternative policies reported in Table II.
- **Do not change the seeds** (`20260820`, `20260822`, `20260823`). The multi-seed result is the qualitative ordering VFH < 0.95 < hybrids = 1.0; changing seeds invalidates the cross-seed comparison.

---

## 5. Mapping paper claims → source files

- **Abstract numbers** (Adaptive = 15.10 ms, VFH mean recall 0.83, CI [0.77, 0.88], 100/125 admitted, 0% safety violations): `final/results/tables/main_summary.csv` rows for `SQL_FIRST`, `HNSW_HYBRID`, `IVFFLAT_HYBRID`, `VECTOR_FIRST_HNSW`, `Adaptive`.
- **VFH min Recall@10 = 0.00**: `final/results/main_run/per_query.csv` filtered to `strategy == VECTOR_FIRST_HNSW`, `recall@10` column.
- **Budget sweep (0.701 → 0.942)**: `final/results/tables/budget_table.csv`.
- **Multi-seed (0.829, 0.835, 0.776)**: `final/results/tables/seed_table.csv`.
- **Policy admission counts (48 / 52 / etc.)**: `final/results/tables/policy_table.csv`.
- **Bucket selection totals (24 / 25 / 23 / 29 / 24 → 125)**: `final/results/tables/bucket_table.csv` row sums.
- **`enable_indexscan = off` for SQL_FIRST**: `final/audit/ann_parameter_audit.md` line 31 (documented choice, not a bug).
- **ef_construction = 200 vs. original 64 disclosure**: `final/frozen_configuration.yaml` (in-line comment) and `final/audit/IEEE_FORMAT_FINAL_REPORT.md` §2-F.

---

## 6. File layout (frozen; do not modify)

```
final/
├── paper/
│   ├── main.pdf                (7p reproducibility report, frozen)
│   └── ieee/
│       ├── main.tex            (IEEEtran source, frozen)
│       ├── main.pdf            (IEEE 6p PDF, frozen SHA-256)
│       ├── references.bib      (12 entries, TelegraphCQ[3] / ACORN[12] verified)
│       └── figures/            (8 PDF + 8 PNG figures, copied from final/figures/)
├── figures/                    (8 PDF + 8 PNG figures, source of truth)
├── tables/                     (legacy 7p-paper table copies)
├── frozen_configuration.yaml   (frozen; consistent with main.tex)
├── reproducibility/
│   ├── final_config.json       (machine-readable frozen config, 40 keys)
│   └── smoke_config.json
├── results/
│   ├── main_run/               (frozen main run, 125 held-out × 3 reps × 4 strategies)
│   ├── sweep_ef*/              (frozen parameter sweep, 12 combos)
│   ├── budget_*/               (frozen budget sweep, 5 budgets)
│   ├── seed_*/                 (frozen multi-seed runs, 3 seeds)
│   └── tables/                 (5 aggregate tables, source of all numbers in the paper)
├── audit/
│   ├── original_artifact_shas.json   (9 SHAs of results/real_run_20260826T065155Z/)
│   ├── db_config.json
│   ├── admission_rule_analysis.md
│   ├── ann_parameter_audit.md
│   ├── workload_audit.md
│   ├── baseline_reproduction_report.md
│   ├── final_claim_evidence_matrix.md
│   ├── final_numeric_audit.md
│   ├── project_inventory.md
│   ├── FINAL_FREEZE_REPORT.md
│   ├── IEEE_FORMAT_FINAL_REPORT.md
│   ├── POST_EDIT_FINAL_REPORT.md
│   └── SUBMISSION_AUDIT_CHANGELOG.md
└── scripts/
    ├── validate.py             (7p-paper + SHA + table-cell validator)
    ├── validate_ieee.py        (IEEE 6p + frozen-numbers validator)
    ├── render_pdf.py           (builds the 7p paper, NOT the IEEE PDF)
    ├── make_figures.py         (rebuilds the 8 figures from frozen CSVs)
    ├── pdf_to_png.py           (page-rasterizer used by render_pdf.py)
    ├── run_calibration.py      (rebuilds calibration CSV, NOT a re-run of queries)
    ├── final_experiment.py     (entry point for the full pipeline)
    ├── compare_policies.py     (rebuilds policy_table.csv)
    ├── analyze_results.py      (rebuilds the 5 aggregate tables)
    ├── analyze_workload.py     (rebuilds the workload summary)
    ├── build_ivfflat_200k.py   (one-time IVFFlat index builder)
    ├── capture_db_config.py    (one-time DB config snapshot)
    ├── param_sweep.sh          (driver for sweep_ef*/)
    ├── budget_sweep.sh         (driver for budget_*/)
    └── multi_seed.sh           (driver for seed_*/)
```

The root-level `REPRODUCIBILITY_REPORT.md` (sibling of this file) is an earlier, broader reproducibility investigation from August 2026 and is **not** what the paper points to.

---

## 7. Quick verification recipe (≈30 seconds)

```bash
cd /path/to/MyProject
( cd results/real_run_20260826T065155Z && shasum -a 256 * | sort -k2 ) | \
    sort -k2 | \
    diff - <(python3 -c "import json; [print(f'{h}  {n}') for n,h in json.load(open('final/audit/original_artifact_shas.json'))['files'].items()]" | sort -k2) \
    && echo "[OK] 9 original SHAs preserved"
python3 final/scripts/validate.py          # → ALL CHECKS PASSED
python3 final/scripts/validate_ieee.py     # → ALL CHECKS PASSED
```

If all three commands succeed, the paper's numbers are consistent with the frozen artifacts on disk.

