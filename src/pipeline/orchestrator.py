"""High-level orchestration for the modular timetable pipeline."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, Mapping, Optional
from datetime import datetime

from ..config.manager import ConfigManager
from ..config.schemas import SchedulerConfig
from ..data.data_loader import DataLoader, DataLoadResult
from ..data.preprocessing import DataPreprocessor
from ..data.schemas import ExtendedDataContainer
from ..models.model_builder import ConstraintModel, ModelBuilder
from ..runtime.extractor import ScheduleExtractor, ScheduleExtractionResult
from ..runtime.solver import SolverRunner, SolverResult
from ..telemetry.grouping import GroupTelemetryBuilder
from ..telemetry.overlaps import OverlapTelemetryBuilder
from ..telemetry.slot_caps import SlotCapTelemetryBuilder
from ..telemetry.teacher_labs import TeacherLabTelemetryBuilder

logger = logging.getLogger(__name__)


class PipelineOrchestrator:
	"""Coordinate configuration loading, data processing, solving, and extraction."""

	def __init__(self, config_path: Path | str = Path("config/scheduler.yaml"), *, base_dir: Optional[Path] = None) -> None:
		self._base_dir = Path(base_dir or Path.cwd()).resolve()
		candidate_path = Path(config_path)
		self._config_path = candidate_path if candidate_path.is_absolute() else (self._base_dir / candidate_path).resolve()
		self._config_manager = ConfigManager(base_dir=self._base_dir)
		self._config: Optional[SchedulerConfig] = None
		self._data: Optional[DataLoadResult] = None
		self._extended_data: Optional[ExtendedDataContainer] = None
		self._model: Optional[ConstraintModel] = None
		self._solver_result: Optional[SolverResult] = None
		self._schedule: Optional[ScheduleExtractionResult] = None
		self._latest_output_dir: Optional[Path] = None

	@property
	def config(self) -> SchedulerConfig:
		if self._config is None:
			logger.debug("Configuration not loaded; defaulting to lazy load with strict=False")
			self.load_config(strict=False)
		return self._config

	@property
	def data(self) -> DataLoadResult:
		if self._data is None:
			raise RuntimeError("Data not loaded; call load_data() or bootstrap() first")
		return self._data

	def load_config(
		self,
		overrides: Optional[Mapping[str, Any]] = None,
		*,
		strict: bool = True,
	) -> SchedulerConfig:
		"""Load scheduler configuration from disk, applying optional overrides."""

		logger.info("Loading scheduler configuration from %s", self._config_path)
		self._config = self._config_manager.load(self._config_path, overrides=overrides, strict=strict)
		return self._config

	def load_data(self) -> DataLoadResult:
		"""Load raw data artefacts using the active configuration."""

		loader = DataLoader(self.config, base_dir=self._base_dir)
		self._data = loader.load()
		return self._data

	def load_preprocessed_data(self) -> ExtendedDataContainer:
		"""Load preprocessed data artefacts using the active configuration."""
		if self._data is None:
			self.load_data()

		loader = DataPreprocessor(self.config, base_dir=self._base_dir)
		self._extended_data = loader.build_extended_container(self._data)
		return self._extended_data

	def build_model(self) -> ConstraintModel:
		"""Construct the CP-SAT model from preprocessed data."""
		if self._extended_data is None:
			self.load_preprocessed_data()

		builder = ModelBuilder(self.config)
		self._model = builder.build(self._extended_data)
		return self._model

	def solve(self) -> SolverResult:
		"""Run the solver on the built model."""
		if self._model is None:
			self.build_model()

		runner = SolverRunner(self.config)
		self._solver_result = runner.solve(self._model)
		return self._solver_result

	def extract(self) -> ScheduleExtractionResult:
		"""Extract the schedule from the solver result."""
		if self._solver_result is None:
			self.solve()

		# Ensure output directory exists
		output_dir = self.config.paths.output_root / "latest"
		output_dir.mkdir(parents=True, exist_ok=True)

		extractor = ScheduleExtractor(self._extended_data, self._model)
		timestamp_dir = self._base_dir / "output" / datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
		self._latest_output_dir = timestamp_dir
		self._schedule = extractor.export(
			self._solver_result,
			output_dir=timestamp_dir,
			write_json=True,
			write_csv=True,
		)
		self._write_slot_cap_telemetry(timestamp_dir, self._schedule)
		self._write_teacher_lab_telemetry(timestamp_dir, self._schedule)
		self._write_grouping_telemetry(timestamp_dir, self._schedule)
		self._write_overlap_telemetry(timestamp_dir, self._schedule)
		return self._schedule

	def run(self) -> ScheduleExtractionResult:
		"""Execute the full pipeline from config to extraction."""
		logger.info("Starting pipeline execution")
		self.load_config()
		self.load_data()
		self.load_preprocessed_data()
		self.build_model()
		self.solve()
		return self.extract()

	def bootstrap(
		self,
		*,
		overrides: Optional[Mapping[str, Any]] = None,
		strict: bool = True,
	) -> DataLoadResult:
		"""Convenience helper that loads configuration and data in succession."""

		self.load_config(overrides=overrides, strict=strict)
		return self.load_data()

	def config_dict(self) -> Dict[str, Any]:
		"""Return the active configuration as a serialisable dictionary."""

		return self._config_manager.to_dict()

	def legacy_snapshot(self) -> Dict[str, Any]:
		"""Expose a combined-scheduler-compatible payload of the loaded data."""

		if self._data is None:
			raise RuntimeError("Cannot produce snapshot before data is loaded")
		return self._data.to_legacy_dict()

	def summary(self) -> Dict[str, Any]:
		"""Return lightweight statistics for logging or quick inspection."""

		if self._data is None:
			raise RuntimeError("Cannot summarise without loaded data")

		data = self._data
		return {
			"config_path": str(self._config_path),
			"courses": len(data.courses_df),
			"rooms": len(data.rooms_df),
			"departments": len(data.departments_list),
			"teachers": len(data.teachers),
			"lab_room_ids": len(data.rooms.lab_room_ids),
			"theory_room_ids": len(data.rooms.theory_room_ids),
		}

	def _slot_cap_settings(self) -> Mapping[str, Mapping[str, Any]]:
		lab_constraints = getattr(self.config.constraints, "lab", {})
		relevant = {}
		for key in ("core_group_slot_cap", "computing_group_slot_cap", "semester_slot_cap"):
			setting = lab_constraints.get(key)
			if setting is None:
				continue
			relevant[key] = dict(setting.params or {})
		return relevant

	def _write_slot_cap_telemetry(self, output_dir: Path, schedule: ScheduleExtractionResult) -> None:
		if not self._model or not schedule:
			return
		builder = SlotCapTelemetryBuilder(
			constraint_results=self._model.constraint_results,
			slot_cap_settings=self._slot_cap_settings(),
		)
		try:
			builder.write(schedule, output_dir / "slot_caps_telemetry.json")
		except Exception:  # pragma: no cover - telemetry is best-effort
			logger.exception("Failed to write slot cap telemetry")

	def _write_teacher_lab_telemetry(self, output_dir: Path, schedule: ScheduleExtractionResult) -> None:
		if not self._model or not schedule:
			return
		builder = TeacherLabTelemetryBuilder(
			constraint_results=self._model.constraint_results,
		)
		try:
			builder.write(schedule, output_dir / "teacher_lab_telemetry.json")
		except Exception:  # pragma: no cover - telemetry is best-effort
			logger.exception("Failed to write teacher lab telemetry")

	def _write_grouping_telemetry(self, output_dir: Path, schedule: ScheduleExtractionResult) -> None:
		if not self._model or not schedule:
			return
		builder = GroupTelemetryBuilder(
			constraint_results=self._model.constraint_results,
		)
		try:
			builder.write(schedule, output_dir / "grouping_telemetry.json")
		except Exception:  # pragma: no cover - telemetry is best-effort
			logger.exception("Failed to write grouping telemetry")

	def _write_overlap_telemetry(self, output_dir: Path, schedule: ScheduleExtractionResult) -> None:
		if not self._model or not schedule or not self._extended_data:
			return
		builder = OverlapTelemetryBuilder(
			constraint_results=self._model.constraint_results,
			time_system=self._extended_data.raw.time,
		)
		try:
			builder.write(schedule, output_dir / "overlap_telemetry.json")
		except Exception:  # pragma: no cover - telemetry is best-effort
			logger.exception("Failed to write overlap telemetry")


__all__ = ["PipelineOrchestrator"]
