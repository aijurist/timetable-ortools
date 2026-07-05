"""
app/services/distribution/traditional.py
=========================================
TRADITIONAL distribution: fixed teacher per offering, per-batch demand.

Owns the full TRADITIONAL data-model shape (moved out of cohort_service +
allocation.service._run_inline_allocation):
  1. BATCH children of the COHORT (one per class label A, B, C…)
  2. TargetCourseDemand per BATCH × course
  3. one FIXED_BATCH OfferingBucket per BATCH × course + TargetRequirement
  4. one CourseOffering per (faculty, BATCH) assignment, honouring pinned labels
     and emitting TBA placeholders for uncovered sections.
"""
from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.course import Course
from app.models.curriculum import (
    CourseOffering,
    SchedulingTarget,
    SelectionPolicy,
    TargetType,
)
from app.services.distribution import persistence
from app.services.distribution.base import DistributionStrategy
from app.services.distribution.contracts import (
    CourseLine,
    DistributionDemand,
    DistributionResult,
)


def _label(index: int) -> str:
    """0-based index → alphabetic label (0→'A' … 25→'Z', 26→'AA' …)."""
    result = ""
    n = index
    while True:
        result = chr(ord("A") + (n % 26)) + result
        n = n // 26 - 1
        if n < 0:
            break
    return result


class TraditionalDistribution(DistributionStrategy):
    code = "TRADITIONAL_DIST"

    async def build(
        self, db: AsyncSession, demand: DistributionDemand
    ) -> DistributionResult:
        result = DistributionResult(status="OK")

        if demand.size is None or demand.class_count is None or demand.class_count < 1:
            result.warnings.append(
                "TRADITIONAL distribution needs 'size' and a derivable 'class_count'."
            )
            return result

        cohort_uuid = uuid.UUID(demand.cohort_id)
        inst_uuid = uuid.UUID(demand.institution_id)
        term_uuid = uuid.UUID(demand.academic_term_id)
        dept_uuid = uuid.UUID(demand.department_id) if demand.department_id else None
        scenario_uuid = uuid.UUID(demand.scenario_id) if demand.scenario_id else None

        # ── 1. BATCH children + 2. per-batch demand ─────────────────────────
        class_count = demand.class_count
        base_size = demand.size // class_count
        remainder = demand.size % class_count

        children: list[SchedulingTarget] = []
        for i in range(class_count):
            batch_size = base_size + (1 if i < remainder else 0)
            label = _label(i)
            child = SchedulingTarget(
                institution_id=inst_uuid,
                academic_term_id=term_uuid,
                name=f"{demand.dept_code}-{label}",
                target_type=TargetType.BATCH,
                size=batch_size,
                department_id=dept_uuid,
                parent_id=cohort_uuid,
                extra_data={
                    **(demand.cohort_extra_data or {}),
                    "section_label": label,
                    "cohort_id": demand.cohort_id,
                },
                is_active=True,
                scenario_id=scenario_uuid,
            )
            db.add(child)
            await db.flush()
            children.append(child)

        label_to_target = {_label(i): children[i] for i in range(class_count)}
        all_labels = list(label_to_target.keys())

        # ── 3 + 4. FIXED_BATCH buckets + offerings per course ───────────────
        for line in demand.courses:
            course_uuid = uuid.UUID(line.course_id)
            course = (await db.execute(
                select(Course).where(Course.id == course_uuid)
            )).scalar_one_or_none()
            course_name = course.name if course else line.course_id

            # Expand teacher tuples into (faculty_id, target) assignments.
            assignments_flat: list[tuple[str, SchedulingTarget | None]] = []
            pinned_targets: set[str] = set()
            for fid, section_count, pinned_label in line.teacher_tuples:
                if pinned_label and pinned_label in label_to_target:
                    target = label_to_target[pinned_label]
                    for _ in range(max(int(section_count or 1), 1)):
                        assignments_flat.append((fid, target))
                    pinned_targets.add(pinned_label)
                else:
                    for _ in range(max(int(section_count or 1), 1)):
                        assignments_flat.append((fid, None))

            unpinned_labels = [lb for lb in all_labels if lb not in pinned_targets]
            unpinned_idxs = [i for i, a in enumerate(assignments_flat) if a[1] is None]
            for slot_i, asg_i in enumerate(unpinned_idxs):
                if slot_i < len(unpinned_labels):
                    fid = assignments_flat[asg_i][0]
                    assignments_flat[asg_i] = (fid, label_to_target[unpinned_labels[slot_i]])

            for idx, (fid, tgt) in enumerate(assignments_flat):
                if tgt is None:
                    result.tba_created += 1
                    result.warnings.append(
                        f"Course {course_name}: section {idx + 1} has no target assigned — TBA"
                    )
                    continue
                await self._emit_fixed_batch_offering(
                    db, demand, line, course_name, tgt,
                    faculty_id=uuid.UUID(fid) if fid else None,
                    result=result,
                    inst_uuid=inst_uuid, term_uuid=term_uuid, scenario_uuid=scenario_uuid,
                )

            # Coverage check — TBA placeholders for uncovered labels.
            covered = {lb for lb in all_labels if lb in pinned_targets}
            covered.update(unpinned_labels[: len(unpinned_idxs)])
            for lb in [lb for lb in all_labels if lb not in covered]:
                tgt = label_to_target[lb]
                result.tba_created += 1
                await self._emit_fixed_batch_offering(
                    db, demand, line, course_name, tgt,
                    faculty_id=None, result=result, is_tba=True,
                    inst_uuid=inst_uuid, term_uuid=term_uuid, scenario_uuid=scenario_uuid,
                )
                result.warnings.append(
                    f"Course {course_name}: section {lb} has no teacher assigned — TBA"
                )

        await db.flush()
        return result

    async def _emit_fixed_batch_offering(
        self,
        db: AsyncSession,
        demand: DistributionDemand,
        line: CourseLine,
        course_name: str,
        tgt: SchedulingTarget,
        *,
        faculty_id: uuid.UUID | None,
        result: DistributionResult,
        inst_uuid: uuid.UUID,
        term_uuid: uuid.UUID,
        scenario_uuid: uuid.UUID | None,
        is_tba: bool = False,
    ) -> None:
        course_uuid = uuid.UUID(line.course_id)
        bucket_name = f"{course_name} — {tgt.name}"
        bucket, created = await persistence.find_or_create_bucket(
            db,
            institution_id=inst_uuid,
            academic_term_id=term_uuid,
            department_id=tgt.department_id,
            name=bucket_name,
            selection_policy=SelectionPolicy.FIXED_BATCH,
            scenario_id=scenario_uuid,
            min_selection=1,
            max_selection=1,
        )
        if created:
            result.buckets_created += 1
        await persistence.ensure_target_requirement(
            db, target_id=tgt.id, bucket_id=bucket.id
        )

        # Avoid duplicate offering for the same (bucket, course[, TBA]).
        stmt = select(CourseOffering).where(
            CourseOffering.bucket_id == bucket.id,
            CourseOffering.course_id == course_uuid,
        )
        if is_tba:
            stmt = stmt.where(CourseOffering.faculty_id.is_(None))
        if (await db.execute(stmt)).scalar_one_or_none() is not None:
            return

        ta_kwargs = line.ta_overrides.get(str(faculty_id), {}) if faculty_id else {}
        await persistence.create_offering(
            db,
            bucket_id=bucket.id,
            course_id=course_uuid,
            faculty_id=faculty_id,
            min_capacity=demand.class_size,
            is_frozen=False,
            ta_kwargs=ta_kwargs,
        )
        result.offerings_created += 1
