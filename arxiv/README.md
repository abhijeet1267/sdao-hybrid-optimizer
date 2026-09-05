arXiv submission package for "A Selectivity-Driven Adaptive Strategy-Selection Framework with Recall-Aware Admission for Hybrid SQL--Vector Databases"
========================================================================================================================================

This directory contains the source files required for arXiv compilation and submission.
Do NOT upload to arXiv from this directory without confirming the following:

1. Paper source (LaTeX):
   - source/main.tex       -- IEEEtran conference class, 6 pages, two-column
   - source/references.bib -- BibTeX bibliography
   - source/figures/       -- 8 PDF figures (figure_1 through figure_8)
   - main.pdf              -- compiled PDF (216,724 bytes, 6 pages, SHA-256: 3b319455...)

2. arXiv-specific license:
   - LICENSE_ARXIV.txt     -- states "arXiv non-exclusive license to distribute"
     (not Creative Commons / CC-BY)

3. Author block in main.tex (lines 28-35):
   - \IEEEauthorblockN{Abhijeet L.M\textsuperscript{1}\thanks{Corresponding author. Email: \texttt{[REQUEST USER: email needed]}}, Leninisha S\textsuperscript{2}}
   - \IEEEauthorblockA{\textsuperscript{1}\textsuperscript{2}School of Computer Science Engineering\\ Vellore Institute of Technology, Chennai\\ Chennai, India\\ \textsuperscript{1}\texttt{[REQUEST USER: email needed]}\\ \textsuperscript{2}\texttt{[REQUEST USER: email needed]}}
   - Placeholder emails are intentionally left unfilled per user decision.
   - No anonymization artifacts ("Anonymous Author(s)" or blinded hedges) remain.

4. Frozen artifacts (9/9 SHA-256 matches original_artifact_shas.json):
   - results/real_run_20260826T065155Z/*.csv (9 files)

5. Confirmed validator results:
   - validate.py: 13/13 PASS
   - validate_ieee.py: 11/11 PASS

6. arXiv category suggestion: cs.DB (to be confirmed at upload time)

================================================================================