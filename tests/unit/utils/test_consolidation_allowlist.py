from src.data.preprocessing import _cohort_key_matches_allowlist
from src.data.schemas import DepartmentSemesterKey


def test_empty_allowlist_defaults_to_sem_5_6():
	assert _cohort_key_matches_allowlist(DepartmentSemesterKey("Information Technology", 6), []) is True
	assert _cohort_key_matches_allowlist(DepartmentSemesterKey("Information Technology", 5), []) is True
	assert _cohort_key_matches_allowlist(DepartmentSemesterKey("Information Technology", 4), []) is False


def test_non_empty_allowlist_is_strict():
	allowlist = ["Information Technology|6"]
	assert _cohort_key_matches_allowlist(DepartmentSemesterKey("Information Technology", 6), allowlist) is True
	assert _cohort_key_matches_allowlist(DepartmentSemesterKey("Information Technology", 5), allowlist) is False
	assert _cohort_key_matches_allowlist(DepartmentSemesterKey("Mechanical Engineering", 6), allowlist) is False


def test_allowlist_supports_common_formats_and_wildcards():
	key = DepartmentSemesterKey("Information Technology", 6)
	assert _cohort_key_matches_allowlist(key, ["Information Technology_S6"]) is True
	assert _cohort_key_matches_allowlist(key, ["Information Technology S6"]) is True
	assert _cohort_key_matches_allowlist(key, [key.slug()]) is True
	assert _cohort_key_matches_allowlist(key, ["*|6"]) is True
	assert _cohort_key_matches_allowlist(key, ["Information Technology|*"]) is True
