"""Adaptive execution and consistent filter-aware evaluation metrics."""
from __future__ import annotations
import os
import time
import resource
from typing import Callable
from .planner import AdaptivePlanner
from ..strategies.pre import run_pre
from ..strategies.post import run_post
from ..strategies.graph import run_graph
from ..strategies.isect import run_isect


def _rss_mb() -> float:
    # macOS ru_maxrss is bytes; Linux reports KiB.
    value = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return value / (1024 * 1024) if os.uname().sysname == "Darwin" else value / 1024


class Executor:
    """Route a hybrid query and score it against its exact filtered top-k."""
    def __init__(self, planner: AdaptivePlanner | None = None) -> None:
        self.planner = planner or AdaptivePlanner()

    def execute(self, predicate: str, query_id: int = 0, top_k: int = 10, strategy_override: str | None = None) -> dict:
        decision = self.planner.choose_strategy(predicate)
        strategy = strategy_override or decision["strategy"]
        if strategy not in {"PRE", "POST", "GRAPH", "ISECT"}:
            raise ValueError(f"Unsupported strategy: {strategy}")
        budget = int(decision["candidate_budget"])
        functions: dict[str, Callable[..., dict]] = {
            "PRE": run_pre, "POST": run_post, "GRAPH": run_graph, "ISECT": run_isect,
        }
        started = time.perf_counter(); before = _rss_mb()
        if strategy == "PRE":
            result = run_pre(predicate, query_id, top_k)
            reference = result
        elif strategy == "POST":
            result = run_post(predicate, query_id, top_k, budget)
            reference = run_pre(predicate, query_id, top_k)
        elif strategy == "GRAPH":
            result = run_graph(predicate, query_id, top_k, budget)
            reference = run_pre(predicate, query_id, top_k)
        else:
            result = run_isect(predicate, query_id, top_k, budget)
            reference = run_pre(predicate, query_id, top_k)
        elapsed = (time.perf_counter() - started) * 1000
        expected = set(reference["topk"])
        recall = len(set(result["topk"]) & expected) / len(expected) if expected else 1.0
        return {
            "query_id": query_id, "predicate": predicate, "strategy": strategy,
            "rows": decision["rows"], "selectivity": decision["selectivity"],
            "candidate_budget": budget, "planned_costs": decision["costs"],
            "estimated_recall": decision.get("estimated_recall", {}),
            "feasible_strategies": decision.get("feasible_strategies", []),
            "target_recall": decision.get("target_recall", 0.95),
            "latency_ms": elapsed, "strategy_latency_ms": result["latency_ms"],
            "vectors_scanned": result["vectors_scanned"], "matched_rows": result["matched_rows"],
            "recall_at_10": recall, "memory_mb": max(before, _rss_mb()),
            "topk": result["topk"], "reference_topk": reference["topk"],
        }
