"""Configuration for SDAO experiments.

Single source of truth for every experiment parameter. All scripts that run
experiments must read from this module (or a JSON file produced by
``to_json``) rather than hard-coding values. The legacy
``benchmark_hybrid_optimizer.py`` constants are preserved for compatibility but
are not the authoritative source for new experiments.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ExperimentConfig:
    """All experiment parameters in one place."""

    # Dataset
    dataset_name: str = "SIFT1M"
    dataset_size: int = 1_000_000
    vector_dimension: int = 128
    distance_metric: str = "L2"
    base_vector_path: str = "dataset/sift/sift_base.fvecs"
    query_vector_path: str = "dataset/sift/sift_query.fvecs"

    # Schema
    table_name: str = "sift_hybrid"
    predicate_columns: tuple[str, ...] = ("category", "price", "in_stock")
    n_categories: int = 10
    n_brands: int = 8  # legacy support
    price_min: int = 10
    price_max: int = 1000

    # Workload / splits
    seed: int = 20260820
    split_seed: int = 20260821
    query_count: int = 500
    calibration_count: int = 250
    tuning_count: int = 0
    test_count: int = 250
    top_k: int = 10
    repetitions_calibration: int = 1
    repetitions_heldout: int = 5
    warmup_repetitions: int = 1

    # Selectivity workload
    target_distribution: str = "uniform_5_buckets"  # see _build_queries
    selectivity_buckets: tuple[tuple[float, float], ...] = (
        (0.0, 0.05), (0.05, 0.10), (0.10, 0.25), (0.25, 0.50), (0.50, 1.01),
    )
    bucket_target_counts: tuple[int, ...] = (60, 40, 60, 60, 30)  # 250 total

    # ANN index parameters
    hnsw_m: int = 16
    hnsw_ef_construction: int = 200
    hnsw_ef_search: int = 100
    ivfflat_lists: int = 100
    ivfflat_probes: int = 10
    vector_first_budget: int = 100

    # Adaptive policy
    target_recall: float = 0.95
    admission_policy: str = "min_recall"  # min_recall, mean_recall, lcb_recall, quantile_recall
    admission_confidence: float = 0.95
    admission_quantile: float = 0.05
    min_calibration_observations: int = 1

    # Cache / ordering
    execution_order: str = "sequential_strategy"  # or "random_per_query"
    cache_condition: str = "warm"  # or "cold"

    # Output
    results_dir: str = "results/exp_default"
    experiment_label: str = "default"

    def total_queries(self) -> int:
        return self.tuning_count + self.calibration_count + self.test_count

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        # Convert tuples to lists for JSON
        for k, v in list(d.items()):
            if isinstance(v, tuple):
                d[k] = list(v)
        return d

    def to_json(self, path: Path) -> None:
        path.write_text(json.dumps(self.to_dict(), indent=2) + "\n")

    @classmethod
    def from_json(cls, path: Path) -> "ExperimentConfig":
        d = json.loads(path.read_text())
        # Convert lists back to tuples for frozen-tuple fields
        for key in ("predicate_columns", "selectivity_buckets", "bucket_target_counts"):
            if key in d and isinstance(d[key], list):
                d[key] = tuple(tuple(x) if isinstance(x, list) else x for x in d[key])
        return cls(**d)


# The original baseline configuration, frozen for reproducibility.
BASELINE_CONFIG = ExperimentConfig(
    dataset_name="SIFT1M",
    dataset_size=1_000_000,
    vector_dimension=128,
    distance_metric="L2",
    seed=20260820,
    split_seed=20260821,
    query_count=500,
    calibration_count=250,
    test_count=250,
    top_k=10,
    repetitions_calibration=1,
    repetitions_heldout=5,
    target_recall=0.95,
    admission_policy="min_recall",
    hnsw_m=16,
    hnsw_ef_construction=200,
    hnsw_ef_search=100,
    ivfflat_lists=1000,
    ivfflat_probes=10,
    vector_first_budget=100,
    selectivity_buckets=(
        (0.0, 0.05), (0.05, 0.10), (0.10, 0.25), (0.25, 0.50), (0.50, 1.01),
    ),
    bucket_target_counts=(60, 0, 37, 0, 153),  # matches observed baseline
    results_dir="results/baseline_reproduction",
    experiment_label="baseline_reproduction",
)
