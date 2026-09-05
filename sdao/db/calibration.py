"""Empirical DB-strategy calibration from preserved baseline observations."""
from __future__ import annotations

from dataclasses import asdict, dataclass
import argparse
import json
from math import sqrt
from pathlib import Path
from statistics import mean, median, pstdev
from typing import Iterable

import pandas as pd

from .baseline_results import DatabaseBaselineRecord, DatabaseBaselineResults, FINAL_BASELINE_DIRECTORY
from .strategy_registry import DatabaseStrategy


@dataclass(frozen=True)
class SelectivityBucket:
    name: str
    lower_exclusive: float | None
    upper_inclusive: float | None

    def contains(self, value: float) -> bool:
        return (self.lower_exclusive is None or value > self.lower_exclusive) and (
            self.upper_inclusive is None or value <= self.upper_inclusive
        )


DEFAULT_BUCKETS = (
    SelectivityBucket("<=0.05", None, 0.05),
    SelectivityBucket(">0.05_to_0.10", 0.05, 0.10),
    SelectivityBucket(">0.10_to_0.25", 0.10, 0.25),
    SelectivityBucket(">0.25_to_0.50", 0.25, 0.50),
    SelectivityBucket(">0.50", 0.50, None),
)


@dataclass(frozen=True)
class RecallStatistics:
    observation_count: int
    mean: float
    median: float
    minimum: float
    maximum: float
    p05: float
    p95: float
    fraction_meeting_target: float


@dataclass(frozen=True)
class BucketCalibration:
    bucket: str
    observation_count: int
    latency_mean_ms: float | None
    latency_median_ms: float | None
    recall: RecallStatistics | None
    conservative_feasibility: str


@dataclass(frozen=True)
class LatencyModel:
    model_type: str
    observation_count: int
    bucket_median_ms: dict[str, float]
    global_median_ms: float
    mae_ms: float
    rmse_ms: float
    used_small_sample_fallback: bool

    def predict(self, selectivity: float, buckets: Iterable[SelectivityBucket]) -> float:
        bucket = bucket_for(selectivity, buckets)
        return self.bucket_median_ms.get(bucket.name, self.global_median_ms)


@dataclass(frozen=True)
class StrategyCalibration:
    strategy: DatabaseStrategy
    observation_count: int
    latency_mean_ms: float
    latency_median_ms: float
    latency_p95_ms: float
    latency_stddev_ms: float
    latency_model: LatencyModel
    recall: RecallStatistics
    buckets: tuple[BucketCalibration, ...]


@dataclass(frozen=True)
class CalibrationModel:
    source_path: str
    source_observation_count: int
    expected_query_count: int
    target_recall: float
    selectivity_buckets: tuple[SelectivityBucket, ...]
    strategies: dict[DatabaseStrategy, StrategyCalibration]
    limitations: tuple[str, ...]

    def strategy(self, name: DatabaseStrategy) -> StrategyCalibration:
        return self.strategies[name]

    def predict_latency(self, strategy: DatabaseStrategy, selectivity: float) -> float:
        return self.strategy(strategy).latency_model.predict(selectivity, self.selectivity_buckets)


def bucket_for(selectivity: float, buckets: Iterable[SelectivityBucket] = DEFAULT_BUCKETS) -> SelectivityBucket:
    if not 0.0 <= selectivity <= 1.0:
        raise ValueError("selectivity must be between 0 and 1")
    for bucket in buckets:
        if bucket.contains(selectivity):
            return bucket
    raise ValueError("selectivity buckets do not cover the supplied value")


def _quantile(values: list[float], fraction: float) -> float:
    return float(pd.Series(values).quantile(fraction))


def _recall_statistics(values: list[float], target_recall: float) -> RecallStatistics:
    if not values:
        raise ValueError("recall statistics require observations")
    return RecallStatistics(
        observation_count=len(values), mean=float(mean(values)), median=float(median(values)),
        minimum=float(min(values)), maximum=float(max(values)), p05=_quantile(values, 0.05), p95=_quantile(values, 0.95),
        fraction_meeting_target=sum(value >= target_recall for value in values) / len(values),
    )


class DatabaseStrategyCalibrator:
    """Fit conservative, per-strategy empirical summaries from saved results."""

    def __init__(self, buckets: tuple[SelectivityBucket, ...] = DEFAULT_BUCKETS,
                 target_recall: float = 0.95, minimum_model_observations: int = 5) -> None:
        if not buckets or not 0.0 < target_recall <= 1.0 or minimum_model_observations < 1:
            raise ValueError("invalid calibration configuration")
        self.buckets = buckets
        self.target_recall = target_recall
        self.minimum_model_observations = minimum_model_observations
        for value in (0.0, 0.05, 0.10, 0.25, 0.50, 1.0):
            bucket_for(value, buckets)

    def calibrate(self, baseline: DatabaseBaselineResults) -> CalibrationModel:
        records = baseline.records
        self._validate_records(records)
        grouped = {strategy: [record for record in records if record.strategy is strategy] for strategy in DatabaseStrategy}
        return CalibrationModel(
            source_path=str(baseline.source_directory), source_observation_count=len(records),
            expected_query_count=32, target_recall=self.target_recall, selectivity_buckets=self.buckets,
            strategies={strategy: self.calibrate_strategy(strategy, grouped[strategy]) for strategy in DatabaseStrategy},
            limitations=(
                "Calibration uses one completed 32-query workload and is not an independent training set.",
                "Bucket medians are descriptive empirical estimates, not a causal database performance model.",
                "Recall feasibility is conservative observed evidence; unobserved selectivities have insufficient evidence.",
                "Measurements use the baseline's warm persistent-session protocol and uncontrolled cache state.",
            ),
        )

    def _validate_records(self, records: tuple[DatabaseBaselineRecord, ...]) -> None:
        expected_queries = set(range(32))
        seen: set[tuple[DatabaseStrategy, int]] = set()
        for record in records:
            key = (record.strategy, record.query_id)
            if key in seen:
                raise ValueError(f"duplicate baseline observation for {record.strategy.value} query {record.query_id}")
            seen.add(key)
            if record.status != "completed":
                raise ValueError(f"baseline observation failed: {record.strategy.value} query {record.query_id}")
            if record.measured_selectivity is None or record.strategy_latency_ms is None or record.recall is None:
                raise ValueError(f"baseline observation is incomplete: {record.strategy.value} query {record.query_id}")
        for strategy in DatabaseStrategy:
            query_ids = {query_id for candidate_strategy, query_id in seen if candidate_strategy is strategy}
            if query_ids != expected_queries:
                raise ValueError(f"missing baseline observations for {strategy.value}: expected queries 0..31")

    def calibrate_strategy(self, strategy: DatabaseStrategy,
                           records: list[DatabaseBaselineRecord]) -> StrategyCalibration:
        if not records:
            raise ValueError(f"no observations for {strategy.value}")
        latency = [float(record.strategy_latency_ms) for record in records if record.strategy_latency_ms is not None]
        recall = [float(record.recall) for record in records if record.recall is not None]
        bucket_medians: dict[str, float] = {}
        bucket_models: list[BucketCalibration] = []
        for bucket in self.buckets:
            subset = [record for record in records if record.measured_selectivity is not None and bucket.contains(record.measured_selectivity)]
            if not subset:
                bucket_models.append(BucketCalibration(bucket.name, 0, None, None, None, "insufficient_evidence"))
                continue
            bucket_latency = [float(record.strategy_latency_ms) for record in subset if record.strategy_latency_ms is not None]
            bucket_recall = [float(record.recall) for record in subset if record.recall is not None]
            bucket_medians[bucket.name] = float(median(bucket_latency))
            recall_stats = _recall_statistics(bucket_recall, self.target_recall)
            feasibility = "reliably_feasible" if recall_stats.minimum >= self.target_recall else "not_reliably_feasible"
            bucket_models.append(BucketCalibration(
                bucket.name, len(subset), float(mean(bucket_latency)), float(median(bucket_latency)), recall_stats, feasibility,
            ))
        global_median = float(median(latency))
        predictions = [bucket_medians.get(bucket_for(float(record.measured_selectivity), self.buckets).name, global_median) for record in records]
        errors = [prediction - observed for prediction, observed in zip(predictions, latency)]
        model = LatencyModel(
            model_type="empirical_bucket_median", observation_count=len(records), bucket_median_ms=bucket_medians,
            global_median_ms=global_median, mae_ms=float(mean(abs(error) for error in errors)),
            rmse_ms=sqrt(mean(error * error for error in errors)),
            used_small_sample_fallback=len(records) < self.minimum_model_observations,
        )
        return StrategyCalibration(
            strategy=strategy, observation_count=len(records), latency_mean_ms=float(mean(latency)),
            latency_median_ms=global_median, latency_p95_ms=_quantile(latency, 0.95),
            latency_stddev_ms=float(pstdev(latency)), latency_model=model,
            recall=_recall_statistics(recall, self.target_recall), buckets=tuple(bucket_models),
        )


def write_calibration(model: CalibrationModel, output_directory: str | Path) -> Path:
    output = Path(output_directory)
    if output.exists():
        raise FileExistsError(f"Calibration output directory already exists: {output}")
    output.mkdir(parents=True)
    (output / "db_strategy_calibration.json").write_text(json.dumps(asdict(model), indent=2) + "\n")
    summaries = []
    buckets = []
    for strategy, calibration in model.strategies.items():
        summaries.append({
            "strategy": strategy.value, "observation_count": calibration.observation_count,
            "latency_mean_ms": calibration.latency_mean_ms, "latency_median_ms": calibration.latency_median_ms,
            "latency_p95_ms": calibration.latency_p95_ms, "latency_stddev_ms": calibration.latency_stddev_ms,
            "latency_model_type": calibration.latency_model.model_type, "latency_mae_ms": calibration.latency_model.mae_ms,
            "latency_rmse_ms": calibration.latency_model.rmse_ms, "recall_mean": calibration.recall.mean,
            "recall_minimum": calibration.recall.minimum, "recall_fraction_meeting_target": calibration.recall.fraction_meeting_target,
        })
        for bucket in calibration.buckets:
            buckets.append({
                "strategy": strategy.value, "bucket": bucket.bucket, "observation_count": bucket.observation_count,
                "latency_mean_ms": bucket.latency_mean_ms, "latency_median_ms": bucket.latency_median_ms,
                "conservative_feasibility": bucket.conservative_feasibility,
                "recall_mean": None if bucket.recall is None else bucket.recall.mean,
                "recall_minimum": None if bucket.recall is None else bucket.recall.minimum,
                "recall_fraction_meeting_target": None if bucket.recall is None else bucket.recall.fraction_meeting_target,
            })
    pd.DataFrame(summaries).to_csv(output / "db_strategy_calibration_summary.csv", index=False)
    pd.DataFrame(buckets).to_csv(output / "db_strategy_calibration_buckets.csv", index=False)
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description="Calibrate DB strategy summaries from saved baseline artifacts")
    parser.add_argument("--source", type=Path, default=FINAL_BASELINE_DIRECTORY)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--target-recall", type=float, default=0.95)
    args = parser.parse_args()
    model = DatabaseStrategyCalibrator(target_recall=args.target_recall).calibrate(DatabaseBaselineResults.load(args.source))
    write_calibration(model, args.output)
    print(f"Wrote calibration artifacts to {args.output}")


if __name__ == "__main__":
    main()
