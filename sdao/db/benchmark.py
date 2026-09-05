"""Executable PostgreSQL/pgvector baselines, isolated from the hnswlib prototype."""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import json
import time
from typing import Any, Iterator

import numpy as np

from .predicates import translate_predicate
from .workload import WorkloadQuery, get_workload_query
from .loader import EMBEDDING_DIMENSION, TABLE_NAME, _vector_literal

HNSW_INDEX_NAME = "sift1m_items_embedding_hnsw_l2_idx"
IVFFLAT_INDEX_NAME = "sift1m_items_embedding_ivfflat_l2_idx"


def _validate_top_k(top_k: int) -> int:
    if isinstance(top_k, bool) or not isinstance(top_k, int) or top_k <= 0:
        raise ValueError("top_k must be a positive integer")
    return top_k


@dataclass(frozen=True)
class QueryRequest:
    query_id: int
    predicate: str
    query_vector: np.ndarray
    top_k: int

    def __post_init__(self) -> None:
        _validate_top_k(self.top_k)
        vector = np.asarray(self.query_vector)
        if vector.shape != (EMBEDDING_DIMENSION,) or not np.isfinite(vector).all():
            raise ValueError(f"query_vector must be a finite {EMBEDDING_DIMENSION}-dimensional vector")
        translate_predicate(self.predicate)


@dataclass(frozen=True)
class _QuerySpec:
    sql: str
    params: tuple[Any, ...]
    strategy: str
    index_name: str | None
    configuration: dict[str, Any]


class DatabaseBenchmark:
    """Run database strategies with isolated transactions and optional plan checks.

    ANN ordering intentionally contains only ``embedding <-> query``. pgvector
    can use an ANN index for that ordering, but equal-distance ANN ties are not
    deterministic. Exact filtered reference ordering adds ``id`` as a stable
    tie-breaker and disables vector index scans for perfect-recall execution.
    """
    def __init__(self, connection, dataset_size: int = 1_000_000, hnsw_ef_search: int = 100,
                 ivfflat_probes: int = 10, hnsw_iterative_scan: str | None = "strict_order",
                 hnsw_max_scan_tuples: int | None = 20_000, hnsw_scan_mem_multiplier: float | None = None,
                 ivfflat_iterative_scan: str | None = "off", ivfflat_max_probes: int | None = None) -> None:
        if dataset_size <= 0 or hnsw_ef_search <= 0 or ivfflat_probes <= 0:
            raise ValueError("dataset_size and ANN settings must be positive")
        if ivfflat_iterative_scan not in (None, "off", "relaxed_order"):
            raise ValueError("ivfflat_iterative_scan must be None, 'off', or 'relaxed_order' for pgvector 0.8.5")
        self.connection, self.dataset_size = connection, dataset_size
        self.hnsw_ef_search, self.ivfflat_probes = hnsw_ef_search, ivfflat_probes
        self.hnsw_iterative_scan, self.hnsw_max_scan_tuples = hnsw_iterative_scan, hnsw_max_scan_tuples
        self.hnsw_scan_mem_multiplier = hnsw_scan_mem_multiplier
        self.ivfflat_iterative_scan, self.ivfflat_max_probes = ivfflat_iterative_scan, ivfflat_max_probes
        self._database_metadata: dict[str, str | None] | None = None

    @contextmanager
    def _transaction(self) -> Iterator[None]:
        """Commit/rollback each logical operation so SET LOCAL never leaks."""
        try:
            with self.connection.transaction():
                yield
        except Exception:
            raise

    def request_from_workload(self, query_id: int, top_k: int = 10, workload: WorkloadQuery | None = None) -> QueryRequest:
        item = workload or get_workload_query(query_id)
        return QueryRequest(item.query_id, item.predicate, item.vector, _validate_top_k(top_k))

    def _database_versions(self) -> dict[str, str | None]:
        if self._database_metadata is None:
            with self._transaction():
                with self.connection.cursor() as cursor:
                    cursor.execute("SHOW server_version")
                    postgres_version = str(cursor.fetchone()[0])
                    cursor.execute("SELECT extversion FROM pg_extension WHERE extname = 'vector'")
                    row = cursor.fetchone()
            self._database_metadata = {"postgres_version": postgres_version, "pgvector_version": str(row[0]) if row else None}
        return self._database_metadata.copy()

    def _selectivity(self, predicate_sql: str, params: tuple[Any, ...]) -> float:
        with self._transaction():
            with self.connection.cursor() as cursor:
                cursor.execute(f"SELECT count(*) FROM {TABLE_NAME} WHERE {predicate_sql}", params)
                return int(cursor.fetchone()[0]) / self.dataset_size

    @staticmethod
    def _set_local(cursor, settings: dict[str, Any]) -> None:
        for setting, value in settings.items():
            cursor.execute("SELECT set_config(%s, %s, true)", (setting, str(value)))

    def _spec(self, request: QueryRequest, strategy: str, candidate_budget: int | None = None) -> _QuerySpec:
        predicate = translate_predicate(request.predicate)
        vector = _vector_literal(np.asarray(request.query_vector))
        if strategy == "sql_first_exact":
            return _QuerySpec(
                f"SELECT id FROM {TABLE_NAME} WHERE {predicate.sql} ORDER BY embedding <-> %s::vector, id LIMIT %s",
                predicate.params + (vector, request.top_k), "PGVECTOR_SQL_FIRST_EXACT", None,
                {"index": "exact-l2-sequential", "index_name": None, "session_settings": {"enable_indexscan": "off"}},
            )
        if strategy == "vector_first_post_filter":
            if candidate_budget is None or candidate_budget < request.top_k:
                raise ValueError("candidate_budget must be at least top_k")
            return _QuerySpec(
                f"WITH candidates AS MATERIALIZED (SELECT id, embedding <-> %s::vector AS distance FROM {TABLE_NAME} "
                "ORDER BY embedding <-> %s::vector LIMIT %s) "
                f"SELECT candidates.id FROM candidates JOIN {TABLE_NAME} AS item ON item.id = candidates.id "
                f"WHERE {predicate.sql} ORDER BY candidates.distance, candidates.id LIMIT %s",
                (vector, vector, candidate_budget) + predicate.params + (request.top_k,), "PGVECTOR_VECTOR_FIRST_HNSW_POST_FILTER", HNSW_INDEX_NAME,
                {"index": "hnsw", "index_name": HNSW_INDEX_NAME, "candidate_budget": candidate_budget, "session_settings": self._hnsw_settings()},
            )
        if strategy == "hnsw_hybrid":
            return _QuerySpec(
                f"SELECT id FROM {TABLE_NAME} WHERE {predicate.sql} ORDER BY embedding <-> %s::vector LIMIT %s",
                predicate.params + (vector, request.top_k), "PGVECTOR_HNSW_HYBRID", HNSW_INDEX_NAME,
                {"index": "hnsw", "index_name": HNSW_INDEX_NAME, "session_settings": self._hnsw_settings()},
            )
        if strategy == "ivfflat_hybrid":
            return _QuerySpec(
                f"SELECT id FROM {TABLE_NAME} WHERE {predicate.sql} ORDER BY embedding <-> %s::vector LIMIT %s",
                predicate.params + (vector, request.top_k), "PGVECTOR_IVFFLAT_HYBRID", IVFFLAT_INDEX_NAME,
                {"index": "ivfflat", "index_name": IVFFLAT_INDEX_NAME, "session_settings": self._ivfflat_settings()},
            )
        raise ValueError(f"Unsupported database strategy: {strategy}")

    def _hnsw_settings(self) -> dict[str, Any]:
        # Both ANN indexes may be installed for preparation.  Make the
        # non-target IVFFlat path prohibitively broad in this transaction so
        # EXPLAIN and the immediately following strategy query verify/use
        # HNSW without changing index definitions or server configuration.
        settings: dict[str, Any] = {"hnsw.ef_search": self.hnsw_ef_search, "ivfflat.probes": 1000}
        if self.hnsw_iterative_scan is not None:
            settings["hnsw.iterative_scan"] = self.hnsw_iterative_scan
        if self.hnsw_max_scan_tuples is not None:
            settings["hnsw.max_scan_tuples"] = self.hnsw_max_scan_tuples
        if self.hnsw_scan_mem_multiplier is not None:
            settings["hnsw.scan_mem_multiplier"] = self.hnsw_scan_mem_multiplier
        return settings

    def _ivfflat_settings(self) -> dict[str, Any]:
        # Symmetric transaction-local isolation for IVFFlat.  pgvector caps
        # hnsw.ef_search at 1000, which makes the competing HNSW path more
        # expensive while leaving the requested IVFFlat probes untouched.
        settings: dict[str, Any] = {"ivfflat.probes": self.ivfflat_probes, "hnsw.ef_search": 1000}
        if self.ivfflat_iterative_scan is not None:
            settings["ivfflat.iterative_scan"] = self.ivfflat_iterative_scan
        if self.ivfflat_max_probes is not None:
            settings["ivfflat.max_probes"] = self.ivfflat_max_probes
        return settings

    @staticmethod
    def _plan_index_names(plan: Any) -> set[str]:
        if isinstance(plan, dict):
            names = {str(plan["Index Name"])} if "Index Name" in plan else set()
            for value in plan.values():
                names.update(DatabaseBenchmark._plan_index_names(value))
            return names
        if isinstance(plan, list):
            return set().union(*(DatabaseBenchmark._plan_index_names(value) for value in plan)) if plan else set()
        return set()

    def verify_plan(self, request: QueryRequest, strategy: str, candidate_budget: int | None = None) -> dict[str, Any]:
        """Return EXPLAIN evidence separately; it is never part of query timing."""
        spec = self._spec(request, strategy, candidate_budget)
        with self._transaction():
            with self.connection.cursor() as cursor:
                self._set_local(cursor, spec.configuration["session_settings"])
                cursor.execute(f"EXPLAIN (FORMAT JSON) {spec.sql}", spec.params)
                raw_plan = cursor.fetchone()[0]
        plan = json.loads(raw_plan) if isinstance(raw_plan, str) else raw_plan
        index_names = sorted(self._plan_index_names(plan))
        if spec.index_name is None:
            ann_indexes = {HNSW_INDEX_NAME, IVFFLAT_INDEX_NAME}
            status = "verified" if not ann_indexes.intersection(index_names) else "unexpected_ann_index"
        else:
            ann_indexes = {HNSW_INDEX_NAME, IVFFLAT_INDEX_NAME}
            wrong_ann_indexes = sorted(ann_indexes.intersection(index_names) - {spec.index_name})
            if spec.index_name in index_names and not wrong_ann_indexes:
                status = "verified"
            elif wrong_ann_indexes:
                status = "wrong_ann_index"
            else:
                status = "missing_expected_ann_index"
        return {
            "plan": plan, "plan_index_names": index_names, "plan_verification_status": status,
            "expected_index_name": spec.index_name,
            "wrong_ann_index_names": [] if spec.index_name is None else wrong_ann_indexes,
        }

    def _run(self, request: QueryRequest, strategy: str, candidate_budget: int | None = None,
             verify_plan: bool = False, require_verified_plan: bool = False) -> dict[str, Any]:
        spec = self._spec(request, strategy, candidate_budget)
        plan_evidence = self.verify_plan(request, strategy, candidate_budget) if verify_plan else None
        if require_verified_plan and (plan_evidence is None or plan_evidence["plan_verification_status"] != "verified"):
            status = None if plan_evidence is None else plan_evidence["plan_verification_status"]
            raise RuntimeError(f"Refusing to run {spec.strategy}: pgvector index plan was not verified ({status})")
        predicate = translate_predicate(request.predicate)
        selectivity = self._selectivity(predicate.sql, predicate.params)
        versions = self._database_versions()
        with self._transaction():
            started = time.perf_counter_ns()
            with self.connection.cursor() as cursor:
                self._set_local(cursor, spec.configuration["session_settings"])
                cursor.execute(spec.sql, spec.params)
                ids = [int(row[0]) for row in cursor.fetchall()]
            latency_ms = (time.perf_counter_ns() - started) / 1_000_000
        return {
            "result_ids": ids, "strategy": spec.strategy, "strategy_latency_ms": latency_ms,
            "rows_retrieved": len(ids), "rows_examined": None, "dataset_size": self.dataset_size,
            "query_id": request.query_id, "selectivity": selectivity, "top_k": request.top_k,
            "database_index_configuration": spec.configuration, **versions,
            "plan_verification_status": None if plan_evidence is None else plan_evidence["plan_verification_status"],
            "plan_evidence": plan_evidence,
        }

    def sql_first_exact(self, request: QueryRequest, verify_plan: bool = False) -> dict[str, Any]:
        return self._run(request, "sql_first_exact", verify_plan=verify_plan)

    def vector_first_post_filter(self, request: QueryRequest, candidate_budget: int, verify_plan: bool = True) -> dict[str, Any]:
        return self._run(request, "vector_first_post_filter", candidate_budget, verify_plan, require_verified_plan=True)

    def hnsw_hybrid(self, request: QueryRequest, verify_plan: bool = True) -> dict[str, Any]:
        return self._run(request, "hnsw_hybrid", verify_plan=verify_plan, require_verified_plan=True)

    def ivfflat_hybrid(self, request: QueryRequest, verify_plan: bool = True) -> dict[str, Any]:
        return self._run(request, "ivfflat_hybrid", verify_plan=verify_plan, require_verified_plan=True)

    def filtered_ground_truth(self, request: QueryRequest) -> dict[str, Any]:
        """Exact filtered reference; unlike SIFT .ivecs it honours the predicate."""
        result = self.sql_first_exact(request)
        result["reference_latency_ms"] = result["strategy_latency_ms"]
        result["strategy"] = "PGVECTOR_FILTERED_EXACT_GROUND_TRUTH"
        return result

    def execute_with_reference(self, request: QueryRequest, strategy: str, **kwargs: Any) -> dict[str, Any]:
        methods = {"sql_first_exact": self.sql_first_exact, "vector_first_post_filter": self.vector_first_post_filter, "hnsw_hybrid": self.hnsw_hybrid, "ivfflat_hybrid": self.ivfflat_hybrid}
        if strategy not in methods:
            raise ValueError(f"Unsupported database strategy: {strategy}")
        result = methods[strategy](request, **kwargs)
        reference = self.filtered_ground_truth(request)
        result["reference_ids"] = reference["result_ids"]
        result["reference_latency_ms"] = reference["reference_latency_ms"]
        return result
