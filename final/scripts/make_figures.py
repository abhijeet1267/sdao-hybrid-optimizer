"""Generate publication-quality figures for the SDAO paper."""
import json
from ast import literal_eval
from pathlib import Path
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
ROOT = Path("/Users/abhijeetmiskin/AppData/MyProject")
RES = ROOT / "final" / "results"
FIG = ROOT / "final" / "figures"
FIG.mkdir(parents=True, exist_ok=True)
plt.rcParams["font.family"] = "DejaVu Sans"
plt.rcParams["font.size"] = 9
STRATEGIES = ["SQL_FIRST", "VECTOR_FIRST_HNSW", "HNSW_HYBRID", "IVFFLAT_HYBRID"]
COLORS = {"SQL_FIRST": "#888888", "VECTOR_FIRST_HNSW": "#d62728",
          "HNSW_HYBRID": "#1f77b4", "IVFFLAT_HYBRID": "#ff7f0e"}
def fig1_decision_flow():
    fig, ax = plt.subplots(figsize=(6.5, 8))
    ax.set_xlim(0, 10); ax.set_ylim(0, 14); ax.axis("off")
    ax.set_title("Figure 1: Adaptive Decision Flow", fontsize=11)
    boxes = [
        (1, 13, "Hybrid SQL+Vector Query Q", "#cce5ff"),
        (1, 11, "EXPLAIN (FORMAT JSON) selectivity estimate s", "#cce5ff"),
        (1, 9, "bucket b = bucket(s)", "#cce5ff"),
        (1, 7, "Look up calibration statistics for b", "#cce5ff"),
        (4.5, 7, "Compute per-strategy admission statistic", "#fff2cc"),
        (4.5, 5, "Apply admission policy (min_recall, etc.)", "#fff2cc"),
        (4.5, 3, "F(b) = {SQL_FIRST} U feasible ANN strategies", "#fff2cc"),
        (4.5, 1, "argmin median calibrated latency", "#d5e8d4"),
    ]
    for x, y, text, color in boxes:
        rect = plt.Rectangle((x, y-0.4), 2.6, 0.8, facecolor=color, edgecolor="black")
        ax.add_patch(rect)
        ax.text(x+1.3, y, text, ha="center", va="center", fontsize=8)
    arrows = [(2.3, 12.6, 2.3, 11.4), (2.3, 10.6, 2.3, 9.4),
              (2.3, 8.6, 2.3, 7.4), (3.6, 7, 4.5, 7),
              (5.8, 6.6, 5.8, 5.4), (5.8, 4.6, 5.8, 3.4),
              (5.8, 2.6, 5.8, 1.4)]
    for x1, y1, x2, y2 in arrows:
        ax.annotate("", xy=(x2, y2), xytext=(x1, y1),
                    arrowprops=dict(arrowstyle="->", color="black", lw=1))
    ax.text(0.2, 13.5, "Input", fontsize=9, color="#0066cc", fontweight="bold")
    ax.text(3.4, 7.5, "Decision", fontsize=9, color="#cc8800", fontweight="bold")
    plt.tight_layout()
    plt.savefig(FIG / "figure_1_decision_flow.pdf", bbox_inches="tight")
    plt.close()
    print("Wrote figure_1_decision_flow.pdf")


def fig2_strategy_vs_selectivity():
    main = pd.read_csv(RES / "main_run" / "per_query.csv")
    fig, axes = plt.subplots(1, 2, figsize=(7, 3.2))
    for ax, metric, title, ylabel in [
        (axes[0], "median_latency_ms", "Latency", "Median latency (ms)"),
        (axes[1], "recall_at_10", "Recall@10", "Recall@10"),
    ]:
        for strat in STRATEGIES:
            sub = main[main["strategy"] == strat]
            ax.scatter(sub["estimated_selectivity"], sub[metric],
                       s=10, alpha=0.4, color=COLORS[strat], label=strat)
        ax.set_xlim(-0.05, 1.05)
        ax.set_xlabel("EXPLAIN estimated selectivity")
        ax.set_ylabel(ylabel)
        ax.set_title(title)
        if metric == "median_latency_ms":
            ax.set_yscale("log")
        ax.grid(True, alpha=0.3)
        ax.legend(loc="best", fontsize=7)
    plt.tight_layout()
    plt.savefig(FIG / "figure_2_strategy_vs_selectivity.pdf", bbox_inches="tight")
    plt.close()
    print("Wrote figure_2_strategy_vs_selectivity.pdf")


def fig3_adaptive_selection():
    sel = pd.read_csv(RES / "main_run" / "selection_by_bucket.csv")
    fig, ax = plt.subplots(figsize=(6.5, 3.2))
    buckets = sorted(sel["bucket"].unique())
    bottom = np.zeros(len(buckets))
    for strat in STRATEGIES:
        counts = []
        for b in buckets:
            row = sel[(sel["bucket"] == b) & (sel["adaptive_selected"] == strat)]
            counts.append(int(row["count"].iloc[0]) if len(row) else 0)
        ax.bar(buckets, counts, bottom=bottom, label=strat, color=COLORS[strat])
        bottom += np.array(counts)
    ax.set_xlabel("Selectivity bucket")
    ax.set_ylabel("Number of queries")
    ax.set_title("Adaptive selection by selectivity bucket")
    ax.legend(loc="best", fontsize=8)
    plt.xticks(rotation=20, ha="right")
    plt.tight_layout()
    plt.savefig(FIG / "figure_3_adaptive_selection.pdf", bbox_inches="tight")
    plt.close()
    print("Wrote figure_3_adaptive_selection.pdf")


def fig4_latency_recall_pareto():
    fig, ax = plt.subplots(figsize=(6.5, 3.5))
    main = pd.read_csv(RES / "main_run" / "summary.csv")
    for _, row in main.iterrows():
        if row["strategy"] == "Adaptive": continue
        ax.scatter(row["mean_latency_ms"], row["mean_recall_at_10"],
                   s=120, color=COLORS[row["strategy"]], edgecolor="black",
                   label=row["strategy"], zorder=3)
        ax.annotate(row["strategy"], (row["mean_latency_ms"], row["mean_recall_at_10"]),
                    xytext=(5, 5), textcoords="offset points", fontsize=7)
    budget_rows = []
    for d in sorted(RES.glob("budget_*")):
        budget = int(d.name.split("_")[1])
        s = pd.read_csv(d / "summary.csv")
        for _, r in s.iterrows():
            if r["strategy"] == "VECTOR_FIRST_HNSW":
                budget_rows.append({"budget": budget, "lat": r["mean_latency_ms"],
                                    "rec": r["mean_recall_at_10"]})
    budget_df = pd.DataFrame(budget_rows).sort_values("budget")
    if len(budget_df) > 0:
        ax.plot(budget_df["lat"], budget_df["rec"], "-o", color="#d62728",
                alpha=0.6, markersize=4, label="VFH budget sweep", zorder=2)
        for _, r in budget_df.iterrows():
            ax.annotate(f"b={int(r['budget'])}", (r["lat"], r["rec"]),
                        xytext=(3, -8), textcoords="offset points", fontsize=6,
                        color="#d62728")
    ax.axhline(0.95, color="black", linestyle="--", alpha=0.5,
               label="Target Recall@10 = 0.95")
    ax.set_xlabel("Mean latency (ms)")
    ax.set_ylabel("Mean Recall@10")
    ax.set_title("Latency-Recall Pareto frontier")
    ax.legend(loc="lower right", fontsize=7)
    ax.set_ylim(0.6, 1.05)
    ax.grid(True, alpha=0.3)
    plt.tight_layout()
    plt.savefig(FIG / "figure_4_latency_recall_pareto.pdf", bbox_inches="tight")
    plt.close()
    print("Wrote figure_4_latency_recall_pareto.pdf")


def fig5_calibration_size():
    raw = json.loads((RES / "main_run" / "calibration_map.json").read_text())
    cal = {}
    for k, v in raw.items():
        key = literal_eval(k); cal[key] = v
    fig, ax = plt.subplots(figsize=(6.5, 3.5))
    bucket_ns = {}
    for (strat, bucket), v in cal.items():
        if strat == "SQL_FIRST":
            bucket_ns[bucket] = v["n"]
    buckets = sorted(bucket_ns.keys())
    n_values = [bucket_ns[b] for b in buckets]
    ax.bar(buckets, n_values, color="#1f77b4", alpha=0.7)
    for b, n in zip(buckets, n_values):
        ax.text(b, n + 1, str(n), ha="center", fontsize=8)
    ax.set_ylabel("Calibration observations per bucket")
    ax.set_xlabel("Selectivity bucket")
    ax.set_title("Calibration size per bucket")
    plt.xticks(rotation=20, ha="right")
    plt.tight_layout()
    plt.savefig(FIG / "figure_5_calibration_size.pdf", bbox_inches="tight")
    plt.close()
    print("Wrote figure_5_calibration_size.pdf")


def fig6_safety_coverage_tradeoff():
    pol = pd.read_csv(RES / "main_run" / "policy_comparison.csv")
    fig, ax = plt.subplots(figsize=(6.5, 3.5))
    for _, row in pol.iterrows():
        ann_pct = float(row["ann_pct"])
        mean_lat = float(row["mean_latency_ms"])
        ax.scatter(ann_pct, mean_lat, s=120)
        ax.annotate(row["policy"], (ann_pct, mean_lat),
                    xytext=(5, 5), textcoords="offset points", fontsize=8)
    ax.set_xlabel("ANN selection rate (%)")
    ax.set_ylabel("Mean adaptive latency (ms)")
    ax.set_title("Safety-coverage tradeoff across admission policies")
    ax.grid(True, alpha=0.3)
    plt.tight_layout()
    plt.savefig(FIG / "figure_6_safety_coverage.pdf", bbox_inches="tight")
    plt.close()
    print("Wrote figure_6_safety_coverage.pdf")



def fig7_parameter_sensitivity():
    rows = []
    for d in sorted(RES.glob("sweep_*")):
        ef = int(d.name.split("ef")[1].split("_")[0])
        pr = int(d.name.split("probes")[1])
        s = pd.read_csv(d / "summary.csv")
        for _, r in s.iterrows():
            if r["strategy"] in ("Adaptive",): continue
            rows.append({"ef_search": ef, "probes": pr, "strategy": r["strategy"],
                         "mean_recall": r["mean_recall_at_10"],
                         "mean_latency": r["mean_latency_ms"]})
    df = pd.DataFrame(rows)
    fig, axes = plt.subplots(1, 2, figsize=(7, 3.2))
    for ax, metric, ylabel in [(axes[0], "mean_recall", "Mean Recall@10"),
                               (axes[1], "mean_latency", "Mean latency (ms)")]:
        for strat in ["HNSW_HYBRID", "IVFFLAT_HYBRID", "VECTOR_FIRST_HNSW"]:
            sub = df[df["strategy"] == strat]
            grouped = sub.groupby(["ef_search", "probes"])[metric].mean().reset_index()
            ax.plot(grouped["ef_search"], grouped[metric], "-o", label=strat)
        ax.set_xlabel("HNSW ef_search")
        ax.set_ylabel(ylabel)
        ax.grid(True, alpha=0.3)
        ax.legend(fontsize=7)
        ax.set_xscale("log")
    plt.tight_layout()
    plt.savefig(FIG / "figure_7_parameter_sensitivity.pdf", bbox_inches="tight")
    plt.close()
    print("Wrote figure_7_parameter_sensitivity.pdf")


def fig8_plan_verification():
    pv = pd.read_csv(RES / "main_run" / "plan_verification.csv")
    fig, ax = plt.subplots(figsize=(6.5, 3.2))
    verified, unverified = [], []
    for s in STRATEGIES:
        v = pv[(pv["strategy"] == s) & (pv["plan_verified"] == True)]["count"].sum()
        u = pv[(pv["strategy"] == s) & (pv["plan_verified"] == False)]["count"].sum()
        verified.append(int(v)); unverified.append(int(u))
    x = np.arange(len(STRATEGIES))
    ax.bar(x, verified, label="Verified", color="#2ca02c")
    ax.bar(x, unverified, bottom=verified, label="Not verified", color="#d62728")
    ax.set_xticks(x); ax.set_xticklabels(STRATEGIES, rotation=15)
    ax.set_ylabel("Execution count")
    ax.set_title("Plan verification by strategy")
    ax.legend()
    plt.tight_layout()
    plt.savefig(FIG / "figure_8_plan_verification.pdf", bbox_inches="tight")
    plt.close()
    print("Wrote figure_8_plan_verification.pdf")


def main():
    fig1_decision_flow()
    fig2_strategy_vs_selectivity()
    fig3_adaptive_selection()
    fig4_latency_recall_pareto()
    fig5_calibration_size()
    fig6_safety_coverage_tradeoff()
    fig7_parameter_sensitivity()
    fig8_plan_verification()
    print(f"\nAll figures written to {FIG}")


if __name__ == "__main__":
    main()
