"""Replay a frozen 250-query held-out split and log end-to-end timings.

This command never calibrates, generates queries, changes seeds, or changes ANN
settings. It requires a frozen workload CSV containing 500 rows with a ``split``
column and exactly 250 ``held_out`` rows. The default calibration map is the
preserved calibration artifact from 2026-08-14.

The adaptive row's ``adaptive_execution_ms`` is strategy-only execution time;
``adaptive_end_to_end_ms`` also includes the measured plan-verification wall
clock inside the execution phase. SQL_FIRST planning time is the SQL_FIRST
EXPLAIN/verification wall clock minus its measured execution time.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
import time

import pandas as pd

from .evaluate_heldout import HeldOutHarness, SyntheticQuery
from .evaluate_heldout import read_fvecs, select_adaptive_strategy
from ..utils.data_loader import QUERY_FILE
from .config import DatabaseConfig

DEFAULT_CALIBRATION_MAP = Path("sdao/results/db_calibration_20260814/db_strategy_calibration_buckets.csv")
EXPECTED_HELD_OUT = 250


@dataclass(frozen=True)
class TimingRow:
    query_id: int
    estimated_selectivity: float
    explain_time_ms: float
    decision_overhead_ms: float
    selected_strategy: str
    adaptive_execution_ms: float
    adaptive_end_to_end_ms: float
    sql_first_planning_ms: float
    sql_first_execution_ms: float
    sql_first_end_to_end_ms: float


def load_queries(path: Path) -> list[SyntheticQuery]:
    frame = pd.read_csv(path)
    required = {"query_id", "price_threshold", "category", "in_stock", "predicate", "vector_id", "split"}
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"workload is missing columns: {', '.join(sorted(missing))}")
    held_out = frame[frame["split"] == "held_out"].copy()
    if len(held_out) != EXPECTED_HELD_OUT or held_out.query_id.duplicated().any():
        raise ValueError(f"workload must contain exactly {EXPECTED_HELD_OUT} unique held_out rows")
    return [
        SyntheticQuery(
            query_id=int(row.query_id),
            target_selectivity=float(getattr(row, "target_selectivity", 0.0)),
            price_threshold=int(row.price_threshold),
            category=str(row.category),
            in_stock=str(row.in_stock).strip().lower() == "true",
            predicate=str(row.predicate),
            vector_id=int(row.vector_id),
        )
        for row in held_out.itertuples(index=False)
    ]


def load_calibration(path: Path) -> pd.DataFrame:
    frame = pd.read_csv(path)
    required = {"strategy", "bucket", "latency_median_ms", "minimum_recall"}
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"calibration map is missing columns: {', '.join(sorted(missing))}")
    return frame


def run(args: argparse.Namespace) -> pd.DataFrame:
    queries = load_queries(args.workload)
    calibration = load_calibration(args.calibration_map)
    query_vectors = read_fvecs(QUERY_FILE)
    connection = __import__("psycopg").connect(**DatabaseConfig.from_env().connect_kwargs())
    harness = HeldOutHarness(connection, query_vectors, args.top_k, args.safety_factor)
    rows: list[TimingRow] = []
    try:
        for query in queries:
            explain_started = time.perf_counter_ns()
            estimate = harness.estimate_selectivity(query)
            explain_time_ms = (time.perf_counter_ns() - explain_started) / 1_000_000

            decision_started = time.perf_counter_ns()
            selected = select_adaptive_strategy(calibration, estimate)
            decision_overhead_ms = (time.perf_counter_ns() - decision_started) / 1_000_000

            adaptive_started = time.perf_counter_ns()
            adaptive_record = harness.run_once(query, "held_out", selected, 0, estimate)
            adaptive_wall_ms = (time.perf_counter_ns() - adaptive_started) / 1_000_000

            sql_started = time.perf_counter_ns()
            sql_record = harness.run_once(query, "held_out", "SQL_FIRST", 0, estimate)
            sql_wall_ms = (time.perf_counter_ns() - sql_started) / 1_000_000
            sql_first_planning_ms = sql_wall_ms - sql_record.latency_ms

            rows.append(TimingRow(
                query_id=query.query_id,
                estimated_selectivity=estimate,
                explain_time_ms=explain_time_ms,
                decision_overhead_ms=decision_overhead_ms,
                selected_strategy=selected,
                adaptive_execution_ms=adaptive_record.latency_ms,
                adaptive_end_to_end_ms=explain_time_ms + decision_overhead_ms + adaptive_wall_ms,
                sql_first_planning_ms=sql_first_planning_ms,
                sql_first_execution_ms=sql_record.latency_ms,
                sql_first_end_to_end_ms=sql_wall_ms,
            ))
    finally:
        connection.close()
    return pd.DataFrame([row.__dict__ for row in rows]).sort_values("query_id")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workload", type=Path, required=True)
    parser.add_argument("--calibration-map", type=Path, default=DEFAULT_CALIBRATION_MAP)
    parser.add_argument("--output", type=Path, default=Path("held_out_end_to_end_250.csv"))
    parser.add_argument("--top-k", type=int, default=10)
    parser.add_argument("--safety-factor", type=float, default=2.0)
    args = parser.parse_args()
    result = run(args)
    result.to_csv(args.output, index=False)
    print(f"Wrote {args.output}")
    print(f"row_count={len(result)}")
    if len(result) != EXPECTED_HELD_OUT:
        raise SystemExit(f"expected {EXPECTED_HELD_OUT} rows, got {len(result)}")


if __name__ == "__main__":
    main()
