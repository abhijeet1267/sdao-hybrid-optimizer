#!/usr/bin/env python3
"""
benchmark_cold_cache.py — Cold-Cache vs Hot-Cache I/O Experiment
=================================================================
Compares query latency under two buffer-pool states:
  - HOT:  after pg_prewarm has loaded the table into shared_buffers
  - COLD: after a full Docker container restart (clears shared_buffers
          and macOS filesystem cache associated with the container)

For each cache state × selectivity bucket × strategy, we run a fixed set
of query vectors and record wall-clock latency, planning time, execution
time, and Recall@10 vs brute-force ground truth.

Environment:
    macOS (Apple Silicon) host running PostgreSQL 17.10/pgvector inside
    a Docker container.  Cold-cache reset is performed via:
        docker restart <container_name>
    followed by a reconnect wait.

Output: final/results/new_experiments/results_cold_cache.csv

Usage:
    python3 benchmark_cold_cache.py [--scale 1000000]
                                     [--queries-per-bucket 10]
                                     [--repeats 5]
                                     [--sift-dir /tmp/sift10m]
"""

import argparse
import time
from pathlib import Path

import numpy as np

from _common import (
    ALL_STRATEGIES,
    SELECTIVITY_BUCKETS,
    brute_force_topk,
    bulk_insert,
    cold_cache_reset,
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


def parse_args():
    p = argparse.ArgumentParser(description="Cold-cache benchmark")
    p.add_argument("--scale", type=int, default=1_000_000,
                   help="Dataset size N (default: 1M)")
    p.add_argument("--queries-per-bucket", "--n-queries", type=int,
                   default=10, dest="queries_per_bucket")
    p.add_argument("--repeats", type=int, default=5,
                   help="Repeated runs per query for latency percentiles")
    p.add_argument("--sift-dir", type=str, default="/tmp/sift10m")
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--reuse-table", action="store_true",
                   help="Use the configured table as-is; do NOT truncate/reload")
    return p.parse_args()


def load_queries(args, n_queries):
    local = find_local_sift_query_path()
    if local is not None and Path(local).exists():
        log.info("Using local SIFT query file: %s", local)
        return load_sift_queries_fvecs(local, n_queries=n_queries)
    hdf5 = download_sift10m(args.sift_dir)
    return load_sift_queries(hdf5, n_queries=n_queries)


# ---------------------------------------------------------------------------
# Ingest data (identical to scale benchmark, fixed at one N)
# ---------------------------------------------------------------------------

def ingest_data(cfg, hdf5_path, N, rng, reuse_table: bool = False):
    """Load N rows, create indexes, ANALYZE.  No-op in reuse mode."""
    if reuse_table:
        with connect(cfg) as conn:
            n = get_row_count(conn)
        log.info("Reuse-table mode: skipping ingest.  Existing N=%d", n)
        return
    log.info("=== Ingesting N=%d for cold-cache experiment ===", N)
    vecs = load_sift_vectors(hdf5_path, max_rows=N)
    actual_n = len(vecs)
    if actual_n < N:
        N = actual_n
    cols = generate_relational_columns(N, rng, n_categories=10, stock_ratio=0.5)
    ids = np.arange(1, N + 1)

    with connect(cfg) as conn:
        truncate_items(conn)
        create_schema(conn)
        bulk_insert(conn, ids, vecs, cols["category"], cols["price"],
                    cols["in_stock"])
        with conn.cursor() as cur:
            cur.execute("DROP INDEX IF EXISTS hnsw_idx")
            cur.execute("DROP INDEX IF EXISTS ivfflat_idx")
            conn.commit()
        create_vector_indexes(conn)
        with conn.cursor() as cur:
            cur.execute(f"ANALYZE {cfg['table_name']}")
            conn.commit()
        log.info("Ingestion complete.  Row count = %d", get_row_count(conn))


# ---------------------------------------------------------------------------
# Pre-build the query workload (so both hot & cold phases use the same set)
# ---------------------------------------------------------------------------

def build_workload(cfg, queries, n_queries, rng):
    """
    Return a list of dicts, each containing:
        query_vec, category, price, in_stock, bucket_label, gt_ids
    Ground truths are computed once so they are identical for hot & cold.
    """
    workload = []

    with connect(cfg) as conn:
        for bucket_idx, (blabel, *_) in enumerate(SELECTIVITY_BUCKETS):
            for qi in range(n_queries):
                qvec = queries[qi % len(queries)]
                params = make_query_params_for_bucket(bucket_idx, rng, cfg)
                gt = brute_force_topk(
                    conn, qvec,
                    params["category"], params["price"],
                    params["in_stock"], k=10, cfg=cfg,
                )
                if not gt:
                    continue
                workload.append({
                    "query_vec": qvec,
                    "category": params["category"],
                    "price": params["price"],
                    "in_stock": params["in_stock"],
                    "bucket_label": blabel,
                    "query_idx": qi,
                    "gt_ids": gt,
                })

    log.info("Workload built: %d query instances", len(workload))
    return workload



# ---------------------------------------------------------------------------
# Run one phase (hot or cold) over the entire workload
# ---------------------------------------------------------------------------

def run_phase(cfg, workload, cache_state: str, repeats: int):
    """
    Execute every (workload_item × strategy) with `repeats` repetitions.
    Returns a list of result dicts.
    """
    results = []

    for wi, item in enumerate(workload):
        for strategy in ALL_STRATEGIES:
            wall_times = []
            planning_ms = 0.0
            execution_ms = 0.0
            recall = 0.0

            for rep in range(repeats):
                with connect(cfg) as conn:
                    use_explain = (rep == 0)
                    res = run_strategy(
                        conn, strategy, item["query_vec"],
                        item["category"], item["price"],
                        item["in_stock"], explain=use_explain, cfg=cfg,
                    )
                    wall_times.append(res["wall_ms"])
                    if use_explain:
                        planning_ms = res["planning_ms"]
                        execution_ms = res["execution_ms"]
                        recall = recall_at_k(
                            res["ids"], item["gt_ids"], k=10,
                        )

            pcts = percentiles(wall_times)
            results.append({
                "cache_state": cache_state,
                "bucket": item["bucket_label"],
                "strategy": strategy,
                "query_idx": item["query_idx"],
                "recall_at_10": round(recall, 4),
                "planning_ms": round(planning_ms, 3),
                "execution_ms": round(execution_ms, 3),
                "wall_p50_ms": round(pcts["p50"], 3),
                "wall_p95_ms": round(pcts["p95"], 3),
                "wall_p99_ms": round(pcts["p99"], 3),
                "n_repeats": repeats,
                "gt_size": len(item["gt_ids"]),
            })

        if (wi + 1) % 10 == 0:
            log.info("  [%s] %d / %d workload items done",
                     cache_state, wi + 1, len(workload))

    return results


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    args = parse_args()
    cfg = load_config()
    rng = np.random.default_rng(args.seed)

    log.info("Cold-cache experiment: N=%s, queries/bucket=%d, repeats=%d",
             "reuse" if args.reuse_table else args.scale,
             args.queries_per_bucket, args.repeats)

    queries = load_queries(args, args.queries_per_bucket)

    # Step 1: Ingest data (no-op in reuse mode)
    hdf5_path = None
    if not args.reuse_table:
        hdf5_path = download_sift10m(args.sift_dir)
    ingest_data(cfg, hdf5_path, args.scale, rng,
                reuse_table=args.reuse_table)

    # Step 2: Build workload (with ground truth)
    workload = build_workload(cfg, queries, args.queries_per_bucket, rng)

    all_results = []

    # --- Phase 1: HOT cache ---
    log.info("=== Phase 1: HOT cache ===")
    with connect(cfg) as conn:
        warm_cache(conn, cfg=cfg)
    hot_results = run_phase(cfg, workload, "hot", args.repeats)
    all_results.extend(hot_results)
    log.info("HOT phase complete: %d result rows", len(hot_results))

    # --- Phase 2: COLD cache (Docker restart or 'purge') ---
    log.info("=== Phase 2: COLD cache ===")
    cold_cache_reset(cfg)
    cold_results = run_phase(cfg, workload, "cold", args.repeats)
    all_results.extend(cold_results)
    log.info("COLD phase complete: %d result rows", len(cold_results))

    # --- Phase 3: Second HOT pass (to show warm-up effect) ---
    log.info("=== Phase 3: HOT cache (second pass) ===")
    with connect(cfg) as conn:
        warm_cache(conn, cfg=cfg)
    hot2_results = run_phase(cfg, workload, "hot_2nd", args.repeats)
    all_results.extend(hot2_results)
    log.info("HOT (2nd) phase complete: %d result rows", len(hot2_results))

    out_path = write_csv(all_results, "results_cold_cache.csv")
    log.info("Done.  Results: %s  (%d rows)", out_path, len(all_results))


if __name__ == "__main__":
    main()

