#!/usr/bin/env python3
"""
benchmark_scale.py — Scale Sweep Experiment
============================================
Loads SIFT vectors (100K / 1M / 10M) into PostgreSQL/pgvector, then sweeps
across 5 selectivity buckets × 4 strategies, measuring:
  - Recall@10 vs brute-force ground truth
  - p50 / p95 / p99 wall-clock latency
  - Planning time and execution time (via EXPLAIN ANALYZE)

Output: final/results/new_experiments/results_scale.csv

Usage:
    python3 benchmark_scale.py [--scales 100000,1000000,10000000]
                                [--queries-per-bucket 20]
                                [--repeats 3]
                                [--sift-dir /tmp/sift10m]
"""

import argparse
import sys
import time
from pathlib import Path

import numpy as np

from _common import (
    ALL_STRATEGIES,
    SELECTIVITY_BUCKETS,
    brute_force_topk,
    bulk_insert,
    connect,
    create_schema,
    create_vector_indexes,
    download_sift10m,
    find_local_sift_query_path,
    generate_relational_columns,
    get_row_count,
    load_config,
    load_sift_queries,
    load_sift_queries_fvecs,
    load_sift_vectors,
    log,
    make_query_params_for_bucket,
    percentiles,
    recall_at_k,
    run_strategy,
    truncate_items,
    warm_cache,
    write_csv,
)

# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args():
    p = argparse.ArgumentParser(description="Scale sweep benchmark")
    p.add_argument(
        "--scales", type=str, default="100000,1000000,10000000",
        help="Comma-separated dataset sizes N (default: 100K,1M,10M)",
    )
    p.add_argument(
        "--queries-per-bucket", "--n-queries", type=int, default=20,
        dest="queries_per_bucket",
        help="Number of random query vectors per selectivity bucket",
    )
    p.add_argument(
        "--repeats", type=int, default=3,
        help="Number of repeated runs per (strategy, query) for percentile stats",
    )
    p.add_argument(
        "--sift-dir", type=str, default="/tmp/sift10m",
        help="Directory to download / cache SIFT-10M HDF5",
    )
    p.add_argument(
        "--seed", type=int, default=42,
        help="Random seed for reproducibility",
    )
    p.add_argument(
        "--reuse-table", action="store_true",
        help="Use the configured table (e.g. sift_hybrid) as-is; do NOT "
             "truncate/reload. Skips the scale sweep (uses table's current "
             "row count) and falls back to the local SIFT-1M .fvecs file for "
             "queries.",
    )
    return p.parse_args()


def load_queries(args, n_queries):
    """Load query vectors from local fvecs if available, else download HDF5."""
    local = find_local_sift_query_path()
    if local is not None and Path(local).exists():
        log.info("Using local SIFT query file: %s", local)
        return load_sift_queries_fvecs(local, n_queries=n_queries)
    log.info("No local SIFT query file found; downloading SIFT-10M HDF5...")
    hdf5 = download_sift10m(args.sift_dir)
    return load_sift_queries(hdf5, n_queries=n_queries)


# ---------------------------------------------------------------------------
# Data ingestion for a given scale N
# ---------------------------------------------------------------------------

def ingest_scale(cfg, hdf5_path, N: int, rng: np.random.Generator):
    """
    Truncate, reload N SIFT vectors with synthetic relational columns,
    rebuild vector indexes, and ANALYZE.
    """
    log.info("=== Ingesting N=%d ===", N)
    vecs = load_sift_vectors(hdf5_path, max_rows=N)
    actual_n = len(vecs)
    if actual_n < N:
        log.warning(
            "SIFT dataset has only %d vectors; using all of them.", actual_n
        )
        N = actual_n

    # Determine the n_categories that gives the widest selectivity range
    # We use 20 categories globally; per-bucket selectivity is controlled
    # at query time by make_query_params_for_bucket.
    cols = generate_relational_columns(N, rng, n_categories=20, stock_ratio=0.8)
    ids = np.arange(1, N + 1)

    with connect(cfg) as conn:
        truncate_items(conn)
        create_schema(conn)
        bulk_insert(
            conn, ids, vecs,
            cols["category"], cols["price"], cols["in_stock"],
        )
        log.info("Building vector indexes (this may take a while for N=%d)...", N)
        # Drop and recreate vector indexes for correct list/graph sizing
        with conn.cursor() as cur:
            cur.execute("DROP INDEX IF EXISTS hnsw_idx")
            cur.execute("DROP INDEX IF EXISTS ivfflat_idx")
            conn.commit()
        create_vector_indexes(conn)
        with conn.cursor() as cur:
            cur.execute("ANALYZE items")
            conn.commit()
        log.info("ANALYZE complete.  Row count = %d", get_row_count(conn))



# ---------------------------------------------------------------------------
# Benchmark loop
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    args = parse_args()
    cfg = load_config()
    rng = np.random.default_rng(args.seed)

    if args.reuse_table:
        # In reuse mode we run on a single scale: the current table size.
        with connect(cfg) as conn:
            n_rows = get_row_count(conn)
        scales = [n_rows]
        log.info("Reuse-table mode: scale = %d (current row count)", n_rows)
    else:
        scales = [int(s) for s in args.scales.split(",")]
    log.info("Scale sweep: N ∈ %s", scales)
    log.info("Queries per bucket: %d,  repeats: %d", args.queries_per_bucket,
             args.repeats)

    # We still need queries — try local fvecs first, else download HDF5.
    n_queries_total = args.queries_per_bucket
    queries = load_queries(args, n_queries_total)

    if not args.reuse_table:
        hdf5_path = download_sift10m(args.sift_dir)
    else:
        hdf5_path = None  # not used in reuse mode

    # If we got a local queries array, pass it through via a small adapter.
    # For simplicity, just pass `queries` and let run_benchmark use them
    # by overriding the load_sift_queries call inside.
    results = []
    for N in scales:
        if args.reuse_table:
            log.info("Reuse-table mode: skipping ingest for N=%d", N)
        else:
            ingest_scale(cfg, hdf5_path, N, rng)
        # We need to call run_benchmark-style work but with our queries array.
        results.extend(
            _run_benchmark_for_N(
                cfg, queries, N, args.queries_per_bucket, args.repeats, rng,
                cfg,  # for brute_force_topk
            )
        )

    out_path = write_csv(results, "results_scale.csv")
    log.info("Done.  Results: %s  (%d rows)", out_path, len(results))


def _run_benchmark_for_N(cfg, queries, N, n_queries, repeats, rng, _cfg):
    """
    Benchmark loop for a single N, given a pre-loaded queries array.
    Returns per-(N, bucket, strategy, query) summary rows.
    """
    results = []
    for bucket_idx, (label, *_) in enumerate(SELECTIVITY_BUCKETS):
        log.info("--- N=%d  bucket=%s ---", N, label)
        for qi in range(n_queries):
            query_vec = queries[qi % len(queries)]
            params = make_query_params_for_bucket(bucket_idx, rng, cfg)

            # Brute-force ground truth
            with connect(cfg) as conn:
                gt = brute_force_topk(
                    conn, query_vec,
                    params["category"], params["price"],
                    params["in_stock"], k=10, cfg=cfg,
                )

            if not gt:
                log.warning(
                    "  query %d: empty ground truth (no rows match "
                    "filters); skipping.", qi,
                )
                continue

            for strategy in ALL_STRATEGIES:
                wall_times = []
                planning_ms = 0.0
                execution_ms = 0.0
                recall = 0.0

                for rep in range(repeats):
                    with connect(cfg) as conn:
                        use_explain = (rep == 0)
                        res = run_strategy(
                            conn, strategy, query_vec,
                            params["category"], params["price"],
                            params["in_stock"],
                            explain=use_explain, cfg=cfg,
                        )
                        wall_times.append(res["wall_ms"])
                        if use_explain:
                            planning_ms = res["planning_ms"]
                            execution_ms = res["execution_ms"]
                            recall = recall_at_k(res["ids"], gt, k=10)

                pcts = percentiles(wall_times)
                results.append({
                    "N": N,
                    "bucket": label,
                    "strategy": strategy,
                    "query_idx": qi,
                    "recall_at_10": round(recall, 4),
                    "planning_ms": round(planning_ms, 3),
                    "execution_ms": round(execution_ms, 3),
                    "wall_p50_ms": round(pcts["p50"], 3),
                    "wall_p95_ms": round(pcts["p95"], 3),
                    "wall_p99_ms": round(pcts["p99"], 3),
                    "n_repeats": repeats,
                    "gt_size": len(gt),
                })
            log.info(
                "  query %d/%d done  [%s]",
                qi + 1, n_queries, label,
            )
    return results


if __name__ == "__main__":
    main()

