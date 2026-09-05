from __future__ import annotations

import logging
from pathlib import Path

import hnswlib
import numpy as np
import pandas as pd

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Base paths
# Assuming the file is in sdao/utils/data_loader.py, parent.parent.parent is the workspace root
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DATASET_PATH = PROJECT_ROOT / "dataset" / "sift"

# Data files
BASE_FILE = DATASET_PATH / "sift_base.fvecs"
QUERY_FILE = DATASET_PATH / "sift_query.fvecs"
LEARN_FILE = DATASET_PATH / "sift_learn.fvecs"
GROUND_FILE = DATASET_PATH / "sift_groundtruth.ivecs"

# Project files (in sdao/ directory)
SDAO_DIR = PROJECT_ROOT / "sdao"
ATTRIBUTE_FILE = SDAO_DIR / "attributes.csv"
QUERIES_FILE = SDAO_DIR / "queries.csv"
INDEX_FILE = SDAO_DIR / "sift_hnsw.bin"

def read_fvecs(filename: str | Path) -> np.ndarray:
    """Read a SIFT .fvecs file into a dense float32 matrix."""
    filename = Path(filename)
    if not filename.exists():
        raise FileNotFoundError(f"File not found: {filename}")
    
    data = np.fromfile(filename, dtype=np.float32)
    if data.size == 0:
        raise ValueError(f"Empty vector file: {filename}")
    
    dim = int(data.view(np.int32)[0])
    return data.reshape(-1, dim + 1)[:, 1:].astype(np.float32)

def read_ivecs(filename: str | Path) -> np.ndarray:
    """Read a SIFT .ivecs file into an int32 matrix."""
    filename = Path(filename)
    if not filename.exists():
        raise FileNotFoundError(f"File not found: {filename}")
        
    data = np.fromfile(filename, dtype=np.int32)
    if data.size == 0:
        raise ValueError(f"Empty index file: {filename}")
    
    dim = int(data[0])
    return data.reshape(-1, dim + 1)[:, 1:].astype(np.int32)

class DataLoader:
    """Utility class to load all project data."""
    
    def __init__(self):
        self.base_vectors = None
        self.query_vectors = None
        self.ground_truth = None
        self.attributes = None
        self.queries = None
        self.index = None

    def load_base_vectors(self) -> np.ndarray:
        if self.base_vectors is None:
            logger.info(f"Loading base vectors from {BASE_FILE}")
            self.base_vectors = read_fvecs(BASE_FILE)
        return self.base_vectors

    def load_query_vectors(self) -> np.ndarray:
        if self.query_vectors is None:
            logger.info(f"Loading query vectors from {QUERY_FILE}")
            self.query_vectors = read_fvecs(QUERY_FILE)
        return self.query_vectors

    def load_ground_truth(self) -> np.ndarray:
        if self.ground_truth is None:
            logger.info(f"Loading ground truth from {GROUND_FILE}")
            self.ground_truth = read_ivecs(GROUND_FILE)
        return self.ground_truth

    def load_attributes(self) -> pd.DataFrame:
        if self.attributes is None:
            logger.info(f"Loading attributes from {ATTRIBUTE_FILE}")
            self.attributes = pd.read_csv(ATTRIBUTE_FILE)
        return self.attributes

    def load_queries(self) -> pd.DataFrame:
        if self.queries is None:
            logger.info(f"Loading queries from {QUERIES_FILE}")
            self.queries = pd.read_csv(QUERIES_FILE)
        return self.queries

    def load_hnsw_index(self, dim: int = 128) -> hnswlib.Index:
        if self.index is None:
            logger.info(f"Loading HNSW index from {INDEX_FILE}")
            if not INDEX_FILE.exists():
                raise FileNotFoundError(f"Index file not found: {INDEX_FILE}")
            
            self.index = hnswlib.Index(space="l2", dim=dim)
            self.index.load_index(str(INDEX_FILE))
            self.index.set_ef(400)
        return self.index

# Singleton instance for easy access
data_loader = DataLoader()
