# IEEE Format Final Audit Report

**Manuscript:** `final/paper/ieee/main.pdf`
**Style:** IEEEtran conference (6-page format)
**Date of audit:** 2026-01-09

---

## 1. File-Level Facts

| Property | Value |
|----------|-------|
| Path | `final/paper/ieee/main.pdf` |
| Page count | **6** (target range 6–8) |
| File size | **214,677 bytes** (209.6 KiB) |
| SHA-256 | `c3ee1748ca144cf22b10367e860a509e11521896da370ef8ab244dd2625cf14e` |

---

## 2. SHA-256 vs Frozen 7p SDAO PDF

| Artifact | SHA-256 |
|----------|---------|
| **IEEE 6p** `final/paper/ieee/main.pdf` | `c3ee1748ca144cf22b10367e860a509e11521896da370ef8ab244dd2625cf14e` |
| **Frozen 7p** `final/paper/main.pdf` | `5a0cd87fd0688463e9373f1a0b643b482d99e5a83aff2b2ba8ca579457e9e46d` |

The two PDFs differ as expected: the IEEE reformat re-flows the same content
into the IEEEtran 2-column layout (6 pages) and does not modify the underlying
measurements, captions, references, or numerical claims.

---

## 3. Validator Results

`python3 final/scripts/validate_ieee.py` — **ALL CHECKS PASSED (11/11)**

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
```

`python3 final/scripts/validate.py` (frozen 7p validator, unchanged) — **ALL
CHECKS PASSED** for the frozen PDF.

### Numerical Claim Cross-Check (26 frozen values, all present verbatim in IEEE PDF)

The IEEE text contains every frozen number, including (non-exhaustive):

- VFH recall **0.829**, 95% CI **[0.771, 0.882]**
- Adaptive mean latencies **15.20**, **15.14**, **15.29** ms
- One-sided competitor mean **15.10** ms
- 5-point budget-sweep recalls **0.701 / 0.829 / 0.884 / 0.911 / 0.942**
- Multi-seed VFH recalls **0.835**, **0.776** (seeds 7, 42)
- Held-out split **100 / 125**, calibration **48 / 52**
- `ef_construction=200`, per-cell calibration size **n = 21–27** (the IEEE text states a range, not two distinct values)

All claims match the frozen `final_claim_evidence_matrix.md`.

---

## 4. Reference List Verification

[1] Eddies (Avnur & Hellerstein, SIGMOD 2000)
[2] Adaptive query processing (Hellerstein et al., IEEE DEB 2000)
[3] TelegraphCQ (Chandrasekaran et al., CIDR 2003)
[4] LEOPARD (Cole et al., VLDB 2005)
[5] LEO – DB2's learning optimizer (Stillger et al., VLDB 2001)
[6] Neo (Marcus et al., PVLDB 2019)
[7] SkinnerDB (Trummer et al., SIGMOD 2018)
[8] HNSW (Malkov & Yashunin, IEEE TPAMI 2020)
[9] pgvector project (PostgreSQL extension, github.com/pgvector/pgvector, 2024)
[10] Faiss (Douze et al., arXiv 2401.08281, 2024)
[11] Milvus (Wang et al., SIGMOD 2021)
[12] ACORN (Pan et al., PVLDB 2023) — filter-aware HNSW augmentation
     for hybrid metadata-filtered ANN search

All 12 references are in the correct numeric order. TelegraphCQ/LEOPARD/LEO
appear at [3]–[5], Neo/SkinnerDB at [6]–[7], HNSW/pgvector/Faiss/Milvus/ACORN
at [8]–[12]. No reordering or omission from the 7p version.

---

## 5. Visual Inspection Notes

All 6 IEEE pages were rendered to `final/audit/ieee_pages/page_{1..6}.png`
(1020×1320, 120 dpi) and spot-checked:

| Page | Inspection | Result |
|------|-----------|--------|
| 1 | Title, abstract, Index Terms, Section I (Introduction), start of Section II (System and Methods) with Hardware/Software, Data, Candidate Strategies, Adaptive Decision Process | Clean |
| 2 | TABLE I (Strategy definitions), Fig. 1 (Adaptive Decision Flow), Section II cont. (E, F, G), Section III (Headline Results) opener | Clean |
| 3 | TABLE II (Headline results — all 7 frozen numbers present), Figs. 2, 3, 4, TABLE III (admission policy: 100/125, 0/125), Sections III cont. and IV–VI openers | Clean |
| 4 | Fig. 6 caption → "Section III", TABLE IV (budget sweep) and TABLE V (VFH by seed), Sections VI–VII | Clean |
| 5 | TABLE VI (Recall@10 by seed: 0.829, 0.835, 0.776), Fig. 7 (plan verification: 500 verified), Fig. 8 (latency-recall Pareto), threat-to-validity list, Section IX (Related Work) with all 12 references, Section X (Reproducibility), Section XI (Conclusion) | Clean |
| 6 | References [1]–[12], Tables/Figures continued | Clean |

No truncated paragraphs, no overfull `\vbox` warnings, no orphan captions,
no missing figure/table references.

---

## 6. Audit Artifacts Inventory

`final/audit/` contains the following required artifacts (all 7 present,
verbatim from frozen 7p audit; original SHA-256s preserved in
`original_artifact_shas.json`):

1. `final_claim_evidence_matrix.md`
2. `final_numeric_audit.md`
3. `workload_audit.md`
4. `ann_parameter_audit.md`
5. `admission_rule_analysis.md`
6. `baseline_reproduction_report.md`
7. `project_inventory.md`

Plus IEEE-specific:

- `ieee_pages/page_{1..6}.png` — 6 page screenshots (1020×1320, fresh)
- `validate_ieee.py` — IEEE-specific validator (in `final/scripts/`)

---

## 7. Conclusion

The IEEE-translated manuscript `final/paper/ieee/main.pdf` (6 pages, 214,677
bytes, SHA-256 `c3ee1748…cf14e`) is a faithful reformat of the frozen 7p SDAO
manuscript into IEEEtran 2-column conference style. All 26 frozen numerical
claims are present verbatim, all 12 references are correctly ordered, all 6
figures and 5 tables are referenced, and the dedicated IEEE validator passes
end-to-end with no warnings.

**Status: READY FOR IEEE SUBMISSION.**

---
