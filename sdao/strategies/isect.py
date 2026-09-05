from __future__ import annotations
import time
from ..utils.data_loader import DataLoader, data_loader


def run_isect(predicate: str, query_id: int = 0, top_k: int = 10, vector_k: int = 1_000, loader: DataLoader = data_loader) -> dict:
    """Intersect a ranked HNSW candidate list with relational matching ids."""
    started = time.perf_counter(); attributes = loader.load_attributes(); index = loader.load_hnsw_index()
    allowed = set(attributes.query(predicate, engine="python")["id"].astype(int).tolist())
    k = min(max(top_k, vector_k), len(attributes)); index.set_ef(max(k, 128))
    labels, _ = index.knn_query(loader.load_query_vectors()[query_id], k=k)
    candidates = [int(idx) for idx in labels[0]]
    matched = [idx for idx in candidates if idx in allowed]
    return {"topk": matched[:top_k], "matched_rows": len(matched), "vectors_scanned": k, "latency_ms": (time.perf_counter()-started)*1000}
