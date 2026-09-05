#!/usr/bin/env python3
"""Load SIFT1M vectors and synthetic relational attributes into PostgreSQL.

The target database must be PostgreSQL 16 with pgvector 0.8.5 available. The
script creates the ``vector`` extension, replaces the ``sift_hybrid`` table,
bulk-loads one million SIFT vectors, and builds HNSW, IVFFLAT, and B-tree indexes.

Example:
    python load_sift_hybrid.py --host localhost --database sdao \
        --user sdao --password "$POSTGRES_PASSWORD"

The password may also be supplied through POSTGRES_PASSWORD. Other connection
settings default to the corresponding POSTGRES_* environment variables.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import os
import sys
from typing import Iterator

import numpy as np
import psycopg2
from psycopg2.extras import execute_values


DEFAULT_VECTOR_PATH = Path(__file__).resolve().parent / "dataset" / "sift" / "sift_base.fvecs"
VECTOR_DIMENSION = 128
ROW_COUNT = 1_000_000
DEFAULT_BATCH_SIZE = 2_000
DEFAULT_PAGE_SIZE = 2_000
CATEGORIES = tuple(f"category_{index:02d}" for index in range(10))


# SIFT .fvecs stores each vector as: int32 dimension, followed by dimension
# float32 values. The mmap avoids an additional copy of the source file.
def iter_fvec_batches(path: Path, batch_size: int) -> Iterator[tuple[int, np.ndarray]]:
    """Yield ``(start_id, vectors)`` batches from a standard .fvecs file."""
    if batch_size <= 0:
        raise ValueError("batch_size must be positive")
    if not path.is_file():
        raise FileNotFoundError(f"SIFT base-vector file not found: {path}")

    raw = np.memmap(path, dtype=np.int32, mode="r")
    record_width = VECTOR_DIMENSION + 1
    if raw.size == 0 or raw.size % record_width:
        raise ValueError(f"Malformed .fvecs file: {path}")
    records = raw.reshape(-1, record_width)
    if not np.all(records[:, 0] == VECTOR_DIMENSION):
        raise ValueError(f"Expected every .fvecs record to have dimension {VECTOR_DIMENSION}")

    for start in range(0, len(records), batch_size):
        block = records[start:start + batch_size]
        vectors = block[:, 1:].view(np.float32).reshape(len(block), VECTOR_DIMENSION)
        yield start, vectors


def connection_arguments(args: argparse.Namespace) -> dict[str, object]:
    """Build psycopg2 connection arguments from CLI values and environment."""
    return {
        "host": args.host or os.getenv("POSTGRES_HOST", "localhost"),
        "port": args.port or int(os.getenv("POSTGRES_PORT", "5432")),
        "dbname": args.database or os.getenv("POSTGRES_DB", "sdao"),
        "user": args.user or os.getenv("POSTGRES_USER", "sdao"),
        "password": args.password or os.getenv("POSTGRES_PASSWORD", ""),
    }


def create_schema(connection: psycopg2.extensions.connection) -> None:
    """Create the extension and replace the target table and its indexes."""
    with connection.cursor() as cursor:
        cursor.execute("CREATE EXTENSION IF NOT EXISTS vector")
        cursor.execute("DROP TABLE IF EXISTS sift_hybrid CASCADE")
        cursor.execute(
            """
            CREATE TABLE sift_hybrid (
                id SERIAL PRIMARY KEY,
                embedding vector(128) NOT NULL,
                category VARCHAR(50) NOT NULL,
                price NUMERIC(10, 2) NOT NULL,
                in_stock BOOLEAN NOT NULL
            )
            """
        )
    connection.commit()


def load_vectors(
    connection: psycopg2.extensions.connection,
    vector_path: Path,
    batch_size: int,
    page_size: int,
    seed: int,
) -> int:
    """Generate attributes and insert all vectors in bounded batches."""
    rng = np.random.default_rng(seed)
    inserted = 0
    insert_sql = "INSERT INTO sift_hybrid (embedding, category, price, in_stock) VALUES %s"
    template = "(%s::vector, %s, %s, %s)"

    with connection.cursor() as cursor:
        for start_id, vectors in iter_fvec_batches(vector_path, batch_size):
            rows = []
            categories = rng.choice(CATEGORIES, size=len(vectors))
            # Generate integer cents first so every stored price has exactly two
            # decimal places and stays within [$10.00, $1000.00].
            prices_cents = rng.integers(1_000, 100_001, size=len(vectors))
            stock_flags = rng.random(len(vectors)) < 0.90
            for vector, category, price_cents, in_stock in zip(
                vectors, categories, prices_cents, stock_flags, strict=True
            ):
                vector_literal = "[" + ",".join(str(float(value)) for value in vector) + "]"
                rows.append((
                    vector_literal,
                    str(category),
                    int(price_cents) / 100.0,
                    bool(in_stock),
                ))
            execute_values(cursor, insert_sql, rows, template=template, page_size=page_size)
            inserted += len(rows)
            if inserted % (batch_size * 10) == 0 or inserted == ROW_COUNT:
                print(f"Inserted {inserted:,}/{ROW_COUNT:,} rows", flush=True)
    connection.commit()
    return inserted


def create_indexes(connection: psycopg2.extensions.connection) -> None:
    """Build the requested vector and relational indexes after loading data."""
    with connection.cursor() as cursor:
        cursor.execute(
            "CREATE INDEX sift_hybrid_embedding_hnsw_idx "
            "ON sift_hybrid USING hnsw (embedding vector_l2_ops)"
        )
        cursor.execute(
            "CREATE INDEX sift_hybrid_embedding_ivfflat_idx "
            "ON sift_hybrid USING ivfflat (embedding vector_l2_ops) WITH (lists = 1000)"
        )
        cursor.execute("CREATE INDEX sift_hybrid_category_idx ON sift_hybrid (category)")
        cursor.execute("CREATE INDEX sift_hybrid_price_idx ON sift_hybrid (price)")
        cursor.execute("CREATE INDEX sift_hybrid_in_stock_idx ON sift_hybrid (in_stock)")
    connection.commit()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vector-path", type=Path, default=DEFAULT_VECTOR_PATH)
    parser.add_argument("--host")
    parser.add_argument("--port", type=int)
    parser.add_argument("--database")
    parser.add_argument("--user")
    parser.add_argument("--password")
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE)
    parser.add_argument("--page-size", type=int, default=DEFAULT_PAGE_SIZE)
    parser.add_argument("--seed", type=int, default=20260820)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.batch_size <= 0 or args.page_size <= 0:
        raise SystemExit("--batch-size and --page-size must be positive")
    if not args.password and not os.getenv("POSTGRES_PASSWORD"):
        raise SystemExit("Provide --password or set POSTGRES_PASSWORD")

    vector_path = args.vector_path.expanduser().resolve()
    connection = None
    try:
        print(f"Connecting to PostgreSQL at {args.host or os.getenv('POSTGRES_HOST', 'localhost')}...")
        connection = psycopg2.connect(**connection_arguments(args))
        create_schema(connection)
        inserted = load_vectors(connection, vector_path, args.batch_size, args.page_size, args.seed)
        if inserted != ROW_COUNT:
            raise RuntimeError(f"Expected {ROW_COUNT:,} vectors, inserted {inserted:,}")
        create_indexes(connection)
        print("Created HNSW, category, price, and in_stock indexes.")
        print("SIFT hybrid table setup completed successfully.")
        return 0
    except Exception as exc:
        if connection is not None:
            connection.rollback()
        print(f"Load failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    finally:
        if connection is not None:
            connection.close()


if __name__ == "__main__":
    raise SystemExit(main())
