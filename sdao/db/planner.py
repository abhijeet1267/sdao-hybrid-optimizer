"""Conservative adaptive planning for the PostgreSQL/pgvector backend."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
import json
from typing import Mapping

from .calibration import CalibrationModel, bucket_for
from .selectivity import PostgresSelectivityAdapter
from .strategy_registry import DatabaseStrategy


class InsufficientEvidencePolicy(str, Enum):
    REJECT = "reject"
    ALLOW = "allow"


@dataclass(frozen=True)
class StrategyDecisionEvidence:
    strategy: DatabaseStrategy
    feasibility: str
    predicted_latency_ms: float | None
    eligible: bool
    reason: str
    bucket: str
    observed_minimum_recall: float | None
    observed_fraction_meeting_target: float | None


@dataclass(frozen=True)
class DatabasePlanningResult:
    query_id: int
    predicate: str
    top_k: int
    estimated_selectivity: float
    target_recall: float
    selected_strategy: DatabaseStrategy
    predicted_latency_ms: float
    candidate_strategies: tuple[DatabaseStrategy, ...]
    rejected_strategies: tuple[DatabaseStrategy, ...]
    rejection_reasons: dict[str, str]
    recall_feasibility: dict[str, str]
    evidence: tuple[StrategyDecisionEvidence, ...]
    calibration_source: str
    calibration_model_version: str
    decision_reason: str

    def to_json(self) -> str:
        return json.dumps(asdict(self), default=lambda value: value.value if isinstance(value, Enum) else str(value))


class DBAdaptivePlanner:
    """Choose the fastest empirically reliable registered DB strategy.

    This planner deliberately operates on *estimated* selectivity only.  It
    never accepts baseline measured selectivity as an input and never derives
    recall from candidate counts.
    """

    def __init__(self, calibration: CalibrationModel, selectivity_adapter: PostgresSelectivityAdapter | None = None,
                 target_recall: float = 0.95,
                 insufficient_evidence_policy: InsufficientEvidencePolicy | str = InsufficientEvidencePolicy.REJECT) -> None:
        if not 0.0 < target_recall <= 1.0:
            raise ValueError("target_recall must be between 0 and 1")
        self.calibration = calibration
        self.selectivity_adapter = selectivity_adapter
        self.target_recall = target_recall
        self.insufficient_evidence_policy = InsufficientEvidencePolicy(insufficient_evidence_policy)

    def _evidence(self, strategy: DatabaseStrategy, estimated_selectivity: float) -> StrategyDecisionEvidence:
        bucket = bucket_for(estimated_selectivity, self.calibration.selectivity_buckets)
        calibration = self.calibration.strategy(strategy)
        bucket_evidence = next(item for item in calibration.buckets if item.bucket == bucket.name)
        prediction = self.calibration.predict_latency(strategy, estimated_selectivity)
        if strategy is DatabaseStrategy.SQL_FIRST:
            return StrategyDecisionEvidence(
                strategy, "reliably_feasible", prediction, True,
                "Exact SQL-first remains the recall-safe fallback.", bucket.name, 1.0, 1.0,
            )
        if bucket_evidence.observation_count == 0 or bucket_evidence.recall is None:
            status = "insufficient_evidence"
            eligible = self.insufficient_evidence_policy is InsufficientEvidencePolicy.ALLOW
            reason = "No observed recall evidence in this selectivity bucket."
            if eligible:
                reason += " Allowed only by the explicit insufficient-evidence policy."
            return StrategyDecisionEvidence(strategy, status, prediction, eligible, reason, bucket.name, None, None)
        recall = bucket_evidence.recall
        if recall.minimum >= self.target_recall:
            return StrategyDecisionEvidence(
                strategy, "reliably_feasible", prediction, True,
                f"Observed minimum recall {recall.minimum:.3f} meets target {self.target_recall:.3f}.",
                bucket.name, recall.minimum, recall.fraction_meeting_target,
            )
        return StrategyDecisionEvidence(
            strategy, "not_reliably_feasible", prediction, False,
            f"Observed minimum recall {recall.minimum:.3f} is below target {self.target_recall:.3f}.",
            bucket.name, recall.minimum, recall.fraction_meeting_target,
        )

    def plan(self, *, query_id: int, predicate: str, top_k: int,
             estimated_selectivity: float | None = None) -> DatabasePlanningResult:
        if top_k <= 0:
            raise ValueError("top_k must be positive")
        if estimated_selectivity is None:
            if self.selectivity_adapter is None:
                raise ValueError("estimated_selectivity is required when no PostgreSQL selectivity adapter is configured")
            estimated_selectivity = self.selectivity_adapter.estimate(predicate).estimated_selectivity
        if not 0.0 <= estimated_selectivity <= 1.0:
            raise ValueError("estimated_selectivity must be between 0 and 1")
        evidence = tuple(self._evidence(strategy, estimated_selectivity) for strategy in DatabaseStrategy)
        candidates = tuple(item for item in evidence if item.eligible)
        # SQL_FIRST is always eligible, so this has a deterministic exact fallback.
        selected = min(candidates, key=lambda item: (float(item.predicted_latency_ms), item.strategy.value))
        rejected = tuple(item.strategy for item in evidence if not item.eligible)
        rejected_reasons = {item.strategy.value: item.reason for item in evidence if not item.eligible}
        feasible_names = ", ".join(item.strategy.value for item in candidates)
        reason = (
            f"Selected {selected.strategy.value}: lowest predicted latency among eligible strategies "
            f"({feasible_names}) in {selected.bucket}; {selected.reason}"
        )
        return DatabasePlanningResult(
            query_id=query_id, predicate=predicate, top_k=top_k, estimated_selectivity=float(estimated_selectivity),
            target_recall=self.target_recall, selected_strategy=selected.strategy,
            predicted_latency_ms=float(selected.predicted_latency_ms),
            candidate_strategies=tuple(item.strategy for item in candidates), rejected_strategies=rejected,
            rejection_reasons=rejected_reasons,
            recall_feasibility={item.strategy.value: item.feasibility for item in evidence}, evidence=evidence,
            calibration_source=self.calibration.source_path, calibration_model_version="empirical_db_calibration_v1",
            decision_reason=reason,
        )


def offline_plan_evaluation(planner: DBAdaptivePlanner, records, estimated_selectivity_by_query: Mapping[int, float]) -> tuple[DatabasePlanningResult, ...]:
    """Replay predicates with externally supplied planner estimates only.

    The baseline's ``measured_selectivity`` is intentionally not consulted.
    """
    query_predicates: dict[int, str] = {}
    for record in records:
        if record.query_id in query_predicates and query_predicates[record.query_id] != record.predicate:
            raise ValueError(f"inconsistent predicate for query {record.query_id}")
        query_predicates[record.query_id] = record.predicate
    if set(estimated_selectivity_by_query) != set(query_predicates):
        raise ValueError("offline evaluation requires an estimated selectivity for every baseline query")
    return tuple(
        planner.plan(query_id=query_id, predicate=predicate, top_k=10,
                     estimated_selectivity=float(estimated_selectivity_by_query[query_id]))
        for query_id, predicate in sorted(query_predicates.items())
    )
