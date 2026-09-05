"""Database-facing view of the existing query workload."""
from __future__ import annotations

from dataclasses import dataclass
import numpy as np
from ..utils.data_loader import DataLoader, data_loader


@dataclass(frozen=True)
class WorkloadQuery:
    query_id: int
    predicate: str
    vector: np.ndarray
    query_type: str


def get_workload_query(query_id: int, loader: DataLoader = data_loader) -> WorkloadQuery:
    queries = loader.load_queries().reset_index(drop=True)
    if isinstance(query_id, bool) or not isinstance(query_id, int) or not 0 <= query_id < len(queries):
        raise IndexError(f"query_id must be an integer in [0, {len(queries) - 1}]")
    vectors = loader.load_query_vectors()
    if query_id >= len(vectors):
        raise IndexError(f"SIFT query vector {query_id} is unavailable")
    row = queries.iloc[query_id]
    return WorkloadQuery(query_id, str(row["predicate"]), vectors[query_id], str(row.get("type", "UNKNOWN")))
