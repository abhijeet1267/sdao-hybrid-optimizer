-- Run with psql variables, for example:
-- psql -v hnsw_m=16 -v hnsw_ef_construction=200 -f sql/indexes_hnsw.sql "$DATABASE_URL"
-- Values are experiment parameters, not asserted optimal settings.
CREATE INDEX IF NOT EXISTS sift1m_items_embedding_hnsw_l2_idx
ON sift1m_items USING hnsw (embedding vector_l2_ops)
WITH (m = :hnsw_m, ef_construction = :hnsw_ef_construction);
