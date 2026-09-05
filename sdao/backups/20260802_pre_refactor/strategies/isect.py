from __future__ import annotations

import time
import numpy as np
import pandas as pd
from ..utils.data_loader import data_loader

def run_isect(predicate: str, top_k: int = 10, vector_k: int = 2000) -> dict:
    """
    Execute the ISECT (Intersection) strategy:
    1. Retrieve a large set of candidates from the Vector Index.
    2. Retrieve all IDs matching the predicate from the Attribute Index (simulated).
    3. Intersect the two sets of IDs.
    """
    query_vectors = data_loader.load_query_vectors()
    attributes = data_loader.load_attributes()
    ground_truth = data_loader.load_ground_truth()
    index = data_loader.load_hnsw_index()
    
    qvec = query_vectors[0]
    
    start = time.time()
    
    # 1. Vector Search (Candidates)
    v_labels, v_dists = index.knn_query(qvec, k=vector_k)
    v_candidate_set = set(v_labels[0])
    
    # 2. Attribute Filter (using pandas query as a proxy for an attribute index)
    try:
        filtered = attributes.query(predicate)
        attr_ids = set(filtered["id"].values)
    except Exception:
        attr_ids = set()
        
    # 3. Intersection
    intersected_ids = list(v_candidate_set.intersection(attr_ids))
    
    # Re-ranking might be needed if we want distance order, but they are already from HNSW
    # We should keep the order from v_labels for the intersected ones
    top_ids = []
    for label in v_labels[0]:
        if label in attr_ids:
            top_ids.append(int(label))
            if len(top_ids) >= top_k:
                break
                
    latency_ms = (time.time() - start) * 1000
    
    # Calculate Recall
    gt_ids = ground_truth[0][:top_k] if ground_truth.size else []
    recall = len(set(top_ids) & set(gt_ids)) / float(top_k) if top_k else 0.0

    return {
        "query": predicate,
        "vector_k": vector_k,
        "matched_rows": len(intersected_ids),
        "latency_ms": latency_ms,
        "vectors_scanned": vector_k,
        "topk": top_ids,
        "recall": recall,
    }
