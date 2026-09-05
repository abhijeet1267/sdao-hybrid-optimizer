import csv
import os
from pathlib import Path
import unittest

from sdao.db.baseline_results import DatabaseBaselineResults, FINAL_BASELINE_DIRECTORY
from sdao.db.benchmark import HNSW_INDEX_NAME, IVFFLAT_INDEX_NAME
from sdao.db.connection import connect
from sdao.db.selectivity import PostgresSelectivityAdapter
from sdao.db.strategy_registry import DatabaseStrategy, STRATEGY_REGISTRY, strategy_definition
from sdao.db.predicates import translate_predicate


class _Transaction:
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class _Cursor:
    def __init__(self, connection):
        self.connection = connection

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute(self, statement, params=()):
        self.connection.statements.append((statement, params))

    def fetchone(self):
        return ([{"Plan": {"Plan Rows": 250_000}}],)


class _Connection:
    def __init__(self):
        self.statements = []

    def transaction(self):
        return _Transaction()

    def cursor(self):
        return _Cursor(self)


class DatabaseAdaptiveTests(unittest.TestCase):
    def test_all_workload_predicates_use_safe_translation(self):
        with (Path(__file__).resolve().parents[1] / "queries.csv").open() as handle:
            rows = list(csv.DictReader(handle))
        self.assertEqual(len(rows), 32)
        for row in rows:
            translated = translate_predicate(row["predicate"])
            self.assertIn("%s", translated.sql)
            self.assertNotIn(";", translated.sql)

    def test_selectivity_estimate_is_bounded_and_not_measured_data(self):
        connection = _Connection()
        estimate = PostgresSelectivityAdapter(connection).estimate("category == 'Speaker'")
        self.assertEqual(estimate.estimated_rows, 250_000)
        self.assertEqual(estimate.estimated_selectivity, 0.25)
        self.assertIsNone(estimate.measured_selectivity)
        self.assertTrue(0.0 <= estimate.estimated_selectivity <= 1.0)
        statement, params = connection.statements[0]
        self.assertTrue(statement.startswith("EXPLAIN (FORMAT JSON)"))
        self.assertIn('"category" = %s', statement)
        self.assertEqual(params, ("Speaker",))

    def test_final_baseline_reader_preserves_measured_selectivity(self):
        baseline = DatabaseBaselineResults.load()
        self.assertEqual(baseline.source_directory, FINAL_BASELINE_DIRECTORY)
        self.assertEqual(len(baseline.records), 128)
        record = baseline.records[0]
        self.assertIsNotNone(record.measured_selectivity)
        self.assertIsNone(record.estimated_selectivity)
        self.assertEqual(record.top_k, 10)
        self.assertEqual(record.pgvector_version, "0.8.5")

    def test_all_database_strategies_are_explicitly_registered(self):
        self.assertEqual(set(STRATEGY_REGISTRY), set(DatabaseStrategy))
        hnsw = strategy_definition(DatabaseStrategy.HNSW_HYBRID)
        ivfflat = strategy_definition(DatabaseStrategy.IVFFLAT_HYBRID)
        exact = strategy_definition(DatabaseStrategy.SQL_FIRST)
        self.assertTrue(hnsw.requires_ann_plan_verification)
        self.assertEqual(hnsw.required_index, HNSW_INDEX_NAME)
        self.assertTrue(ivfflat.requires_ann_plan_verification)
        self.assertEqual(ivfflat.required_index, IVFFLAT_INDEX_NAME)
        self.assertFalse(exact.requires_ann_plan_verification)
        self.assertTrue(exact.exact)

    @unittest.skipUnless(os.getenv("SDAO_DB_INTEGRATION") == "1", "set SDAO_DB_INTEGRATION=1 to query local PostgreSQL")
    def test_live_selectivity_adapter_returns_postgres_estimate(self):
        connection = connect()
        try:
            estimate = PostgresSelectivityAdapter(connection).estimate("category == 'Speaker'")
        finally:
            connection.close()
        self.assertGreaterEqual(estimate.estimated_rows, 0)
        self.assertTrue(0.0 <= estimate.estimated_selectivity <= 1.0)


if __name__ == "__main__":
    unittest.main()
