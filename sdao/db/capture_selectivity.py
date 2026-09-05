"""Capture EXPLAIN-only PostgreSQL selectivity estimates and replay the planner offline.

This module deliberately issues exactly one database statement per workload
predicate: ``EXPLAIN (FORMAT JSON) ...``.  It never executes a workload query,
does not change session/persistent configuration, and does not use baseline
measured selectivity as a planning input.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

from .baseline_results import DatabaseBaselineResults, FINAL_BASELINE_DIRECTORY
from .calibration import DatabaseStrategyCalibrator
from .connection import connect
from .loader import TABLE_NAME
from .planner import DBAdaptivePlanner, offline_plan_evaluation
from .predicates import translate_predicate
from .selectivity import PostgresSelectivityAdapter
from .workload import get_workload_query

EXPECTED_QUERY_IDS = frozenset(range(32))
DATASET_SIZE = 1_000_000


def _json_default(value: Any) -> Any:
    return getattr(value, "value", str(value))


def _postgres_version(server_version: int) -> str:
    """Format libpq protocol metadata without issuing a SQL version query."""
    major, remainder = divmod(server_version, 10_000)
    # PostgreSQL 10+ encodes this as ``major * 10000 + minor`` (for example,
    # PostgreSQL 16.14 is 160014), unlike the pre-10 three-component scheme.
    return f"{major}.{remainder}"


def _baseline_pgvector_version(baseline: DatabaseBaselineResults) -> str:
    versions = {record.pgvector_version for record in baseline.records if record.pgvector_version}
    if len(versions) != 1:
        raise ValueError("baseline artifact must preserve exactly one pgvector version")
    return versions.pop()


def _explain_record(connection, query_id: int, predicate: str) -> dict[str, Any]:
    """Issue the sole allowed database statement for a workload predicate."""
    translated = translate_predicate(predicate)
    sql = f"EXPLAIN (FORMAT JSON) SELECT id FROM {TABLE_NAME} WHERE {translated.sql}"
    with connection.transaction():
        with connection.cursor() as cursor:
            cursor.execute(sql, translated.params)
            raw_plan = cursor.fetchone()[0]
    plan = json.loads(raw_plan) if isinstance(raw_plan, str) else raw_plan
    estimated_rows = PostgresSelectivityAdapter._plan_rows(plan)
    return {
        "query_id": query_id,
        "predicate": predicate,
        "estimated_rows": estimated_rows,
        "estimated_selectivity": estimated_rows / DATASET_SIZE,
        "explain_format": "JSON",
        "plan": plan,
    }


def capture(output: Path, baseline_directory: Path = FINAL_BASELINE_DIRECTORY) -> Path:
    if output.exists():
        raise FileExistsError(f"output directory already exists: {output}")
    baseline = DatabaseBaselineResults.load(baseline_directory)
    records: list[dict[str, Any]] = []
    connection = connect()
    try:
        for query_id in sorted(EXPECTED_QUERY_IDS):
            workload = get_workload_query(query_id)
            records.append(_explain_record(connection, query_id, workload.predicate))
        postgres_version = _postgres_version(connection.info.server_version)
    finally:
        connection.close()

    observed_ids = {int(record["query_id"]) for record in records}
    if observed_ids != EXPECTED_QUERY_IDS or len(records) != len(EXPECTED_QUERY_IDS):
        raise ValueError("EXPLAIN capture must contain every query id 0..31 exactly once")
    estimates = {int(record["query_id"]): float(record["estimated_selectivity"]) for record in records}

    # Calibration is fixed from the saved baseline.  The only selectivity fed
    # to plan() is the EXPLAIN mapping above, never baseline measured values.
    calibration = DatabaseStrategyCalibrator().calibrate(baseline)
    decisions = offline_plan_evaluation(DBAdaptivePlanner(calibration), baseline.records, estimates)
    distribution: dict[str, int] = {}
    for decision in decisions:
        distribution[decision.selected_strategy.value] = distribution.get(decision.selected_strategy.value, 0) + 1

    output.mkdir(parents=True)
    artifact = {
        "artifact_type": "postgres_explain_selectivity_and_offline_planner_evaluation",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "safety": {
            "database_statements": "EXPLAIN (FORMAT JSON) only; one statement for each workload predicate",
            "actual_strategy_queries_executed": 0,
            "data_or_index_modifications": 0,
            "persistent_postgresql_configuration_modifications": 0,
            "planner_selectivity_input": "PostgreSQL EXPLAIN estimated_selectivity only",
            "baseline_measured_selectivity_used_as_planner_input": False,
        },
        "dataset": {"table": TABLE_NAME, "assumed_row_count": DATASET_SIZE, "embedding_dimension": 128},
        "versions": {
            "postgresql": postgres_version,
            "postgresql_source": "psycopg connection protocol metadata (no SQL version query)",
            "pgvector": _baseline_pgvector_version(baseline),
            "pgvector_source": f"preserved baseline metadata: {baseline.source_directory}",
        },
        "validation": {"expected_query_ids": sorted(EXPECTED_QUERY_IDS), "captured_query_ids": sorted(observed_ids), "all_32_queries_present": True},
        "query_estimates": records,
        "estimated_selectivity_by_query": {str(key): value for key, value in estimates.items()},
        "offline_planner": {
            "calibration_source": calibration.source_path,
            "target_recall": calibration.target_recall,
            "decision_distribution": distribution,
            "decisions": [asdict(decision) for decision in decisions],
        },
    }
    (output / "postgres_explain_selectivity.json").write_text(json.dumps(artifact, indent=2, default=_json_default) + "\n")
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description="Capture 32 EXPLAIN-only selectivity estimates and replay DB planner offline")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--baseline", type=Path, default=FINAL_BASELINE_DIRECTORY)
    args = parser.parse_args()
    print(f"Wrote EXPLAIN-only artifact to {capture(args.output, args.baseline)}")


if __name__ == "__main__":
    main()
