# Experimental protocol

This document describes the completed experiment; it does not claim held-out evaluation or statistical significance.

## Dataset and workload
- SIFT1M; 1,000,000 rows; 128 dimensions; L2 distance.
- 32 workload queries, top-k=10.

## Method
- Strategies: SQL_FIRST, VECTOR_FIRST_HNSW, HNSW_HYBRID, IVFFLAT_HYBRID.
- Selectivity source: live PostgreSQL EXPLAIN (FORMAT JSON) estimate only.
- Recall target: 0.95; SQL_FIRST is the exact fallback.

## Measurement
- Warm persistent session: True.
- Execution order: for each query: adaptive selected strategy, then four fixed strategies; exact filtered reference after each strategy.
- Comparable latency: timed selected SQL execution only; comparable across adaptive and fixed rows.

## Limitations
- No cold-cache control, repeated trials, random interleaving, held-out evaluation, or significance testing.
