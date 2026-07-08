"""POP staff availability parsing shared by variable creation and constraints."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Iterable, Mapping, Optional, Sequence, Tuple

from ..utils.time_utils import DayNormalizer


DEFAULT_POP_START_TIME = "8:00AM"
DEFAULT_POP_END_TIME = "5:00PM"


@dataclass(frozen=True)
class PopTeacherAvailability:
	teacher_id: str
	preferred_days: frozenset[str]
	alternative_lab_days: frozenset[str]
	time_windows: Tuple[Tuple[int, int], ...]
	hard_lab_limit: bool = False
	day_time_windows: Tuple[Tuple[str, Tuple[Tuple[int, int], ...]], ...] = ()
	lab_day_time_windows: Tuple[Tuple[str, Tuple[Tuple[int, int], ...]], ...] = ()

	def allows_theory(self, day_label: object, slot_label: object) -> bool:
		day = normalize_day_label(day_label)
		if not day or day not in self.preferred_days:
			return False
		time_windows = self._time_windows_for_day(day)
		if not time_windows:
			return True
		slot_range = parse_time_range_minutes(slot_label)
		if slot_range is None:
			return False
		return any(_range_contains(window, slot_range) for window in time_windows)

	def lab_preference_tier(self, day_label: object, session_time_range: object) -> str:
		day = normalize_day_label(day_label)
		if not day:
			return "other_day"
		lab_windows = self._lab_time_windows_for_day(day)
		if lab_windows is not None:
			if not lab_windows:
				return "other_day"
			session_range = parse_time_range_minutes(session_time_range)
			if session_range and any(_range_contains(window, session_range) for window in lab_windows):
				return "preferred_window"
			return "preferred_day"
		if day in self.preferred_days:
			time_windows = self._time_windows_for_day(day)
			if not time_windows:
				return "preferred_window"
			session_range = parse_time_range_minutes(session_time_range)
			if session_range and any(_range_contains(window, session_range) for window in time_windows):
				return "preferred_window"
			return "preferred_day"
		if day in self.alternative_lab_days:
			return "alternative_day"
		return "other_day"

	def _time_windows_for_day(self, day: str) -> Tuple[Tuple[int, int], ...]:
		for window_day, windows in self.day_time_windows:
			if window_day == day:
				return windows
		return self.time_windows

	def _lab_time_windows_for_day(self, day: str) -> Optional[Tuple[Tuple[int, int], ...]]:
		if not self.lab_day_time_windows:
			return None
		for window_day, windows in self.lab_day_time_windows:
			if window_day == day:
				return windows
		return tuple()


def build_pop_availability_from_dataframe(
	dataframe: object,
	*,
	default_start_time: object = DEFAULT_POP_START_TIME,
	default_end_time: object = DEFAULT_POP_END_TIME,
) -> dict[str, PopTeacherAvailability]:
	if dataframe is None or getattr(dataframe, "empty", False):
		return {}
	to_records = getattr(dataframe, "to_dict", None)
	if not callable(to_records):
		return {}
	records = to_records("records")
	return build_pop_availability(
		records,
		default_start_time=default_start_time,
		default_end_time=default_end_time,
	)


def build_pop_availability(
	records: Iterable[Mapping[str, object]],
	*,
	default_start_time: object = DEFAULT_POP_START_TIME,
	default_end_time: object = DEFAULT_POP_END_TIME,
) -> dict[str, PopTeacherAvailability]:
	mutable: dict[str, dict[str, object]] = {}
	default_window = _build_time_window(default_start_time, default_end_time)

	for row in records:
		teacher_id = normalize_teacher_id(_first_value(row, _TEACHER_ID_COLUMNS))
		if not teacher_id:
			continue

		preferred_days = _extract_preferred_days(row)
		explicit_day_time_windows = _extract_day_time_windows(row)
		explicit_lab_day_time_windows = _extract_lab_day_time_windows(row)
		preferred_days.update(explicit_day_time_windows.keys())
		if not preferred_days:
			continue
		window = _extract_time_window(row) or default_window
		row_day_time_windows = {
			day: set(windows)
			for day, windows in explicit_day_time_windows.items()
		}
		if window is not None:
			for day in preferred_days:
				if day not in row_day_time_windows:
					row_day_time_windows[day] = {window}

		entry = mutable.setdefault(
			teacher_id,
			{
				"preferred_days": set(),
				"alternative_lab_days": set(),
				"time_windows": set(),
				"day_time_windows": {},
				"lab_day_time_windows": {},
				"hard_lab_limit": False,
			},
		)
		entry["preferred_days"].update(preferred_days)  # type: ignore[union-attr]
		entry["alternative_lab_days"].update(_extract_alternative_lab_days(row))  # type: ignore[union-attr]
		entry["hard_lab_limit"] = bool(entry["hard_lab_limit"]) or _extract_hard_lab_limit(row)
		if window is not None:
			entry["time_windows"].add(window)  # type: ignore[union-attr]
		entry_day_time_windows = entry["day_time_windows"]  # type: ignore[assignment]
		for day, windows in row_day_time_windows.items():
			entry_day_time_windows.setdefault(day, set()).update(windows)
		entry_lab_day_time_windows = entry["lab_day_time_windows"]  # type: ignore[assignment]
		for day, windows in explicit_lab_day_time_windows.items():
			entry_lab_day_time_windows.setdefault(day, set()).update(windows)

	availability: dict[str, PopTeacherAvailability] = {}
	for teacher_id, entry in mutable.items():
		day_time_windows = tuple(
			(day, tuple(sorted(windows)))
			for day, windows in sorted(entry["day_time_windows"].items())  # type: ignore[union-attr]
		)
		lab_day_time_windows = tuple(
			(day, tuple(sorted(windows)))
			for day, windows in sorted(entry["lab_day_time_windows"].items())  # type: ignore[union-attr]
		)
		availability[teacher_id] = PopTeacherAvailability(
			teacher_id=teacher_id,
			preferred_days=frozenset(entry["preferred_days"]),  # type: ignore[arg-type]
			alternative_lab_days=frozenset(entry["alternative_lab_days"]),  # type: ignore[arg-type]
			time_windows=tuple(sorted(entry["time_windows"])),  # type: ignore[arg-type]
			hard_lab_limit=bool(entry["hard_lab_limit"]),
			day_time_windows=day_time_windows,
			lab_day_time_windows=lab_day_time_windows,
		)
	return availability


def normalize_teacher_id(value: object) -> str:
	text = _clean_cell(value)
	if not text:
		return ""
	try:
		number = float(text)
	except ValueError:
		return text
	if number.is_integer():
		return str(int(number))
	return text


def normalize_day_label(value: object) -> str:
	text = _clean_cell(value)
	if not text:
		return ""
	normalized = DayNormalizer.normalize_day_name(text)
	return normalized or text.strip().lower()


def parse_time_range_minutes(value: object) -> Optional[Tuple[int, int]]:
	text = _clean_cell(value)
	if not text:
		return None
	parts = re.split(_TIME_RANGE_SEPARATOR_RE, text, maxsplit=1, flags=re.IGNORECASE)
	if len(parts) != 2:
		return None
	start = parse_time_minutes(parts[0])
	end = parse_time_minutes(parts[1])
	if start is None or end is None or end <= start:
		return None
	return start, end


def parse_time_minutes(value: object) -> Optional[int]:
	text = _clean_cell(value).replace(".", "").upper()
	if not text:
		return None
	text = re.sub(r"\s+", "", text)

	for fmt in ("%I:%M%p", "%I%p", "%H:%M", "%H"):
		try:
			parsed = datetime.strptime(text, fmt)
			minutes = parsed.hour * 60 + parsed.minute
			if "AM" in text or "PM" in text:
				return minutes
			return _infer_daytime_minutes(minutes)
		except ValueError:
			continue
	return None


def _extract_preferred_days(row: Mapping[str, object]) -> set[str]:
	days: set[str] = set()
	for column in _PREFERRED_DAY_COLUMNS:
		days.update(_parse_day_tokens(_first_value(row, (column,))))
	for index in range(1, 8):
		days.update(_parse_day_tokens(_first_value(row, (f"Preferred Day {index}", f"preferred_day_{index}"))))
	return days


def _extract_alternative_lab_days(row: Mapping[str, object]) -> set[str]:
	days: set[str] = set()
	for column in _ALTERNATIVE_LAB_DAY_COLUMNS:
		days.update(_parse_day_tokens(_first_value(row, (column,))))
	return days


def _extract_hard_lab_limit(row: Mapping[str, object]) -> bool:
	return any(
		_truthy(_first_value(row, (column,)))
		for column in _HARD_LAB_LIMIT_COLUMNS
	)


def _extract_day_time_windows(row: Mapping[str, object]) -> dict[str, Tuple[Tuple[int, int], ...]]:
	day_time_windows: dict[str, set[Tuple[int, int]]] = {}

	for column in _DAY_TIME_WINDOW_COLUMNS:
		_add_day_time_windows(
			day_time_windows,
			_parse_day_time_window_tokens(_first_value(row, (column,))),
		)

	for index in range(1, 8):
		days = _parse_day_tokens(
			_first_value(row, (f"Preferred Day {index}", f"preferred_day_{index}"))
		)
		if not days:
			continue
		window = parse_time_range_minutes(_first_value(row, _indexed_time_range_columns(index)))
		if window is None:
			window = _build_time_window(
				_first_value(row, _indexed_start_time_columns(index)),
				_first_value(row, _indexed_end_time_columns(index)),
			)
		if window is None:
			continue
		for day in days:
			day_time_windows.setdefault(day, set()).add(window)

	return {
		day: tuple(sorted(windows))
		for day, windows in day_time_windows.items()
	}


def _extract_lab_day_time_windows(row: Mapping[str, object]) -> dict[str, Tuple[Tuple[int, int], ...]]:
	day_time_windows: dict[str, set[Tuple[int, int]]] = {}
	for column in _LAB_DAY_TIME_WINDOW_COLUMNS:
		_add_day_time_windows(
			day_time_windows,
			_parse_day_time_window_tokens(_first_value(row, (column,))),
		)
	return {
		day: tuple(sorted(windows))
		for day, windows in day_time_windows.items()
	}


def _extract_time_window(row: Mapping[str, object]) -> Optional[Tuple[int, int]]:
	range_value = _first_value(row, _TIME_RANGE_COLUMNS)
	range_window = parse_time_range_minutes(range_value)
	if range_window is not None:
		return range_window
	return _build_time_window(
		_first_value(row, _START_TIME_COLUMNS),
		_first_value(row, _END_TIME_COLUMNS),
	)


def _build_time_window(start_value: object, end_value: object) -> Optional[Tuple[int, int]]:
	start = parse_time_minutes(start_value)
	end = parse_time_minutes(end_value)
	if start is None or end is None or end <= start:
		return None
	return start, end


def _parse_day_tokens(value: object) -> set[str]:
	text = _clean_cell(value)
	if not text:
		return set()
	tokens = re.split(r"[,;/|]+", text)
	days = {normalize_day_label(token) for token in tokens}
	return {day for day in days if day}


def _parse_day_time_window_tokens(value: object) -> dict[str, Tuple[Tuple[int, int], ...]]:
	text = _clean_cell(value)
	if not text:
		return {}
	day_time_windows: dict[str, set[Tuple[int, int]]] = {}
	for match in _DAY_TIME_WINDOW_RE.finditer(text):
		day = normalize_day_label(match.group("day"))
		if not day:
			continue
		window = _build_time_window(match.group("start"), match.group("end"))
		if window is None:
			continue
		day_time_windows.setdefault(day, set()).add(window)
	return {
		day: tuple(sorted(windows))
		for day, windows in day_time_windows.items()
	}


def _add_day_time_windows(
	target: dict[str, set[Tuple[int, int]]],
	source: Mapping[str, Tuple[Tuple[int, int], ...]],
) -> None:
	for day, windows in source.items():
		target.setdefault(day, set()).update(windows)


def _indexed_time_range_columns(index: int) -> Tuple[str, ...]:
	return (
		f"Preferred Day {index} Time Window",
		f"Preferred Day {index} Timing",
		f"preferred_day_{index}_time_window",
		f"preferred_day_{index}_timing",
		f"time_window_{index}",
		f"timing_{index}",
	)


def _indexed_start_time_columns(index: int) -> Tuple[str, ...]:
	return (
		f"Preferred Day {index} Start Time",
		f"Preferred Day {index} Start",
		f"preferred_day_{index}_start_time",
		f"preferred_day_{index}_start",
		f"start_time_{index}",
		f"start_{index}",
	)


def _indexed_end_time_columns(index: int) -> Tuple[str, ...]:
	return (
		f"Preferred Day {index} End Time",
		f"Preferred Day {index} End",
		f"preferred_day_{index}_end_time",
		f"preferred_day_{index}_end",
		f"end_time_{index}",
		f"end_{index}",
	)


def _first_value(row: Mapping[str, object], columns: Sequence[str]) -> str:
	lower_lookup = {str(key).strip().lower(): key for key in row.keys()}
	for column in columns:
		key = lower_lookup.get(column.strip().lower())
		if key is None:
			continue
		value = _clean_cell(row.get(key))
		if value:
			return value
	return ""


def _clean_cell(value: object) -> str:
	if value is None:
		return ""
	if isinstance(value, float) and math.isnan(value):
		return ""
	text = str(value).strip()
	if not text or text.lower() in {"nan", "none", "null", "-"}:
		return ""
	return text


def _truthy(value: object) -> bool:
	text = _clean_cell(value).strip().lower()
	return text in {"1", "true", "yes", "y", "hard", "strict", "enforce", "enforced"}


def _infer_daytime_minutes(minutes: int) -> int:
	hour = minutes // 60
	minute = minutes % 60
	if 1 <= hour <= 7:
		hour += 12
	return hour * 60 + minute


def _range_contains(window: Tuple[int, int], candidate: Tuple[int, int]) -> bool:
	return candidate[0] >= window[0] and candidate[1] <= window[1]


_TEACHER_ID_COLUMNS = (
	"Teacher ID",
	"teacher_id",
	"teacher id",
	"faculty_id",
	"staff_id",
)

_PREFERRED_DAY_COLUMNS = (
	"preferred_days",
	"preferred day",
	"preferred_day",
	"available_days",
	"availability_days",
)

_ALTERNATIVE_LAB_DAY_COLUMNS = (
	"alternative_lab_days",
	"Alternative Lab Days",
	"alternative lab days",
	"alternative_lab_day",
	"Alternative Lab Day",
	"lab_alternative_days",
)

_HARD_LAB_LIMIT_COLUMNS = (
	"hard_lab_limit",
	"Hard Lab Limit",
	"hard_lab_days",
	"Hard Lab Days",
	"enforce_lab_days",
	"Enforce Lab Days",
)

_START_TIME_COLUMNS = (
	"start_time",
	"Start Time",
	"available_start_time",
	"available_start",
	"from_time",
	"from",
)

_END_TIME_COLUMNS = (
	"end_time",
	"End Time",
	"available_end_time",
	"available_end",
	"to_time",
	"to",
)

_TIME_RANGE_COLUMNS = (
	"time_window",
	"Time Window",
	"available_time",
	"availability_window",
	"working_time",
)

_DAY_TIME_WINDOW_COLUMNS = (
	"day_time_windows",
	"Day Time Windows",
	"availability_windows",
	"availability_by_day",
	"time_windows_by_day",
	"day_wise_time_windows",
	"daywise_time_windows",
	"timings",
	"Timing",
	"timing",
)

_LAB_DAY_TIME_WINDOW_COLUMNS = (
	"lab_day_time_windows",
	"Lab Day Time Windows",
	"lab_availability_windows",
	"lab_availability_by_day",
	"lab_time_windows_by_day",
	"lab_day_wise_time_windows",
	"lab_daywise_time_windows",
	"lab_timings",
	"Lab Timing",
	"lab_timing",
)

_TIME_TOKEN_RE = r"\d{1,2}(?::\d{2})?\s*(?:[AP]\.?M\.?)?"
_TIME_RANGE_SEPARATOR_RE = "\\s*(?:-|\\u2013|\\u2014|\\bto\\b)\\s*"
_DAY_NAME_RE = (
	r"monday|mon\.?|tuesday|tues?\.?|wednesday|weds?\.?|"
	r"thursday|thurs?\.?|thur\.?|thu\.?|friday|fri\.?|saturday|sat\.?|sunday|sun\.?"
)
_DAY_TIME_WINDOW_RE = re.compile(
	rf"(?<![A-Za-z])(?P<day>{_DAY_NAME_RE})(?![A-Za-z])\s*[:=]?\s*"
	rf"(?P<start>{_TIME_TOKEN_RE}){_TIME_RANGE_SEPARATOR_RE}(?P<end>{_TIME_TOKEN_RE})",
	re.IGNORECASE,
)


__all__ = [
	"DEFAULT_POP_END_TIME",
	"DEFAULT_POP_START_TIME",
	"PopTeacherAvailability",
	"build_pop_availability",
	"build_pop_availability_from_dataframe",
	"normalize_day_label",
	"normalize_teacher_id",
	"parse_time_minutes",
	"parse_time_range_minutes",
]
