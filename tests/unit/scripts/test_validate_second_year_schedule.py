from scripts.validate_second_year_schedule import _combined_lab_window_violations


def test_only_combined_courses_are_rejected_from_l3():
    rows = [
        {"course_code": "CS23332", "course_instance_id": "dbms", "session_name": "L3", "day": "tuesday"},
        {"course_code": "CS23333", "course_instance_id": "oops", "session_name": "L4", "day": "tuesday"},
        {"course_code": "AE23331", "course_instance_id": "ordinary", "session_name": "L3", "day": "tuesday"},
    ]

    violations = _combined_lab_window_violations(rows)

    assert violations == ["CS23332:dbms uses blocked L3 on tuesday"]
