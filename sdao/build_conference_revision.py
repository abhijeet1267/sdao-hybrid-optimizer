"""Build a claim-preserving conference-revision companion for the PDF-only manuscript."""
from __future__ import annotations

import shutil
import textwrap
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch
from PyPDF2 import PdfReader, PdfWriter

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / "selectivity_driven_hybrid_optimizer_final.pdf"
OUTPUT = ROOT / "selectivity_driven_hybrid_optimizer_conference_revision.pdf"
ASSETS = ROOT / "results" / "conference_revision"
BACKUP = ROOT / "backups" / "20260802_pre_conference_revision" / SOURCE.name


def page(title: str, subtitle: str = "") -> tuple[plt.Figure, plt.Axes]:
    fig, ax = plt.subplots(figsize=(8.27, 11.69))
    ax.set_xlim(0, 1); ax.set_ylim(0, 1); ax.axis("off")
    fig.text(.08, .955, title, fontsize=17, fontweight="bold", va="top")
    if subtitle: fig.text(.08, .925, subtitle, fontsize=9, color="#555555", va="top")
    return fig, ax


def text(ax: plt.Axes, body: str, x: float, y: float, width: int = 94, size: float = 9.5) -> float:
    lines = []
    for paragraph in body.split("\n"):
        lines.extend(textwrap.wrap(paragraph, width=width) or [""])
    ax.text(x, y, "\n".join(lines), va="top", ha="left", fontsize=size, linespacing=1.45)
    return y - .024 * len(lines)


def box(ax: plt.Axes, x: float, y: float, label: str, color: str = "#e8f1fb") -> None:
    ax.add_patch(FancyBboxPatch((x-.17, y-.03), .34, .06, boxstyle="round,pad=0.012", facecolor=color, edgecolor="#2b5d8a", linewidth=1.2))
    ax.text(x, y, label, ha="center", va="center", fontsize=9, fontweight="bold")


def arrow(ax: plt.Axes, y1: float, y2: float, x: float = .50) -> None:
    ax.add_patch(FancyArrowPatch((x, y1), (x, y2), arrowstyle="-|>", mutation_scale=13, linewidth=1.2, color="#2b5d8a"))


def workflow_figure() -> Path:
    fig, ax = plt.subplots(figsize=(7.2, 10.0)); ax.set_xlim(0, 1); ax.set_ylim(0, 1); ax.axis("off")
    fig.suptitle("SDAO Adaptive Planning and Feedback Workflow", fontsize=16, fontweight="bold", y=.98)
    labels = ["Incoming hybrid query", "Feature extraction", "Learned selectivity estimator", "Cost model", "Adaptive planner", "Choose strategy\nPRE  |  POST  |  GRAPH  |  ISECT", "Execute query", "Collect feedback", "Update estimator"]
    ys = [.89, .79, .69, .59, .49, .37, .25, .15, .06]
    for label, y in zip(labels, ys): box(ax, .5, y, label, "#dceefb" if "strategy" not in label else "#e4f4df")
    for y1, y2 in zip(ys[:-1], ys[1:]): arrow(ax, y1-.035, y2+.035)
    ax.add_patch(FancyArrowPatch((.32,.06), (.22,.69), connectionstyle="arc3,rad=.35", arrowstyle="-|>", mutation_scale=13, color="#4b7d3f", linewidth=1.2))
    ax.text(.07, .39, "online\nfeedback", color="#4b7d3f", fontsize=9, ha="center")
    path = ASSETS / "sdao_workflow.pdf"; fig.savefig(path, bbox_inches="tight"); plt.close(fig); return path


def experiment_figure() -> Path:
    fig, ax = plt.subplots(figsize=(10, 3.2)); ax.set_xlim(0, 1); ax.set_ylim(0, 1); ax.axis("off")
    fig.suptitle("Experimental Evaluation Flow", fontsize=15, fontweight="bold", y=.98)
    labels = ["Dataset", "Generate\nqueries", "Estimator", "Planner", "Strategy", "Execution", "Metrics", "Feedback", "Model\nupdate"]
    xs = [.08,.19,.30,.40,.50,.61,.72,.83,.94]
    for x, label in zip(xs, labels):
        ax.add_patch(FancyBboxPatch((x-.045,.40),.09,.18,boxstyle="round,pad=.01",facecolor="#e8f1fb",edgecolor="#2b5d8a")); ax.text(x,.49,label,ha="center",va="center",fontsize=8,fontweight="bold")
    for x1,x2 in zip(xs[:-1],xs[1:]): ax.add_patch(FancyArrowPatch((x1+.047,.49),(x2-.047,.49),arrowstyle="-|>",mutation_scale=11,color="#2b5d8a"))
    path=ASSETS / "experiment_flow.pdf"; fig.savefig(path,bbox_inches="tight"); plt.close(fig); return path


def supplement(path: Path, workflow: Path, experiment: Path) -> None:
    with PdfPages(path) as pdf:
        fig, ax = page("Conference-Revision Supplement", "Claim-preserving editorial material for integration into the editable manuscript")
        y = text(ax, "Purpose. This supplement improves presentation and records the sections required for a conference revision without changing the paper's algorithm, contributions, datasets, or reported numerical results. It is appended because the available manuscript is PDF-only; no editable source was supplied.", .08, .86)
        y = text(ax, "Editorial actions for the source manuscript", .08, y-.035, 75, 12)
        text(ax, "• Apply one term consistently: “predicate-aware graph traversal” (GRAPH).\n• Define every symbol before its first use and retain Table 2 as the notation authority.\n• Replace unfinished cross-references such as “§??” with a resolved section reference before submission.\n• Repair the malformed illustrative query in the abstract and motivating example from the source; its omitted predicate text cannot be reconstructed safely from the PDF alone.\n• Use sentence-case captions that state the metric, workload, backend, and whether values are means, medians, or confidence intervals.\n• Keep reported prototype results separate from planned million-scale evaluations.", .08, y-.02)
        pdf.savefig(fig, bbox_inches="tight"); plt.close(fig)

        fig, ax = page("Figure Placement and Captions")
        text(ax, "Insert Figure A after §4.1 (Architecture Overview) and Figure B at the beginning of §6 (Evaluation). Both diagrams are vector PDFs and use a consistent blue/green palette, aligned arrows, and readable conference-paper typography.", .08, .86)
        text(ax, "Suggested captions", .08, .74, 75, 12)
        text(ax, "Figure A. SDAO adaptive-planning workflow. Structured-predicate and vector-density features feed the estimator and cost model; the planner selects one physical strategy and logs feedback for later estimator updates.\n\nFigure B. Evaluation pipeline. The dataset and generated query workload are processed by the estimator and planner, executed under a selected strategy, measured, and returned to the feedback path.", .08, .68)
        pdf.savefig(fig, bbox_inches="tight"); plt.close(fig)

        fig, ax = page("6.x Ablation Study (Planned Evaluation)")
        text(ax, "Experiment design. Hold the dataset, query set, ANN parameters, and target recall constant. Compare the full SDAO configuration with one component removed at a time. Report mean and median latency, filtered Recall@10, vectors scanned, planning latency, and memory overhead. Use the same query seeds across variants.", .08, .86)
        rows = [["Variant", "Purpose", "Latency", "Recall@10", "Scans", "Status"], ["Full SDAO", "Reference configuration", "To be measured", "To be measured", "To be measured", "Planned"], ["Without estimator", "Static/selectivity baseline", "To be measured", "To be measured", "To be measured", "Planned"], ["Without online learning", "Isolate feedback updates", "To be measured", "To be measured", "To be measured", "Planned"], ["Without GRAPH", "Assess graph action", "To be measured", "To be measured", "To be measured", "Planned"], ["Without ISECT", "Assess intersection action", "To be measured", "To be measured", "To be measured", "Planned"], ["Without adaptive planner", "Fixed-strategy control", "To be measured", "To be measured", "To be measured", "Planned"]]
        table = ax.table(cellText=rows[1:], colLabels=rows[0], cellLoc="center", colLoc="center", bbox=[.05,.36,.90,.38]); table.auto_set_font_size(False); table.set_fontsize(7.7)
        text(ax, "Results will be reported after implementation. This table is intentionally a template: no values are inferred from existing experiments.", .08, .28)
        pdf.savefig(fig, bbox_inches="tight"); plt.close(fig)

        fig, ax = page("Memory, Planner, and Statistical Evaluation")
        y = text(ax, "Memory Overhead", .08, .86, 75, 12)
        y = text(ax, "Measure resident and peak memory separately for the estimator parameters, per-attribute histograms, planner state, online training buffer, and feature cache. Report both absolute bytes and incremental bytes over the vector-index baseline at each dataset scale. Memory measurements are left for future evaluation.", .08, y-.02)
        y = text(ax, "Planner Overhead", .08, y-.04, 75, 12)
        y = text(ax, "Instrument feature extraction, selectivity estimation, cost evaluation, strategy decision, and total optimizer overhead with monotonic timers. Report warm and cold-cache distributions. Planner overhead will be evaluated in future work.", .08, y-.02)
        y = text(ax, "Statistical Evaluation Plan", .08, y-.04, 75, 12)
        text(ax, "For planned evaluations, use multiple independent seeds and report 95% confidence intervals. Compare paired query outcomes with a paired t-test when normality is supported; otherwise use a Wilcoxon signed-rank test. Apply a stated multiple-comparison correction where several strategies are tested. No p-values or significance claims are made until these measurements are collected.", .08, y-.02)
        pdf.savefig(fig, bbox_inches="tight"); plt.close(fig)

        fig, ax = page("Threats to Validity and Future Evaluation")
        y = text(ax, "Threats to Validity", .08, .86, 75, 12)
        y = text(ax, "Internal validity: the current workload is synthetic and the system is a prototype; parameter tuning may affect outcomes. External validity: the design is discussed in the context of PostgreSQL and limited datasets, so generalization to other engines and data distributions remains to be evaluated. Construct validity: Recall@10 and latency capture important but incomplete behavior; workload diversity, tail latency, update cost, and resource isolation require additional study.", .08, y-.02)
        y = text(ax, "Future Work", .08, y-.04, 75, 12)
        y = text(ax, "Planned evaluations include million-scale datasets, real PostgreSQL integration, direct pgvector and ACORN comparisons, cloud deployment, distributed execution, join optimization, and adaptive threshold learning. These are evaluation and implementation plans, not completed results.", .08, y-.02)
        y = text(ax, "Related-work framing", .08, y-.04, 75, 12)
        text(ax, "Position SDAO as complementary to learned-optimization systems (Bao, Neo, NeuroCard), integrated vector systems (pgvector and PostgreSQL-V), and filtered ANN systems (ACORN, NaviX, SERF, and iRangeGraph). The distinction is the proposed selectivity-conditioned, adaptive strategy-selection layer; avoid implying head-to-head performance unless directly measured.", .08, y-.02)
        pdf.savefig(fig, bbox_inches="tight"); plt.close(fig)

        fig, ax = page("Revision Record and Remaining Submission Risks")
        text(ax, "Changes supplied in this revision package", .08, .86, 75, 12)
        y = text(ax, "• Two publication-quality vector diagrams with consistent visual language.\n• A claim-preserving ablation-study template and methodology.\n• Explicit memory, planner-overhead, and statistical-evaluation plans.\n• A threats-to-validity section and expanded future-evaluation roadmap.\n• A source-level editorial checklist for consistency, captions, notation, and unresolved references.", .08, .81)
        text(ax, "Remaining weaknesses requiring future experiments", .08, y-.04, 75, 12)
        text(ax, "The PDF-only source prevents a safe line-by-line prose rewrite, bibliographic reformatting, and replacement of malformed source text. The existing paper must retain its reported results; production-scale comparisons, direct external-baseline experiments, memory measurements, planning-overhead measurements, ablations, and statistical tests remain to be performed before a final conference submission.", .08, y-.09)
        pdf.savefig(fig, bbox_inches="tight"); plt.close(fig)


def main() -> None:
    if not SOURCE.exists(): raise FileNotFoundError(SOURCE)
    ASSETS.mkdir(parents=True, exist_ok=True); BACKUP.parent.mkdir(parents=True, exist_ok=True)
    if not BACKUP.exists(): shutil.copy2(SOURCE, BACKUP)
    # PNG copies are used only for the placement-preview page; PDFs remain the publication artifacts.
    workflow, experiment = workflow_figure(), experiment_figure()
    supplement_pdf = ASSETS / "editorial_supplement.pdf"; supplement(supplement_pdf, workflow, experiment)
    writer = PdfWriter()
    for document in (SOURCE, workflow, experiment, supplement_pdf):
        for p in PdfReader(str(document)).pages: writer.add_page(p)
    with OUTPUT.open("wb") as f: writer.write(f)
    print(f"Wrote {OUTPUT}")


if __name__ == "__main__": main()
