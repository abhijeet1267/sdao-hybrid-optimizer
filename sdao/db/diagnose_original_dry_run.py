"""Replay the original ten-query dry-run planner diagnostic."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import pandas as pd

from .config import DatabaseConfig
from .evaluate_heldout import (
    ATTRIBUTE_FILE,
    QUERY_FILE,
    HeldOutHarness,
    generate_queries,
    split_queries,
)
from .loader import TABLE_NAME
from ..utils.data_loader import read_fvecs

try:
    import psycopg
except ImportError as exc:  # pragma: no cover - optional database dependency
    raise RuntimeError("Install requirements-db.txt before running this diagnostic.") from exc


def _plan_details(raw_plan: Any, expected_index: str | None) -> dict[str, Any]:
    plan = json.loads(raw_plan) if isinstance(raw_plan, str) else raw_plan
    index_names: list[str] = []
    node_types: list[str] = []

    def walk(value: Any) -> None:
        if isinstance(value, dict):
            if "Node Type" in value:
                node = str(value["Node Type"])
                if "Index Name" in value:
                    node += ":" + str(value["Index Name"])
                    index_names.append(str(value["Index Name"]))
                node_types.append(node)
            for child in value.values():
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)

    walk(plan)
    return {
        "expected_index": expected_index,
        "uses_expected_index": expected_index in index_names if expected_index else False,
        "uses_seq_scan": any(node == "Seq Scan" for node in node_types),
        "index_names": index_names,
        "node_types": node_types,
    }


def _explain(
    connection,
    harness: HeldOutHarness,
    query,
    candidate_budget: int,
    disable_seqscan: bool,
) -> dict[str, Any]:
    sql, params, settings, expected_index = harness._sql(query, "VECTOR_FIRST_HNSW", candidate_budget)
    with connection.transaction():
        with connection.cursor() as cursor:
            harness._set_local(cursor, settings)
            if disable_seqscan:
                cursor.execute("SET LOCAL enable_seqscan = off")
            cursor.execute(f"EXPLAIN (FORMAT JSON) {sql}", params)
            raw_plan = cursor.fetchone()[0]
    return _plan_details(raw_plan, expected_index)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=999)
    parser.add_argument("--split-seed", type=int, default=None)
    args = parser.parse_args()

    attributes = pd.read_csv(ATTRIBUTE_FILE)
    vectors = read_fvecs(QUERY_FILE)
    queries = generate_queries(attributes, vectors, 10, seed=args.seed)
    split_seed = args.seed + 1 if args.split_seed is None else args.split_seed
    splits = split_queries(queries, calibration_fraction=0.5, seed=split_seed)
    split_by_id = {item.query_id: item.split for item in splits}
    calibration_queries = [query for query in queries if split_by_id[query.query_id] == "calibration"]
    query = calibration_queries[0]

    connection = psycopg.connect(**DatabaseConfig.from_env().connect_kwargs())
    try:
        harness = HeldOutHarness(connection, vectors, top_k=10, safety_factor=2.0)
        estimated_selectivity = harness.estimate_selectivity(query)
        candidate_budget = harness.candidate_budget(estimated_selectivity)
        default_plan = _explain(connection, harness, query, candidate_budget, disable_seqscan=False)
        forced_plan = _explain(connection, harness, query, candidate_budget, disable_seqscan=True)
    finally:
        connection.close()

    print(f"query_id: {query.query_id}")
    print(f"split: calibration")
    print(f"target_selectivity: {query.target_selectivity:.12f}")
    print(f"category: {query.category!r}")
    print(f"price_threshold: {query.price_threshold}")
    print(f"in_stock: {query.in_stock}")
    print(f"predicate: {query.predicate}")
    print(f"vector_id: {query.vector_id}")
    print(f"estimated_selectivity: {estimated_selectivity:.12f}")
    print(f"candidate_budget: {candidate_budget}")
    print(f"table: {TABLE_NAME}")
    print("default_plan: " + json.dumps(default_plan, sort_keys=True))
    print("enable_seqscan_off_plan: " + json.dumps(forced_plan, sort_keys=True))


if __name__ == "__main__":
    main()