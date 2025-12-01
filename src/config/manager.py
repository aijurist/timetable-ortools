"""Configuration loader and helper utilities for scheduler modules."""

from __future__ import annotations

import json
import logging
import os
from copy import deepcopy
from dataclasses import asdict
from pathlib import Path
from typing import Any, Dict, Mapping, Optional

import yaml

from .defaults import default_scheduler_config
from .schemas import (
	ConstraintConfig,
	ConstraintSetting,
	DataSourceConfig,
	DepartmentConfig,
	DepartmentSettings,
	GroupingConfig,
	LoggingConfig,
	MetaConfig,
	ModelConfig,
	PathConfig,
	PreprocessingConfig,
	RuntimeConfig,
	SchedulerConfig,
	ShiftTemplate,
	TimeSystemConfig,
	ValidationConfig,
	WarmStartConfig,
)

logger = logging.getLogger(__name__)


def _deep_merge(base: Any, override: Any) -> Any:
	"""Recursively merge *override* into *base* without mutating inputs."""

	if isinstance(base, dict) and isinstance(override, Mapping):
		merged: Dict[str, Any] = deepcopy(base)
		for key, value in override.items():
			if key in merged:
				merged[key] = _deep_merge(merged[key], value)
			else:
				merged[key] = deepcopy(value)
		return merged

	if isinstance(override, Mapping):
		return {key: deepcopy(value) for key, value in override.items()}

	if isinstance(override, list):
		return [deepcopy(item) for item in override]

	return deepcopy(override)


def _serialise_for_output(value: Any) -> Any:
	"""Convert dataclass-friendly values (Path, tuples) for YAML/JSON output."""

	if isinstance(value, Path):
		return str(value)
	if isinstance(value, tuple):
		return [_serialise_for_output(item) for item in value]
	if isinstance(value, list):
		return [_serialise_for_output(item) for item in value]
	if isinstance(value, dict):
		return {key: _serialise_for_output(val) for key, val in value.items()}
	return value


class ConfigManager:
	"""Load, merge, and expose scheduler configuration values."""

	ENV_TIMEOUT = "SCHEDULER_TIMEOUT_SECONDS"
	ENV_THREADS = "SCHEDULER_THREAD_COUNT"
	ENV_LOG_LEVEL = "SCHEDULER_LOG_LEVEL"
	ENV_OUTPUT_ROOT = "SCHEDULER_OUTPUT_DIR"
	ENV_COURSES_CSV = "SCHEDULER_COURSES_CSV"
	ENV_ROOMS_CSV = "SCHEDULER_ROOMS_CSV"
	ENV_ENVIRONMENT = "SCHEDULER_ENVIRONMENT"

	def __init__(
		self,
		base_dir: Optional[Path | str] = None,
		defaults: Optional[SchedulerConfig] = None,
	) -> None:
		self.base_dir = Path(base_dir).resolve() if base_dir else Path.cwd()
		self._defaults = defaults or default_scheduler_config()
		self._config: Optional[SchedulerConfig] = None
		self._raw_dict: Dict[str, Any] = {}
		self._source_path: Optional[Path] = None

	@property
	def config(self) -> SchedulerConfig:
		if self._config is None:
			logger.debug("Configuration not loaded explicitly; using defaults")
			self._config = self._defaults
			self._raw_dict = asdict(self._defaults)
		return self._config

	@property
	def raw_dict(self) -> Dict[str, Any]:
		return deepcopy(self._raw_dict)

	@property
	def source_path(self) -> Optional[Path]:
		return self._source_path

	def load(
		self,
		config_path: Optional[Path | str] = None,
		overrides: Optional[Mapping[str, Any]] = None,
		strict: bool = False,
	) -> SchedulerConfig:
		"""Load configuration from YAML, applying overrides and validation."""

		base_dict = asdict(self._defaults)
		user_dict: Dict[str, Any] = {}

		path: Optional[Path] = Path(config_path).resolve() if config_path else None
		if path:
			if not path.exists():
				message = f"Configuration file not found: {path}"
				if strict:
					raise FileNotFoundError(message)
				logger.warning("%s; continuing with defaults", message)
			else:
				try:
					with path.open("r", encoding="utf-8") as handle:
						user_dict = yaml.safe_load(handle) or {}
					logger.info("Loaded configuration overrides from %s", path)
				except yaml.YAMLError as exc:
					if strict:
						raise ValueError(f"Failed to parse configuration file {path}: {exc}") from exc
					logger.warning("YAML parsing failed for %s (%s); falling back to defaults", path, exc)

		merged = _deep_merge(base_dict, user_dict)
		if overrides:
			merged = _deep_merge(merged, overrides)

		merged = self._apply_environment_overrides(merged)

		config = self._build_scheduler_config(merged, self.base_dir)

		self._config = config
		self._raw_dict = merged
		self._source_path = path
		return config

	def to_dict(self) -> Dict[str, Any]:
		"""Return configuration as a plain dictionary suitable for serialisation."""

		return _serialise_for_output(asdict(self.config))

	def to_json(self, *, indent: int = 2) -> str:
		return json.dumps(self.to_dict(), indent=indent)

	def save_sample(self, destination: Path | str) -> Path:
		"""Save the default configuration to *destination* as YAML."""

		destination_path = Path(destination)
		destination_path.parent.mkdir(parents=True, exist_ok=True)
		with destination_path.open("w", encoding="utf-8") as handle:
			yaml.safe_dump(_serialise_for_output(asdict(self._defaults)), handle, sort_keys=False)
		logger.info("Wrote sample configuration to %s", destination_path)
		return destination_path

	# ------------------------------------------------------------------
	# Internal helpers
	# ------------------------------------------------------------------

	@classmethod
	def _build_scheduler_config(cls, data: Mapping[str, Any], base_dir: Path) -> SchedulerConfig:
		meta = MetaConfig(**data["meta"])

		paths = PathConfig(**data["paths"]).resolve(base_dir)

		data_cfg = DataSourceConfig(**data["data"])
		time_cfg = TimeSystemConfig(**data["time"])

		dept_payload = data["departments"]
		default_settings = DepartmentSettings(**dept_payload["default_settings"])
		overrides = {
			name: DepartmentSettings(**settings) for name, settings in dept_payload.get("overrides", {}).items()
		}
		shift_templates = {
			name: ShiftTemplate(**template) for name, template in dept_payload.get("shift_templates", {}).items()
		}
		departments = DepartmentConfig(
			default_settings=default_settings,
			overrides=overrides,
			shift_templates=shift_templates,
			flexible_lunch_departments=dept_payload.get("flexible_lunch_departments", ()),
			five_pm_constraints=dept_payload.get("five_pm_constraints", {}),
		)

		preprocessing = PreprocessingConfig(**data["preprocessing"])
		grouping = GroupingConfig(**data["grouping"])

		constraints_payload = data["constraints"]
		constraint_config = ConstraintConfig(
			lab={name: ConstraintSetting(**value) for name, value in constraints_payload.get("lab", {}).items()},
			theory={name: ConstraintSetting(**value) for name, value in constraints_payload.get("theory", {}).items()},
			cross_system={
				name: ConstraintSetting(**value) for name, value in constraints_payload.get("cross_system", {}).items()
			},
		)

		model = ModelConfig(**data["model"])
		runtime_payload = dict(data["runtime"])
		warm_start_payload = runtime_payload.get("warm_start")
		if isinstance(warm_start_payload, Mapping):
			runtime_payload["warm_start"] = WarmStartConfig(**warm_start_payload)
		elif not isinstance(warm_start_payload, WarmStartConfig):
			runtime_payload["warm_start"] = WarmStartConfig()
		runtime = RuntimeConfig(**runtime_payload)
		logging_cfg = LoggingConfig(**data["logging"])
		validation = ValidationConfig(**data["validation"])

		return SchedulerConfig(
			meta=meta,
			paths=paths,
			data=data_cfg,
			time=time_cfg,
			departments=departments,
			preprocessing=preprocessing,
			grouping=grouping,
			constraints=constraint_config,
			model=model,
			runtime=runtime,
			logging=logging_cfg,
			validation=validation,
		)

	def _apply_environment_overrides(self, config_dict: Dict[str, Any]) -> Dict[str, Any]:
		merged = deepcopy(config_dict)

		if self.ENV_TIMEOUT in os.environ:
			try:
				merged["runtime"]["time_limit_sec"] = int(os.environ[self.ENV_TIMEOUT])
			except ValueError:
				logger.warning("Invalid integer for %s", self.ENV_TIMEOUT)

		if self.ENV_THREADS in os.environ:
			try:
				merged["runtime"]["thread_count"] = int(os.environ[self.ENV_THREADS])
			except ValueError:
				logger.warning("Invalid integer for %s", self.ENV_THREADS)

		if self.ENV_LOG_LEVEL in os.environ:
			merged.setdefault("logging", {})["level"] = os.environ[self.ENV_LOG_LEVEL]

		if self.ENV_OUTPUT_ROOT in os.environ:
			merged.setdefault("paths", {})["output_root"] = os.environ[self.ENV_OUTPUT_ROOT]

		if self.ENV_COURSES_CSV in os.environ:
			merged.setdefault("paths", {})["courses_csv"] = os.environ[self.ENV_COURSES_CSV]

		if self.ENV_ROOMS_CSV in os.environ:
			merged.setdefault("paths", {})["rooms_csv"] = os.environ[self.ENV_ROOMS_CSV]

		if self.ENV_ENVIRONMENT in os.environ:
			merged.setdefault("meta", {})["environment"] = os.environ[self.ENV_ENVIRONMENT]

		return merged


__all__ = ["ConfigManager"]
