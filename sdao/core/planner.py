from __future__ import annotations
from math import ceil

from .cost_model import CostModel
from .estimator import SelectivityEstimator


class AdaptivePlanner:
    """Plans each query from its observed relational selectivity."""
    def __init__(self, estimator: SelectivityEstimator | None = None, cost_model: CostModel | None = None,
                 target_recall: float = 0.95, top_k: int = 10) -> None:
        self.estimator = estimator or SelectivityEstimator()
        self.cost_model = cost_model or CostModel()
        self.target_recall = target_recall
        self.top_k = top_k

    def _estimate_strategy_recall(self, selectivity: float, candidate_budget: int, strategy: str) -> float:
        if strategy == "PRE":
            return 1.0
        if selectivity <= 0:
            return 0.0
        required_candidates = max(1, int(ceil(self.top_k / selectivity)))
        if candidate_budget >= required_candidates:
            return 1.0
        return candidate_budget / required_candidates

    def choose_strategy(self, predicate: str) -> dict:
        estimate = self.estimator.estimate(predicate)
        selectivity = float(estimate["selectivity"])
        costs = self.cost_model.estimate_all(self.estimator.total_rows, selectivity)
        candidate_budget = self.cost_model.candidate_budget(selectivity)
        estimated_recall = {
            strategy: self._estimate_strategy_recall(selectivity, candidate_budget, strategy)
            for strategy in costs
        }
        feasible_strategies = [strategy for strategy, recall in estimated_recall.items() if recall >= self.target_recall]
        if feasible_strategies:
            strategy = min(feasible_strategies, key=lambda name: costs[name])
        else:
            strategy = max(estimated_recall, key=estimated_recall.get)
        return {
            "predicate": predicate,
            **estimate,
            "costs": costs,
            "strategy": strategy,
            "candidate_budget": candidate_budget,
            "estimated_recall": estimated_recall,
            "feasible_strategies": feasible_strategies,
            "target_recall": self.target_recall,
        }
