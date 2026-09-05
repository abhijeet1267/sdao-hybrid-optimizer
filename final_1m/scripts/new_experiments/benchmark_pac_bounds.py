#!/usr/bin/env python3
"""
benchmark_pac_bounds.py — PAC-Bounds Validation Experiment
===========================================================
Validates the PAC (Probably Approximately Correct) confidence bounds on
Recall@10 by running each (strategy × selectivity bucket) query across
T independent random seeds, computing empirical Recall@10 for each seed,
and then deriving both:
  - Empirical confidence intervals (bootstrap percentile)
  - Theoretical Bernstein PAC bounds

If the PAC bound is valid, the empirical mean Recall@10 should fall
within the Bernstein bound with probability ≥ (1 − δ).

Method:
    1. Load a fixed dataset (default: 1M SIFT vectors).
    2. For T = 30 seeds:
       a. Re-generate relational columns with a different RNG seed
          (same vectors, different category/price/in_stock).
       b. Re-ANALYZE so the planner sees fresh statistics.
       c. For each bucket × strategy: run n_queries queries, compute
          per-query Recall@10, record the mean Recall@10 for this seed.
    3. Across all T seeds, compute:
       - Mean and std of Recall@10
       - Empirical 95% CI (percentile bootstrap)
       - Bernstein PAC bound width at confidence δ = 0.05

Output: final/results/new_experiments/results_pac.csv

Usage:
    python3 benchmark_pac_bounds.py [--scale 1000000]
                                     [--n-seeds 30]
                                     [--queries-per-bucket 20]
                                     [--sift-dir /tmp/sift10m]
"""

import argparse
import math
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
    recall_at_k,
    run_strategy,
    truncate_items,
    write_csv,
)

# Module-level cache for N (set by main before run_seed_workload is called)
N_GLOBAL = None


def parse_args():
    p = argparse.ArgumentParser(description="PAC-bounds benchmark")
    p.add_argument("--scale", type=int, default=1_000_000,
                   help="Dataset size N (default: 1M)")
    p.add_argument("--n-seeds", type=int, default=30,
                   help="Number of independent RNG seeds T (default: 30)")
    p.add_argument("--queries-per-bucket", "--n-queries", type=int,
                   default=20, dest="queries_per_bucket")
    p.add_argument("--sift-dir", type=str, default="/tmp/sift10m")
    p.add_argument("--base-seed", type=int, default=1000,
                   help="Starting seed (seeds will be base..base+T-1)")
    p.add_argument("--delta", type=float, default=0.05,
                   help="PAC confidence parameter δ (default: 0.05)")
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
# Bernstein PAC bound
# ---------------------------------------------------------------------------

def bernstein_bound(samples: list[float], delta: float) -> float:
    """
    Compute the half-width of the one-sided Bernstein PAC bound
    for the mean of bounded random variables X_i ∈ [0, 1]:

        P( |mean - E[X]| <= B ) >= 1 - delta

    where
        B = sqrt( 2 * v_n * ln(3/delta) / n )
            + 3 * R * ln(3/delta) / (n - 1)
    and v_n is the sample variance, R is the range bound (here 1.0),
    and n is the sample count.

    Returns the bound half-width B (a non-negative float).
    """
    n = len(samples)
    if n < 2:
        return float("nan")
    arr = np.array(samples, dtype=np.float64)
    mean = float(arr.mean())
    var = float(arr.var(ddof=1))
    R = 1.0  # Recall@10 ∈ [0, 1]
    log_term = math.log(3.0 / delta)
    bound = math.sqrt(2.0 * var * log_term / n) + \
        (3.0 * R * log_term) / (n - 1)
    return bound


def empirical_ci(samples: list[float], alpha: float = 0.05) -> tuple:
    """
    Percentile bootstrap CI for the mean.
    Returns (lower, upper) for confidence level 1 - alpha.
    """
    if len(samples) < 2:
        return (float("nan"), float("nan"))
    arr = np.array(samples, dtype=np.float64)
    # Non-parametric bootstrap, 2000 resamples
    rng = np.random.default_rng(0)
    boot_means = np.empty(2000)
    for i in range(2000):
        idx = rng.integers(0, len(arr), size=len(arr))
        boot_means[i] = arr[idx].mean()
    lo = float(np.percentile(boot_means, 100 * alpha / 2))
    hi = float(np.percentile(boot_means, 100 * (1 - alpha / 2)))
    return (lo, hi)



# ---------------------------------------------------------------------------
# Per-seed ingest (different relational columns each seed)
# ---------------------------------------------------------------------------

def reload_with_seed(cfg, hdf5_path, N, seed: int, reuse_table: bool = False):
    """
    Truncate items, re-insert SIFT vectors with fresh relational columns
    generated under the given seed, rebuild vector indexes, ANALYZE.
    The vectors themselves are deterministic (from HDF5), but the
    category/price/in_stock columns change per seed.

    When reuse_table=True, this is a no-op (we're using the existing
    sift_hybrid data as-is).
    """
    if reuse_table:
        return
    rng = np.random.default_rng(seed)
    vecs = load_sift_vectors(hdf5_path, max_rows=N)
    actual_n = len(vecs)
    if actual_n < N:
        N = actual_n
    cols = generate_relational_columns(N, rng, n_categories=10, stock_ratio=0.5)
    ids = np.arange(1, N + 1)
    tbl = cfg.get("table_name", "items")

    with connect(cfg) as conn:
        truncate_items(conn)
        bulk_insert(conn, ids, vecs, cols["category"], cols["price"],
                    cols["in_stock"])
        with conn.cursor() as cur:
            cur.execute(f"ANALYZE {tbl}")
            conn.commit()


def ensure_schema(cfg):
    """Create the table and vector indexes if missing."""
    with connect(cfg) as conn:
        create_schema(conn)
        # Vector indexes (idempotent — uses opclass matching distance_op)
        create_vector_indexes(conn)



# ---------------------------------------------------------------------------
# Per-seed workload
# ---------------------------------------------------------------------------

def run_seed_workload(cfg, queries, n_queries, seed: int,
                       reuse_table: bool = False) -> dict:
    """
    For one RNG seed:
        1. Reload data with that seed (skipped in reuse mode)
        2. For each bucket × strategy: run n_queries queries, compute
           per-query Recall@10.
    Returns: dict keyed by (bucket, strategy) -> list[recall] of length n_queries.
    """
    # The reload is done OUTSIDE the per-bucket/strategy loop in main,
    # because reloading a million rows is slow.  We accept a no-op when
    # reuse_table=True.
    rng = np.random.default_rng(seed)
    recalls = {}

    with connect(cfg) as conn:
        for bucket_idx, (blabel, *_) in enumerate(SELECTIVITY_BUCKETS):
            for strategy in ALL_STRATEGIES:
                rec_list = []
                for qi in range(n_queries):
                    qvec = queries[qi % len(queries)]
                    params = make_query_params_for_bucket(bucket_idx, rng, cfg)

                    gt = brute_force_topk(
                        conn, qvec,
                        params["category"], params["price"],
                        params["in_stock"], k=10, cfg=cfg,
                    )
                    if not gt:
                        rec_list.append(0.0)
                        continue

                    res = run_strategy(
                        conn, strategy, qvec,
                        params["category"], params["price"],
                        params["in_stock"], explain=False, cfg=cfg,
                    )
                    rec_list.append(recall_at_k(res["ids"], gt, k=10))
                recalls[(blabel, strategy)] = rec_list

    return recalls



# ---------------------------------------------------------------------------
# Aggregate per-seed results into PAC-bound table
# ---------------------------------------------------------------------------

def aggregate_pac(seed_recalls: list[dict], delta: float) -> list[dict]:
    """
    For each (bucket, strategy) across T seeds, compute:
        - per-seed mean Recall@10 (one value per seed)
        - overall mean, std, min, max
        - empirical 95% CI (bootstrap)
        - Bernstein PAC half-width
        - whether empirical CI is contained in PAC bound
    """
    keys = sorted(seed_recalls[0].keys())  # (bucket, strategy) pairs
    rows = []

    for key in keys:
        blabel, strategy = key
        # per-seed mean
        per_seed_means = []
        per_query_all = []
        for s in seed_recalls:
            recs = s[key]
            per_seed_means.append(float(np.mean(recs)))
            per_query_all.extend(recs)

        mean_val = float(np.mean(per_seed_means))
        std_val = float(np.std(per_seed_means, ddof=1)) \
            if len(per_seed_means) > 1 else 0.0
        min_val = float(np.min(per_seed_means))
        max_val = float(np.max(per_seed_means))

        # PAC bound on per-seed mean
        bern_half = bernstein_bound(per_seed_means, delta)
        # PAC bound on per-query Recall@10
        bern_half_q = bernstein_bound(per_query_all, delta)

        ci_lo, ci_hi = empirical_ci(per_seed_means, alpha=0.05)
        ci_width = ci_hi - ci_lo
        pac_contains = (
            (mean_val - bern_half <= ci_lo) and
            (mean_val + bern_half >= ci_hi)
        )

        rows.append({
            "bucket": blabel,
            "strategy": strategy,
            "n_seeds": len(seed_recalls),
            "queries_per_seed": len(per_query_all) // len(seed_recalls),
            "mean_recall": round(mean_val, 4),
            "std_recall": round(std_val, 4),
            "min_recall": round(min_val, 4),
            "max_recall": round(max_val, 4),
            "ci95_lower": round(ci_lo, 4),
            "ci95_upper": round(ci_hi, 4),
            "ci95_width": round(ci_width, 4),
            "bernstein_bound_seed_mean": round(bern_half, 4),
            "bernstein_bound_per_query": round(bern_half_q, 4),
            "ci_within_pac": bool(pac_contains),
            "delta": delta,
        })

    return rows



# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    global N_GLOBAL
    args = parse_args()
    cfg = load_config()
    rng = np.random.default_rng(args.base_seed)

    # Step 1: load queries (local fvecs or downloaded HDF5)
    queries = load_queries(args, args.queries_per_bucket)

    # Step 2: ensure schema and indexes exist once
    log.info("Ensuring schema and vector indexes ...")
    ensure_schema(cfg)

    if args.reuse_table:
        with connect(cfg) as conn:
            N_GLOBAL = get_row_count(conn)
        log.info("Reuse-table mode: N_GLOBAL = %d (from existing table)", N_GLOBAL)
    else:
        N_GLOBAL = args.scale
        hdf5_path = download_sift10m(args.sift_dir)

    log.info("PAC-bounds experiment: N=%d, T=%d seeds, queries/bucket=%d, δ=%.2f",
             N_GLOBAL, args.n_seeds, args.queries_per_bucket, args.delta)

    # Step 3: Run workload for each seed
    seed_recalls = []
    for s_idx in range(args.n_seeds):
        seed = args.base_seed + s_idx
        log.info("=== Seed %d / %d  (seed=%d) ===",
                 s_idx + 1, args.n_seeds, seed)
        if not args.reuse_table:
            # Reload with the seed (synthesise fresh relational columns)
            reload_with_seed(cfg, hdf5_path, N_GLOBAL, seed,
                             reuse_table=False)
        recalls = run_seed_workload(
            cfg, queries, args.queries_per_bucket, seed,
            reuse_table=args.reuse_table,
        )
        seed_recalls.append(recalls)

    # Step 4: Aggregate into PAC table
    log.info("Aggregating PAC bounds across %d seeds ...", args.n_seeds)
    rows = aggregate_pac(seed_recalls, args.delta)

    # Step 5: Write CSV
    out_path = write_csv(rows, "results_pac.csv")
    log.info("Done.  Results: %s  (%d rows)", out_path, len(rows))

    # Also dump the raw per-seed data for transparency
    raw_rows = []
    for s_idx, recalls in enumerate(seed_recalls):
        seed = args.base_seed + s_idx
        for (blabel, strategy), rec_list in recalls.items():
            for qi, r in enumerate(rec_list):
                raw_rows.append({
                    "seed": seed,
                    "bucket": blabel,
                    "strategy": strategy,
                    "query_idx": qi,
                    "recall_at_10": r,
                })
    raw_path = write_csv(raw_rows, "results_pac_raw.csv")
    log.info("Raw per-query results: %s  (%d rows)", raw_path, len(raw_rows))


if __name__ == "__main__":
    main()

