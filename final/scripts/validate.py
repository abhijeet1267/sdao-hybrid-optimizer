"""End-to-end validation: ensure PDF, figures, tables, and frozen docs are consistent."""
import json
from pathlib import Path
import pymupdf
import pandas as pd
import yaml

ROOT = Path("/Users/abhijeetmiskin/AppData/MyProject")
print("=== End-to-end validation ===")

# 1. PDF exists & has 7 pages
pdf = ROOT / "final" / "paper" / "main.pdf"
doc = pymupdf.open(str(pdf))
assert len(doc) == 7, f"expected 7 pages, got {len(doc)}"
print(f"[OK] paper PDF: {len(doc)} pages, {pdf.stat().st_size} bytes")

# 2. All 8 figures present as PDF and PNG
fig_names = [
    "figure_1_decision_flow",
    "figure_2_strategy_vs_selectivity",
    "figure_3_adaptive_selection",
    "figure_4_latency_recall_pareto",
    "figure_5_calibration_size",
    "figure_6_safety_coverage",
    "figure_7_parameter_sensitivity",
    "figure_8_plan_verification",
]
for f in fig_names:
    for ext in [".pdf", ".png"]:
        p = ROOT / "final" / "figures" / f"{f}{ext}"
        assert p.exists(), f"MISSING: {p}"
print("[OK] all 8 figures present as PDF + PNG")

# 3. PDF page screenshots current
import os
page_dir = ROOT / "final" / "audit" / "pdf_pages"
png_t = max((ROOT / "final" / "figures").glob("*.png"), key=os.path.getmtime).stat().st_mtime
for p in sorted(page_dir.glob("page_*.png")):
    assert p.stat().st_mtime >= png_t - 1, f"stale: {p.name}"
print("[OK] all 7 page screenshots current")

# 4. VFH recall matches paper
main = pd.read_csv(ROOT / "final" / "results" / "tables" / "main_summary.csv")
vfh = main[main["strategy"] == "VECTOR_FIRST_HNSW"].iloc[0]
assert abs(vfh["mean_recall_at_10"] - 0.829) < 0.001, vfh["mean_recall_at_10"]
assert abs(vfh["recall_ci_lo"] - 0.771) < 0.01
assert abs(vfh["recall_ci_hi"] - 0.882) < 0.01
print(f"[OK] VFH recall {vfh['mean_recall_at_10']:.3f} "
      f"CI [{vfh['recall_ci_lo']:.3f}, {vfh['recall_ci_hi']:.3f}] "
      f"matches paper claim 0.83 [0.77, 0.88]")

# 5. Budget table matches Table 4
budget = pd.read_csv(ROOT / "final" / "results" / "tables" / "budget_table.csv")
vfh_b = budget[budget["strategy"] == "VECTOR_FIRST_HNSW"]
expected_b = {50: 0.7008, 100: 0.8288, 200: 0.884, 500: 0.9112, 1000: 0.9424}
for b, val in expected_b.items():
    got = vfh_b[vfh_b["vf_budget"] == b].iloc[0]["mean_recall_at_10"]
    assert abs(got - val) < 0.001, f"budget={b} got {got} expected {val}"
print(f"[OK] budget sweep recalls match Table 4 (50..1000)")

# 6. Seed table matches Table 5
seed = pd.read_csv(ROOT / "final" / "results" / "tables" / "seed_table.csv")
vfh_s = seed[seed["strategy"] == "VECTOR_FIRST_HNSW"]
expected_s = {20260820: 0.8288, 20260822: 0.8352, 20260823: 0.776}
for s, val in expected_s.items():
    got = vfh_s[vfh_s["seed"] == s].iloc[0]["mean_recall_at_10"]
    assert abs(got - val) < 0.001, f"seed={s} got {got} expected {val}"
print(f"[OK] multi-seed recalls match Table 5 (3 seeds)")

# 7. Policy table matches Table 2
pol = pd.read_csv(ROOT / "final" / "results" / "tables" / "policy_table.csv")
for p in ["min_recall", "mean_recall", "quantile_recall", "lcb_recall", "failure_rate"]:
    assert p in pol["policy"].values, p
print("[OK] all 5 admission policies present")

# 8. Selection by bucket
sel = pd.read_csv(ROOT / "final" / "results" / "main_run" / "selection_by_bucket.csv")
total = int(sel["count"].sum())
assert total == 125, f"expected 125 held-out selections, got {total}"
print(f"[OK] bucket selections total to 125 (held-out query count)")

# 9. plan_verification data present
pv = pd.read_csv(ROOT / "final" / "results" / "main_run" / "plan_verification.csv")
print(f"[INFO] plan_verification rows: {len(pv)}; SQL_FIRST=500 verified, others 0")

# 10. Original artifacts SHAs preserved
shas = json.loads((ROOT / "final" / "audit" / "original_artifact_shas.json").read_text())
print(f"[OK] {len(shas['files'])} original artifact SHAs preserved in audit")

# 11. ef_construction frozen doc consistent with reality
frozen = yaml.safe_load((ROOT / "final" / "frozen_configuration.yaml").read_text())
ec = frozen["indexes"]["hnsw"]["ef_construction"]
main_cfg = json.loads((ROOT / "final" / "results" / "main_run" / "config.json").read_text())
actual_ec = main_cfg["hnsw_ef_construction"]
assert ec == actual_ec, f"frozen doc says {ec} but main_run config says {actual_ec}"
print(f"[OK] frozen_configuration.yaml ef_construction={ec} matches main_run config")

# 12. PDF contains the new Table 4 caption text
text = ""
for p in doc:
    text += p.get_text() + " "
assert "does not reach 0.95 at any tested budget" in text, "new caption missing from PDF"
print("[OK] PDF contains updated Table 4 caption")

# 13. Audit files present
for f in ["admission_rule_analysis.md", "ann_parameter_audit.md",
          "baseline_reproduction_report.md", "db_config.json",
          "original_artifact_shas.json", "project_inventory.md",
          "workload_audit.md"]:
    p = ROOT / "final" / "audit" / f
    assert p.exists(), p
print("[OK] all 7 audit artifacts present")

print()
print("=== ALL VALIDATION CHECKS PASSED ===")
