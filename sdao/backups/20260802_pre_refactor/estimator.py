from __future__ import annotations

import pandas as pd

from .data_utils import ATTRIBUTE_FILE


class SelectivityEstimator:
    """Estimate row counts and selectivity from attribute predicates."""

    def __init__(self, attribute_file=ATTRIBUTE_FILE):
        self.df = pd.read_csv(attribute_file)
        self.total_rows = len(self.df)

    def estimate(self, predicate: str) -> dict:
        try:
            filtered = self.df.query(predicate)
            rows = int(len(filtered))
            return {"rows": rows, "selectivity": rows / self.total_rows if self.total_rows else 0.0}
        except Exception as exc:
            print(exc)
            return {"rows": 0, "selectivity": 0.0}


if __name__ == "__main__":
    est = SelectivityEstimator()
    tests = [
        "category == 'Laptop'",
        "price < 500",
        "stock == True",
        "category == 'Phone' and price < 600",
    ]

    for query in tests:
        print(query)
        print(est.estimate(query))
        print("-" * 50)
