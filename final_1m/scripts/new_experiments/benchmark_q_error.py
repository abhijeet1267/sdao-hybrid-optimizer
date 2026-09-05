#!/usr/bin/env python3
"""
benchmark_q_error.py — Cardinality q-Error Injection Experiment
================================================================
Measures the impact of cardinality mis-estimation on plan selection and
query latency by injecting controlled estimation errors into PostgreSQL's
planner statistics.

Method:
    1. Load a fixed dataset (default: 1M SIFT vectors).
    2. Run ANALYZE to establish a baseline.
    3. For each q-error factor f in {0.1, 0.2, 0.5, 1.0, 2.0, 5.0, 10.0}:
       a. Manipulate the planner's row-count estimate by adjusting
          n_distinct and column statistics via ALTER TABLE ... SET STATISTICS
          and by setting planner cost constants (random_page_cost,
          seq_page_cost, cpu_tuple_cost) to bias the optimizer.
       b. For each selectivity bucket × strategy, run queries and capture
          the chosen plan (via EXPLAIN), Recall@10, and latency.
    4. Reset statistics to baseline after each factor.

Note on q-error injection:
    PostgreSQL does not expose a knob to directly set "estimated rows".
    We approximate q-error injection by:
      - Lowering `default_statistics_target` to 10 and running ANALYZE
        with a tiny sample → under-estimation.
      - Setting it to 10000 for over-estimation accuracy, then using
        `SET LOCAL` cost constants to simulate the planner *believing*
        more/fewer rows qualify than actually do.
      - For precise control, we capture the baseline EXPLAIN estimate,
        then compare it with the actual row count to compute the
        *observed* q-error for each run.

Output: final/results/new_experiments/results_q_error.csv

Usage:
    python3 benchmark_q_error.py [--scale 1000000]
                                  [--queries-per-bucket 10]
                                  [--sift-dir /tmp/sift10m]
"""

import argparse
import math
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
    recall_at_k,
    run_strategy,
    truncate_items,
    write_csv,
)


def parse_args():
    p = argparse.ArgumentParser(description="q-error injection benchmark")
    p.add_argument("--scale", type=int, default=1_000_000,
                   help="Dataset size N (default: 1M)")
    p.add_argument("--queries-per-bucket", "--n-queries", type=int,
                   default=10, dest="queries_per_bucket")
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
# q-error factors and corresponding planner knob overrides
# ---------------------------------------------------------------------------
# Each entry: (label, factor, stats_target, random_page_cost, seq_page_cost)
#
# factor < 1 → under-estimation (planner thinks fewer rows match)
#   We shrink stats_target so histograms are coarser, then lower
#   random_page_cost so the planner favours index scans on small estimates.
#
# factor > 1 → over-estimation (planner thinks more rows match)
#   We raise random_page_cost so the planner sees random I/O as expensive
#   relative to sequential, biasing it toward seq-scan / bitmap plans
#   (as if more rows were qualifying).
#
# factor = 1 → baseline (accurate statistics).

Q_ERROR_CONFIGS = [
    # (label,       factor, stats_target, random_page_cost, seq_page_cost)
    ("0.1x_under",    0.1,    10,    0.5,   1.0),
    ("0.2x_under",    0.2,    10,    0.8,   1.0),
    ("0.5x_under",    0.5,    50,    1.5,   1.0),
    ("1.0x_baseline", 1.0,   100,    4.0,   1.0),
    ("2.0x_over",     2.0,   100,    8.0,   1.0),
    ("5.0x_over",     5.0,   100,   20.0,   1.0),
    ("10.0x_over",   10.0,   100,   40.0,   1.0),
]


def get_explain_estimate(conn, query_vec, category, price, in_stock, cfg):
    """
    Run EXPLAIN (no ANALYZE) on a baseline query and extract the planner's
    estimated row count for the top-level node.
    """
    op = cfg.get("distance_op", "<=>")
    tbl = cfg.get("table_name", "items")
    sql = (
        "EXPLAIN (FORMAT JSON) "
        f"SELECT id FROM {tbl} "
        "WHERE category = %s AND price <= %s AND in_stock = %s "
        f"ORDER BY embedding {op} %s LIMIT 10"
    )
    with conn.cursor() as cur:
        # Pass query_vec as ndarray so pgvector's adapter sends a `vector`
        # literal (a Python list would be sent as numeric[]).
        cur.execute(sql, (category, price, in_stock, query_vec))
        plan_json = cur.fetchone()[0]
        node = plan_json[0] if isinstance(plan_json, list) else plan_json
        plan_node = node.get("Plan", node)
        return plan_node.get("Plan Rows", 0)


def get_actual_qualifying_rows(conn, category, price, in_stock, cfg):
    """Count exact number of rows matching the filter predicate."""
    tbl = cfg.get("table_name", "items")
    with conn.cursor() as cur:
        cur.execute(
            f"SELECT COUNT(*) FROM {tbl} "
            "WHERE category = %s AND price <= %s AND in_stock = %s",
            (category, price, in_stock),
        )
        return cur.fetchone()[0]


def compute_q_error(estimated: float, actual: int) -> float:
    """q-error = max(estimated/actual, actual/estimated).  ≥ 1.0 always."""
    if actual == 0 or estimated == 0:
        return float("inf")
    return max(estimated / actual, actual / estimated)



# ---------------------------------------------------------------------------
# Apply / reset planner knobs for a given q-error configuration
# ---------------------------------------------------------------------------

def apply_q_error_config(conn, qcfg, cfg):
    """
    Set statistics target and re-ANALYZE, then adjust planner cost constants.
    This is done at the *session* level so it persists across queries in this
    connection but does not affect other sessions.
    """
    label, factor, stats_target, rpc, spc = qcfg
    tbl = cfg.get("table_name", "items")
    log.info("  Applying q-error config: %s  (stats_target=%d, "
             "random_page_cost=%.1f)", label, stats_target, rpc)
    with conn.cursor() as cur:
        # Adjust column statistics target — affects next ANALYZE
        for col in ("category", "price", "in_stock"):
            cur.execute(
                f"ALTER TABLE {tbl} ALTER COLUMN {col} "
                f"SET STATISTICS {stats_target}"
            )
        conn.commit()
        cur.execute(f"ANALYZE {tbl}")
        conn.commit()
        # Session-level planner cost overrides
        cur.execute(f"SET random_page_cost = {rpc}")
        cur.execute(f"SET seq_page_cost = {spc}")
        conn.commit()


def reset_planner_defaults(conn, cfg):
    """Reset planner cost constants and statistics targets to defaults."""
    tbl = cfg.get("table_name", "items")
    with conn.cursor() as cur:
        cur.execute("RESET random_page_cost")
        cur.execute("RESET seq_page_cost")
        for col in ("category", "price", "in_stock"):
            cur.execute(
                f"ALTER TABLE {tbl} ALTER COLUMN {col} SET STATISTICS 100"
            )
        conn.commit()
        cur.execute(f"ANALYZE {tbl}")
        conn.commit()
    log.info("  Planner defaults reset.")



# ---------------------------------------------------------------------------
# Benchmark loop
# ---------------------------------------------------------------------------

def run_benchmark(cfg, queries, N, n_queries, rng, reuse_table: bool = False):
    """
    1. Ingest N rows (skipped if reuse_table=True).
    2. For each q-error config:
       a. Apply planner overrides.
       b. For each bucket × query × strategy: run + record.
       c. Reset.
    """
    if not reuse_table:
        # --- Ingest ---
        log.info("=== Ingesting N=%d for q-error experiment ===", N)
        from _common import download_sift10m
        hdf5_path = download_sift10m("/tmp/sift10m")
        vecs = load_sift_vectors(hdf5_path, max_rows=N)
        actual_n = len(vecs)
        if actual_n < N:
            N = actual_n
        cols = generate_relational_columns(
            N, rng, n_categories=10, stock_ratio=0.5,
        )
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
    else:
        with connect(cfg) as conn:
            N = get_row_count(conn)
        log.info("Reuse-table mode: using existing table with N=%d rows", N)

    results = []

    for qcfg in Q_ERROR_CONFIGS:
        label, factor, *_ = qcfg

        with connect(cfg) as conn:
            apply_q_error_config(conn, qcfg, cfg)

            for bucket_idx, (blabel, *_rest) in enumerate(SELECTIVITY_BUCKETS):
                for qi in range(n_queries):
                    query_vec = queries[qi % len(queries)]
                    params = make_query_params_for_bucket(bucket_idx, rng, cfg)

                    # Get planner estimate before running strategies
                    estimated_rows = get_explain_estimate(
                        conn, query_vec,
                        params["category"], params["price"],
                        params["in_stock"], cfg,
                    )
                    actual_rows = get_actual_qualifying_rows(
                        conn,
                        params["category"], params["price"],
                        params["in_stock"], cfg,
                    )
                    observed_q = compute_q_error(estimated_rows, actual_rows)

                    # Brute-force ground truth
                    gt = brute_force_topk(
                        conn, query_vec,
                        params["category"], params["price"],
                        params["in_stock"], k=10, cfg=cfg,
                    )
                    if not gt:
                        continue

                    for strategy in ALL_STRATEGIES:
                        res = run_strategy(
                            conn, strategy, query_vec,
                            params["category"], params["price"],
                            params["in_stock"], explain=True, cfg=cfg,
                        )
                        recall = recall_at_k(res["ids"], gt, k=10)

                        results.append({
                            "q_error_label": label,
                            "q_error_factor": factor,
                            "observed_q_error": round(observed_q, 3),
                            "estimated_rows": estimated_rows,
                            "actual_rows": actual_rows,
                            "bucket": blabel,
                            "strategy": strategy,
                            "query_idx": qi,
                            "recall_at_10": round(recall, 4),
                            "planning_ms": round(res["planning_ms"], 3),
                            "execution_ms": round(res["execution_ms"], 3),
                            "wall_ms": round(res["wall_ms"], 3),
                            "N": N,
                        })

                log.info("  %s / %s done", label, blabel)

            reset_planner_defaults(conn, cfg)

    return results



# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    args = parse_args()
    cfg = load_config()
    rng = np.random.default_rng(args.seed)

    log.info("q-error injection experiment: N=%s, queries/bucket=%d",
             "reuse" if args.reuse_table else args.scale,
             args.queries_per_bucket)

    queries = load_queries(args, args.queries_per_bucket)

    results = run_benchmark(
        cfg, queries, args.scale,
        n_queries=args.queries_per_bucket,
        rng=rng, reuse_table=args.reuse_table,
    )

    out_path = write_csv(results, "results_q_error.csv")
    log.info("Done.  Results: %s  (%d rows)", out_path, len(results))


if __name__ == "__main__":
    main()

