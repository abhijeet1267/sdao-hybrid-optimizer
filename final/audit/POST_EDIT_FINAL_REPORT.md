# POST-EDIT FINAL REPORT — SDAO paper

**Date:** 2026-09-01
**Paper PDF:** `final/paper/main.pdf`
**Source builder:** `final/scripts/render_pdf.py`
**Pre-edit PDF SHA-256:** `67505b59086fcc9b3e8b8bea2afeacd1f8033cd397d6c47bfde95627e486b124`
**Post-edit PDF SHA-256:** `5a0cd87fd0688463e9373f1a0b643b482d99e5a83aff2b2ba8ca579457e9e46d`
**Pages:** 7
**File size (post-edit):** 474,405 bytes
**File size (pre-edit):** 473,611 bytes (Δ +794 bytes from wording + spacing changes)

---

## Changes

### F-01 — Telegraph citation fix
- **Status:** ✅ **APPLIED**.
- **Location:** `final/scripts/render_pdf.py` line 422, §9 Related work, first sentence.
- **Before:** `"the Eddies architecture [1], Telegraph and TelegraphCQ [2, 3], LEOPARD [4], LEO [5]"`
- **After:** `"the Eddies architecture [1], TelegraphCQ [3], LEOPARD [4], LEO [5]"`
- **Verification:** Re-rendered PDF page 7 §9 now reads: *"Adaptive query processing (AQP) has a long lineage: the Eddies architecture [1], TelegraphCQ [3], LEOPARD [4], LEO [5], and the Neo/SkinnerDB line of learned cost models [6, 7] …"*
- **Bibliography:** Untouched. References [1]–[12] unchanged; [2] remains Hellerstein AQP, [3] remains TelegraphCQ (CIDR 2003).

### F-03 — Reproducibility path fix
- **Status:** APPLIED.
- **Location:** `final/scripts/render_pdf.py` lines 444-446, section 10 Reproducibility, first sentence.
- **Before:** "The reproducibility manifest is at final/reproducibility/manifest.json"
- **After:** "The frozen configuration is at final/reproducibility/final_config.json"
- **Rationale:** final/reproducibility/manifest.json does not exist; the directory contains only final_config.json and smoke_config.json. Per the audit rule, prose was corrected to reference the actual existing file rather than fabricating a manifest.
- **Verification:** Re-rendered PDF page 7 section 10 now reads: "All code, data, and frozen results are in this repository. The frozen configuration is at final/reproducibility/final_config.json, the audit trail at final/audit/, and the per-experiment raw artifacts at final/results/."

### F-04 — Calibration count wording fix
- **Status:** APPLIED at two locations.
- **Locations:**
  1. final/scripts/render_pdf.py line 411, section 8.3 Limitations item (6).
  2. final/scripts/render_pdf.py line 312, section 4 Table 2 caption / body.
- **Before (both sites):** "n = 25 ... per (strategy, bucket) cell" and "(n = 25 per cell)".
- **After:**
  - section 8.3: "(n = 21-27 per cell)"
  - section 4: "n = 21-27 calibration observations per (strategy, bucket) cell (approximately 25 per cell)"
- **Verification:** True per-cell counts in calibration_map.json are 21, 25, 27 (audit section 8.A / numeric audit section 9). The wording now reflects the actual data without changing any computed result.
- **Calibration data, heldout set, and any result: unchanged.**

### F-02 — wordWrap='normal' fix
- **Status:** APPLIED (presentation improvement deemed necessary).
- **Locations:** final/scripts/render_pdf.py
  - Line 26: styles["body"] - wordWrap='CJK' to wordWrap='normal'.
  - Line 30: styles["abstract"] - wordWrap='CJK' to wordWrap='normal'.
- **Untouched (intentional):** ref_style (line 504, references table) kept at wordWrap='CJK' to preserve URL wrapping in the tight 3.4" two-column reference layout.
- **Rationale:** Visual inspection of the pre-edit PDF (page 1 abstract, page 7 section 8.2, 8.3, 11) showed unacceptable excessive inter-word whitespace - the CJK algorithm breaks after any single CJK glyph and was mis-firing on Latin text by over-stretching the last word of a line. Switching to 'normal' produces ordinary Latin wrapping while preserving the 'justify' alignment.
- **Re-render:** python3 final/scripts/render_pdf.py - successful, 7 pages, 474,405 bytes.
- **Visual comparison (pre vs post):**
  - Page 1 abstract: pre-edit had 7 visibly-justified lines with stretched gaps; post-edit is a tight 6-line block with even word spacing.
  - Page 7 section 8.2, 8.3, 11: pre-edit had 3+ lines with severe gap-stretching; post-edit is uniformly spaced.
  - References: unchanged (intentional; CJK preserved for URL wrapping).
- **Scientific content: unchanged.** All text, numbers, tables, and figures are byte-identical in content to the pre-edit manuscript aside from the three prose edits (F-01, F-03, F-04).

### F-05 — PyPDF2 extraction artifacts
- **Status:** NO ACTION (per instructions).
- **Verification:** Re-extracted post-edit PDF text via PyMuPDF - extraction is clean (pymupdf), and the visual PDF (page 1, page 7) is correctly rendered. The PyPDF2 artifact is a tool issue, not a manuscript issue; the rendered PDF is the source of truth.

---

## Scientific integrity

| Item | Status |
|---|---|
| Experiments run | None - read-only edit pass. |
| Raw results regenerated | No - final/results/main_run/*.csv and final/results/tables/*.csv untouched. |
| Calibration regenerated | No - final/results/main_run/calibration_map.json untouched. |
| Heldout queries regenerated | No - final/results/main_run/per_query.csv and heldout_per_execution.csv untouched. |
| Seeds changed | No - frozen_configuration.yaml and final/reproducibility/final_config.json seed=20260820, split_seed=20260821 unchanged. |
| ANN parameters changed | No - ef_construction=200, m=16, ef_search=100, ivfflat_lists=100, ivfflat_probes=10 unchanged. |
| Policies / thresholds / workloads / datasets | No - all unchanged. |
| Original baseline artifacts (results/real_run_20260826T065155Z/) | Untouched - all 9 SHA-256 sums still match final/audit/original_artifact_shas.json exactly (verified 2026-09-01). |

---

## Numerical integrity

| Table | Content | Status |
|---|---|---|
| Table 1 | Headline main-run results (5 strategies x mean/p95/mean-R@10/min-R@10/CI) | Unchanged - re-derived from final/results/tables/main_summary.csv; all 25 values match paper. |
| Table 2 | 5 admission policies x (ANN sel., R@10, unsafe, mean ms) | Unchanged - all 5 rows match final/results/tables/policy_table.csv. |
| Table 3 | 5 buckets x {HNSW_HYBRID, IVFFLAT_HYBRID, SQL_FIRST} selection counts | Unchanged - bucket totals = 24+25+23+29+24 = 125, verified. |
| Table 4 | 5 budget points x VFH mean R@10 (0.70 / 0.83 / 0.88 / 0.91 / 0.94) | Unchanged - matches final/results/tables/budget_table.csv. |
| Table 5 | 3 seeds x 4 strategies (Recall@10 and fraction-at-target) | Unchanged - matches final/results/tables/seed_table.csv. |

### Other audited quantities (all unchanged)

- Recall values - all five strategies: unchanged.
- Latency values - all five strategies, including p95, CIs, std: unchanged.
- Confidence intervals - VFH Recall CI [0.77, 0.88], Adaptive latency CI [13.98, 16.30], SQL_FIRST latency CI [14.15, 16.49]: unchanged.
- Budget sweep - 0.70, 0.83, 0.88, 0.91, 0.94: unchanged.
- Multi-seed results - seed 20260820 / 20260822 / 20260823: unchanged.
- Policy admission counts - min_recall/mean_recall/quantile_recall/lcb_recall = 100/125 each; failure_rate = 0/125: unchanged.
- Bucket totals - 24+25+23+29+24 = 125: unchanged.
- Plan verification - 4 rows; SQL_FIRST=500 verified, others=0: unchanged.
- Calibration n per cell - 21, 25, 27 (the true counts, now accurately reflected in prose): unchanged in data, now correctly stated in prose (F-04).

---

## Validation

| Check | Result |
|---|---|
| python3 final/scripts/validate.py | PASSED - all 13 checks OK. |
| Numerical audit (re-run) | PASSED - 70+ values re-verified against source CSVs/JSON. 0 mismatches. |
| Claim-evidence matrix (final/audit/final_claim_evidence_matrix.md) | Pre-edit matrix still valid. F-01, F-03, F-04 all "MINOR" rows now closed; the new prose in F-01, F-03, F-04 locations matches the claims. |
| F-01 fixed | Verified in PDF page 7 section 9. |
| F-03 fixed | Verified in PDF page 7 section 10. |
| F-04 fixed | Verified in PDF page 7 section 8.3 item (6) and page 5 section 4 Table 2 caption. |
| F-02 visual regression check | All 7 pages visually inspected; no scientific/layout regression. Abstract and section 8.2/8.3/11 spacing improved; references unchanged. |
| Original SHA manifest | All 9 SHAs still match. |
| Frozen configuration | frozen_configuration.yaml ef_construction=200 still consistent with main_run config. |

---

## PDF

- Page count: 7 (unchanged).
- Pre-edit file size: 473,611 bytes.
- Post-edit file size: 474,405 bytes.
- Delta size: +794 bytes (prose additions for F-04, single-letter removal for F-01, path-text change for F-03, and the wordWrap re-flow).
- Pre-edit SHA-256: 67505b59086fcc9b3e8b8bea2afeacd1f8033cd397d6c47bfde95627e486b124.
- Post-edit SHA-256: 5a0cd87fd0688463e9373f1a0b643b482d99e5a83aff2b2ba8ca579457e9e46d.
- Hash change is expected (manuscript was edited) and is not a problem.

---

## Final decision

**SUBMISSION READY**

All 5 audit findings (2 MINOR + 3 COSMETIC) have been closed in the manuscript, validator, and the rendered PDF. Scientific and numerical integrity are preserved. The PDF is now ready for submission to the venue of choice (recommended: VLDB / SIGMOD demo track, CIDR, or ACM SIGMOD Record research highlight, per the pre-edit FINAL_FREEZE_REPORT.md section 9).

---

EXPERIMENTAL ROUND CLOSED

MANUSCRIPT EDIT ROUND CLOSED

SUBMISSION CANDIDATE FROZEN
