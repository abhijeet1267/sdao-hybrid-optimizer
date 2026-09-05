import logging
import argparse
import os
import sys

# Ensure the current directory is in sys.path so we can import from the package
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from sdao.experiments.evaluate import Evaluator

def main():
    parser = argparse.ArgumentParser(description="SDAO: Selectivity-Driven Adaptive Optimizer for Hybrid Vector Search")
    parser.add_argument("--results", type=str, default="results", help="Directory to save results")
    parser.add_argument("--log-level", type=str, default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"], help="Logging level")
    
    args = parser.parse_args()
    
    # Configure logging
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(os.path.join(args.results, "sdao.log") if os.path.exists(args.results) else "sdao.log")
        ]
    )
    
    logger = logging.getLogger("SDAO")
    logger.info("Starting SDAO Pipeline")
    
    try:
        evaluator = Evaluator(results_dir=args.results)
        
        # 1. Run experiments
        df = evaluator.run()
        
        # 2. Generate plots
        evaluator.generate_plots(df)
        
        # 3. Generate summary metrics
        evaluator.generate_summary_table(df)
        
        logger.info("SDAO Pipeline completed successfully.")
        
    except Exception as e:
        logger.exception(f"Pipeline failed: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
