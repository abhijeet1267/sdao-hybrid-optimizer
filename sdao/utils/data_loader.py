"""Cached, path-independent access to the SIFT and relational data sets."""
from __future__ import annotations

from pathlib import Path
import logging
import hnswlib
import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATASET_PATH = PROJECT_ROOT / "dataset" / "sift"
BASE_FILE = DATASET_PATH / "sift_base.fvecs"
QUERY_FILE = DATASET_PATH / "sift_query.fvecs"
GROUND_FILE = DATASET_PATH / "sift_groundtruth.ivecs"
# Prefer the project-level assets; the copies in the package are legacy inputs.
ATTRIBUTE_FILE = PROJECT_ROOT / "attributes.csv"
QUERIES_FILE = PROJECT_ROOT / "queries.csv"
INDEX_FILE = PROJECT_ROOT / "sift_hnsw.bin"


def _read_vectors(path: Path, dtype: np.dtype) -> np.ndarray:
    if not path.is_file():
        raise FileNotFoundError(f"Required data file is missing: {path}")
    raw = np.fromfile(path, dtype=dtype)
    if raw.size == 0:
        raise ValueError(f"Vector file is empty: {path}")
    dimension = int(raw[0] if dtype == np.dtype(np.int32) else raw.view(np.int32)[0])
    if dimension <= 0 or raw.size % (dimension + 1):
        raise ValueError(f"Malformed vector file: {path}")
    return raw.reshape(-1, dimension + 1)[:, 1:]


def read_fvecs(path: str | Path) -> np.ndarray:
    return _read_vectors(Path(path), np.dtype(np.float32)).astype(np.float32, copy=False)


def read_ivecs(path: str | Path) -> np.ndarray:
    return _read_vectors(Path(path), np.dtype(np.int32)).astype(np.int32, copy=False)


class DataLoader:
    """Lazy process-local cache. The 1M-vector matrix is loaded only when needed."""
    def __init__(self) -> None:
        self.base_vectors: np.ndarray | None = None
        self.query_vectors: np.ndarray | None = None
        self.ground_truth: np.ndarray | None = None
        self.attributes: pd.DataFrame | None = None
        self.queries: pd.DataFrame | None = None
        self.index: hnswlib.Index | None = None

    def load_base_vectors(self) -> np.ndarray:
        if self.base_vectors is None:
            logger.info("Loading SIFT base vectors")
            self.base_vectors = read_fvecs(BASE_FILE)
        return self.base_vectors

    def load_query_vectors(self) -> np.ndarray:
        if self.query_vectors is None:
            self.query_vectors = read_fvecs(QUERY_FILE)
        return self.query_vectors

    def load_ground_truth(self) -> np.ndarray:
        if self.ground_truth is None:
            self.ground_truth = read_ivecs(GROUND_FILE)
        return self.ground_truth

    def load_attributes(self) -> pd.DataFrame:
        if self.attributes is None:
            self.attributes = pd.read_csv(ATTRIBUTE_FILE)
            if not self.attributes["id"].equals(pd.Series(np.arange(len(self.attributes)), name="id")):
                raise ValueError("attributes.csv must contain dense, zero-based vector ids")
        return self.attributes

    def load_queries(self) -> pd.DataFrame:
        if self.queries is None:
            self.queries = pd.read_csv(QUERIES_FILE)
            if "predicate" not in self.queries:
                raise ValueError("queries.csv must contain a predicate column")
        return self.queries

    def load_hnsw_index(self) -> hnswlib.Index:
        if self.index is None:
            dim = self.load_query_vectors().shape[1]
            self.index = hnswlib.Index(space="l2", dim=dim)
            self.index.load_index(str(INDEX_FILE), max_elements=len(self.load_attributes()))
        return self.index


data_loader = DataLoader()
