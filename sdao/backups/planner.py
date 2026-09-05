from __future__ import annotations

from .cost_model import CostModel
from .estimator import SelectivityEstimator


class AdaptivePlanner:
    """Choose the cheapest strategy for a given predicate."""

    def __init__(self):
        self.estimator = SelectivityEstimator()
        self.cost_model = CostModel()

    def choose_strategy(self, predicate: str) -> dict:
        estimate = self.estimator.estimate(predicate)
        rows = estimate["rows"]
        selectivity = estimate["selectivity"]
        costs = self.cost_model.estimate_all(rows, selectivity)
        strategy = min(costs, key=costs.get)

        return {
            "predicate": predicate,
            "rows": rows,
            "selectivity": selectivity,
            "costs": costs,
            "strategy": strategy,
        }


if __name__ == "__main__":
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
        print("Query:", result["predicate"])
        print("Rows:", result["rows"])
        print("Selectivity:", round(result["selectivity"], 4))
        print("Costs:", result["costs"])
        print("Chosen Strategy:", result["strategy"])
