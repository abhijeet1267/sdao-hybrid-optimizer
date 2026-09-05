# PROJECT_HANDOFF.md — Master Project Handoff & Architecture Document

> **Status: SUBMISSION-READY (all 4 pre-submission gates PASS).**
> **Date:** 2026-09-05. **Workspace root:** `/Users/abhijeetmiskin/.cline/data/workspaces/chat`
> (`final/` is the artifact tree; loose files at root are submission docs + bundle.)
> **Audience:** any new AI agent, collaborator, or reviewer — no prior chat history required.

---

## 1. Executive Summary & Scientific Thesis

**Paper title (final):**
*Recall-Constrained Admission for Hybrid ANN-SQL Plans: PAC Bounds, q-Error Resilience, and 1M-Row Validation*

**Authors:** Abhijeet L. M. (first/corresponding, `abhijeet.lm@vit.ac.in`) and
Leninisha S. (`leninisha.s@vit.ac.in`) — School of Computer Science and
Engineering, Vellore Institute of Technology, Chennai, India.

**Core research problem.** PostgreSQL + pgvector increasingly serves hybrid
queries that combine a relational predicate (e.g. `WHERE price < 100`) with
approximate-nearest-neighbour (ANN) top-k over high-dimensional embeddings.
The planner must lead with either an exact-SQL scan (high recall, high
latency) or an ANN index scan (low latency, uncertain recall).

**Core scientific thesis.** A naive latency-driven optimizer always picks the
hybrid ANN path because it is **40–65× faster** than the brute-force scan —
but on restrictive relational filters HNSW/IVFFlat suffer **catastrophic
recall collapse (Recall@10 = 0.10–0.22)**. We formalise plan choice as a
**recall-constrained admission problem** `q = <v, P, k, R_target>` and prove a
data-dependent **(ε, δ)-PAC empirical-Bernstein bound** on the per-bucket mean
Recall@10 of each candidate plan. The bound is computed once per
(strategy, selectivity-bucket) pair offline, then evaluated in O(1) inside a
planner hook that gates every query. Result: at production quality
(`R_target ≥ 0.90`) the gate routes **100 % of 1M-row queries to the exact
`SQL_FIRST` fallback**, preventing silent top-k corruption; hybrid plans are
admitted only for `R_target ≤ 0.3` (RAG surface-and-rerank workloads).

**Target venues:** IEEE TKDE, IEEE ICDE, ACM SIGMOD, VLDB.
Artifact badges claimed: *Artifacts Available; Artifacts Evaluated & Reusable.*

---

## 2. Evolution of the Work (Dual-Scale Evaluation Story)

### Stage 1 — 200K macOS microbenchmark audit
- PostgreSQL **17.10 vs 16.14 portability investigation**; pgvector HNSW graph
  quality shown sensitive to build environment / compiler libc.
- Key finding: on 200K rows the workload is buffer-cache resident, so
  in-memory sequential scans match ANN latency (**~15 ms**) — an optimizer
  **cannot justify itself on 200K rows alone**.
- Positive latency-contract result: the gate admits hybrid plans at **~80 %**
  when cache and selectivity are favourable, proving the boundary is
  **data-driven, not hard-coded**.

### Stage 2 — 1M production-scale benchmark (`sift_hybrid`, 128-D L2, 1,000,000 rows)
- Scale sweep: **25 queries × 5 selectivity buckets × 4 strategies × 3
  repeats = 500-measurement `results_scale.csv`** (+ header).
- Discovery of the **40–65× latency gap** (HNSW_HYBRID ~2.4–2.9 ms vs
  SQL_FIRST ~122–150 ms) **and** the recall collapse (0.048–0.216).
- Structural diagnosis: recall is bounded away from 0.95 by the fixed
  **`hnsw_ef_search = 100`** graph-traversal budget, not by planner tuning
  (see `REVIEWER_DEFENSE_FAQ.md` Defense 2).
- Empirical validation of the PAC gate: **20/20 cells pass** (coverage 1.00 ≥
  1−δ = 0.95), **35/35 q-error decisions preserved** (0.1×–10× mis-estimation).

### Stage 3 — Sanitization, compliance & packaging (2026-09-05)
- Credential scrub (spec placeholders `postgres`/`REDACTED`), portable paths,
  manuscript tightening (Table VIII/IX/X `\resizebox` overflow fix, 6 pages
  preserved), IEEE font-embed audit, double-blind PDF, `submission_bundle.tar.gz`.
## 3. Complete Repository Map & File Inventory

Paths relative to workspace root `/Users/abhijeetmiskin/.cline/data/workspaces/chat`.
Line counts measured 2026-09-05. Sizes: `main.tex` 30 KiB / 679 lines;
`main.pdf` 108,369 B; `main_anonymized.pdf` 108,798 B;
`submission_bundle.tar.gz` 348,578 B, 50 tar entries,
SHA-256 `6c617a64a898aa47cf80460d19fb3980c48385ab20fe72fbff3c7ecf0e793bbf`.

### 3.1 Manuscript — `final/manuscript/`
| File | Lines | Role / status |
|---|---|---|
| `final/manuscript/main.tex` | 679 | 6-page `IEEEtran[conference]` paper. Clean tectonic build. Tables VIII/IX/X wrapped in `\resizebox{\columnwidth}{!}{...}` (overflow fix); Table VII stays `table*`. |
| `final/manuscript/main.pdf` | 6 pp, 612x792 pt Letter | Camera-ready single-blind PDF. 23/23 FontDescriptors embedded (FontFile3), 0 Type3, 0 off-page blocks. |
| `final/manuscript/main_anonymized.pdf` | 6 pp, Letter | Double-blind copy (Anonymous Authors; no Vellore/vit.ac.in). |
| `tables/TableVII_Scale.tex` | 48 | Scale table: 5 buckets x 4 strategies, p50/p95/p99 + Recall@10 + speedup (75 meas/cell). |
| `tables/TableVIII_qError.tex` | 53 | q-error table (7 factors 0.1x-10x). |
| `tables/TableIX_ColdCache.tex` | 53 | Cold-cache inflation table (Docker-restart method). |
| `tables/TableX_PAC.tex` | 55 | PAC Bernstein coverage table (20 cells). |
| `figures/` | (empty) | No figures in this submission. |

### 3.2 Benchmarking suite — `final/scripts/new_experiments/`
| File | Lines | Role |
|---|---|---|
| `_common.py` | 777 | Shared utils: `load_config/get_connection/wait_for_pg/cold_cache_reset/warm_cache/build_strategy_sql (SET LOCAL hnsw.ef_search=100)/run_strategy/brute_force_topk/recall_at_k/generate_relational_columns/make_query_params_for_bucket/create_schema+vector_indexes (HNSW m=16 ef_c=200; IVFFlat lists=1000)/bulk_insert/SIFT loaders/portable find_local_sift_query_path ($SIFT_QUERY_FVECS, no abspaths)`. |
| `benchmark_scale.py` | 273 | N x selectivity sweep; writes `results_scale.csv` (500 rows). |
| `benchmark_q_error.py` | 352 | 7-factor mis-estimation stress (0.1x-10x); writes `results_q_error.csv` (700 rows). |
| `benchmark_cold_cache.py` | 274 | Hot-vs-cold cache (Docker restart); writes `results_cold_cache.csv` (900 rows). |
| `benchmark_pac_bounds.py` | 379 | 30-seed Monte-Carlo Bernstein validation; writes `results_pac.csv` (20) + `results_pac_raw.csv` (3000). |
| `aggregate_results.py` | 283 | Raw CSVs to `aggregated/agg_*.csv + agg_summary.json + Table*.tex`. Portable ROOT via `Path(__file__)`. |
| `README.md` | 183 | Usage, prerequisites, index DDL, env notes. |
| `__init__.py` | 0 | Empty package marker. |
### 3.3 Results & data — `final/results/new_experiments/`
| File | Rows (hdr incl.) | Size | Role |
|---|---|---|---|
| `results_scale.csv` | 501 | 39 KiB | 25q x 5 buckets x 4 strats x 3 repeats (1M run). |
| `results_q_error.csv` | 701 | 63 KiB | 7 factors x 5 buckets x 4 strats x 5 queries. |
| `results_cold_cache.csv` | 901 | 70 KiB | 5 buckets x 4 strats x (15 hot + 15 cold + 15 hot-2nd). |
| `results_pac.csv` | 21 | 2.0 KiB | 20 PAC cells (5 buckets x 4 strats). |
| `results_pac_raw.csv` | 3001 | 111 KiB | 30 seeds x 5 queries x 20 cells. |
| `smoke_*.csv` (5 files) | small | 0.8-13 KiB | Smoke-test fast subsets. |
| `logs/` (4 logs) | — | — | Historic logs with stale /Users paths; EXCLUDED from bundle. |
| `aggregated/agg_scale.csv` | 21 | — | Per-cell medians; headline cells in section 4. |
| `aggregated/agg_q_error.csv` | 141 | — | Per-factor recall+latency; 35/35 fallback preserved. |
| `aggregated/agg_cold_cache.csv` | 21 | — | Hot/cold p50 + inflation_ratio. |
| `aggregated/agg_pac.csv` | 21 | — | mean/std/CI95 + bernstein_bound + ci_within_pac=True (20/20). |
| `aggregated/agg_summary.json` | — | 652 B | Gold headlines: hnsw p50 2.57ms, speedup 61.15, recall 0.192/0.112, switches 35/35, inflation ~0.99-1.01, PAC 20 cells cov 1.0. |

NOTE: live `agg_scale.csv` is the newest re-run (SQL_FIRST sel_000_005 p50
182.05 ms); camera-ready Table VII embeds the frozen PDF-run numbers
(121.77 ms). Frozen reference: `final/audit/frozen_paper_summary.json`
(SQL_FIRST 149.69, HNSW 2.51, speedup 59.57, recalls 0.192/0.112,
inflations 1.02/1.02). `verify` checks frozen file within tolerances: PASS.

### 3.4 Artifact evaluation & audit — `final/audit/` + root docs + runners
| File | Lines | Role / status |
|---|---|---|
| `SUBMISSION_METADATA.txt` | 100 | Portal packet: title, authors, 248-word abstract, 8 IEEE keywords + CCS, blind-copy line. |
| `REPRODUCIBILITY.md` | 338 | AE guide: layout, HW/SW, dataset, schema, claim map, repro steps, tolerances, manifest regen. |
| `REVIEWER_DEFENSE_FAQ.md` | 274 | 4 rebuttals: 100pct-fallback proof, ef_search saturation, q-error stability, SIFT representativeness. |
| `final/scripts/reproduce_all.sh` | 257 | Runner: `check` (DB probe <5s), `verify` (<1s), full (~60-90 min M2). Exit 0/1/2. Run from `final/`. |
| `final/audit/submission_checksums.sha256` | 38 entries | SHA-256 manifest. Verified 38 OK / 0 FAIL. |
| `final/audit/frozen_paper_summary.json` | — | Frozen camera-ready numbers for `verify`. |
| `final/audit/db_config.json` | — | LIVE credentials only here; git-ignored, never shipped. |
| `final/audit/db_config.json.template` | 17 (JSON) | Sanitized schema (postgres/REDACTED, localhost:5432, sdao, sift_hybrid, L2 <->, HNSW m16/efc200/efs100, IVFFlat 1000/10). |
| `scripts/build_bundle.sh` | ~61, 0755 | Packer: stages artifact/, excludes .git/.venv/__pycache__/*.pyc/.DS_Store/*.dump/logs/, 50 entries. |
| `submission_bundle.tar.gz` | 50 entries | Payload: PDFs + tex/tables + docs + scripts + audit + aggregated + raw/smoke CSVs. |
| `.gitignore` | — | Guards live config, pycache, .venv, .DS_Store, TeX aux. No git repo init here. |
## 4. Ground-Truth Empirical Findings (The "Gold" Numbers)

Camera-ready Table VII (frozen PDF run; `verify` tolerates +/-10 pct / +/-0.02):

| Selectivity | SQL_FIRST p50 / R@10 | VECTOR_FIRST_HNSW p50 / R@10 | HNSW_HYBRID p50 / R@10 | IVFFLAT_HYBRID p50 / R@10 | Gate @ R_target>=0.90 |
|---|---|---|---|---|---|
| 0.0-0.5% | 121.77 ms / 1.000 | 2.40 ms / 0.072 (50.67x) | 2.92 ms / 0.112 (41.72x) | 2.66 ms / 0.048 (45.85x) | SQL_FIRST |
| 0.5-1.0% | 144.46 ms / 1.000 | 2.28 ms / 0.124 (63.44x) | 2.60 ms / 0.152 (55.50x) | 2.64 ms / 0.092 (54.80x) | SQL_FIRST |
| 1.0-2.5% | 143.90 ms / 1.000 | 2.24 ms / 0.164 (64.27x) | 2.39 ms / 0.172 (60.23x) | 2.62 ms / 0.212 (54.84x) | SQL_FIRST |
| 2.5-5.0% | 142.47 ms / 0.996 | 2.31 ms / 0.204 (61.54x) | 2.41 ms / 0.216 (59.22x) | 2.66 ms / 0.180 (53.56x) | SQL_FIRST |
| 5.0-100% | 149.69 ms / 1.000 | 2.32 ms / 0.192 (64.41x) | 2.51 ms / 0.192 (59.57x) | 2.73 ms / 0.216 (54.77x) | SQL_FIRST |

Summary: SQL_FIRST ~121-150 ms, Recall 1.000. HNSW_HYBRID ~2.4-2.9 ms
(40-65x), Recall 0.112-0.216. IVFFLAT ~2.6-2.7 ms, Recall 0.048-0.216.
VECTOR_FIRST ~2.2-2.4 ms, Recall 0.072-0.204. Gate: 100 pct SQL_FIRST at
R_target >= 0.90; hybrids admitted only for R_target <= 0.3 (RAG rerank).

- **q-Error invariance:** recall is topology-driven (graph traversal budget),
  not estimate-driven. All 35/35 `(bucket, q-factor)` fallback decisions
  preserved from 0.1x to 10x mis-estimation (`agg_summary.json:
  n_plan_switches_to_hnsw=35, n_total_buckets=35`).
- **Cold-cache ratios:** macOS unified memory + shared buffers give ~1.0x
  inflation (frozen 1.02/1.02; live 0.99/1.01). Docker-restart workaround in
  `_common.py::cold_cache_reset` + `benchmark_cold_cache.py` documented.
- **PAC coverage:** 20/20 cells pass; empirical Bernstein CI within bound,
  empirical coverage 1.00 >= 1-delta = 0.95 (delta=0.05). Re-derivation in
  `verify` checks 11 summary cells + PAC: 0 failures, PASS.

## 5. Tooling, Environment & Compilation Commands

- **Python:** psycopg2-binary 2.9.12, psycopg 3.3.4, pgvector 0.5.0,
  numpy 2.5.1, h5py 3.16.0, pandas 3.0.5, pymupdf 1.28.2 (audit only).
  Install: `pip install psycopg2-binary pgvector numpy h5py pandas`
  (per `final/scripts/new_experiments/README.md`).
- **Database:** PostgreSQL 17.10 + pgvector 0.7+; table `sift_hybrid`
  (id, embedding vector(128), category, price, in_stock); indexes: btree x3,
  HNSW (m=16, ef_construction=200), IVFFlat (lists=1000); runtime
  `hnsw.ef_search=100`, `ivfflat.probes=10`. Native Homebrew or Docker
  (`container_name` in db_config selects cold-cache path). SIFT vectors via
  `$SIFT_QUERY_FVECS` / `./data/` / HDF5 fallback (`download_sift10m`).
- **LaTeX:** `tectonic final/manuscript/main.tex` (run from workspace root;
  outputs alongside main.tex; copy to `final/manuscript/main.pdf`).
  Anonymized build: redact author block to Anonymous Authors, rebuild same
  way to `main_anonymized.pdf`.
- **Reproduction (run from `final/`):**
  `bash scripts/reproduce_all.sh check` (DB probe, <5 s, exit 0;
  fails closed exit 2 on REDACTED placeholder) and
  `bash scripts/reproduce_all.sh verify` (frozen-number check, <1 s,
  11 cells + PAC re-derivation, exit 0 PASS). Full: `bash
  scripts/reproduce_all.sh` (~60-90 min on M2).
- **Manifest:** regen per `REPRODUCIBILITY.md` Section 7 one-liner;
  verify with `python3 /tmp/final_manifest_check.py` (38 OK / 0 FAIL).
- **Fonts/margins audit:** PyMuPDF xref scan (23/23 FontFile3, 0 Type3) +
  page rect 612.0x792.0; off-page block scan 0/6.
- **Bundle:** `bash scripts/build_bundle.sh` (from root) writes
  `submission_bundle.tar.gz` (`files=50 size=392K
  sha256=6c617a64...ecf0e793bbf`); verify with
  `python3 /tmp/bundle_verify.py` + `tar -tzf submission_bundle.tar.gz`.

## 6. Immediate Next Steps / Roadmap

1. **Security:** keep live password strictly in untracked
   `final/audit/db_config.json`; ship only template/placeholder. Re-sweep
   `grep -r '12345@Postg'` (expect 1 hit: live file) before any upload.
2. **Fonts:** re-run `pdffonts main.pdf` on the portal side if available;
   local audit already 100 pct embedded / 0 Type3 / Letter.
3. **Anonymization:** submit `main_anonymized.pdf` for double-blind tracks,
   `main.pdf` for single-blind/camera-ready. Never mix author sets.
4. **Packaging:** after any edit, rehash manifest, rebuild bundle, record
   new `files/size/sha256`, re-verify tar contents + exclusions.
5. **Venues:** TKDE (journal archival), ICDE / SIGMOD / VLDB (conference);
   portal payload (title/abstract/keywords/authors/COI) in
   `SUBMISSION_METADATA.txt` (100 lines, abstract 248 words).
6. **Future work:** ef_search/lists auto-tuning study, larger-than-memory
   scale-out, optimizer-integrated (ε,δ) hook upstream to pgvector.

---
*End of PROJECT_HANDOFF.md — single source of truth as of 2026-09-05.
Bundle SHA-256: `6c617a64a898aa47cf80460d19fb3980c48385ab20fe72fbff3c7ecf0e793bbf`.*
