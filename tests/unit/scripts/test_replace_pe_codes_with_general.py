import csv
import importlib.util
import sys


def load_script_module():
    module_name = "replace_pe_codes_with_general_under_test"
    spec = importlib.util.spec_from_file_location(module_name, "scripts/replace_pe_codes_with_general.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def write_csv(path, fieldnames, rows):
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def test_rewrites_all_pe_option_columns_by_default(tmp_path):
    module = load_script_module()
    mapping_path = tmp_path / "pe_map.csv"
    write_csv(
        mapping_path,
        ["GENERAL CODE", "PE1", "PE2", "PE3", "PE4", "PE5", "DEPT", "SEM"],
        [
            {
                "GENERAL CODE": "CS23PE99",
                "PE1": "CS23A11",
                "PE2": "CS23B22",
                "PE3": "CS23C33",
                "PE4": "CS23D44",
                "PE5": "CS23E55",
                "DEPT": "CSE",
                "SEM": "7",
            }
        ],
    )

    pe_mapping = module.load_pe_mapping(mapping_path, min_pe_options=1)
    rows = [
        {"course_code": "CS23A11", "elective_type": "NE", "student_dept": "Computer Science & Engineering", "semester": "7"},
        {"course_code": "CS23B22", "elective_type": "NE", "student_dept": "Computer Science & Engineering", "semester": "7"},
        {"course_code": "CS23C33", "elective_type": "NE", "student_dept": "Computer Science & Engineering", "semester": "7"},
        {"course_code": "CS23D44", "elective_type": "NE", "student_dept": "Computer Science & Engineering", "semester": "7"},
        {"course_code": "CS23E55", "elective_type": "NE", "student_dept": "Computer Science & Engineering", "semester": "7"},
    ]

    new_rows, stats = module.rewrite_course_codes(
        rows,
        pe_mapping,
        only_when_elective_type_pe=False,
    )

    assert [row["course_code"] for row in new_rows] == ["CS23PE99"] * 5
    assert stats.changed_rows == 5


def test_restrictive_mode_keeps_non_pe_rows(tmp_path):
    module = load_script_module()
    mapping_path = tmp_path / "pe_map.csv"
    write_csv(
        mapping_path,
        ["GENERAL CODE", "PE1", "PE2", "PE3", "PE4", "PE5", "DEPT", "SEM"],
        [
            {
                "GENERAL CODE": "CS23PE99",
                "PE1": "CS23A11",
                "PE2": "CS23B22",
                "PE3": "",
                "PE4": "",
                "PE5": "",
                "DEPT": "CSE",
                "SEM": "7",
            }
        ],
    )

    pe_mapping = module.load_pe_mapping(mapping_path, min_pe_options=1)
    rows = [
        {"course_code": "CS23A11", "elective_type": "NE", "student_dept": "Computer Science & Engineering", "semester": "7"},
        {"course_code": "CS23B22", "elective_type": "PE", "student_dept": "Computer Science & Engineering", "semester": "7"},
    ]

    new_rows, stats = module.rewrite_course_codes(
        rows,
        pe_mapping,
        only_when_elective_type_pe=True,
    )

    assert [row["course_code"] for row in new_rows] == ["CS23A11", "CS23PE99"]
    assert stats.changed_rows == 1
