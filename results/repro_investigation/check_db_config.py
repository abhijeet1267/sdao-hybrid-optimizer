"""Record current PostgreSQL configuration for comparison with canonical."""
import json
from pathlib import Path
import psycopg2

conn = psycopg2.connect(host='localhost', user='sdao', dbname='sdao')
with conn.cursor() as c:
    c.execute("""
        SELECT name, setting, unit, category
        FROM pg_settings
        WHERE name IN (
            'shared_buffers', 'work_mem', 'maintenance_work_mem',
            'effective_cache_size', 'random_page_cost', 'seq_page_cost',
            'max_parallel_workers', 'max_parallel_workers_per_gather',
            'max_connections', 'wal_buffers', 'checkpoint_completion_target',
            'default_statistics_target', 'random_page_cost', 'cpu_tuple_cost',
            'cpu_index_tuple_cost', 'cpu_operator_cost', 'effective_io_concurrency',
            'hnsw.ef_search', 'ivfflat.probes', 'hnsw.iterative_scan'
        )
        ORDER BY category, name
    """)
    rows = c.fetchall()

config = []
for name, setting, unit, category in rows:
    config.append({
        "name": name, "setting": setting, "unit": unit or "",
        "category": category,
    })

out = {"current_postgres_config": config}
Path("results/repro_investigation/database_config_current.json").write_text(
    json.dumps(out, indent=2) + "\n"
)
print(f"Recorded {len(config)} PostgreSQL settings")
for c in config:
    print(f"  {c['name']}: {c['setting']} {c['unit']}")
conn.close()
