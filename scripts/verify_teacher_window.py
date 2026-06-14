
import csv
import logging
import sys
from collections import defaultdict
from pathlib import Path

# Setup logging
logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("verify_teacher_window")

# Mock DayNormalizer for standalone script
class DayNormalizer:
    @staticmethod
    def normalize_day_name(day: str):
        if not day: return None
        d = day.strip().lower()
        if d in ["mon", "monday", "mon."]: return "monday"
        if d in ["tue", "tuesday", "tue."]: return "tuesday"
        if d in ["wed", "wednesday", "wed."]: return "wednesday"
        if d in ["thu", "thursday", "thur", "thurs"]: return "thursday"
        if d in ["fri", "friday", "fri."]: return "friday"
        if d in ["sat", "saturday", "sat."]: return "saturday"
        return d

def load_teacher_days(lab_path: Path, theory_path: Path):
    teacher_days = defaultdict(set)
    
    for path in [lab_path, theory_path]:
        if not path.exists():
            logger.error(f"File not found: {path}")
            continue
            
        logger.info(f"Loading {path}...")
        with path.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                teacher_id = (row.get("teacher_id") or "").strip()
                day_raw = row.get("day")
                day = DayNormalizer.normalize_day_name(day_raw)
                
                if teacher_id and day:
                    teacher_days[teacher_id].add(day)
    return teacher_days

def analyze_windows(teacher_days):
    stats = {
        "mon_fri": 0,
        "tue_sat": 0,
        "ambiguous": 0,
        "total": len(teacher_days)
    }
    
    issues = []
    
    for teacher_id, days in teacher_days.items():
        has_mon = "monday" in days
        has_sat = "saturday" in days
        
        status = "unknown"
        if has_mon and not has_sat:
            status = "mon_fri"
            stats["mon_fri"] += 1
        elif has_sat and not has_mon:
            status = "tue_sat"
            stats["tue_sat"] += 1
        else:
            status = "ambiguous"
            stats["ambiguous"] += 1
            if has_mon and has_sat:
                issues.append(f"Teacher {teacher_id} has BOTH Monday and Saturday: {sorted(days)}")
    
    return stats, issues

def main():
    base_dir = Path("d:/timetable-scheduler")
    lab_csv = base_dir / "data/final/2025-12-26_04-47-12/csv/lab_schedule.csv"
    theory_csv = base_dir / "data/final/2025-12-26_04-47-12/csv/theory_schedule.csv"
    
    logger.info("Verifying teacher day windows...")
    teacher_days = load_teacher_days(lab_csv, theory_csv)
    
    if not teacher_days:
        logger.error("No teacher data loaded!")
        sys.exit(1)
        
    stats, issues = analyze_windows(teacher_days)
    
    logger.info("--- Analysis Results ---")
    logger.info(f"Total Teachers found in fixed schedule: {stats['total']}")
    logger.info(f"Forced Mon-Fri: {stats['mon_fri']}")
    logger.info(f"Forced Tue-Sat: {stats['tue_sat']}")
    logger.info(f"Ambiguous (skipped): {stats['ambiguous']}")
    
    if issues:
        logger.warning(f"Found {len(issues)} teachers with conflicting fixed schedules (both Mon & Sat):")
        for i, issue in enumerate(issues[:10]):
            logger.warning(f"  {issue}")
        if len(issues) > 10:
            logger.warning(f"  ... and {len(issues) - 10} more.")
    else:
        logger.info("No teachers have both Monday and Saturday classes in the fixed schedule.")

if __name__ == "__main__":
    main()
