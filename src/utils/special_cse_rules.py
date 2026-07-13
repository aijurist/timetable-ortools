"""Hardcoded CSE-only scheduling rules requested for specific courses."""

from __future__ import annotations

from typing import FrozenSet


CSE_DEPARTMENT_CANONICAL = "computer science and engineering"
LOW_CODE_COURSE_CODE = "CS23PE33"
LOW_CODE_THEORY_SLOT = "12:00 - 12:50"
LOW_CODE_MIN_THEORY_ROOM_CAPACITY = 140
JEYA_MOHAN_CS23511_COURSE_CODE = "CS23511"
JEYA_MOHAN_TEACHER_IDS: FrozenSet[str] = frozenset({"1004", "1008", "500081"})
JEYA_MOHAN_ROOM_NUMBER = "A104/105"


def normalize_course_code(value: object) -> str:
	return str(value or "").strip().upper()


def normalize_department(value: object) -> str:
	text = str(value or "").strip().lower().replace("&", "and")
	collapsed = "".join(ch if ch.isalnum() else " " for ch in text)
	return " ".join(collapsed.split())


def is_exact_cse_department(value: object) -> bool:
	return normalize_department(value) == CSE_DEPARTMENT_CANONICAL


def is_cse_low_code_theory(course_code: object, department: object) -> bool:
	return normalize_course_code(course_code) == LOW_CODE_COURSE_CODE and is_exact_cse_department(department)


def is_cse_large_low_code_theory(
	course_code: object,
	department: object,
	student_count: object,
) -> bool:
	if not is_cse_low_code_theory(course_code, department):
		return False
	try:
		count = int(round(float(student_count)))
	except (TypeError, ValueError):
		return False
	return count >= LOW_CODE_MIN_THEORY_ROOM_CAPACITY


def is_jeya_mohan_cs23511(course_code: object, department: object, teacher_id: object) -> bool:
	return (
		normalize_course_code(course_code) == JEYA_MOHAN_CS23511_COURSE_CODE
		and is_exact_cse_department(department)
		and str(teacher_id or "").strip() in JEYA_MOHAN_TEACHER_IDS
	)


def normalize_slot_label(value: object) -> str:
	text = str(value or "").strip().replace(" ", "")
	return text.replace("–", "-").replace("—", "-").lower()


def is_low_code_theory_slot(value: object) -> bool:
	return normalize_slot_label(value) == normalize_slot_label(LOW_CODE_THEORY_SLOT)


def normalize_room_number(value: object) -> str:
	return str(value or "").strip().replace(" ", "").upper()


def is_jeya_mohan_room(value: object) -> bool:
	return normalize_room_number(value) == normalize_room_number(JEYA_MOHAN_ROOM_NUMBER)
