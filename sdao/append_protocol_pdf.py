"""Append a planned large-scale experimental protocol to the conference revision."""
from __future__ import annotations

import shutil
import textwrap
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages
from PyPDF2 import PdfReader, PdfWriter

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / "selectivity_driven_hybrid_optimizer_conference_revision.pdf"
OUTPUT = ROOT / "selectivity_driven_hybrid_optimizer_conference_protocol.pdf"
ASSETS = ROOT / "results" / "experimental_protocol"
BACKUP = ROOT / "backups" / "20260802_pre_protocol_append" / SOURCE.name


def make_page(title: str, subtitle: str = "") -> tuple[plt.Figure, plt.Axes]:
    fig, ax = plt.subplots(figsize=(8.27, 11.69))
    ax.set_xlim(0, 1); ax.set_ylim(0, 1); ax.axis("off")
    fig.text(.08, .955, title, fontsize=17, fontweight="bold", va="top")
    if subtitle: fig.text(.08, .925, subtitle, fontsize=9, color="#555555", va="top")
    return fig, ax


def write(ax: plt.Axes, s: str, x: float, y: float, width: int = 91, size: float = 9.3) -> float:
    lines = []
    for p in s.split("\n"):
        lines.extend(textwrap.wrap(p, width=width) or [""])
    ax.text(x, y, "\n".join(lines), va="top", fontsize=size, linespacing=1.45)
    return y - .024 * len(lines)


def build_appendix(path: Path) -> None:
    import csv
    import json

    with PdfPages(path) as pdf:
        fig, ax = make_page("Planned Large-Scale Experimental Protocol", "SDAO validation plan; no future results are claimed in this appendix")
        y = write(ax, "Scope. This protocol extends the preliminary evaluation in §6 into a reproducible systems-validation plan. It specifies acquisition, controls, measurement, and statistical analysis before runs are performed.", .08, .86)
        y = write(ax, "Evaluation goals", .08, y-.04, 75, 12)
        y = write(ax, "1. Determine whether SDAO satisfies a stated filtered-recall target while reducing execution cost relative to fixed physical strategies.\n2. Measure the accuracy and overhead of the selectivity, overlap, and cost estimates.\n3. Separate cold-start, steady-state, and drift behavior.\n4. Compare fairly against exact, native ANN, and PostgreSQL-based baselines.", .08, y-.02)
        y = write(ax, "Primary outcomes", .08, y-.04, 75, 12)
        write(ax, "Filtered Recall@K; result-shortfall rate; median/p95/p99 latency; QPS; planner, execution, and total latency; vectors scanned; index-build time and size; peak memory; cost-model error; and planner regret relative to an offline feasible oracle.", .08, y-.02)
        pdf.savefig(fig, bbox_inches="tight"); plt.close(fig)

        fig, ax = make_page("Datasets and Reproducible Predicate Workloads")
        rows = [["Family", "Role", "Required record"], ["SIFT1M", "Correctness and calibration", "Source, checksum, metric, split"], ["SIFT10M", "Scale, memory, build cost", "Source, checksum, metric, split"], ["DEEP1M", "Cross-distribution validation", "Source, checksum, metric, split"], ["BEIR", "Semantic workload heterogeneity", "Dataset release, encoder, qrels, overlay"]]
        table = ax.table(cellText=rows[1:], colLabels=rows[0], cellLoc="left", colLoc="center", bbox=[.06,.64,.88,.20]); table.auto_set_font_size(False); table.set_fontsize(8)
        y = write(ax, "Predicate overlay", .08, .57, 75, 12)
        y = write(ax, "BEIR does not inherently provide a uniform SQL-filter workload. Use native metadata where available; otherwise generate deterministic, documented attributes from corpus properties such as document-length quantile, source collection, language, or fixed hash bucket. Never derive predicates from relevance labels. For each query/predicate pair, compute filtered exact top-K ground truth and separately report cases with fewer than K eligible documents.", .08, y-.02)
        y = write(ax, "Coverage matrix", .08, y-.04, 75, 12)
        write(ax, "Test equality, range, conjunction, and disjunction predicates across selectivity buckets <0.1\%, 0.1--1\%, 1--5\%, 5--20\%, 20--50\%, and >50\%. Include anti-correlated, approximately independent, and positively correlated predicate--vector regimes.", .08, y-.02)
        pdf.savefig(fig, bbox_inches="tight"); plt.close(fig)

        fig, ax = make_page("Controlled Platform and Measurement Contract")
        y = write(ax, "Reference server specification", .08, .86, 75, 12)
        y = write(ax, "Two AMD EPYC 9554 processors (64 physical cores each), 512 GiB DDR5 ECC memory, high-performance 3.84 TB NVMe storage, Ubuntu 24.04 LTS, and a pinned PostgreSQL/pgvector/hnswlib toolchain. The final artifact must record exact package versions, compiler flags, kernel version, NUMA policy, CPU governor, Docker image digest, and configuration files.", .08, y-.02)
        y = write(ax, "Timing decomposition", .08, y-.04, 75, 12)
        y = write(ax, r"For every query, report $T_{total}=T_{plan}+T_{exec}$, where $T_{plan}=T_{features}+T_{estimator}+T_{cost}+T_{decision}$. Report warm-cache and cold-cache trials separately. Exclude evaluation-only exact-ground-truth construction from online query latency, but report that cost independently.", .08, y-.02)
        y = write(ax, "Load modes", .08, y-.04, 75, 12)
        write(ax, "Use closed-loop latency runs and open-loop QPS runs at controlled client concurrencies of 1, 8, 32, and 128. Pin processes to cores, perform at least 1,000 warm-up queries, and run no unrelated workload.", .08, y-.02)
        pdf.savefig(fig, bbox_inches="tight"); plt.close(fig)

        fig, ax = make_page("Baselines, Tuning, and Oracle Controls")
        rows = [["Method", "Purpose"], ["Exact SQL-first / PRE", "Exact quality and predicate-first control"], ["pgvector exact", "PostgreSQL execution baseline"], ["pgvector HNSW / IVFFlat", "Integrated approximate baselines"], ["hnswlib POST", "Native vector-first post-filter baseline"], ["Filtered hnswlib GRAPH proxy", "Native predicate-filtered traversal proxy"], ["Forced SDAO strategies", "PRE, POST, GRAPH, and ISECT action values"], ["Static histogram selector", "Estimator-free planner control"], ["Offline feasible oracle", "Per-query lower bound and regret reference"]]
        table = ax.table(cellText=rows[1:], colLabels=rows[0], cellLoc="left", colLoc="center", bbox=[.06,.47,.88,.38]); table.auto_set_font_size(False); table.set_fontsize(8)
        write(ax, "Tune all ANN parameters only on a disjoint tuning workload. Fix HNSW construction and search parameters, pgvector settings, and any oversampling cap before final tests. Include ACORN only when the authors' native artifact can be compiled and configured faithfully; otherwise report it as unavailable rather than treating filtered hnswlib as ACORN.", .08, .39)
        pdf.savefig(fig, bbox_inches="tight"); plt.close(fig)

        fig, ax = make_page("Multi-Seed Statistical Validation Pipeline")
        y = write(ax, "Run schedule", .08, .86, 75, 12)
        y = write(ax, "Use at least ten independent seeds. Vary and log data/query generation, index-construction order, estimator initialization, calibration split, and online feedback order. For each seed, execute the same ordered test trace for all paired methods. For online learning, evaluate each query before using its feedback and report cold-start separately from steady state.", .08, y-.02)
        y = write(ax, "Paired analysis", .08, y-.04, 75, 12)
        y = write(ax, "Retain one row per query execution. For baseline b, analyze paired differences ΔT(q) = T(SDAO, q) − T(b, q) and ΔR(q) = R(SDAO, q) − R(b, q). Report mean and median differences, 95% stratified bootstrap confidence intervals, effect sizes, recall-target violation rate, and oracle regret.", .08, y-.02)
        y = write(ax, "Hypothesis testing", .08, y-.04, 75, 12)
        write(ax, "Use a paired t-test only when paired-difference assumptions are defensible; otherwise use a two-sided Wilcoxon signed-rank test. Apply Holm correction across the pre-registered comparisons. Report sample size, test statistic, adjusted p-value, confidence interval, and effect size. Do not claim statistical significance until the planned measurements are collected.", .08, y-.02)
        pdf.savefig(fig, bbox_inches="tight"); plt.close(fig)

        # Planner decision summary page (textual)
        try:
            feasibility_path = ROOT / "results" / "csv" / "planner_feasibility_report.json"
            with feasibility_path.open() as fh: feasibility = json.load(fh)
        except Exception:
            feasibility = {"summary": {"target_recall": None, "planner_behavior": "Unavailable", "notes": "No feasibility report found."}}

        fig, ax = make_page("Planner Decision Summary", "Automated planner decision artifacts generated from latest runs")
        y = write(ax, f"Target recall used: {feasibility['summary'].get('target_recall', 'N/A')}", .08, .86)
        y = write(ax, f"Planner behavior: {feasibility['summary'].get('planner_behavior', 'N/A')}", .08, y-.02)
        y = write(ax, f"Notes: {feasibility['summary'].get('notes', '')}", .08, y-.04)
        pdf.savefig(fig, bbox_inches="tight"); plt.close(fig)

        # Planner decisions bar chart
        try:
            decision_csv = ROOT / "results" / "csv" / "planner_decision_table.csv"
            strategies = {}
            with decision_csv.open() as fh:
                reader = csv.DictReader(fh)
                for row in reader:
                    s = row.get("strategy", "UNKNOWN")
                    try:
                        count = int(row.get("queries", 0))
                    except Exception:
                        count = 0
                    strategies[s] = strategies.get(s, 0) + count

            if strategies:
                fig, ax = make_page("Planner Decisions by Strategy", "Counts of queries for which each strategy was chosen")
                names = list(strategies.keys())
                counts = [strategies[n] for n in names]
                ax.barh(range(len(names)), counts, color=["#2ca02c" if n == "GRAPH" else "#1f77b4" for n in names])
                ax.set_yticks(range(len(names))); ax.set_yticklabels(names)
                ax.set_xlabel("Queries selected")
                pdf.savefig(fig, bbox_inches="tight"); plt.close(fig)
        except Exception:
            # silently continue; appendix remains useful without a chart
            pass

        # Recall vs Latency Pareto curve
        try:
            import numpy as np
            eval_csv = ROOT / "results" / "csv" / "evaluation_results.csv"
            rows = []
            with eval_csv.open() as fh:
                reader = csv.DictReader(fh)
                for row in reader:
                    try:
                        recall = float(row.get("recall_at_10", "nan"))
                        latency = float(row.get("latency_ms", "nan"))
                        strat = row.get("strategy", "UNKNOWN")
                        if not (np.isnan(recall) or np.isnan(latency)):
                            rows.append((strat, recall, latency))
                    except Exception:
                        continue

            if rows:
                fig, ax = make_page("Recall@10 vs Latency (ms)", "Per-query points colored by strategy and Pareto envelope")
                strategies_map = {}
                colors = ["#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd", "#8c564b"]
                for i, (s, r, l) in enumerate(rows):
                    if s not in strategies_map:
                        strategies_map[s] = {"color": colors[len(strategies_map) % len(colors)], "xs": [], "ys": []}
                    strategies_map[s]["xs"].append(r)
                    strategies_map[s]["ys"].append(l)

                for s, data in strategies_map.items():
                    ax.scatter(data["xs"], data["ys"], label=s, c=data["color"], s=18, alpha=0.65)

                # Pareto envelope: for recall threshold r, find min latency among points with recall >= r
                recalls = np.linspace(0.0, 1.0, 101)
                envelope = []
                for rr in recalls:
                    latencies = [l for (_, r, l) in rows if r >= rr]
                    envelope.append(min(latencies) if latencies else np.nan)
                ax.plot(recalls, envelope, c="#000000", lw=1.5, label="Pareto envelope (min latency for recall>=r)")

                ax.set_xlabel("Recall@10")
                ax.set_ylabel("Latency (ms)")
                ax.set_xlim(0.0, 1.01)
                ax.set_ylim(0, max(l for (_, _, l) in rows) * 1.05)
                ax.legend(loc="lower right", fontsize=8)
                pdf.savefig(fig, bbox_inches="tight"); plt.close(fig)
        except Exception:
            # Do not fail the entire appendix generation on plotting errors
            pass


def main() -> None:
    if not SOURCE.exists(): raise FileNotFoundError(SOURCE)
    BACKUP.parent.mkdir(parents=True, exist_ok=True); ASSETS.mkdir(parents=True, exist_ok=True)
    if not BACKUP.exists(): shutil.copy2(SOURCE, BACKUP)
    appendix = ASSETS / "experimental_protocol.pdf"; build_appendix(appendix)
    writer = PdfWriter()
    for document in (SOURCE, appendix):
        for p in PdfReader(str(document)).pages: writer.add_page(p)
    with OUTPUT.open("wb") as f: writer.write(f)
    print(f"Wrote {OUTPUT}")


if __name__ == "__main__": main()
