"""Held-out evaluation harness for the PostgreSQL/pgvector prototype.

This script addresses calibration leakage by generating one workload, assigning
queries to disjoint calibration and held-out partitions, fitting calibration
summaries only on the calibration partition, and evaluating every fixed
strategy only on the held-out partition.

The generated predicates use ``price < threshold``. Thresholds are selected
from the local metadata quantiles so requested selectivities are approximately
uniform on [0.01, 1.0] while remaining valid hybrid relational predicates. The
achieved planning-time selectivity is recorded from PostgreSQL EXPLAIN and is
used for calibration buckets and dynamic vector-first candidate budgets.

The harness uses psycopg 3, the dependency already used by this repository.
It does not create, modify, or delete database objects.

Example:
    python -m sdao.db.evaluate_heldout \
        --output sdao/results/db_heldout_20260820 \
        --repetitions 5
"""
from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import time
from typing import Any, Iterable

import numpy as np
import pandas as pd

from .benchmark import HNSW_INDEX_NAME, IVFFLAT_INDEX_NAME
from .config import DatabaseConfig
from .loader import ATTRIBUTE_FILE, TABLE_NAME, _vector_literal
from ..utils.data_loader import QUERY_FILE, read_fvecs

try:
    import psycopg
except ImportError as exc:  # pragma: no cover - depends on optional DB install
    raise RuntimeError("Install requirements-db.txt before running this harness.") from exc


STRATEGIES = (
    "SQL_FIRST",
    "VECTOR_FIRST_HNSW",
    "HNSW_HYBRID",
    "IVFFLAT_HYBRID",
)
TARGET_RECALL = 0.95
DEFAULT_QUERY_COUNT = 500
DEFAULT_CALIBRATION_FRACTION = 0.50
DEFAULT_REPETITIONS = 5
DEFAULT_CALIBRATION_REPETITIONS = 1
DEFAULT_TOP_K = 10
DEFAULT_SAFETY_FACTOR = 2.0
DEFAULT_BOOTSTRAPS = 2_000
DEFAULT_RUNS = 5
LOW_CONFIDENCE_BUCKET_THRESHOLD = 10


@dataclass(frozen=True)
class SyntheticQuery:
    query_id: int
    target_selectivity: float
    price_threshold: int
    category: str
    in_stock: bool
    predicate: str
    vector_id: int


@dataclass(frozen=True)
class QuerySplit:
    query_id: int
    split: str


@dataclass(frozen=True)
class RunRecord:
    query_id: int
    split: str
    strategy: str
    repetition: int
    target_selectivity: float
    estimated_selectivity: float
    price_threshold: int
    vector_id: int
    candidate_budget: int
    latency_ms: float
    result_ids: tuple[int, ...]
    reference_ids: tuple[int, ...]
    recall: float
    plan_verified: bool
    actual_index_names: tuple[str, ...]
    postgres_version: str | None
    pgvector_version: str | None


@dataclass(frozen=True)
class PlanVerificationFailure:
    query_id: int
    strategy: str
    split: str
    repetition: int
    predicate: str
    estimated_selectivity: float
    candidate_budget: int
    expected_index: str | None
    actual_index_names: tuple[str, ...]
    node_types: tuple[str, ...]
    used_hnsw: bool
    used_seq_scan: bool
    error: str


def _json_default(value: Any) -> Any:
    if isinstance(value, (np.integer, np.floating)):
        return value.item()
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, tuple):
        return list(value)
    raise TypeError(f"Cannot serialize {type(value)!r}")


def _percentile(values: Iterable[float], probability: float) -> float:
    return float(np.percentile(np.asarray(list(values), dtype=float), probability * 100))


def _recall(result_ids: tuple[int, ...], reference_ids: tuple[int, ...]) -> float:
    if not reference_ids:
        return 1.0
    return len(set(result_ids).intersection(reference_ids)) / len(reference_ids)


def _bucket(value: float) -> str:
    if value <= 0.05:
        return "<=0.05"
    if value <= 0.10:
        return ">0.05_to_0.10"
    if value <= 0.25:
        return ">0.10_to_0.25"
    if value <= 0.50:
        return ">0.25_to_0.50"
    return ">0.50"


def generate_queries(
    attributes: pd.DataFrame,
    query_vectors: np.ndarray,
    count: int,
    seed: int,
    low: float = 0.01,
    high: float = 1.0,
) -> list[SyntheticQuery]:
    """Generate predicates with approximately uniform requested selectivity.

    Metadata quantiles turn each target selectivity into a price threshold.
    PostgreSQL EXPLAIN remains the authoritative planning-time value recorded
    later; the target is only a workload-generation control.
    """
    if count <= 0 or not 0.0 < low <= high <= 1.0:
        raise ValueError("invalid query count or selectivity range")
    if len(query_vectors) == 0 or not {"category", "price", "stock"}.issubset(attributes.columns):
        raise ValueError("attributes and query vectors are required")
    rng = np.random.default_rng(seed)
    targets = rng.uniform(low, high, count)
    vector_ids = rng.integers(0, len(query_vectors), size=count)
    prices = np.sort(attributes["price"].to_numpy(dtype=np.int64))
    categories = attributes["category"].dropna().drop_duplicates().to_numpy()
    stock_values, stock_counts = np.unique(attributes["stock"].dropna().to_numpy(dtype=bool), return_counts=True)
    stock_probabilities = stock_counts / stock_counts.sum()
    sampled_categories = rng.choice(categories, size=count)
    sampled_stock = rng.choice(stock_values, size=count, p=stock_probabilities)
    queries: list[SyntheticQuery] = []
    for query_id, (target, vector_id, category, in_stock) in enumerate(
        zip(targets, vector_ids, sampled_categories, sampled_stock, strict=True)
    ):
        # Select the smallest threshold whose empirical price CDF reaches target.
        position = min(len(prices) - 1, max(0, math.ceil(target * len(prices)) - 1))
        threshold = int(prices[position]) + 1
        queries.append(SyntheticQuery(
            query_id=query_id,
            target_selectivity=float(target),
            price_threshold=threshold,
            category=str(category),
            in_stock=bool(in_stock),
            predicate=(
                f"category == {str(category)!r} and price < {threshold} "
                f"and stock == {bool(in_stock)!r}"
            ),
            vector_id=int(vector_id),
        ))
    return queries


def split_queries(queries: list[SyntheticQuery], calibration_fraction: float, seed: int) -> list[QuerySplit]:
    """Return a seeded, disjoint calibration/held-out assignment."""
    if not 0.0 < calibration_fraction < 1.0:
        raise ValueError("calibration_fraction must be strictly between 0 and 1")
    rng = np.random.default_rng(seed)
    order = rng.permutation(len(queries))
    calibration_count = int(round(len(queries) * calibration_fraction))
    calibration_ids = set(int(value) for value in order[:calibration_count])
    return [QuerySplit(query.query_id, "calibration" if query.query_id in calibration_ids else "held_out") for query in queries]


class HeldOutHarness:
    """Execute fixed PostgreSQL strategies without calibration/test leakage."""

    def __init__(self, connection, query_vectors: np.ndarray, top_k: int, safety_factor: float,
                 hnsw_ef_search: int = 100, ivfflat_probes: int = 10) -> None:
        if top_k <= 0 or safety_factor <= 0:
            raise ValueError("top_k and safety_factor must be positive")
        if hnsw_ef_search <= 0 or ivfflat_probes <= 0:
            raise ValueError("ANN parameters must be positive")
        self.connection = connection
        self.query_vectors = query_vectors
        self.top_k = top_k
        self.safety_factor = safety_factor
        self.hnsw_ef_search = hnsw_ef_search
        self.ivfflat_probes = ivfflat_probes
        self.versions: tuple[str | None, str | None] | None = None

    @staticmethod
    def _set_local(cursor, settings: dict[str, Any]) -> None:
        for setting, value in settings.items():
            cursor.execute("SELECT set_config(%s, %s, true)", (setting, str(value)))

    @staticmethod
    def _index_names(plan: Any) -> set[str]:
        if isinstance(plan, dict):
            names = {str(plan["Index Name"])} if "Index Name" in plan else set()
            for value in plan.values():
                names.update(HeldOutHarness._index_names(value))
            return names
        if isinstance(plan, list):
            return set().union(*(HeldOutHarness._index_names(value) for value in plan)) if plan else set()
        return set()

    @staticmethod
    def _node_types(plan: Any) -> tuple[str, ...]:
        if isinstance(plan, dict):
            current = (str(plan["Node Type"]),) if "Node Type" in plan else ()
            return current + tuple(
                node for value in plan.values() for node in HeldOutHarness._node_types(value)
            )
        if isinstance(plan, list):
            return tuple(node for value in plan for node in HeldOutHarness._node_types(value))
        return ()

    def _versions(self) -> tuple[str | None, str | None]:
        if self.versions is None:
            with self.connection.cursor() as cursor:
                cursor.execute("SHOW server_version")
                postgres_version = str(cursor.fetchone()[0])
                cursor.execute("SELECT extversion FROM pg_extension WHERE extname = 'vector'")
                row = cursor.fetchone()
            self.versions = (postgres_version, None if row is None else str(row[0]))
        return self.versions

    def estimate_selectivity(self, query: SyntheticQuery) -> float:
        """Obtain planning-time selectivity from EXPLAIN, without scanning rows."""
        with self.connection.transaction():
            with self.connection.cursor() as cursor:
                cursor.execute(
                    f"EXPLAIN (FORMAT JSON) SELECT id FROM {TABLE_NAME} "
                    "WHERE category = %s AND price < %s AND stock = %s",
                    (query.category, query.price_threshold, query.in_stock),
                )
                plan = cursor.fetchone()[0]
        if isinstance(plan, str):
            plan = json.loads(plan)
        try:
            estimated_rows = int(plan[0]["Plan"]["Plan Rows"])
        except (IndexError, KeyError, TypeError, ValueError) as exc:
            raise RuntimeError("EXPLAIN did not contain top-level Plan Rows") from exc
        return min(1.0, max(0.0, estimated_rows / 1_000_000))

    def candidate_budget(self, estimated_selectivity: float) -> int:
        if estimated_selectivity <= 0:
            return 1_000_000
        return max(
            100,
            int(math.ceil(self.top_k / estimated_selectivity * self.safety_factor)),
        )

    def _sql(self, query: SyntheticQuery, strategy: str, candidate_budget: int) -> tuple[str, tuple[Any, ...], dict[str, Any], str | None]:
        vector = _vector_literal(self.query_vectors[query.vector_id])
        predicate = (query.category, query.price_threshold, query.in_stock)
        if strategy == "SQL_FIRST":
            return (
            f"SELECT id FROM {TABLE_NAME} WHERE category = %s AND price < %s AND stock = %s "
                "ORDER BY embedding <-> %s::vector, id LIMIT %s",
                predicate + (vector, self.top_k),
                {"enable_indexscan": "off"},
                None,
            )
        if strategy == "VECTOR_FIRST_HNSW":
            return (
                f"WITH candidates AS MATERIALIZED (SELECT id, embedding <-> %s::vector AS distance "
                f"FROM {TABLE_NAME} ORDER BY embedding <-> %s::vector LIMIT %s) "
                f"SELECT candidates.id FROM candidates JOIN {TABLE_NAME} AS item ON item.id = candidates.id "
                "WHERE item.category = %s AND item.price < %s AND item.stock = %s "
                "ORDER BY candidates.distance, candidates.id LIMIT %s",
                (vector, vector, candidate_budget) + predicate + (self.top_k,),
                {"hnsw.ef_search": self.hnsw_ef_search, "ivfflat.probes": 1000, "hnsw.iterative_scan": "strict_order", "hnsw.max_scan_tuples": 20_000},
                HNSW_INDEX_NAME,
            )
        if strategy == "HNSW_HYBRID":
            return (
                f"SELECT id FROM {TABLE_NAME} WHERE category = %s AND price < %s AND stock = %s "
                "ORDER BY embedding <-> %s::vector LIMIT %s",
                predicate + (vector, self.top_k),
                {"hnsw.ef_search": self.hnsw_ef_search, "ivfflat.probes": 1000, "hnsw.iterative_scan": "strict_order", "hnsw.max_scan_tuples": 20_000},
                HNSW_INDEX_NAME,
            )
        if strategy == "IVFFLAT_HYBRID":
            return (
                f"SELECT id FROM {TABLE_NAME} WHERE category = %s AND price < %s AND stock = %s "
                "ORDER BY embedding <-> %s::vector LIMIT %s",
                predicate + (vector, self.top_k),
                {"ivfflat.probes": self.ivfflat_probes, "hnsw.ef_search": 1000, "ivfflat.iterative_scan": "off"},
                IVFFLAT_INDEX_NAME,
            )
        raise ValueError(f"Unknown strategy: {strategy}")

    def verify_plan(self, query: SyntheticQuery, strategy: str, candidate_budget: int) -> tuple[bool, tuple[str, ...]]:
        verified, names, _, _ = self.verify_plan_detailed(query, strategy, candidate_budget)
        return verified, names

    def verify_plan_detailed(
        self, query: SyntheticQuery, strategy: str, candidate_budget: int,
    ) -> tuple[bool, tuple[str, ...], tuple[str, ...], str | None]:
        sql, params, settings, expected_index = self._sql(query, strategy, candidate_budget)
        with self.connection.transaction():
            with self.connection.cursor() as cursor:
                self._set_local(cursor, settings)
                cursor.execute(f"EXPLAIN (FORMAT JSON) {sql}", params)
                raw_plan = cursor.fetchone()[0]
        plan = json.loads(raw_plan) if isinstance(raw_plan, str) else raw_plan
        names = tuple(sorted(self._index_names(plan)))
        node_types = self._node_types(plan)
        if expected_index is None:
            verified = not ({HNSW_INDEX_NAME, IVFFLAT_INDEX_NAME} & set(names))
            return verified, names, node_types, expected_index
        ann_names = {HNSW_INDEX_NAME, IVFFLAT_INDEX_NAME}
        verified = expected_index in names and not ((ann_names - {expected_index}) & set(names))
        return verified, names, node_types, expected_index

    def run_once(
        self,
        query: SyntheticQuery,
        split: str,
        strategy: str,
        repetition: int,
        estimated_selectivity: float,
        reference_ids: tuple[int, ...] | None = None,
        warnings: list[PlanVerificationFailure] | None = None,
    ) -> RunRecord | None:
        budget = self.candidate_budget(estimated_selectivity)
        verified, index_names, node_types, expected_index = self.verify_plan_detailed(query, strategy, budget)
        if not verified:
            if warnings is None:
                raise RuntimeError(f"plan verification failed for {strategy}: {index_names}")
            warnings.append(PlanVerificationFailure(
                query_id=query.query_id, strategy=strategy, split=split, repetition=repetition,
                predicate=query.predicate, estimated_selectivity=estimated_selectivity,
                candidate_budget=budget, expected_index=expected_index,
                actual_index_names=index_names, node_types=node_types,
                used_hnsw=HNSW_INDEX_NAME in index_names,
                used_seq_scan="Seq Scan" in node_types,
                error=f"plan verification failed: actual indexes={index_names}",
            ))
            return None
        sql, params, settings, _ = self._sql(query, strategy, budget)
        with self.connection.transaction():
            with self.connection.cursor() as cursor:
                self._set_local(cursor, settings)
                started = time.perf_counter_ns()
                cursor.execute(sql, params)
                result_ids = tuple(int(row[0]) for row in cursor.fetchall())
                latency_ms = (time.perf_counter_ns() - started) / 1_000_000
        if reference_ids is None:
            reference_ids = result_ids
        postgres_version, pgvector_version = self._versions()
        return RunRecord(
            query_id=query.query_id,
            split=split,
            strategy=strategy,
            repetition=repetition,
            target_selectivity=query.target_selectivity,
            estimated_selectivity=estimated_selectivity,
            price_threshold=query.price_threshold,
            vector_id=query.vector_id,
            candidate_budget=budget,
            latency_ms=latency_ms,
            result_ids=result_ids,
            reference_ids=reference_ids,
            recall=_recall(result_ids, reference_ids),
            plan_verified=verified,
            actual_index_names=index_names,
            postgres_version=postgres_version,
            pgvector_version=pgvector_version,
        )


def calibration_map(records: list[RunRecord]) -> pd.DataFrame:
    """Build latency/recall evidence using calibration rows only."""
    frame = pd.DataFrame(asdict(record) for record in records)
    frame["bucket"] = frame["estimated_selectivity"].map(_bucket)
    return frame.groupby(["strategy", "bucket"], as_index=False, observed=True).agg(
        observations=("latency_ms", "count"),
        median_latency_ms=("latency_ms", "median"),
        minimum_recall=("recall", "min"),
        mean_recall=("recall", "mean"),
    )


def _bootstrap_ci(values: np.ndarray, rng: np.random.Generator, samples: int) -> tuple[float, float]:
    if len(values) == 0:
        return float("nan"), float("nan")
    draws = rng.choice(values, size=(samples, len(values)), replace=True).mean(axis=1)
    return float(np.percentile(draws, 2.5)), float(np.percentile(draws, 97.5))


def summarize_held_out(records: list[RunRecord], seed: int, bootstrap_samples: int,
                       strategies: tuple[str, ...] = STRATEGIES) -> pd.DataFrame:
    """Summarize median-per-query held-out results with bootstrap CIs."""
    frame = pd.DataFrame(asdict(record) for record in records)
    if frame.empty:
        frame = pd.DataFrame(columns=["strategy", "query_id", "latency_ms", "recall"])
    per_query = frame.groupby(["strategy", "query_id"], as_index=False, observed=True).agg(
        latency_ms=("latency_ms", "median"), recall=("recall", "mean"),
    )
    rng = np.random.default_rng(seed)
    rows: list[dict[str, Any]] = []
    for strategy in strategies:
        group = per_query[per_query["strategy"] == strategy]
        latencies = group["latency_ms"].to_numpy(dtype=float)
        recalls = group["recall"].to_numpy(dtype=float)
        if len(group) == 0:
            rows.append({
                "strategy": strategy,
                "queries": 0,
                "mean_latency_ms": float("nan"),
                "median_latency_ms": float("nan"),
                "p95_latency_ms": float("nan"),
                "latency_ci95_low_ms": float("nan"),
                "latency_ci95_high_ms": float("nan"),
                "mean_recall_at_10": float("nan"),
                "median_recall_at_10": float("nan"),
                "minimum_recall_at_10": float("nan"),
                "fraction_recall_at_least_095": float("nan"),
                "recall_ci95_low": float("nan"),
                "recall_ci95_high": float("nan"),
            })
            continue
        latency_low, latency_high = _bootstrap_ci(latencies, rng, bootstrap_samples)
        recall_low, recall_high = _bootstrap_ci(recalls, rng, bootstrap_samples)
        rows.append({
            "strategy": strategy,
            "queries": len(group),
            "mean_latency_ms": float(np.mean(latencies)),
            "median_latency_ms": float(np.median(latencies)),
            "p95_latency_ms": _percentile(latencies, 0.95),
            "latency_ci95_low_ms": latency_low,
            "latency_ci95_high_ms": latency_high,
            "mean_recall_at_10": float(np.mean(recalls)),
            "median_recall_at_10": float(np.median(recalls)),
            "minimum_recall_at_10": float(np.min(recalls)),
            "fraction_recall_at_least_095": float(np.mean(recalls >= TARGET_RECALL)),
            "recall_ci95_low": recall_low,
            "recall_ci95_high": recall_high,
        })
    return pd.DataFrame(rows)


def summarize_adaptive(records: list[RunRecord], seed: int, bootstrap_samples: int) -> pd.DataFrame:
    """Summarize one selected adaptive execution per query and repetition."""
    frame = pd.DataFrame(asdict(record) for record in records)
    if frame.empty:
        frame = pd.DataFrame(columns=["query_id", "latency_ms", "recall"])
    per_query = frame.groupby("query_id", as_index=False, observed=True).agg(
        latency_ms=("latency_ms", "median"), recall=("recall", "mean"),
    )
    latencies = per_query["latency_ms"].to_numpy(dtype=float)
    recalls = per_query["recall"].to_numpy(dtype=float)
    if len(per_query) == 0:
        return pd.DataFrame([{
            "strategy": "ADAPTIVE", "queries": 0,
            "mean_latency_ms": float("nan"), "median_latency_ms": float("nan"),
            "p95_latency_ms": float("nan"), "latency_ci95_low_ms": float("nan"),
            "latency_ci95_high_ms": float("nan"), "mean_recall_at_10": float("nan"),
            "median_recall_at_10": float("nan"), "minimum_recall_at_10": float("nan"),
            "fraction_recall_at_least_095": float("nan"), "recall_ci95_low": float("nan"),
            "recall_ci95_high": float("nan"),
        }])
    rng = np.random.default_rng(seed)
    latency_low, latency_high = _bootstrap_ci(latencies, rng, bootstrap_samples)
    recall_low, recall_high = _bootstrap_ci(recalls, rng, bootstrap_samples)
    return pd.DataFrame([{
        "strategy": "ADAPTIVE",
        "queries": len(per_query),
        "mean_latency_ms": float(np.mean(latencies)),
        "median_latency_ms": float(np.median(latencies)),
        "p95_latency_ms": _percentile(latencies, 0.95),
        "latency_ci95_low_ms": latency_low,
        "latency_ci95_high_ms": latency_high,
        "mean_recall_at_10": float(np.mean(recalls)),
        "median_recall_at_10": float(np.median(recalls)),
        "minimum_recall_at_10": float(np.min(recalls)),
        "fraction_recall_at_least_095": float(np.mean(recalls >= TARGET_RECALL)),
        "recall_ci95_low": recall_low,
        "recall_ci95_high": recall_high,
    }])


def select_adaptive_strategy(calibration: pd.DataFrame, estimated_selectivity: float,
                             target_recall: float = TARGET_RECALL) -> str:
    """Replay the conservative planner using only calibration-map evidence."""
    bucket = _bucket(estimated_selectivity)
    candidates = calibration[
        (calibration["bucket"] == bucket)
        & ((calibration["strategy"] == "SQL_FIRST") | (calibration["minimum_recall"] >= target_recall))
    ]
    if candidates.empty:
        raise RuntimeError(f"no feasible strategy in bucket {bucket}")
    selected = candidates.sort_values(["median_latency_ms", "strategy"], kind="stable").iloc[0]
    return str(selected["strategy"])


def _adaptive_records_for_query(query: SyntheticQuery, harness: HeldOutHarness,
                               repetitions: int, estimate: float,
                               calibration: pd.DataFrame,
                               references: dict[int, tuple[int, ...]],
                               warnings: list[PlanVerificationFailure]) -> list[RunRecord]:
    strategy = select_adaptive_strategy(calibration, estimate)
    records = []
    for repetition in range(repetitions):
        reference = references.get(repetition)
        record = harness.run_once(query, "held_out", strategy, repetition, estimate, reference, warnings)
        if record is not None:
            records.append(record)
    return records


def bucket_confidence(queries: list[SyntheticQuery], estimates: dict[int, float]) -> pd.DataFrame:
    """Flag held-out buckets with fewer than ten queries in this run."""
    frame = pd.DataFrame({
        "query_id": [query.query_id for query in queries],
        "estimated_selectivity": [estimates[query.query_id] for query in queries],
    })
    frame["bucket"] = frame["estimated_selectivity"].map(_bucket)
    counts = frame.groupby("bucket", observed=True).size().reindex(
        ("<=0.05", ">0.05_to_0.10", ">0.10_to_0.25", ">0.25_to_0.50", ">0.50"), fill_value=0
    )
    return pd.DataFrame({
        "bucket": counts.index,
        "held_out_queries": counts.to_numpy(dtype=int),
        "low_confidence": counts.to_numpy(dtype=int) < LOW_CONFIDENCE_BUCKET_THRESHOLD,
        "low_confidence_threshold": LOW_CONFIDENCE_BUCKET_THRESHOLD,
    })


def summarize_repeated_runs(run_summaries: list[pd.DataFrame], bootstrap_samples: int,
                            seed: int) -> pd.DataFrame:
    """Summarize run-level means with bootstrap 95% CIs across independent runs."""
    combined = pd.concat(
        [summary.assign(run_index=index + 1) for index, summary in enumerate(run_summaries)],
        ignore_index=True,
    )
    rng = np.random.default_rng(seed)
    rows: list[dict[str, Any]] = []
    for strategy in ("ADAPTIVE", *STRATEGIES):
        group = combined[combined["strategy"] == strategy]
        if group.empty:
            continue
        latency_means = group["mean_latency_ms"].to_numpy(dtype=float)
        recall_means = group["mean_recall_at_10"].to_numpy(dtype=float)
        latency_low, latency_high = _bootstrap_ci(latency_means, rng, bootstrap_samples)
        recall_low, recall_high = _bootstrap_ci(recall_means, rng, bootstrap_samples)
        rows.append({
            "strategy": strategy,
            "runs": len(group),
            "mean_of_run_mean_latency_ms": float(np.mean(latency_means)),
            "latency_ci95_low_ms": latency_low,
            "latency_ci95_high_ms": latency_high,
            "mean_of_run_mean_recall_at_10": float(np.mean(recall_means)),
            "recall_ci95_low": recall_low,
            "recall_ci95_high": recall_high,
        })
    return pd.DataFrame(rows)


def _records_for_query(query: SyntheticQuery, split: str, harness: HeldOutHarness, repetitions: int,
                       estimate: float, warnings: list[PlanVerificationFailure]) -> list[RunRecord]:
    records: list[RunRecord] = []
    reference: tuple[int, ...] | None = None
    for repetition in range(repetitions):
        exact = harness.run_once(query, split, "SQL_FIRST", repetition, estimate, reference, warnings)
        if exact is not None and reference is None:
            reference = exact.result_ids
        if exact is not None:
            records.append(exact)
        for strategy in STRATEGIES[1:]:
            record = harness.run_once(query, split, strategy, repetition, estimate, reference, warnings)
            if record is not None:
                records.append(record)
    return records


def summarize_plan_failures(failures: list[PlanVerificationFailure]) -> pd.DataFrame:
    """Summarize verification failures by selectivity bucket and strategy."""
    if not failures:
        return pd.DataFrame(columns=["dimension", "value", "failures"])
    frame = pd.DataFrame(asdict(failure) for failure in failures)
    rows = []
    for strategy, count in frame["strategy"].value_counts().items():
        rows.append({"dimension": "strategy", "value": strategy, "failures": int(count)})
    frame["selectivity_bucket"] = frame["estimated_selectivity"].map(_bucket)
    for bucket, count in frame["selectivity_bucket"].value_counts().items():
        rows.append({"dimension": "selectivity_bucket", "value": bucket, "failures": int(count)})
    return pd.DataFrame(rows)


def run(args: argparse.Namespace) -> None:
    output = args.output
    if output.exists() and any(output.iterdir()):
        raise FileExistsError(f"output directory is not empty: {output}")
    output.mkdir(parents=True, exist_ok=True)
    attributes = pd.read_csv(ATTRIBUTE_FILE)
    query_vectors = read_fvecs(QUERY_FILE)
    run_summaries: list[pd.DataFrame] = []
    bucket_summaries: list[pd.DataFrame] = []

    for run_index in range(args.runs):
        run_seed = args.seed + run_index
        run_output = output / f"run_{run_index + 1:02d}"
        run_output.mkdir()
        queries = generate_queries(attributes, query_vectors, args.query_count, run_seed)
        splits = split_queries(queries, args.calibration_fraction, run_seed + 1)
        split_by_id = {item.query_id: item.split for item in splits}
        calibration_queries = [query for query in queries if split_by_id[query.query_id] == "calibration"]
        held_out_queries = [query for query in queries if split_by_id[query.query_id] == "held_out"]
        if set(query.query_id for query in calibration_queries) & set(query.query_id for query in held_out_queries):
            raise RuntimeError("calibration and held-out query IDs overlap")

        connection = psycopg.connect(**DatabaseConfig.from_env().connect_kwargs())
        harness = HeldOutHarness(
            connection,
            query_vectors,
            args.top_k,
            args.safety_factor,
            args.hnsw_ef_search,
            args.ivfflat_probes,
        )
        calibration_records: list[RunRecord] = []
        held_out_records: list[RunRecord] = []
        adaptive_records: list[RunRecord] = []
        plan_failures: list[PlanVerificationFailure] = []
        estimates: dict[int, float] = {}
        try:
            for query in calibration_queries:
                estimate = harness.estimate_selectivity(query)
                estimates[query.query_id] = estimate
                calibration_records.extend(_records_for_query(
                    query, "calibration", harness, args.calibration_repetitions, estimate, plan_failures,
                ))
            calibration = calibration_map(calibration_records)
            for query in held_out_queries:
                estimate = harness.estimate_selectivity(query)
                estimates[query.query_id] = estimate
                fixed_records = _records_for_query(
                    query, "held_out", harness, args.repetitions, estimate, plan_failures,
                )
                held_out_records.extend(fixed_records)
                references = {
                    record.repetition: record.result_ids
                    for record in fixed_records
                    if record.strategy == "SQL_FIRST"
                }
                adaptive_records.extend(_adaptive_records_for_query(
                    query, harness, args.repetitions, estimate, calibration, references, plan_failures,
                ))
        finally:
            connection.close()

        fixed_summary = summarize_held_out(held_out_records, run_seed + 2, args.bootstrap_samples)
        adaptive_summary = summarize_adaptive(adaptive_records, run_seed + 3, args.bootstrap_samples)
        summary = pd.concat([adaptive_summary, fixed_summary], ignore_index=True)
        run_summaries.append(summary)
        bucket_summary = bucket_confidence(held_out_queries, estimates).assign(run_index=run_index + 1, seed=run_seed)
        bucket_summaries.append(bucket_summary)

        query_frame = pd.DataFrame(asdict(query) | {"split": split_by_id[query.query_id]} for query in queries)
        query_frame.to_csv(run_output / "synthetic_queries.csv", index=False)
        pd.DataFrame(asdict(record) for record in calibration_records).to_csv(run_output / "calibration_records.csv", index=False)
        pd.DataFrame(asdict(record) for record in held_out_records).to_csv(run_output / "held_out_records.csv", index=False)
        pd.DataFrame(asdict(record) for record in adaptive_records).to_csv(run_output / "adaptive_records.csv", index=False)
        calibration.to_csv(run_output / "calibration_map.csv", index=False)
        summary.to_csv(run_output / "held_out_summary.csv", index=False)
        bucket_summary.to_csv(run_output / "bucket_confidence.csv", index=False)
        pd.DataFrame(asdict(failure) for failure in plan_failures).to_csv(
            run_output / "plan_verification_warnings.csv", index=False,
        )
        summarize_plan_failures(plan_failures).to_csv(run_output / "plan_verification_warning_summary.csv", index=False)
        (run_output / "held_out_summary.tex").write_text(summary.to_latex(index=False, float_format="%.4f") + "\n")
        (run_output / "run_metadata.json").write_text(json.dumps({
            "run_index": run_index + 1,
            "seed": run_seed,
            "query_count": args.query_count,
            "calibration_queries": len(calibration_queries),
            "held_out_queries": len(held_out_queries),
            "calibration_fraction": args.calibration_fraction,
            "calibration_repetitions": args.calibration_repetitions,
            "held_out_repetitions": args.repetitions,
            "confidence_interval": "bootstrap 95% CI over per-query held-out medians within run",
            "low_confidence_bucket_threshold": LOW_CONFIDENCE_BUCKET_THRESHOLD,
            "hnsw_ef_search": args.hnsw_ef_search,
            "ivfflat_probes": args.ivfflat_probes,
            "plan_verification_failures": len(plan_failures),
        }, indent=2) + "\n")

        print(f"Run {run_index + 1}: processed {len(queries)} queries; plan-verification failures={len(plan_failures)}")
        if plan_failures:
            print(pd.DataFrame(asdict(failure) for failure in plan_failures).to_string(index=False))

    repeated_summary = summarize_repeated_runs(run_summaries, args.bootstrap_samples, args.seed + args.runs + 1)
    all_bucket_summaries = pd.concat(bucket_summaries, ignore_index=True)
    repeated_summary.to_csv(output / "repeated_summary.csv", index=False)
    (output / "repeated_summary.tex").write_text(repeated_summary.to_latex(index=False, float_format="%.4f") + "\n")
    all_bucket_summaries.to_csv(output / "bucket_confidence_across_runs.csv", index=False)
    all_failures = []
    for run_index in range(args.runs):
        warning_path = output / f"run_{run_index + 1:02d}" / "plan_verification_warnings.csv"
        if warning_path.is_file() and warning_path.stat().st_size > 1:
            all_failures.append(pd.read_csv(warning_path))
    failure_frame = pd.concat(all_failures, ignore_index=True) if all_failures else pd.DataFrame()
    failure_frame.to_csv(output / "plan_verification_warnings.csv", index=False)
    failure_summary = summarize_plan_failures([
        PlanVerificationFailure(**row) for row in failure_frame.to_dict("records")
    ]) if not failure_frame.empty else pd.DataFrame(columns=["dimension", "value", "failures"])
    failure_summary.to_csv(output / "plan_verification_warning_summary.csv", index=False)
    (output / "run_metadata.json").write_text(json.dumps({
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "runs": args.runs,
        "seeds": [args.seed + index for index in range(args.runs)],
        "query_count": args.query_count,
        "held_out_queries_per_run": int(args.query_count * (1.0 - args.calibration_fraction)),
        "confidence_interval": "bootstrap 95% CI over independent run-level means",
        "low_confidence_bucket_threshold": LOW_CONFIDENCE_BUCKET_THRESHOLD,
        "hnsw_ef_search": args.hnsw_ef_search,
        "ivfflat_probes": args.ivfflat_probes,
        "strategies": ("ADAPTIVE", *STRATEGIES),
        "total_queries_processed": args.query_count * args.runs,
        "plan_verification_failures": int(len(failure_frame)),
        "plan_verification_failure_strategies": failure_summary[failure_summary["dimension"] == "strategy"].to_dict("records"),
        "plan_verification_failure_selectivity_buckets": failure_summary[failure_summary["dimension"] == "selectivity_bucket"].to_dict("records"),
    }, indent=2) + "\n")
    print(repeated_summary.to_string(index=False))
    print("\nBucket confidence by run:")
    print(all_bucket_summaries.to_string(index=False))
    print(f"Wrote repeated held-out evaluation artifacts to {output}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--query-count", type=int, default=DEFAULT_QUERY_COUNT)
    parser.add_argument("--calibration-fraction", type=float, default=DEFAULT_CALIBRATION_FRACTION)
    parser.add_argument("--calibration-repetitions", type=int, default=DEFAULT_CALIBRATION_REPETITIONS)
    parser.add_argument("--repetitions", type=int, default=DEFAULT_REPETITIONS)
    parser.add_argument("--top-k", type=int, default=DEFAULT_TOP_K)
    parser.add_argument("--safety-factor", type=float, default=DEFAULT_SAFETY_FACTOR)
    parser.add_argument("--hnsw-ef-search", type=int, default=100)
    parser.add_argument("--ivfflat-probes", type=int, default=10)
    parser.add_argument("--seed", type=int, default=20260820)
    parser.add_argument("--bootstrap-samples", type=int, default=DEFAULT_BOOTSTRAPS)
    parser.add_argument("--runs", type=int, default=DEFAULT_RUNS,
                        help="Independent calibration/held-out split runs (default: 5).")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    if (args.runs < 2 or args.repetitions < 1 or args.calibration_repetitions < 1
            or args.bootstrap_samples < 100 or args.hnsw_ef_search < 1 or args.ivfflat_probes < 1):
        raise SystemExit("runs must be at least 2, repetitions must be positive, and bootstrap-samples must be at least 100")
    run(args)


if __name__ == "__main__":
    main()
