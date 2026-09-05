"""Explicit database strategy metadata for a future adaptive DB executor."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .benchmark import HNSW_INDEX_NAME, IVFFLAT_INDEX_NAME


class DatabaseStrategy(str, Enum):
    SQL_FIRST = "SQL_FIRST"
    VECTOR_FIRST_HNSW = "VECTOR_FIRST_HNSW"
    HNSW_HYBRID = "HNSW_HYBRID"
    IVFFLAT_HYBRID = "IVFFLAT_HYBRID"


@dataclass(frozen=True)
class DatabaseStrategyDefinition:
    strategy: DatabaseStrategy
    execution_method: str
    baseline_strategy: str
    required_index: str | None
    ann_parameters: tuple[str, ...]
    exact: bool
    recall_must_be_checked: bool
    requires_ann_plan_verification: bool


STRATEGY_REGISTRY: dict[DatabaseStrategy, DatabaseStrategyDefinition] = {
    DatabaseStrategy.SQL_FIRST: DatabaseStrategyDefinition(
        DatabaseStrategy.SQL_FIRST, "sql_first_exact", "PGVECTOR_SQL_FIRST_EXACT", None, (), True, False, False,
    ),
    DatabaseStrategy.VECTOR_FIRST_HNSW: DatabaseStrategyDefinition(
        DatabaseStrategy.VECTOR_FIRST_HNSW, "vector_first_post_filter", "PGVECTOR_VECTOR_FIRST_HNSW_POST_FILTER",
        HNSW_INDEX_NAME, ("candidate_budget", "hnsw.ef_search", "hnsw.iterative_scan"), False, True, True,
    ),
    DatabaseStrategy.HNSW_HYBRID: DatabaseStrategyDefinition(
        DatabaseStrategy.HNSW_HYBRID, "hnsw_hybrid", "PGVECTOR_HNSW_HYBRID",
        HNSW_INDEX_NAME, ("hnsw.ef_search", "hnsw.iterative_scan", "hnsw.max_scan_tuples"), False, True, True,
    ),
    DatabaseStrategy.IVFFLAT_HYBRID: DatabaseStrategyDefinition(
        DatabaseStrategy.IVFFLAT_HYBRID, "ivfflat_hybrid", "PGVECTOR_IVFFLAT_HYBRID",
        IVFFLAT_INDEX_NAME, ("ivfflat.probes", "ivfflat.iterative_scan", "ivfflat.max_probes"), False, True, True,
    ),
}


def strategy_definition(strategy: DatabaseStrategy) -> DatabaseStrategyDefinition:
    return STRATEGY_REGISTRY[strategy]


def strategy_from_baseline_name(name: str) -> DatabaseStrategyDefinition:
    for definition in STRATEGY_REGISTRY.values():
        if definition.baseline_strategy == name:
            return definition
    raise ValueError(f"Unknown database baseline strategy: {name}")
