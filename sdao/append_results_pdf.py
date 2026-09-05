"""Append reproducible SDAO experimental results to the conference-paper PDF."""
from __future__ import annotations

import shutil
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.image as mpimg
import matplotlib.pyplot as plt
import pandas as pd
from matplotlib.backends.backend_pdf import PdfPages
from PyPDF2 import PdfReader, PdfWriter


SDAO_DIR = Path(__file__).resolve().parent
SOURCE = SDAO_DIR / "selectivity_driven_hybrid_optimizer_final.pdf"
RESULTS = SDAO_DIR / "results"
OUTPUT = SDAO_DIR / "selectivity_driven_hybrid_optimizer_with_results.pdf"
BACKUP = SDAO_DIR / "backups" / "20260802_pre_results_append" / SOURCE.name


def _add_title(page: plt.Figure, title: str, subtitle: str = "") -> None:
    page.text(0.5, 0.94, title, ha="center", va="top", fontsize=18, fontweight="bold")
    if subtitle:
        page.text(0.5, 0.90, subtitle, ha="center", va="top", fontsize=10, color="#444444")


def build_results_appendix(path: Path) -> None:
    comparison = pd.read_csv(RESULTS / "csv" / "strategy_comparison_summary.csv")
    adaptive = pd.read_csv(RESULTS / "csv" / "summary_metrics.csv")
    with PdfPages(path) as pdf:
        fig = plt.figure(figsize=(8.27, 11.69))
        _add_title(fig, "Experimental Results", "SIFT1M hybrid SQL–vector workload; k = 10")
        fig.text(0.10, 0.83, "Evaluation protocol", fontsize=13, fontweight="bold")
        fig.text(0.10, 0.73, "• 32 generated hybrid predicates, each paired with a SIFT query vector.\n"
                 "• PRE, POST, GRAPH, and ISECT were evaluated on every query (128 executions).\n"
                 "• Recall@10 is measured against exact top-k results within the predicate-qualified set.\n"
                 "• Latency is end-to-end wall-clock time; vector scans are the HNSW probe budget or exact candidates.", fontsize=10, linespacing=1.7)
        fig.text(0.10, 0.55, "Forced-strategy comparison", fontsize=13, fontweight="bold")
        table = fig.add_axes([0.08, 0.34, 0.84, 0.16]); table.axis("off")
        display = comparison[["strategy", "latency_ms_mean", "recall_at_10_mean", "vectors_scanned_mean"]].copy()
        display.columns = ["Strategy", "Mean latency (ms)", "Mean Recall@10", "Mean vectors scanned"]
        display["Mean latency (ms)"] = display["Mean latency (ms)"].map("{:.2f}".format)
        display["Mean Recall@10"] = display["Mean Recall@10"].map("{:.3f}".format)
        display["Mean vectors scanned"] = display["Mean vectors scanned"].map("{:.0f}".format)
        rendered = table.table(cellText=display.values, colLabels=display.columns, loc="center", cellLoc="center")
        rendered.auto_set_font_size(False); rendered.set_fontsize(9); rendered.scale(1, 1.7)
        fig.text(0.10, 0.21, "Adaptive planner outcome", fontsize=13, fontweight="bold")
        row = adaptive.iloc[0]
        fig.text(0.10, 0.13, f"The calibrated planner selected {row.strategy} for all 32 workload queries. "
                 f"It achieved mean filtered Recall@10 = {row.recall_at_10_mean:.3f}, "
                 f"mean latency = {row.latency_ms_mean:.2f} ms, and mean probes = {row.vectors_scanned_mean:.0f}.", fontsize=10, wrap=True)
        pdf.savefig(fig, bbox_inches="tight"); plt.close(fig)

        for title, filenames in [
            ("Latency and Recall versus Predicate Selectivity", ["latency_vs_selectivity.png", "recall_vs_selectivity.png"]),
            ("Planner Decisions and Execution Cost", ["planner_decisions.png", "execution_cost.png"]),
        ]:
            fig, axes = plt.subplots(2, 1, figsize=(8.27, 11.69))
            fig.suptitle(title, fontsize=17, fontweight="bold", y=.97)
            for axis, filename in zip(axes, filenames):
                axis.imshow(mpimg.imread(RESULTS / "plots" / filename)); axis.axis("off")
            fig.tight_layout(rect=(0, 0, 1, .94)); pdf.savefig(fig, bbox_inches="tight"); plt.close(fig)


def main() -> None:
    if not SOURCE.is_file():
        raise FileNotFoundError(SOURCE)
    BACKUP.parent.mkdir(parents=True, exist_ok=True)
    if not BACKUP.exists():
        shutil.copy2(SOURCE, BACKUP)
    appendix = RESULTS / "sdao_results_appendix.pdf"
    build_results_appendix(appendix)
    writer = PdfWriter()
    for document in (SOURCE, appendix):
        for page in PdfReader(str(document)).pages:
            writer.add_page(page)
    with OUTPUT.open("wb") as stream:
        writer.write(stream)
    print(f"Wrote {OUTPUT}")
    print(f"Preserved original at {BACKUP}")


if __name__ == "__main__":
    main()
