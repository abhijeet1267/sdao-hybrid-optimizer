"""Command-line entry point: python3 -m sdao.main --results results."""
from __future__ import annotations
import argparse
import logging
from pathlib import Path
from .experiments.evaluate import Evaluator


def main() -> None:
    parser = argparse.ArgumentParser(description="SDAO hybrid-query benchmark")
    parser.add_argument("--results", default="results", help="artifact directory")
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args()
    path = Path(args.results); (path / "logs").mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=args.log_level.upper(), format="%(asctime)s %(levelname)s %(name)s: %(message)s", handlers=[logging.StreamHandler(), logging.FileHandler(path / "logs" / "sdao.log")])
    evaluator = Evaluator(path); results = evaluator.run(); comparison = evaluator.run_strategy_benchmark(); evaluator.generate_plots(comparison); summary = evaluator.generate_summary_table(results)
    print(summary.to_string(index=False))

if __name__ == "__main__": main()
