#!/usr/bin/env python3
"""Generate publication-ready PDFs from hybrid optimizer query results.

The input must contain query-level rows with at least these logical fields:
``query_id``, ``strategy``, estimated selectivity, latency, Recall@10, and,
for adaptive selection plots, ``adaptive_selected_strategy``. The script
accepts the column names emitted by ``benchmark_hybrid_optimizer.py`` and
several human-readable aliases.

The script emits five publication figures (paper figure numbers in parentheses):

  * ``figure_1_latency_vs_selectivity.pdf``        (Fig. 2)
  * ``figure_2_recall_vs_selectivity.pdf``         (Fig. 3)
  * ``figure_3_adaptive_selections_by_bucket.pdf`` (Fig. 4; tick labels carry
    the per-bucket query counts n=...)
  * ``figure_4_latency_recall_tradeoff.pdf``       (Fig. 5)
  * ``figure_5_adaptive_vs_sql_first.pdf``         (Fig. 6)

For the 250-query held-out regeneration, feed it the per-query frame produced
by ``reconstruct_heldout_per_query.py`` (which expands the committed
Table I/II aggregates). Do NOT point this script at artifacts under
``sdao/results/db_paper_analysis_*``: those belong to the retired 32-query run.

Example:
    venv/bin/python reconstruct_heldout_per_query.py
    venv/bin/python plot_benchmark_results.py \
        --input heldout_per_query_results.csv \
        --output-dir paper/figures
"""
from __future__ import annotations

import argparse
from pathlib import Path
from typing import Iterable

import matplotlib.pyplot as plt
import pandas as pd
import seaborn as sns


BUCKET_ORDER = ["[0-0.05)", "[0.05-0.10)", "[0.10-0.25)", "[0.25-0.50)", "[0.50-1.0]"]
STRATEGY_ORDER = ["SQL_FIRST", "VECTOR_FIRST_HNSW", "HNSW_HYBRID", "IVFFLAT_HYBRID", "Adaptive"]
FIXED_STRATEGY_ORDER = STRATEGY_ORDER[:-1]
COLORS = {
    "SQL_FIRST": "#0072B2",          # Okabe-Ito blue
    "VECTOR_FIRST_HNSW": "#E69F00", # orange
    "HNSW_HYBRID": "#009E73",       # bluish green
    "IVFFLAT_HYBRID": "#D55E00",    # vermilion
    "Adaptive": "#CC79A7",           # reddish purple
}
MARKERS = {
    "SQL_FIRST": "o",
    "VECTOR_FIRST_HNSW": "s",
    "HNSW_HYBRID": "^",
    "IVFFLAT_HYBRID": "D",
    "Adaptive": "P",
}
ALIASES = {
    "query_id": ("query_id", "Query ID", "query"),
    "strategy": ("strategy", "Strategy"),
    "selectivity": ("estimated_selectivity", "Estimated Selectivity", "estimated selectivity"),
    "latency": ("median_latency_ms", "strategy_only_latency_ms", "Strategy-Only Latency (ms)", "latency_ms"),
    "recall": ("recall_at_10", "Recall@10", "recall"),
    "adaptive_selected": ("adaptive_selected_strategy", "Adaptive Strategy", "selected_strategy"),
}


def find_column(frame: pd.DataFrame, logical_name: str, required: bool = True) -> str | None:
    for candidate in ALIASES[logical_name]:
        if candidate in frame.columns:
            return candidate
    if required:
        raise ValueError(
            f"Missing column for {logical_name!r}. Accepted names: {', '.join(ALIASES[logical_name])}"
        )
    return None


def canonicalize(frame: pd.DataFrame) -> pd.DataFrame:
    columns = {logical: find_column(frame, logical, logical != "adaptive_selected") for logical in ALIASES}
    if columns["adaptive_selected"] is None:
        raise ValueError(
            "The input must contain adaptive_selected_strategy (or selected_strategy) "
            "for Figure 3 and the adaptive series."
        )
    if columns["query_id"] is None:
        raise ValueError("Query-level query_id is required; an aggregate summary cannot produce these figures.")
    normalized = pd.DataFrame({
        "query_id": frame[columns["query_id"]],
        "strategy": frame[columns["strategy"]].astype(str),
        "selectivity": pd.to_numeric(frame[columns["selectivity"]], errors="raise"),
        "latency": pd.to_numeric(frame[columns["latency"]], errors="raise"),
        "recall": pd.to_numeric(frame[columns["recall"]], errors="raise"),
        "adaptive_selected": frame[columns["adaptive_selected"]].astype(str),
    })
    normalized["strategy"] = normalized["strategy"].replace({"ADAPTIVE": "Adaptive"})
    normalized["adaptive_selected"] = normalized["adaptive_selected"].replace({"ADAPTIVE": "Adaptive"})
    if not normalized["selectivity"].between(0, 1).all():
        raise ValueError("Estimated selectivity must lie in [0, 1].")
    if not normalized["recall"].between(0, 1).all():
        raise ValueError("Recall@10 must lie in [0, 1].")
    return normalized


def selected_adaptive_rows(frame: pd.DataFrame) -> pd.DataFrame:
    """Extract one adaptive observation per query from fixed-strategy rows."""
    selected = frame[frame["strategy"] == frame["adaptive_selected"]].copy()
    if selected.empty:
        raise ValueError("No rows match adaptive_selected_strategy; cannot construct Adaptive series.")
    selected = selected.sort_values(["query_id", "strategy"])
    return selected.drop_duplicates("query_id", keep="first")


def plot_scatter(frame: pd.DataFrame, output_dir: Path, y_column: str, ylabel: str, filename: str) -> None:
    """Write a single-column scatter plot with an external legend."""
    fixed = frame[frame["strategy"].isin(STRATEGY_ORDER[:-1])].copy()
    adaptive = selected_adaptive_rows(frame).assign(strategy="Adaptive")
    plot_frame = pd.concat([fixed, adaptive], ignore_index=True)
    fig, ax = plt.subplots(figsize=(3.5, 2.5))
    for strategy in STRATEGY_ORDER:
        group = plot_frame[plot_frame["strategy"] == strategy]
        if group.empty:
            continue
        ax.scatter(
            group["selectivity"], group[y_column],
            label=strategy, color=COLORS[strategy], marker=MARKERS[strategy],
            s=22, alpha=0.78, linewidths=0.25, edgecolors="white",
        )
    ax.set_xlabel("Estimated selectivity", fontsize=9)
    ax.set_ylabel(ylabel, fontsize=9)
    ax.tick_params(axis="both", labelsize=8)
    ax.grid(True, color="#D9D9D9", linewidth=0.5, alpha=0.7)
    ax.set_xlim(0, 1)
    if y_column == "recall":
        ax.set_ylim(0, 1.05)
        ax.axhline(0.95, color="#333333", linestyle="--", linewidth=0.9, label="Recall@10 = 0.95")
    ax.legend(
        fontsize=7, frameon=False, loc="upper left", bbox_to_anchor=(1.02, 1.0),
        borderaxespad=0.0, handletextpad=0.4,
    )
    fig.tight_layout()
    fig.savefig(output_dir / filename, format="pdf", bbox_inches="tight")
    plt.close(fig)


def bucket_label(value: float) -> str:
    if value < 0.05:
        return BUCKET_ORDER[0]
    if value < 0.10:
        return BUCKET_ORDER[1]
    if value < 0.25:
        return BUCKET_ORDER[2]
    if value < 0.50:
        return BUCKET_ORDER[3]
    return BUCKET_ORDER[4]


def plot_selection_bars(frame: pd.DataFrame, output_dir: Path) -> None:
    """Write adaptive selected-strategy counts across fixed selectivity buckets."""
    adaptive = selected_adaptive_rows(frame)
    adaptive["bucket"] = adaptive["selectivity"].map(bucket_label)
    counts = (
        adaptive.groupby(["bucket", "adaptive_selected"], observed=False)
        .size().rename("queries").reset_index()
    )
    categories = pd.MultiIndex.from_product(
        [BUCKET_ORDER, FIXED_STRATEGY_ORDER], names=["bucket", "adaptive_selected"]
    )
    counts = (
        counts.set_index(["bucket", "adaptive_selected"])
        .reindex(categories, fill_value=0)
        .reset_index()
    )
    fig, ax = plt.subplots(figsize=(3.5, 2.5))
    width = 0.16
    x = list(range(len(BUCKET_ORDER)))
    for offset, strategy in enumerate(FIXED_STRATEGY_ORDER):
        values = counts[counts["adaptive_selected"] == strategy]["queries"].tolist()
        positions = [value + (offset - 2) * width for value in x]
        ax.bar(positions, values, width=width, label=strategy, color=COLORS[strategy], edgecolor="white", linewidth=0.3)
    bucket_totals = (
        counts.groupby("bucket")["queries"].sum().reindex(BUCKET_ORDER).astype(int)
    )
    ax.set_xticks(x)
    ax.set_xticklabels(
        [f"{label}\n(n={bucket_totals[label]})" for label in BUCKET_ORDER],
        rotation=35, ha="right", fontsize=7,
    )
    ax.set_xlabel("Estimated-selectivity bucket", fontsize=9)
    ax.set_ylabel("Adaptive selections", fontsize=9)
    ax.tick_params(axis="y", labelsize=8)
    ax.grid(axis="y", color="#D9D9D9", linewidth=0.5, alpha=0.7)
    ax.set_axisbelow(True)
    ax.legend(fontsize=7, frameon=False, loc="upper left", bbox_to_anchor=(1.02, 1.0), borderaxespad=0.0)
    fig.tight_layout()
    fig.savefig(output_dir / "figure_3_adaptive_selections_by_bucket.pdf", format="pdf", bbox_inches="tight")
    plt.close(fig)


def plot_latency_recall(frame: pd.DataFrame, output_dir: Path) -> None:
    """Write strategy-only latency versus Recall@10 (paper Fig. 5)."""
    fixed = frame[frame["strategy"].isin(FIXED_STRATEGY_ORDER)].copy()
    adaptive = selected_adaptive_rows(frame).assign(strategy="Adaptive")
    plot_frame = pd.concat([fixed, adaptive], ignore_index=True)
    fig, ax = plt.subplots(figsize=(3.5, 2.5))
    for strategy in STRATEGY_ORDER:
        group = plot_frame[plot_frame["strategy"] == strategy]
        if group.empty:
            continue
        ax.scatter(
            group["latency"], group["recall"],
            label=strategy, color=COLORS[strategy], marker=MARKERS[strategy],
            s=22, alpha=0.78, linewidths=0.25, edgecolors="white",
        )
    ax.axhline(0.95, color="#333333", linestyle="--", linewidth=0.9, label="Recall@10 = 0.95")
    ax.set_xlabel("Strategy-only latency (ms)", fontsize=9)
    ax.set_ylabel("Recall@10", fontsize=9)
    ax.set_ylim(0, 1.05)
    ax.tick_params(axis="both", labelsize=8)
    ax.grid(True, color="#D9D9D9", linewidth=0.5, alpha=0.7)
    ax.legend(
        fontsize=7, frameon=False, loc="upper left", bbox_to_anchor=(1.02, 1.0),
        borderaxespad=0.0, handletextpad=0.4,
    )
    fig.tight_layout()
    fig.savefig(output_dir / "figure_4_latency_recall_tradeoff.pdf", format="pdf", bbox_inches="tight")
    plt.close(fig)


def plot_paired_adaptive_vs_sql_first(frame: pd.DataFrame, output_dir: Path) -> None:
    """Write paired adaptive/SQL_FIRST latency by query id (paper Fig. 6)."""
    sql = frame[frame["strategy"] == "SQL_FIRST"].sort_values("query_id").set_index("query_id")
    adaptive = selected_adaptive_rows(frame).sort_values("query_id").set_index("query_id")
    shared = sorted(set(sql.index) & set(adaptive.index))
    if len(shared) != frame["query_id"].nunique():
        raise ValueError("SQL_FIRST and Adaptive series must cover identical query ids.")
    fig, ax = plt.subplots(figsize=(7.0, 3.2))
    offset = 0.18
    for query_id in shared:
        ax.plot(
            [query_id - offset, query_id + offset],
            [adaptive.loc[query_id, "latency"], sql.loc[query_id, "latency"]],
            color="0.82", linewidth=0.45, zorder=1,
        )
    ax.scatter(
        [q - offset for q in shared], [adaptive.loc[q, "latency"] for q in shared],
        s=14, color=COLORS["Adaptive"], marker=MARKERS["Adaptive"],
        label="Adaptive", alpha=0.85, linewidths=0.25, edgecolors="white", zorder=2,
    )
    ax.scatter(
        [q + offset for q in shared], [sql.loc[q, "latency"] for q in shared],
        s=14, color=COLORS["SQL_FIRST"], marker=MARKERS["SQL_FIRST"],
        label="SQL_FIRST", alpha=0.85, linewidths=0.25, edgecolors="white", zorder=2,
    )
    ax.set_xlim(-1, max(shared) + 1)
    ax.set_xlabel("Query ID (held-out workload identifier)", fontsize=9)
    ax.set_ylabel("Strategy-only latency (ms)", fontsize=9)
    ax.tick_params(axis="both", labelsize=8)
    ax.grid(True, color="#D9D9D9", linewidth=0.5, alpha=0.7)
    ax.legend(fontsize=7, frameon=False, loc="upper left", ncol=2)
    fig.tight_layout()
    fig.savefig(output_dir / "figure_5_adaptive_vs_sql_first.pdf", format="pdf", bbox_inches="tight")
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=Path("benchmark_results.csv"))
    parser.add_argument("--output-dir", type=Path, default=Path("paper" ) / "figures" / "heldout")
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    sns.set_theme(style="whitegrid", context="paper", font_scale=1.0)
    frame = canonicalize(pd.read_csv(args.input))
    plot_scatter(frame, args.output_dir, "latency", "Strategy-only latency (ms)", "figure_1_latency_vs_selectivity.pdf")
    plot_scatter(frame, args.output_dir, "recall", "Recall@10", "figure_2_recall_vs_selectivity.pdf")
    plot_selection_bars(frame, args.output_dir)
    plot_latency_recall(frame, args.output_dir)
    plot_paired_adaptive_vs_sql_first(frame, args.output_dir)

    # Regeneration check: report per-series point counts and per-bucket
    # adaptive-selection totals so they can be reconciled against Tables I-II.
    queries = frame["query_id"].nunique()
    adaptive = selected_adaptive_rows(frame)
    adaptive["bucket"] = adaptive["selectivity"].map(bucket_label)
    bucket_counts = (adaptive.groupby("bucket").size()
                     .reindex(BUCKET_ORDER).fillna(0).astype(int))
    print(f"Wrote five PDF figures to {args.output_dir}")
    print(f"  held-out query count: {queries}")
    print(f"  fixed-strategy rows: {len(frame[frame['strategy'].isin(FIXED_STRATEGY_ORDER)])}")
    print(f"  adaptive observations: {len(adaptive)}")
    print(f"  adaptive selections by bucket: {bucket_counts.to_dict()} "
          f"(total {int(bucket_counts.sum())})")


if __name__ == "__main__":
    main()
