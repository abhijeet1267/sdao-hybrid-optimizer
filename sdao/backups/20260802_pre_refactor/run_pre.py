from __future__ import annotations

import time
from pathlib import Path

import numpy as np
import pandas as pd

from .data_utils import BASE_FILE, QUERY_FILE, load_attributes, load_ground_truth, load_queries, load_query_vectors

TOP_K = 10


def read_fvecs(filename: str | Path) -> np.ndarray:
    data = np.fromfile(filename, dtype=np.float32)
    dim = int(data.view(np.int32)[0])
    return data.reshape(-1, dim + 1)[:, 1:].astype(np.float32)


def run_pre(predicate: str, top_k: int = TOP_K) -> dict:
    """Execute the PRE strategy by scanning the filtered attribute rows and ranking vectors."""
    base = read_fvecs(BASE_FILE)
    query_vectors = load_query_vectors()
    attributes = load_attributes()
    ground_truth = load_ground_truth()

    try:
        filtered = attributes.query(predicate)
    except Exception:
        filtered = pd.DataFrame(columns=attributes.columns)

    ids = filtered["id"].values if not filtered.empty else []
    if len(ids) == 0:
        return {"query": predicate, "matched_rows": 0, "latency_ms": 0.0, "vectors_scanned": 0, "topk": [], "recall_at_10": 0.0}

    qvec = query_vectors[0]
    start = time.time()
    candidates = base[ids]
    dists = np.linalg.norm(candidates - qvec, axis=1)
    top_idx = np.argsort(dists)[:top_k]
    top_ids = [int(ids[i]) for i in top_idx]
    latency_ms = (time.time() - start) * 1000

    gt_ids = ground_truth[0][:top_k] if ground_truth.size else []
    recall_at_10 = len(set(top_ids) & set(gt_ids)) / float(top_k) if top_k else 0.0

    return {
        "query": predicate,
        "matched_rows": int(len(ids)),
        "latency_ms": latency_ms,
        "vectors_scanned": int(len(ids)),
        "topk": top_ids,
        "recall_at_10": recall_at_10,
    }


def run_experiment(output_path: str | Path | None = None) -> pd.DataFrame:
    results = []
    query_df = load_queries()
    for _, row in query_df.iterrows():
        results.append(run_pre(row["predicate"]))

    df = pd.DataFrame(results)
    if output_path is not None:
        df.to_csv(output_path, index=False)
    return df


if __name__ == "__main__":
    output = run_experiment("pre_results.csv")
    print(output.head())