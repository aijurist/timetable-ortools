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
)

logger = logging.getLogger(__name__)

def _deep_merge(base: Any, override: Any) -> Any:
    if isinstance(base, object) and isinstance(override, Mapping):
        merged: Optional[Dict[str: Any]] = deepcopy(base)
        for key, value in override.items():
            if key in merged:
                merged[key] = _deep_merge(merged[key], value)
            else:
                merged[key] = deepcopy(value)
        return merged
    
    if isinstance(override, Mapping):
        return {key: deepcopy(value) for key, value in override.items()}

    if isinstance(override, list):
        return [deepcopy(value) for value in override]
    
    return deepcopy(override)

def _serialize_for_output(value: any) -> any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, tuple):
        return [_serialize_for_output(val) for val in value]
    if isinstance(value, list):
        return [_serialize_for_output(val) for val in value]
    if isinstance(value,dict):
        return  {key: _serialize_for_output(val) for key, val in value.items()}
    

class ConfigManager:
    def __init__(self, base_dir: Optional[Path] = None, default: Optional[SchedulerConfig] = None):
        self.base_dir = Path(base_dir).resolve() if base_dir else Path.cwd()
        self.default = default or default_scheduler_config()
        self._config:Optional[SchedulerConfig] = None
        self._raw_dict:Dict[str, any] = {}
        self._source_path: Optional[Path] = None

    @property
    def config(self):
        if self._config is None:
            logger.debug('There is no _config given, reverting to default')
            self._config = self.default
            self._raw_dict = asdict(self._config)

        return self._config

    @property
    def raw_dict(self) -> Dict[str,any]:
        return deepcopy(self._raw_dict)

    @property
    def source_path(self) -> Optional[Path]:
        return self._source_path

    def load(self, config_path: Optional[Path|str], overrides:Optional[Mapping[str, Any]] , strict:bool = True) -> SchedulerConfig:
        path = Path(config_path).resolve() 
        base_dict = asdict(self.default)
        user_dict: Optional[Dict[str, Any]] = {}

        if path:
            if not path.exists():
                message = f"Configuration file not found: {path}"
                if strict:
                    raise FileNotFoundError(message)
                logger.warning("%s; continuing with defaults", message)
            else:
                try:
                    with path.open('r', encoding='utf-8') as handle:
                       user_dict = yaml.safe_load(handle) or {}
                    logger.info("Loaded configuration overrides from %s", path)
                except yaml.YAMLError as exc:
                    if strict:
                        raise ValueError(f"Failed to parse configuration file {path}: {exc}") from exc
                    logger.warning("YAML parsing failed for %s (%s); falling back to defaults", path, exc)

        merged = _deep_merge(base_dict, user_dict)

        if overrides:
            merged = _deep_merge(merged, overrides)

        @classmethod
        def _build_scheduler_config(cls,data: Mapping[str, Any], base_dir: Path) -> SchedulerConfig:
            meta = MetaConfig(**data['meta'])

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
            runtime = RuntimeConfig(**data["runtime"])
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

if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(name)s - %(levelname)s %(time)s')