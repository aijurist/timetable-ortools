"""Shared context objects passed into every constraint implementation.

The :class:`ConstraintContext` dataclass mirrors the payload previously defined
inside :mod:`src.models.model_builder`, making it importable by constraint
modules without creating circular dependencies.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import MutableMapping, TYPE_CHECKING

from ortools.sat.python import cp_model

from ..config.schemas import SchedulerConfig
from ..data.schemas import ExtendedDataContainer

if TYPE_CHECKING:  # pragma: no cover - type checking only
	from ..models.variables import VariableCreationResult
else:  # pragma: no cover - runtime placeholder to avoid circular import
	VariableCreationResult = object  # type: ignore[misc,assignment]


@dataclass(frozen=True)
class ConstraintContext:
	"""Bundle of artefacts shared by all constraints during application."""

	model: cp_model.CpModel
	config: SchedulerConfig
	data: ExtendedDataContainer
	variables: VariableCreationResult
	logger: logging.Logger
	extra: MutableMapping[str, object] = field(default_factory=dict)

	def child_logger(self, suffix: str) -> logging.Logger:
		"""Return a child logger for fine-grained tracing."""
		return self.logger.getChild(suffix)


__all__ = ["ConstraintContext"]
