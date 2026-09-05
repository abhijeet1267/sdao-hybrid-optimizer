"""Capture current PostgreSQL configuration for the audit."""
import json
from datetime import datetime, timezone
from pathlib import Path

import psycopg2

OUT = Path("final/audit/db_config.json")
OUT.parent.mkdir(parents=True, exist_ok=True)

SETTINGS = [
    "server_version",
    "server_version_num",
    "shared_buffers",
    "work_mem",
    "effective_cache_size",
    "max_parallel_workers",
    "max_parallel_workers_per_gather",
    "max_parallel_maintenance_workers",
    "random_page_cost",
    "effective_io_concurrency",
    "jit",
    "default_statistics_target",
    "enable_indexscan",
    "plan_cache_mode",
]

conn = psycopg2.connect(host="localhost", user="sdao", dbname="sdao")
conn.autocommit = True
result = {"captured_at_utc": datetime.now(timezone.utc).isoformat()}

with conn.cursor() as cur:
    for s in SETTINGS:
        cur.execute("SELECT current_setting(%s)", (s,))
        result[s] = cur.fetchone()[0]
    cur.execute("SELECT extversion FROM pg_extension WHERE extname='vector'")
    result["pgvector_version"] = cur.fetchone()[0]
    # Session-level ANN parameters (pgvector custom GUCs).
    # These are runtime-only and may not be in pg_settings.
    for name in ("hnsw.ef_search", "ivfflat.probes"):
        try:
            cur.execute("SELECT pg_catalog.current_setting(%s, true)", (name,))
            result[name] = cur.fetchone()[0]
        except Exception as e:
            result[name] = f"N/A: {e}"
conn.close()

OUT.write_text(json.dumps(result, indent=2) + "\n")
print(json.dumps(result, indent=2))