from hashlib import sha256
from pathlib import Path
import os
import unittest

import numpy as np

from sdao.db.baseline_results import FINAL_BASELINE_DIRECTORY
from sdao.db.benchmark import HNSW_INDEX_NAME, IVFFLAT_INDEX_NAME
from sdao.db.connection import connect
from sdao.db.executor import DBAdaptiveExecutor
from sdao.db.strategy_registry import DatabaseStrategy


class FakeBenchmark:
    def __init__(self, plan_status="verified"):
        self.plan_status = plan_status
        self.calls = []

    def _result(self, method, request):
        self.calls.append((method, request))
        index = {
            "sql_first_exact": None,
            "vector_first_post_filter": HNSW_INDEX_NAME,
            "hnsw_hybrid": HNSW_INDEX_NAME,
            "ivfflat_hybrid": IVFFLAT_INDEX_NAME,
        }[method]
        return {
            "result_ids": [8, 3], "strategy_latency_ms": 12.5, "selectivity": 0.125,
            "postgres_version": "16.14", "pgvector_version": "0.8.5",
            "plan_verification_status": self.plan_status,
            "plan_evidence": {"plan_index_names": [] if index is None else [index]},
            "database_index_configuration": {"index_name": index},
        }

    def sql_first_exact(self, request, verify_plan=True):
        return self._result("sql_first_exact", request)

    def vector_first_post_filter(self, request, candidate_budget, verify_plan=True):
        self.calls.append(("candidate_budget", candidate_budget))
        return self._result("vector_first_post_filter", request)

    def hnsw_hybrid(self, request, verify_plan=True):
        return self._result("hnsw_hybrid", request)

    def ivfflat_hybrid(self, request, verify_plan=True):
        return self._result("ivfflat_hybrid", request)


class DatabaseExecutorTests(unittest.TestCase):
    def setUp(self):
        self.vector = np.zeros(128, dtype=np.float32)

    def execute(self, strategy, benchmark=None, **kwargs):
        return DBAdaptiveExecutor(benchmark=benchmark or FakeBenchmark()).execute(
            query_id=4, predicate="category == 'Monitor'", query_vector=self.vector,
            top_k=5, strategy=strategy, **kwargs,
        )

    def test_all_four_execution_mappings_return_standardized_results(self):
        cases = (
            (DatabaseStrategy.SQL_FIRST, {}),
            (DatabaseStrategy.VECTOR_FIRST_HNSW, {"strategy_parameters": {"candidate_budget": 100}}),
            (DatabaseStrategy.HNSW_HYBRID, {}),
            (DatabaseStrategy.IVFFLAT_HYBRID, {}),
        )
        for strategy, kwargs in cases:
            result = self.execute(strategy, estimated_selectivity=0.12, reference_ids=[8, 4], **kwargs)
            self.assertTrue(result.success)
            self.assertEqual(result.strategy, strategy)
            self.assertEqual(result.result_ids, (8, 3))
            self.assertEqual(result.top_k, 5)
            self.assertEqual(result.recall, 0.5)
            self.assertEqual(result.estimated_selectivity, 0.12)
            self.assertEqual(result.measured_selectivity, 0.125)
            self.assertIsNotNone(result.plan_evidence)

    def test_sql_first_has_no_ann_requirement_and_propagates_top_k(self):
        benchmark = FakeBenchmark(plan_status="unexpected_ann_index")
        result = self.execute(DatabaseStrategy.SQL_FIRST, benchmark=benchmark)
        self.assertTrue(result.success)
        self.assertIsNone(result.expected_index)
        self.assertFalse(result.plan_verified)
        self.assertEqual(benchmark.calls[0][1].top_k, 5)

    def test_hnsw_and_ivfflat_require_their_verified_plan(self):
        for strategy, expected in ((DatabaseStrategy.HNSW_HYBRID, HNSW_INDEX_NAME), (DatabaseStrategy.IVFFLAT_HYBRID, IVFFLAT_INDEX_NAME)):
            result = self.execute(strategy)
            self.assertTrue(result.success)
            self.assertTrue(result.plan_verified)
            self.assertEqual(result.expected_index, expected)

    def test_wrong_or_missing_ann_plan_is_reported_as_failure(self):
        for status in ("wrong_ann_index", "missing_expected_ann_index"):
            result = self.execute(DatabaseStrategy.HNSW_HYBRID, benchmark=FakeBenchmark(plan_status=status))
            self.assertFalse(result.success)
            self.assertIn("Expected ANN index was not verified", result.error)

    def test_vector_first_requires_budget_and_reports_failures(self):
        result = self.execute(DatabaseStrategy.VECTOR_FIRST_HNSW)
        self.assertFalse(result.success)
        self.assertIn("requires candidate_budget", result.error)

    def test_executor_does_not_mutate_baseline_artifacts(self):
        artifact = FINAL_BASELINE_DIRECTORY / "db_baseline_results.json"
        before = sha256(artifact.read_bytes()).hexdigest()
        self.execute(DatabaseStrategy.SQL_FIRST)
        self.assertEqual(sha256(artifact.read_bytes()).hexdigest(), before)

    @unittest.skipUnless(os.getenv("SDAO_DB_INTEGRATION") == "1", "set SDAO_DB_INTEGRATION=1 to query local PostgreSQL")
    def test_live_hnsw_smoke(self):
        connection = connect()
        executor = DBAdaptiveExecutor(connection=connection)
        try:
            result = executor.execute(
                query_id=0, predicate="category == 'Speaker'", query_vector=np.array(
                    [0] * 128, dtype=np.float32), top_k=1,
                strategy=DatabaseStrategy.HNSW_HYBRID,
            )
        finally:
            connection.close()
        self.assertTrue(result.success, result.error)
        self.assertTrue(result.plan_verified)
        self.assertEqual(result.expected_index, HNSW_INDEX_NAME)


if __name__ == "__main__":
    unittest.main()
