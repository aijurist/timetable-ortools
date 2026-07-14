from ortools.sat.python import cp_model

from src.constraints.base import ConstraintMetadata
from src.constraints.lab.consecutive_batches import (
	ConsecutiveBatchLabConstraint,
	ConsecutiveBatchStats,
)


def _constraint() -> ConsecutiveBatchLabConstraint:
	return ConsecutiveBatchLabConstraint(
		metadata=ConstraintMetadata(
			id="lab.consecutive_batches.test",
			name="Consecutive batches test",
			category="lab",
			priority=7,
		)
	)


def test_rejects_unpaired_session_and_lone_pair_side() -> None:
	model = cp_model.CpModel()
	l1 = model.NewBoolVar("l1")
	l2 = model.NewBoolVar("l2")
	l3 = model.NewBoolVar("l3")
	stats = ConsecutiveBatchStats()
	_constraint()._apply_day_pairs(
		model,
		"course",
		0,
		{"L1": {"R": l1}, "L2": {"R": l2}, "L3": {"R": l3}},
		(("L1", "L2"),),
		stats,
	)
	model.Add(l1 == 1)
	model.Add(l2 == 0)
	model.Add(l3 == 1)

	assert cp_model.CpSolver().Solve(model) == cp_model.INFEASIBLE


def test_rejects_available_side_when_partner_has_no_variables() -> None:
	model = cp_model.CpModel()
	l1 = model.NewBoolVar("l1")
	stats = ConsecutiveBatchStats()
	_constraint()._apply_day_pairs(
		model,
		"course",
		0,
		{"L1": {"R": l1}, "L2": {}},
		(("L1", "L2"),),
		stats,
	)
	model.Add(l1 == 1)

	assert cp_model.CpSolver().Solve(model) == cp_model.INFEASIBLE
