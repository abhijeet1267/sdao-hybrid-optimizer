from __future__ import annotations

import logging
import pandas as pd
from ..utils.data_loader import data_loader

logger = logging.getLogger(__name__)

class SelectivityEstimator:
    """Estimate row counts and selectivity from attribute predicates."""

    def __init__(self):
        self.df = data_loader.load_attributes()
        self.total_rows = len(self.df)
        logger.info(f"SelectivityEstimator initialized with {self.total_rows} rows.")

    def estimate(self, predicate: str) -> dict:
        """
        Estimates the number of rows and selectivity for a given SQL-like predicate.
        """
        try:
            # Use pandas query for estimation
            filtered = self.df.query(predicate)
            rows = int(len(filtered))
            selectivity = rows / self.total_rows if self.total_rows > 0 else 0.0
            
            return {
                "rows": rows,
                "selectivity": selectivity
            }
        except Exception as exc:
            logger.error(f"Error estimating selectivity for predicate '{predicate}': {exc}")
            return {"rows": 0, "selectivity": 0.0}

if __name__ == "__main__":
    # Test
    logging.basicConfig(level=logging.INFO)
    estimator = SelectivityEstimator()
    test_queries = [
        "category == 'Laptop'",
        "price < 500",
        "stock == True",
        "category == 'Phone' and price < 600",
    ]

    for q in test_queries:
        print(f"Query: {q} -> {estimator.estimate(q)}")
