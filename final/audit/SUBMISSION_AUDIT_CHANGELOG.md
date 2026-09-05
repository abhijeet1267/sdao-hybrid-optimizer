# Submission Audit Changelog

**Date:** 2026-09-02
**Auditor:** submission-readiness pass over IEEE variant
**Frozen PDF SHA-256:** `c3ee1748ca144cf22b10367e860a509e11521896da370ef8ab244dd2625cf14e`
**Frozen PDF pages:** 6 (target 6–8)
**Validator result:** `validate_ieee.py` 11/11 PASSED, `validate.py` 13/13 PASSED

---

## Scope

Final pre-submission audit of `final/paper/ieee/main.tex` and the
`final/audit/IEEE_FORMAT_FINAL_REPORT.md` companion. The 7p
`final/paper/main.pdf` was inspected for completeness only; the IEEE
6p variant is the canonical submission source.

## Tasks completed

1. **Bibliography audit (Task 1).** All 12 references traced
   TelegraphCQ[3]…ACORN[12]. No TODO/placeholder citations.
   `references.bib` is complete and IEEEtran-formatted. **PASS.**
2. **Internal numeric consistency (Task 2).** All 26 frozen numerical
   claims verified against `final/results/tables/*.csv` and
   `final/results/main_run/*.json` to the paper's stated precision.
   Adaptive CIs [13.98, 16.30] and SQL_FIRST CIs [14.15, 16.49] match
   the source `latency_ci_lo/hi` columns to 2dp. **PASS.**
3. **Terminology audit (Task 3).** `SQL_FIRST`, `VECTOR_FIRST_HNSW`,
   `HNSW_HYBRID`, `IVFFLAT_HYBRID`, `Recall@10` are used uniformly
   across abstract, §III.D, §VII.D, and §XI. **PASS.**
4. **Validator count reconciliation (Task 4).** `validate_ieee.py`
   contains 11 checks (PDF size, SHA-256, 26 verbatim strings, ref
   ordering, roman-numeral labels, 6 fig refs, 5 table refs, VFH CI,
   6 page screenshots, 7 audit artifacts, final summary). `validate.py`
   contains 13 checks for the 7p paper. Both counts are consistent with
   their respective script bodies. **PASS.**

## Drift items found and resolved in this pass

| ID | Severity | File | Before | After |
|---|---|---|---|---|
| D-1 | MINOR (prose) | `IEEE_FORMAT_FINAL_REPORT.md` line 67 | "held-out size n=21, full size n=27" (implied two distinct values) | "per-cell calibration size n = 21–27 (the IEEE text states a range, not two distinct values)" |
| D-2 | MINOR (citation label) | `IEEE_FORMAT_FINAL_REPORT.md` lines 86–87 | ACORN [12] labeled as "self-citation; result not yet published" | ACORN (Pan et al., PVLDB 2023) — filter-aware HNSW augmentation for hybrid metadata-filtered ANN search |
| D-3 | COSMETIC (count) | `IEEE_FORMAT_FINAL_REPORT.md` lines 57, 139 | "27 frozen values" / "All 27 frozen numerical claims" | "26 frozen values" / "All 26 frozen numerical claims" (matches `validate_ieee.py` stdout) |

## Drift item deferred (cannot be applied in this sandbox)

| ID | Severity | File | Issue | Resolution path |
|---|---|---|---|---|
| M-1 | MINOR (broken reference) | `final/paper/ieee/main.tex` line 563, mirrored in `main.pdf` page 5 | Paper references `REPRODUCE.md` (a file that does **not exist** anywhere in the repo). The only existing file is `REPRODUCIBILITY_REPORT.md` (a report, not a how-to-reproduce guide). | On a machine with `pdflatex`/`xelatex` installed, edit line 563 to: `reproduce end-to-end, see \texttt{REPRODUCIBILITY\_REPORT.md} at the repository root.`, then rebuild `final/paper/ieee/main.pdf` and re-run `validate_ieee.py`. The current sandbox has no LaTeX engine, so the change is **NOT** applied to the PDF. **The frozen `main.pdf` still says `REPRODUCE.md`.** |

## Validator result (post-edits)

```
=== IEEE Manuscript Validation ===
[OK] IEEE PDF: 6 pages, 214677 bytes
[OK] IEEE PDF SHA-256: c3ee1748ca144cf22b10367e860a509e11521896da370ef8ab244dd2625cf14e
[INFO] frozen SDAO PDF SHA-256: 5a0cd87fd0688463e9373f1a0b643b482d99e5a83aff2b2ba8ca579457e9e46d
[OK] all 26 frozen numerical claims present verbatim
[OK] references ordered: TelegraphCQ[3] ... ACORN[12]
[OK] all section roman-numeral labels present
[OK] all 6 figure references present
[OK] all 5 table references present
[OK] VFH recall 0.829 CI [0.771, 0.882] matches CSV
[OK] all 6 IEEE page screenshots present and current
[OK] all 7 audit artifacts present
=== ALL IEEE VALIDATION CHECKS PASSED ===

=== End-to-end validation ===
[OK] paper PDF: 7 pages, 474405 bytes
[OK] all 8 figures present as PDF + PNG
[OK] all 7 page screenshots current
[OK] VFH recall 0.829 CI [0.771, 0.882] matches paper claim 0.83 [0.77, 0.88]
[OK] budget sweep recalls match Table 4 (50..1000)
[OK] multi-seed recalls match Table 5 (3 seeds)
[OK] all 5 admission policies present
[OK] bucket selections total to 125 (held-out query count)
[INFO] plan_verification rows: 4; SQL_FIRST=500 verified, others 0
[OK] 9 original artifact SHAs preserved in audit
[OK] frozen_configuration.yaml ef_construction=200 matches main_run config
[OK] PDF contains updated Table 4 caption
[OK] all 7 audit artifacts present
=== ALL VALIDATION CHECKS PASSED ===
```

## Outstanding decisions requiring user input (NOT technical)

1. **Target venue.** A `IEEEtran` 6-page conference variant is
   submission-ready for most IEEE venues (e.g., ICDE, VLDB-endorsed
   IEEE tracks, KDD, SIGMOD industrial / reproducibility tracks). The
   user has not confirmed a specific venue. **Action:** the venue's
   submission-system maximum page count and copyright-transfer
   language still need to be confirmed before the paper is uploaded.
2. **Author block.** The title page shows `Anonymous Author(s)`. If
   the target venue is double-blind, this is correct. If the venue is
   single-blind or non-anonymous, the authors need to be added. **No
   editor was changed** because the audit cannot resolve the
   double-blind-vs-not question.
3. **`REPRODUCE.md` reference (M-1).** See the deferred-change table
   above. The 7p paper's `final/scripts/render_pdf.py` source already
   says `REPRODUCIBILITY_REPORT.md` in some sections but the IEEE
   paper was rendered before that fix was applied. **This needs a
   LaTeX rebuild on a TeX-enabled host.**

## Summary

- **All in-scope audit tasks PASS.**
- **Three audit-report drifts (D-1, D-2, D-3) are fixed** in
  `final/audit/IEEE_FORMAT_FINAL_REPORT.md`. Frozen artifacts
  (`final/results/`, `final/frozen_configuration.yaml`,
  `final/reproducibility/final_config.json`, both PDFs) are
  **untouched**.
- **One paper-level drift (M-1: broken `REPRODUCE.md` reference) is
  deferred** because the sandbox lacks a LaTeX engine. The PDF
  is unchanged; the user is notified.
- **No MAJOR findings.** All numerical, citation, and cross-reference
  claims verified.

---

## 2026-09-02 — M-1 fix: real `REPRODUCE.md` written, §10.1 sentence expanded, IEEE PDF rebuilt

### Files changed
- **Created**: `/Users/abhijeetmiskin/AppData/MyProject/REPRODUCE.md` (189 lines, 10,850 bytes, SHA-256 `0f671ec7446c20a38f72638df7ce5422ba754cc03d1e6a4457236464278c6f2c`) — the file the paper's §10.1 has always pointed to but which did not exist on disk. Covers: claim→artifact mapping for all 5 tables and 8 figures, frozen environment (PG 17.10, pgvector 0.8.x, SIFT1M 200K subset, `ef_construction=200`), exact verifier commands for `validate.py` and `validate_ieee.py`, explicit "do not regenerate" guidance for the 200K index / policy / seeds, full `final/` directory layout, and a 30-second SHA-recipe that was live-tested against the 9 original artifact SHAs.
- **Edited**: `/Users/abhijeetmiskin/AppData/MyProject/final/paper/ieee/main.tex` — single 1-line edit at line 563 of §10.1. Replaced the bare `\texttt{REPRODUCE.md}` reference with a path-qualified sentence:
  - **Old**: `reproduce end-to-end, follow \texttt{REPRODUCE.md}.`
  - **New**: `reproduce end-to-end, follow the top-level \texttt{REPRODUCE.md} (at the repository root), which maps every claim in this paper to a frozen artifact and lists the verifier commands (\texttt{validate.py} and \texttt{validate\_ieee.py}).`
- **Rebuilt**: `final/paper/ieee/main.pdf` via `tectonic -X compile main.tex` (only TeX underfull-`\hbox` warnings; no errors; no overfull-`\hbox` warnings; 2 LaTeX passes as normal).
- **Regenerated**: `final/audit/ieee_pages/page_{1..6}.png` at 150 DPI from the new PDF (required by `validate_ieee.py` step 10's mtime check). Old screenshots were dated 2026-09-01 20:07 and would have tripped a `stale screenshot` assertion against the freshly built PDF.

### Hashes
- **Old IEEE PDF SHA-256**: `c3ee1748ca144cf22b10367e860a509e11521896da370ef8ab244dd2625cf14e` (6 pages, 214,677 bytes) — pre-rebuild state.
- **New IEEE PDF SHA-256**: `318a0ac972336971709dfd332c410730875f69d2c5ab8dc4e1f1865113c2aaf4` (6 pages, 214,832 bytes) — post-rebuild state.
- **Net change**: +155 bytes, SHA changed, page count unchanged at 6.

### Text diff summary (new − old)
- **Page 5 (§X. Reproducibility, last sentence of §10.1)**: the only textual change. The old ending `… and \texttt{ef\_construction} consistency. To reproduce end-to-end, follow \texttt{REPRODUCE.md}.` was replaced with `… and \texttt{ef\_construction} consistency. To reproduce end-to-end, follow the top-level \texttt{REPRODUCE.md} (at the repository root), which maps every claim in this paper to a frozen artifact and lists the verifier commands (\texttt{validate.py} and \texttt{validate\_ieee.py}).`
- All other 6 pages of prose, all 5 tables, all 6 figure captions, and the 12-entry references list are byte-for-byte unchanged in textual content (small font-kerning differences from the additional 8 words produced the +155-byte PDF size delta and the SHA change; the `tectonic` rebuild is deterministic up to embed-font timestamp metadata).

### Validator results
- `python3 final/scripts/validate.py` (7p reproducibility report): **13/13 PASS**, ending with `=== ALL VALIDATION CHECKS PASSED ===`.
- `python3 final/scripts/validate_ieee.py` (IEEE 6p submission): **11/11 PASS**, ending with `=== ALL IEEE VALIDATION CHECKS PASSED ===`. All 26 frozen numerical claims present verbatim; references ordered TelegraphCQ[3] … ACORN[12]; all 6 section roman-numeral labels present; all 6 figure references present; all 5 table references present; VFH recall 0.829 CI [0.771, 0.882] matches CSV; all 6 IEEE page screenshots present and current; all 7 audit artifacts present.

### Frozen artifacts — confirmed untouched
- `final/results/` — 9/9 SHA-256 entries in `original_artifact_shas.json` verified bit-for-bit.
- `final/frozen_configuration.yaml` — `ef_construction=200` still consistent with the main run config and the audit report.
- `final/reproducibility/final_config.json` — 40 keys, unchanged.
- `final/figures/` — 8 PDF + 8 PNG figures, unchanged.
- `final/paper/main.pdf` (7p reproducibility report) — SHA `5a0cd87fd0688463e9373f1a0b643b482d99e5a83aff2b2ba8ca579457e9e46d`, unchanged.
- All numeric values, CIs, seeds, and policy-admission counts in the paper.

### M-1 status
- **M-1 (broken `REPRODUCE.md` reference) — RESOLVED.** The referenced file now exists at `/Users/abhijeetmiskin/AppData/MyProject/REPRODUCE.md` and the §10.1 sentence has been expanded to (i) make the path unambiguous and (ii) document the verifier commands.

### Outstanding items
- Venue selection (IEEE track / arXiv / other) — awaiting user input.
- Author block (names, affiliations, ordering, corresponding author) — awaiting user input.
- All scientific content remains frozen; no further edits are planned without explicit user authorization.

## 2026-09-02 — Task 2 & 3: Author block replacement + venue preparation

### Files changed
- **Edited**: `/Users/abhijeetmiskin/AppData/MyProject/final/paper/ieee/main.tex` — replaced the placeholder `Anonymous Author(s)` block (lines 27–35) with a real author block:
  - **Authors**: Abhijeet L.M (corresponding), Leninisha S
  - **Affiliation**: School of Computer Science Engineering, Vellore Institute of Technology, Chennai, India (both authors share the same affiliation)
  - **Corresponding author designation**: `\thanks{Corresponding author. Email: \texttt{[REQUEST USER: email needed]}}` on first author
  - **Email placeholders**: two explicit `[REQUEST USER: email needed]` markers — user must supply before submission
- No anonymization artifacts (blinded self-citation hedges like "the authors' prior work") were found in the paper body; the text already uses first-person ("We study", "We construct", "The study does not") consistent with non-anonymous submission.
- Venue template: kept IEEEtran `conference` class (6 pages, two-column) — no template swap performed because the user has not yet named a specific workshop/CFP. If the chosen venue (e.g., DBTest, VLDB workshop) uses a different template, a separate edit pass will be needed.

### Hashes
- **Old IEEE PDF SHA-256**: `318a0ac972336971709dfd332c410730875f69d2c5ab8dc4e1f1865113c2aaf4` (6 pages, 214,832 bytes) — post-M-1 rebuild state.
- **New IEEE PDF SHA-256**: `3b319455eb996810e1edd3c391052f9b8a589b709ded3ea2637ec1ac31f784ae` (6 pages, 216,724 bytes) — post-author-block rebuild.
- **Net change**: +1,892 bytes, SHA changed, page count unchanged at 6.

### Text diff summary (new − old)
- **Title page (page 1)**: author block replaced; no other textual changes.
- All 6 pages of prose, all 5 tables, all 6 figure captions, and the 12-entry references list are byte-for-byte unchanged in content (the author block addition is the sole visible change; font-kerning and layout shifts produced the +1,892-byte PDF size delta and the SHA change).

### Validator results
- `python3 final/scripts/validate.py` (7p reproducibility report): **13/13 PASS**, ending with `=== ALL VALIDATION CHECKS PASSED ===`.
- `python3 final/scripts/validate_ieee.py` (IEEE 6p submission): **11/11 PASS**, ending with `=== ALL IEEE VALIDATION CHECKS PASSED ===`. All 26 frozen numerical claims present verbatim; references ordered TelegraphCQ[3] … ACORN[12]; all 6 section roman-numeral labels present; all 6 figure references present; all 5 table references present; VFH recall 0.829 CI [0.771, 0.882] matches CSV; all 6 IEEE page screenshots present and current; all 7 audit artifacts present.

### Frozen artifacts — confirmed untouched
- `final/results/` — 9/9 SHA-256 entries in `original_artifact_shas.json` verified bit-for-bit.
- `final/frozen_configuration.yaml` — `ef_construction=200` still consistent with the main run config and the audit report.
- `final/reproducibility/final_config.json` — 40 keys, unchanged.
- `final/figures/` — 8 PDF + 8 PNG figures, unchanged.
- `final/paper/main.pdf` (7p reproducibility report) — SHA `5a0cd87fd0688463e9373f1a0b643b482d99e5a83aff2b2ba8ca579457e9e46d`, unchanged.
- All numeric values, CIs, seeds, and policy-admission counts in the paper.

### Outstanding items (updated)
- **EMAIL ADDRESSES REQUIRED**: Two email addresses for Abhijeet L.M and Leninisha S (placeholders currently read `[REQUEST USER: email needed]`).
- **VENUE CONFIRMATION REQUIRED**: User must specify the target venue (e.g., DBTest@SIGMOD, VLDB workshop, other IEEE conference, or arXiv-first). If a workshop template is chosen that differs from IEEEtran, a template swap and possible re-flow will be required.
- **ARXIV LICENSE**: If posting to arXiv, user must choose a license (CC-BY, arXiv non-exclusive, etc.).
- All scientific content remains frozen; no further edits are planned without explicit user authorization.

## 2026-09-02 — Final Closing Pass: Venue Lock + arXiv Package Preparation

### Decisions applied
- **Format**: Keeping IEEEtran conference class (no ACM switch). No template change needed.
- **arXiv license**: arXiv non-exclusive license (not Creative Commons).
- **Email placeholders**: Intentionally left as `[REQUEST USER: email needed]` per user decision. The `\thanks{Corresponding author. Email: ...}` markup is preserved.

### Files created (not modified — all source files untouched in this pass)
- **Created**: `/Users/abhijeetmiskin/AppData/MyProject/arxiv/README.md` — submission package index documenting package contents, author block, frozen SHAs, validator results, and category suggestion.
- **Created**: `/Users/abhijeetmiskin/AppData/MyProject/arxiv/LICENSE_ARXIV.txt` — states the submission is under the arXiv non-exclusive license, explicitly NOT a Creative Commons license.
- **Created**: `/Users/abhijeetmiskin/AppData/MyProject/arxiv/main.pdf` — copy of the compiled IEEE PDF (216,724 bytes, 6 pages, SHA-256 `3b319455...`).
- **Created**: `/Users/abhijeetmiskin/AppData/MyProject/arxiv/source/` — LaTeX source bundle:
  - `source/main.tex` (27,292 bytes, copy of `final/paper/ieee/main.tex`)
  - `source/references.bib` (4,673 bytes, copy of `final/paper/ieee/references.bib`)
  - `source/figures/figure_{1..8}_*.pdf` (8 PDF figures, ~166 KiB total)
  - No custom `.sty`/`.cls` files were needed — IEEEtran is auto-resolved by arXiv's TeX Live.

### Files NOT modified in this pass
- `final/paper/ieee/main.tex` — confirmed unchanged from the post-Task-2 author-block state.
- `final/paper/ieee/main.pdf` — SHA `3b319455eb996810e1edd3c391052f9b8a589b709ded3ea2637ec1ac31f784ae` (6 pages, 216,724 bytes).
- All frozen result, configuration, and reproducibility artifacts.

### Pre-flight checklist
- [x] `validate_ieee.py` 11/11 PASS (`=== ALL IEEE VALIDATION CHECKS PASSED ===`).
- [x] `validate.py` 13/13 PASS (`=== ALL VALIDATION CHECKS PASSED ===`).
- [x] Email placeholders present at: `final/paper/ieee/main.tex:28`, `final/paper/ieee/main.tex:33`, `final/paper/ieee/main.tex:34`.
- [x] No "Anonymous Author(s)" or blind-review artifacts reintroduced (grep for `Anonymous|blind|prior work|self-citation` returned zero matches in `main.tex`).
- [x] `REPRODUCE.md` unchanged since M-1 fix (no drift).
- [x] All 9 frozen artifact SHAs re-verified against `original_artifact_shas.json`: 9/9 PASS.
- [x] Document class: `\documentclass[conference]{IEEEtran}` (line 8 of `main.tex`) — 6 pages satisfies typical workshop limits (4–8 pages); no specific CFP limit can be checked until a venue is named.

### arXiv category suggestion
- **Primary**: `cs.DB` (Databases) — most natural fit for a hybrid SQL–vector query processing paper.
- Secondary (if applicable): `cs.LG` if the adaptive selection framing is emphasized, `cs.PF` if performance focus is highlighted.
- **Final category selection is the user's action at arXiv upload time.**

### Outstanding items (carried forward, unchanged)
- Filling the two email placeholders.
- Naming a specific workshop/CFP.
- The actual arXiv upload (uploading, category click-through, license confirmation) — agent has prepared the package and **stopped**, as instructed.

### arXiv package contents summary
```
arxiv/
├── LICENSE_ARXIV.txt          (860 B)   - arXiv non-exclusive license notice
├── README.md                  (1,931 B) - package index and instructions
├── main.pdf                   (216,724 B / 6 pages / SHA 3b319455...)
└── source/
    ├── main.tex               (27,292 B)
    ├── references.bib         (4,673 B)
    └── figures/
        ├── figure_1_decision_flow.pdf
        ├── figure_2_strategy_vs_selectivity.pdf
        ├── figure_3_adaptive_selection.pdf
        ├── figure_4_latency_recall_pareto.pdf
        ├── figure_5_calibration_size.pdf
        ├── figure_6_safety_coverage.pdf
        ├── figure_7_parameter_sensitivity.pdf
        └── figure_8_plan_verification.pdf
```

### Submission status
- **STATUS: READY FOR USER REVIEW**. All agent-side tasks complete. Submission to arXiv is a user action.
- **DO NOT SUBMIT** until the two email placeholders are filled and the user confirms the upload.


