import unittest

from sdao.executor import Executor
from sdao.planner import AdaptivePlanner


class SDAOExecutorTests(unittest.TestCase):
    def test_planner_returns_supported_strategy(self):
        planner = AdaptivePlanner()
        decision = planner.choose_strategy("category == 'Speaker'")
        self.assertIn(decision["strategy"], {"PRE", "POST", "GRAPH", "ISECT"})
        self.assertGreaterEqual(decision["rows"], 0)
        self.assertGreaterEqual(decision["selectivity"], 0.0)

    def test_executor_runs_a_query(self):
        executor = Executor()
        result = executor.execute("category == 'Speaker'")
        self.assertEqual(result["predicate"], "category == 'Speaker'")
        self.assertIn(result["strategy"], {"PRE", "POST", "GRAPH", "ISECT"})
        self.assertGreaterEqual(result["latency_ms"], 0.0)

    def test_planner_prefers_exact_strategy_when_target_recall_is_not_feasible(self):
        class FakeEstimator:
            total_rows = 1000

            def estimate(self, predicate):
                return {"rows": 1, "selectivity": 0.001}

        class FakeCostModel:
            def candidate_budget(self, selectivity):
                return 1

            def estimate_all(self, n_total, selectivity):
                return {"PRE": 1.0, "POST": 2.0, "GRAPH": 3.0, "ISECT": 4.0}

        planner = AdaptivePlanner(estimator=FakeEstimator(), cost_model=FakeCostModel(), target_recall=0.95)
        decision = planner.choose_strategy("category == 'Speaker'")
        self.assertEqual(decision["strategy"], "PRE")
        self.assertEqual(decision["feasible_strategies"], ["PRE"])
        self.assertGreaterEqual(decision["estimated_recall"]["PRE"], 0.95)


if __name__ == "__main__":
    unittest.main()
