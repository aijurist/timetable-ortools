from src.constraints.cross_system.bundled_theory import _maximum_matching_size


def test_maximum_matching_pairs_unequal_load_candidates() -> None:
	edges = {(0, 1): object(), (0, 2): object(), (1, 3): object(), (2, 3): object()}

	assert _maximum_matching_size(4, edges) == 2


def test_maximum_matching_leaves_only_one_singleton_for_odd_complete_graph() -> None:
	edges = {(left, right): object() for left in range(5) for right in range(left + 1, 5)}

	assert _maximum_matching_size(5, edges) == 2


def test_maximum_matching_respects_missing_staff_compatible_edges() -> None:
	edges = {(0, 1): object(), (0, 2): object(), (0, 3): object()}

	assert _maximum_matching_size(4, edges) == 1
