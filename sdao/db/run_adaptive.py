"""Final warm-session adaptive PostgreSQL benchmark.

Planning accepts only the live PostgreSQL ``EXPLAIN (FORMAT JSON)`` estimate.
Measured selectivity is collected by ``DatabaseBenchmark`` only after strategy
selection, as evaluation metadata.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import time
from typing import Any

import pandas as pd

from .baseline_results import FINAL_BASELINE_DIRECTORY
from .calibration import (BucketCalibration, CalibrationModel, LatencyModel,
                          RecallStatistics, SelectivityBucket,
                          StrategyCalibration, bucket_for)
from .connection import connect
from .executor import DBAdaptiveExecutor
from .planner import DBAdaptivePlanner
from .selectivity import PostgresSelectivityAdapter
from .strategy_registry import DatabaseStrategy
from .workload import get_workload_query

QUERY_IDS = tuple(range(32))
TOP_K = 10
VECTOR_FIRST_CANDIDATE_BUDGET = 100
PROJECT_ROOT = Path(__file__).resolve().parents[2]
CALIBRATION_PATH = PROJECT_ROOT / "sdao/results/db_calibration_20260814/db_strategy_calibration.json"
EXPLAIN_ARTIFACT_PATH = PROJECT_ROOT / "sdao/results/db_explain_selectivity_20260814T142459Z/postgres_explain_selectivity.json"
FIXED_STRATEGIES = tuple(DatabaseStrategy)


def _json_default(value: Any) -> Any:
    return getattr(value, "value", str(value))


def _sha256(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def load_calibration(path: Path = CALIBRATION_PATH) -> CalibrationModel:
    """Load the preserved calibration artifact without refitting it."""
    raw = json.loads(path.read_text())
    buckets = tuple(SelectivityBucket(**item) for item in raw["selectivity_buckets"])
    strategies: dict[DatabaseStrategy, StrategyCalibration] = {}
    for name, item in raw["strategies"].items():
        latency = item["latency_model"]
        model = LatencyModel(**latency)
        bucket_models = []
        for bucket in item["buckets"]:
            recall = None if bucket["recall"] is None else RecallStatistics(**bucket["recall"])
            bucket_models.append(BucketCalibration(
                bucket=bucket["bucket"], observation_count=bucket["observation_count"],
                latency_mean_ms=bucket["latency_mean_ms"], latency_median_ms=bucket["latency_median_ms"],
                recall=recall, conservative_feasibility=bucket["conservative_feasibility"],
            ))
        strategies[DatabaseStrategy(name)] = StrategyCalibration(
            strategy=DatabaseStrategy(item["strategy"]), observation_count=item["observation_count"],
            latency_mean_ms=item["latency_mean_ms"], latency_median_ms=item["latency_median_ms"],
            latency_p95_ms=item["latency_p95_ms"], latency_stddev_ms=item["latency_stddev_ms"],
            latency_model=model, recall=RecallStatistics(**item["recall"]), buckets=tuple(bucket_models),
        )
    return CalibrationModel(
        source_path=raw["source_path"], source_observation_count=raw["source_observation_count"],
        expected_query_count=raw["expected_query_count"], target_recall=raw["target_recall"],
        selectivity_buckets=buckets, strategies=strategies, limitations=tuple(raw["limitations"]),
    )


def _recall(result_ids: tuple[int, ...], reference_ids: tuple[int, ...]) -> float:
    return len(set(result_ids).intersection(reference_ids)) / len(reference_ids) if reference_ids else 1.0


def _parameters(strategy: DatabaseStrategy) -> dict[str, int]:
    return {"candidate_budget": VECTOR_FIRST_CANDIDATE_BUDGET} if strategy is DatabaseStrategy.VECTOR_FIRST_HNSW else {}


def _percentile(values: pd.Series) -> float:
    return float(values.quantile(0.95))


def _metric_summary(frame: pd.DataFrame, group_columns: list[str]) -> list[dict[str, Any]]:
    rows = []
    for keys, group in frame.groupby(group_columns, dropna=False, observed=True):
        keys = keys if isinstance(keys, tuple) else (keys,)
        latency = group["strategy_only_latency_ms"]
        recall = group["recall"]
        row = dict(zip(group_columns, keys, strict=True))
        row.update({
            "queries": int(len(group)), "mean_latency_ms": float(latency.mean()),
            "median_latency_ms": float(latency.median()), "p95_latency_ms": _percentile(latency),
            "mean_recall": float(recall.mean()), "minimum_recall": float(recall.min()),
            "fraction_recall_at_least_095": float((recall >= 0.95).mean()),
        })
        rows.append(row)
    return rows


def _regrets(adaptive: list[dict[str, Any]], fixed: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_query: dict[int, list[dict[str, Any]]] = {}
    for row in fixed:
        by_query.setdefault(int(row["query_id"]), []).append(row)
    for row in adaptive:
        choices = by_query[int(row["query_id"])]
        feasible = [item for item in choices if item["recall"] >= 0.95]
        best_feasible = min(feasible, key=lambda item: item["strategy_only_latency_ms"])
        best_any = min(choices, key=lambda item: item["strategy_only_latency_ms"])
        actual = row["strategy_only_latency_ms"]
        row.update({
            "best_feasible_fixed_strategy": best_feasible["strategy"],
            "best_feasible_fixed_latency_ms": best_feasible["strategy_only_latency_ms"],
            "planner_regret_vs_best_feasible_fixed_ms": actual - best_feasible["strategy_only_latency_ms"],
            "best_actual_fixed_strategy": best_any["strategy"],
            "best_actual_fixed_latency_ms": best_any["strategy_only_latency_ms"],
            "regret_vs_best_actual_fixed_ms": actual - best_any["strategy_only_latency_ms"],
        })
    return adaptive


def _execute(executor: DBAdaptiveExecutor, workload, strategy: DatabaseStrategy, estimated_selectivity: float | None) -> dict[str, Any]:
    """Run the verified strategy, then independently obtain filtered exact reference."""
    started = time.perf_counter_ns()
    result = executor.execute(
        query_id=workload.query_id, predicate=workload.predicate, query_vector=workload.vector,
        top_k=TOP_K, strategy=strategy, strategy_parameters=_parameters(strategy),
        estimated_selectivity=estimated_selectivity,
    )
    execution_wall_latency_ms = (time.perf_counter_ns() - started) / 1_000_000
    if not result.success:
        raise RuntimeError(f"query {workload.query_id} {strategy.value} failed: {result.error}")
    request = executor.benchmark.request_from_workload(workload.query_id, TOP_K, workload)
    reference = executor.benchmark.filtered_ground_truth(request)
    reference_ids = tuple(int(value) for value in reference["result_ids"])
    return {
        "query_id": workload.query_id, "predicate": workload.predicate, "query_type": workload.query_type,
        "strategy": strategy.value, "estimated_selectivity": estimated_selectivity,
        "measured_selectivity": result.measured_selectivity, "top_k": TOP_K,
        "strategy_only_latency_ms": result.latency_ms, "execution_wall_latency_ms": execution_wall_latency_ms,
        "reference_latency_ms": reference["reference_latency_ms"], "recall": _recall(result.result_ids, reference_ids),
        "result_ids": list(result.result_ids), "reference_ids": list(reference_ids),
        "plan_verified": result.plan_verified, "plan_verification_status": result.plan_verification_status,
        "expected_index": result.expected_index, "actual_index_names": list(result.actual_index_names),
        "plan_evidence": result.plan_evidence,
        "strategy_parameters": result.strategy_parameters, "postgres_version": result.postgres_version,
        "pgvector_version": result.pgvector_version,
    }


def run(output: Path) -> Path:
    if output.exists():
        raise FileExistsError(f"output directory already exists: {output}")
    calibration = load_calibration()
    planner = DBAdaptivePlanner(calibration)
    source_hashes = {str(path.relative_to(PROJECT_ROOT)): _sha256(path) for path in (CALIBRATION_PATH, EXPLAIN_ARTIFACT_PATH)}
    source_hashes[str(FINAL_BASELINE_DIRECTORY.relative_to(PROJECT_ROOT) / "db_baseline_results.json")] = _sha256(FINAL_BASELINE_DIRECTORY / "db_baseline_results.json")
    adaptive, fixed = [], []
    connection = connect()
    executor = DBAdaptiveExecutor(connection=connection)
    try:
        for query_id in QUERY_IDS:
            workload = get_workload_query(query_id)
            estimate_started = time.perf_counter_ns()
            estimate = PostgresSelectivityAdapter(connection).estimate(workload.predicate)
            explain_latency_ms = (time.perf_counter_ns() - estimate_started) / 1_000_000
            plan_started = time.perf_counter_ns()
            decision = planner.plan(query_id=query_id, predicate=workload.predicate, top_k=TOP_K,
                                    estimated_selectivity=estimate.estimated_selectivity)
            planning_latency_ms = (time.perf_counter_ns() - plan_started) / 1_000_000
            selected = _execute(executor, workload, decision.selected_strategy, estimate.estimated_selectivity)
            selected.update({
                "planner_decision": json.loads(decision.to_json()), "estimated_rows": estimate.estimated_rows,
                "explain_latency_ms": explain_latency_ms, "planning_latency_ms": planning_latency_ms,
                "actual_latency_ms": explain_latency_ms + planning_latency_ms + selected["execution_wall_latency_ms"],
            })
            selected["selectivity_bucket"] = bucket_for(estimate.estimated_selectivity, calibration.selectivity_buckets).name
            adaptive.append(selected)
            for strategy in FIXED_STRATEGIES:
                row = _execute(executor, workload, strategy, None)
                row["selectivity_bucket"] = bucket_for(float(row["measured_selectivity"]), calibration.selectivity_buckets).name
                fixed.append(row)
    finally:
        executor.close()
        connection.close()

    if len(adaptive) != len(QUERY_IDS) or len(fixed) != len(QUERY_IDS) * len(FIXED_STRATEGIES):
        raise RuntimeError("final benchmark did not complete the required 32 adaptive and 128 fixed executions")
    _regrets(adaptive, fixed)
    adaptive_frame, fixed_frame = pd.DataFrame(adaptive), pd.DataFrame(fixed)
    adaptive_summary = _metric_summary(adaptive_frame, ["strategy"])
    fixed_summary = _metric_summary(fixed_frame, ["strategy"])
    bucket_summary = _metric_summary(adaptive_frame, ["selectivity_bucket", "strategy"])
    result = {
        "artifact_type": "final_adaptive_postgresql_benchmark", "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "methodology": {
            "queries": 32, "top_k": TOP_K, "warm_persistent_session": True,
            "connection_method": "one persistent psycopg connection for the full adaptive and fixed workload",
            "ann_parameters": {"vector_first_candidate_budget": VECTOR_FIRST_CANDIDATE_BUDGET,
                               "hnsw_ef_search": 100, "hnsw_iterative_scan": "strict_order",
                               "hnsw_max_scan_tuples": 20000, "ivfflat_probes": 10, "ivfflat_iterative_scan": "off"},
            "persistent_postgresql_configuration_changes": False,
            "planning_selectivity": "live PostgreSQL EXPLAIN (FORMAT JSON) estimate only",
            "measured_selectivity": "post-execution SELECT count(*) evaluation metadata; never passed to planner",
            "actual_latency_definition": "EXPLAIN estimate + planner + verified executor wall time; excludes exact reference evaluation",
            "strategy_only_latency_definition": "timed selected SQL execution only; comparable across adaptive and fixed rows",
            "reference": "exact filtered PostgreSQL SQL_FIRST query, executed after each strategy for evaluation",
        },
        "source_artifact_sha256_before": source_hashes,
        "adaptive_records": adaptive, "fixed_strategy_records": fixed,
        "adaptive_summary": adaptive_summary, "fixed_strategy_summary": fixed_summary,
        "adaptive_by_estimated_selectivity_bucket": bucket_summary,
        "strategy_distribution": adaptive_frame["strategy"].value_counts().sort_index().to_dict(),
        "planner_regret_summary_ms": {
            "mean_vs_best_feasible_fixed": float(adaptive_frame["planner_regret_vs_best_feasible_fixed_ms"].mean()),
            "median_vs_best_feasible_fixed": float(adaptive_frame["planner_regret_vs_best_feasible_fixed_ms"].median()),
            "p95_vs_best_feasible_fixed": _percentile(adaptive_frame["planner_regret_vs_best_feasible_fixed_ms"]),
            "mean_vs_best_actual_fixed": float(adaptive_frame["regret_vs_best_actual_fixed_ms"].mean()),
        },
    }
    if source_hashes != {key: _sha256(PROJECT_ROOT / key) for key in source_hashes}:
        raise RuntimeError("a protected source artifact changed during the benchmark")
    output.mkdir(parents=True)
    (output / "final_adaptive_results.json").write_text(json.dumps(result, indent=2, default=_json_default) + "\n")
    adaptive_frame.to_csv(output / "adaptive_per_query.csv", index=False)
    fixed_frame.to_csv(output / "fixed_strategies_per_query.csv", index=False)
    pd.DataFrame(adaptive_summary).to_csv(output / "adaptive_summary.csv", index=False)
    pd.DataFrame(fixed_summary).to_csv(output / "fixed_strategy_summary.csv", index=False)
    pd.DataFrame(bucket_summary).to_csv(output / "adaptive_by_estimated_selectivity_bucket.csv", index=False)
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description="Run final adaptive DB benchmark with all fixed strategy comparisons")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(f"Wrote final adaptive benchmark to {run(args.output)}")


if __name__ == "__main__":
    main()
