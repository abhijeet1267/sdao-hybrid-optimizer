from __future__ import annotations
import time
from ..utils.data_loader import DataLoader, data_loader


def run_graph(predicate: str, query_id: int = 0, top_k: int = 10, ef_search: int = 1_000, loader: DataLoader = data_loader) -> dict:
    """Use hnswlib's native predicate callback during graph traversal."""
    started = time.perf_counter(); attributes = loader.load_attributes(); index = loader.load_hnsw_index()
    allowed = set(attributes.query(predicate, engine="python")["id"].astype(int).tolist())
    if not allowed:
        return {"topk": [], "matched_rows": 0, "vectors_scanned": 0, "latency_ms": (time.perf_counter()-started)*1000}
    index.set_ef(max(top_k, ef_search))
    labels, _ = index.knn_query(loader.load_query_vectors()[query_id], k=min(top_k, len(allowed)), filter=lambda idx: int(idx) in allowed)
    top = [int(idx) for idx in labels[0] if int(idx) >= 0]
    # hnswlib does not expose visited-node count; ef is the reproducible probe-budget proxy.
    return {"topk": top, "matched_rows": len(allowed), "vectors_scanned": min(len(attributes), max(top_k, ef_search)), "latency_ms": (time.perf_counter()-started)*1000}
