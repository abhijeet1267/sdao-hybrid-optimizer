"""Command-line loader for the existing SIFT1M and attributes.csv files."""
from __future__ import annotations

import argparse
import logging

from .connection import connect
from .loader import apply_schema, load_sift1m


def main() -> None:
    parser = argparse.ArgumentParser(description="Load existing SIFT1M data into PostgreSQL/pgvector")
    parser.add_argument("--batch-size", type=int, default=1_000)
    parser.add_argument("--apply-schema", action="store_true", help="create extension/table before loading; never truncates")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    with connect() as connection:
        if args.apply_schema:
            apply_schema(connection)
        inserted = load_sift1m(args.batch_size, connection=connection)
    print(f"Loaded {inserted} SIFT1M rows.")


if __name__ == "__main__":
    main()
