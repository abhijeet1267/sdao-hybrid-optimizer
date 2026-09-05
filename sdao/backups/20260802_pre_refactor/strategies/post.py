from __future__ import annotations

import time
import pandas as pd
from ..utils.data_loader import data_loader

def run_post(predicate: str, top_k: int = 10, oversampling: int = 1000) -> dict:
    """
    Execute the POST strategy:
    1. Search HNSW index for top-M (oversampling).
    2. Filter candidates based on predicate.
    3. Take top-k from filtered candidates.
    """
    query_vectors = data_loader.load_query_vectors()
    attributes = data_loader.load_attributes()
    ground_truth = data_loader.load_ground_truth()
    index = data_loader.load_hnsw_index()

    qvec = query_vectors[0]
    
    start = time.time()
    
    # 1. HNSW Search
    labels, distances = index.knn_query(qvec, k=oversampling)
    candidate_ids = labels[0]
    
    # 2. Filter Candidates
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
        "candidate_vectors": oversampling,
        "matched_rows": int(len(top)),
        "latency_ms": latency_ms,
        "vectors_scanned": int(len(candidate_ids)),
        "topk": top_ids,
        "recall": recall,
    }
