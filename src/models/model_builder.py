
"""CP-SAT model construction scaffold for the modular scheduler."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Iterable, List, Mapping, MutableMapping, Optional, Sequence, Tuple

from ortools.sat.python import cp_model

from ..config.schemas import SchedulerConfig
from ..constraints.context import ConstraintContext
from ..constraints.registry import get_constraint_registrations
from ..constraints.schema import (
	ConstraintApplicationResult,
	ConstraintRegistration,
	ConstraintStatus,
)
from ..data.schemas import ExtendedDataContainer
from .variables import VariableCreationResult, VariableCreator

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ConstraintModel:
	"""Return type for :class:`ModelBuilder.build`."""

	model: cp_model.CpModel
	variables: VariableCreationResult
	constraint_results: Tuple[ConstraintApplicationResult, ...]
	metadata: Mapping[str, object]
	extras: Mapping[str, object]


class ModelBuilder:
	"""Core orchestrator that wires variables, constraints, and metadata."""

	def __init__(
		self,
		config: SchedulerConfig,
		*,
		constraint_loader=get_constraint_registrations,
		variable_creator_cls: type[VariableCreator] = VariableCreator,
		logger_: Optional[logging.Logger] = None,
	) -> None:
		self._config = config
		self._constraint_loader = constraint_loader
		self._variable_creator_cls = variable_creator_cls
		self._logger = logger_ or logging.getLogger(__name__)

	def build(
		self,
		data: ExtendedDataContainer,
		*,
		model: Optional[cp_model.CpModel] = None,
	) -> ConstraintModel:
		"""Create variables, apply registered constraints, and return the model."""

		model_instance = model or cp_model.CpModel()
		self._logger.info("Creating solver variables via VariableCreator")
		variable_creator = self._variable_creator_cls(data, logger_=self._logger.getChild("VariableCreator"))
		variables = variable_creator.create(model_instance)

		context = ConstraintContext(
			model=model_instance,
			config=self._config,
			data=data,
			variables=variables,
			logger=self._logger.getChild("Constraints"),
		)

		registrations = self._load_registrations()
		constraint_results = self._apply_constraints(registrations, context)
		self._apply_objective_terms(context)
		metadata = self._compose_metadata(variables, constraint_results)

		return ConstraintModel(
			model=model_instance,
			variables=variables,
			constraint_results=constraint_results,
			metadata=metadata,
			extras=dict(context.extra),
		)

	def _load_registrations(self) -> Sequence[ConstraintRegistration]:
		registrations = list(self._constraint_loader(self._config) or ())
		registrations.sort(key=lambda entry: (entry.priority, entry.name.lower()))
		self._logger.debug("Loaded %d constraint registrations", len(registrations))
		return registrations

	def _apply_constraints(
		self,
		registrations: Sequence[ConstraintRegistration],
		context: ConstraintContext,
	) -> Tuple[ConstraintApplicationResult, ...]:
		results: List[ConstraintApplicationResult] = []
		for registration in registrations:
			result = self._apply_single_constraint(registration, context)
			results.append(result)
		return tuple(results)

	def _apply_single_constraint(
		self,
		registration: ConstraintRegistration,
		context: ConstraintContext,
	) -> ConstraintApplicationResult:
		if not registration.enabled:
			return self._make_result(registration, ConstraintStatus.SKIPPED, {"reason": "disabled"})

		self._logger.debug(
			"Applying constraint '%s' (domain=%s, priority=%s)",
			registration.name,
			registration.domain,
			registration.priority,
		)

		try:
			result = registration.builder(context)
		except Exception as exc:  # pragma: no cover - defensive logging
			self._logger.exception("Constraint '%s' failed", registration.name)
			return self._make_result(registration, ConstraintStatus.ERROR, {"error": str(exc)})

		if isinstance(result, ConstraintApplicationResult):
			return result
		if result is None:
			return self._make_result(registration, ConstraintStatus.APPLIED)
		if isinstance(result, Mapping):
			return self._make_result(registration, ConstraintStatus.APPLIED, dict(result))

		return self._make_result(
			registration,
			ConstraintStatus.APPLIED,
			{"details": result},
		)

	def _compose_metadata(
		self,
		variables: VariableCreationResult,
		constraint_results: Sequence[ConstraintApplicationResult],
	) -> Mapping[str, object]:
		enabled_constraints = sum(1 for result in constraint_results if result.enabled)
		applied_constraints = sum(1 for result in constraint_results if result.succeeded)
		metadata = {
			"lab_course_count": len(variables.lab.requirements),
			"group_count": len(variables.theory.requirements),
			"constraint_count": len(constraint_results),
			"enabled_constraints": enabled_constraints,
			"applied_constraints": applied_constraints,
		}
		return metadata

	@staticmethod
	def _make_result(
		registration: ConstraintRegistration,
		status: str,
		details: Optional[Mapping[str, object]] = None,
	) -> ConstraintApplicationResult:
		return ConstraintApplicationResult(
			name=registration.name,
			domain=registration.domain,
			priority=registration.priority,
			enabled=registration.enabled,
			status=status,
			details=dict(details or {}),
		)

	def _apply_objective_terms(self, context: ConstraintContext) -> None:
		"""Attach a minimisation objective if constraints registered penalty terms."""

		extra_bucket = context.extra.get("objective")
		if not isinstance(extra_bucket, Mapping):
			return
		penalties = extra_bucket.get("penalties")
		if not penalties:
			return
		proto = context.model.Proto()
		if proto.HasField("objective") and proto.objective.vars:
			self._logger.warning("Objective already defined; skipping penalty aggregation")
			return
		linear_terms = []
		for entry in penalties:
			weight = None
			var = None
			if isinstance(entry, Mapping):
				weight = entry.get("weight")
				var = entry.get("variable") or entry.get("var")
			elif isinstance(entry, tuple):
				if len(entry) >= 2:
					weight, var = entry[0], entry[1]
				else:
					continue
			if var is None:
				continue
			try:
				w_value = int(weight) if weight is not None else 1
			except (TypeError, ValueError):
				w_value = 1
			if w_value == 0:
				continue
			linear_terms.append(w_value * var)
		if not linear_terms:
			return
		context.model.Minimize(sum(linear_terms))
		self._logger.info("Objective minimises %d penalty terms", len(linear_terms))


__all__ = [
	"ConstraintModel",
	"ConstraintContext",
	"ConstraintApplicationResult",
	"ConstraintStatus",
	"ModelBuilder",
]


if __name__ == "__main__":
	from ortools.sat.python import cp_model
	from ..config.manager import ConfigManager
	from ..data.data_loader import DataLoader
	from ..data.preprocessing import DataPreprocessor
	from pathlib import Path

	base_dir = Path.cwd()
	config_manager = ConfigManager(base_dir=base_dir)
	config = config_manager.load()
	data_loader = DataLoader(config, base_dir=base_dir)
	res = data_loader.load()

	pre = DataPreprocessor(config)
	output = pre.build_extended_container(data=res)
	
	
	builder = ModelBuilder(config=config)
	constraint_model = builder.build(data=output)
	print(constraint_model.constraint_results)