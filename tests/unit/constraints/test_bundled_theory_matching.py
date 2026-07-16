from types import SimpleNamespace

from src.constraints.cross_system.bundled_theory import (
	_configured_forced_course_pairs,
	_forced_solo_indices_for_odd_cohort,
	_maximum_matching_size,
	_resolve_forced_pair_edges,
	_same_teacher_id,
)


def test_maximum_matching_pairs_unequal_load_candidates() -> None:
	edges = {(0, 1): object(), (0, 2): object(), (1, 3): object(), (2, 3): object()}

	assert _maximum_matching_size(4, edges) == 2


def test_maximum_matching_leaves_only_one_singleton_for_odd_complete_graph() -> None:
	edges = {(left, right): object() for left in range(5) for right in range(left + 1, 5)}

	assert _maximum_matching_size(5, edges) == 2


def test_maximum_matching_respects_missing_staff_compatible_edges() -> None:
	edges = {(0, 1): object(), (0, 2): object(), (0, 3): object()}

	assert _maximum_matching_size(4, edges) == 1


def test_kutty_pairing_normalizes_equivalent_teacher_ids() -> None:
	assert _same_teacher_id("211", "211.0")
	assert not _same_teacher_id("211", "212")


def test_odd_cohort_forces_ma_course_to_remain_solo() -> None:
	courses = [
		("ae", SimpleNamespace(course_code="AE23331")),
		("maths", SimpleNamespace(course_code="MA23311")),
		("other", SimpleNamespace(course_code="AE23332")),
	]

	assert _forced_solo_indices_for_odd_cohort(courses, course_prefixes=["MA"]) == frozenset({1})


def test_odd_csbs_cohort_uses_explicit_computational_statistics_exception() -> None:
	courses = [
		("business", SimpleNamespace(course_code="CB23311")),
		("statistics", SimpleNamespace(course_code="CB23331")),
		("programming", SimpleNamespace(course_code="CB23332")),
	]

	assert _forced_solo_indices_for_odd_cohort(courses, course_codes=["CB23331"]) == frozenset({1})


def test_even_cohort_does_not_force_a_maths_singleton() -> None:
	courses = [
		("maths", SimpleNamespace(course_code="MA23311")),
		("other", SimpleNamespace(course_code="AE23331")),
	]

	assert not _forced_solo_indices_for_odd_cohort(courses, course_prefixes=["MA"])


def test_certified_pairs_support_wildcard_and_section_specific_entries() -> None:
	payload = {
		"Robotics & Automation": {"*": [["MA23311", "RO23311"]]},
		"Biotechnology": {"2": [["BT23311", "BT23331"]]},
	}

	assert _configured_forced_course_pairs(
		payload, department="Robotics & Automation", section_id=0
	) == (("MA23311", "RO23311"),)
	assert _configured_forced_course_pairs(
		payload, department="Biotechnology", section_id=2
	) == (("BT23311", "BT23331"),)
	assert _configured_forced_course_pairs(
		payload, department="Biotechnology", section_id=1
	) is None


def test_certified_pair_edges_resolve_by_course_code() -> None:
	courses = [
		("maths", SimpleNamespace(course_code="MA23311")),
		("analog", SimpleNamespace(course_code="RO23311")),
		("mechanisms", SimpleNamespace(course_code="RO23312")),
		("sensors", SimpleNamespace(course_code="RO23313")),
	]
	pair_vars = {(0, 1): object(), (0, 2): object(), (1, 3): object(), (2, 3): object()}

	assert _resolve_forced_pair_edges(
		courses,
		pair_vars,
		(("MA23311", "RO23311"), ("RO23312", "RO23313")),
		cohort_key=("Robotics & Automation", 3, 0),
	) == frozenset({(0, 1), (2, 3)})
