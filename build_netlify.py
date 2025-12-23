import json
import shutil
import sys
from pathlib import Path

# Ensure src is in python path
sys.path.append(str(Path(__file__).parent))

from src.app.data import ScheduleRepository

def main():
    base_dir = Path(__file__).parent.resolve()
    dist_dir = base_dir / "dist"
    
    # Clean dist directory
    if dist_dir.exists():
        shutil.rmtree(dist_dir)
    dist_dir.mkdir()
    
    print(f"Building static site in {dist_dir}...")
    
    # Initialize repository
    repo = ScheduleRepository(base_dir=base_dir)
    
    # Override to use specific snapshot
    target_snapshot_name = "2025-12-24_00-55-42"
    target_path = base_dir / "output" / target_snapshot_name
    
    if not target_path.exists():
        print(f"Error: Target snapshot {target_snapshot_name} not found.")
        sys.exit(1)
        
    print(f"Forcing snapshot: {target_snapshot_name}")
    
    # Monkeypatch _scan_latest_snapshot to return our target
    from src.app.data import ScheduleSnapshot
    
    def get_target_snapshot(self):
        lab_path = target_path / "combined_lab_schedule.json"
        theory_path = target_path / "combined_theory_schedule.json"
        
        if lab_path.exists() and theory_path.exists():
            return ScheduleSnapshot(
                root=target_path,
                label=target_path.name,
                data_kind="combined",
                schedule_path=None,
                lab_path=lab_path,
                theory_path=theory_path,
                modified_at=max(lab_path.stat().st_mtime, theory_path.stat().st_mtime),
            )
        
        schedule_path = target_path / "schedule.json"
        if schedule_path.exists():
            return ScheduleSnapshot(
                root=target_path,
                label=target_path.name,
                data_kind="monolithic",
                schedule_path=schedule_path,
                lab_path=None,
                theory_path=None,
                modified_at=schedule_path.stat().st_mtime,
            )
            
        raise FileNotFoundError(f"No valid schedule data found in {target_path}")

    # Apply monkeypatch
    repo._scan_latest_snapshot = get_target_snapshot.__get__(repo, ScheduleRepository)

    try:
        snapshot = repo.get_latest_snapshot()
        print(f"Using snapshot: {snapshot.label}")
    except FileNotFoundError as e:
        print(f"Error: {e}")
        sys.exit(1)

    # 1. Copy Static Assets (src/app/static)
    static_src = base_dir / "src" / "app" / "static"
    if not static_src.exists():
        print("Error: src/app/static not found.")
        sys.exit(1)
        
    shutil.copytree(static_src, dist_dir, dirs_exist_ok=True)
    
    # Rename dashboard.html to index.html
    (dist_dir / "dashboard.html").rename(dist_dir / "index.html")
    
    # 1.5 Fix static paths in HTML files
    # The FastAPI app serves static files under /static/, but in our dist build
    # we copied them to the root. So we need to replace /static/ with / in all HTML files.
    print("Patching HTML file paths...")
    for html_file in dist_dir.glob("*.html"):
        content = html_file.read_text(encoding="utf-8")
        # Replace /static/css/ with /css/, /static/js/ with /js/, etc.
        # Simple replacement of "/static/" with "/" should work for src and href attributes
        new_content = content.replace('"/static/', '"/')
        new_content = new_content.replace("'/static/", "'/")
        html_file.write_text(new_content, encoding="utf-8")
    
    # 2. Generate API Data
    api_dir = dist_dir / "api"
    api_dir.mkdir()
    
    # Helper to write JSON
    def write_json(filename, data):
        with open(api_dir / f"{filename}.json", "w") as f:
            json.dump(data, f)
            
    print("Generating API responses...")
    
    # /api/latest-folder
    write_json("latest-folder", snapshot.as_dict())
    
    # /api/schedule
    schedule_data = repo.get_schedule()
    write_json("schedule", {"snapshot": snapshot.as_dict(), "data": schedule_data})
    
    # /api/metrics
    metrics_data = repo.get_metrics()
    write_json("metrics", metrics_data)
    
    # /api/rooms
    rooms_data = repo.get_rooms()
    write_json("rooms", rooms_data)
    
    # /api/slot-caps
    slot_caps_data = repo.get_slot_cap_telemetry()
    write_json("slot-caps", {"snapshot": snapshot.as_dict(), "data": slot_caps_data})
    
    # /api/teacher-labs
    teacher_labs_data = repo.get_teacher_lab_telemetry()
    write_json("teacher-labs", {"snapshot": snapshot.as_dict(), "data": teacher_labs_data})
    
    # /api/grouping
    grouping_data = repo.get_grouping_telemetry()
    write_json("grouping", {"snapshot": snapshot.as_dict(), "data": grouping_data})
    
    # /api/overlaps
    overlap_data = repo.get_overlap_telemetry()
    write_json("overlaps", {"snapshot": snapshot.as_dict(), "data": overlap_data})
    
    # /api/validation
    validation_data = repo.get_validation_telemetry()
    write_json("validation", {"snapshot": snapshot.as_dict(), "data": validation_data})
    
    # 3. Copy Root Legacy Files (Optional but requested "latest output")
    # We'll put them in a 'legacy' folder or just root if they don't conflict
    # schedule_website.html -> legacy_schedule.html
    # room_timetable.html -> legacy_rooms.html
    # course_selection.html -> legacy_course_selection.html
    # And their JS files
    
    legacy_files = [
        "schedule_website.html", "room_timetable.html", "course_selection.html",
        "schedule_viewer.js", "room_timetable.js", "course_selection.js"
    ]
    
    for fname in legacy_files:
        src_file = base_dir / fname
        if src_file.exists():
            shutil.copy(src_file, dist_dir / fname)
            
    # For legacy files to work, they might need the raw JSON files in a specific path
    # The legacy JS fetches from /api/latest-folder which returns {path: ...}
    # And then fetches {path}/combined_lab_schedule.json
    # We need to replicate the folder structure or mock it.
    # The snapshot path is absolute or relative.
    # Let's see what snapshot.as_dict()['path'] returns.
    # It returns str(self.root).
    # If it's absolute, the fetch will fail on web.
    # We should probably modify the legacy JS or just rely on the App dashboard.
    # But let's try to make it work.
    # We can copy the raw output files to dist/data and update the latest-folder response to point to 'data'
    # But we already wrote latest-folder.json with the real snapshot data.
    
    # Let's overwrite latest-folder.json to point to a relative path 'data'
    # and copy the files there.
    
    data_dir = dist_dir / "data"
    data_dir.mkdir(exist_ok=True)
    
    if snapshot.lab_path and snapshot.lab_path.exists():
        shutil.copy(snapshot.lab_path, data_dir / "combined_lab_schedule.json")
    if snapshot.theory_path and snapshot.theory_path.exists():
        shutil.copy(snapshot.theory_path, data_dir / "combined_theory_schedule.json")
        
    # Update latest-folder.json to point to 'data'
    # The legacy JS does: fetch(`${latestFolder}/combined_lab_schedule.json`)
    # So if latestFolder is "data", it fetches "data/combined_lab_schedule.json". Perfect.
    
    write_json("latest-folder", {
        "latestFolder": "data",
        "folder": snapshot.label,
        "generated_at": datetime.fromtimestamp(snapshot.modified_at, tz=timezone.utc).isoformat()
    })

    # 4. Generate _redirects for Netlify (crucial for manual drag-and-drop)
    print("Generating _redirects...")
    redirects_content = """
/api/latest-folder  /api/latest-folder.json  200
/api/schedule       /api/schedule.json       200
/api/metrics        /api/metrics.json        200
/api/rooms          /api/rooms.json          200
/api/slot-caps      /api/slot-caps.json      200
/api/teacher-labs   /api/teacher-labs.json   200
/api/grouping       /api/grouping.json       200
/api/overlaps       /api/overlaps.json       200
/api/validation     /api/validation.json     200

/slot-caps          /slot_caps_dashboard.html      200
/teacher-labs       /teacher_labs_dashboard.html   200
/grouping           /grouping_dashboard.html       200
/overlaps           /overlap_dashboard.html        200
/validation         /validation_dashboard.html     200
/schedule           /schedule_view.html            200
/rooms              /room_view.html                200
"""
    with open(dist_dir / "_redirects", "w") as f:
        f.write(redirects_content.strip())

    print("Build complete!")

if __name__ == "__main__":
    from datetime import datetime, timezone
    main()
