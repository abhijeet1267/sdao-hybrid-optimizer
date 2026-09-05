from __future__ import annotations

import time
from pathlib import Path

import hnswlib
import numpy as np
import pandas as pd

from .data_utils import INDEX_FILE, QUERY_FILE, load_attributes, load_ground_truth, load_queries, load_query_vectors

TOP_K = 10
OVERSAMPLING = 100


def read_fvecs(filename: str | Path) -> np.ndarray:
    data = np.fromfile(filename, dtype=np.float32)
    dim = int(data.view(np.int32)[0])
    return data.reshape(-1, dim + 1)[:, 1:].astype(np.float32)


def run_post(predicate: str, top_k: int = TOP_K, oversampling: int = OVERSAMPLING) -> dict:
    """Execute the POST strategy using the HNSW index and then filter by predicate."""
    query_vectors = load_query_vectors()
    attributes = load_attributes()
    ground_truth = load_ground_truth()
    index = hnswlib.Index(space="l2", dim=query_vectors.shape[1])
    index.load_index(str(INDEX_FILE))
    index.set_ef(200)

    start = time.time()
    qvec = query_vectors[0]
    labels, _ = index.knn_query(qvec, k=oversampling)
    candidate_ids = labels[0]
    candidate_df = attributes.iloc[candidate_ids]

    try:
        filtered = candidate_df.query(predicate)
    except Exception:
        filtered = pd.DataFrame(columns=attributes.columns)

    latency_ms = (time.time() - start) * 1000
    top = filtered.head(top_k)
    top_ids = [int(i) for i in top["id"].tolist()]
    gt_ids = ground_truth[0][:top_k] if ground_truth.size else []
    recall_at_10 = len(set(top_ids) & set(gt_ids)) / float(top_k) if top_k else 0.0
    return {
        "query": predicate,
        "candidate_vectors": oversampling,
        "matched_rows": int(len(top)),
        "latency_ms": latency_ms,
        "vectors_scanned": int(len(candidate_ids)),
        "topk": top_ids,
        "recall_at_10": recall_at_10,
    }


def run_experiment(output_path: str | Path | None = None) -> pd.DataFrame:
    results = []
    hybrid_queries = load_queries()
    for _, row in hybrid_queries.iterrows():
        result = run_post(row["predicate"])
        results.append(result)

    df = pd.DataFrame(results)
    if output_path is not None:
        df.to_csv(output_path, index=False)
    return df


if __name__ == "__main__":
    output = run_experiment("post_results.csv")
    print(output.head())