"""Faithful baseline reproduction."""
from __future__ import annotations
import json, time
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any
import numpy as np
import pandas as pd
import psycopg2

VECTOR_DIMENSION = 128
DATASET_SIZE = 1_000_000
QUERY_COUNT = 500
CALIBRATION_COUNT = 250
TEST_COUNT = 250
TOP_K = 10
REPETITIONS = 5
TARGET_RECALL = 0.95
STRATEGIES = ("SQL_FIRST", "VECTOR_FIRST_HNSW", "HNSW_HYBRID", "IVFFLAT_HYBRID")
if STRATEGIES[0] != "SQL_FIRST":
    raise RuntimeError("STRATEGIES[0] must be 'SQL_FIRST'")
BUCKETS = ((0.0, 0.05), (0.05, 0.10), (0.10, 0.25), (0.25, 0.50), (0.50, 1.01))
CATEGORIES = tuple(f"category_{index:02d}" for index in range(10))
DEFAULT_VECTOR_PATH = "dataset/sift/sift_base.fvecs"


@dataclass(frozen=True)
class BaselineQuery:
    query_id: int
    vector: np.ndarray
    category: str
    price_limit: float
    in_stock: bool
    target_selectivity: float

    @property
    def predicate_sql(self) -> str:
        if self.target_selectivity < 0.25:
            return "(category = %s AND price < %s AND in_stock = %s)"
        if self.target_selectivity < 0.60:
            return "((category = %s AND price < %s) OR in_stock = %s)"
        return "(category = %s OR price < %s OR in_stock = %s)"

    @property
    def predicate_params(self) -> tuple[Any, ...]:
        return self.category, self.price_limit, self.in_stock


def read_fvecs(path, dim):
    raw = np.fromfile(path, dtype=np.int32)
    width = dim + 1
    if raw.size % width:
        raise ValueError(f"Malformed .fvecs: {path}")
    records = raw.reshape(-1, width)
    if not np.all(records[:, 0] == dim):
        raise ValueError(f"Expected {dim}-dim vectors")
    return records[:, 1:].view(np.float32).reshape(-1, dim)


def generate_queries(vectors, seed):
    rng = np.random.default_rng(seed)
    queries = []
    for query_id in range(QUERY_COUNT):
        target = float(rng.uniform(0.01, 1.0))
        category = str(rng.choice(CATEGORIES))
        in_stock = bool(rng.integers(0, 2))
        price_limit = float(np.clip(10.0 + 990.0 * target, 10.01, 1000.0))
        vector = vectors[int(rng.integers(0, len(vectors)))].copy()
        queries.append(BaselineQuery(query_id, vector, category, price_limit, in_stock, target))
    return queries


def split_queries(queries, seed):
    rng = np.random.default_rng(seed)
    order = rng.permutation(len(queries))
    calibration_ids = set(int(v) for v in order[:CALIBRATION_COUNT])
    calibration = [q for q in queries if q.query_id in calibration_ids]
    held_out = [q for q in queries if q.query_id not in calibration_ids]
    return calibration, held_out


def bucket_for(selectivity):
    for lower, upper in BUCKETS:
        if lower <= selectivity < upper:
            return f"[{lower:.2f},{min(upper, 1.0):.2f})"
    return "[0.50,1.00]"


def recall_at_10(result_ids, reference_ids):
    reference = set(reference_ids)
    return 1.0 if not reference else len(set(result_ids) & reference) / len(reference)


def _vector_literal(vector):
    return "[" + ",".join(repr(float(v)) for v in vector) + "]"


def _build_statement(query, strategy, vector_literal):
    if strategy == "SQL_FIRST":
        return (
            f"SELECT id FROM sift_hybrid WHERE {query.predicate_sql} "
            "ORDER BY embedding <-> %s::vector, id LIMIT %s",
            query.predicate_params + (vector_literal, TOP_K),
            {"enable_indexscan": "off"},
        )
    if strategy == "VECTOR_FIRST_HNSW":
        return (
            f"WITH candidates AS MATERIALIZED ("
            f"SELECT id, embedding <-> %s::vector AS distance "
            f"FROM sift_hybrid ORDER BY embedding <-> %s::vector LIMIT 100) "
            f"SELECT candidates.id FROM candidates JOIN sift_hybrid item ON item.id = candidates.id "
            f"WHERE {query.predicate_sql} "
            "ORDER BY candidates.distance, candidates.id LIMIT %s",
            (vector_literal, vector_literal) + query.predicate_params + (TOP_K,),
            {"hnsw.ef_search": 100, "ivfflat.probes": 1000},
        )
    if strategy == "HNSW_HYBRID":
        return (
            f"SELECT id FROM sift_hybrid WHERE {query.predicate_sql} "
            "ORDER BY embedding <-> %s::vector LIMIT %s",
            query.predicate_params + (vector_literal, TOP_K),
            {"hnsw.ef_search": 100, "ivfflat.probes": 1000},
        )
    if strategy == "IVFFLAT_HYBRID":
        return (
            f"SELECT id FROM sift_hybrid WHERE {query.predicate_sql} "
            "ORDER BY embedding <-> %s::vector LIMIT %s",
            query.predicate_params + (vector_literal, TOP_K),
            {"ivfflat.probes": 10, "hnsw.ef_search": 1000},
        )
    raise ValueError(strategy)


def _classify_plan(strategy, index_names):
    lowered = [str(n).lower() for n in index_names]
    ann_used = any("hnsw" in n or "ivfflat" in n for n in lowered)
    if any("ivfflat" in n for n in lowered):
        access_path = "ivfflat_index"
    elif any("hnsw" in n for n in lowered):
        access_path = "hnsw_index"
    elif lowered:
        access_path = "exact_bitmap"
    else:
        access_path = "exact_seq"
    needle = "hnsw" if strategy in ("VECTOR_FIRST_HNSW", "HNSW_HYBRID") else (
        "ivfflat" if strategy == "IVFFLAT_HYBRID" else None
    )
    verified = (not ann_used) if needle is None else any(needle in n for n in lowered)
    return verified, access_path


def _walk_index_names(node):
    names = []
    if node.get("Index Name"):
        names.append(node["Index Name"])
    for child in node.get("Plans", []):
        names.extend(_walk_index_names(child))
    return names


def estimate_selectivity(conn, query):
    with conn.cursor() as cursor:
        cursor.execute(
            f"EXPLAIN (FORMAT JSON) SELECT id FROM sift_hybrid WHERE {query.predicate_sql}",
            query.predicate_params,
        )
        row = cursor.fetchone()
    plan = row[0] if not isinstance(row[0], str) else json.loads(row[0])
    return float(plan[0]["Plan"]["Plan Rows"]) / DATASET_SIZE


def capture_plan(conn, query, strategy, vector_literal):
    statement, params, settings = _build_statement(query, strategy, vector_literal)
    with conn.cursor() as cursor:
        for k, v in settings.items():
            cursor.execute("SELECT set_config(%s, %s, true)", (k, str(v)))
        cursor.execute("EXPLAIN (FORMAT JSON) " + statement, params)
        row = cursor.fetchone()
    plan = row[0] if not isinstance(row[0], str) else json.loads(row[0])
    return _walk_index_names(plan[0]["Plan"])


def execute_once(conn, query, strategy, reference_ids=None):
    vector_literal = _vector_literal(query.vector)
    statement, params, settings = _build_statement(query, strategy, vector_literal)
    with conn.cursor() as cursor:
        for k, v in settings.items():
            cursor.execute("SELECT set_config(%s, %s, true)", (k, str(v)))
        started = time.perf_counter_ns()
        cursor.execute(statement, params)
        result_ids = tuple(int(r[0]) for r in cursor.fetchall())
        latency_ms = (time.perf_counter_ns() - started) / 1_000_000
    recall = recall_at_10(result_ids, reference_ids) if reference_ids is not None else 1.0
    return result_ids, latency_ms, recall


def build_calibration_map(observations):
    grouped = defaultdict(list)
    for obs in observations:
        grouped[(obs["strategy"], obs["bucket"])].append(obs)
    calibration = {}
    for key, values in grouped.items():
        calibration[key] = {
            "median_latency_ms": float(np.median([v["latency_ms"] for v in values])),
            "minimum_recall": float(min(v["recall_at_10"] for v in values)),
            "observations": float(len(values)),
        }
    return calibration


def choose_adaptive_strategy(estimate, calibration):
    bucket = bucket_for(estimate)
    candidates = ["SQL_FIRST"]
    for strategy in STRATEGIES[1:]:
        evidence = calibration.get((strategy, bucket))
        if evidence and evidence["minimum_recall"] >= TARGET_RECALL:
            candidates.append(strategy)
    return min(
        candidates,
        key=lambda s: calibration.get((s, bucket), {"median_latency_ms": float("inf")})["median_latency_ms"]
    )


def run_calibration(conn, calibration_q):
    calibration_observations = []
    for query in calibration_q:
        estimate = estimate_selectivity(conn, query)
        bucket = bucket_for(estimate)
        for _ in range(1):
            reference_ids = None
            for strategy in STRATEGIES:
                if strategy == "SQL_FIRST" and reference_ids is None:
                    result_ids, latency_ms, _ = execute_once(conn, query, strategy, reference_ids=None)
                    reference_ids = result_ids
                    recall = 1.0
                else:
                    result_ids, latency_ms, recall = execute_once(conn, query, strategy, reference_ids=reference_ids)
                calibration_observations.append({
                    "query_id": query.query_id, "strategy": strategy,
                    "estimated_selectivity": estimate, "bucket": bucket,
                    "latency_ms": latency_ms, "recall_at_10": recall,
                })
    return build_calibration_map(calibration_observations), calibration_observations


def run_heldout(conn, calibration, test_q, warmup=True):
    raw_records = []
    per_query_records = []
    for query in test_q:
        estimate = estimate_selectivity(conn, query)
        bucket = bucket_for(estimate)
        adaptive_strategy = choose_adaptive_strategy(estimate, calibration)
        plan_cache = {}
        # Warm-up: execute each strategy once to prime the OS page cache
        if warmup:
            for strategy in STRATEGIES:
                _, _, _ = execute_once(conn, query, strategy, reference_ids=None)
        fixed_runs = {s: [] for s in STRATEGIES}
        for rep in range(REPETITIONS):
            reference_ids = None
            for strategy in STRATEGIES:
                if strategy == "SQL_FIRST" and reference_ids is None:
                    result_ids, latency_ms, _ = execute_once(conn, query, strategy, reference_ids=None)
                    reference_ids = result_ids
                    recall = 1.0
                else:
                    result_ids, latency_ms, recall = execute_once(conn, query, strategy, reference_ids=reference_ids)
                if strategy not in plan_cache:
                    vector_literal = _vector_literal(query.vector)
                    plan_cache[strategy] = capture_plan(conn, query, strategy, vector_literal)
                verified, access_path = _classify_plan(strategy, plan_cache[strategy])
                rec = {
                    "query_id": query.query_id, "strategy": strategy,
                    "estimated_selectivity": estimate, "bucket": bucket,
                    "latency_ms": latency_ms, "recall_at_10": recall,
                    "repetition": rep,
                    "adaptive_selected": adaptive_strategy,
                    "is_adaptive_selection": strategy == adaptive_strategy,
                    "plan_verified": verified, "access_path": access_path,
                    "plan_index_names": plan_cache[strategy],
                }
                raw_records.append(rec)
                fixed_runs[strategy].append(rec)
        for strategy in STRATEGIES:
            runs = fixed_runs[strategy]
            if not runs:
                continue
            latencies = [r["latency_ms"] for r in runs]
            recalls = [r["recall_at_10"] for r in runs]
            per_query_records.append({
                "query_id": query.query_id, "strategy": strategy,
                "median_latency_ms": float(np.median(latencies)),
                "recall_at_10": float(np.median(recalls)),
                "estimated_selectivity": estimate, "bucket": bucket,
                "adaptive_selected": adaptive_strategy,
                "is_adaptive_selection": strategy == adaptive_strategy,
                "repetitions": len(runs),
            })
    return raw_records, per_query_records


def write_outputs(out_dir, raw_records, per_query_records):
    pd.DataFrame(raw_records).to_csv(out_dir / "heldout_per_execution.csv", index=False)
    pd.DataFrame(per_query_records).to_csv(out_dir / "heldout_per_query.csv", index=False)
    pq = pd.DataFrame(per_query_records)
    rows = []
    for strategy, group in pq.groupby("strategy"):
        lat = group["median_latency_ms"]
        rec = group["recall_at_10"]
        rows.append({
            "strategy": strategy, "queries": len(group),
            "mean_latency_ms": float(lat.mean()),
            "median_latency_ms": float(lat.median()),
            "p95_latency_ms": float(lat.quantile(0.95)),
            "mean_recall_at_10": float(rec.mean()),
            "fraction_recall_at_least_095": float((rec >= TARGET_RECALL).mean()),
        })
    summary = pd.DataFrame(rows).sort_values("strategy").reset_index(drop=True)
    summary.to_csv(out_dir / "summary.csv", index=False)
    print(summary.to_string(index=False))
    sel = pq.drop_duplicates("query_id")[["query_id", "bucket", "estimated_selectivity", "adaptive_selected"]]
    sel_counts = sel.groupby(["bucket", "adaptive_selected"]).size().reset_index(name="count")
    sel_counts.to_csv(out_dir / "selection_by_bucket.csv", index=False)
    print("\nSelection distribution:")
    print(sel_counts.to_string(index=False))
    return summary


def write_metadata(out_dir):
    meta = {
        "seed": 20260820, "split_seed": 20260821,
        "query_count": QUERY_COUNT, "calibration_count": CALIBRATION_COUNT,
        "test_count": TEST_COUNT,
        "repetitions_calibration": 1, "repetitions_heldout": REPETITIONS,
        "top_k": TOP_K, "target_recall": TARGET_RECALL,
        "vector_first_budget": 100, "hnsw_ef_search": 100,
        "ivfflat_probes": 10, "admission_policy": "min_recall",
    }
    (out_dir / "run_metadata.json").write_text(json.dumps(meta, indent=2) + "\n")


def run(out_dir, vector_path, seed=20260820):
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    base_vectors = read_fvecs(vector_path, VECTOR_DIMENSION)
    queries = generate_queries(base_vectors, seed)
    calibration_q, test_q = split_queries(queries, seed + 1)
    print(f"Workload: {len(calibration_q)} calibration, {len(test_q)} test queries")
    conn = psycopg2.connect(host="localhost", user="sdao", dbname="sdao")
    print("Calibration phase...")
    calibration, cal_obs = run_calibration(conn, calibration_q)
    print(f"Calibration: {len(cal_obs)} obs, {len(calibration)} keys")
    pd.DataFrame(cal_obs).to_csv(out_dir / "calibration_per_execution.csv", index=False)
    print("Held-out phase...")
    raw_records, per_query_records = run_heldout(conn, calibration, test_q)
    conn.close()
    write_outputs(out_dir, raw_records, per_query_records)
    write_metadata(out_dir)
    return


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--out-dir", default="results/exp_baseline_reproduction_local")
    parser.add_argument("--vector-path", default=DEFAULT_VECTOR_PATH)
    parser.add_argument("--seed", type=int, default=20260820)
    args = parser.parse_args()
    run(args.out_dir, args.vector_path, args.seed)

