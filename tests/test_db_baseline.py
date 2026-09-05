import csv
from pathlib import Path
import unittest

import numpy as np
import pandas as pd

from sdao.db.benchmark import DatabaseBenchmark, HNSW_INDEX_NAME, IVFFLAT_INDEX_NAME, QueryRequest
from sdao.db.config import ConfigurationError, DatabaseConfig
from sdao.db.loader import DatasetValidationError, _validate_metadata_batch
from sdao.db.predicates import PredicateError, translate_predicate


class FakeTransaction:
    def __init__(self, connection):
        self.connection = connection

    def __enter__(self):
        self.connection.transaction_entries += 1
        return self

    def __exit__(self, *args):
        self.connection.transaction_exits += 1
        return False


class FakeCursor:
    def __init__(self, connection):
        self.connection, self.executed = connection, []
        self.last_statement = ""

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute(self, statement, params=()):
        self.last_statement = statement
        self.executed.append((statement, params))
        self.connection.executed.append((statement, params))

    def fetchone(self):
        if self.last_statement.startswith("SHOW server_version"):
            return ("16.9",)
        if "pg_extension" in self.last_statement:
            return ("0.8.5",)
        if self.last_statement.startswith("EXPLAIN"):
            names = self.connection.explain_index_names
            return ([{"Plan": {"Node Type": "Index Scan", **({"Index Name": names[0]} if names else {})}}],)
        return (125,)

    def fetchall(self):
        return [(8,), (3,)]


class FakeConnection:
    def __init__(self):
        self.cursors, self.executed = [], []
        self.transaction_entries = self.transaction_exits = 0
        self.explain_index_names = [HNSW_INDEX_NAME]

    def cursor(self):
        cursor = FakeCursor(self)
        self.cursors.append(cursor)
        return cursor

    def transaction(self):
        return FakeTransaction(self)


class DatabaseBaselineTests(unittest.TestCase):
    def setUp(self):
        self.connection = FakeConnection()
        self.benchmark = DatabaseBenchmark(self.connection, dataset_size=1000)
        self.vector = np.zeros(128, dtype=np.float32)

    def request(self, top_k=10):
        return QueryRequest(4, "price < 500", self.vector, top_k)

    def test_schema_declares_existing_sift_shape(self):
        schema = (Path(__file__).resolve().parents[1] / "sql" / "schema.sql").read_text()
        self.assertIn("CREATE EXTENSION IF NOT EXISTS vector", schema)
        self.assertIn("embedding vector(128) NOT NULL", schema)
        for column in ("id", "category", "brand", "price", "rating", "stock"):
            self.assertIn(column, schema)

    def test_configuration_requires_all_environment_values(self):
        with self.assertRaises(ConfigurationError):
            DatabaseConfig.from_env({})
        config = DatabaseConfig.from_env({"POSTGRES_HOST": "localhost", "POSTGRES_PORT": "5432", "POSTGRES_DB": "sdao", "POSTGRES_USER": "user", "POSTGRES_PASSWORD": "secret"})
        self.assertEqual(config.connect_kwargs()["dbname"], "sdao")

    def test_every_current_workload_predicate_translates(self):
        workload = Path(__file__).resolve().parents[1] / "queries.csv"
        with workload.open() as handle:
            rows = list(csv.DictReader(handle))
        self.assertEqual(len(rows), 32)
        for row in rows:
            translated = translate_predicate(row["predicate"])
            self.assertIn("%s", translated.sql)
            self.assertNotIn(";", translated.sql)
            self.assertGreaterEqual(len(translated.params), 1)
        with self.assertRaises(PredicateError):
            translate_predicate("category == 'Laptop'; DROP TABLE sift1m_items")

    def test_exact_and_ann_query_ordering_are_intentionally_different(self):
        exact = self.benchmark._spec(self.request(), "sql_first_exact")
        hnsw = self.benchmark._spec(self.request(), "hnsw_hybrid")
        ivfflat = self.benchmark._spec(self.request(), "ivfflat_hybrid")
        post = self.benchmark._spec(self.request(), "vector_first_post_filter", 100)
        self.assertIn("ORDER BY embedding <-> %s::vector, id", exact.sql)
        for spec in (hnsw, ivfflat, post):
            self.assertNotIn("embedding <-> %s::vector, id", spec.sql)
        self.assertEqual(hnsw.index_name, HNSW_INDEX_NAME)
        self.assertEqual(ivfflat.index_name, IVFFLAT_INDEX_NAME)
        self.assertEqual(post.index_name, HNSW_INDEX_NAME)
        self.assertIn("hnsw.ef_search", post.configuration["session_settings"])

    def test_top_k_propagates_for_all_supported_sizes(self):
        for top_k in (1, 5, 10, 20):
            request = self.request(top_k)
            for strategy, budget in (("sql_first_exact", None), ("hnsw_hybrid", None), ("ivfflat_hybrid", None), ("vector_first_post_filter", 100)):
                spec = self.benchmark._spec(request, strategy, budget)
                self.assertEqual(spec.params[-1], top_k)
        with self.assertRaises(ValueError):
            QueryRequest(0, "stock == True", self.vector, 0)

    def test_vector_first_joins_candidates_to_metadata_for_all_predicate_shapes(self):
        predicates = (
            "category == 'Monitor'", "brand == 'Apple'", "price < 500",
            "category == 'Monitor' and price < 500",
        )
        for predicate in predicates:
            request = QueryRequest(4, predicate, self.vector, 7)
            spec = self.benchmark._spec(request, "vector_first_post_filter", 100)
            self.assertIn("WITH candidates AS MATERIALIZED", spec.sql)
            self.assertIn("JOIN sift1m_items AS item ON item.id = candidates.id", spec.sql)
            self.assertIn(translate_predicate(predicate).sql, spec.sql)
            self.assertEqual(spec.params[-1], 7)
            self.assertIn("ORDER BY candidates.distance, candidates.id", spec.sql)

    def test_transaction_boundaries_and_result_metadata(self):
        result = self.benchmark.sql_first_exact(self.request())
        self.assertEqual(result["result_ids"], [8, 3])
        self.assertEqual(result["strategy"], "PGVECTOR_SQL_FIRST_EXACT")
        self.assertEqual(result["postgres_version"], "16.9")
        self.assertEqual(result["pgvector_version"], "0.8.5")
        self.assertIsNone(result["plan_verification_status"])
        self.assertEqual(self.connection.transaction_entries, self.connection.transaction_exits)
        self.assertTrue(any("enable_indexscan" in str(params) for _, params in self.connection.executed))

    def test_ann_requires_and_reports_verified_plan(self):
        result = self.benchmark.hnsw_hybrid(self.request())
        self.assertEqual(result["plan_verification_status"], "verified")
        self.assertEqual(result["database_index_configuration"]["index_name"], HNSW_INDEX_NAME)
        self.assertEqual(self.connection.transaction_entries, self.connection.transaction_exits)

    def test_vector_first_requires_hnsw_plan_and_returns_ids(self):
        result = self.benchmark.vector_first_post_filter(self.request(top_k=5), candidate_budget=100)
        self.assertEqual(result["strategy"], "PGVECTOR_VECTOR_FIRST_HNSW_POST_FILTER")
        self.assertEqual(result["result_ids"], [8, 3])
        self.assertEqual(result["rows_retrieved"], 2)
        self.assertEqual(result["plan_verification_status"], "verified")
        self.assertEqual(result["plan_evidence"]["expected_index_name"], HNSW_INDEX_NAME)

    def test_ivfflat_default_is_pgvector_085_compatible(self):
        spec = self.benchmark._spec(self.request(), "ivfflat_hybrid")
        self.assertEqual(spec.configuration["session_settings"]["ivfflat.iterative_scan"], "off")
        with self.assertRaises(ValueError):
            DatabaseBenchmark(self.connection, ivfflat_iterative_scan="strict_order")

    def test_plan_verification_rejects_the_other_ann_index(self):
        self.connection.explain_index_names = [IVFFLAT_INDEX_NAME]
        evidence = self.benchmark.verify_plan(self.request(), "hnsw_hybrid")
        self.assertEqual(evidence["plan_verification_status"], "wrong_ann_index")
        self.assertEqual(evidence["wrong_ann_index_names"], [IVFFLAT_INDEX_NAME])

    def test_ivfflat_plan_verification_requires_ivfflat(self):
        self.connection.explain_index_names = [IVFFLAT_INDEX_NAME]
        evidence = self.benchmark.verify_plan(self.request(), "ivfflat_hybrid")
        self.assertEqual(evidence["plan_verification_status"], "verified")
        self.assertEqual(evidence["expected_index_name"], IVFFLAT_INDEX_NAME)

    def test_sql_first_accepts_a_sequential_plan(self):
        self.connection.explain_index_names = []
        evidence = self.benchmark.verify_plan(self.request(), "sql_first_exact")
        self.assertEqual(evidence["plan_verification_status"], "verified")
        self.assertEqual(evidence["plan_index_names"], [])

    def test_plan_isolation_settings_are_transaction_local(self):
        self.benchmark.verify_plan(self.request(), "hnsw_hybrid")
        settings = [(statement, params) for statement, params in self.connection.executed if "set_config" in statement]
        self.assertTrue(settings)
        self.assertTrue(all("true" in statement.lower() and len(params) == 2 for statement, params in settings))
        self.assertEqual(self.connection.transaction_entries, self.connection.transaction_exits)

    def test_request_rejects_nonfinite_vector(self):
        invalid = self.vector.copy()
        invalid[0] = np.nan
        with self.assertRaises(ValueError):
            QueryRequest(0, "stock == True", invalid, 7)

    def test_metadata_validation_rejects_null_stock_and_other_malformed_values(self):
        valid = pd.DataFrame({"id": [0], "category": ["Laptop"], "brand": ["Apple"], "price": [100], "rating": [4.5], "stock": [True]})
        self.assertEqual(_validate_metadata_batch(valid, 1).tolist(), [0])
        cases = [
            ("stock", np.nan), ("category", None), ("brand", ""), ("price", -1),
            ("rating", np.inf), ("id", np.nan),
        ]
        for column, value in cases:
            malformed = valid.copy()
            malformed[column] = malformed[column].astype(object)
            malformed.loc[0, column] = value
            with self.assertRaises(DatasetValidationError, msg=column):
                _validate_metadata_batch(malformed, 1)


if __name__ == "__main__":
    unittest.main()
