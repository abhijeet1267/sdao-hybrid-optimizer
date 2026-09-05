from dataclasses import replace
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from sdao.db.baseline_results import DatabaseBaselineResults, FINAL_BASELINE_DIRECTORY
from sdao.db.calibration import DatabaseStrategyCalibrator, DEFAULT_BUCKETS, bucket_for, write_calibration
from sdao.db.strategy_registry import DatabaseStrategy


class DatabaseCalibrationTests(unittest.TestCase):
    def setUp(self):
        self.baseline = DatabaseBaselineResults.load()
        self.calibrator = DatabaseStrategyCalibrator()

    def test_all_four_strategies_and_all_queries_are_calibrated(self):
        model = self.calibrator.calibrate(self.baseline)
        self.assertEqual(set(model.strategies), set(DatabaseStrategy))
        self.assertEqual(model.source_observation_count, 128)
        for calibration in model.strategies.values():
            self.assertEqual(calibration.observation_count, 32)

    def test_bucket_assignment_and_latency_prediction(self):
        self.assertEqual(bucket_for(0.05, DEFAULT_BUCKETS).name, "<=0.05")
        self.assertEqual(bucket_for(0.10, DEFAULT_BUCKETS).name, ">0.05_to_0.10")
        self.assertEqual(bucket_for(0.51, DEFAULT_BUCKETS).name, ">0.50")
        model = self.calibrator.calibrate(self.baseline)
        prediction = model.predict_latency(DatabaseStrategy.HNSW_HYBRID, 0.12)
        self.assertGreaterEqual(prediction, 0.0)

    def test_recall_statistics_and_conservative_feasibility(self):
        model = self.calibrator.calibrate(self.baseline)
        exact = model.strategy(DatabaseStrategy.SQL_FIRST)
        self.assertEqual(exact.recall.minimum, 1.0)
        self.assertTrue(all(bucket.conservative_feasibility == "reliably_feasible" for bucket in exact.buckets if bucket.observation_count))
        ivfflat = model.strategy(DatabaseStrategy.IVFFLAT_HYBRID)
        self.assertLess(ivfflat.recall.minimum, model.target_recall)
        self.assertTrue(any(bucket.conservative_feasibility == "not_reliably_feasible" for bucket in ivfflat.buckets))

    def test_duplicate_or_missing_records_are_rejected(self):
        with self.assertRaises(ValueError):
            self.calibrator._validate_records(self.baseline.records + (self.baseline.records[0],))
        with self.assertRaises(ValueError):
            self.calibrator._validate_records(self.baseline.records[:-1])

    def test_small_sample_strategy_marks_fallback(self):
        records = [record for record in self.baseline.records if record.strategy is DatabaseStrategy.HNSW_HYBRID][:3]
        calibration = self.calibrator.calibrate_strategy(DatabaseStrategy.HNSW_HYBRID, records)
        self.assertTrue(calibration.latency_model.used_small_sample_fallback)
        self.assertEqual(calibration.observation_count, 3)

    def test_serialization_and_baseline_immutability(self):
        artifact = FINAL_BASELINE_DIRECTORY / "db_baseline_results.json"
        before = sha256(artifact.read_bytes()).hexdigest()
        model = self.calibrator.calibrate(self.baseline)
        with TemporaryDirectory() as directory:
            output = Path(directory) / "calibration"
            write_calibration(model, output)
            self.assertTrue((output / "db_strategy_calibration.json").is_file())
            self.assertTrue((output / "db_strategy_calibration_summary.csv").is_file())
            self.assertTrue((output / "db_strategy_calibration_buckets.csv").is_file())
        self.assertEqual(sha256(artifact.read_bytes()).hexdigest(), before)


if __name__ == "__main__":
    unittest.main()
