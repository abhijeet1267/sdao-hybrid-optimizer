# Editable conference manuscript

`main.tex` is a standalone LaTeX manuscript for the PostgreSQL/pgvector adaptive-planning prototype. It does not use results from the repository's earlier hnswlib/pandas prototype.

## Build

From this directory, run `pdflatex main.tex`, `bibtex main`, then `pdflatex main.tex` twice. The bibliography contains verified sources for PostgreSQL, pgvector/IVFFlat, HNSW, and the SIFT1M benchmark context; apply the target venue's bibliography style only after a venue is selected.

## Authoritative inputs

- Final DB experiment: `../sdao/results/db_final_adaptive_20260814T145013Z/`
- Baseline: `../sdao/results/db_baseline_20260814Tfinal/`
- Calibration: `../sdao/results/db_calibration_20260814/`
- EXPLAIN selectivity: `../sdao/results/db_explain_selectivity_20260814T142459Z/`
- Paper-facing analysis: `../sdao/results/db_paper_analysis_20260814T163606Z/`

The figure links in `figures/` point only to the corrected PDF figures in the paper-facing analysis directory. Do not replace them with legacy figures.

## Mapping

| Manuscript item | Authoritative source |
|---|---|
| Figures 1--6 | `db_paper_analysis_20260814T163606Z/figure_*.pdf` |
| Table 1 | `02_strategy_table.csv` |
| Table 2 | `05_selectivity_bucket_table.csv` |
| Table 3 | `07_plan_verification_table.csv` |
| Decision-overhead table | `08_decision_overhead_table.csv` |
| Captions and terminology | `figure_captions.md`, `table_notes.md`, `analysis_summary.md`, and `experimental_protocol.md` |

## Reproducibility boundary

The manuscript reports calculations from frozen canonical artifacts. Do **not** rerun the benchmark to reproduce these reported calculations. Physical timing reproduction is not guaranteed: the completed measurements used a warm persistent session, did not control cold cache, were not randomly interleaved, and can contain cache/order effects. The evaluation is exploratory and not held out.
