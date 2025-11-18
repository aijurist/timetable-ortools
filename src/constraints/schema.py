"""Canonical schema objects shared across constraint packages.

Keeping these dataclasses in a dedicated module prevents circular imports
between :mod:`src.constraints` packages and :mod:`src.models` while providing a
single source of truth for constraint metadata.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Mapping, Tuple, TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - import cycle guard
	from .context import ConstraintContext
else:  # pragma: no cover - runtime placeholder
	ConstraintContext = object  # type: ignore[misc,assignment]


class ConstraintStatus:
	"""Light-weight enum describing the outcome of a constraint application."""

	APPLIED = "applied"
	SKIPPED = "skipped"
	ERROR = "error"

	@classmethod
	def is_success(cls, status: str) -> bool:
		return status == cls.APPLIED


@dataclass(frozen=True)
class ConstraintApplicationResult:
	"""Structured summary describing how a single constraint behaved."""

	name: str
	domain: str
	priority: int
	enabled: bool
	status: str
	details: Mapping[str, object] = field(default_factory=dict)

	@property
	def succeeded(self) -> bool:
		return ConstraintStatus.is_success(self.status)


ConstraintBuilder = Callable[["ConstraintContext"], "ConstraintApplicationResult"]


@dataclass(frozen=True)
class ConstraintRegistration:
	"""Metadata describing how to apply a constraint module."""

	name: str
	domain: str
	priority: int
	enabled: bool
	builder: ConstraintBuilder
	tags: Tuple[str, ...] = field(default_factory=tuple)
	parameters: Mapping[str, object] = field(default_factory=dict)


__all__ = [
	"ConstraintStatus",
	"ConstraintApplicationResult",
	"ConstraintRegistration",
	"ConstraintBuilder",
]
