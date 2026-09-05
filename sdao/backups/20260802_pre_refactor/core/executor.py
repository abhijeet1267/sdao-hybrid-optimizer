from __future__ import annotations

import logging
import time
from .planner import AdaptivePlanner
from ..strategies.pre import run_pre
from ..strategies.post import run_post
from ..strategies.graph import run_graph
from ..strategies.isect import run_isect

logger = logging.getLogger(__name__)

class Executor:
    """Route a predicate to the selected execution strategy."""

    def __init__(self):
        self.planner = AdaptivePlanner()
        logger.info("Executor initialized.")

    def execute(self, predicate: str, top_k: int = 10) -> dict:
        """
        Executes a hybrid query using the best planned strategy.
        """
        # 1. Plan
        decision = self.planner.choose_strategy(predicate)
        strategy = decision["strategy"]
        
        logger.info(f"Executing '{predicate}' using {strategy} strategy.")
        
        start_time = time.time()
        
        # 2. Execute
        try:
            if strategy == "PRE":
                result = run_pre(predicate, top_k=top_k)
            elif strategy == "POST":
                # For POST, we use oversampling based on selectivity
                # Expected candidates = k / selectivity
                sel = max(decision["selectivity"], 0.001)
                oversampling = int(min(10000, top_k / sel * 2)) # extra buffer
                result = run_post(predicate, top_k=top_k, oversampling=oversampling)
            elif strategy == "GRAPH":
                # For GRAPH, we use high ef_search
                result = run_graph(predicate, top_k=top_k, ef_search=500)
            elif strategy == "ISECT":
                result = run_isect(predicate, top_k=top_k)
            else:
                logger.error(f"Unknown strategy: {strategy}")
                result = {"latency_ms": 0.0, "vectors_scanned": 0, "topk": [], "recall": 0.0}
        except Exception as e:
            logger.exception(f"Error during execution of strategy {strategy}: {e}")
            result = {"latency_ms": 0.0, "vectors_scanned": 0, "topk": [], "recall": 0.0, "error": str(e)}

        total_latency = (time.time() - start_time) * 1000

        # 3. Combine results
        return {
            "predicate": predicate,
            "strategy": strategy,
            "rows": decision["rows"],
            "selectivity": decision["selectivity"],
            "planned_costs": decision["costs"],
            "actual_latency_ms": total_latency,
            "strategy_latency_ms": result.get("latency_ms", 0.0),
            "vectors_scanned": result.get("vectors_scanned", 0),
            "recall": result.get("recall", 0.0),
            "topk": result.get("topk", []),
            "matched_rows": result.get("matched_rows", 0)
        }

if __name__ == "__main__":
    # Test
    logging.basicConfig(level=logging.INFO)
    executor = Executor()
    test_predicate = "category == 'Laptop' and price < 500"
    output = executor.execute(test_predicate)
    print(output)
