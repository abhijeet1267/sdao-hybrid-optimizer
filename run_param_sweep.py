"""Full parameter sweep experiment on the 200K SIFT1M subset."""
import json
import time
from collections import defaultdict
from pathlib import Path
from typing import Any
import numpy as np
import pandas as pd
import psycopg2

VECTOR_DIMENSION = 128
DATASET_SIZE = 200_000
TABLE_NAME = "sift_hybrid_200k"
QUERY_COUNT = 500
CALIBRATION_COUNT = 250
TEST_COUNT = 250
TOP_K = 10
REPETITIONS = 5
TARGET_RECALL = 0.95
STRATEGIES = ("SQL_FIRST", "VECTOR_FIRST_HNSW", "HNSW_HYBRID", "IVFFLAT_HYBRID")
BUCKETS = ((0.0, 0.05), (0.05, 0.10), (0.10, 0.25), (0.25, 0.50), (0.50, 1.01))
CATEGORIES = tuple(f"category_{i:02d}" for i in range(10))
VECTOR_PATH = "dataset/sift/sift_base.fvecs"
VECTOR_SUBSET_SIZE = 200_000

# Predefined parameter grids
HNSW_EF_SEARCH_GRID = [50, 100, 200, 400]
IVFFLAT_PROBES_GRID = [1, 10, 50, 200]


def read_fvecs_subset(path, dim, n):
    raw = np.fromfile(path, dtype=np.int32)
    width = dim + 1
    records = raw.reshape(-1, width)[:n]
    return records[:, 1:].view(np.float32).reshape(-1, dim)


def make_queries(vectors, seed):
    rng = np.random.default_rng(seed)
    queries = []
    for qid in range(QUERY_COUNT):
        target = float(rng.uniform(0.01, 1.0))
        category = str(rng.choice(CATEGORIES))
        in_stock = bool(rng.integers(0, 2))
        price_limit = float(np.clip(10.0 + 990.0 * target, 10.01, 1000.0))
        vec = vectors[int(rng.integers(0, len(vectors)))].copy()
        queries.append((qid, vec, category, price_limit, in_stock, target))
    return queries


def split_queries(queries, seed):
    rng = np.random.default_rng(seed)
    order = rng.permutation(len(queries))
    cal_ids = set(int(v) for v in order[:CALIBRATION_COUNT])
    cal = [q for q in queries if q[0] in cal_ids]
    test = [q for q in queries if q[0] not in cal_ids]
    return cal, test


def bucket_for(sel):
    for lo, hi in BUCKETS:
        if lo <= sel < hi:
            return f"[{lo:.2f},{min(hi,1.0):.2f})"
    return "[0.50,1.00]"


def recall_at_10(rids, ref):
    ref = set(ref)
    return 1.0 if not ref else len(set(rids) & ref) / len(ref)


def vec_literal(v):
    return "[" + ",".join(repr(float(x)) for x in v) + "]"


def build_stmt(q, strat, vl, ef_search, probes):
    cid, vec, cat, pl, st, _ = q
    if strat == "SQL_FIRST":
        return (
            f"SELECT id FROM {TABLE_NAME} WHERE (category = %s AND price < %s AND in_stock = %s) "
            "ORDER BY embedding <-> %s::vector, id LIMIT %s",
            (cat, pl, st, vl, TOP_K),
            {"enable_indexscan": "off"},
        )
    if strat == "HNSW_HYBRID":
        return (
            f"SELECT id FROM {TABLE_NAME} WHERE (category = %s AND price < %s AND in_stock = %s) "
            "ORDER BY embedding <-> %s::vector LIMIT %s",
            (cat, pl, st, vl, TOP_K),
            {"hnsw.ef_search": ef_search, "ivfflat.probes": 1000},
        )
    if strat == "IVFFLAT_HYBRID":
        return (
            f"SELECT id FROM {TABLE_NAME} WHERE (category = %s AND price < %s AND in_stock = %s) "
            "ORDER BY embedding <-> %s::vector LIMIT %s",
            (cat, pl, st, vl, TOP_K),
            {"ivfflat.probes": probes, "hnsw.ef_search": 1000},
        )
    if strat == "VECTOR_FIRST_HNSW":
        return (
            f"WITH candidates AS MATERIALIZED ("
            f"SELECT id, embedding <-> %s::vector AS distance "
            f"FROM {TABLE_NAME} ORDER BY embedding <-> %s::vector LIMIT 100) "
            f"SELECT candidates.id FROM candidates JOIN {TABLE_NAME} item ON item.id = candidates.id "
            f"WHERE (category = %s AND price < %s AND in_stock = %s) "
            "ORDER BY candidates.distance, candidates.id LIMIT %s",
            (vl, vl, cat, pl, st, TOP_K),
            {"hnsw.ef_search": ef_search, "ivfflat.probes": 1000},
        )
    raise ValueError(strat)


def exec_once(conn, q, strat, ef_search, probes, ref=None):
    vl = vec_literal(q[1])
    stmt, params, settings = build_stmt(q, strat, vl, ef_search, probes)
    with conn.cursor() as c:
        for k, v in settings.items():
            c.execute("SELECT set_config(%s, %s, true)", (k, str(v)))
        t0 = time.perf_counter_ns()
        c.execute(stmt, params)
        rids = [int(r[0]) for r in c.fetchall()]
        lat = (time.perf_counter_ns() - t0) / 1_000_000
    rec = recall_at_10(rids, ref) if ref is not None else 1.0
    return rids, lat, rec


def est_sel(conn, q):
    cid, vec, cat, pl, st, _ = q
    with conn.cursor() as c:
        c.execute(
            f"EXPLAIN (FORMAT JSON) SELECT id FROM {TABLE_NAME} "
            f"WHERE (category = %s AND price < %s AND in_stock = %s)",
            (cat, pl, st),
        )
        row = c.fetchone()
    plan = row[0] if not isinstance(row[0], str) else json.loads(row[0])
    return float(plan[0]["Plan"]["Plan Rows"]) / DATASET_SIZE
def run_calibration(conn, cal_q, ef_search, probes):
    obs = []
    for q in cal_q:
        sel = est_sel(conn, q)
        bucket = bucket_for(sel)
        ref = None
        for strat in STRATEGIES:
            rids, lat, rec = exec_once(conn, q, strat, ef_search, probes, ref=ref)
            if strat == "SQL_FIRST" and ref is None:
                ref = rids
                rec = 1.0
            obs.append({
                "query_id": q[0], "strategy": strat, "bucket": bucket,
                "latency_ms": lat, "recall_at_10": rec,
            })
    return obs


def run_heldout(conn, test_q, ef_search, probes):
    per_query = []
    raw = []
    for q in test_q:
        sel = est_sel(conn, q)
        bucket = bucket_for(sel)
        for strat in STRATEGIES:
            exec_once(conn, q, strat, ef_search, probes)
        ref = None
        runs = {s: [] for s in STRATEGIES}
        for rep in range(REPETITIONS):
            for strat in STRATEGIES:
                rids, lat, rec = exec_once(conn, q, strat, ef_search, probes, ref=ref)
                if strat == "SQL_FIRST" and ref is None:
                    ref = rids
                    rec = 1.0
                runs[strat].append((lat, rec))
                raw.append({
                    "query_id": q[0], "strategy": strat, "bucket": bucket,
                    "latency_ms": lat, "recall_at_10": rec, "repetition": rep,
                })
        for strat in STRATEGIES:
            lats = [r[0] for r in runs[strat]]
            recs = [r[1] for r in runs[strat]]
            per_query.append({
                "query_id": q[0], "strategy": strat,
                "median_latency_ms": float(np.median(lats)),
                "recall_at_10": float(np.median(recs)),
                "estimated_selectivity": sel, "bucket": bucket,
            })
    return per_query, raw


def summarize(per_query, ef, probes):
    pq = pd.DataFrame(per_query)
    rows = []
    for strat, g in pq.groupby("strategy"):
        lat = g["median_latency_ms"]
        rec = g["recall_at_10"]
        rows.append({
            "strategy": strat,
            "ef_search": ef, "probes": probes,
            "n": len(g),
            "mean_latency_ms": float(lat.mean()),
            "median_latency_ms": float(lat.median()),
            "p95_latency_ms": float(lat.quantile(0.95)),
            "std_latency_ms": float(lat.std()),
            "mean_recall_at_10": float(rec.mean()),
            "min_recall_at_10": float(rec.min()),
            "p05_recall": float(rec.quantile(0.05)),
            "fraction_recall_at_least_095": float((rec >= TARGET_RECALL).mean()),
        })
    return pd.DataFrame(rows)
def main():
    out_dir = Path("results/exp_200k/param_sweep")
    out_dir.mkdir(parents=True, exist_ok=True)
    print("Loading 200K SIFT1M subset...")
    vectors = read_fvecs_subset(VECTOR_PATH, VECTOR_DIMENSION, VECTOR_SUBSET_SIZE)
    queries = make_queries(vectors, 20260820)
    cal_q, test_q = split_queries(queries, 20260821)
    print(f"Workload: {len(cal_q)} cal, {len(test_q)} test")
    conn = psycopg2.connect(host="localhost", user="sdao", dbname="sdao")
    print("\n=== Running one-time calibration (ef_search=200, probes=10) ===")
    cal_obs = run_calibration(conn, cal_q, ef_search=200, probes=10)
    pd.DataFrame(cal_obs).to_csv(out_dir / "calibration_observations.csv", index=False)
    print(f"Calibration: {len(cal_obs)} observations")
    sweep_results = []
    for ef in HNSW_EF_SEARCH_GRID:
        for probes in IVFFLAT_PROBES_GRID:
            label = f"ef{ef}_probes{probes}"
            print(f"\n=== Held-out: ef_search={ef}, probes={probes} ===")
            t0 = time.time()
            per_query, raw = run_heldout(conn, test_q, ef, probes)
            elapsed = time.time() - t0
            print(f"  {len(per_query)} per-query records in {elapsed:.1f}s")
            summary = summarize(per_query, ef, probes)
            sweep_results.append(summary)
            config_dir = out_dir / f"config_{label}"
            config_dir.mkdir(exist_ok=True)
            pd.DataFrame(per_query).to_csv(config_dir / "per_query.csv", index=False)
            pd.DataFrame(raw).to_csv(config_dir / "raw.csv", index=False)
            summary.to_csv(config_dir / "summary.csv", index=False)
            ann = summary[summary["strategy"].isin(["HNSW_HYBRID", "IVFFLAT_HYBRID", "VECTOR_FIRST_HNSW"])]
            print(ann[["strategy", "mean_latency_ms", "p95_latency_ms", "mean_recall_at_10", "fraction_recall_at_least_095"]].to_string(index=False))
    combined = pd.concat(sweep_results, ignore_index=True)
    combined.to_csv(out_dir / "sweep_summary.csv", index=False)
    print(f"\n=== Sweep complete: {len(combined)} rows ===")
    conn.close()


if __name__ == "__main__":
    main()
