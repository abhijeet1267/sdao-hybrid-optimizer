from __future__ import annotations

from pathlib import Path

import hnswlib
import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATASET_PATH = PROJECT_ROOT / "dataset" / "sift"
BASE_FILE = DATASET_PATH / "sift_base.fvecs"
QUERY_FILE = DATASET_PATH / "sift_query.fvecs"
GROUND_FILE = DATASET_PATH / "sift_groundtruth.ivecs"
ATTRIBUTE_FILE = PROJECT_ROOT / "attributes.csv"
QUERIES_FILE = PROJECT_ROOT / "queries.csv"
INDEX_FILE = PROJECT_ROOT / "sift_hnsw.bin"


def read_fvecs(filename: str | Path) -> np.ndarray:
    """Read a SIFT .fvecs file into a dense float32 matrix."""
    data = np.fromfile(filename, dtype=np.float32)
    if data.size == 0:
        raise ValueError(f"Empty vector file: {filename}")
    dim = int(data.view(np.int32)[0])
    return data.reshape(-1, dim + 1)[:, 1:].astype(np.float32)


def read_ivecs(filename: str | Path) -> np.ndarray:
    """Read a SIFT .ivecs file into an int32 matrix."""
    data = np.fromfile(filename, dtype=np.int32)
    if data.size == 0:
        raise ValueError(f"Empty index file: {filename}")
    dim = int(data[0])
    return data.reshape(-1, dim + 1)[:, 1:].astype(np.int32)


def load_base_vectors() -> np.ndarray:
    return read_fvecs(BASE_FILE)


def load_query_vectors() -> np.ndarray:
    return read_fvecs(QUERY_FILE)


def load_ground_truth() -> np.ndarray:
    return read_ivecs(GROUND_FILE)


def load_attributes() -> pd.DataFrame:
    return pd.read_csv(ATTRIBUTE_FILE)


def load_queries() -> pd.DataFrame:
    return pd.read_csv(QUERIES_FILE)


def load_hnsw_index(dim: int | None = None) -> hnswlib.Index:
    """Load the HNSW index from disk."""
    if dim is None:
        dim = load_base_vectors().shape[1]
    index = hnswlib.Index(space="l2", dim=dim)
    index.load_index(str(INDEX_FILE))
    index.set_ef(400)
    return index
