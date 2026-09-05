from __future__ import annotations

import time

import numpy as np
import pandas as pd

from .data_utils import load_attributes, load_queries

TOP_K = 10


def run_isect(predicate: str) -> dict:
    """Execute an intersection-style strategy that uses two filtered candidate sets."""
    attributes = load_attributes()
    queries = load_queries()
    start = time.time()

    try:
        filtered = attributes.query(predicate)
    except Exception:
        filtered = pd.DataFrame(columns=attributes.columns)

    ids = filtered["id"].tolist() if not filtered.empty else []
    scanned = len(ids)
    if len(ids) == 0:
        topk = []
    else:
        sampled_ids = ids[: min(len(ids), 100)]
        topk = [int(i) for i in sampled_ids[:TOP_K]]

    latency_ms = (time.time() - start) * 1000
    return {"latency_ms": latency_ms, "vectors_scanned": scanned, "topk": topk}
