from __future__ import annotations
import time
import numpy as np
from ..utils.data_loader import DataLoader, data_loader


def run_pre(predicate: str, query_id: int = 0, top_k: int = 10, loader: DataLoader = data_loader) -> dict:
    """Filter first, then perform exact L2 ranking over qualifying vectors."""
    started = time.perf_counter()
    attributes = loader.load_attributes()
    ids = attributes.query(predicate, engine="python")["id"].to_numpy(dtype=np.int64)
    if not len(ids):
        return {"topk": [], "matched_rows": 0, "vectors_scanned": 0, "latency_ms": (time.perf_counter()-started)*1000}
    qvec = loader.load_query_vectors()[query_id]
    candidates = loader.load_base_vectors()[ids]
    delta = candidates - qvec
    distances = np.einsum("ij,ij->i", delta, delta)
    order = np.argsort(distances, kind="stable")[:top_k]
    return {"topk": ids[order].astype(int).tolist(), "matched_rows": int(len(ids)), "vectors_scanned": int(len(ids)), "latency_ms": (time.perf_counter()-started)*1000}
