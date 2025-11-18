"""Modular data preprocessing pipeline for the timetable scheduler.

This module consumes the raw artefacts produced by :mod:`data_loader` and
transforms them into scheduler-ready structures.  The pipeline follows three
major stages:

1. Normalisation – convert each raw course row into a well-defined
   :class:`NormalizedCourseInstance` with consistent typing and feature tags.
2. Grouping – delegate to :class:`CourseGroupOptimizer` (OR-Tools) to form
   balanced department/semester groups while keeping a graceful fallback when
   optimisation cannot run.
3. Scheduling packaging – derive constraint-aware requirement bundles so the
   solver can reason about lunch windows, five-pm policies, and teacher load.

The implementation stays close to the functional design outlined in
``docs/PROJECT_SUMMARY.md`` and ``docs/QUICK_REFERENCE_IMPLEMENTATION.md`` while
remaining light-weight enough to plug into the existing orchestrator.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from pathlib import Path
import shutil
from typing import Any, Dict, Iterable, List, Mapping, MutableMapping, Optional, Sequence, Tuple
import pandas as pd

from .data_loader import DataLoader
from ..config.schemas import PreprocessingConfig, SchedulerConfig
from ..config.manager import ConfigManager
from .course_group_optimizer import CourseGroupOptimizer
from .schemas import (
	DataLoadResult,
	DepartmentArtifacts,
	DepartmentSemesterKey,
	NormalizedCourseInstance,
	CourseGroup,
	DepartmentSchedulingPackage,
	GroupSummary,
	GroupPenaltySpec,
	GroupRequirement,
	TeacherWorkloadSummary,
	PreprocessingResult,
	ExtendedDataContainer,
	dataclass_to_dict,
)


logger = logging.getLogger(__name__)



# ---------------------------------------------------------------------------
# Helper utilities
# ---------------------------------------------------------------------------

def _clean_str(value: Any, *, default: str = "") -> str:
	if value is None:
		return default
	if isinstance(value, str):
		return value.strip()
	try:
		return str(value).strip()
	except Exception:  # pragma: no cover - defensive
		return default


def _safe_int(value: Any, *, default: Optional[int] = None) -> Optional[int]:
	if value is None:
		return default
	if isinstance(value, str) and not value.strip():
		return default
	try:
		if pd.isna(value):
			return default
	except Exception:  # pragma: no cover - pandas errors
		pass
	try:
		return int(round(float(value)))
	except Exception:
		return default


def _normalise_department(value: str) -> str:
	if not value:
		return value
	collapsed = " ".join(value.replace("&", " & ").split())
	return collapsed.replace("  ", " ").strip()


def _title_case(name: str) -> str:
	if not name:
		return name
	return " ".join(part.capitalize() for part in name.split())


# ---------------------------------------------------------------------------
# Stage 1 – Normalisation
# ---------------------------------------------------------------------------


class CourseInstanceNormalizer:
	"""Convert raw course rows into structured instances grouped by dept/semester."""

	def __init__(self, config: PreprocessingConfig, *, logger: Optional[logging.Logger] = None) -> None:
		self._config = config
		self._logger = logger or logging.getLogger(__name__)
		self._warnings: List[str] = []

	@property
	def warnings(self) -> Tuple[str, ...]:
		return tuple(self._warnings)

	def normalize(self, courses_df: pd.DataFrame) -> Dict[DepartmentSemesterKey, Tuple[NormalizedCourseInstance, ...]]:
		grouped: Dict[DepartmentSemesterKey, List[NormalizedCourseInstance]] = defaultdict(list)
		if courses_df is None or courses_df.empty:
			self._warnings.append("Courses dataframe is empty; nothing to normalise")
			return {}

		enumerated_df = courses_df.reset_index(drop=True)
		for row_index, row in enumerated_df.iterrows():
			try:
				instance = self._normalise_row(row, row_index)
			except ValueError as exc:
				warning = f"Row {row_index}: {exc}"
				self._warnings.append(warning)
				self._logger.debug("Skipping course row %s due to: %s", row_index, exc)
				continue

			key = DepartmentSemesterKey(instance.student_dept, instance.semester)
			grouped[key].append(instance)

		return {key: tuple(instances) for key, instances in grouped.items()}

	def _normalise_row(self, row: pd.Series, row_index: int) -> NormalizedCourseInstance:
		course_code = _clean_str(row.get("course_code"))
		if not course_code:
			raise ValueError("missing course_code")

		semester = _safe_int(row.get("semester"))
		if semester is None:
			raise ValueError("missing semester")

		student_dept = _clean_str(row.get("student_dept") or row.get("department"))
		if not student_dept:
			raise ValueError("missing student_dept/department")
		if self._config.normalise_department_names:
			student_dept = _normalise_department(student_dept)

		course_dept = _clean_str(row.get("course_dept") or row.get("teaching_dept") or student_dept)
		if self._config.normalise_department_names:
			course_dept = _normalise_department(course_dept)

		teacher_id = _clean_str(row.get("teacher_id") or row.get("teacher") or row.get("staff_code") or f"T_{row_index:04d}")
		teacher_name = _clean_str(row.get("teacher") or row.get("teacher_name") or row.get("first_name"))
		if self._config.normalise_teacher_names:
			teacher_name = _title_case(teacher_name)

		assistant_teacher_id = _clean_str(row.get("assist_teacher_id")) or None
		assistant_teacher_name = _clean_str(row.get("assist_first_name")) or None
		if assistant_teacher_name and self._config.normalise_teacher_names:
			assistant_teacher_name = _title_case(assistant_teacher_name)

		lecture_hours = _safe_int(row.get("lecture_hours"), default=0) or 0
		tutorial_hours = _safe_int(row.get("tutorial_hours"), default=0) or 0
		practical_hours = _safe_int(row.get("practical_hours"), default=0) or 0

		course_type = _clean_str(row.get("course_type"), default="T").upper() or "T"
		has_lab = practical_hours > 0 or course_type in {"L", "LAB", "LOT"}
		has_theory = (lecture_hours + tutorial_hours) > 0 or course_type in {"T", "LOT"}

		student_count = _safe_int(row.get("student_count"), default=None)
		if student_count is None and self._config.fill_missing_students:
			student_count = min(self._config.student_cap or 70, 70)
		if student_count is not None and self._config.student_cap is not None:
			student_count = min(student_count, self._config.student_cap)
		student_count = student_count or 0

		course_id = _clean_str(row.get("course_id") or row.get("id") or f"{course_code}-{teacher_id}-{semester}")
		instance_id = _clean_str(row.get("id") or course_id or f"row-{row_index}")

		requires_special_scheduling = bool(_safe_int(row.get("requires_special_scheduling"), default=0))
		requires_assistant = bool(_safe_int(row.get("is_assistant"), default=0))
		preferred_lab_type = _clean_str(row.get("lab_type")) or None
		preferred_room_type = _clean_str(row.get("preferred_for") or row.get("lab_description")) or None
		required_room_type = _clean_str(row.get("required_room_type") or row.get("specific_room_type")) or None
		pe_flag = "pe" in _clean_str(row.get("pe/ne"), default="").lower()

		tags = set()
		tags.add("lab" if has_lab else "theory")
		if pe_flag:
			tags.add("professional_elective")
		if requires_special_scheduling:
			tags.add("special_schedule")
		if required_room_type:
			tags.add("room_specific")

		metadata = {
			"teacher_email": _clean_str(row.get("teacher_email")),
			"assistant_teacher_email": _clean_str(row.get("assist_teacher_email")),
			"preferred_room_type": preferred_room_type,
			"lab_type": preferred_lab_type,
			"raw_row": row_index,
		}

		return NormalizedCourseInstance(
			instance_id=str(instance_id),
			course_id=str(course_id),
			course_code=course_code,
			course_name=_clean_str(row.get("course_name")),
			course_type=course_type,
			semester=int(semester),
			student_dept=student_dept,
			course_dept=course_dept,
			teacher_id=teacher_id,
			teacher_name=teacher_name or teacher_id,
			assistant_teacher_id=assistant_teacher_id,
			assistant_teacher_name=assistant_teacher_name,
			has_lab=has_lab,
			has_theory=has_theory,
			lecture_hours=lecture_hours,
			tutorial_hours=tutorial_hours,
			practical_hours=practical_hours,
			student_count=student_count,
			requires_special_scheduling=requires_special_scheduling,
			requires_assistant=requires_assistant,
			preferred_lab_type=preferred_lab_type,
			preferred_room_type=preferred_room_type,
			required_room_type=required_room_type,
			pe_flag=pe_flag,
			tags=tuple(sorted(tags)),
			metadata=metadata,
			raw_row_index=row_index,
		)


# ---------------------------------------------------------------------------
# Stage 2 – Grouping via CourseGroupOptimizer (with fallback)
# ---------------------------------------------------------------------------


class DepartmentCourseGrouper:
	def __init__(self, config: SchedulerConfig, *, base_dir: Path, logger: Optional[logging.Logger] = None) -> None:
		self._config = config
		self._base_dir = base_dir
		self._logger = logger or logging.getLogger(__name__)
		self._warnings: List[str] = []
		self._pe_course_map_path = self._discover_pe_course_map()

	@property
	def warnings(self) -> Tuple[str, ...]:
		return tuple(self._warnings)

	def group(
		self,
		normalized_instances: Mapping[DepartmentSemesterKey, Tuple[NormalizedCourseInstance, ...]],
	) -> Dict[DepartmentSemesterKey, Tuple[CourseGroup, ...]]:
		grouped: Dict[DepartmentSemesterKey, Tuple[CourseGroup, ...]] = {}

		filedir = Path(__file__).resolve() / "grouping_visualizations"
		try:
			if filedir.exists() and filedir.is_dir():
				shutil.rmtree(filedir)
			print(f"Clear existing Group Visualizations at {filedir}")
		except PermissionError:
			self._logger.warning("Permission denied when trying to clear existing grouping visualizations at %s", filedir)
			raise PermissionError("Cannot clear existing grouping visualizations")
		except OSError as e:
			print(f"Error {e}")

		for key, instances in normalized_instances.items():
			if not instances:
				continue
			groups = self._group_single_cohort(key, instances)
			grouped[key] = tuple(groups)
		return grouped

	def _group_single_cohort(
		self,
		key: DepartmentSemesterKey,
		instances: Sequence[NormalizedCourseInstance],
	) -> List[CourseGroup]:
		optimizer_courses = [instance.to_optimizer_payload() for instance in instances]
		optimizer = CourseGroupOptimizer(
			courses=optimizer_courses,
			dept=key.department,
			semester=key.semester,
			logger=self._logger,
			pe_course_map_file=self._pe_course_map_path,
		)

		success = optimizer.optimize_distribution()
		if success:
			optimizer.generate_group_distribution_visualizations()
			validator_ok = optimizer.validate_solution()
			if not validator_ok:
				self._warnings.append(
					f"Group validation failed for {key.label()}; using optimiser output regardless"
				)
		else:
			self._warnings.append(
				f"Optimizer infeasible for {key.label()}; applying fallback grouping strategy"
			)

		raw_groups = optimizer.get_groups() if success else self._fallback_groups(instances)
		num_regular_groups = optimizer.num_groups if success else len(raw_groups)
		return self._convert_groups(key, raw_groups, num_regular_groups)

	def _fallback_groups(self, instances: Sequence[NormalizedCourseInstance]) -> List[List[Dict[str, Any]]]:
		grouped: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
		for instance in instances:
			grouped[instance.course_code].append(instance.to_optimizer_payload())
		return list(grouped.values())

	def _convert_groups(
		self,
		key: DepartmentSemesterKey,
		raw_groups: Sequence[Sequence[Mapping[str, Any]]],
		num_regular_groups: int,
	) -> List[CourseGroup]:
		converted: List[CourseGroup] = []
		for ordinal, group_instances in enumerate(raw_groups, start=1):
			course_instance_ids = tuple(str(entry.get("id")) for entry in group_instances if entry)
			teacher_ids = tuple(sorted({str(entry.get("teacher_id")) for entry in group_instances if entry.get("teacher_id")}))
			course_codes = tuple(sorted({str(entry.get("course_code")) for entry in group_instances if entry.get("course_code")}))

			lab_instances = sum(1 for entry in group_instances if entry.get("has_lab"))
			theory_instances = sum(1 for entry in group_instances if entry.get("has_theory"))
			lab_hours = sum((_safe_int(entry.get("practical_hours"), default=0) or 0) for entry in group_instances)
			theory_hours = sum(
				(_safe_int(entry.get("lecture_hours"), default=0) or 0)
				+ (_safe_int(entry.get("tutorial_hours"), default=0) or 0)
				for entry in group_instances
			)
			total_students = sum((_safe_int(entry.get("student_count"), default=0) or 0) for entry in group_instances)

			summary = GroupSummary(
				num_instances=len(group_instances),
				num_courses=len(course_codes),
				num_teachers=len(teacher_ids),
				lab_instances=lab_instances,
				theory_instances=theory_instances,
				total_student_count=total_students,
				lab_hours=lab_hours,
				theory_hours=theory_hours,
			)

			tags = set()
			if lab_instances:
				tags.add("lab")
			if ordinal > num_regular_groups:
				tags.add("professional_elective")

			converted.append(
				CourseGroup(
					key=key,
					group_id=f"{key.slug()}_g{ordinal:02d}",
					ordinal=ordinal,
					is_professional_elective=ordinal > num_regular_groups,
					course_instance_ids=course_instance_ids,
					teacher_ids=teacher_ids,
					course_codes=course_codes,
					summary=summary,
					tags=tuple(sorted(tags)),
				)
			)
		return converted

	def _discover_pe_course_map(self) -> Optional[str]:
		candidate = self._base_dir / "data" / "pe_course_map.csv"
		return str(candidate) if candidate.exists() else None


# ---------------------------------------------------------------------------
# Stage 3 – Scheduling ready packages
# ---------------------------------------------------------------------------


class GroupAssignmentPostProcessor:
	def __init__(self, config: SchedulerConfig, *, logger: Optional[logging.Logger] = None) -> None:
		self._config = config
		self._logger = logger or logging.getLogger(__name__)
		self._warnings: List[str] = []

	@property
	def warnings(self) -> Tuple[str, ...]:
		return tuple(self._warnings)

	def build_packages(
		self,
		groups: Mapping[DepartmentSemesterKey, Tuple[CourseGroup, ...]],
		normalized_instances: Mapping[DepartmentSemesterKey, Tuple[NormalizedCourseInstance, ...]],
		department_artifacts: DepartmentArtifacts,
	) -> Dict[DepartmentSemesterKey, DepartmentSchedulingPackage]:
		packages: Dict[DepartmentSemesterKey, DepartmentSchedulingPackage] = {}
		for key, course_groups in groups.items():
			if not course_groups:
				continue
			lunch_window = self._resolve_lunch_window(department_artifacts, key.department)
			five_pm_policy = self._resolve_five_pm_policy(department_artifacts, key)
			requirements = [
				self._build_group_requirement(group, lunch_window, five_pm_policy)
				for group in course_groups
			]
			penalties = self._build_penalties(requirements, lunch_window, five_pm_policy)
			teacher_workload = self._aggregate_teacher_workload(
				normalized_instances.get(key, ()),
				course_groups,
			)
			packages[key] = DepartmentSchedulingPackage(
				key=key,
				requirements=tuple(requirements),
				penalties=tuple(penalties),
				teacher_workload=teacher_workload,
				metadata={
					"lunch_slot_window": lunch_window,
					"five_pm_policy": five_pm_policy,
					"num_groups": len(course_groups),
				},
			)
		return packages

	def _build_group_requirement(
		self,
		group: CourseGroup,
		lunch_window: Tuple[int, ...],
		five_pm_policy: Optional[Mapping[str, Any]],
	) -> GroupRequirement:
		lab_sessions_estimate = max(1, (group.summary.lab_hours + 3) // 4) if group.summary.lab_hours else 0
		tags = set(group.tags)
		if five_pm_policy:
			tags.add(f"five_pm_{five_pm_policy['label']}")
		return GroupRequirement(
			group_id=group.group_id,
			department=group.key.department,
			semester=group.key.semester,
			has_lab=group.summary.lab_instances > 0,
			required_lab_sessions=lab_sessions_estimate,
			prefer_consecutive_labs=self._config.grouping.consecutive_lab_pairs and group.summary.lab_instances > 0,
			lunch_slot_window=lunch_window,
			five_pm_policy=five_pm_policy.get("label") if five_pm_policy else None,
			tags=tuple(sorted(tags)),
		)

	def _build_penalties(
		self,
		requirements: Sequence[GroupRequirement],
		lunch_window: Tuple[int, ...],
		five_pm_policy: Optional[Mapping[str, Any]],
	) -> List[GroupPenaltySpec]:
		penalties: List[GroupPenaltySpec] = []
		lunch_constraint = self._config.constraints.cross_system.get("lunch_alignment")
		if lunch_constraint and lunch_constraint.enabled and lunch_window:
			penalties.append(
				GroupPenaltySpec(
					name="lunch_alignment",
					weight=lunch_constraint.weight,
					description="Keep lunch within approved slots",
					applies_to=tuple(req.group_id for req in requirements),
					params={"allowed_slots": lunch_window},
				)
			)

		five_pm_constraint = self._config.constraints.cross_system.get("five_pm_policy")
		if five_pm_policy and five_pm_constraint and five_pm_constraint.enabled:
			penalties.append(
				GroupPenaltySpec(
					name="five_pm_policy",
					weight=five_pm_constraint.weight,
					description=f"Respect {five_pm_policy['label']} 5 PM policy",
					applies_to=tuple(req.group_id for req in requirements),
					params={k: v for k, v in five_pm_policy.items() if k != "label"},
				)
			)

		return penalties

	def _aggregate_teacher_workload(
		self,
		instances: Sequence[NormalizedCourseInstance],
		groups: Sequence[CourseGroup],
	) -> Dict[str, TeacherWorkloadSummary]:
		group_lookup: Dict[str, str] = {}
		for group in groups:
			for instance_id in group.course_instance_ids:
				group_lookup[instance_id] = group.group_id

		aggregates: Dict[str, Dict[str, Any]] = {}
		for instance in instances:
			entry = aggregates.setdefault(
				instance.teacher_id,
				{
					"teacher_id": instance.teacher_id,
					"teacher_name": instance.teacher_name,
					"groups": set(),
					"course_codes": set(),
					"course_instance_ids": [],
					"total_hours": 0,
					"lab_hours": 0,
					"theory_hours": 0,
					"total_students": 0,
				},
			)
			entry["course_instance_ids"].append(instance.instance_id)
			entry["course_codes"].add(instance.course_code)
			entry["total_hours"] += instance.total_hours()
			entry["lab_hours"] += instance.practical_hours
			entry["theory_hours"] += instance.lecture_hours + instance.tutorial_hours
			entry["total_students"] += instance.student_count
			group_id = group_lookup.get(instance.instance_id)
			if group_id:
				entry["groups"].add(group_id)

		return {
			teacher_id: TeacherWorkloadSummary(
				teacher_id=data["teacher_id"],
				teacher_name=data["teacher_name"],
				groups=tuple(sorted(data["groups"])),
				course_codes=tuple(sorted(data["course_codes"])),
				course_instance_ids=tuple(data["course_instance_ids"]),
				total_hours=data["total_hours"],
				lab_hours=data["lab_hours"],
				theory_hours=data["theory_hours"],
				total_students=data["total_students"],
			)
			for teacher_id, data in aggregates.items()
		}

	def _resolve_lunch_window(
		self,
		department_artifacts: DepartmentArtifacts,
		department: str,
	) -> Tuple[int, ...]:
		windows = department_artifacts.lunch_slot_windows
		if department in windows and windows[department]:
			return windows[department]
		return windows.get("__default__", tuple())

	def _resolve_five_pm_policy(
		self,
		department_artifacts: DepartmentArtifacts,
		key: DepartmentSemesterKey,
	) -> Optional[Mapping[str, Any]]:
		constraints = department_artifacts.five_pm_constraints or {}
		dept_label = f"{key.department}_S{key.semester}"
		for label, payload in constraints.items():
			departments = payload.get("departments", ())
			if dept_label in departments:
				return {"label": label, **payload}
		return None


# ---------------------------------------------------------------------------
# Orchestrator-facing façade
# ---------------------------------------------------------------------------


class DataPreprocessor:
	"""High level façade combining normalisation, grouping, and packaging."""

	def __init__(
		self,
		config: SchedulerConfig,
		*,
		base_dir: Optional[Path] = None,
		logger: Optional[logging.Logger] = None,
	) -> None:
		self._config = config
		self._base_dir = Path(base_dir or Path.cwd()).resolve()
		self._logger = logger or logging.getLogger(__name__)
		self._normalizer = CourseInstanceNormalizer(config.preprocessing, logger=self._logger)
		self._grouper = DepartmentCourseGrouper(config, base_dir=self._base_dir, logger=self._logger)
		self._post_processor = GroupAssignmentPostProcessor(config, logger=self._logger)

	def run(self, data: DataLoadResult) -> PreprocessingResult:
		normalized = self._normalizer.normalize(data.courses_df)
		grouped = self._grouper.group(normalized)
		packages = self._post_processor.build_packages(grouped, normalized, data.departments)

		warnings = (
			list(self._normalizer.warnings)
			+ list(self._grouper.warnings)
			+ list(self._post_processor.warnings)
		)

		stats = self._build_stats(normalized, grouped)

		return PreprocessingResult(
			normalized_instances=normalized,
			groups=grouped,
			scheduling_packages=packages,
			warnings=tuple(warnings),
			stats=stats,
		)

	def build_extended_container(self, data: DataLoadResult) -> ExtendedDataContainer:
		preprocessing = self.run(data)
		return ExtendedDataContainer(raw=data, preprocessing=preprocessing)

	def _build_stats(
		self,
		normalized: Mapping[DepartmentSemesterKey, Sequence[NormalizedCourseInstance]],
		grouped: Mapping[DepartmentSemesterKey, Sequence[CourseGroup]],
	) -> Dict[str, Any]:
		dept_stats = {}
		total_instances = 0
		total_groups = 0
		for key in normalized:
			instances = len(normalized.get(key, ()))
			groups = len(grouped.get(key, ()))
			dept_stats[key.slug()] = {
				"label": key.label(),
				"instances": instances,
				"groups": groups,
			}
			total_instances += instances
			total_groups += groups
		return {
			"total_instances": total_instances,
			"total_groups": total_groups,
			"department_semesters": dept_stats,
		}


def preprocess_data(
	config: SchedulerConfig,
	data: DataLoadResult,
	*,
	base_dir: Optional[Path] = None,
	logger: Optional[logging.Logger] = None,
) -> PreprocessingResult:
	"""Module-level convenience helper mirroring :func:`data_loader.load_data`."""

	processor = DataPreprocessor(config, base_dir=base_dir, logger=logger)
	return processor.run(data)


__all__ = [
	"DepartmentSemesterKey",
	"NormalizedCourseInstance",
	"GroupSummary",
	"CourseGroup",
	"GroupRequirement",
	"GroupPenaltySpec",
	"TeacherWorkloadSummary",
	"DepartmentSchedulingPackage",
	"PreprocessingResult",
	"ExtendedDataContainer",
	"CourseInstanceNormalizer",
	"DepartmentCourseGrouper",
	"GroupAssignmentPostProcessor",
	"DataPreprocessor",
	"preprocess_data",
]

if __name__ == '__main__':
	base_dir = Path.cwd()
	config_manager = ConfigManager(base_dir=base_dir)
	config = config_manager.load()
    
	data_loader = DataLoader(config, base_dir=base_dir)
	res = data_loader.load()

	pre = DataPreprocessor(config)
	output = pre.build_extended_container(data=res)
