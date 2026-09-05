#!/usr/bin/env python3
"""Leakage-free benchmark for a PostgreSQL/pgvector hybrid query optimizer.

The script expects the ``sift_hybrid`` table created by ``load_sift_hybrid.py``:
``id``, ``embedding vector(128)``, ``category``, ``price``, and ``in_stock``.
It generates 500 queries, assigns exactly 250 to calibration and 250 to a
held-out test split, builds a calibration map from calibration observations,
and evaluates fixed and adaptive policies on the held-out queries.

The adaptive policy uses only the held-out query's PostgreSQL EXPLAIN estimate,
its selectivity bucket, and calibration statistics. Test observations are never
added to the calibration map.

Example:
    venv/bin/python benchmark_hybrid_optimizer.py \
        --output benchmark_results.csv \
        --host localhost --database sdao --user sdao \
        --password "$POSTGRES_PASSWORD"
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
import csv
import json
import math
import os
from pathlib import Path
import time
from typing import Any, Iterable

import numpy as np
import pandas as pd
import psycopg2


TABLE_NAME = "sift_hybrid"
VECTOR_DIMENSION = 128
DATASET_SIZE = 1_000_000
QUERY_COUNT = 500
CALIBRATION_COUNT = 250
TEST_COUNT = 250
TOP_K = 10
REPETITIONS = 5
TARGET_RECALL = 0.95
STRATEGIES = ("SQL_FIRST", "VECTOR_FIRST_HNSW", "HNSW_HYBRID", "IVFFLAT_HYBRID")
# Load-bearing invariant: SQL_FIRST occupies index 0. choose_adaptive_strategy()
# slices STRATEGIES[1:], and the ground-truth reference logic executes SQL_FIRST
# first within every repetition. Fail at import time if this is ever reordered.
if STRATEGIES[0] != "SQL_FIRST":
    raise RuntimeError("STRATEGIES[0] must be 'SQL_FIRST'")
BUCKETS = ((0.0, 0.05), (0.05, 0.10), (0.10, 0.25), (0.25, 0.50), (0.50, 1.01))
CATEGORIES = tuple(f"category_{index:02d}" for index in range(10))
DEFAULT_VECTOR_PATH = Path(__file__).resolve().parent / "dataset" / "sift" / "sift_base.fvecs"


@dataclass(frozen=True)
class Query:
    query_id: int
    vector: np.ndarray
    category: str
    price_limit: float
    in_stock: bool
    target_selectivity: float

    @property
    def predicate_sql(self) -> str:
        if self.target_selectivity < 0.25:
            return "(category = %s AND price < %s AND in_stock = %s)"
        if self.target_selectivity < 0.60:
            return "((category = %s AND price < %s) OR in_stock = %s)"
        return "(category = %s OR price < %s OR in_stock = %s)"

    @property
    def predicate_params(self) -> tuple[Any, ...]:
        return self.category, self.price_limit, self.in_stock


@dataclass(frozen=True)
class Observation:
    query_id: int
    strategy: str
    estimated_selectivity: float
    latency_ms: float
    result_ids: tuple[int, ...]
    recall: float


def read_fvecs(path: Path) -> np.ndarray:
    """Read a standard SIFT .fvecs file as float32 vectors."""
    if not path.is_file():
        raise FileNotFoundError(path)
    raw = np.fromfile(path, dtype=np.int32)
    width = VECTOR_DIMENSION + 1
    if raw.size == 0 or raw.size % width:
        raise ValueError(f"Malformed .fvecs file: {path}")
    records = raw.reshape(-1, width)
    if not np.all(records[:, 0] == VECTOR_DIMENSION):
        raise ValueError(f"Expected {VECTOR_DIMENSION}-dimensional vectors")
    return records[:, 1:].view(np.float32).reshape(-1, VECTOR_DIMENSION)


def generate_queries(vectors: np.ndarray, seed: int) -> list[Query]:
    """Generate varied predicates while preserving a reproducible workload."""
    rng = np.random.default_rng(seed)
    queries: list[Query] = []
    for query_id in range(QUERY_COUNT):
        target = float(rng.uniform(0.01, 1.0))
        category = str(rng.choice(CATEGORIES))
        in_stock = bool(rng.integers(0, 2))
        # Price thresholds span the domain and are adjusted by target. The
        # target is recorded metadata; EXPLAIN remains the decision input.
        price_limit = float(np.clip(10.0 + 990.0 * target, 10.01, 1000.0))
        vector = vectors[int(rng.integers(0, len(vectors)))].copy()
        queries.append(Query(query_id, vector, category, price_limit, in_stock, target))
    return queries


def split_queries(queries: list[Query], seed: int) -> tuple[list[Query], list[Query]]:
    """Return exactly 250 calibration and 250 held-out queries."""
    if len(queries) != QUERY_COUNT:
        raise ValueError(f"expected {QUERY_COUNT} queries")
    rng = np.random.default_rng(seed)
    order = rng.permutation(len(queries))
    calibration_ids = set(int(value) for value in order[:CALIBRATION_COUNT])
    calibration = [query for query in queries if query.query_id in calibration_ids]
    held_out = [query for query in queries if query.query_id not in calibration_ids]
    if len(calibration) != CALIBRATION_COUNT or len(held_out) != TEST_COUNT:
        raise RuntimeError("invalid disjoint split")
    return calibration, held_out


def bucket_for(selectivity: float) -> str:
    for lower, upper in BUCKETS:
        if lower <= selectivity < upper:
            return f"[{lower:.2f},{min(upper, 1.0):.2f})"
    return "[0.50,1.00]"


def recall_at_10(result_ids: Iterable[int], reference_ids: Iterable[int]) -> float:
    reference = set(reference_ids)
    return 1.0 if not reference else len(set(result_ids) & reference) / len(reference)


class PostgreSQLBenchmark:
    """Run parameterized strategies and planning-time EXPLAIN estimates."""

    def __init__(self, connection: Any, vector_first_budget: int = 100) -> None:
        self.connection = connection
        self.vector_first_budget = max(TOP_K, vector_first_budget)

    @staticmethod
    def _set_local(cursor: Any, settings: dict[str, Any]) -> None:
        for key, value in settings.items():
            cursor.execute("SELECT set_config(%s, %s, true)", (key, str(value)))

    @staticmethod
    def _vector_literal(vector: np.ndarray) -> str:
        if vector.shape != (VECTOR_DIMENSION,) or not np.isfinite(vector).all():
            raise ValueError("query vectors must be finite 128-dimensional arrays")
        return "[" + ",".join(repr(float(value)) for value in vector) + "]"

    def estimate_selectivity(self, query: Query) -> float:
        """Get estimated selectivity from EXPLAIN without executing the query."""
        with self.connection:
            with self.connection.cursor() as cursor:
                cursor.execute(
                    f"EXPLAIN (FORMAT JSON) SELECT id FROM {TABLE_NAME} WHERE {query.predicate_sql}",
                    query.predicate_params,
                )
                plan = cursor.fetchone()[0]
        if isinstance(plan, str):
            plan = json.loads(plan)
        try:
            rows = int(plan[0]["Plan"]["Plan Rows"])
        except (IndexError, KeyError, TypeError, ValueError) as exc:
            raise RuntimeError("EXPLAIN JSON did not contain Plan Rows") from exc
        return float(np.clip(rows / DATASET_SIZE, 0.0, 1.0))

    def capture_plan(self, query: Query, strategy: str) -> list[str]:
        """Untimed EXPLAIN of the exact executed statement (same settings)."""
        statement, params, settings = self._statement(query, strategy)
        with self.connection:
            with self.connection.cursor() as cursor:
                self._set_local(cursor, settings)
                cursor.execute("EXPLAIN (FORMAT JSON) " + statement, params)
                plan = cursor.fetchone()[0]
        if isinstance(plan, str):
            plan = json.loads(plan)
        names: list[str] = []

        def walk(node: dict[str, Any]) -> None:
            if node.get("Index Name"):
                names.append(node["Index Name"])
            for child in node.get("Plans", []):
                walk(child)

        walk(plan[0]["Plan"])
        return names

    def _statement(self, query: Query, strategy: str) -> tuple[str, tuple[Any, ...], dict[str, Any]]:
        vector = self._vector_literal(query.vector)
        if strategy == "SQL_FIRST":
            return (
                f"SELECT id FROM {TABLE_NAME} WHERE {query.predicate_sql} "
                "ORDER BY embedding <-> %s::vector, id LIMIT %s",
                query.predicate_params + (vector, TOP_K),
                {"enable_indexscan": "off"},
            )
        if strategy == "VECTOR_FIRST_HNSW":
            return (
                f"WITH candidates AS MATERIALIZED (SELECT id, embedding <-> %s::vector AS distance "
                f"FROM {TABLE_NAME} ORDER BY embedding <-> %s::vector LIMIT {self.vector_first_budget}) "
                f"SELECT candidates.id FROM candidates JOIN {TABLE_NAME} item ON item.id = candidates.id "
                f"WHERE {query.predicate_sql} "
                "ORDER BY candidates.distance, candidates.id LIMIT %s",
                (vector, vector) + query.predicate_params + (TOP_K,),
                {"hnsw.ef_search": 100, "ivfflat.probes": 1000},
            )
        if strategy == "HNSW_HYBRID":
            return (
                f"SELECT id FROM {TABLE_NAME} WHERE {query.predicate_sql} "
                "ORDER BY embedding <-> %s::vector LIMIT %s",
                query.predicate_params + (vector, TOP_K),
                {"hnsw.ef_search": 100, "ivfflat.probes": 1000},
            )
        if strategy == "IVFFLAT_HYBRID":
            return (
                f"SELECT id FROM {TABLE_NAME} WHERE {query.predicate_sql} "
                "ORDER BY embedding <-> %s::vector LIMIT %s",
                query.predicate_params + (vector, TOP_K),
                {"ivfflat.probes": 10, "hnsw.ef_search": 1000},
            )
        raise ValueError(f"unknown strategy: {strategy}")

    def execute_once(self, query: Query, strategy: str, estimated_selectivity: float, reference_ids: tuple[int, ...] | None = None) -> Observation:
        statement, params, settings = self._statement(query, strategy)
        with self.connection:
            with self.connection.cursor() as cursor:
                self._set_local(cursor, settings)
                started = time.perf_counter_ns()
                cursor.execute(statement, params)
                result_ids = tuple(int(row[0]) for row in cursor.fetchall())
                latency_ms = (time.perf_counter_ns() - started) / 1_000_000
        reference = result_ids if reference_ids is None else reference_ids
        return Observation(query.query_id, strategy, estimated_selectivity, latency_ms, result_ids, recall_at_10(result_ids, reference))


def run_query(benchmark: PostgreSQLBenchmark, query: Query, split: str, repetitions: int) -> list[Observation]:
    """Run SQL_FIRST plus all strategies, reusing the exact reference per query."""
    estimate = benchmark.estimate_selectivity(query)
    observations: list[Observation] = []
    reference_ids: tuple[int, ...] | None = None
    for _ in range(repetitions):
        exact = benchmark.execute_once(query, "SQL_FIRST", estimate)
        reference_ids = exact.result_ids if reference_ids is None else reference_ids
        observations.append(exact)
        for strategy in STRATEGIES[1:]:
            observations.append(benchmark.execute_once(query, strategy, estimate, reference_ids))
    return observations


def build_calibration_map(observations: list[Observation]) -> dict[tuple[str, str], dict[str, float]]:
    """Build latency median and minimum recall from calibration observations only."""
    grouped: dict[tuple[str, str], list[Observation]] = defaultdict(list)
    for observation in observations:
        grouped[(observation.strategy, bucket_for(observation.estimated_selectivity))].append(observation)
    calibration: dict[tuple[str, str], dict[str, float]] = {}
    for key, values in grouped.items():
        calibration[key] = {
            "median_latency_ms": float(np.median([value.latency_ms for value in values])),
            "minimum_recall": float(min(value.recall for value in values)),
            "observations": float(len(values)),
        }
    return calibration


def choose_adaptive_strategy(estimate: float, calibration: dict[tuple[str, str], dict[str, float]]) -> str:
    """Select the lowest-calibrated-latency strategy meeting the recall gate."""
    bucket = bucket_for(estimate)
    candidates = ["SQL_FIRST"]
    for strategy in STRATEGIES[1:]:
        evidence = calibration.get((strategy, bucket))
        if evidence and evidence["minimum_recall"] >= TARGET_RECALL:
            candidates.append(strategy)
    return min(
        candidates,
        key=lambda strategy: calibration.get((strategy, bucket), {"median_latency_ms": float("inf")})["median_latency_ms"]
        if strategy != "SQL_FIRST" else calibration.get((strategy, bucket), {"median_latency_ms": float("inf")})["median_latency_ms"],
    )


RAW_FIELDS = (
    "ts_utc", "phase", "repetition", "query_id", "strategy",
    "target_selectivity", "estimated_selectivity", "bucket",
    "latency_ms", "recall_at_10", "result_ids", "reference_source",
    "adaptive_selected_strategy", "is_adaptive_selection",
    "plan_index_names", "plan_verified", "access_path",
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


ANN_NEEDLE = {"VECTOR_FIRST_HNSW": "hnsw", "HNSW_HYBRID": "hnsw",
              "IVFFLAT_HYBRID": "ivfflat"}


def classify_plan(strategy: str, index_names: list[str]) -> tuple[bool, str]:
    """Return ``(plan_verified, access_path)`` for one captured plan.

    ``plan_verified`` is the strict named-access-path check: SQL_FIRST must
    involve NO ANN index; each ANN strategy must use its own index type.
    ``access_path`` records how the query was actually served so that
    planner-preferred exact bitmap/sequential paths are transparent without
    counting as failures.
    """
    lowered = [str(name).lower() for name in index_names]
    ann_used = any("hnsw" in name or "ivfflat" in name for name in lowered)
    if any("ivfflat" in name for name in lowered):
        access_path = "ivfflat_index"
    elif any("hnsw" in name for name in lowered):
        access_path = "hnsw_index"
    elif lowered:
        access_path = "exact_bitmap"
    else:
        access_path = "exact_seq"
    needle = ANN_NEEDLE.get(strategy)
    verified = not ann_used if needle is None else any(
        needle in name for name in lowered)
    return verified, access_path


def execution_row(phase: str, query: Query, estimate: float, observation: Observation,
                  repetition: int, adaptive_strategy: str = "",
                  plan: tuple[list[str], bool, str] | None = None) -> dict[str, Any]:
    """Materialize one physical execution as a persistable record."""
    index_names, verified, access_path = plan if plan else ([], None, "")
    return {
        "ts_utc": _utc_now(),
        "phase": phase,
        "repetition": repetition,
        "query_id": query.query_id,
        "strategy": observation.strategy,
        "target_selectivity": query.target_selectivity,
        "estimated_selectivity": estimate,
        "bucket": bucket_for(estimate),
        "latency_ms": observation.latency_ms,
        "recall_at_10": observation.recall,
        "result_ids": json.dumps(observation.result_ids),
        # One canonical reference per query: the FIRST SQL_FIRST execution
        # (repetition 0). Every other execution of any strategy — including
        # SQL_FIRST's own repetitions 1-4 — is scored against those exact IDs.
        "reference_source": "" if observation.strategy == "SQL_FIRST"
        and repetition == 0 else "sql_first_rep0",
        "adaptive_selected_strategy": adaptive_strategy,
        "is_adaptive_selection": observation.strategy == adaptive_strategy,
        "plan_index_names": json.dumps(index_names),
        "plan_verified": verified,
        "access_path": access_path,
    }


def verify_plan(strategy: str, index_names: list[str]) -> bool:
    """Deprecated single-value wrapper kept for compatibility; use classify_plan."""
    return classify_plan(strategy, index_names)[0]


def percentile(values: pd.Series, probability: float) -> float:
    return float(values.quantile(probability))


def summarize(records: list[dict[str, Any]]) -> pd.DataFrame:
    frame = pd.DataFrame(records)
    rows: list[dict[str, Any]] = []
    for strategy, group in frame.groupby("strategy", observed=True):
        latency = group["median_latency_ms"]
        recall = group["recall_at_10"]
        rows.append({
            "strategy": strategy,
            "queries": len(group),
            "mean_latency_ms": float(latency.mean()),
            "median_latency_ms": float(latency.median()),
            "p95_latency_ms": percentile(latency, 0.95),
            "mean_recall_at_10": float(recall.mean()),
            "fraction_recall_at_least_095": float((recall >= TARGET_RECALL).mean()),
        })
    return pd.DataFrame(rows).sort_values("strategy").reset_index(drop=True)


def connection_kwargs(args: argparse.Namespace) -> dict[str, Any]:
    return {
        "host": args.host or os.getenv("POSTGRES_HOST", "localhost"),
        "port": args.port or int(os.getenv("POSTGRES_PORT", "5432")),
        "dbname": args.database or os.getenv("POSTGRES_DB", "sdao"),
        "user": args.user or os.getenv("POSTGRES_USER", "sdao"),
        "password": args.password or os.getenv("POSTGRES_PASSWORD", ""),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("benchmark_results.csv"))
    parser.add_argument("--results-dir", type=Path, default=None,
                        help="Persist per-execution, per-query, summary and "
                             "metadata files into this directory.")
    parser.add_argument("--vector-path", type=Path, default=DEFAULT_VECTOR_PATH)
    parser.add_argument("--host")
    parser.add_argument("--port", type=int)
    parser.add_argument("--database")
    parser.add_argument("--user")
    parser.add_argument("--password")
    parser.add_argument("--seed", type=int, default=20260820)
    parser.add_argument("--repetitions", type=int, default=REPETITIONS)
    parser.add_argument("--vector-first-budget", type=int, default=100)
    args = parser.parse_args()
    if args.repetitions != REPETITIONS:
        raise SystemExit("This harness requires exactly 5 repetitions per test query")
    if not args.password and not os.getenv("POSTGRES_PASSWORD"):
        raise SystemExit("Provide --password or set POSTGRES_PASSWORD")

    query_vectors = read_fvecs(args.vector_path.expanduser().resolve())
    queries = generate_queries(query_vectors, args.seed)
    calibration_queries, test_queries = split_queries(queries, args.seed + 1)
    connection = psycopg2.connect(**connection_kwargs(args))
    benchmark = PostgreSQLBenchmark(connection, args.vector_first_budget)
    run_started_at = _utc_now()
    with connection.cursor() as cursor:
        cursor.execute("SELECT version()")
        db_versions = {"postgres": str(cursor.fetchone()[0])}
        cursor.execute("SELECT extversion FROM pg_extension WHERE extname = 'vector'")
        row = cursor.fetchone()
        db_versions["pgvector"] = str(row[0]) if row else "not installed"
    print(f"Connected. postgres={db_versions['postgres'][:80]}")
    print(f"pgvector={db_versions['pgvector']}")
    if args.results_dir is not None:
        args.results_dir.mkdir(parents=True, exist_ok=True)
        summary_path = args.results_dir / "summary.csv"
        calibration_path = args.results_dir / "calibration_per_execution.csv"
        heldout_raw_path = args.results_dir / "heldout_per_execution.csv"
        per_query_path = args.results_dir / "heldout_per_query.csv"
        metadata_path = args.results_dir / "run_metadata.json"
    else:
        summary_path = args.output
        calibration_path = heldout_raw_path = per_query_path = metadata_path = None
    try:
        print("Calibration phase: 250 queries x 4 strategies")
        calibration_observations: list[Observation] = []
        calib_handle = calibration_path.open("w", newline="") if calibration_path else None
        calib_writer = None
        if calib_handle is not None:
            calib_writer = csv.DictWriter(calib_handle, fieldnames=RAW_FIELDS)
            calib_writer.writeheader()
        calibration_executed = 0
        for query in calibration_queries:
            observations = run_query(benchmark, query, "calibration", 1)
            calibration_observations.extend(observations)
            for observation in observations:  # repetitions=1 -> rep index 0
                if calib_writer is not None:
                    calib_writer.writerow(execution_row(
                        "calibration", query, observation.estimated_selectivity,
                        observation, 0))
                    calib_handle.flush()
                calibration_executed += 1
        if calib_handle is not None:
            calib_handle.close()
        print(f"Calibration executions persisted: {calibration_executed}")
        calibration = build_calibration_map(calibration_observations)
        print("Held-out phase: 250 queries x 4 strategies x 5 repetitions")
        raw_handle = heldout_raw_path.open("w", newline="") if heldout_raw_path else None
        raw_writer = None
        if raw_handle is not None:
            raw_writer = csv.DictWriter(raw_handle, fieldnames=RAW_FIELDS)
            raw_writer.writeheader()
        test_records: list[dict[str, Any]] = []
        executed = 0
        nondeterministic_queries = 0
        for query in test_queries:
            explain_started = time.perf_counter_ns()
            estimate = benchmark.estimate_selectivity(query)
            explain_ms = (time.perf_counter_ns() - explain_started) / 1_000_000
            # Unchanged selection function; evaluated before execution so each
            # raw row can carry the decision (was previously computed after).
            decide_started = time.perf_counter_ns()
            adaptive_strategy = choose_adaptive_strategy(estimate, calibration)
            decision_ms = (time.perf_counter_ns() - decide_started) / 1_000_000
            fixed_runs = {strategy: [] for strategy in STRATEGIES}
            plan_cache: dict[str, tuple[list[str], bool, str]] = {}
            # Canonical ground truth: captured once per query from the FIRST
            # executed strategy (STRATEGIES[0] == SQL_FIRST, enforced at import)
            # during repetition 0, then reused for every strategy/repetition.
            reference_ids: tuple[int, ...] | None = None
            sql_first_reps: list[tuple[int, ...]] = []
            for repetition_index in range(REPETITIONS):
                for strategy in STRATEGIES:
                    observation = benchmark.execute_once(query, strategy, estimate, reference_ids)
                    executed += 1
                    if strategy == "SQL_FIRST":
                        if len(observation.result_ids) != TOP_K:
                            raise RuntimeError(
                                f"query {query.query_id}: SQL_FIRST returned "
                                f"{len(observation.result_ids)} rows, expected {TOP_K}")
                        if reference_ids is None:
                            if repetition_index != 0:
                                raise RuntimeError(
                                    f"query {query.query_id}: reference captured on "
                                    f"repetition {repetition_index}, expected 0")
                            reference_ids = observation.result_ids
                        sql_first_reps.append(observation.result_ids)
                    elif reference_ids is None:
                        raise RuntimeError(
                            f"query {query.query_id}: strategy {strategy} executed "
                            "before the SQL_FIRST reference was established")
                    if strategy not in plan_cache:
                        index_names = benchmark.capture_plan(query, strategy)
                        plan_cache[strategy] = (index_names,
                                                *classify_plan(strategy, index_names))
                    if raw_writer is not None:
                        raw_writer.writerow(execution_row(
                            "held_out", query, estimate, observation,
                            repetition_index, adaptive_strategy,
                            plan_cache[strategy]))
                        raw_handle.flush()
                    fixed_runs[strategy].append(observation)
            sql_first_deterministic = all(
                ids == sql_first_reps[0] for ids in sql_first_reps[1:])
            if not sql_first_deterministic:
                nondeterministic_queries += 1
                print(f"WARNING: SQL_FIRST result IDs differ across repetitions "
                      f"for query_id={query.query_id}; ground truth is unstable.")
            for strategy in STRATEGIES:
                runs = fixed_runs[strategy]
                index_names, verified, access_path = plan_cache[strategy]
                test_records.append({
                    "query_id": query.query_id,
                    "strategy": strategy,
                    "median_latency_ms": float(np.median([run.latency_ms for run in runs])),
                    "recall_at_10": float(np.median([run.recall for run in runs])),
                    "estimated_selectivity": estimate,
                    "bucket": bucket_for(estimate),
                    "adaptive_selected_strategy": adaptive_strategy,
                    "is_adaptive_selection": strategy == adaptive_strategy,
                    "repetitions": len(runs),
                    "plan_index_names": json.dumps(index_names),
                    "plan_verified": bool(verified),
                    "access_path": access_path,
                    "explain_ms": round(explain_ms, 4),
                    "decision_ms": round(decision_ms, 4),
                    "selected_exec_ms": round(
                        float(fixed_runs[adaptive_strategy][0].latency_ms), 4),
                    "decision_overhead_ms": round(
                        explain_ms + decision_ms
                        + float(fixed_runs[adaptive_strategy][0].latency_ms), 4),
                    "sql_first_deterministic": bool(sql_first_deterministic),
                })
        if raw_handle is not None:
            raw_handle.close()
        print(f"Held-out executions persisted: {executed}")
        if nondeterministic_queries:
            print(f"WARNING: {nondeterministic_queries} held-out queries had "
                  f"non-deterministic SQL_FIRST results across repetitions.")
        summary = summarize(test_records)
        adaptive_rows = [row for row in test_records if row["strategy"] == row["adaptive_selected_strategy"]]
        adaptive_summary = summarize(adaptive_rows).assign(strategy="Adaptive")
        summary = pd.concat([summary, adaptive_summary], ignore_index=True)
        summary_path.parent.mkdir(parents=True, exist_ok=True)
        summary.to_csv(summary_path, index=False)
        if per_query_path is not None:
            pd.DataFrame(test_records).to_csv(per_query_path, index=False)
        print(summary.to_string(index=False))
        print(f"Wrote {summary_path}"
              + (f", {per_query_path}" if per_query_path else ""))
        if metadata_path is not None:
            metadata_path.write_text(json.dumps({
                "started_at_utc": run_started_at,
                "finished_at_utc": _utc_now(),
                "seed": args.seed,
                "split_seed": args.seed + 1,
                "query_count": QUERY_COUNT,
                "calibration_count": CALIBRATION_COUNT,
                "heldout_count": TEST_COUNT,
                "repetitions": REPETITIONS,
                "top_k": TOP_K,
                "target_recall": TARGET_RECALL,
                "vector_first_budget": args.vector_first_budget,
                "postgres_version": db_versions["postgres"],
                "pgvector_version": db_versions["pgvector"],
                "calibration_executions": calibration_executed,
                "heldout_executions": executed,
                "per_query_records": len(test_records),
                "plans_verified": int(sum(
                    1 for r in test_records if r["plan_verified"])),
                "sql_first_nondeterministic_queries": nondeterministic_queries,
                "decision_overhead_ms": (lambda oh: {
                    "mean": round(float(oh.mean()), 3),
                    "median": round(float(oh.median()), 3),
                    "p95": round(float(oh.quantile(0.95)), 3),
                })(pd.Series([r["decision_overhead_ms"] for r in test_records])),
                "access_path_by_strategy": {
                    strategy: pd.Series(
                        [r["access_path"] for r in test_records
                         if r["strategy"] == strategy]
                    ).value_counts().to_dict()
                    for strategy in STRATEGIES
                },
            }, indent=2) + "\n")
        return 0
    finally:
        connection.close()


if __name__ == "__main__":
    raise SystemExit(main())
