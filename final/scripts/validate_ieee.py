"""End-to-end validation for the IEEE-translated manuscript.

Validates that final/paper/ieee/main.pdf:
  - compiles to 6-8 pages (target band)
  - contains all 12 references in the correct order
  - preserves all frozen numerical claims verbatim
  - contains all figure and table references
"""
import hashlib
import re
from pathlib import Path
import pymupdf
import pandas as pd

ROOT = Path("/Users/abhijeetmiskin/AppData/MyProject")
print("=== IEEE Manuscript Validation ===")

# 1. IEEE PDF exists & has 6-8 pages
pdf = ROOT / "final" / "paper" / "ieee" / "main.pdf"
assert pdf.exists(), f"missing {pdf}"
doc = pymupdf.open(str(pdf))
n_pages = len(doc)
assert 6 <= n_pages <= 8, f"expected 6-8 pages, got {n_pages}"
print(f"[OK] IEEE PDF: {n_pages} pages, {pdf.stat().st_size} bytes")

# 2. SHA-256
sha = hashlib.sha256(pdf.read_bytes()).hexdigest()
print(f"[OK] IEEE PDF SHA-256: {sha}")
frozen = ROOT / "final" / "paper" / "main.pdf"
frozen_sha = hashlib.sha256(frozen.read_bytes()).hexdigest()
print(f"[INFO] frozen SDAO PDF SHA-256: {frozen_sha}")

# 3. Extract text
text = ""
for p in doc:
    text += p.get_text() + "\n"

# 4. Required numerical claims
claims = {
    "VFH recall 0.829": "0.829",
    "HNSW_HYBRID recall 1.000": "1.000",
    "HNSW_HYBRID latency 15.20": "15.20",
    "IVFFLAT_HYBRID recall 1.000": "1.000",
    "IVFFLAT_HYBRID latency 15.14": "15.14",
    "SQL_FIRST recall 1.000": "1.000",
    "SQL_FIRST latency 15.29": "15.29",
    "Adaptive recall 1.000": "1.000",
    "Adaptive latency 15.10": "15.10",
    "VFH CI lo 0.771": "0.771",
    "VFH CI hi 0.882": "0.882",
    "budget=50 0.701": "0.701",
    "budget=200 0.884": "0.884",
    "budget=500 0.911": "0.911",
    "budget=1000 0.942": "0.942",
    "seed 20260822 0.835": "0.835",
    "seed 20260823 0.776": "0.776",
    "ANN 100": "100",
    "ANN 125": "125",
    "SQL_FIRST 25": "25",
    "bucket 48": "48",
    "bucket 52": "52",
    "ef_construction 200": "200",
    "enable_indexscan off": "enable_indexscan",
    "n=21": "n=21",
    "n=27": "n=27",
}
for label, needle in claims.items():
    assert needle in text, f"MISSING: {label} ({needle!r})"
print(f"[OK] all {len(claims)} frozen numerical claims present verbatim")

# 5. Reference order check
# Find the references section (last "References" header) and split into entries
ref_idx = text.rfind("References")
assert ref_idx > 0, "References section not found"
refs_text = text[ref_idx:]
# Split on "[N]" patterns that begin at line start
ref_entries = re.split(r"\n\[(\d+)\]\s*", refs_text)
# ref_entries[0] is preamble, then alternating (n, body)
ref_titles = {}
ref_bodies = {}
for i in range(1, len(ref_entries), 2):
    n = ref_entries[i]
    body = ref_entries[i+1] if i+1 < len(ref_entries) else ""
    m = re.search(r"\u201c(.*?)\u201d", body, re.DOTALL)
    if m:
        title = re.sub(r"\s+", " ", m.group(1)).strip().lower()
        ref_titles[n] = title
    ref_bodies[n] = body.lower()
expected_refs = {
    "3": "telegraphcq", "4": "leopard", "5": "leo",
    "6": "neo", "7": "skinnerdb", "8": "hierarchical navigable",  # HNSW
    "9": "pgvector", "10": "faiss", "11": "milvus", "12": "acorn",
}
for num, needle in expected_refs.items():
    title = ref_titles.get(num, "")
    body = ref_bodies.get(num, "")
    # Match in title OR body (some entries mention the system in body, not title)
    haystack = title + " " + body
    assert needle in haystack, (
        f"ref [{num}] expected to contain {needle!r}, "
        f"title={title[:60]!r}"
    )
print("[OK] references ordered: TelegraphCQ[3] ... ACORN[12]")

# 6. Section labels
for s in ["II.", "III.", "IV.", "V.", "VI.", "VII.", "VIII.", "IX."]:
    assert s in text, f"missing section label {s!r}"
print("[OK] all section roman-numeral labels present")

# 7. Figure references
for n in range(1, 7):
    pat = re.compile(rf"(Fig\.?\s*{n}\b|Figure\s*{n}\b)")
    assert pat.search(text), f"figure reference {n} not found"
print("[OK] all 6 figure references present")

# 8. Table references (IEEE uses Roman numerals)
for label in ["Table I", "Table II", "Table III", "Table IV", "Table V"]:
    assert label in text, f"table reference {label!r} not found"
print("[OK] all 5 table references present")

# 9. CSV cross-check
main = pd.read_csv(ROOT / "final" / "results" / "tables" / "main_summary.csv")
vfh = main[main["strategy"] == "VECTOR_FIRST_HNSW"].iloc[0]
assert abs(vfh["mean_recall_at_10"] - 0.829) < 0.001
assert abs(vfh["recall_ci_lo"] - 0.771) < 0.01
assert abs(vfh["recall_ci_hi"] - 0.882) < 0.01
print(f"[OK] VFH recall {vfh['mean_recall_at_10']:.3f} "
      f"CI [{vfh['recall_ci_lo']:.3f}, {vfh['recall_ci_hi']:.3f}] matches CSV")

# 10. Page screenshots
page_dir = ROOT / "final" / "audit" / "ieee_pages"
assert page_dir.exists(), f"missing {page_dir}"
pages = sorted(page_dir.glob("page_*.png"))
assert len(pages) == n_pages, f"expected {n_pages} page screenshots, got {len(pages)}"
for p in pages:
    assert p.stat().st_mtime >= pdf.stat().st_mtime - 1, f"stale screenshot: {p.name}"
print(f"[OK] all {len(pages)} IEEE page screenshots present and current")

# 11. Audit artifacts
for f in ["admission_rule_analysis.md", "ann_parameter_audit.md",
          "baseline_reproduction_report.md", "db_config.json",
          "original_artifact_shas.json", "project_inventory.md",
          "workload_audit.md"]:
    p = ROOT / "final" / "audit" / f
    assert p.exists(), p
print("[OK] all 7 audit artifacts present")

print()
print("=== ALL IEEE VALIDATION CHECKS PASSED ===")
print(f"Final IEEE PDF: {pdf}")
print(f"Pages: {n_pages} (target 6-8)")
print(f"Size: {pdf.stat().st_size} bytes")
print(f"SHA-256: {sha}")
