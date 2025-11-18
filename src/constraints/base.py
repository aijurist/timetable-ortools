"""Foundational types for modular constraint implementations.

This module provides the abstract :class:`Constraint` interface plus metadata
structures shared by all constraint implementations. Keeping these contracts in
one place allows constraint packages (lab, theory, cross-system, utilities) to
stay decoupled while the model builder can reason about them uniformly.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Mapping, Tuple, TYPE_CHECKING

from .schema import ConstraintApplicationResult

if TYPE_CHECKING:
	from .context import ConstraintContext


@dataclass(frozen=True)
class ConstraintMetadata:
	"""Describes an individual constraint for diagnostics and registry lookups."""

	id: str
	name: str
	category: str
	priority: int
	description: str = ""
	tags: Tuple[str, ...] = field(default_factory=tuple)
	weight: float = 1.0
	params: Mapping[str, object] = field(default_factory=dict)

	def as_dict(self) -> Mapping[str, object]:
		"""Return a JSON-serialisable snapshot useful for logging/metrics."""
		return {
			"id": self.id,
			"name": self.name,
			"category": self.category,
			"priority": self.priority,
			"description": self.description,
			"tags": list(self.tags),
			"weight": self.weight,
			"params": dict(self.params),
		}


class Constraint(ABC):
	"""Abstract base class every constraint module must implement."""

	def __init__(self, metadata: ConstraintMetadata, params: Mapping[str, object] | None = None) -> None:
		self._metadata = metadata
		self._params = dict(params or {})

	@property
	def metadata(self) -> ConstraintMetadata:
		"""Structured information about the constraint instance."""
		return self._metadata

	@property
	def params(self) -> Mapping[str, object]:
		"""Configuration parameters merged in from registry settings."""
		return self._params

	@property
	def name(self) -> str:
		"""Human-readable constraint name."""
		return self._metadata.name

	@property
	def category(self) -> str:
		"""Constraint domain, e.g., ``lab`` or ``theory``."""
		return self._metadata.category

	@property
	def priority(self) -> int:
		"""Ordering hint; higher numbers are applied first."""
		return self._metadata.priority

	def describe(self) -> str:
		"""Short text combining the constraint name and description."""
		return f"{self.name} ({self.category}, priority={self.priority})"

	@abstractmethod
	def apply(self, context: "ConstraintContext") -> "ConstraintApplicationResult":
		"""Apply constraint logic to the CP-SAT model.

		Implementations should mutate ``context.model`` by adding clauses or
		contribute penalty terms to the objective, then return whatever structure the
		``ModelBuilder`` expects (most commonly ``ConstraintApplicationResult``).
		"""
		raise NotImplementedError


__all__ = ["Constraint", "ConstraintMetadata"]
