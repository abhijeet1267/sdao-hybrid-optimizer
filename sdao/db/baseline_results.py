"""Typed, read-only access to PostgreSQL/pgvector baseline artifacts."""
from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any

from .strategy_registry import DatabaseStrategy, strategy_from_baseline_name


FINAL_BASELINE_DIRECTORY = Path(__file__).resolve().parents[2] / "sdao" / "results" / "db_baseline_20260814Tfinal"


@dataclass(frozen=True)
class DatabaseBaselineRecord:
    query_id: int
    predicate: str
    measured_selectivity: float | None
    strategy: DatabaseStrategy
    strategy_latency_ms: float | None
    recall: float | None
    top_k: int
    ann_parameters: dict[str, Any]
    plan_verification_status: str | None
    postgres_version: str | None
    pgvector_version: str | None
    returned_ids: tuple[int, ...]
    reference_ids: tuple[int, ...]
    status: str
    error: str | None

    @property
    def estimated_selectivity(self) -> None:
        """Baseline files contain measured evaluation selectivity only."""
        return None


class DatabaseBaselineResults:
    def __init__(self, records: tuple[DatabaseBaselineRecord, ...], source_directory: Path) -> None:
        self.records = records
        self.source_directory = source_directory

    @classmethod
    def load(cls, directory: str | Path = FINAL_BASELINE_DIRECTORY) -> "DatabaseBaselineResults":
        source = Path(directory)
        raw_records = json.loads((source / "db_baseline_results.json").read_text())
        records = tuple(cls._record(raw) for raw in raw_records)
        return cls(records, source)

    @staticmethod
    def _record(raw: dict[str, Any]) -> DatabaseBaselineRecord:
        definition = strategy_from_baseline_name(str(raw["strategy"]))
        return DatabaseBaselineRecord(
            query_id=int(raw["query_id"]), predicate=str(raw["predicate"]),
            measured_selectivity=float(raw["selectivity"]) if raw.get("selectivity") is not None else None,
            strategy=definition.strategy,
            strategy_latency_ms=float(raw["strategy_latency_ms"]) if raw.get("strategy_latency_ms") is not None else None,
            recall=float(raw["recall"]) if raw.get("recall") is not None else None,
            top_k=int(raw["top_k"]), ann_parameters=dict(raw.get("ann_parameters") or {}),
            plan_verification_status=raw.get("plan_verification_status"),
            postgres_version=raw.get("postgres_version"), pgvector_version=raw.get("pgvector_version"),
            returned_ids=tuple(int(value) for value in raw.get("returned_ids") or ()),
            reference_ids=tuple(int(value) for value in raw.get("reference_ids") or ()),
            status=str(raw["status"]), error=raw.get("error"),
        )
