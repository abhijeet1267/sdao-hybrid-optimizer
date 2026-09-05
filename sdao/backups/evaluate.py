from __future__ import annotations

import pandas as pd

from .data_utils import load_queries
from .executor import Executor


class Evaluator:
    """Run the adaptive executor across all hybrid queries and collect metrics."""

    def __init__(self):
        self.executor = Executor()

    def run(self, output_path: str | None = None) -> pd.DataFrame:
        queries = load_queries()
        results = []
        for _, row in queries.iterrows():
            output = self.executor.execute(row["predicate"])
            results.append(output)

        df = pd.DataFrame(results)
        if output_path is not None:
            df.to_csv(output_path, index=False)
        return df


if __name__ == "__main__":
    evaluator = Evaluator()
    df = evaluator.run("results/evaluation_results.csv")
    print(df.head())
    print("\nSaved results/evaluation_results.csv")