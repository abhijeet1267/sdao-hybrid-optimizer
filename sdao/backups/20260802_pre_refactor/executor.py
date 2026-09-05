from __future__ import annotations

import time

import pandas as pd

from .planner import AdaptivePlanner
from .run_pre import run_pre
from .run_post import run_post
from .strategy_graph import run_graph
from .strategy_isect import run_isect


class Executor:
    """Route a predicate to the selected execution strategy."""

    def __init__(self):
        self.planner = AdaptivePlanner()

    def execute(self, predicate: str) -> dict:
        decision = self.planner.choose_strategy(predicate)
        strategy = decision["strategy"]

        start = time.time()
        if strategy == "PRE":
            result = run_pre(predicate)
        elif strategy == "POST":
            result = run_post(predicate)
        elif strategy == "GRAPH":
            result = run_graph(predicate)
        elif strategy == "ISECT":
            result = run_isect(predicate)
        else:
            result = {"latency_ms": 0.0, "vectors_scanned": 0, "topk": 0}

        latency = (time.time() - start) * 1000

        return {
            "predicate": predicate,
            "strategy": strategy,
            "rows": decision["rows"],
            "selectivity": decision["selectivity"],
            "latency_ms": latency,
            "result": result,
        }


if __name__ == "__main__":
    executor = Executor()
    queries = pd.read_csv("queries.csv")
    results = []

    for _, row in queries.iterrows():
        output = executor.execute(row["predicate"])
        results.append(output)
        print(output)

    pd.DataFrame(results).to_csv("executor_results.csv", index=False)
    print("\nSaved executor_results.csv")