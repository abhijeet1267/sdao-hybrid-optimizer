"""
_common.py — Shared utilities for all benchmark scripts.

Provides:
    - Database connection management (from db_config.json)
    - Cold-cache reset via Docker container restart
    - Strategy query runners with timing instrumentation
    - Brute-force ground-truth computation (cosine distance, top-k)
    - Selectivity-controlled synthetic column generation
    - CSV result writer
"""

import json
import os
import sys
import time
import subprocess
import csv
import logging
from pathlib import Path
from contextlib import contextmanager

import numpy as np
import psycopg2
import psycopg2.extras

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
ROOT_DIR = Path(__file__).resolve().parent.parent.parent  # final/
CONFIG_PATH = ROOT_DIR / "audit" / "db_config.json"
RESULTS_DIR = ROOT_DIR / "results" / "new_experiments"

RESULTS_DIR.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("bench")

# ---------------------------------------------------------------------------
# Configuration loader
# ---------------------------------------------------------------------------

def load_config() -> dict:
    """Load database connection parameters from db_config.json."""
    if not CONFIG_PATH.exists():
        log.error("Config file not found at %s", CONFIG_PATH)
        sys.exit(1)
    with open(CONFIG_PATH, "r") as f:
        return json.load(f)



# ---------------------------------------------------------------------------
# Database connections
# ---------------------------------------------------------------------------

def get_connection(cfg: dict | None = None, autocommit: bool = False):
    """Return a new psycopg2 connection using cfg (or load from file)."""
    if cfg is None:
        cfg = load_config()
    conn = psycopg2.connect(
        host=cfg["host"],
        port=cfg["port"],
        dbname=cfg["dbname"],
        user=cfg["user"],
        password=cfg["password"],
        options=f"-c search_path={cfg.get('schema', 'public')}",
    )
    # Set autocommit BEFORE registering pgvector adapters — the adapter
    # registration can issue a SET command internally which requires
    # autocommit to be safely togglable.
    conn.autocommit = autocommit
    # Register pgvector adapters so Python list <-> vector casts work.
    try:
        from pgvector.psycopg2 import register_vector
        register_vector(conn)
    except Exception as e:  # pragma: no cover
        log.warning("pgvector.psycopg2.register_vector failed: %s", e)
    return conn


@contextmanager
def connect(cfg: dict | None = None, autocommit: bool = False):
    """Context manager that yields a connection and closes it on exit."""
    conn = get_connection(cfg, autocommit)
    try:
        yield conn
    finally:
        conn.close()


def wait_for_pg(cfg: dict, timeout: int = 30):
    """Block until PostgreSQL accepts connections (used after restart)."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            c = get_connection(cfg, autocommit=True)
            c.close()
            return
        except psycopg2.OperationalError:
            time.sleep(0.5)
    raise RuntimeError(f"PostgreSQL not ready after {timeout}s")


# ---------------------------------------------------------------------------
# Cold-cache reset (Docker restart on macOS)
# ---------------------------------------------------------------------------

def cold_cache_reset(cfg: dict | None = None, sleep_after: float = 3.0):
    """
    Reset the buffer cache by restarting the Docker container.
    This is the macOS-safe alternative to /proc/sys/vm/drop_caches.
    If container_name is empty/blank (e.g. native Postgres), uses
    pg_buffercache + pg_reload_conf + a system-level cache drop with
    `purge` (macOS) instead.
    """
    if cfg is None:
        cfg = load_config()
    container = cfg.get("container_name", "").strip()
    if not container:
        # No container → use a non-Docker cold-cache approach.
        log.info("No container_name set; using macOS 'purge' command "
                 "to drop filesystem caches.")
        try:
            subprocess.run(
                ["sync"], check=True, capture_output=True, timeout=30,
            )
            subprocess.run(
                ["purge"], check=False, capture_output=True, timeout=60,
            )
        except (subprocess.TimeoutExpired, FileNotFoundError) as e:
            log.warning("purge command unavailable: %s", e)
        # Force a small read so the kernel evicts old data; not perfect but
        # is the best we can do without Docker.
        time.sleep(sleep_after)
        return

    log.info("Restarting container '%s' for cold-cache reset ...", container)
    result = subprocess.run(
        ["docker", "restart", container],
        capture_output=True, text=True, timeout=60,
    )
    if result.returncode != 0:
        raise RuntimeError(f"docker restart failed: {result.stderr.strip()}")
    time.sleep(sleep_after)
    wait_for_pg(cfg, timeout=30)
    log.info("Container restarted.  PostgreSQL is accepting connections.")


# ---------------------------------------------------------------------------
# Buffer-pool warm-up (hot cache via pg_prewarm if available)
# ---------------------------------------------------------------------------

def warm_cache(conn, table: str | None = None, cfg: dict | None = None):
    """
    Pre-warm the PostgreSQL shared-buffer cache for a table.
    Falls back gracefully if pg_prewarm is not installed.
    """
    if table is None:
        if cfg is None:
            cfg = load_config()
        table = cfg.get("table_name", "items")
    cur = conn.cursor()
    try:
        cur.execute("SELECT pg_prewarm(%s, 'buffer', 'main')", (table,))
        pages = cur.fetchone()[0]
        conn.commit()
        log.info("pg_prewarm loaded %d pages for '%s'", pages, table)
    except psycopg2.errors.UndefinedFunction:
        conn.rollback()
        log.warning("pg_prewarm not available; skipping warm-up")
    finally:
        cur.close()


# ---------------------------------------------------------------------------
# Strategy SQL templates
# ---------------------------------------------------------------------------

def build_strategy_sql(cfg: dict) -> dict:
    """
    Build the four strategy query templates, parameterised by:
      - cfg["table_name"]     : target table
      - cfg["distance_op"]    : e.g. '<=>' cosine, '<->' L2
      - cfg["hnsw_ef_search"] : HNSW ef_search GUC
      - cfg["ivfflat_probes"] : IVFFlat probes GUC
    """
    tbl = cfg.get("table_name", "items")
    op = cfg.get("distance_op", "<=>")
    ef = cfg.get("hnsw_ef_search", 100)
    pr = cfg.get("ivfflat_probes", 10)

    return {
        "SQL_FIRST": {
            "setup": [
                "SET LOCAL enable_indexscan = off",
                "SET LOCAL enable_bitmapscan = on",
                "SET LOCAL enable_seqscan = on",
            ],
            "query": (
                f"SELECT id FROM {tbl} "
                "WHERE category = %s AND price <= %s AND in_stock = %s "
                f"ORDER BY embedding {op} %s LIMIT 10"
            ),
            "params_order": ("category", "price", "in_stock", "embedding"),
        },
        "VECTOR_FIRST_HNSW": {
            "setup": [
                "SET LOCAL enable_seqscan = off",
                "SET LOCAL enable_indexscan = on",
                f"SET LOCAL hnsw.ef_search = {ef}",
            ],
            "query": (
                f"SELECT id FROM ("
                f"  SELECT id, category, price, in_stock, embedding"
                f"  FROM {tbl} ORDER BY embedding {op} %s LIMIT 100"
                f") sub "
                "WHERE category = %s AND price <= %s AND in_stock = %s "
                "LIMIT 10"
            ),
            "params_order": ("embedding", "category", "price", "in_stock"),
        },
        "HNSW_HYBRID": {
            "setup": [
                "SET LOCAL enable_seqscan = off",
                "SET LOCAL enable_indexscan = on",
                f"SET LOCAL hnsw.ef_search = {ef}",
            ],
            "query": (
                f"SELECT id FROM {tbl} "
                "WHERE category = %s AND price <= %s AND in_stock = %s "
                f"ORDER BY embedding {op} %s LIMIT 10"
            ),
            "params_order": ("category", "price", "in_stock", "embedding"),
        },
        "IVFFLAT_HYBRID": {
            "setup": [
                "SET LOCAL enable_seqscan = off",
                "SET LOCAL enable_indexscan = on",
                f"SET LOCAL ivfflat.probes = {pr}",
            ],
            "query": (
                f"SELECT id FROM {tbl} "
                "WHERE category = %s AND price <= %s AND in_stock = %s "
                f"ORDER BY embedding {op} %s LIMIT 10"
            ),
            "params_order": ("category", "price", "in_stock", "embedding"),
        },
    }


ALL_STRATEGIES = [
    "SQL_FIRST", "VECTOR_FIRST_HNSW", "HNSW_HYBRID", "IVFFLAT_HYBRID",
]


# ---------------------------------------------------------------------------
# Query execution with timing
# ---------------------------------------------------------------------------

def run_strategy(conn, strategy_name: str, query_vec: np.ndarray,
                 category, price: float, in_stock: bool,
                 explain: bool = False, cfg: dict | None = None) -> dict:
    """
    Execute one strategy query inside a transaction, returning:
        {
            "ids":            [int, ...],      # result row ids
            "planning_ms":    float,
            "execution_ms":   float,
            "wall_ms":        float,           # end-to-end wall clock
        }
    """
    if cfg is None:
        cfg = load_config()
    spec = build_strategy_sql(cfg)[strategy_name]
    # Build ordered parameter tuple.  Pass query_vec as ndarray so
    # pgvector's VectorAdapter recognises it (a plain Python list would
    # be sent as numeric[]).
    param_map = {
        "category": category,
        "price": price,
        "in_stock": in_stock,
        "embedding": query_vec,
    }
    params = tuple(param_map[k] for k in spec["params_order"])

    planning_ms = 0.0
    execution_ms = 0.0

    # The connection is usually already in a transaction (autocommit=False).
    # End any pre-existing tx, then SET LOCAL + query in a fresh one.
    try:
        conn.rollback()
    except psycopg2.ProgrammingError:
        pass

    try:
        with conn.cursor() as cur:
            # Apply SET LOCAL overrides (transaction-scoped)
            for stmt in spec["setup"]:
                cur.execute(stmt)

            wall_start = time.perf_counter()

            if explain:
                cur.execute(
                    "EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) " + spec["query"],
                    params,
                )
                plan_json = cur.fetchone()[0]
                node = plan_json[0] if isinstance(plan_json, list) else plan_json
                planning_ms = node.get("Planning Time", 0.0)
                execution_ms = node.get("Execution Time", 0.0)
                # Re-run without EXPLAIN to get the actual ids
                cur.execute(spec["query"], params)
            else:
                cur.execute(spec["query"], params)

            wall_ms = (time.perf_counter() - wall_start) * 1000.0
            ids = [row[0] for row in cur.fetchall()]
    except Exception:
        conn.rollback()
        raise
    else:
        if conn.autocommit:
            conn.commit()

    return {
        "ids": ids,
        "planning_ms": planning_ms,
        "execution_ms": execution_ms,
        "wall_ms": wall_ms,
    }



# ---------------------------------------------------------------------------
# Ground-truth: brute-force cosine top-k
# ---------------------------------------------------------------------------

def cosine_distance(a: np.ndarray, b: np.ndarray) -> float:
    """1 - cosine_similarity  (matches pgvector <=> operator)."""
    dot = np.dot(a, b)
    denom = np.linalg.norm(a) * np.linalg.norm(b)
    if denom == 0:
        return 1.0
    return 1.0 - dot / denom


def brute_force_topk(conn, query_vec: np.ndarray,
                     category, price: float, in_stock: bool,
                     k: int = 10, cfg: dict | None = None) -> list[int]:
    """
    Compute exact top-k by distance over the filtered subset.
    Done in-DB by issuing an ORDER BY embedding <op> ... LIMIT k query
    after disabling all index access — pure sequential scan over the
    filtered rows.  This is the most efficient "ground truth" on
    1M-row tables because pgvector's distance operator is vectorised
    in C, and we only ship the top-k row ids back.
    Distance metric is the one configured in db_config.json (default L2).
    """
    if cfg is None:
        cfg = load_config()
    op = cfg.get("distance_op", "<->")
    tbl = cfg.get("table_name", "items")

    # The connection is usually already in a transaction (autocommit=False).
    # End any pre-existing tx, then SET LOCAL + query in a fresh one.
    try:
        conn.rollback()
    except psycopg2.ProgrammingError:
        pass
    try:
        with conn.cursor() as cur:
            cur.execute("SET LOCAL enable_indexscan = off")
            cur.execute("SET LOCAL enable_bitmapscan = off")
            cur.execute("SET LOCAL enable_seqscan = on")
            cur.execute(
                f"SELECT id FROM {tbl} "
                "WHERE category = %s AND price <= %s AND in_stock = %s "
                f"ORDER BY embedding {op} %s LIMIT %s",
                (category, price, in_stock, query_vec, k),
            )
            return [row[0] for row in cur.fetchall()]
    except Exception:
        conn.rollback()
        raise
    else:
        if conn.autocommit:
            conn.commit()


def recall_at_k(retrieved: list[int], ground_truth: list[int], k: int = 10) -> float:
    """Compute Recall@k = |retrieved ∩ ground_truth| / k."""
    if not ground_truth:
        return 0.0
    gt_set = set(ground_truth[:k])
    ret_set = set(retrieved[:k])
    return len(ret_set & gt_set) / k



# ---------------------------------------------------------------------------
# Selectivity-controlled synthetic column generation
# ---------------------------------------------------------------------------
# Each bucket specifies:
#   (label,             target_selectivity_midpoint, n_categories_to_pick,
#    price_pct,         in_stock)
# Categories are formatted as 'category_NN' (zero-padded 2 digits), matching
# the existing sift_hybrid table. n_categories_to_pick = number of distinct
# categories the data was drawn from for this bucket (so picking any single
# 'category_NN' gives selectivity 1/n_categories_to_pick before price/in_stock
# filtering).

SELECTIVITY_BUCKETS = [
    # (label,             target_mid, n_cat, price_pct, in_stock)
    ("sel_000_005", 0.025,  10, 0.30, True),    # ≈ (1/10)*0.30*0.5  = 0.015
    ("sel_005_010", 0.075,  10, 0.50, True),    # ≈ (1/10)*0.50*0.5  = 0.025
    ("sel_010_025", 0.175,  10, 0.90, True),    # ≈ (1/10)*0.90*0.5  = 0.045
    ("sel_025_050", 0.375,  10, 0.90, False),   # ≈ (1/10)*0.90*0.5  = 0.045 + unfiltered price
    ("sel_050_100", 0.750,  10, 1.00, False),   # ≈ (1/10)*1.00*1.0  = 0.10
]
# NOTE:  the real sift_hybrid has only 10 categories, so target selectivities
# are achieved by (category_selectivity=1/10) × (price_selectivity=price_pct)
# × (in_stock_selectivity=0.5 since half the rows are in_stock=true).
# The in_stock=False buckets return roughly the unfiltered price range.


def generate_relational_columns(n_rows: int, rng: np.random.Generator,
                                n_categories: int = 10,
                                stock_ratio: float = 0.5,
                                price_min: float = 10.0,
                                price_max: float = 1000.0) -> dict:
    """
    Generate category, price, in_stock arrays for n_rows items.
    Category is uniform in [0, n_categories) → formatted as 'category_NN'.
    Price is uniform in [price_min, price_max].
    in_stock is Bernoulli(stock_ratio).
    """
    cat_idx = rng.integers(0, n_categories, size=n_rows)
    return {
        "category": np.array(
            [f"category_{int(c):02d}" for c in cat_idx], dtype=object,
        ),
        "price": np.round(
            rng.uniform(price_min, price_max, size=n_rows), 2,
        ),
        "in_stock": rng.random(size=n_rows) < stock_ratio,
    }


def make_query_params_for_bucket(bucket_idx: int,
                                 rng: np.random.Generator,
                                 cfg: dict | None = None) -> dict:
    """
    Return filter parameters (category, price_threshold, in_stock) that,
    combined with the data distribution in that bucket, achieve the target
    selectivity.
    """
    if cfg is None:
        cfg = load_config()
    label, _, n_cat, price_pct, in_stock = SELECTIVITY_BUCKETS[bucket_idx]

    # n_categories = n_cat (default 10), so picking any single category_NN
    # gives a 1/n_cat selectivity; the rest of the selectivity is achieved
    # via the price threshold and in_stock filter.
    cat_idx = int(rng.integers(0, n_cat))
    category = f"category_{cat_idx:02d}"
    # price_pct of the [10, 1000] range (matching real data)
    price_threshold = round(10.0 + price_pct * 990.0, 2)

    return {
        "category": category,
        "price": float(price_threshold),
        "in_stock": bool(in_stock),
        "bucket_label": label,
    }



# ---------------------------------------------------------------------------
# Data loading helpers
# ---------------------------------------------------------------------------

def create_schema(conn, cfg: dict | None = None):
    """
    Ensure the configured table + btree indexes exist.
    Skips if the table already exists with the right shape.
    """
    if cfg is None:
        cfg = load_config()
    tbl = cfg.get("table_name", "items")
    with conn.cursor() as cur:
        cur.execute(
            "SELECT to_regclass(%s)", (tbl,),
        )
        if cur.fetchone()[0] is not None:
            log.info("Table %s already exists; skipping schema creation.", tbl)
            return
        cur.execute(f"""
            CREATE TABLE {tbl} (
                id bigserial PRIMARY KEY,
                embedding vector(128),
                category integer,
                price numeric,
                in_stock boolean
            )
        """)
        cur.execute(
            f"CREATE INDEX IF NOT EXISTS idx_{tbl}_category "
            f"ON {tbl} USING btree (category)"
        )
        cur.execute(
            f"CREATE INDEX IF NOT EXISTS idx_{tbl}_price "
            f"ON {tbl} USING btree (price)"
        )
        cur.execute(
            f"CREATE INDEX IF NOT EXISTS idx_{tbl}_in_stock "
            f"ON {tbl} USING btree (in_stock)"
        )
        conn.commit()
    log.info("Schema ensured for table %s.", tbl)


def create_vector_indexes(conn, cfg: dict | None = None):
    """Create HNSW and IVFFlat indexes if missing (idempotent).

    Important: we look up *any* existing HNSW / IVFFlat index on the
    embedding column first.  If one exists, we don't try to create a
    differently-named one (which would either be a no-op via
    IF NOT EXISTS on the same name, or a long blocking build for a
    different name).  We use table-specific names so that the helper
    works for both `items` (empty) and `sift_hybrid` (pre-loaded).
    """
    if cfg is None:
        cfg = load_config()
    tbl = cfg.get("table_name", "items")
    op = cfg.get("distance_op", "<=>")
    m = cfg.get("hnsw_m", 16)
    ef = cfg.get("hnsw_ef_construction", 200)
    lists = cfg.get("ivfflat_lists", 100)
    opclass = "vector_l2_ops" if op == "<->" else "vector_cosine_ops"

    hnsw_name = f"idx_{tbl}_hnsw"
    ivf_name = f"idx_{tbl}_ivfflat"

    with conn.cursor() as cur:
        # HNSW: only create if no HNSW index on this column exists yet.
        cur.execute(
            "SELECT 1 FROM pg_indexes "
            "WHERE tablename = %s AND indexdef ILIKE '%%USING hnsw (%%embedding%%)' "
            "LIMIT 1",
            (tbl,),
        )
        if cur.fetchone() is None:
            log.info("Creating HNSW index %s on %s ...", hnsw_name, tbl)
            cur.execute(
                f"CREATE INDEX IF NOT EXISTS {hnsw_name} "
                f"ON {tbl} USING hnsw (embedding {opclass}) "
                f"WITH (m = {m}, ef_construction = {ef})"
            )
        else:
            log.info("HNSW index on %s.embedding already exists; skipping.", tbl)

        # IVFFlat: same check.
        cur.execute(
            "SELECT 1 FROM pg_indexes "
            "WHERE tablename = %s AND indexdef ILIKE '%%USING ivfflat (%%embedding%%)' "
            "LIMIT 1",
            (tbl,),
        )
        if cur.fetchone() is None:
            log.info("Creating IVFFlat index %s on %s ...", ivf_name, tbl)
            cur.execute(
                f"CREATE INDEX IF NOT EXISTS {ivf_name} "
                f"ON {tbl} USING ivfflat (embedding {opclass}) "
                f"WITH (lists = {lists})"
            )
        else:
            log.info("IVFFlat index on %s.embedding already exists; skipping.", tbl)

        conn.commit()
    log.info("HNSW and IVFFlat indexes ensured on %s.", tbl)



def bulk_insert(conn, ids: np.ndarray, embeddings: np.ndarray,
                categories: np.ndarray, prices: np.ndarray,
                in_stocks: np.ndarray, batch_size: int = 5000,
                cfg: dict | None = None):
    """
    Bulk-insert rows into the configured table using execute_values.
    embeddings: (N, 128) float32 array.
    """
    if cfg is None:
        cfg = load_config()
    tbl = cfg.get("table_name", "items")
    n = len(ids)
    with conn.cursor() as cur:
        for start in range(0, n, batch_size):
            end = min(start + batch_size, n)
            values = []
            for i in range(start, end):
                vec_str = (
                    "[" + ",".join(f"{v:.6f}" for v in embeddings[i]) + "]"
                )
                # category may be int or string depending on the schema
                cat_val = categories[i]
                if isinstance(cat_val, (np.integer, int)):
                    cat_val = int(cat_val)
                else:
                    cat_val = str(cat_val)
                values.append((
                    int(ids[i]),
                    vec_str,
                    cat_val,
                    float(prices[i]),
                    bool(in_stocks[i]),
                ))
            psycopg2.extras.execute_values(
                cur,
                f"INSERT INTO {tbl} (id, embedding, category, price, in_stock)"
                " VALUES %s ON CONFLICT (id) DO NOTHING",
                values,
                page_size=batch_size,
            )
            conn.commit()
            if (end % 100_000) < batch_size:
                log.info("  inserted %d / %d rows ...", end, n)
    log.info("Bulk insert complete: %d rows into %s.", n, tbl)


def get_row_count(conn, cfg: dict | None = None) -> int:
    """Return current row count of the configured table."""
    if cfg is None:
        cfg = load_config()
    tbl = cfg.get("table_name", "items")
    with conn.cursor() as cur:
        cur.execute(f"SELECT COUNT(*) FROM {tbl}")
        return cur.fetchone()[0]


def truncate_items(conn, cfg: dict | None = None):
    """Truncate the configured table and reset the id sequence."""
    if cfg is None:
        cfg = load_config()
    tbl = cfg.get("table_name", "items")
    with conn.cursor() as cur:
        cur.execute(f"TRUNCATE {tbl} RESTART IDENTITY CASCADE")
        conn.commit()
    log.info("Table '%s' truncated.", tbl)



# ---------------------------------------------------------------------------
# SIFT-10M dataset download + extraction
# ---------------------------------------------------------------------------

def download_sift10m(target_dir: str = "/tmp/sift10m") -> Path:
    """
    Download the ANN-Benchmarks SIFT-10M HDF5 file if not already present.
    Returns the path to the .hdf5 file.
    """
    import urllib.request
    td = Path(target_dir)
    td.mkdir(parents=True, exist_ok=True)
    hdf5_path = td / "sift-10M.hdf5"
    if hdf5_path.exists():
        log.info("SIFT-10M already downloaded at %s", hdf5_path)
        return hdf5_path
    url = "http://ann-benchmarks.com/sift-10M.hdf5"
    log.info("Downloading SIFT-10M from %s (~3.3 GB) ...", url)
    urllib.request.urlretrieve(url, str(hdf5_path))
    log.info("Download complete: %s", hdf5_path)
    return hdf5_path


def load_sift_vectors(hdf5_path: str, max_rows: int | None = None):
    """
    Load the 'train' split of SIFT HDF5 as float32 (N, 128).
    If max_rows is set, return only the first max_rows vectors.
    """
    import h5py
    with h5py.File(str(hdf5_path), "r") as f:
        key = "train" if "train" in f else list(f.keys())[0]
        if max_rows is not None:
            vecs = f[key][:max_rows]
        else:
            vecs = f[key][:]
    return vecs.astype(np.float32)


def load_sift_queries(hdf5_path: str, n_queries: int = 100):
    """Load the 'test' split (query vectors) from the SIFT HDF5."""
    import h5py
    with h5py.File(str(hdf5_path), "r") as f:
        if "test" in f:
            q = f["test"][:n_queries]
        else:
            q = f[list(f.keys())[0]][:n_queries]
    return q.astype(np.float32)


def load_sift_queries_fvecs(path: str, n_queries: int = 100) -> np.ndarray:
    """
    Load the SIFT-1M official `sift_query.fvecs` file (Texpoint/Facebook
    fvecs format) and return the first n_queries as float32.
    """
    arr = np.fromfile(path, dtype=np.int32)
    dim = arr[0]
    n_total = arr.size // (dim + 1)
    n = min(n_queries, n_total)
    vecs = np.zeros((n, dim), dtype=np.float32)
    for i in range(n):
        offset = i * (dim + 1) + 1
        vecs[i] = arr[offset:offset + dim].view(np.float32)
    return vecs


def find_local_sift_query_path() -> str | None:
    """
    Search the project for a local SIFT-1M query file.
    Returns the path if found, else None.
    """
    env = os.environ.get("SIFT_QUERY_FVECS")
    candidates = [
        env if env else "",
        str(Path.cwd() / "data" / "sift_query.fvecs"),
        str(ROOT_DIR / "data" / "sift_query.fvecs"),
        "/tmp/sift_query.fvecs",
    ]
    for c in candidates:
        if Path(c).exists():
            return c
    return None



# ---------------------------------------------------------------------------
# CSV writer
# ---------------------------------------------------------------------------

def write_csv(rows: list[dict], filename: str) -> Path:
    """Write a list of dicts to a CSV file in the results directory."""
    path = RESULTS_DIR / filename
    if not rows:
        log.warning("No rows to write for %s", filename)
        return path
    fieldnames = list(rows[0].keys())
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    log.info("Results written to %s  (%d rows)", path, len(rows))
    return path


# ---------------------------------------------------------------------------
# Percentile helper
# ---------------------------------------------------------------------------

def percentiles(values: list[float]) -> dict:
    """Return p50, p95, p99 for a list of floats."""
    a = np.array(values)
    return {
        "p50": float(np.percentile(a, 50)),
        "p95": float(np.percentile(a, 95)),
        "p99": float(np.percentile(a, 99)),
    }

