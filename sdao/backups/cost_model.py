from __future__ import annotations


class CostModel:
    """Estimate relative execution costs for each hybrid strategy."""

    def __init__(self, scan_cost: float = 1.0, post_over_sampling: int = 100):
        self.scan_cost = scan_cost
        self.post_over_sampling = post_over_sampling

    def estimate_pre(self, rows: int) -> float:
        return rows * self.scan_cost

    def estimate_post(self, selectivity: float, oversampling: int | None = None) -> float:
        if selectivity <= 0:
            return float("inf")
        sample_size = oversampling or self.post_over_sampling
        return sample_size / max(selectivity, 1e-6) + 0.2 * sample_size

    def estimate_graph(self, rows: int) -> float:
        return rows * 0.7 + 20.0

    def estimate_isect(self, rows: int) -> float:
        return rows * 0.45 + 15.0

    def estimate_all(self, rows: int, selectivity: float) -> dict:
        return {
            "PRE": self.estimate_pre(rows),
            "POST": self.estimate_post(selectivity),
            "GRAPH": self.estimate_graph(rows),
            "ISECT": self.estimate_isect(rows),
        }


if __name__ == "__main__":
    model = CostModel()
    tests = [(124752, 0.124752), (230466, 0.230466), (500146, 0.500146), (35327, 0.035327)]

    for rows, sel in tests:
        print("=" * 50)
        print("Rows:", rows)
        print("Selectivity:", sel)
        print(model.estimate_all(rows, sel))
        