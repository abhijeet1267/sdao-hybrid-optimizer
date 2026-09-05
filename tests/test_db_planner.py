from dataclasses import replace
import json
import unittest

from sdao.db.baseline_results import DatabaseBaselineResults
from sdao.db.calibration import DatabaseStrategyCalibrator, SelectivityBucket
from sdao.db.planner import DBAdaptivePlanner, InsufficientEvidencePolicy, offline_plan_evaluation
from sdao.db.strategy_registry import DatabaseStrategy


class DatabasePlannerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.baseline = DatabaseBaselineResults.load()
        cls.calibration = DatabaseStrategyCalibrator().calibrate(cls.baseline)

    def test_sql_first_is_exact_fallback_when_no_ann_is_reliably_feasible(self):
        planner = DBAdaptivePlanner(self.calibration, target_recall=1.0)
        result = planner.plan(query_id=0, predicate="category == 'Speaker'", top_k=10, estimated_selectivity=0.12)
        self.assertEqual(result.selected_strategy, DatabaseStrategy.SQL_FIRST)
        self.assertIn(DatabaseStrategy.HNSW_HYBRID, result.rejected_strategies)

    def test_hnsw_hybrid_is_selected_when_fastest_feasible(self):
        planner = DBAdaptivePlanner(self.calibration)
        result = planner.plan(query_id=0, predicate="category == 'Speaker'", top_k=10, estimated_selectivity=0.03)
        self.assertEqual(result.selected_strategy, DatabaseStrategy.HNSW_HYBRID)
        self.assertEqual(result.recall_feasibility[DatabaseStrategy.HNSW_HYBRID.value], "reliably_feasible")

    def test_ivfflat_and_vector_first_are_rejected_when_evidence_is_insufficient_for_target(self):
        planner = DBAdaptivePlanner(self.calibration)
        result = planner.plan(query_id=0, predicate="category == 'Speaker'", top_k=10, estimated_selectivity=0.12)
        self.assertEqual(result.recall_feasibility[DatabaseStrategy.IVFFLAT_HYBRID.value], "not_reliably_feasible")
        self.assertEqual(result.recall_feasibility[DatabaseStrategy.VECTOR_FIRST_HNSW.value], "not_reliably_feasible")

    def test_lowest_predicted_latency_among_eligible_strategies_wins_deterministically(self):
        planner = DBAdaptivePlanner(self.calibration)
        first = planner.plan(query_id=1, predicate="brand == 'Apple'", top_k=10, estimated_selectivity=0.03)
        second = planner.plan(query_id=1, predicate="brand == 'Apple'", top_k=10, estimated_selectivity=0.03)
        self.assertEqual(first, second)
        eligible = {item.strategy: item.predicted_latency_ms for item in first.evidence if item.eligible}
        self.assertEqual(first.predicted_latency_ms, min(eligible.values()))

    def test_insufficient_evidence_is_rejected_by_default_and_recorded(self):
        buckets = (
            SelectivityBucket("<=0.50", None, 0.50),
            SelectivityBucket(">0.50_to_0.80", 0.50, 0.80),
            SelectivityBucket(">0.80", 0.80, None),
        )
        calibration = DatabaseStrategyCalibrator(buckets=buckets).calibrate(self.baseline)
        result = DBAdaptivePlanner(calibration).plan(query_id=2, predicate="price < 500", top_k=10, estimated_selectivity=0.90)
        for strategy in (DatabaseStrategy.VECTOR_FIRST_HNSW, DatabaseStrategy.HNSW_HYBRID, DatabaseStrategy.IVFFLAT_HYBRID):
            self.assertEqual(result.recall_feasibility[strategy.value], "insufficient_evidence")
            self.assertIn(strategy, result.rejected_strategies)

    def test_policy_can_explicitly_allow_insufficient_evidence(self):
        buckets = (SelectivityBucket("<=0.80", None, 0.80), SelectivityBucket(">0.80", 0.80, None))
        calibration = DatabaseStrategyCalibrator(buckets=buckets).calibrate(self.baseline)
        result = DBAdaptivePlanner(calibration, insufficient_evidence_policy=InsufficientEvidencePolicy.ALLOW).plan(
            query_id=2, predicate="price < 500", top_k=10, estimated_selectivity=0.90,
        )
        self.assertIn(DatabaseStrategy.HNSW_HYBRID, result.candidate_strategies)
        self.assertEqual(result.recall_feasibility[DatabaseStrategy.HNSW_HYBRID.value], "insufficient_evidence")

    def test_serialization_and_offline_evaluation_do_not_accept_measured_selectivity(self):
        planner = DBAdaptivePlanner(self.calibration)
        estimates = {query_id: 0.03 for query_id in range(32)}
        decisions = offline_plan_evaluation(planner, self.baseline.records, estimates)
        self.assertEqual(len(decisions), 32)
        self.assertEqual(json.loads(decisions[0].to_json())["estimated_selectivity"], 0.03)
        with self.assertRaises(ValueError):
            offline_plan_evaluation(planner, self.baseline.records, {})


if __name__ == "__main__":
    unittest.main()
