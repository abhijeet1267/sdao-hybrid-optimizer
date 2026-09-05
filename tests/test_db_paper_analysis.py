import unittest
import pandas as pd

from sdao.db.paper_analysis import TARGET_RECALL, _equal, bucket_name, metrics, oracle_table


class PaperAnalysisTests(unittest.TestCase):
    def setUp(self):
        self.adaptive = pd.DataFrame([
            {"query_id": 0, "strategy": "SQL_FIRST", "strategy_only_latency_ms": 10.0, "recall": 1.0},
            {"query_id": 1, "strategy": "HNSW_HYBRID", "strategy_only_latency_ms": 5.0, "recall": 1.0},
        ])
        self.fixed = pd.DataFrame([
            {"query_id": 0, "strategy": "SQL_FIRST", "strategy_only_latency_ms": 8.0, "recall": 1.0},
            {"query_id": 0, "strategy": "HNSW_HYBRID", "strategy_only_latency_ms": 2.0, "recall": .9},
            {"query_id": 1, "strategy": "SQL_FIRST", "strategy_only_latency_ms": 9.0, "recall": 1.0},
            {"query_id": 1, "strategy": "HNSW_HYBRID", "strategy_only_latency_ms": 3.0, "recall": 1.0},
        ])

    def test_percentile_and_recall_metrics(self):
        got = metrics(self.adaptive)
        self.assertEqual(got["query_count"], 2)
        self.assertEqual(got["mean_latency_ms"], 7.5)
        self.assertEqual(got["minimum_recall"], 1.0)
        self.assertEqual(got["fraction_recall_at_least_095"], 1.0)

    def test_recall_feasible_oracle_excludes_unsafe_fast_strategy(self):
        result = oracle_table(self.adaptive, self.fixed)
        self.assertEqual(result.loc[0, "recall_feasible_oracle_strategy"], "SQL_FIRST")
        self.assertEqual(result.loc[0, "fastest_oracle_strategy"], "HNSW_HYBRID")
        self.assertEqual(result.loc[0, "planner_regret_ms"], 2.0)

    def test_oracle_match_and_regret(self):
        result = oracle_table(self.adaptive, self.fixed)
        self.assertTrue(result.loc[1, "recall_feasible_identity_match"])
        self.assertTrue(result.loc[1, "fastest_identity_match"])
        self.assertEqual(result.loc[1, "planner_regret_ms"], 2.0)

    def test_selectivity_bucket_boundaries(self):
        self.assertEqual(bucket_name(0.05), "<=0.05")
        self.assertEqual(bucket_name(0.050001), ">0.05_to_0.10")
        self.assertEqual(bucket_name(0.50), ">0.25_to_0.50")
        self.assertEqual(bucket_name(0.500001), ">0.50")

    def test_nested_csv_consistency_comparison(self):
        self.assertTrue(_equal({"a": [1, 2]}, "{'a': [1, 2]}"))
        self.assertTrue(_equal(None, float("nan")))
        self.assertFalse(_equal([1], "[2]"))

    def test_target_is_the_required_recall_threshold(self):
        self.assertEqual(TARGET_RECALL, .95)


if __name__ == "__main__":
    unittest.main()
