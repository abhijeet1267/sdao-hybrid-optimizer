"""Analytical latency model for the four physical hybrid-search plans."""
from __future__ import annotations
from dataclasses import dataclass
from math import ceil, log2


@dataclass(frozen=True)
class CostModel:
    """Costs are milliseconds and expose the assumptions used by the planner.

    The model separates a relational predicate scan, exact distance work, HNSW
    traversal, and set intersection. It is intentionally parameterised so that
    measurements from a different system can calibrate it without code changes.
    """
    top_k: int = 10
    min_ef: int = 128
    max_candidates: int = 50_000
    predicate_scan_ms_per_row: float = 0.000035
    distance_ms_per_vector: float = 0.000055
    hnsw_setup_ms: float = 0.08
    hnsw_ms_per_candidate: float = 0.00085
    membership_ms_per_candidate: float = 0.000012
    intersection_ms_per_id: float = 0.000020

    def candidate_budget(self, selectivity: float) -> int:
        if selectivity <= 0:
            return self.max_candidates
        # 99% probability of seeing k qualifying elements under a binomial model.
        expected = ceil((self.top_k + 4.61 * (self.top_k ** .5)) / selectivity)
        return min(self.max_candidates, max(self.min_ef, expected))

    def estimate_pre(self, n_total: int, selectivity: float) -> float:
        return self.predicate_scan_ms_per_row * n_total + self.distance_ms_per_vector * n_total * selectivity

    def estimate_post(self, n_total: int, selectivity: float) -> float:
        if selectivity <= 0:
            return float("inf")
        m = self.candidate_budget(selectivity)
        return self.hnsw_setup_ms + self.hnsw_ms_per_candidate * m * log2(n_total + 1) + self.membership_ms_per_candidate * m

    def estimate_graph(self, n_total: int, selectivity: float) -> float:
        if selectivity <= 0:
            return float("inf")
        # Native filtered traversal avoids materialising a post-filter candidate set,
        # but rejected graph nodes still cost a traversal visit.
        visits = self.candidate_budget(selectivity)
        return self.hnsw_setup_ms + self.hnsw_ms_per_candidate * visits * log2(n_total + 1) * 0.82

    def estimate_isect(self, n_total: int, selectivity: float) -> float:
        if selectivity <= 0:
            return float("inf")
        m = self.candidate_budget(selectivity)
        bitmap_lookup = self.predicate_scan_ms_per_row * n_total * 0.18
        return bitmap_lookup + self.hnsw_setup_ms + self.hnsw_ms_per_candidate * m * log2(n_total + 1) + self.intersection_ms_per_id * (m + n_total * selectivity)

    def estimate_all(self, n_total: int, selectivity: float) -> dict[str, float]:
        return {"PRE": self.estimate_pre(n_total, selectivity), "POST": self.estimate_post(n_total, selectivity), "GRAPH": self.estimate_graph(n_total, selectivity), "ISECT": self.estimate_isect(n_total, selectivity)}
