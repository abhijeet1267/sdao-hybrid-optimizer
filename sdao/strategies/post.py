from __future__ import annotations
import time
import numpy as np
from ..utils.data_loader import DataLoader, data_loader


def run_post(predicate: str, query_id: int = 0, top_k: int = 10, oversampling: int = 1_000, loader: DataLoader = data_loader) -> dict:
    """Retrieve a global HNSW prefix, apply the predicate, preserve ANN rank."""
    started = time.perf_counter(); attributes = loader.load_attributes(); index = loader.load_hnsw_index()
    k = min(max(top_k, oversampling), len(attributes)); index.set_ef(max(k, 128))
    labels, _ = index.knn_query(loader.load_query_vectors()[query_id], k=k)
    candidate_ids = labels[0].astype(np.int64)
    allowed = attributes.iloc[candidate_ids].query(predicate, engine="python")["id"].to_numpy(dtype=np.int64)
    allowed_set = set(allowed.tolist())
    top = [int(idx) for idx in candidate_ids if int(idx) in allowed_set][:top_k]
    return {"topk": top, "matched_rows": int(len(allowed)), "vectors_scanned": int(k), "latency_ms": (time.perf_counter()-started)*1000}
