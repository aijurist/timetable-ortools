"""Command-line interface for the modular timetable scheduler pipeline."""

import argparse
import logging
import sys
from pathlib import Path

from .orchestrator import PipelineOrchestrator

def setup_logging(level: str = "INFO") -> None:
    logging.basicConfig(
        level=level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)]
    )

def main() -> None:
    parser = argparse.ArgumentParser(description="Modular Timetable Scheduler CLI")
    parser.add_argument("--config", type=str, default="config/scheduler.yaml", help="Path to configuration file")
    parser.add_argument("--verbose", action="store_true", help="Enable verbose logging")
    
    args = parser.parse_args()
    
    setup_logging("DEBUG" if args.verbose else "INFO")
    
    try:
        orchestrator = PipelineOrchestrator(config_path=args.config)
        result = orchestrator.run()
        
        print("\nPipeline completed successfully!")
        if orchestrator._solver_result:
            print(f"Status: {orchestrator._solver_result.status}")
            if orchestrator._solver_result.objective_value is not None:
                print(f"Objective Value: {orchestrator._solver_result.objective_value}")
        
        # Summary of generated files
        output_dir = orchestrator.config.paths.output_root / "latest"
        print(f"\nOutput generated in: {output_dir}")
        print(f"- JSON: {output_dir / 'schedule.json'}")
        print(f"- CSV: {output_dir / 'csv'}")
        
    except Exception as e:
        logging.error("Pipeline execution failed", exc_info=True)
        sys.exit(1)

if __name__ == "__main__":
    main()
