-- PostgreSQL 16+ with the pgvector extension (0.7+ recommended).
-- The loader preserves the existing zero-based SIFT1M ids.
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS sift1m_items (
    id INTEGER PRIMARY KEY CHECK (id >= 0),
    category TEXT NOT NULL,
    brand TEXT NOT NULL,
    price INTEGER NOT NULL,
    rating REAL NOT NULL,
    stock BOOLEAN NOT NULL,
    embedding vector(128) NOT NULL
);
