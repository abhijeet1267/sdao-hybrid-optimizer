from __future__ import annotations

import logging
import numpy as np

logger = logging.getLogger(__name__)

class CostModel:
    """
    Estimate relative execution costs for each hybrid strategy.
    
    Formulas are based on standard vector database cost models:
    - PRE: Scan attributes + Exact search on filtered vectors.
    - POST: HNSW search + Filter results.
    - GRAPH: In-index filtered search (traversing while filtering).
    - ISECT: Intersecting vector results with attribute results.
    """

    def __init__(
        self, 
        c_scan: float = 0.01,    # Cost to scan one attribute row
        c_dist: float = 1.0,     # Cost to compute one vector distance
        c_hop: float = 5.0,      # Cost of one graph hop in HNSW
        k: int = 10,             # Target top-k
        ef: int = 200            # HNSW search parameter
    ):
        self.c_scan = c_scan
        self.c_dist = c_dist
        self.c_hop = c_hop
        self.k = k
        self.ef = ef

    def estimate_pre(self, n_total: int, selectivity: float) -> float:
        """
        Cost(PRE) = Scan all attributes + Exact search on filtered subset.
        """
        n_filtered = n_total * selectivity
        return (self.c_scan * n_total) + (self.c_dist * n_filtered)

    def estimate_post(self, n_total: int, selectivity: float) -> float:
        """
        Cost(POST) = HNSW search + Filtering candidates.
        To get K results with selectivity S, we expect to need K/S candidates.
        """
        if selectivity <= 0:
            return float("inf")
        
        # HNSW search cost is roughly proportional to log(N) * ef
        search_cost = self.c_hop * np.log2(n_total + 1) * self.ef
        
        # Filtering cost: we might need to oversample
        # If selectivity is 0.1, we need 10x oversampling on average
        oversampling = min(10000, self.k / selectivity) 
        filter_cost = self.c_scan * oversampling
        
        return search_cost + filter_cost

    def estimate_graph(self, n_total: int, selectivity: float) -> float:
        """
        Cost(GRAPH) = Filtered HNSW search.
        Hops increase as we search for valid nodes: hops ~ log(N) / selectivity.
        """
        if selectivity <= 0:
            return float("inf")
        
        # Rough model: each hop needs to find a filtered node, so hops increase by 1/S
        return self.c_hop * np.log2(n_total + 1) * (self.ef / selectivity)

    def estimate_isect(self, n_total: int, selectivity: float) -> float:
        """
        Cost(ISECT) = HNSW search + Attribute index search + Intersection.
        """
        # HNSW search cost
        v_search = self.c_hop * np.log2(n_total + 1) * self.ef
        
        # Attribute search (e.g., using an inverted index or bitmap)
        a_search = self.c_scan * n_total * 0.1 # Assume index is 10x faster than scan
        
        # Intersection cost
        intersect = self.c_scan * (n_total * selectivity + self.ef)
        
        return v_search + a_search + intersect

    def estimate_all(self, n_total: int, selectivity: float) -> dict[str, float]:
        return {
            "PRE": self.estimate_pre(n_total, selectivity),
            "POST": self.estimate_post(n_total, selectivity),
            "GRAPH": self.estimate_graph(n_total, selectivity),
            "ISECT": self.estimate_isect(n_total, selectivity),
        }

if __name__ == "__main__":
    model = CostModel()
    n = 1_000_000
    selectivities = [0.0001, 0.001, 0.01, 0.1, 0.5, 0.9]
    
    print(f"{'Selectivity':<12} | {'PRE':<10} | {'POST':<10} | {'GRAPH':<10} | {'ISECT':<10}")
    print("-" * 65)
    for s in selectivities:
        costs = model.estimate_all(n, s)
        print(f"{s:<12.4f} | {costs['PRE']:<10.1f} | {costs['POST']:<10.1f} | {costs['GRAPH']:<10.1f} | {costs['ISECT']:<10.1f}")
