"""Repeatable benchmark runner and paper-ready artifact generation."""
from __future__ import annotations
import json
import logging
import gc
from pathlib import Path
import matplotlib
# Experiments run headlessly; selecting a raster backend avoids GUI-framework
# aborts on workstations and CI agents without an active display server.
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd
import seaborn as sns
from ..core.executor import Executor
from ..utils.data_loader import data_loader

logger = logging.getLogger(__name__)


class Evaluator:
    def __init__(self, results_dir: str | Path = "results", executor: Executor | None = None) -> None:
        self.executor = executor or Executor()
        self.results_dir = Path(results_dir)
        self.csv_dir, self.plots_dir, self.logs_dir = (self.results_dir / x for x in ("csv", "plots", "logs"))
        for path in (self.csv_dir, self.plots_dir, self.logs_dir): path.mkdir(parents=True, exist_ok=True)

    def run(self) -> pd.DataFrame:
        queries = data_loader.load_queries()
        results = []
        for query_id, row in queries.reset_index(drop=True).iterrows():
            results.append({"query_type": row.get("type", "UNKNOWN"), **self.executor.execute(str(row.predicate), int(query_id))})
        df = pd.DataFrame(results)
        for strategy in ("PRE", "POST", "GRAPH", "ISECT"):
            df[f"cost_{strategy.lower()}_ms"] = df.planned_costs.map(lambda costs: costs[strategy])
        df.drop(columns=["planned_costs"]).to_csv(self.csv_dir / "evaluation_results.csv", index=False)
        with (self.csv_dir / "planner_decisions.json").open("w") as handle:
            json.dump(results, handle, default=str, indent=2)
        return df

    def run_strategy_benchmark(self, strategies: tuple[str, ...] = ("PRE", "POST", "GRAPH", "ISECT")) -> pd.DataFrame:
        """Execute every physical plan on every workload query for comparison."""
        queries = data_loader.load_queries().reset_index(drop=True)
        records = []
        for query_id, row in queries.iterrows():
            for strategy in strategies:
                records.append({"query_type": row.get("type", "UNKNOWN"), **self.executor.execute(str(row.predicate), int(query_id), strategy_override=strategy)})
                gc.collect()
        df = pd.DataFrame(records)
        for strategy in ("PRE", "POST", "GRAPH", "ISECT"):
            df[f"cost_{strategy.lower()}_ms"] = df.planned_costs.map(lambda costs: costs[strategy])
        df.drop(columns=["planned_costs"]).to_csv(self.csv_dir / "strategy_comparison.csv", index=False)
        summary = df.groupby("strategy", observed=True).agg(queries=("predicate", "count"), latency_ms_mean=("latency_ms", "mean"), latency_ms_median=("latency_ms", "median"), recall_at_10_mean=("recall_at_10", "mean"), vectors_scanned_mean=("vectors_scanned", "mean"), memory_mb_peak=("memory_mb", "max")).reset_index()
        summary.to_csv(self.csv_dir / "strategy_comparison_summary.csv", index=False)
        summary.to_latex(self.csv_dir / "strategy_comparison_summary.tex", index=False, float_format="%.4f")
        return df

    def generate_plots(self, df: pd.DataFrame) -> None:
        sns.set_theme(context="paper", style="whitegrid", font_scale=1.25)
        def save(name: str) -> None:
            plt.tight_layout(); plt.savefig(self.plots_dir / f"{name}.pdf", bbox_inches="tight"); plt.savefig(self.plots_dir / f"{name}.png", dpi=300, bbox_inches="tight"); plt.close()
        plot_df = df.copy(); plot_df["selectivity_plot"] = plot_df.selectivity.clip(lower=1e-6)
        plt.figure(figsize=(7.2, 4.4)); sns.scatterplot(data=plot_df, x="selectivity_plot", y="latency_ms", hue="strategy", s=70); plt.xscale("log"); plt.xlabel("Predicate selectivity"); plt.ylabel("End-to-end latency (ms)"); save("latency_vs_selectivity")
        plt.figure(figsize=(7.2, 4.4)); sns.scatterplot(data=plot_df, x="selectivity_plot", y="recall_at_10", hue="strategy", s=70); plt.xscale("log"); plt.ylim(-.03, 1.03); plt.xlabel("Predicate selectivity"); plt.ylabel("Filtered Recall@10"); save("recall_vs_selectivity")
        plt.figure(figsize=(6.4, 4.2)); order=[x for x in ("PRE","POST","GRAPH","ISECT") if x in df.strategy.unique()]; sns.countplot(data=df, x="strategy", order=order, hue="strategy", legend=False); plt.xlabel("Selected strategy"); plt.ylabel("Number of queries"); save("strategy_distribution")
        costs = df.melt(id_vars=["query_id", "strategy"], value_vars=[f"cost_{x.lower()}_ms" for x in ("PRE","POST","GRAPH","ISECT")], var_name="candidate_strategy", value_name="estimated_cost_ms"); costs.candidate_strategy=costs.candidate_strategy.str.extract(r"cost_(.*)_ms")[0].str.upper()
        plt.figure(figsize=(7.2, 4.4)); sns.lineplot(data=costs, x="query_id", y="estimated_cost_ms", hue="candidate_strategy", marker="o"); plt.yscale("log"); plt.xlabel("Query id"); plt.ylabel("Estimated cost (ms)"); save("execution_cost")
        plt.figure(figsize=(7.2, 4.4)); sns.scatterplot(data=df, x="query_id", y="selectivity", hue="strategy", style="query_type", s=75); plt.yscale("log"); plt.xlabel("Query id"); plt.ylabel("Predicate selectivity"); save("planner_decisions")

    def generate_summary_table(self, df: pd.DataFrame) -> pd.DataFrame:
        summary = df.groupby("strategy", observed=True).agg(queries=("predicate", "count"), latency_ms_mean=("latency_ms", "mean"), latency_ms_median=("latency_ms", "median"), recall_at_10_mean=("recall_at_10", "mean"), vectors_scanned_mean=("vectors_scanned", "mean"), memory_mb_peak=("memory_mb", "max")).reset_index()
        summary.to_csv(self.csv_dir / "summary_metrics.csv", index=False)
        (self.csv_dir / "summary_metrics.tex").write_text(summary.to_latex(index=False, float_format="%.4f"))
        decisions = df.groupby(["query_type", "strategy"], observed=True).size().rename("queries").reset_index()
        decisions.to_csv(self.csv_dir / "planner_decision_table.csv", index=False)
        (self.csv_dir / "planner_decision_table.tex").write_text(decisions.to_latex(index=False))
        return summary
