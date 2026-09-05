#!/usr/bin/env python3
"""Compare adaptive and SQL_FIRST end-to-end wall-clock latency.

The input must contain exactly one row per held-out query with these columns:

``query_id,adaptive_decision_overhead_ms,adaptive_strategy_execution_ms,``
``sql_first_planning_ms,sql_first_execution_ms``

Adaptive end-to-end latency is decision overhead plus the selected strategy's
execution. SQL_FIRST end-to-end latency is its own planning plus execution.
The script deliberately rejects aggregate-only benchmark files because they
cannot produce a valid paired per-query delta or P95 comparison.

Example:
    venv/bin/python compute_end_to_end_latency.py \
        --input heldout_end_to_end_timings.csv \
        --output-dir paper/end_to_end
"""
from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd


EXPECTED_QUERY_COUNT = 250
REQUIRED_COLUMNS = {
    "query_id",
    "adaptive_decision_overhead_ms",
    "adaptive_strategy_execution_ms",
    "sql_first_planning_ms",
    "sql_first_execution_ms",
}


def percentile(values: pd.Series, probability: float) -> float:
    return float(values.quantile(probability, interpolation="linear"))


def load_timings(path: Path) -> pd.DataFrame:
    if not path.is_file():
        raise FileNotFoundError(f"timing input does not exist: {path}")

    frame = pd.read_csv(path)
    missing = REQUIRED_COLUMNS - set(frame.columns)
    if missing:
        raise ValueError(
            "Input must contain per-query timing columns; missing: "
            + ", ".join(sorted(missing))
        )
    if len(frame) != EXPECTED_QUERY_COUNT:
        raise ValueError(
            f"Expected exactly {EXPECTED_QUERY_COUNT} held-out queries, got {len(frame)}"
        )
    if frame["query_id"].duplicated().any():
        raise ValueError("query_id must be unique: paired deltas require one row per query")

    numeric_columns = sorted(REQUIRED_COLUMNS - {"query_id"})
    for column in numeric_columns:
        frame[column] = pd.to_numeric(frame[column], errors="raise")
        if not frame[column].ge(0).all():
            raise ValueError(f"{column} contains a negative timing")

    frame = frame.sort_values("query_id").reset_index(drop=True)
    frame["adaptive_end_to_end_ms"] = (
        frame["adaptive_decision_overhead_ms"]
        + frame["adaptive_strategy_execution_ms"]
    )
    frame["sql_first_end_to_end_ms"] = (
        frame["sql_first_planning_ms"] + frame["sql_first_execution_ms"]
    )
    frame["adaptive_minus_sql_first_ms"] = (
        frame["adaptive_end_to_end_ms"] - frame["sql_first_end_to_end_ms"]
    )
    return frame


def summary_rows(frame: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for label, column in (
        ("Adaptive end-to-end", "adaptive_end_to_end_ms"),
        ("SQL_FIRST end-to-end", "sql_first_end_to_end_ms"),
    ):
        values = frame[column]
        rows.append(
            {
                "Metric": label,
                "Mean ms": values.mean(),
                "Median ms": values.median(),
                "P95 ms": percentile(values, 0.95),
            }
        )
    delta = frame["adaptive_minus_sql_first_ms"]
    rows.append(
        {
            "Metric": "Adaptive - SQL_FIRST",
            "Mean ms": delta.mean(),
            "Median ms": delta.median(),
            "P95 ms": percentile(delta, 0.95),
        }
    )
    return pd.DataFrame(rows)


def write_latex_table(summary: pd.DataFrame, output_path: Path) -> None:
    lines = [
        r"\begin{table}[t]",
        r"\centering",
        r"\caption{End-to-end wall-clock latency on the 250-query held-out test set. Adaptive latency includes decision overhead and selected-strategy execution; SQL_FIRST includes its own planning and execution. The delta is Adaptive minus SQL_FIRST.}",
        r"\label{tab:end-to-end-latency}",
        r"\scriptsize",
        r"\begin{tabular}{lrrr}",
        r"\toprule",
        r"Policy & Mean ms & Median ms & P95 ms \\",
        r"\midrule",
    ]
    for row in summary.itertuples(index=False):
        lines.append(
            f"{row[0]} & {row[1]:.2f} & {row[2]:.2f} & {row[3]:.2f} " + r"\\"
        )
    lines.extend(
        [
            r"\bottomrule",
            r"\end{tabular}",
            r"\end{table}",
            "",
        ]
    )
    output_path.write_text("\n".join(lines), encoding="utf-8")


def write_plot(frame: pd.DataFrame, output_path: Path) -> None:
    figure, axes = plt.subplots(figsize=(7.0, 4.5))
    axes.scatter(
        frame["query_id"],
        frame["adaptive_end_to_end_ms"],
        label="Adaptive end-to-end",
        s=22,
        alpha=0.85,
    )
    axes.scatter(
        frame["query_id"],
        frame["sql_first_end_to_end_ms"],
        label="SQL_FIRST end-to-end",
        s=22,
        alpha=0.85,
    )
    for row in frame.itertuples(index=False):
        axes.plot(
            [row.query_id, row.query_id],
            [row.adaptive_end_to_end_ms, row.sql_first_end_to_end_ms],
            color="0.75",
            linewidth=0.45,
            zorder=0,
        )
    axes.set_xlabel("Query ID (held-out workload identifier)")
    axes.set_ylabel("End-to-end wall-clock latency (ms)")
    axes.legend(frameon=False)
    axes.grid(True, color="0.88", linewidth=0.6)
    figure.tight_layout()
    figure.savefig(output_path, format="pdf", bbox_inches="tight")
    plt.close(figure)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, default=Path("paper/end_to_end"))
    args = parser.parse_args()

    args.output_dir.mkdir(parents=True, exist_ok=True)
    frame = load_timings(args.input)
    summary = summary_rows(frame)
    frame.to_csv(args.output_dir / "end_to_end_per_query.csv", index=False)
    summary.to_csv(args.output_dir / "end_to_end_summary.csv", index=False)
    write_latex_table(summary, args.output_dir / "end_to_end_latency.tex")
    write_plot(frame, args.output_dir / "figure_07_end_to_end_adaptive_vs_sql_first.pdf")
    print(summary.to_string(index=False, float_format=lambda value: f"{value:.2f}"))
    print(f"Mean per-query delta (Adaptive - SQL_FIRST): {frame['adaptive_minus_sql_first_ms'].mean():.2f} ms")
    print(f"Wrote outputs to {args.output_dir}")


if __name__ == "__main__":
    main()