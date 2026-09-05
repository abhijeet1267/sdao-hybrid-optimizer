"""Top-level experiment driver. Reads a config JSON or builds a config in-code,
runs the benchmark, writes the reproducibility package.

Usage:
    venv/bin/python run_experiment.py --config path/to/config.json
    venv/bin/python run_experiment.py --quick   # smoke test
"""
import argparse
import json
import os
import sys
from pathlib import Path

# Make the project root importable
ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

os.environ.setdefault("PGHOST", "localhost")
os.environ.setdefault("PGUSER", "sdao")
os.environ.setdefault("PGDATABASE", "sdao")

import numpy as np
import psycopg2

from sdao_experiments.config import ExperimentConfig
from sdao_experiments.runner import run_experiment
from sdao_experiments.workload import read_fvecs


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, help="ExperimentConfig JSON")
    parser.add_argument("--quick", action="store_true",
                        help="Run a 30-query smoke test on the small table")
    parser.add_argument("--baseline", action="store_true",
                        help="Reproduce the baseline (500 queries, 3 buckets only)")
    args = parser.parse_args()

    if args.quick:
        cfg = ExperimentConfig(
            dataset_size=10_000,
            table_name="sift_hybrid_small",
            query_count=15,
            calibration_count=8,
            test_count=7,
            bucket_target_counts=(3, 0, 3, 3, 3),
            seed=42, split_seed=43,
            results_dir="results/exp_quick",
            experiment_label="quick",
        )
    elif args.baseline:
        # Reproduce the baseline distribution: 3 buckets only
        cfg = ExperimentConfig(
            query_count=500, calibration_count=250, test_count=250,
            bucket_target_counts=(60, 0, 37, 0, 153),
            hnsw_ef_search=100, ivfflat_probes=10,
            vector_first_budget=100,
            admission_policy="min_recall",
            results_dir="results/exp_baseline_reproduction",
            experiment_label="baseline_reproduction",
        )
        Path(cfg.results_dir).mkdir(parents=True, exist_ok=True)
    elif args.config:
        cfg = ExperimentConfig.from_json(args.config)
    else:
        parser.error("Provide --config, --quick, or --baseline")

    cfg.to_json(Path(cfg.results_dir) / "config.json")
    print(f"Config: {cfg.results_dir}/config.json")
    print(f"Total queries: {cfg.total_queries()} = "
          f"{cfg.tuning_count} tuning + {cfg.calibration_count} cal + "
          f"{cfg.test_count} test")
    print(f"Admission policy: {cfg.admission_policy}")
    print(f"ANN: hnsw_ef_search={cfg.hnsw_ef_search}, "
          f"ivfflat_probes={cfg.ivfflat_probes}, "
          f"vf_budget={cfg.vector_first_budget}")

    # Load query vectors
    if cfg.table_name == "sift_hybrid_small":
        query_vectors = np.random.default_rng(0).standard_normal((100, cfg.vector_dimension)).astype(np.float32)
    else:
        qpath = Path(cfg.query_vector_path if hasattr(cfg, 'query_vector_path') else 'dataset/sift/sift_query.fvecs')
        query_vectors = read_fvecs(qpath, cfg.vector_dimension)
    print(f"Loaded {len(query_vectors)} query vectors")

    # Connect
    conn = psycopg2.connect(host="localhost", user="sdao", dbname="sdao")
    try:
        result = run_experiment(cfg, conn, query_vectors)
    finally:
        conn.close()
    print(f"Experiment complete: {cfg.results_dir}")


if __name__ == "__main__":
    main()
