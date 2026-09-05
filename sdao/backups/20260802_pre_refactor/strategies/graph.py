from __future__ import annotations

import time
import numpy as np
import pandas as pd
from ..utils.data_loader import data_loader

def run_graph(predicate: str, top_k: int = 10, ef_search: int = 500) -> dict:
    """
    Simulates a GRAPH strategy (In-index filtering).
    In a real implementation, this would be HNSW traversal with a bitmask filter.
    Here we simulate it using HNSW search with high 'ef' and applying the filter.
    """
    query_vectors = data_loader.load_query_vectors()
    attributes = data_loader.load_attributes()
    ground_truth = data_loader.load_ground_truth()
    index = data_loader.load_hnsw_index()
    
    qvec = query_vectors[0]
    
    start = time.time()
    
    # 1. Simulate Filtered Traversal
    # We use a higher ef to ensure we find enough candidates that pass the filter
    # In a real system, this happens during the graph walk.
    index.set_ef(ef_search)
    
    # We search for a larger number of candidates to simulate the search space
    labels, distances = index.knn_query(qvec, k=ef_search)
    candidate_ids = labels[0]
    
    # 2. Apply filter
    candidate_df = attributes.iloc[candidate_ids]
    try:
        filtered = candidate_df.query(predicate)
    except Exception:
        filtered = pd.DataFrame(columns=attributes.columns)
        
    # 3. Take Top-K
    top = filtered.head(top_k)
    top_ids = [int(i) for i in top["id"].tolist()]
    
    latency_ms = (time.time() - start) * 1000
    
    # Calculate Recall
    gt_ids = ground_truth[0][:top_k] if ground_truth.size else []
    recall = len(set(top_ids) & set(gt_ids)) / float(top_k) if top_k else 0.0

    return {
        "query": predicate,
        "ef_search": ef_search,
        "matched_rows": int(len(top)),
        "latency_ms": latency_ms,
        "vectors_scanned": ef_search, # Simulation of nodes visited
        "topk": top_ids,
        "recall": recall,
    }
