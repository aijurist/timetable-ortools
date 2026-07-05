"""Student course eligibility for selective PE/OE and auto-seeded core courses."""

from __future__ import annotations

import csv
import io
import uuid
from typing import Literal, Optional, Sequence

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.exceptions import ValidationError
from app.core.logger import logger
from app.models.course import Course, ElectiveType
from app.models.curriculum import (
    CourseOffering,
    OfferingBucket,
    SelectionPolicy,
    SchedulingTarget,
    TargetRequirement,
    TargetType,
)
from app.models.selection import EligibilitySource, StudentCourseEligibility
from app.models.institution import Department
from app.models.student import StudentProfile
from app.models.user import User

import app.services.selection_window_service as window_svc


async def list_eligibility(
    db: AsyncSession,
    *,
    academic_term_id: uuid.UUID,
    department_id: uuid.UUID | None = None,
    study_semester: int | None = None,
    course_id: uuid.UUID | None = None,
    student_ids: Sequence[uuid.UUID] | None = None,
) -> list[StudentCourseEligibility]:
    q = select(StudentCourseEligibility).where(
        StudentCourseEligibility.academic_term_id == academic_term_id
    )
    if department_id is not None:
        q = q.where(StudentCourseEligibility.department_id == department_id)
    if study_semester is not None:
        q = q.where(StudentCourseEligibility.study_semester == study_semester)
    if course_id is not None:
        q = q.where(StudentCourseEligibility.course_id == course_id)
    if student_ids is not None:
        q = q.where(StudentCourseEligibility.student_id.in_(student_ids))
    result = await db.execute(q.order_by(StudentCourseEligibility.student_id))
    return list(result.scalars().all())


async def get_eligible_course_ids(
    db: AsyncSession,
    profile: StudentProfile,
    *,
    academic_term_id: uuid.UUID,
    department_id: uuid.UUID,
    study_semester: int,
) -> set[uuid.UUID]:
    result = await db.execute(
        select(StudentCourseEligibility.course_id).where(
            StudentCourseEligibility.student_id == profile.id,
            StudentCourseEligibility.academic_term_id == academic_term_id,
            StudentCourseEligibility.department_id == department_id,
            StudentCourseEligibility.study_semester == study_semester,
        )
    )
    return {row[0] for row in result.all()}


async def bulk_update_eligibility(
    db: AsyncSession,
    *,
    student_profile_ids: list[uuid.UUID],
    course_id: uuid.UUID,
    academic_term_id: uuid.UUID,
    study_semester: int,
    action: Literal["assign", "remove"],
    source: EligibilitySource,
    restrict_to_dept_id: uuid.UUID | None = None,
) -> int:
    if not student_profile_ids:
        return 0

    profiles_result = await db.execute(
        select(StudentProfile, User.department_id)
        .join(User, StudentProfile.user_id == User.id)
        .where(StudentProfile.id.in_(student_profile_ids))
    )
    profiles = profiles_result.all()
    if len(profiles) != len(set(student_profile_ids)):
        raise ValidationError("One or more student profiles were not found")

    for _profile, dept_id in profiles:
        if restrict_to_dept_id is not None and dept_id != restrict_to_dept_id:
            raise ValidationError(
                "One or more students are outside your department scope"
            )

    if action == "assign":
        mismatched = [
            profile.id
            for profile, _dept_id in profiles
            if profile.semester is not None and profile.semester != study_semester
        ]
        if mismatched:
            raise ValidationError(
                f"{len(mismatched)} selected student(s) are not in semester {study_semester}"
            )

    if action == "remove":
        result = await db.execute(
            delete(StudentCourseEligibility).where(
                StudentCourseEligibility.student_id.in_(student_profile_ids),
                StudentCourseEligibility.course_id == course_id,
                StudentCourseEligibility.academic_term_id == academic_term_id,
                StudentCourseEligibility.study_semester == study_semester,
                StudentCourseEligibility.source.in_(
                    (EligibilitySource.PE, EligibilitySource.OE, EligibilitySource.MANUAL)
                ),
            )
        )
        await db.flush()
        return result.rowcount or 0

    # Eligibility is per course — teachers may assign a student to one PE/OE course,
    # several in the same pool, or none. Student selection still picks one offering
    # per CHOOSE_COURSE bucket at confirm time.

    rows = []
    for profile, dept_id in profiles:
        if profile.semester is not None and profile.semester != study_semester:
            continue
        rows.append(
            {
                "id": uuid.uuid4(),
                "student_id": profile.id,
                "course_id": course_id,
                "academic_term_id": academic_term_id,
                "department_id": dept_id,
                "study_semester": study_semester,
                "source": source,
            }
        )

    if not rows:
        return 0

    stmt = insert(StudentCourseEligibility).values(rows)
    stmt = stmt.on_conflict_do_nothing(
        index_elements=[
            "student_id",
            "course_id",
            "academic_term_id",
            "study_semester",
        ]
    )
    result = await db.execute(stmt)
    await db.flush()
    return result.rowcount or len(rows)


async def clear_core_eligibility(
    db: AsyncSession,
    profile_ids: Sequence[uuid.UUID],
    *,
    academic_term_id: uuid.UUID,
    study_semester: int,
) -> int:
    if not profile_ids:
        return 0
    result = await db.execute(
        delete(StudentCourseEligibility).where(
            StudentCourseEligibility.student_id.in_(profile_ids),
            StudentCourseEligibility.academic_term_id == academic_term_id,
            StudentCourseEligibility.study_semester == study_semester,
            StudentCourseEligibility.source == EligibilitySource.CORE_AUTO,
        )
    )
    await db.flush()
    return result.rowcount or 0


async def seed_core_eligibility_for_profiles(
    db: AsyncSession,
    profile_ids: Sequence[uuid.UUID],
    *,
    academic_term_id: uuid.UUID,
    department_id: uuid.UUID,
    study_semester: int,
) -> int:
    """Create CORE_AUTO eligibility rows from CHOOSE_FACULTY buckets on published scenario."""
    if not profile_ids:
        return 0

    window = await window_svc.get_window(
        db, academic_term_id, department_id, study_semester
    )
    if window is None or window.published_scenario_id is None:
        return 0

    profiles_result = await db.execute(
        select(StudentProfile).where(StudentProfile.id.in_(profile_ids))
    )
    profiles = list(profiles_result.scalars().all())
    course_ids: set[uuid.UUID] = set()

    for profile in profiles:
        if profile.batch_id is None:
            continue
        reqs = await db.execute(
            select(TargetRequirement)
            .where(TargetRequirement.target_id == profile.batch_id)
            .options(
                selectinload(TargetRequirement.bucket).selectinload(
                    OfferingBucket.offerings
                )
            )
        )
        for req in reqs.scalars().all():
            bucket = req.bucket
            if bucket is None:
                continue
            if bucket.scenario_id and bucket.scenario_id != window.published_scenario_id:
                continue
            if bucket.selection_policy != SelectionPolicy.CHOOSE_FACULTY:
                continue
            for offering in bucket.offerings:
                if offering.course_id:
                    course_ids.add(offering.course_id)

    if not course_ids:
        return 0

    await clear_core_eligibility(
        db,
        profile_ids,
        academic_term_id=academic_term_id,
        study_semester=study_semester,
    )

    rows = []
    for profile in profiles:
        if profile.batch_id is None:
            continue
        for course_id in course_ids:
            rows.append(
                {
                    "id": uuid.uuid4(),
                    "student_id": profile.id,
                    "course_id": course_id,
                    "academic_term_id": academic_term_id,
                    "department_id": department_id,
                    "study_semester": study_semester,
                    "source": EligibilitySource.CORE_AUTO,
                }
            )

    if not rows:
        return 0

    stmt = insert(StudentCourseEligibility).values(rows)
    stmt = stmt.on_conflict_do_nothing(
        index_elements=[
            "student_id",
            "course_id",
            "academic_term_id",
            "study_semester",
        ]
    )
    await db.execute(stmt)
    await db.flush()
    logger.info(
        "Seeded core eligibility",
        profiles=len(profiles),
        courses=len(course_ids),
    )
    return len(rows)


def infer_eligibility_source(course: Course | None) -> EligibilitySource:
    if course is None or course.elective_type is None:
        return EligibilitySource.MANUAL
    if course.elective_type == ElectiveType.PROFESSIONAL:
        return EligibilitySource.PE
    if course.elective_type == ElectiveType.OPEN:
        return EligibilitySource.OE
    return EligibilitySource.MANUAL


async def filter_buckets_for_student(
    db: AsyncSession,
    buckets: list[OfferingBucket],
    *,
    profile: StudentProfile,
    academic_term_id: uuid.UUID,
    department_id: uuid.UUID,
    study_semester: int,
) -> list[OfferingBucket]:
    eligible_course_ids = await get_eligible_course_ids(
        db,
        profile,
        academic_term_id=academic_term_id,
        department_id=department_id,
        study_semester=study_semester,
    )

    filtered: list[OfferingBucket] = []
    for bucket in buckets:
        if bucket.selection_policy == SelectionPolicy.CHOOSE_FACULTY:
            filtered.append(bucket)
            continue
        if bucket.selection_policy == SelectionPolicy.CHOOSE_COURSE:
            eligible_offerings = [
                o
                for o in bucket.offerings
                if o.course_id and o.course_id in eligible_course_ids
            ]
            if eligible_offerings:
                bucket.offerings = eligible_offerings
                filtered.append(bucket)
    return filtered


def filter_menu_items_for_student(
    bucket_items: list,
    eligible_course_ids: set[uuid.UUID],
) -> list:
    """Keep only eligible PE/OE offerings inside CHOOSE_COURSE menu buckets."""
    from app.schemas.selection import BucketMenuItem

    filtered: list[BucketMenuItem] = []
    for bucket in bucket_items:
        if bucket.selection_policy == SelectionPolicy.CHOOSE_FACULTY.value:
            filtered.append(bucket)
            continue
        if bucket.selection_policy == SelectionPolicy.CHOOSE_COURSE.value:
            eligible_offerings = [
                o
                for o in bucket.offerings
                if o.course_id and o.course_id in eligible_course_ids
            ]
            if eligible_offerings:
                filtered.append(
                    bucket.model_copy(update={"offerings": eligible_offerings})
                )
            continue
        filtered.append(bucket)
    return filtered


async def list_elective_courses_for_dept_sem(
    db: AsyncSession,
    *,
    department_id: uuid.UUID,
    study_semester: int,
    scenario_id: uuid.UUID | None = None,
) -> list[dict]:
    """Return PE/OE courses from CHOOSE_COURSE buckets for a dept/semester.

    When ``scenario_id`` is set (published selection window), only buckets on
    that scenario are included.  Otherwise all matching buckets for the dept
    are returned so planning staff can assign eligibility before publishing.
    """
    q = (
        select(OfferingBucket, Course)
        .join(CourseOffering, CourseOffering.bucket_id == OfferingBucket.id)
        .join(Course, CourseOffering.course_id == Course.id)
        .where(
            OfferingBucket.department_id == department_id,
            OfferingBucket.selection_policy == SelectionPolicy.CHOOSE_COURSE,
            CourseOffering.study_semester == study_semester,
        )
    )
    if scenario_id is not None:
        q = q.where(OfferingBucket.scenario_id == scenario_id)

    result = await db.execute(q)
    seen: set[uuid.UUID] = set()
    items: list[dict] = []
    for bucket, course in result.all():
        if course.id in seen:
            continue
        seen.add(course.id)
        items.append(
            {
                "course_id": course.id,
                "course_code": course.code,
                "course_name": course.name,
                "elective_type": course.elective_type.value if course.elective_type else None,
                "bucket_id": bucket.id,
                "bucket_name": bucket.name,
            }
        )
    items.sort(key=lambda x: (x["course_code"] or ""))
    return items


async def list_elective_courses_for_published_scenario(
    db: AsyncSession,
    *,
    academic_term_id: uuid.UUID,
    department_id: uuid.UUID,
    study_semester: int,
) -> list[dict]:
    """Return CHOOSE_COURSE bucket courses for the published selection window scenario."""
    window = await window_svc.get_window(
        db, academic_term_id, department_id, study_semester
    )
    if window is None or window.published_scenario_id is None:
        return []

    return await list_elective_courses_for_dept_sem(
        db,
        department_id=department_id,
        study_semester=study_semester,
        scenario_id=window.published_scenario_id,
    )


async def get_published_context(
    db: AsyncSession,
    *,
    academic_term_id: uuid.UUID,
    department_id: uuid.UUID,
    study_semester: int,
) -> dict:
    """Return published scenario, cohorts, and PE/OE courses for planning UI."""
    window = await window_svc.get_window(
        db, academic_term_id, department_id, study_semester
    )
    scenario_id = (
        window.published_scenario_id
        if window is not None and window.published_scenario_id is not None
        else None
    )

    elective_courses = await list_elective_courses_for_dept_sem(
        db,
        department_id=department_id,
        study_semester=study_semester,
        scenario_id=scenario_id,
    )

    if scenario_id is None:
        targets_result = await db.execute(
            select(SchedulingTarget)
            .where(
                SchedulingTarget.academic_term_id == academic_term_id,
                SchedulingTarget.department_id == department_id,
                SchedulingTarget.target_type.in_((TargetType.BATCH, TargetType.COHORT)),
                SchedulingTarget.is_active.is_(True),
            )
            .order_by(SchedulingTarget.name)
        )
    else:
        targets_result = await db.execute(
            select(SchedulingTarget)
            .where(
                SchedulingTarget.academic_term_id == academic_term_id,
                SchedulingTarget.department_id == department_id,
                SchedulingTarget.scenario_id == scenario_id,
                SchedulingTarget.target_type.in_((TargetType.BATCH, TargetType.COHORT)),
                SchedulingTarget.is_active.is_(True),
            )
            .order_by(SchedulingTarget.name)
        )

    cohorts = [
        {
            "id": target.id,
            "name": target.name,
            "target_type": target.target_type.value,
        }
        for target in targets_result.scalars().all()
    ]

    return {
        "published_scenario_id": scenario_id,
        "cohorts": cohorts,
        "elective_courses": elective_courses,
    }


async def export_eligibility_csv(
    db: AsyncSession,
    *,
    academic_term_id: uuid.UUID,
    department_id: uuid.UUID | None = None,
    study_semester: int | None = None,
    source: EligibilitySource | None = None,
) -> str:
    """Generate a CSV string of PE/OE eligibility data.

    Joins StudentCourseEligibility → StudentProfile → User → Course → Department
    and returns a UTF-8 CSV string ready for a StreamingResponse.

    Columns
    -------
    enrollment_number, student_name, email, semester, program, degree_type,
    department_code, department_name, course_code, course_name, elective_type,
    eligibility_source, assigned_at
    """
    q = (
        select(
            StudentCourseEligibility,
            StudentProfile,
            User,
            Course,
            Department,
        )
        .join(StudentProfile, StudentProfile.id == StudentCourseEligibility.student_id)
        .join(User, User.id == StudentProfile.user_id)
        .join(Course, Course.id == StudentCourseEligibility.course_id)
        .join(Department, Department.id == StudentCourseEligibility.department_id)
        .where(StudentCourseEligibility.academic_term_id == academic_term_id)
    )
    if department_id is not None:
        q = q.where(StudentCourseEligibility.department_id == department_id)
    if study_semester is not None:
        q = q.where(StudentCourseEligibility.study_semester == study_semester)
    if source is not None:
        q = q.where(StudentCourseEligibility.source == source)

    # Order by department, semester, then roll number for readability
    q = q.order_by(
        Department.code,
        StudentCourseEligibility.study_semester,
        StudentProfile.enrollment_number,
        Course.code,
    )

    result = await db.execute(q)
    rows = result.all()

    output = io.StringIO()
    writer = csv.writer(output)

    # Header row
    writer.writerow([
        "enrollment_number",
        "student_name",
        "email",
        "semester",
        "program",
        "degree_type",
        "department_code",
        "department_name",
        "course_code",
        "course_name",
        "elective_type",
        "eligibility_source",
        "assigned_at",
    ])

    for eligibility, profile, user, course, dept in rows:
        writer.writerow([
            profile.enrollment_number or "",
            user.full_name,
            user.email,
            profile.semester or "",
            profile.program or "",
            profile.degree_type or "",
            dept.code,
            dept.name,
            course.code,
            course.name,
            course.elective_type.value if course.elective_type else "",
            eligibility.source.value,
            eligibility.created_at.isoformat() if eligibility.created_at else "",
        ])

    return output.getvalue()
