
import logging
import sys
from pathlib import Path

# Adjust path to find src
sys.path.append("d:/timetable-scheduler")

from src.pipeline.orchestrator import PipelineOrchestrator
from src.constraints.cross_system.teacher_day_window import TeacherDayWindowConstraint, TeacherDayWindowStats
from src.constraints.context import ConstraintContext
from src.constraints.base import ConstraintMetadata

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("debug_teacher_window")

def main():
    logger.info("Initializing PipelineOrchestrator...")
    orchestrator = PipelineOrchestrator(base_dir=Path("d:/timetable-scheduler"))
    
    # Load everything to build the model
    logger.info("Loading config and data...")
    orchestrator.load_config()
    orchestrator.load_data()
    orchestrator.load_preprocessed_data()
    
    logger.info("Building model (variables)...")
    model = orchestrator.build_model()
    
    logger.info("Setting up Constraint Context...")
    context = ConstraintContext(
        config=orchestrator.config,
        data=orchestrator._extended_data,
        model=model.model,
        variables=model.variables,
        logger=logger,
    )
    
    # Create the constraint instance manually
    metadata = ConstraintMetadata(
        name="teacher_day_window", 
        category="cross_system", 
        priority=9, 
        weight=1.0
    )
    # Pull params from config to ensure we test exactly what's configured
    params = orchestrator.config.constraints.cross_system.teacher_day_window.params
    logger.info(f"Constraint Params: {params}")
    
    constraint = TeacherDayWindowConstraint(metadata=metadata, params=params)
    stats = TeacherDayWindowStats()
    
    # Introspect forced windows logic directly
    logger.info("Loading forced windows...")
    forced_windows = constraint._load_forced_windows(context, stats)
    
    logger.info(f"Stats after loading: {stats.to_details()}")
    logger.info(f"Loaded {len(forced_windows)} forced windows.")
    
    if not forced_windows:
        logger.error("No forced windows loaded! Checking paths in config...")
        return

    # Check a few sample teachers
    sample_teachers = list(forced_windows.keys())[:5]
    logger.info(f"Sample forced windows: { {k: forced_windows[k] for k in sample_teachers} }")
    
    # Now simulate the application loop for a specific problematic teacher if possible
    # User mentioned: "solution found but not blocked"
    # Let's find a teacher who is forced 'mon_fri' -> should NOT have variables on 'saturday'
    # Or 'tue_sat' -> should NOT have variables on 'monday'
    
    conflicts_found = 0
    checks = 0
    
    logger.info("Checking variable day resolution...")
    
    # Create the constraint to access helper methods
    
    # We will manually iterate a few teachers to see if variables are found and days resolved correctly
    lab_teachers = list(context.variables.lab.assignments.keys())
    
    for teacher_id in lab_teachers:
        forced = forced_windows.get(teacher_id)
        if not forced:
            continue
            
        checks += 1
        # Iterate their variables and check day resolution
        from src.constraints.utils import iter_lab_session_variables
        
        for _tid, course_id, day_idx, session_name, _room_id, var in iter_lab_session_variables(context, teacher_id=teacher_id):
             day_label = constraint._resolve_course_day_label(
                context,
                context.variables.lab.day_patterns,
                course_id,
                day_idx,
            )
             
             if checks < 5:
                 logger.info(f"Teacher {teacher_id} (Forced: {forced}) -> Course {course_id} DayIdx {day_idx} -> Label '{day_label}'")
             
             if forced == "mon_fri" and day_label == "saturday":
                 # This SHOULD be blocked. If the constraint works, it adds model.Add(var == 0)
                 # We can't easily check if the model has the constraint added without inspecting the proto,
                 # but we can verify that the logic REACHES here.
                 pass
             elif forced == "tue_sat" and day_label == "monday":
                 pass
                 
    logger.info(f"Checked {checks} teachers against their variables.")
    logger.info("Script finished successfully.")

if __name__ == "__main__":
    main()
