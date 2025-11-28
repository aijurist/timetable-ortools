"""Core workflow excerpts collected for the project report appendix.

This module is documentation-only: each entry captures 50-60 lines of the
original implementation so the appendix can show real production code without
having to stitch together multiple files.
"""

from __future__ import annotations

from textwrap import dedent
from typing import Dict, Iterable, Tuple

APPENDIX_SNIPPETS: Dict[str, str] = {
    "data_loader": dedent('''
# src/data/data_loader.py
class DataLoader:
    """Load data based on `SchedulerConfig`, preserving legacy semantics."""

    def __init__(self, config: SchedulerConfig, *, base_dir: Optional[Path] = None) -> None:
        self._base_dir = Path(base_dir or Path.cwd()).resolve()
        self._paths = config.paths.resolve(self._base_dir)
        self._config = config

    def load(self) -> DataLoadResult:
        """Load all scheduler artefacts and return a structured result."""

        courses_df = self._read_csv(self._paths.courses_csv, required=True, friendly_name="courses")
        rooms_df = self._read_csv(self._paths.rooms_csv, required=True, friendly_name="rooms")
        day_order_df = self._read_csv(self._paths.day_order_csv, friendly_name="day order")
        core_lab_mapping_df = self._read_csv(
            self._paths.core_lab_mapping_csv,
            friendly_name="core lab mapping",
        )
        teacher_preferences_df = self._read_csv(
            self._paths.preferences_csv,
            friendly_name="teacher preferences",
        )

        courses_df = self._normalise_courses_dataframe(courses_df)
        rooms_df = self._normalise_rooms_dataframe(rooms_df)

        time_artifacts = self._build_time_artifacts(self._config.time)
        department_artifacts = self._build_department_artifacts(self._config.departments, time_artifacts)
        room_collections = self._build_room_collections(rooms_df)
        room_registry = RoomRegistry.build_registry(rooms_df.to_dict("records"), key_field="id")

        teachers = self._extract_sorted_unique(courses_df, ["teacher", "teacher_name", "faculty"], fallback="teacher_id")
        departments = self._extract_sorted_unique(courses_df, ["department", "dept", "course_dept"])

        result = DataLoadResult(
            config=self._config,
            courses_df=courses_df,
            rooms_df=rooms_df,
            day_order_df=day_order_df,
            core_lab_mapping_df=core_lab_mapping_df,
            teacher_preferences_df=teacher_preferences_df,
            time=time_artifacts,
            departments=department_artifacts,
            rooms=room_collections,
            teachers=teachers,
            departments_list=departments,
            room_registry=room_registry,
            load_timestamp=datetime.utcnow(),
        )

        logger.info(
            "Loaded %s courses, %s rooms, %s departments, %s teachers",
            len(courses_df),
            len(rooms_df),
            len(result.departments_list),
            len(result.teachers),
        )
        return result

    def _build_time_artifacts(self, time_config: TimeSystemConfig) -> TimeSystemArtifacts:
        theory_slots = tuple(time_config.theory_slots)
        lab_slots = tuple(time_config.lab_slots)
        working_days = tuple(time_config.working_days)

        lab_sessions = {
            name: LabSessionDetail(
                name=name,
                slots=tuple(indices),
                time_range=self._derive_session_range(tuple(indices), lab_slots),
            )
            for name, indices in time_config.lab_sessions.items()
        }

        lab_slot_to_theory, theory_slot_to_lab = self._build_slot_overlap_maps(theory_slots, lab_slots)
        lab_session_to_theory = {
            name: tuple(sorted({slot for idx in detail.slots for slot in lab_slot_to_theory.get(idx, ())}))
            for name, detail in lab_sessions.items()
        }

        return TimeSystemArtifacts(
            theory_slots=theory_slots,
            lab_slots=lab_slots,
            lab_sessions=lab_sessions,
            working_days=working_days,
            lab_slot_to_theory=lab_slot_to_theory,
            theory_slot_to_lab=theory_slot_to_lab,
            lab_session_to_theory=lab_session_to_theory,
        )
'''),
    "preprocessing": dedent('''
# src/data/preprocessing.py
class GroupAssignmentPostProcessor:
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

class DataPreprocessor:
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
'''),
    "variables": dedent('''
# src/models/variables.py
class VariableCreator:
    """Create CP-SAT decision variables backed by preprocessing artefacts."""

    def create(self, model: cp_model.CpModel) -> VariableCreationResult:
        """Create all decision variables and return a structured handle bundle."""

        lab_block = self._create_lab_variables(model)
        theory_block = self._create_theory_variables(model)

        metadata = {
            "lab_courses": len(lab_block.requirements),
            "lab_teachers": len(lab_block.teacher_courses),
            "groups": len(theory_block.requirements),
        }

        self._logger.info(
            "VariableCreator initialised %s lab courses across %s teachers and %s groups",
            metadata["lab_courses"],
            metadata["lab_teachers"],
            metadata["groups"],
        )

        return VariableCreationResult(lab=lab_block, theory=theory_block, metadata=metadata)

    def _create_lab_variables(self, model: cp_model.CpModel) -> LabVariableBlock:
        requirements = self._build_lab_course_requirements()
        assignments: LabAssignmentDict = {}
        teacher_courses: Dict[str, Tuple[str, ...]] = {}
        day_patterns: Dict[str, Tuple[str, ...]] = {}

        for teacher_id, course_requirements in self._group_requirements_by_teacher(requirements).items():
            assignments[teacher_id] = {}
            teacher_courses[teacher_id] = tuple(req.course_instance_id for req in course_requirements)

            for requirement in course_requirements:
                course_vars: Dict[int, Dict[str, Dict[str, cp_model.IntVar]]] = {}
                assignments[teacher_id][requirement.course_instance_id] = course_vars
                pattern = self._resolve_day_pattern(requirement.department)
                day_patterns[requirement.course_instance_id] = pattern
                for day_index, _ in enumerate(pattern):
                    session_map: Dict[str, Dict[str, cp_model.IntVar]] = {}
                    course_vars[day_index] = session_map
                    for session_name in self._lab_session_names:
                        room_map: Dict[str, cp_model.IntVar] = {}
                        session_map[session_name] = room_map
                        for room_id in self._lab_room_ids:
                            var_name = (
                                f"lab_{teacher_id}_{requirement.course_instance_id}_d{day_index}_{session_name}_{room_id}"
                            )
                            room_map[room_id] = model.NewBoolVar(var_name)

        return LabVariableBlock(
            assignments=assignments,
            requirements=requirements,
            teacher_courses=teacher_courses,
            day_patterns=day_patterns,
            lab_session_names=self._lab_session_names,
            room_ids=self._lab_room_ids,
            instance_group_lookup=self._instance_group_lookup,
        )

    def _build_lab_course_requirements(self) -> Dict[str, LabCourseRequirement]:
        requirements: Dict[str, LabCourseRequirement] = {}
        for instance_id, instance in self._instance_index.items():
            if not instance.has_lab or instance.practical_hours <= 0:
                continue
            group = self._instance_group_index.get(instance_id)
            if not group:
                self._logger.debug("Skipping lab instance %s without group assignment", instance_id)
                continue
            required_sessions = max(1, math.ceil(instance.practical_hours / 2))
            requirements[instance_id] = LabCourseRequirement(
                course_instance_id=instance_id,
                course_code=instance.course_code,
                teacher_id=instance.teacher_id,
                group_id=group.group_id,
                department=instance.student_dept,
                semester=instance.semester,
                practical_hours=instance.practical_hours,
                required_sessions=required_sessions,
                student_count=instance.student_count,
                preferred_room_type=instance.preferred_room_type,
                required_room_type=instance.required_room_type,
                tags=instance.tags,
            )
        return requirements
'''),
    "model_builder": dedent('''
# src/models/model_builder.py
class ModelBuilder:
    """Core orchestrator that wires variables, constraints, and metadata."""

    def build(
        self,
        data: ExtendedDataContainer,
        *,
        model: Optional[cp_model.CpModel] = None,
    ) -> ConstraintModel:
        """Create variables, apply registered constraints, and return the model."""

        model_instance = model or cp_model.CpModel()
        self._logger.info("Creating solver variables via VariableCreator")
        variable_creator = self._variable_creator_cls(data, logger_=self._logger.getChild("VariableCreator"))
        variables = variable_creator.create(model_instance)

        context = ConstraintContext(
            model=model_instance,
            config=self._config,
            data=data,
            variables=variables,
            logger=self._logger.getChild("Constraints"),
        )

        registrations = self._load_registrations()
        constraint_results = self._apply_constraints(registrations, context)
        self._apply_objective_terms(context)
        metadata = self._compose_metadata(variables, constraint_results)

        return ConstraintModel(
            model=model_instance,
            variables=variables,
            constraint_results=constraint_results,
            metadata=metadata,
            extras=dict(context.extra),
        )

    def _apply_constraints(
        self,
        registrations: Sequence[ConstraintRegistration],
        context: ConstraintContext,
    ) -> Tuple[ConstraintApplicationResult, ...]:
        results: List[ConstraintApplicationResult] = []
        for registration in registrations:
            result = self._apply_single_constraint(registration, context)
            results.append(result)
        return tuple(results)
'''),
    "solver": dedent('''
# src/runtime/solver.py
class SolverRunner:
    """High-level CP-SAT solver wrapper that manages parameters and logging."""

    def solve(
        self,
        constraint_model: ConstraintModel,
        *,
        log_dir: Optional[Path | str] = None,
    ) -> SolverResult:
        model = constraint_model.model
        solver = cp_model.CpSolver()
        self._apply_yaml_parameters(solver.parameters)
        self._apply_runtime_parameters(solver.parameters)

        has_objective = self._model_has_objective(model)
        callback = _BoundTracker(has_objective=has_objective)
        self._logger.info(
            "Starting CP-SAT solve (time_limit=%s, workers=%s)",
            solver.parameters.max_time_in_seconds or "default",
            solver.parameters.num_search_workers or 1,
        )
        start_time = time.perf_counter()
        status_code = solver.Solve(model, callback)
        elapsed = time.perf_counter() - start_time

        best_bound = self._normalise_bound(solver.BestObjectiveBound()) if has_objective else None
        callback.finalize(best_bound)
        status_label = self._STATUS_LABELS.get(status_code, f"STATUS_{status_code}")
        objective_value = None
        if has_objective and status_code in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            objective_value = solver.ObjectiveValue()
        gap = self._compute_relative_gap(objective_value, best_bound)

        response = solver.ResponseProto()
        solver_stats = {
            "wall_time": solver.WallTime(),
            "user_time": solver.UserTime(),
            "branches": solver.NumBranches(),
            "conflicts": solver.NumConflicts(),
        }
        deterministic_time = getattr(response, "deterministic_time", None)
        if deterministic_time not in (None, 0):
            solver_stats["deterministic_time"] = deterministic_time

        log_directory = self._resolve_log_dir(log_dir)
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        log_path = self._write_solver_log(log_directory, solver.ResponseStats(), timestamp)
        diagnostics_path = None
        if status_code == cp_model.INFEASIBLE:
            diagnostics_path = self._export_infeasible_snapshot(model, log_directory, timestamp)

        result = SolverResult(
            status=status_label,
            status_code=status_code,
            objective_value=objective_value,
            best_bound=best_bound,
            gap=gap,
            wall_time=elapsed,
            solution_count=callback.solution_count,
            best_bound_history=callback.events,
            solver_statistics=solver_stats,
            response_stats=solver.ResponseStats(),
            response=response,
            log_path=log_path,
            diagnostics_path=diagnostics_path,
        )

        summary_path = log_directory / f"solver_{timestamp}.json"
        result.write_summary(summary_path)
        return result
'''),
    "extractor": dedent('''
# src/runtime/extractor.py
class ScheduleExtractor:
    """Translate solver assignments into lab/theory/combined schedule payloads."""

    def extract(self, solver_result: SolverResult) -> ScheduleExtractionResult:
        accessor = _SolutionAccessor(self._constraint_model.model, solver_result.response)
        lab_entries = self._build_lab_entries(accessor)
        theory_entries = self._build_theory_entries(accessor)
        combined = self._combine_entries(lab_entries, theory_entries)
        instance_index = self._build_instance_index(lab_entries, theory_entries)
        return ScheduleExtractionResult(
            lab_entries=lab_entries,
            theory_entries=theory_entries,
            combined_entries=combined,
            instance_index=instance_index,
        )

    def _build_lab_entries(self, accessor: _SolutionAccessor) -> Tuple[LabScheduleEntry, ...]:
        entries: List[LabScheduleEntry] = []
        lab_sessions = self._time.lab_sessions
        for teacher_id, course_map in self._lab_vars.assignments.items():
            for course_instance_id, day_map in course_map.items():
                requirement = self._lab_vars.requirements.get(course_instance_id)
                if not requirement:
                    continue
                instance = self._instance_lookup.get(course_instance_id)
                teacher_name = (instance.teacher_name if instance else None) or self._teacher_lookup.get(teacher_id, teacher_id)
                course_code = requirement.course_code
                course_name = instance.course_name if instance else course_code
                day_pattern = self._lab_vars.day_patterns.get(course_instance_id, self._time.working_days)
                day_pattern_label = self._format_day_pattern(day_pattern)
                group_display = self._group_display.get(requirement.group_id, {})
                group = self._group_lookup.get(requirement.group_id)
                group_name = group_display.get("name") or self._format_group_name(group) or requirement.group_id
                group_index = group_display.get("index") or (group.ordinal if group else None)
                total_students = group_display.get("total_students") or (group.summary.total_student_count if group else requirement.student_count)
                course_row = self._get_course_row(instance)
                course_code_display = self._coalesce_str(
                    (course_row or {}).get("course_code_display"),
                    instance.metadata.get("course_code_display") if instance and instance.metadata else None,
                    course_code,
                )
                staff_code = self._coalesce_str(
                    (course_row or {}).get("staff_code"),
                    instance.metadata.get("staff_code") if instance and instance.metadata else None,
                    teacher_id,
                )
                batch_info = self._coalesce_str(
                    (course_row or {}).get("batch_info"),
                    (course_row or {}).get("batch_label"),
                    (course_row or {}).get("batch_name"),
                )
                num_batches = self._safe_int((course_row or {}).get("num_batches")) or 1
                is_batched = bool(batch_info) or num_batches > 1
                co_schedule_id = self._coalesce_str(
                    (course_row or {}).get("co_schedule_id"),
                    (course_row or {}).get("virtual_id"),
                    (course_row or {}).get("co_scheduled_id"),
                )
                co_schedule_group_size = self._safe_int((course_row or {}).get("co_schedule_group_size")) or 1
                co_schedule_partner_teachers = self._coalesce_str(
                    (course_row or {}).get("co_schedule_partner_teachers"),
                    (course_row or {}).get("partner_teachers"),
                )
                co_schedule_info = self._coalesce_str(
                    (course_row or {}).get("co_schedule_info"),
                    "Single session" if not co_schedule_id else f"Co-scheduled ({co_schedule_id})",
                )
                for day_index, session_map in day_map.items():
                    day_label = day_pattern[day_index % len(day_pattern)] if day_pattern else str(day_index)
                    for session_name, room_map in session_map.items():
                        session_detail = lab_sessions.get(session_name)
                        session_slots = session_detail.slots if isinstance(session_detail, LabSessionDetail) else tuple()
                        session_time = session_detail.time_range if isinstance(session_detail, LabSessionDetail) else session_name
                        for room_id, var in room_map.items():
                            if not accessor.bool_value(var):
                                continue
                            is_lunch = self._lab_session_overlaps_lunch(requirement.department, session_name)
                            entries.append(
                                LabScheduleEntry(
                                    teacher_id=teacher_id,
                                    teacher_name=teacher_name,
                                    course_instance_id=course_instance_id,
                                    course_code_display=course_code_display,
                                    course_name=course_name,
                                    group_id=requirement.group_id,
                                    group_name=group_name,
                                    group_index=group_index,
                                    total_students=total_students,
                                    day_index=day_index,
                                    day_label=day_label,
                                    day_pattern_label=day_pattern_label,
                                    session_name=session_name,
                                    session_time=session_time,
                                    session_slots=session_slots,
                                    room_id=room_id,
                                    staff_code=staff_code,
                                    batch_info=batch_info,
                                    num_batches=num_batches,
                                    is_batched=is_batched,
                                    co_schedule_id=co_schedule_id,
                                    co_schedule_group_size=co_schedule_group_size,
                                    co_schedule_partner_teachers=co_schedule_partner_teachers,
                                    co_schedule_info=co_schedule_info,
                                    is_lunch_session=is_lunch,
                                )
                            )
        return tuple(entries)
'''),
    "validator": dedent('''
# src/runtime/validator.py
class ScheduleValidator:
    """Perform structural validations on extracted lab and theory schedules."""

    def validate(
        self,
        schedule: ScheduleExtractionResult,
        *,
        checks: Optional[Iterable[str]] = None,
    ) -> ValidationReport:
        """Run configured checks against the provided schedule payload."""

        issues: List[ValidationIssue] = []
        executed: List[str] = []
        selected = self._resolve_checks(checks)
        self._logger.debug("Executing %d validation checks", len(selected))
        for name, check in selected:
            executed.append(name)
            issues.extend(check(schedule))
        severity_counts = Counter(issue.severity for issue in issues)
        metadata = {
            "lab_entries": len(schedule.lab_entries),
            "theory_entries": len(schedule.theory_entries),
            "combined_entries": len(schedule.combined_entries),
        }
        return ValidationReport(
            generated_at=datetime.utcnow(),
            issues=tuple(issues),
            executed_checks=tuple(executed),
            severity_counts=severity_counts,
            metadata=metadata,
        )

    def _check_lab_teacher_conflicts(self, schedule: ScheduleExtractionResult) -> List[ValidationIssue]:
        bucket: MutableMapping[Tuple[str, int, str], List[LabScheduleEntry]] = defaultdict(list)
        for entry in schedule.lab_entries:
            bucket[(entry.teacher_id, entry.day_index, entry.session_name)].append(entry)
        issues: List[ValidationIssue] = []
        for key, entries in bucket.items():
            if len(entries) <= 1:
                continue
            teacher_id, day_index, session_name = key
            issues.append(
                ValidationIssue(
                    category="lab_teacher_conflict",
                    severity=ValidationSeverity.ERROR,
                    message=f"Teacher {teacher_id} double-booked for lab session {session_name} on day {day_index}",
                    context={
                        "teacher_id": teacher_id,
                        "day_index": day_index,
                        "session": session_name,
                        "course_instance_ids": [entry.course_instance_id for entry in entries],
                        "rooms": [entry.room_id for entry in entries],
                    },
                )
            )
        return issues
'''),
    "pipeline": dedent('''
# src/pipeline/orchestrator.py
class PipelineOrchestrator:
    """Coordinate configuration loading, data processing, solving, and extraction."""

    def extract(self) -> ScheduleExtractionResult:
        """Extract the schedule from the solver result."""
        if self._solver_result is None:
            self.solve()

        output_dir = self.config.paths.output_root / "latest"
        output_dir.mkdir(parents=True, exist_ok=True)

        extractor = ScheduleExtractor(self._extended_data, self._model)
        timestamp_dir = self._base_dir / "output" / datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        self._latest_output_dir = timestamp_dir
        self._schedule = extractor.export(
            self._solver_result,
            output_dir=timestamp_dir,
            write_json=True,
            write_csv=True,
        )
        self._write_slot_cap_telemetry(timestamp_dir, self._schedule)
        self._write_teacher_lab_telemetry(timestamp_dir, self._schedule)
        self._write_grouping_telemetry(timestamp_dir, self._schedule)
        self._write_overlap_telemetry(timestamp_dir, self._schedule)
        return self._schedule

    def run(self) -> ScheduleExtractionResult:
        """Execute the full pipeline from config to extraction."""
        logger.info("Starting pipeline execution")
        self.load_config()
        self.load_data()
        self.load_preprocessed_data()
        self.build_model()
        self.solve()
        return self.extract()
'''),
    "telemetry_slot_caps": dedent('''
# src/telemetry/slot_caps.py
@dataclass
class SlotCapTelemetryBuilder:
    """Aggregate constraint details and realised usage into dashboard telemetry."""

    constraint_results: Sequence[ConstraintApplicationResult]
    slot_cap_settings: Mapping[str, Mapping[str, Any]]
    timestamp: Optional[datetime] = None

    def build(self, schedule: ScheduleExtractionResult) -> Mapping[str, Any]:
        lab_entries = schedule.lab_entries if schedule else tuple()
        group_usage = _build_group_usage(lab_entries)
        semester_usage = _build_semester_usage(lab_entries)
        group_metadata = _collect_group_metadata(schedule.instance_index.values())

        core_payload = self._build_group_payload(
            "core_group_slot_cap",
            group_usage,
            group_metadata,
            self._core_groups_from_constraints(),
        )
        computing_payload = self._build_group_payload(
            "computing_group_slot_cap",
            group_usage,
            group_metadata,
            self._computing_groups_from_constraints(),
        )
        semester_payload = self._build_semester_payload(
            semester_usage,
            self._semester_tokens_from_constraints(),
        )

        summary = {
            "groups_monitored": len(core_payload) + len(computing_payload),
            "groups_over_limit": sum(1 for entry in (*core_payload, *computing_payload) if entry["breached"]),
            "semesters_over_limit": sum(1 for entry in semester_payload if entry["breached"]),
        }

        payload = {
            "generated_at": (self.timestamp or datetime.now(timezone.utc)).isoformat(),
            "limits": self._merged_settings(),
            "summary": summary,
            "core_groups": core_payload,
            "computing_groups": computing_payload,
            "semesters": semester_payload,
            "constraints": self._serialize_constraint_results(),
        }
        return payload
'''),
}


def iter_snippets() -> Iterable[Tuple[str, str]]:
    """Yield `(name, code)` pairs to keep the appendix tooling simple."""

    return APPENDIX_SNIPPETS.items()
