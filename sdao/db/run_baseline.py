"""Run the PostgreSQL/pgvector baseline without invoking SDAO experiments."""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from .benchmark import DatabaseBenchmark
from .connection import connect
from .workload import get_workload_query


STRATEGIES = ("sql_first_exact", "vector_first_post_filter", "hnsw_hybrid", "ivfflat_hybrid")


def _json_default(value: Any):
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, np.ndarray):
        return value.tolist()
    raise TypeError(f"not JSON serializable: {type(value)!r}")


def _recall(result_ids: list[int], reference_ids: list[int]) -> float:
    return len(set(result_ids).intersection(reference_ids)) / len(reference_ids) if reference_ids else 1.0


def run(results_dir: Path, top_k: int = 10, candidate_budget: int = 100) -> list[dict[str, Any]]:
    if results_dir.exists():
        raise FileExistsError(f"Results directory already exists: {results_dir}")
    results_dir.mkdir(parents=True)
    rows: list[dict[str, Any]] = []
    connection = connect()
    benchmark = DatabaseBenchmark(connection)
    try:
        for query_id in range(32):
            workload = get_workload_query(query_id)
            request = benchmark.request_from_workload(query_id, top_k=top_k, workload=workload)
            for strategy in STRATEGIES:
                try:
                    kwargs = {"candidate_budget": candidate_budget} if strategy == "vector_first_post_filter" else {}
                    result = benchmark.execute_with_reference(request, strategy, **kwargs)
                    rows.append({
                        "query_id": query_id, "predicate": workload.predicate, "selectivity": result["selectivity"],
                        "top_k": top_k, "strategy": result["strategy"], "status": "completed",
                        "strategy_latency_ms": result["strategy_latency_ms"],
                        "reference_latency_ms": result["reference_latency_ms"],
                        "recall": _recall(result["result_ids"], result["reference_ids"]),
                        "returned_ids": result["result_ids"], "reference_ids": result["reference_ids"],
                        "ann_parameters": result["database_index_configuration"].get("session_settings", {}),
                        "index_configuration": result["database_index_configuration"],
                        "postgres_version": result["postgres_version"], "pgvector_version": result["pgvector_version"],
                        "plan_verification_status": result["plan_verification_status"],
                        "plan_index_names": result["plan_evidence"]["plan_index_names"] if result["plan_evidence"] else [],
                        "error": None,
                    })
                except Exception as exc:  # Keep failed workload cells visible in artifacts.
                    rows.append({
                        "query_id": query_id, "predicate": workload.predicate, "selectivity": None, "top_k": top_k,
                        "strategy": strategy, "status": "failed", "strategy_latency_ms": None,
                        "reference_latency_ms": None, "recall": None, "returned_ids": [], "reference_ids": [],
                        "ann_parameters": {}, "index_configuration": {}, "postgres_version": None,
                        "pgvector_version": None, "plan_verification_status": None, "plan_index_names": [],
                        "error": f"{type(exc).__name__}: {exc}",
                    })
    finally:
        connection.close()

    (results_dir / "db_baseline_results.json").write_text(json.dumps(rows, indent=2, default=_json_default) + "\n")
    csv_rows = [{key: json.dumps(value, default=_json_default) if isinstance(value, (dict, list)) else value for key, value in row.items()} for row in rows]
    pd.DataFrame(csv_rows).to_csv(results_dir / "db_baseline_results.csv", index=False)
    completed = pd.DataFrame([row for row in rows if row["status"] == "completed"])
    summary = completed.groupby("strategy", dropna=False).agg(
        queries=("query_id", "count"), mean_latency_ms=("strategy_latency_ms", "mean"),
        median_latency_ms=("strategy_latency_ms", "median"), p95_latency_ms=("strategy_latency_ms", lambda values: values.quantile(0.95)),
        mean_recall=("recall", "mean"), min_recall=("recall", "min"),
        min_selectivity=("selectivity", "min"), max_selectivity=("selectivity", "max"),
    ).reset_index()
    summary.to_csv(results_dir / "db_baseline_summary.csv", index=False)
    (results_dir / "db_baseline_run.json").write_text(json.dumps({
        "started_at_utc": datetime.now(timezone.utc).isoformat(), "queries": 32, "top_k": top_k,
        "vector_first_candidate_budget": candidate_budget, "rows": len(rows),
        "failures": sum(row["status"] == "failed" for row in rows),
    }, indent=2) + "\n")
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the 32-query PostgreSQL/pgvector baseline only")
    parser.add_argument("--results-dir", type=Path, required=True)
    parser.add_argument("--top-k", type=int, default=10)
    parser.add_argument("--candidate-budget", type=int, default=100)
    args = parser.parse_args()
    rows = run(args.results_dir, args.top_k, args.candidate_budget)
    print(f"Wrote {len(rows)} result rows to {args.results_dir}")


if __name__ == "__main__":
    main()
