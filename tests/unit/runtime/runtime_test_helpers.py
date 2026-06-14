from __future__ import annotations

"""Shared fixtures for runtime unit tests."""

from datetime import datetime

import pandas as pd
from ortools.sat import cp_model_pb2
from ortools.sat.python import cp_model

from src.config.defaults import default_scheduler_config
from src.config.schemas import DepartmentSettings
from src.data.schemas import (
    CourseGroup,
    DataLoadResult,
    DepartmentArtifacts,
    DepartmentSchedulingPackage,
    DepartmentSemesterKey,
    ExtendedDataContainer,
    GroupRequirement,
    GroupSummary,
    LabSessionDetail,
    NormalizedCourseInstance,
    PreprocessingResult,
    RoomCollections,
    TeacherWorkloadSummary,
    TimeSystemArtifacts,
)
from src.models.model_builder import ConstraintModel
from src.models.schema import (
    GroupTimeslotRequirement,
    LabCourseRequirement,
    LabVariableBlock,
    TheoryCourseRequirement,
    TheoryVariableBlock,
    VariableCreationResult,
)
from src.runtime.solver_schema import SolverResult


def build_extended_container() -> ExtendedDataContainer:
    time_artifacts = TimeSystemArtifacts(
        theory_slots=("08:00-09:00", "09:00-10:00"),
        lab_slots=("08:00-08:50", "08:50-09:40"),
        lab_sessions={"L1": LabSessionDetail("L1", (0, 1), "08:00-10:00")},
        working_days=("monday", "tuesday"),
        lab_slot_to_theory={0: (0,), 1: (1,)},
        theory_slot_to_lab={0: (0,), 1: (1,)},
        lab_session_to_theory={"L1": (0, 1)},
    )
    default_settings = DepartmentSettings(
        day_pattern=("monday", "tuesday"),
        lunch_break_slot=None,
        lunch_slot_window=(1,),
        shift_id="SHIFT_1",
        flexible_lunch=False,
    )
    department_artifacts = DepartmentArtifacts(
        default_settings=default_settings,
        overrides={},
        day_patterns={"__default__": ("monday", "tuesday"), "Engineering": ("monday", "tuesday")},
        lunch_break_slots={"__default__": None, "Engineering": None},
        lunch_slot_windows={"__default__": (1,), "Engineering": (1,)},
        shift_assignments={},
        shift_definitions={},
        valid_shift_patterns=((3, 2),),
        flexible_lunch_departments=tuple(),
        five_pm_constraints={
            "hard": {
                "departments": ("Engineering_S3",),
                "blocked_theory_slots": (1,),
                "blocked_lab_sessions": ("L1",),
            }
        },
    )
    room_collections = RoomCollections(
        lab_rooms=pd.DataFrame({"id": ["Lab1"]}),
        theory_rooms=pd.DataFrame({"id": ["A202"]}),
        lab_room_ids=("Lab1",),
        theory_room_ids=("A202",),
        laboratory_room_ids=("Lab1",),
    )
    config = default_scheduler_config()
    data_result = DataLoadResult(
        config=config,
        courses_df=pd.DataFrame(),
        rooms_df=pd.DataFrame(),
        day_order_df=None,
        core_lab_mapping_df=None,
        computer_lab_mapping_df=None,
        teacher_preferences_df=None,
        time=time_artifacts,
        departments=department_artifacts,
        rooms=room_collections,
        teachers=("t1",),
        departments_list=("Engineering",),
        room_registry={
            "Lab1": {"room_number": "Lab1", "block": "Lab Block", "capacity": 30},
            "A202": {"room_number": "A202", "block": "A Block", "capacity": 70},
        },
        load_timestamp=datetime.utcnow(),
    )
    dept_key = DepartmentSemesterKey("Engineering", 3)
    normalized_instance = NormalizedCourseInstance(
        instance_id="C1",
        course_id="C1",
        course_code="CS101",
        course_name="Intro to CS",
        course_type="theory",
        semester=3,
        student_dept="Engineering",
        course_dept="Engineering",
        teacher_id="t1",
        teacher_name="Teacher One",
        assistant_teacher_id=None,
        assistant_teacher_name=None,
        has_lab=True,
        has_theory=True,
        lecture_hours=1,
        tutorial_hours=0,
        practical_hours=2,
        student_count=60,
        requires_special_scheduling=False,
        requires_assistant=False,
        preferred_lab_type=None,
        preferred_room_type=None,
        required_room_type=None,
        pe_flag=False,
        tags=tuple(),
        metadata={},
        raw_row_index=None,
    )
    group_summary = GroupSummary(
        num_instances=1,
        num_courses=1,
        num_teachers=1,
        lab_instances=1,
        theory_instances=1,
        total_student_count=60,
        lab_hours=2,
        theory_hours=1,
    )
    course_group = CourseGroup(
        key=dept_key,
        group_id="G1",
        ordinal=1,
        is_professional_elective=False,
        course_instance_ids=("C1",),
        teacher_ids=("t1",),
        course_codes=("CS101",),
        summary=group_summary,
        tags=tuple(),
    )
    group_requirement = GroupRequirement(
        group_id="G1",
        department="Engineering",
        semester=3,
        has_lab=True,
        required_lab_sessions=1,
        prefer_consecutive_labs=False,
        lunch_slot_window=(1,),
        five_pm_policy="hard",
        tags=tuple(),
    )
    teacher_summary = TeacherWorkloadSummary(
        teacher_id="t1",
        teacher_name="Teacher One",
        groups=("G1",),
        course_codes=("CS101",),
        course_instance_ids=("C1",),
        total_hours=3,
        lab_hours=2,
        theory_hours=1,
        total_students=60,
    )
    scheduling_package = DepartmentSchedulingPackage(
        key=dept_key,
        requirements=(group_requirement,),
        penalties=tuple(),
        teacher_workload={"t1": teacher_summary},
        metadata={},
    )
    preprocessing = PreprocessingResult(
        normalized_instances={dept_key: (normalized_instance,)},
        groups={dept_key: (course_group,)},
        scheduling_packages={dept_key: scheduling_package},
        warnings=tuple(),
        stats={},
    )
    return ExtendedDataContainer(raw=data_result, preprocessing=preprocessing)


def build_constraint_model() -> ConstraintModel:
    data = build_extended_container()
    model = cp_model.CpModel()
    lab_var = model.NewBoolVar("lab_t1_C1_d0_L1_Lab1")
    theory_var = model.NewBoolVar("grp_G1_d0_t0")
    theory_room_var = model.NewBoolVar("theory_t1_C1_d1_s0_A202")
    model.Add(theory_room_var == theory_var)
    lab_block = LabVariableBlock(
        assignments={"t1": {"C1": {0: {"L1": {"Lab1": lab_var}}}}},
        requirements={
            "C1": LabCourseRequirement(
                course_instance_id="C1",
                course_code="CS101",
                teacher_id="t1",
                group_id="G1",
                department="Engineering",
                semester=3,
                practical_hours=2,
                required_sessions=1,
                student_count=60,
                preferred_room_type=None,
                required_room_type=None,
                tags=tuple(),
            )
        },
        teacher_courses={"t1": ("C1",)},
        day_patterns={"C1": ("monday",)},
        lab_session_names=("L1",),
        room_ids=("Lab1",),
        instance_group_lookup={"C1": "G1"},
    )
    theory_block = TheoryVariableBlock(
        assignments={"t1": {"C1": {1: {0: theory_var}}}},
        room_assignments={"t1": {"C1": {1: {0: {"A202": theory_room_var}}}}},
        course_requirements={
            "C1": TheoryCourseRequirement(
                course_instance_id="C1",
                course_code="CS101",
                group_id="G1",
                teacher_id="t1",
                department="Engineering",
                semester=3,
                required_slots=1,
                lecture_hours=1,
                tutorial_hours=0,
                student_count=60,
                preferred_room_type=None,
                required_room_type=None,
                tags=tuple(),
            )
        },
        teacher_courses={"t1": ("C1",)},
        course_day_patterns={"C1": ("monday", "tuesday")},
        group_timeslots={"G1": {1: {0: theory_var}}},
        requirements={
            "G1": GroupTimeslotRequirement(
                group_id="G1",
                department="Engineering",
                semester=3,
                required_theory_slots=1,
                day_pattern=("monday", "tuesday"),
                lunch_slot_window=(1,),
                five_pm_policy="hard",
                tags=tuple(),
                base_requirement=None,
            )
        },
        day_patterns={"G1": ("monday", "tuesday")},
        theory_slot_labels=("08:00-09:00", "09:00-10:00"),
        group_course_index={"G1": ("C1",)},
        instance_group_lookup={"C1": "G1"},
        room_ids=("A202",),
    )
    variables = VariableCreationResult(lab=lab_block, theory=theory_block, metadata={})
    return ConstraintModel(
        model=model,
        variables=variables,
        constraint_results=tuple(),
        metadata={},
        extras={},
    )


def build_solver_result(model: cp_model.CpModel) -> SolverResult:
    response = cp_model_pb2.CpSolverResponse()
    response.status = cp_model.OPTIMAL
    variable_count = len(model.Proto().variables)
    response.solution.extend([1] * variable_count)
    return SolverResult(
        status="OPTIMAL",
        status_code=cp_model.OPTIMAL,
        objective_value=0.0,
        best_bound=None,
        gap=None,
        wall_time=0.01,
        solution_count=1,
        best_bound_history=tuple(),
        solver_statistics={},
        response_stats="",
        response=response,
    )
