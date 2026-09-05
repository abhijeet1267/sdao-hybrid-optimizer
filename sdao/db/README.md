# PostgreSQL + pgvector baseline

This optional baseline is separate from the existing hnswlib SDAO prototype. It
uses the existing project-root `attributes.csv`, `dataset/sift/sift_base.fvecs`,
and `queries.csv` without duplicating or changing them.

The supplied Docker definition is pinned to `pgvector/pgvector:0.8.5-pg16`:
PostgreSQL 16 and pgvector 0.8.5. Python requires the optional packages pinned
by `requirements-db.txt` (`psycopg` 3 and `python-dotenv`). Record the Docker
image digest, `SHOW server_version`, and the `vector` extension version with
every experimental run.

## Configuration and database startup

1. Copy `.env.example` to a local, untracked `.env` and replace
   `POSTGRES_PASSWORD`, or export the same `POSTGRES_*` values in your shell.
   `DatabaseConfig.from_env()` loads `.env` without overriding shell exports.
   For shell commands that interpolate these variables, run
   `set -a; . ./.env; set +a` first.
2. Install the optional client dependencies explicitly: `pip install -r
   requirements-db.txt`.
3. Start the pinned local service only when ready: `docker compose up -d`.
   The named `sdao_postgres_data` volume preserves database contents across
   container recreation. No startup step truncates or initializes data.
4. Load the existing data: `python -m sdao.db.load_data --apply-schema
   --batch-size 1000`. This creates the `vector` extension/table and validates
   all source IDs, dimensions, metadata domains, and alignment before insert.
5. After loading, run
   `docker compose exec -T postgres psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "ANALYZE sift1m_items;"`.
   This is required before measuring planner-sensitive predicate/index plans.

Create relational indexes with
`docker compose exec -T postgres psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" < sql/indexes_relational.sql`.
Create **one** ANN index for an experiment, after loading and `ANALYZE`:

```sh
docker compose exec -T postgres psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v hnsw_m=16 -v hnsw_ef_construction=200 < sql/indexes_hnsw.sql
docker compose exec -T postgres psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v ivfflat_lists=1000 < sql/indexes_ivfflat.sql
```

`m`, `ef_construction`, and `lists` are experiment parameters, not optimality
claims. Search uses `hnsw.ef_search` or `ivfflat.probes`; the benchmark also
exposes pgvector 0.8 iterative-scan controls to explore further when filters
remove ANN candidates. Record all creation/search settings, table/index sizes,
and execution plans. Do not leave both ANN indexes installed if comparing a
single-index configuration.

## Strategies and ground truth

- **Exact filtered ground truth** / **SQL-first exact**: `WHERE predicate`,
  exact L2 `<->` ordering, `id` as a deterministic equal-distance tie-break,
  and `LIMIT top_k`. It disables vector index scans in its isolated transaction.
- **Vector-first ANN post-filter**: an explicitly verified HNSW global prefix,
  then predicate filtering. The candidate budget and HNSW settings are reported.
- **HNSW hybrid**: a filtered pgvector HNSW query with `hnsw.ef_search` and
  optional iterative scanning.
- **IVFFlat hybrid**: a filtered pgvector IVFFlat query with
  `ivfflat.probes` and optional iterative scanning.

ANN queries use only `ORDER BY embedding <-> query_vector`, which is compatible
with `vector_l2_ops`. Equal-distance ANN ties are not guaranteed deterministic.
`verify_plan()` runs separate `EXPLAIN (FORMAT JSON)` evidence and ANN methods
refuse to run unless the expected index is verified. EXPLAIN time is not part of
strategy latency. Filtered reference latency is reported separately and is
never included in strategy latency. The global SIFT `.ivecs` file is not valid
filtered ground truth and is not used here.

The benchmark keeps a caller-supplied persistent connection and creates an
isolated transaction for each selectivity query, plan check, and timed strategy;
transaction-local settings cannot leak between strategies. This is a warm
persistent-session protocol: it excludes connection/database startup, loading,
schema/index creation, plan verification, and reference work from strategy
latency. It does not control or record OS/PostgreSQL warm versus cold cache
state; report that limitation and use a documented external cache protocol.

## Partial-load recovery

Each successful loader batch commits. If a load fails, a later load detects the
non-empty `sift1m_items` table and refuses to append. First confirm the intended
project database and row count. To intentionally restart **only this project
table**, manually execute `TRUNCATE TABLE sift1m_items;` in that database, then
rerun the loader. The loader never drops databases/tables or truncates data.
