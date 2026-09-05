from __future__ import annotations

import logging
import os
from pathlib import Path
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
from tqdm import tqdm

from ..core.executor import Executor
from ..utils.data_loader import data_loader

logger = logging.getLogger(__name__)

class Evaluator:
    """Run the adaptive executor across all hybrid queries and collect metrics."""

    def __init__(self, results_dir: str = "results"):
        self.executor = Executor()
        self.results_dir = Path(results_dir)
        self.csv_dir = self.results_dir / "csv"
        self.plots_dir = self.results_dir / "plots"
        self.logs_dir = self.results_dir / "logs"
        
        # Create directories
        for d in [self.csv_dir, self.plots_dir, self.logs_dir]:
            d.mkdir(parents=True, exist_ok=True)

    def run(self) -> pd.DataFrame:
        queries = data_loader.load_queries()
        logger.info(f"Starting evaluation on {len(queries)} queries...")
        
        results = []
        for _, row in tqdm(queries.iterrows(), total=len(queries), desc="Evaluating Queries"):
            output = self.executor.execute(row["predicate"])
            results.append(output)

        df = pd.DataFrame(results)
        
        # Flatten planned_costs for CSV
        for strategy in ["PRE", "POST", "GRAPH", "ISECT"]:
            df[f"cost_{strategy}"] = df["planned_costs"].apply(lambda x: x.get(strategy, 0.0))
        
        # Save results
        output_path = self.csv_dir / "evaluation_results.csv"
        df.to_csv(output_path, index=False)
        logger.info(f"Saved evaluation results to {output_path}")
        
        return df

    def generate_plots(self, df: pd.DataFrame):
        logger.info("Generating plots...")
        sns.set_theme(style="whitegrid")

        # 1. Latency vs Selectivity
        plt.figure(figsize=(10, 6))
        sns.scatterplot(data=df, x="selectivity", y="actual_latency_ms", hue="strategy", style="strategy", s=100)
        plt.xscale('log')
        plt.yscale('log')
        plt.title("Latency vs Selectivity (Log Scale)")
        plt.xlabel("Selectivity")
        plt.ylabel("Latency (ms)")
        plt.savefig(self.plots_dir / "latency_vs_selectivity.png")
        plt.close()

        # 2. Recall vs Selectivity
        plt.figure(figsize=(10, 6))
        sns.scatterplot(data=df, x="selectivity", y="recall", hue="strategy", s=100)
        plt.xscale('log')
        plt.title("Recall vs Selectivity")
        plt.xlabel("Selectivity")
        plt.ylabel("Recall @ 10")
        plt.ylim(0, 1.1)
        plt.savefig(self.plots_dir / "recall_vs_selectivity.png")
        plt.close()

        # 3. Strategy Distribution
        plt.figure(figsize=(8, 6))
        df["strategy"].value_counts().plot(kind='pie', autopct='%1.1f%%', colors=sns.color_palette("pastel"))
        plt.title("Strategy Distribution")
        plt.ylabel("")
        plt.savefig(self.plots_dir / "strategy_distribution.png")
        plt.close()

        # 4. Latency Boxplot by Strategy
        plt.figure(figsize=(10, 6))
        sns.boxplot(data=df, x="strategy", y="actual_latency_ms")
        plt.yscale('log')
        plt.title("Latency Distribution by Strategy")
        plt.savefig(self.plots_dir / "latency_boxplot.png")
        plt.close()

        logger.info(f"Plots saved to {self.plots_dir}")

    def generate_summary_table(self, df: pd.DataFrame):
        summary = df.groupby("strategy").agg({
            "actual_latency_ms": ["mean", "std", "median"],
            "recall": ["mean", "max", "min"],
            "vectors_scanned": "mean",
            "predicate": "count"
        }).reset_index()
        
        summary.columns = ["Strategy", "Latency Mean (ms)", "Latency Std", "Latency Median", "Recall Mean", "Recall Max", "Recall Min", "Avg Vectors Scanned", "Query Count"]
        
        summary_path = self.csv_dir / "summary_metrics.csv"
        summary.to_csv(summary_path, index=False)
        logger.info(f"Summary metrics saved to {summary_path}")
        
        # Also print as Markdown table for the user
        print("\n### Evaluation Summary Table")
        print(summary.to_markdown(index=False))

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    evaluator = Evaluator()
    results_df = evaluator.run()
    evaluator.generate_plots(results_df)
    evaluator.generate_summary_table(results_df)
