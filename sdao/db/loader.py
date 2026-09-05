"""Validated, chunked loading of existing SIFT1M assets into PostgreSQL."""
from __future__ import annotations

from pathlib import Path
import logging
from typing import Iterator

import numpy as np
import pandas as pd

from .connection import connect
from .config import DatabaseConfig
from ..utils.data_loader import ATTRIBUTE_FILE, BASE_FILE, PROJECT_ROOT

logger = logging.getLogger(__name__)
EMBEDDING_DIMENSION = 128
TABLE_NAME = "sift1m_items"
SCHEMA_FILE = PROJECT_ROOT / "sql" / "schema.sql"


class DatasetValidationError(ValueError):
    pass


class PartialLoadError(RuntimeError):
    """Raised rather than appending to a populated destination table."""


def _first_bad_row(batch: pd.DataFrame, mask: pd.Series | np.ndarray, column: str, detail: str) -> DatasetValidationError:
    positions = np.flatnonzero(np.asarray(mask))
    row = int(batch.index[positions[0]]) + 2 if len(positions) else "unknown"
    return DatasetValidationError(f"Invalid {column} at attributes.csv row {row}: {detail}")


def _validate_metadata_batch(batch: pd.DataFrame, vector_count: int, seen: np.ndarray | None = None) -> np.ndarray:
    required = ("id", "category", "brand", "price", "rating", "stock")
    missing = [column for column in required if column not in batch.columns]
    if missing:
        raise DatasetValidationError(f"attributes.csv is missing required column(s): {', '.join(missing)}")
    for column in required:
        nulls = batch[column].isna()
        if nulls.any():
            raise _first_bad_row(batch, nulls, column, "null values are not allowed")
    ids = batch["id"].to_numpy()
    if not np.issubdtype(ids.dtype, np.integer):
        raise _first_bad_row(batch, np.ones(len(batch), dtype=bool), "id", "must use an integer CSV representation")
    ids = ids.astype(np.int64, copy=False)
    invalid_ids = (ids < 0) | (ids >= vector_count)
    if invalid_ids.any():
        raise _first_bad_row(batch, invalid_ids, "id", f"must be in [0, {vector_count - 1}]")
    if seen is not None:
        duplicates = seen[ids]
        if duplicates.any():
            raise _first_bad_row(batch, duplicates, "id", "duplicate id")
        seen[ids] = True
    for column in ("category", "brand"):
        values = batch[column]
        invalid = ~values.map(lambda value: isinstance(value, str) and bool(value.strip())).to_numpy(dtype=bool)
        if invalid.any():
            raise _first_bad_row(batch, invalid, column, "must be a non-empty string")
    prices = batch["price"].to_numpy()
    if not np.issubdtype(prices.dtype, np.integer):
        raise _first_bad_row(batch, np.ones(len(batch), dtype=bool), "price", "must use an integer CSV representation")
    invalid_prices = prices < 0
    if invalid_prices.any():
        raise _first_bad_row(batch, invalid_prices, "price", "must be non-negative")
    ratings = batch["rating"].to_numpy(dtype=np.float64)
    invalid_ratings = ~np.isfinite(ratings) | (ratings < 0) | (ratings > 5)
    if invalid_ratings.any():
        raise _first_bad_row(batch, invalid_ratings, "rating", "must be a finite value in [0, 5]")
    stock = batch["stock"].to_numpy()
    invalid_stock = np.asarray([not isinstance(value, (bool, np.bool_)) for value in stock])
    if invalid_stock.any():
        raise _first_bad_row(batch, invalid_stock, "stock", "must be a boolean True or False")
    return ids


def _fvec_layout(path: Path) -> tuple[int, int]:
    if not path.is_file():
        raise FileNotFoundError(f"SIFT base-vector file is missing: {path}")
    raw = np.memmap(path, dtype=np.int32, mode="r")
    if raw.size == 0:
        raise DatasetValidationError("SIFT base-vector file is empty")
    dimension = int(raw[0])
    if dimension != EMBEDDING_DIMENSION or raw.size % (dimension + 1):
        raise DatasetValidationError(f"Expected well-formed {EMBEDDING_DIMENSION}-D fvecs data, got dimension {dimension}")
    return raw.size // (dimension + 1), dimension


def validate_source_data(attributes_path: Path = ATTRIBUTE_FILE, vectors_path: Path = BASE_FILE, batch_size: int = 100_000) -> int:
    """Validate ids and dimensions without materialising the 1M-vector matrix."""
    if batch_size <= 0:
        raise ValueError("batch_size must be positive")
    vector_count, dimension = _fvec_layout(vectors_path)
    if dimension != EMBEDDING_DIMENSION:
        raise DatasetValidationError("Unexpected embedding dimension")
    seen = np.zeros(vector_count, dtype=bool)
    rows = 0
    try:
        batches = pd.read_csv(attributes_path, chunksize=batch_size)
        for batch in batches:
            _validate_metadata_batch(batch, vector_count, seen)
            rows += len(batch)
    except FileNotFoundError:
        raise
    except pd.errors.EmptyDataError as exc:
        raise DatasetValidationError("attributes.csv is empty") from exc
    if rows != vector_count:
        raise DatasetValidationError(f"metadata row count ({rows}) does not match vector count ({vector_count})")
    if not seen.all():
        raise DatasetValidationError("attributes.csv has missing vector ids")
    return vector_count


def _vector_batches(vectors_path: Path, batch_size: int) -> Iterator[tuple[int, np.ndarray]]:
    count, dimension = _fvec_layout(vectors_path)
    raw = np.memmap(vectors_path, dtype=np.int32, mode="r").reshape(count, dimension + 1)
    for start in range(0, count, batch_size):
        records = raw[start:start + batch_size]
        if not np.all(records[:, 0] == dimension):
            raise DatasetValidationError(f"Malformed fvecs dimension header in rows {start}:{start + len(records)}")
        yield start, records[:, 1:].view(np.float32).reshape(len(records), dimension)


def _vector_literal(vector: np.ndarray) -> str:
    if vector.shape != (EMBEDDING_DIMENSION,) or not np.isfinite(vector).all():
        raise DatasetValidationError("Every embedding must be a finite 128-dimensional vector")
    return "[" + ",".join(repr(float(value)) for value in vector) + "]"


def apply_schema(connection, schema_path: Path = SCHEMA_FILE) -> None:
    """Apply the supplied schema; this never truncates or drops existing data."""
    with connection.cursor() as cursor:
        cursor.execute(schema_path.read_text())
    connection.commit()


def load_sift1m(batch_size: int = 1_000, config: DatabaseConfig | None = None, connection=None) -> int:
    """Insert existing SIFT1M rows in batches, failing on any malformed or duplicate row.

    The destination table must be empty. This intentionally avoids destructive
    reset behaviour; create a new database to repeat a load.
    """
    if batch_size <= 0:
        raise ValueError("batch_size must be positive")
    expected_rows = validate_source_data(batch_size=max(batch_size, 10_000))
    owns_connection = connection is None
    connection = connection or connect(config)
    try:
        with connection.cursor() as cursor:
            cursor.execute(f"SELECT count(*) FROM {TABLE_NAME}")
            existing_rows = int(cursor.fetchone()[0])
        if existing_rows:
            raise PartialLoadError(
                f"{TABLE_NAME} already has {existing_rows} rows; refusing to append or overwrite it. "
                f"Verify the intended project database, then either keep a complete {expected_rows}-row table or "
                f"run TRUNCATE TABLE {TABLE_NAME} manually in that database before restarting the load."
            )
        metadata = pd.read_csv(ATTRIBUTE_FILE, chunksize=batch_size)
        inserted = 0
        statement = (
            f"INSERT INTO {TABLE_NAME} (id, category, brand, price, rating, stock, embedding) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s::vector)"
        )
        for (start, vectors), batch in zip(_vector_batches(BASE_FILE, batch_size), metadata, strict=True):
            ids = _validate_metadata_batch(batch, expected_rows)
            expected_ids = np.arange(start, start + len(batch), dtype=np.int64)
            if not np.array_equal(ids, expected_ids):
                raise DatasetValidationError("metadata row order must align with zero-based SIFT vector ids")
            rows = [
                (int(row.id), row.category, row.brand, int(row.price), float(row.rating), row.stock, _vector_literal(vector))
                for row, vector in zip(batch.itertuples(index=False), vectors, strict=True)
            ]
            with connection.cursor() as cursor:
                cursor.executemany(statement, rows)
            connection.commit()
            inserted += len(rows)
            logger.info("Loaded %d/%d SIFT1M rows (%.1f%%)", inserted, expected_rows, 100 * inserted / expected_rows)
        if inserted != expected_rows:
            raise DatasetValidationError(f"Inserted {inserted} rows but expected {expected_rows}")
        return inserted
    finally:
        if owns_connection:
            connection.close()
