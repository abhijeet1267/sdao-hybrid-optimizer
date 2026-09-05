-- Run with psql variables, for example:
-- psql -v ivfflat_lists=1000 -f sql/indexes_ivfflat.sql "$DATABASE_URL"
-- Build only after loading data.  The lists value is an experiment parameter.
CREATE INDEX IF NOT EXISTS sift1m_items_embedding_ivfflat_l2_idx
ON sift1m_items USING ivfflat (embedding vector_l2_ops)
WITH (lists = :ivfflat_lists);
