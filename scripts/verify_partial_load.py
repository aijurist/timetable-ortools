import sys
from pathlib import Path

# Add src to path
sys.path.append(str(Path.cwd()))

from src.config.manager import ConfigManager

def load_config(config_dir: Path):
    manager = ConfigManager(base_dir=Path.cwd())
    return manager.load(config_dir / "scheduler.yaml")
from src.constraints.cross_system.partial_schedule_loader import PartialScheduleLoaderSettings, PartialScheduleLoaderConstraint

def verify():
    print("Loading configuration...")
    config = load_config(config_dir=Path("config"))
    
    constraint_config = config.constraints.cross_system.get("partial_schedule_loader")
    if not constraint_config:
        print("ERROR: 'partial_schedule_loader' not found in cross_system constraints.")
        return
    
    if not constraint_config.enabled:
        print("WARNING: 'partial_schedule_loader' is disabled in config.")
    
    print(f"Partial Schedule Loader Configuration:")
    print(f"  Enabled: {constraint_config.enabled}")
    print(f"  Priority: {constraint_config.priority}")
    print(f"  Params: {constraint_config.params}")
    
    # Instantiate settings to check path resolution
    settings = PartialScheduleLoaderSettings.from_params(constraint_config.params)
    print(f"\nResolved Settings:")
    print(f"  Lab CSV: {settings.lab_csv_path}")
    print(f"  Theory CSV: {settings.theory_csv_path}")
    print(f"  Block Dept Slots Codes: {settings.block_dept_slots_course_codes}")

    # Create dummy metadata
    from src.constraints.base import ConstraintMetadata
    metadata = ConstraintMetadata(
        id="test.partial_loader",
        name="Test",
        category="cross_system",
        priority=1,
        description="Test",
    )
    
    constraint = PartialScheduleLoaderConstraint(metadata, params=constraint_config.params)
    
    # Test loading
    print("\nTesting CSV Loading...")
    lab_records, theory_records, source = constraint._load_from_csv(settings)
    
    print(f"  Source Info: {source}")
    print(f"  Loaded Lab Records: {len(lab_records)}")
    print(f"  Loaded Theory Records: {len(theory_records)}")
    
    if len(lab_records) > 0:
        print("\nFirst 3 Lab Records:")
        for r in lab_records[:3]:
            print(f"  {r}")
            
    if len(lab_records) == 0 :
        print("ERROR: No lab records loaded. Check path.")
    else:
        print("\nSUCCESS: Constraint configured and data loaded successfully.")

if __name__ == "__main__":
    verify()
