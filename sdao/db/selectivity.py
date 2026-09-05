"""Read-only PostgreSQL planner selectivity estimates for future DB planning."""
from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any

from .loader import TABLE_NAME
from .predicates import translate_predicate


@dataclass(frozen=True)
class DatabaseSelectivityEstimate:
    """A planner estimate, deliberately distinct from measured evaluation data."""

    predicate: str
    estimated_rows: int
    estimated_selectivity: float
    source: str = "postgres_explain"
    measured_selectivity: None = None


class PostgresSelectivityAdapter:
    """Obtain PostgreSQL cardinality estimates without executing the predicate."""

    def __init__(self, connection, dataset_size: int = 1_000_000) -> None:
        if dataset_size <= 0:
            raise ValueError("dataset_size must be positive")
        self.connection = connection
        self.dataset_size = dataset_size

    @staticmethod
    def _plan_rows(raw_plan: Any) -> int:
        plan = json.loads(raw_plan) if isinstance(raw_plan, str) else raw_plan
        try:
            rows = plan[0]["Plan"]["Plan Rows"]
        except (IndexError, KeyError, TypeError) as exc:
            raise ValueError("EXPLAIN (FORMAT JSON) did not contain top-level Plan Rows") from exc
        return max(0, int(rows))

    def estimate(self, predicate: str) -> DatabaseSelectivityEstimate:
        """Use the safe predicate translator in an isolated read-only operation.

        No GUCs or database objects are changed.  The transaction only scopes
        the EXPLAIN statement and is committed/rolled back by the caller's
        connection implementation.
        """
        translated = translate_predicate(predicate)
        sql = f"EXPLAIN (FORMAT JSON) SELECT id FROM {TABLE_NAME} WHERE {translated.sql}"
        with self.connection.transaction():
            with self.connection.cursor() as cursor:
                cursor.execute(sql, translated.params)
                raw_plan = cursor.fetchone()[0]
        rows = self._plan_rows(raw_plan)
        return DatabaseSelectivityEstimate(
            predicate=predicate,
            estimated_rows=rows,
            estimated_selectivity=min(1.0, rows / self.dataset_size),
        )
