"""FastAPI application that serves the dashboard and JSON APIs."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
import uvicorn

from .data import ScheduleRepository

BASE_DIR = Path(__file__).resolve().parents[2]
STATIC_DIR = Path(__file__).resolve().parent / "static"


def create_app() -> FastAPI:
    repo = ScheduleRepository(base_dir=BASE_DIR)
    app = FastAPI(title="Timetable Scheduler Dashboard", version="1.0.0")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    if STATIC_DIR.exists():
        app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    def _snapshot_or_404():
        try:
            return repo.get_latest_snapshot()
        except FileNotFoundError as exc:  # pragma: no cover - runtime path only
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/", include_in_schema=False)
    async def serve_dashboard() -> FileResponse:
        html_path = STATIC_DIR / "dashboard.html"
        if not html_path.exists():
            raise HTTPException(status_code=500, detail="dashboard.html is missing from the static folder")
        return FileResponse(html_path)

    @app.get("/slot-caps", include_in_schema=False)
    async def serve_slot_caps_dashboard() -> FileResponse:
        html_path = STATIC_DIR / "slot_caps_dashboard.html"
        if not html_path.exists():
            raise HTTPException(status_code=500, detail="slot_caps_dashboard.html is missing from the static folder")
        return FileResponse(html_path)

    @app.get("/teacher-labs", include_in_schema=False)
    async def serve_teacher_labs_dashboard() -> FileResponse:
        html_path = STATIC_DIR / "teacher_labs_dashboard.html"
        if not html_path.exists():
            raise HTTPException(status_code=500, detail="teacher_labs_dashboard.html is missing from the static folder")
        return FileResponse(html_path)

    @app.get("/grouping", include_in_schema=False)
    async def serve_grouping_dashboard() -> FileResponse:
        html_path = STATIC_DIR / "grouping_dashboard.html"
        if not html_path.exists():
            raise HTTPException(status_code=500, detail="grouping_dashboard.html is missing from the static folder")
        return FileResponse(html_path)

    @app.get("/overlaps", include_in_schema=False)
    async def serve_overlap_dashboard() -> FileResponse:
        html_path = STATIC_DIR / "overlap_dashboard.html"
        if not html_path.exists():
            raise HTTPException(status_code=500, detail="overlap_dashboard.html is missing from the static folder")
        return FileResponse(html_path)

    @app.get("/validation", include_in_schema=False)
    async def serve_validation_dashboard() -> FileResponse:
        html_path = STATIC_DIR / "validation_dashboard.html"
        if not html_path.exists():
            raise HTTPException(status_code=500, detail="validation_dashboard.html is missing from the static folder")
        return FileResponse(html_path)

    @app.get("/schedule", include_in_schema=False)
    async def serve_schedule_view() -> FileResponse:
        html_path = STATIC_DIR / "schedule_view.html"
        if not html_path.exists():
            raise HTTPException(status_code=500, detail="schedule_view.html is missing from the static folder")
        return FileResponse(html_path)

    @app.get("/rooms", include_in_schema=False)
    async def serve_room_view() -> FileResponse:
        html_path = STATIC_DIR / "room_view.html"
        if not html_path.exists():
            raise HTTPException(status_code=500, detail="room_view.html is missing from the static folder")
        return FileResponse(html_path)

    @app.get("/api/health")
    async def healthcheck() -> Dict[str, Any]:
        return {"status": "ok"}

    @app.get("/api/latest-folder")
    async def latest_folder() -> Dict[str, Any]:
        snapshot = _snapshot_or_404()
        return snapshot.as_dict()

    @app.get("/api/schedule")
    async def schedule() -> Dict[str, Any]:
        snapshot = _snapshot_or_404()
        data = repo.get_schedule()
        return {"snapshot": snapshot.as_dict(), "data": data}

    @app.get("/api/metrics")
    async def metrics() -> Dict[str, Any]:
        _snapshot_or_404()
        data = repo.get_metrics()
        return data

    @app.get("/api/rooms")
    async def rooms() -> Dict[str, Any]:
        _snapshot_or_404()
        return repo.get_rooms()

    @app.get("/api/slot-caps")
    async def slot_caps() -> Dict[str, Any]:
        snapshot = _snapshot_or_404()
        data = repo.get_slot_cap_telemetry()
        return {"snapshot": snapshot.as_dict(), "data": data}

    @app.get("/api/teacher-labs")
    async def teacher_labs() -> Dict[str, Any]:
        snapshot = _snapshot_or_404()
        data = repo.get_teacher_lab_telemetry()
        return {"snapshot": snapshot.as_dict(), "data": data}

    @app.get("/api/grouping")
    async def grouping() -> Dict[str, Any]:
        snapshot = _snapshot_or_404()
        data = repo.get_grouping_telemetry()
        return {"snapshot": snapshot.as_dict(), "data": data}

    @app.get("/api/overlaps")
    async def overlaps() -> Dict[str, Any]:
        snapshot = _snapshot_or_404()
        data = repo.get_overlap_telemetry()
        return {"snapshot": snapshot.as_dict(), "data": data}

    @app.get("/api/validation")
    async def validation() -> Dict[str, Any]:
        snapshot = _snapshot_or_404()
        data = repo.get_validation_telemetry()
        return {"snapshot": snapshot.as_dict(), "data": data}

    @app.get("/api/solver-metrics")
    async def solver_metrics() -> Dict[str, Any]:
        snapshot = _snapshot_or_404()
        data = repo.get_solver_metrics()
        return {"snapshot": snapshot.as_dict(), "data": data}

    @app.get("/api/warm-start")
    async def warm_start() -> Dict[str, Any]:
        snapshot = _snapshot_or_404()
        data = repo.get_warm_start_snapshot_summary()
        return {"snapshot": snapshot.as_dict(), "data": data}

    return app


def main() -> None:  # pragma: no cover - CLI entry point
    parser = argparse.ArgumentParser(description="Run the timetable dashboard server")
    parser.add_argument("--host", default="0.0.0.0", help="Host interface to bind")
    parser.add_argument("--port", type=int, default=8000, help="Port to listen on")
    parser.add_argument("--reload", action="store_true", help="Enable auto-reload (development only)")
    parser.add_argument(
        "--print-metrics",
        action="store_true",
        help="Print the latest snapshot metrics and exit",
    )
    args = parser.parse_args()

    if args.print_metrics:
        repo = ScheduleRepository(base_dir=BASE_DIR)
        snapshot = repo.get_latest_snapshot()
        metrics = repo.get_metrics()
        print(json.dumps({"snapshot": snapshot.as_dict(), "totals": metrics.get("totals")}, indent=2))
        return

    uvicorn.run("src.app.server:create_app", factory=True, host=args.host, port=args.port, reload=args.reload)


if __name__ == "__main__":  # pragma: no cover
    main()
