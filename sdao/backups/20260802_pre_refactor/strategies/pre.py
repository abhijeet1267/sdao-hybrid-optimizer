from __future__ import annotations

import time
import numpy as np
import pandas as pd
from ..utils.data_loader import data_loader

def run_pre(predicate: str, top_k: int = 10) -> dict:
    """
    Execute the PRE strategy:
    1. Filter attributes based on predicate.
    2. Perform exact vector search on the filtered set.
    """
    # Load data
    base = data_loader.load_base_vectors()
    query_vectors = data_loader.load_query_vectors()
    attributes = data_loader.load_attributes()
    ground_truth = data_loader.load_ground_truth()

    # 1. Filter
    try:
        filtered = attributes.query(predicate)
    except Exception:
        filtered = pd.DataFrame(columns=attributes.columns)

    ids = filtered["id"].values if not filtered.empty else []
    
    if len(ids) == 0:
        return {
            "query": predicate,
            "matched_rows": 0,
            "latency_ms": 0.0,
            "vectors_scanned": 0,
            "topk": [],
            "recall": 0.0
        }

    # Use the first query vector for now (as in original script)
    qvec = query_vectors[0]
    
    start = time.time()
    
    # 2. Exact Search on subset
    candidates = base[ids]
    # Compute L2 distances
    dists = np.linalg.norm(candidates - qvec, axis=1)
    
    # Sort and take top-k
    top_idx_in_candidates = np.argsort(dists)[:top_k]
    top_ids = [int(ids[i]) for i in top_idx_in_candidates]
    
    latency_ms = (time.time() - start) * 1000

    # Calculate Recall
    gt_ids = ground_truth[0][:top_k] if ground_truth.size else []
    recall = len(set(top_ids) & set(gt_ids)) / float(top_k) if top_k else 0.0

    return {
        "query": predicate,
        "matched_rows": int(len(ids)),
        "latency_ms": latency_ms,
        "vectors_scanned": int(len(ids)),
        "topk": top_ids,
        "recall": recall,
    }
