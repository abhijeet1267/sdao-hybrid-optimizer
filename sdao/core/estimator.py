"""Selectivity estimation backed by the materialised relational table."""
from __future__ import annotations
import pandas as pd
from ..utils.data_loader import DataLoader, data_loader


class SelectivityEstimator:
    def __init__(self, loader: DataLoader = data_loader) -> None:
        self.df = loader.load_attributes()
        self.total_rows = len(self.df)

    def matching_ids(self, predicate: str) -> pd.Series:
        try:
            return self.df.query(predicate, engine="python")["id"]
        except Exception as exc:
            raise ValueError(f"Invalid predicate {predicate!r}: {exc}") from exc

    def estimate(self, predicate: str) -> dict[str, float | int]:
        rows = len(self.matching_ids(predicate))
        return {"rows": rows, "selectivity": rows / self.total_rows if self.total_rows else 0.0}
