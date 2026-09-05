"""Index construction ablation on the 200K SIFT1M subset."""
import json
import time
from collections import defaultdict
from pathlib import Path
import numpy as np
import pandas as pd
import psycopg2

VECTOR_DIMENSION = 128
DATASET_SIZE = 200_000
TABLE_NAME = "sift_hybrid_200k"
TOP_K = 10
QUERY_COUNT = 500
CALIBRATION_COUNT = 250
TEST_COUNT = 250
REPETITIONS = 5
TARGET_RECALL = 0.95
STRATEGIES = ("SQL_FIRST", "VECTOR_FIRST_HNSW", "HNSW_HYBRID", "IVFFLAT_HYBRID")
CATEGORIES = tuple(f"category_{i:02d}" for i in range(10))
VECTOR_PATH = "dataset/sift/sift_base.fvecs"
VECTOR_SUBSET_SIZE = 200_000
EF_CONSTRUCTION_VALUES = [64, 200, 400]
EF_SEARCH_VALUES = [50, 100, 200, 400]
def read_fvecs_subset(path, dim, n):
    raw = np.fromfile(path, dtype=np.int32)
    width = dim + 1
    return raw.reshape(-1, width)[:n, 1:].view(np.float32).reshape(-1, dim)


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
    return [q for q in queries if q[0] in cal_ids], [q for q in queries if q[0] not in cal_ids]


def recall_at_10(rids, ref):
    ref = set(ref)
    return 1.0 if not ref else len(set(rids) & ref) / len(ref)


def vec_literal(v):
    return "[" + ",".join(repr(float(x)) for x in v) + "]"


def exec_hnsw_hybrid(conn, q, ef_search):
    cid, vec, cat, pl, st, _ = q
    vl = vec_literal(vec)
    with conn.cursor() as c:
        c.execute("SELECT set_config('hnsw.ef_search', %s, true)", (str(ef_search),))
        t0 = time.perf_counter_ns()
        c.execute(
            f"SELECT id FROM {TABLE_NAME} WHERE (category = %s AND price < %s AND in_stock = %s) "
            "ORDER BY embedding <-> %s::vector LIMIT %s",
            (cat, pl, st, vl, TOP_K))
        rids = [int(r[0]) for r in c.fetchall()]
        lat = (time.perf_counter_ns() - t0) / 1_000_000
    return rids, lat


def get_sql_first_ref(conn, q):
    cid, vec, cat, pl, st, _ = q
    vl = vec_literal(vec)
    with conn.cursor() as c:
        c.execute("SELECT set_config('enable_indexscan', 'off', true)")
        c.execute(
            f"SELECT id FROM {TABLE_NAME} WHERE (category = %s AND price < %s AND in_stock = %s) "
            "ORDER BY embedding <-> %s::vector, id LIMIT %s",
            (cat, pl, st, vl, TOP_K))
        return [int(r[0]) for r in c.fetchall()]


def warmup(conn, test_q, ef_search):
    for q in test_q:
        exec_hnsw_hybrid(conn, q, ef_search)
        get_sql_first_ref(conn, q)
def run_ablation_for_ef(ef_construction, ef_search, test_q, conn):
    with conn.cursor() as c:
        c.execute(f"DROP INDEX IF EXISTS {TABLE_NAME}_embedding_hnsw_idx;")
    conn.commit()
    if ef_construction == 64:
        index_sql = f"CREATE INDEX {TABLE_NAME}_embedding_hnsw_idx ON {TABLE_NAME} USING hnsw (embedding vector_l2_ops);"
    else:
        index_sql = f"CREATE INDEX {TABLE_NAME}_embedding_hnsw_idx ON {TABLE_NAME} USING hnsw (embedding vector_l2_ops) WITH (m = 16, ef_construction = {ef_construction});"
    build_start = time.time()
    with conn.cursor() as c:
        c.execute("SET maintenance_work_mem = '2GB';")
        c.execute(index_sql)
    conn.commit()
    build_time = time.time() - build_start
    with conn.cursor() as c:
        c.execute(f"SELECT pg_size_pretty(pg_relation_size('{TABLE_NAME}_embedding_hnsw_idx'))")
        index_size = c.fetchone()[0]
    warmup(conn, test_q, ef_search)
    hnsw_lats = []
    hnsw_recs = []
    for q in test_q:
        rids, lat = exec_hnsw_hybrid(conn, q, ef_search)
        ref = get_sql_first_ref(conn, q)
        rec = recall_at_10(rids, ref)
        hnsw_lats.append(lat)
        hnsw_recs.append(rec)
    return {
        "ef_construction": ef_construction, "ef_search": ef_search,
        "build_time_s": round(build_time, 1), "index_size": index_size,
        "n": len(hnsw_lats),
        "mean_latency_ms": round(float(np.mean(hnsw_lats)), 3),
        "median_latency_ms": round(float(np.median(hnsw_lats)), 3),
        "p95_latency_ms": round(float(np.quantile(hnsw_lats, 0.95)), 3),
        "mean_recall_at_10": round(float(np.mean(hnsw_recs)), 4),
        "min_recall_at_10": round(float(np.min(hnsw_recs)), 4),
        "p05_recall": round(float(np.quantile(hnsw_recs, 0.05)), 4),
        "fraction_recall_at_least_095": round(float(np.mean([r >= 0.95 for r in hnsw_recs])), 4),
    }


def main():
    out_dir = Path("results/repro_investigation")
    out_dir.mkdir(exist_ok=True)
    print("Loading 200K SIFT1M subset...")
    vectors = read_fvecs_subset(VECTOR_PATH, VECTOR_DIMENSION, VECTOR_SUBSET_SIZE)
    queries = make_queries(vectors, 20260820)
    cal_q, test_q = split_queries(queries, 20260821)
    print(f"Workload: {len(cal_q)} cal, {len(test_q)} test")
    conn = psycopg2.connect(host='localhost', user='sdao', dbname='sdao')
    results = []
    for ef_c in EF_CONSTRUCTION_VALUES:
        for ef_s in EF_SEARCH_VALUES:
            print(f"\n=== ef_construction={ef_c}, ef_search={ef_s} ===")
            t0 = time.time()
            r = run_ablation_for_ef(ef_c, ef_s, test_q, conn)
            elapsed = time.time() - t0
            print(f"  build={r['build_time_s']}s size={r['index_size']} "
                  f"recall={r['mean_recall_at_10']:.4f} (min={r['min_recall_at_10']:.3f}) "
                  f"lat={r['mean_latency_ms']:.2f}ms p95={r['p95_latency_ms']:.2f}ms "
                  f"elapsed={elapsed:.0f}s")
            results.append(r)
    pd.DataFrame(results).to_csv(out_dir / "index_ablation.csv", index=False)
    (out_dir / "index_ablation.json").write_text(json.dumps(results, indent=2) + "\n")
    print(f"\nWrote index_ablation.csv and index_ablation.json")
    print(pd.DataFrame(results).to_string(index=False))
    conn.close()


if __name__ == "__main__":
    main()
