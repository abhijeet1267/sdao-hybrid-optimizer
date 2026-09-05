-- Single-column B-tree indexes correspond to every workload predicate field.
-- PostgreSQL may combine these through bitmap scans for conjunctions; no
-- workload-specific composite indexes are created so the baseline stays general.
CREATE INDEX IF NOT EXISTS sift1m_items_category_idx ON sift1m_items (category);
CREATE INDEX IF NOT EXISTS sift1m_items_brand_idx ON sift1m_items (brand);
CREATE INDEX IF NOT EXISTS sift1m_items_price_idx ON sift1m_items (price);
CREATE INDEX IF NOT EXISTS sift1m_items_rating_idx ON sift1m_items (rating);
CREATE INDEX IF NOT EXISTS sift1m_items_stock_idx ON sift1m_items (stock);
