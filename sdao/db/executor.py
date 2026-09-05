"""Database-backed execution adapter for future SDAO planning integration."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

import numpy as np

from .benchmark import DatabaseBenchmark, QueryRequest
from .config import DatabaseConfig
from .connection import connect
from .strategy_registry import DatabaseStrategy, DatabaseStrategyDefinition, strategy_definition


@dataclass(frozen=True)
class DatabaseExecutionResult:
    query_id: int
    strategy: DatabaseStrategy
    result_ids: tuple[int, ...]
    top_k: int
    latency_ms: float | None
    estimated_selectivity: float | None
    measured_selectivity: float | None
    recall: float | None
    plan_verified: bool
    plan_verification_status: str | None
    expected_index: str | None
    actual_index_names: tuple[str, ...]
    plan_evidence: dict[str, Any] | None
    postgres_version: str | None
    pgvector_version: str | None
    strategy_parameters: dict[str, Any]
    success: bool
    error: str | None


class DBAdaptiveExecutor:
    """Execute one registered database strategy via ``DatabaseBenchmark``.

    The adapter owns no SQL and relies on the benchmark's parameterized
    predicate handling, isolated transactions, plan verification, and timing.
    """

    def __init__(self, connection=None, config: DatabaseConfig | None = None,
                 benchmark: DatabaseBenchmark | None = None, **benchmark_kwargs: Any) -> None:
        if benchmark is not None and (connection is not None or config is not None or benchmark_kwargs):
            raise ValueError("benchmark cannot be combined with connection, config, or benchmark settings")
        self._owns_connection = benchmark is None and connection is None
        self.connection = connection if benchmark is None else getattr(benchmark, "connection", None)
        if benchmark is None:
            self.connection = self.connection or connect(config)
            self.benchmark = DatabaseBenchmark(self.connection, **benchmark_kwargs)
        else:
            self.benchmark = benchmark

    def close(self) -> None:
        if self._owns_connection and self.connection is not None:
            self.connection.close()
            self._owns_connection = False

    @staticmethod
    def _recall(result_ids: tuple[int, ...], reference_ids: tuple[int, ...] | None) -> float | None:
        if reference_ids is None:
            return None
        return len(set(result_ids).intersection(reference_ids)) / len(reference_ids) if reference_ids else 1.0

    @staticmethod
    def _normalize_strategy(strategy: DatabaseStrategy | str) -> DatabaseStrategy:
        return strategy if isinstance(strategy, DatabaseStrategy) else DatabaseStrategy(strategy)

    def _failure(self, query_id: int, definition: DatabaseStrategyDefinition, top_k: int,
                 estimated_selectivity: float | None, parameters: Mapping[str, Any], error: Exception) -> DatabaseExecutionResult:
        return DatabaseExecutionResult(
            query_id=query_id, strategy=definition.strategy, result_ids=(), top_k=top_k,
            latency_ms=None, estimated_selectivity=estimated_selectivity, measured_selectivity=None,
            recall=None, plan_verified=False, plan_verification_status=None,
            expected_index=definition.required_index, actual_index_names=(),
            plan_evidence=None,
            postgres_version=None, pgvector_version=None, strategy_parameters=dict(parameters),
            success=False, error=f"{type(error).__name__}: {error}",
        )

    def execute(self, *, query_id: int, predicate: str, query_vector: np.ndarray,
                top_k: int, strategy: DatabaseStrategy | str,
                strategy_parameters: Mapping[str, Any] | None = None,
                estimated_selectivity: float | None = None,
                reference_ids: tuple[int, ...] | list[int] | None = None) -> DatabaseExecutionResult:
        selected = self._normalize_strategy(strategy)
        definition = strategy_definition(selected)
        parameters = dict(strategy_parameters or {})
        reference = tuple(int(value) for value in reference_ids) if reference_ids is not None else None
        try:
            request = QueryRequest(query_id, predicate, query_vector, top_k)
            if selected is DatabaseStrategy.SQL_FIRST:
                if parameters:
                    raise ValueError("SQL_FIRST does not accept ANN strategy parameters")
                raw = self.benchmark.sql_first_exact(request, verify_plan=True)
            elif selected is DatabaseStrategy.VECTOR_FIRST_HNSW:
                candidate_budget = parameters.pop("candidate_budget", None)
                if parameters:
                    raise ValueError("Unsupported VECTOR_FIRST_HNSW strategy parameters")
                if candidate_budget is None:
                    raise ValueError("VECTOR_FIRST_HNSW requires candidate_budget")
                raw = self.benchmark.vector_first_post_filter(request, candidate_budget=int(candidate_budget), verify_plan=True)
            elif selected is DatabaseStrategy.HNSW_HYBRID:
                if parameters:
                    raise ValueError("HNSW_HYBRID parameters are configured when the benchmark is constructed")
                raw = self.benchmark.hnsw_hybrid(request, verify_plan=True)
            else:
                if parameters:
                    raise ValueError("IVFFLAT_HYBRID parameters are configured when the benchmark is constructed")
                raw = self.benchmark.ivfflat_hybrid(request, verify_plan=True)

            plan = raw.get("plan_evidence") or {}
            plan_status = raw.get("plan_verification_status")
            if definition.requires_ann_plan_verification and plan_status != "verified":
                raise RuntimeError(f"Expected ANN index was not verified ({plan_status})")
            result_ids = tuple(int(value) for value in raw["result_ids"])
            effective_parameters = dict(raw.get("database_index_configuration") or {})
            if selected is DatabaseStrategy.VECTOR_FIRST_HNSW:
                effective_parameters["candidate_budget"] = int(strategy_parameters["candidate_budget"])  # type: ignore[index]
            return DatabaseExecutionResult(
                query_id=query_id, strategy=selected, result_ids=result_ids, top_k=top_k,
                latency_ms=float(raw["strategy_latency_ms"]), estimated_selectivity=estimated_selectivity,
                measured_selectivity=float(raw["selectivity"]), recall=self._recall(result_ids, reference),
                plan_verified=plan_status == "verified", plan_verification_status=plan_status,
                expected_index=definition.required_index,
                actual_index_names=tuple(str(value) for value in plan.get("plan_index_names", ())),
                plan_evidence=plan or None,
                postgres_version=raw.get("postgres_version"), pgvector_version=raw.get("pgvector_version"),
                strategy_parameters=effective_parameters, success=True, error=None,
            )
        except Exception as exc:
            return self._failure(query_id, definition, top_k, estimated_selectivity, strategy_parameters or {}, exc)
