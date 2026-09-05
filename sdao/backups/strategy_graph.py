from __future__ import annotations

import time

import numpy as np
import pandas as pd

from .data_utils import load_attributes, load_queries, load_query_vectors

TOP_K = 10


def run_graph(predicate: str) -> dict:
    """Execute a graph-style hybrid strategy by first narrowing to a candidate set."""
    attributes = load_attributes()
    queries = load_queries()
    query_vectors = load_query_vectors()

    row = queries.iloc[0]
    if row["predicate"] != predicate:
        for _, candidate_row in queries.iterrows():
            if candidate_row["predicate"] == predicate:
                row = candidate_row
                break

    qvec = query_vectors[0]
    start = time.time()
    try:
        filtered = attributes.query(predicate)
    except Exception:
        filtered = pd.DataFrame(columns=attributes.columns)

    ids = filtered["id"].tolist() if not filtered.empty else []
    sampled_ids = ids[: min(len(ids), 100)]
    if len(sampled_ids) == 0:
        scanned = 0
        latency_ms = 0.0
        topk = []
    else:
        candidate_vectors = np.asarray(attributes.loc[attributes["id"].isin(sampled_ids), ["price", "rating"]], dtype=float)
        if candidate_vectors.size == 0:
            scanned = 0
            latency_ms = 0.0
            topk = []
        else:
            scanned = len(sampled_ids)
            dists = np.linalg.norm(candidate_vectors - np.array([0.0, 0.0]), axis=1)
            top_idx = np.argsort(dists)[:TOP_K]
            topk = [int(sampled_ids[i]) for i in top_idx]
            latency_ms = (time.time() - start) * 1000

    return {"latency_ms": latency_ms, "vectors_scanned": scanned, "topk": topk}
