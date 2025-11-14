"""High-level orchestration for the modular timetable pipeline."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, Mapping, Optional

from ..config.manager import ConfigManager
from ..config.schemas import SchedulerConfig
from ..data.data_loader import DataLoader, DataLoadResult

logger = logging.getLogger(__name__)


class PipelineOrchestrator:
	"""Coordinate configuration loading and initial data extraction."""

	def __init__(self, config_path: Path | str = Path("config/scheduler.yaml"), *, base_dir: Optional[Path] = None) -> None:
		self._base_dir = Path(base_dir or Path.cwd()).resolve()
		candidate_path = Path(config_path)
		self._config_path = candidate_path if candidate_path.is_absolute() else (self._base_dir / candidate_path).resolve()
		self._config_manager = ConfigManager(base_dir=self._base_dir)
		self._config: Optional[SchedulerConfig] = None
		self._data: Optional[DataLoadResult] = None

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


__all__ = ["PipelineOrchestrator"]
