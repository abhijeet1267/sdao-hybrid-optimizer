from __future__ import annotations

import logging
from .estimator import SelectivityEstimator
from .cost_model import CostModel

logger = logging.getLogger(__name__)

class AdaptivePlanner:
    """Choose the cheapest strategy for a given predicate."""

    def __init__(self):
        self.estimator = SelectivityEstimator()
        self.cost_model = CostModel()
        logger.info("AdaptivePlanner initialized.")

    def choose_strategy(self, predicate: str) -> dict:
        """
        Plans the execution by estimating selectivity and choosing the strategy with minimum estimated cost.
        """
        # 1. Estimate selectivity
        estimate = self.estimator.estimate(predicate)
        n_total = self.estimator.total_rows
        rows = estimate["rows"]
        selectivity = estimate["selectivity"]
        
        # 2. Estimate costs
        costs = self.cost_model.estimate_all(n_total, selectivity)
        
        # 3. Choose the best strategy
        # Filter out strategies with infinite cost
        valid_costs = {k: v for k, v in costs.items() if v != float("inf")}
        
        if not valid_costs:
            logger.warning(f"No valid strategy found for predicate '{predicate}'. Defaulting to PRE.")
            chosen_strategy = "PRE"
        else:
            chosen_strategy = min(valid_costs, key=valid_costs.get)

        logger.info(f"Planned query '{predicate}': selectivity={selectivity:.4f}, chosen_strategy={chosen_strategy}")

        return {
            "predicate": predicate,
            "rows": rows,
            "selectivity": selectivity,
            "costs": costs,
            "strategy": chosen_strategy,
        }

if __name__ == "__main__":
    # Test
    logging.basicConfig(level=logging.INFO)
    planner = AdaptivePlanner()
    queries = [
        "category == 'Laptop'",
        "price < 500",
        "stock == True",
        "category == 'Phone' and price < 600",
        "brand == 'Apple' and rating > 4",
    ]

    for query in queries:
        result = planner.choose_strategy(query)
        print("=" * 60)
        print(f"Query: {result['predicate']}")
        print(f"Selectivity: {result['selectivity']:.4f}")
        print(f"Costs: {result['costs']}")
        print(f"Chosen Strategy: {result['strategy']}")
