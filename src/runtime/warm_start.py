"""Warm-start snapshot management for CP-SAT timetable solves."""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Sequence

from ..config.schemas import SchedulerConfig, WarmStartConfig
from ..models.model_builder import ConstraintModel
from .extractor_schema import ScheduleExtractionResult

LOGGER = logging.getLogger(__name__)


class WarmStartManager:
    """Persist and reload solver assignments to prime subsequent solves."""

    SNAPSHOT_VERSION = 1

    def __init__(self, config: SchedulerConfig, *, base_dir: Optional[Path] = None) -> None:
        self._config = config
        self._settings: WarmStartConfig = config.runtime.warm_start
        self._base_dir = Path(base_dir or Path.cwd()).resolve()
        self._logger = LOGGER.getChild("WarmStart")
        self._cache_dir = self._resolve_cache_dir()

    def apply_hints(self, constraint_model: ConstraintModel) -> int:
        """Load the latest snapshot and seed the model with hint literals."""

        if not self._settings.enabled:
            return 0
        if constraint_model.variables is None:
            return 0
        payload = self._load_payload(constraint_model)
        if not payload:
            return 0
        try:
            return self._apply_payload(constraint_model, payload)
        except Exception:  # pragma: no cover - defensive guard
            self._logger.exception("Failed to apply warm-start payload")
            return 0

    def write_snapshot(
        self,
        schedule: ScheduleExtractionResult,
        constraint_model: ConstraintModel,
        *,
        output_dir: Optional[Path] = None,
    ) -> Optional[Path]:
        """Persist the current schedule as a warm-start snapshot."""

        if not self._settings.enabled:
            return None
        if constraint_model.variables is None:
            return None
        payload = self._build_payload(schedule, constraint_model, output_dir=output_dir)
        if not payload.get("lab_assignments") and not payload.get("theory_assignments"):
            self._logger.info("Warm-start snapshot has no assignments; skipping persist")
            return None
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        latest_path = self._cache_dir / "latest_snapshot.json"
        versioned_path = self._cache_dir / f"snapshot_{timestamp}.json"
        self._write_json(versioned_path, payload)
        self._write_json(latest_path, payload)
        if output_dir is not None:
            output_path = Path(output_dir) / "warm_start_snapshot.json"
            self._write_json(output_path, payload)
        self._logger.info("Saved warm-start snapshot with %s lab / %s theory entries", len(payload["lab_assignments"]), len(payload["theory_assignments"]))
        return latest_path

    # ------------------------------------------------------------------
    # Payload lifecycle helpers
    # ------------------------------------------------------------------

    def _load_payload(self, constraint_model: ConstraintModel) -> Optional[Dict[str, Any]]:
        path = self._cache_dir / "latest_snapshot.json"
        if not path.exists():
            self._logger.debug("No warm-start snapshot found at %s", path)
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            self._logger.warning("Warm-start snapshot %s is not valid JSON", path)
            return None
        if not self._is_payload_compatible(payload, constraint_model):
            return None
        return payload

    def _apply_payload(self, constraint_model: ConstraintModel, payload: Mapping[str, Any]) -> int:
        model = constraint_model.model
        variables = constraint_model.variables
        hinted: set[str] = set()
        hints_applied = 0
        max_literals = self._settings.max_hint_literals or 0

        def _limit_reached() -> bool:
            return bool(max_literals and hints_applied >= max_literals)

        def _try_hint(var, value: int = 1) -> None:
            nonlocal hints_applied
            if var is None or _limit_reached():
                return
            name = getattr(var, "Name", lambda: None)()
            if not name or name in hinted:
                return
            model.AddHint(var, value)
            hinted.add(name)
            hints_applied += 1

        lab_assignments = getattr(variables, "lab", None)
        if lab_assignments:
            lab_map = getattr(lab_assignments, "assignments", {}) or {}
            for record in payload.get("lab_assignments", []):
                if _limit_reached():
                    break
                teacher_map = lab_map.get(record.get("teacher_id")) or {}
                course_map = teacher_map.get(record.get("course_instance_id")) or {}
                day_map = course_map.get(record.get("day_index")) or {}
                session_map = day_map.get(record.get("session_name")) or {}
                var = session_map.get(record.get("room_id"))
                _try_hint(var)

        theory_block = getattr(variables, "theory", None)
        if theory_block and not _limit_reached():
            assignment_map = getattr(theory_block, "assignments", {}) or {}
            group_map = getattr(theory_block, "group_timeslots", {}) or {}
            room_map = getattr(theory_block, "room_assignments", {}) or {}
            for record in payload.get("theory_assignments", []):
                if _limit_reached():
                    break
                teacher_bucket = assignment_map.get(record.get("teacher_id")) or {}
                course_bucket = teacher_bucket.get(record.get("course_instance_id")) or {}
                day_bucket = course_bucket.get(record.get("day_index")) or {}
                var = day_bucket.get(record.get("slot_index"))
                _try_hint(var)
                group_id = record.get("group_id")
                if group_id:
                    group_day_bucket = group_map.get(group_id, {}).get(record.get("day_index"), {})
                    group_var = group_day_bucket.get(record.get("slot_index"))
                    _try_hint(group_var)
                room_id = record.get("room_id")
                if room_id:
                    room_teacher_bucket = room_map.get(record.get("teacher_id")) or {}
                    room_course_bucket = room_teacher_bucket.get(record.get("course_instance_id")) or {}
                    room_day_bucket = room_course_bucket.get(record.get("day_index")) or {}
                    room_slot_bucket = room_day_bucket.get(record.get("slot_index")) or {}
                    room_var = room_slot_bucket.get(room_id)
                    _try_hint(room_var)

        if hints_applied:
            self._logger.info("Applied %s warm-start hints (limit=%s)", hints_applied, max_literals or "unbounded")
        else:
            self._logger.info("Warm-start snapshot available but no hints were applied")
        return hints_applied

    # ------------------------------------------------------------------
    # Snapshot serialisation helpers
    # ------------------------------------------------------------------

    def _build_payload(
        self,
        schedule: ScheduleExtractionResult,
        constraint_model: ConstraintModel,
        *,
        output_dir: Optional[Path],
    ) -> Dict[str, Any]:
        signature = self._compute_signature(constraint_model)
        lab_records = [
            {
                "teacher_id": entry.teacher_id,
                "course_instance_id": entry.course_instance_id,
                "day_index": entry.day_index,
                "session_name": entry.session_name,
                "room_id": entry.room_id,
            }
            for entry in schedule.lab_entries
            if entry.teacher_id and entry.course_instance_id
        ]
        theory_records = [
            {
                "teacher_id": entry.teacher_id,
                "course_instance_id": entry.course_instance_id,
                "group_id": entry.group_id,
                "day_index": entry.day_index,
                "slot_index": entry.slot_index,
                "room_id": entry.room_id,
            }
            for entry in schedule.theory_entries
            if entry.teacher_id and entry.course_instance_id and entry.group_id
        ]
        now = datetime.now(timezone.utc).replace(microsecond=0)
        metadata = {
            "created_at": now.isoformat(),
            "signature": signature,
            "config_name": self._config.meta.name,
            "config_version": self._config.meta.version,
            "lab_count": len(lab_records),
            "theory_count": len(theory_records),
            "output_dir": str(output_dir) if output_dir else None,
        }
        return {
            "version": self.SNAPSHOT_VERSION,
            "metadata": metadata,
            "lab_assignments": lab_records,
            "theory_assignments": theory_records,
        }

    def _is_payload_compatible(self, payload: Mapping[str, Any], constraint_model: ConstraintModel) -> bool:
        if payload.get("version") != self.SNAPSHOT_VERSION:
            self._logger.info(
                "Ignoring warm-start snapshot due to version mismatch (found %s)",
                payload.get("version"),
            )
            return False
        metadata = payload.get("metadata") or {}
        signature = metadata.get("signature")
        expected_signature = self._compute_signature(constraint_model)
        if self._settings.require_signature_match and signature != expected_signature:
            self._logger.info("Warm-start snapshot signature mismatch; skipping reuse")
            return False
        expiry_hours = self._settings.max_snapshot_age_hours
        created_at = metadata.get("created_at")
        if expiry_hours and created_at:
            created_time = self._parse_timestamp(created_at)
            if created_time:
                horizon = datetime.now(timezone.utc) - timedelta(hours=expiry_hours)
                if created_time < horizon:
                    self._logger.info("Warm-start snapshot expired (age > %sh)", expiry_hours)
                    return False
        return True

    def _compute_signature(self, constraint_model: ConstraintModel) -> str:
        variables = constraint_model.variables
        lab_keys: Sequence[str] = tuple(sorted((variables.lab.requirements or {}).keys())) if variables and variables.lab else tuple()
        theory_course_keys: Sequence[str] = (
            tuple(sorted((variables.theory.course_requirements or {}).keys()))
            if variables and variables.theory
            else tuple()
        )
        group_keys: Sequence[str] = (
            tuple(sorted((variables.theory.requirements or {}).keys()))
            if variables and variables.theory
            else tuple()
        )
        payload = {
            "config": {
                "name": self._config.meta.name,
                "version": self._config.meta.version,
            },
            "lab": lab_keys,
            "theory": theory_course_keys,
            "groups": group_keys,
        }
        return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()

    @staticmethod
    def _parse_timestamp(value: str) -> Optional[datetime]:
        token = value
        if token.endswith("Z"):
            token = token[:-1] + "+00:00"
        try:
            result = datetime.fromisoformat(token)
        except ValueError:
            return None
        return result if result.tzinfo else result.replace(tzinfo=timezone.utc)

    def _resolve_cache_dir(self) -> Path:
        configured = self._settings.snapshot_dir
        if configured is None:
            base = self._config.paths.output_root
        else:
            base = configured if configured.is_absolute() else (self._base_dir / configured)
        return (base / "warm_start_cache" if configured is None else base).resolve()

    @staticmethod
    def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


__all__ = ["WarmStartManager"]
