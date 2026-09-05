#!/usr/bin/env python3
"""Compute end-to-end latency from existing per-query benchmark logs.

Required inputs are the adaptive and fixed-strategy per-query CSVs emitted by
sdao.db.paper_analysis. The script uses recorded per-query ``actual_latency_ms``
for the adaptive decision-to-verified-execution path and the SQL_FIRST
``execution_wall_latency_ms`` for its execution. SQL_FIRST's own planning/EXPLAIN
component is derived from ``actual_latency_ms - execution_wall_latency_ms`` in
its per-query row. No benchmark is rerun and aggregate overhead values are not
broadcast across queries.

The script requires exactly 250 matched query IDs, because an aggregate result
from a smaller workload cannot support a valid held-out comparison.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

EXPECTED_QUERY_COUNT = 250


def load_csv(path: Path) -> pd.DataFrame:
    if not path.is_file():
        raise FileNotFoundError(path)
    return pd.read_csv(path)


def compute(adaptive_path: Path, fixed_path: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    adaptive = load_csv(adaptive_path)
    fixed = load_csv(fixed_path)
    required_adaptive = {"query_id", "actual_latency_ms", "strategy_only_latency_ms"}
    required_fixed = {"query_id", "strategy", "actual_latency_ms", "execution_wall_latency_ms"}
    missing_adaptive = required_adaptive - set(adaptive.columns)
    missing_fixed = required_fixed - set(fixed.columns)
    if missing_adaptive or missing_fixed:
        raise ValueError(
            f"Missing adaptive columns: {sorted(missing_adaptive)}; "
            f"missing fixed columns: {sorted(missing_fixed)}"
        )
    adaptive = adaptive.drop_duplicates("query_id", keep=False).copy()
    sql_first = fixed[fixed["strategy"] == "SQL_FIRST"].drop_duplicates("query_id", keep=False).copy()
    if len(adaptive) != EXPECTED_QUERY_COUNT or len(sql_first) != EXPECTED_QUERY_COUNT:
        raise ValueError(
            f"Expected {EXPECTED_QUERY_COUNT} unique adaptive and SQL_FIRST rows; "
            f"found {len(adaptive)} and {len(sql_first)}. Existing logs must be complete "
            "before a 250-query result can be reported."
        )
    if set(adaptive.query_id) != set(sql_first.query_id):
        raise ValueError("Adaptive and SQL_FIRST logs do not contain the same query IDs")

    adaptive = adaptive.set_index("query_id").sort_index()
    sql_first = sql_first.set_index("query_id").sort_index()
    result = pd.DataFrame(index=adaptive.index)
    result["adaptive_decision_to_verified_ms"] = adaptive["actual_latency_ms"]
    result["adaptive_strategy_execution_ms"] = adaptive["strategy_only_latency_ms"]
    result["adaptive_end_to_end_ms"] = result["adaptive_decision_to_verified_ms"]
    result["sql_first_strategy_execution_ms"] = sql_first["execution_wall_latency_ms"]
    result["sql_first_planning_overhead_ms"] = (
        sql_first["actual_latency_ms"] - sql_first["execution_wall_latency_ms"]
    )
    result["sql_first_end_to_end_ms"] = sql_first["actual_latency_ms"]
    result["adaptive_minus_sql_first_ms"] = (
        result["adaptive_end_to_end_ms"] - result["sql_first_end_to_end_ms"]
    )
    return result.reset_index(), adaptive.reset_index()


def summarize(frame: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for label, column in (
        ("Adaptive end-to-end", "adaptive_end_to_end_ms"),
        ("SQL_FIRST end-to-end", "sql_first_end_to_end_ms"),
        ("Adaptive - SQL_FIRST", "adaptive_minus_sql_first_ms"),
    ):
        values = frame[column]
        rows.append({
            "case": label,
            "mean_ms": values.mean(),
            "median_ms": values.median(),
            "p95_ms": values.quantile(0.95),
        })
    return pd.DataFrame(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--adaptive", type=Path, required=True)
    parser.add_argument("--fixed", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, default=Path("paper/end_to_end"))
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    per_query, _ = compute(args.adaptive, args.fixed)
    summary = summarize(per_query)
    per_query.to_csv(args.output_dir / "true_end_to_end_per_query.csv", index=False)
    summary.to_csv(args.output_dir / "true_end_to_end_summary.csv", index=False)
    adaptive_mean = summary.loc[summary.case == "Adaptive end-to-end", "mean_ms"].iloc[0]
    sql_mean = summary.loc[summary.case == "SQL_FIRST end-to-end", "mean_ms"].iloc[0]
    if adaptive_mean < sql_mean:
        verdict = "Adaptive wins end-to-end."
    elif adaptive_mean > sql_mean:
        verdict = "Adaptive is slower end-to-end than SQL_FIRST."
    else:
        verdict = "Adaptive and SQL_FIRST tie end-to-end."
    print(summary.to_string(index=False, float_format=lambda value: f"{value:.12f}"))
    print(verdict)
    print(f"Wrote {args.output_dir / 'true_end_to_end_per_query.csv'}")
    print(f"Wrote {args.output_dir / 'true_end_to_end_summary.csv'}")


if __name__ == "__main__":
    main()
