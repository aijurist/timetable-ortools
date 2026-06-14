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
    logging.getLogger("matplotlib").setLevel(logging.WARNING)
    logging.getLogger("matplotlib.font_manager").setLevel(logging.WARNING)

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
            if getattr(orchestrator._solver_result, "solution_count", None) == 0 and orchestrator._solver_result.status not in ("FEASIBLE", "OPTIMAL"):
                print("Note: CP-SAT reported 0 feasible solutions; schedule export will be empty.")
            if orchestrator._solver_result.objective_value is not None:
                print(f"Objective Value: {orchestrator._solver_result.objective_value}")
        
        # Summary of generated files
        output_dir = orchestrator.latest_output_dir or (orchestrator.config.paths.output_root / "latest")
        print(f"\nOutput generated in: {output_dir}")
        artifacts = [
            ("Schedule JSON", output_dir / "schedule.json"),
            ("CSV bundle", output_dir / "csv"),
            ("Slot-cap telemetry", output_dir / "slot_caps_telemetry.json"),
            ("Teacher lab telemetry", output_dir / "teacher_lab_telemetry.json"),
            ("Grouping telemetry", output_dir / "grouping_telemetry.json"),
            ("Overlap telemetry", output_dir / "overlap_telemetry.json"),
            ("Validation telemetry", output_dir / "validation_telemetry.json"),
        ]
        for label, path in artifacts:
            print(f"- {label}: {path}")

        report = orchestrator.validation_report
        if report:
            severity = ", ".join(f"{key}={value}" for key, value in report.severity_counts.items()) or "no issues"
            print("\nValidation summary:")
            print(f"- Checks executed: {len(report.executed_checks)}")
            print(f"- Severity counts: {severity}")
        else:
            if orchestrator._solver_result and getattr(orchestrator._solver_result, "solution_count", None) == 0:
                print("\nValidation summary:")
                print("- Checks executed: 0")
                print("- Severity counts: error=0, warning=0")
                print("- Note: validation skipped because solver produced no feasible solution")
        
    except Exception as e:
        logging.error("Pipeline execution failed", exc_info=True)
        sys.exit(1)

if __name__ == "__main__":
    main()
