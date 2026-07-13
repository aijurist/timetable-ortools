"""Minimum-penalty planner for second-year 25+25 theory bundles."""

from __future__ import annotations

import logging
import re
from collections import defaultdict
from dataclasses import dataclass
from typing import Dict, Mapping, Optional, Sequence, Tuple

from ortools.sat.python import cp_model

from ..config.schemas import GroupingConfig
from ..utils.time_utils import DayNormalizer
from .schemas import (
    CourseGroup,
    DataLoadResult,
    DepartmentSemesterKey,
    KuttyBundle,
    NormalizedCourseInstance,
)


@dataclass(frozen=True)
class _OfferingPair:
    first: NormalizedCourseInstance
    second: NormalizedCourseInstance
    cost: int
    feasible_slots: int
    first_feasible_slots: int
    second_feasible_slots: int
    shared_blocks: int
    first_remainder_blocks: int
    second_remainder_blocks: int
    breakdown: Mapping[str, int]


@dataclass(frozen=True)
class _StaffMatchPlan:
    pairs: Tuple[_OfferingPair, ...]
    unmatched: Tuple[NormalizedCourseInstance, ...]
    total_cost: int


class KuttyBundlePlanner:
    """Pair course codes, then permanently pair their staff offerings.

    Both matching levels are solved as deterministic CP-SAT minimum-cost
    matchings.  Candidate feasibility is computed from the same fixed schedule
    mask later used during variable creation, so a teacher already occupied by
    a third/fourth-year lock reduces or eliminates that pair before the main
    timetable model is built.
    """

    COURSE_UNMATCHED_PENALTY = 1_000_000
    OFFERING_UNMATCHED_PENALTY = 100_000
    FIXED_PRESSURE_WEIGHT = 100
    STUDENT_GAP_WEIGHT = 10
    THEORY_LOAD_GAP_WEIGHT = 5_000

    def __init__(
        self,
        config: GroupingConfig,
        *,
        excluded_course_codes: Sequence[str] = (),
        logger: Optional[logging.Logger] = None,
    ) -> None:
        self._config = config
        self._excluded_course_codes = frozenset(
            str(code).strip().upper() for code in excluded_course_codes if str(code).strip()
        )
        self._logger = logger or logging.getLogger(__name__)
        self._warnings: list[str] = []

    @property
    def warnings(self) -> Tuple[str, ...]:
        return tuple(self._warnings)

    def plan(
        self,
        normalized: Mapping[DepartmentSemesterKey, Tuple[NormalizedCourseInstance, ...]],
        groups: Mapping[DepartmentSemesterKey, Tuple[CourseGroup, ...]],
        data: DataLoadResult,
    ) -> Tuple[Dict[DepartmentSemesterKey, Tuple[KuttyBundle, ...]], Mapping[str, int]]:
        self._warnings.clear()
        if not self._config.kutty_enabled:
            return {}, {
                "cohorts": 0,
                "paired_bundles": 0,
                "singletons": 0,
                "verified_bundles": 0,
            }

        planned: Dict[DepartmentSemesterKey, Tuple[KuttyBundle, ...]] = {}
        paired_total = 0
        singleton_total = 0
        verified_total = 0
        for key in sorted(normalized, key=lambda item: (item.department, item.semester)):
            if key.semester not in self._config.kutty_semesters:
                continue
            theory_instances = tuple(
                instance
                for instance in normalized.get(key, ())
                if instance.has_theory and self._theory_hours(instance) > 0
                and instance.course_code.strip().upper() not in self._excluded_course_codes
            )
            if not theory_instances:
                continue
            cohort_bundles = self._plan_cohort(
                key,
                theory_instances,
                groups.get(key, ()),
                data,
            )
            planned[key] = cohort_bundles
            paired_total += sum(1 for bundle in cohort_bundles if bundle.is_paired)
            singleton_total += sum(1 for bundle in cohort_bundles if not bundle.is_paired)
            verified_total += len(cohort_bundles)

        return planned, {
            "cohorts": len(planned),
            "paired_bundles": paired_total,
            "singletons": singleton_total,
            "verified_bundles": verified_total,
        }

    def _plan_cohort(
        self,
        key: DepartmentSemesterKey,
        instances: Sequence[NormalizedCourseInstance],
        groups: Sequence[CourseGroup],
        data: DataLoadResult,
    ) -> Tuple[KuttyBundle, ...]:
        instance_group = {
            instance_id: group.group_id
            for group in groups
            for instance_id in group.course_instance_ids
        }
        by_code: Dict[str, list[NormalizedCourseInstance]] = defaultdict(list)
        for instance in instances:
            by_code[instance.course_code.strip()].append(instance)
        for offerings in by_code.values():
            offerings.sort(key=lambda item: (item.teacher_id, item.instance_id))

        codes = tuple(sorted(by_code))
        candidate_plans: Dict[Tuple[str, str], _StaffMatchPlan] = {}
        for index, first_code in enumerate(codes):
            for second_code in codes[index + 1 :]:
                plan = self._match_staff_offerings(
                    key,
                    by_code[first_code],
                    by_code[second_code],
                    data,
                )
                if plan.pairs:
                    candidate_plans[(first_code, second_code)] = plan

        selected_edges, unmatched_codes = self._match_course_codes(codes, by_code, candidate_plans)
        bundles: list[KuttyBundle] = []
        singleton_instances: list[NormalizedCourseInstance] = []

        for first_code, second_code in selected_edges:
            plan = candidate_plans[(first_code, second_code)]
            bundle_group_id = (
                f"{key.slug()}_kutty_{self._slug(first_code)}__{self._slug(second_code)}"
            )
            for ordinal, pairing in enumerate(
                sorted(plan.pairs, key=lambda item: (item.first.teacher_id, item.second.teacher_id)),
                start=1,
            ):
                bundles.append(
                    KuttyBundle(
                        key=key,
                        bundle_id=f"{bundle_group_id}_b{ordinal:02d}",
                        bundle_group_id=bundle_group_id,
                        first_instance_id=pairing.first.instance_id,
                        first_group_id=instance_group[pairing.first.instance_id],
                        second_instance_id=pairing.second.instance_id,
                        second_group_id=instance_group[pairing.second.instance_id],
                        delivery_mode="kutty_25x2",
                        required_blocks=pairing.shared_blocks,
                        theory_hours=self._theory_hours(pairing.first),
                        second_theory_hours=self._theory_hours(pairing.second),
                        first_remainder_blocks=pairing.first_remainder_blocks,
                        second_remainder_blocks=pairing.second_remainder_blocks,
                        pairing_score=pairing.cost,
                        feasible_slot_count=pairing.feasible_slots,
                        score_breakdown=pairing.breakdown,
                        tags=(
                            "kutty",
                            "paired",
                            "fixed_staff_pair",
                            *(('hybrid_load',) if pairing.first_remainder_blocks or pairing.second_remainder_blocks else ()),
                        ),
                    )
                )
            singleton_instances.extend(plan.unmatched)

        for code in unmatched_codes:
            singleton_instances.extend(by_code[code])

        seen_singletons: set[str] = set()
        for instance in sorted(singleton_instances, key=lambda item: (item.course_code, item.teacher_id, item.instance_id)):
            if instance.instance_id in seen_singletons:
                continue
            seen_singletons.add(instance.instance_id)
            if self._config.kutty_unmatched_policy == "error":
                raise ValueError(
                    f"No valid Kutty partner for {instance.course_code}/{instance.teacher_id} in {key.label()}"
                )
            group_id = instance_group[instance.instance_id]
            bundle_id = f"{key.slug()}_kutty_single_{self._slug(instance.instance_id)}"
            feasible = self._common_feasible_slots(instance, None, data)
            bundles.append(
                KuttyBundle(
                    key=key,
                    bundle_id=bundle_id,
                    bundle_group_id=bundle_id,
                    first_instance_id=instance.instance_id,
                    first_group_id=group_id,
                    second_instance_id=None,
                    second_group_id=None,
                    delivery_mode="legacy_full_slot",
                    required_blocks=self._theory_hours(instance),
                    theory_hours=self._theory_hours(instance),
                    second_theory_hours=0,
                    first_remainder_blocks=0,
                    second_remainder_blocks=0,
                    pairing_score=self.COURSE_UNMATCHED_PENALTY,
                    feasible_slot_count=feasible,
                    score_breakdown={"unmatched": self.COURSE_UNMATCHED_PENALTY},
                    tags=("kutty", "unmatched", "full_slot_fallback"),
                )
            )
            self._warnings.append(
                f"{key.label()}: {instance.course_code}/{instance.teacher_id} has no feasible partner "
                "after maximum-cardinality pairing and remains a full 50-minute theory offering"
            )

        self._verify_cohort(key, bundles, instances)
        self._logger.info(
            "Kutty pairing for %s: %d paired bundles, %d full-slot fallbacks",
            key.label(),
            sum(1 for item in bundles if item.is_paired),
            sum(1 for item in bundles if not item.is_paired),
        )
        return tuple(sorted(bundles, key=lambda item: item.bundle_id))

    def _verify_cohort(
        self,
        key: DepartmentSemesterKey,
        bundles: Sequence[KuttyBundle],
        instances: Sequence[NormalizedCourseInstance],
    ) -> None:
        """Fail fast when a pairing violates any delivery invariant."""

        instance_index = {instance.instance_id: instance for instance in instances}
        coverage: Dict[str, int] = defaultdict(int)
        errors: list[str] = []
        for bundle in bundles:
            for instance_id in bundle.instance_ids:
                coverage[instance_id] += 1
            first = instance_index.get(bundle.first_instance_id)
            second = instance_index.get(bundle.second_instance_id) if bundle.second_instance_id else None
            if first is None or (bundle.second_instance_id and second is None):
                errors.append(f"{bundle.bundle_id}: unknown course instance")
                continue
            expected_hours = self._theory_hours(first)
            if bundle.is_paired:
                if second is None:
                    errors.append(f"{bundle.bundle_id}: missing second half")
                    continue
                if first.course_code == second.course_code:
                    errors.append(f"{bundle.bundle_id}: halves use the same course code")
                if self._teacher_key(first) == self._teacher_key(second):
                    errors.append(f"{bundle.bundle_id}: one teacher assigned to both halves")
                second_hours = self._theory_hours(second)
                expected_shared = 2 * min(expected_hours, second_hours)
                expected_first_remainder = max(0, expected_hours - second_hours)
                expected_second_remainder = max(0, second_hours - expected_hours)
                if bundle.required_blocks != expected_shared:
                    errors.append(f"{bundle.bundle_id}: shared block count does not cover the common theory load")
                if bundle.first_remainder_blocks != expected_first_remainder:
                    errors.append(f"{bundle.bundle_id}: invalid first-course remainder block count")
                if bundle.second_remainder_blocks != expected_second_remainder:
                    errors.append(f"{bundle.bundle_id}: invalid second-course remainder block count")
                if bundle.second_theory_hours != second_hours:
                    errors.append(f"{bundle.bundle_id}: invalid second-course theory load")
                if bundle.feasible_slot_count < bundle.required_blocks:
                    errors.append(f"{bundle.bundle_id}: insufficient common fixed-free windows")
            elif bundle.required_blocks != expected_hours:
                errors.append(f"{bundle.bundle_id}: singleton block count is not full-slot theory hours")
            elif bundle.feasible_slot_count < bundle.required_blocks:
                errors.append(f"{bundle.bundle_id}: singleton has insufficient fixed-free windows")

        expected_ids = set(instance_index)
        covered_ids = set(coverage)
        if expected_ids != covered_ids:
            errors.append(
                f"instance coverage mismatch missing={sorted(expected_ids - covered_ids)} "
                f"extra={sorted(covered_ids - expected_ids)}"
            )
        duplicated = sorted(instance_id for instance_id, count in coverage.items() if count != 1)
        if duplicated:
            errors.append(f"instances assigned more than once: {duplicated}")
        if errors:
            raise ValueError(f"Kutty bundle verification failed for {key.label()}: {'; '.join(errors)}")

    def _match_course_codes(
        self,
        codes: Sequence[str],
        by_code: Mapping[str, Sequence[NormalizedCourseInstance]],
        candidates: Mapping[Tuple[str, str], _StaffMatchPlan],
    ) -> Tuple[Tuple[Tuple[str, str], ...], Tuple[str, ...]]:
        model = cp_model.CpModel()
        edge_vars = {
            edge: model.NewBoolVar(f"course_pair_{self._slug(edge[0])}_{self._slug(edge[1])}")
            for edge in candidates
        }
        unmatched_vars = {
            code: model.NewBoolVar(f"course_unmatched_{self._slug(code)}") for code in codes
        }
        for code in codes:
            incident = [var for edge, var in edge_vars.items() if code in edge]
            model.Add(sum(incident) + unmatched_vars[code] == 1)

        objective = []
        # Pair as many course codes as the feasible graph permits before
        # considering pairing quality.  This guarantees zero singleton course
        # codes for an even cohort whenever a perfect matching exists, and one
        # singleton for an odd cohort whenever a near-perfect matching exists.
        total_candidate_cost = sum(max(0, plan.total_cost) for plan in candidates.values())
        cardinality_weight = max(1, total_candidate_cost + len(codes) * 10 + 1)
        for rank, (edge, var) in enumerate(sorted(edge_vars.items()), start=1):
            objective.append((candidates[edge].total_cost + rank) * var)
        for rank, code in enumerate(codes, start=1):
            cost = cardinality_weight + rank
            objective.append(cost * unmatched_vars[code])
        model.Minimize(sum(objective))

        solver = self._new_solver()
        status = solver.Solve(model)
        if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            return tuple(), tuple(codes)
        selected = tuple(edge for edge, var in sorted(edge_vars.items()) if solver.BooleanValue(var))
        unmatched = tuple(code for code, var in unmatched_vars.items() if solver.BooleanValue(var))
        return selected, unmatched

    def _match_staff_offerings(
        self,
        key: DepartmentSemesterKey,
        first: Sequence[NormalizedCourseInstance],
        second: Sequence[NormalizedCourseInstance],
        data: DataLoadResult,
    ) -> _StaffMatchPlan:
        model = cp_model.CpModel()
        candidates: Dict[Tuple[int, int], _OfferingPair] = {}
        pair_vars: Dict[Tuple[int, int], cp_model.IntVar] = {}
        total_windows = self._total_windows(key, data)
        for first_index, first_instance in enumerate(first):
            for second_index, second_instance in enumerate(second):
                if self._teacher_key(first_instance) == self._teacher_key(second_instance):
                    continue
                first_hours = self._theory_hours(first_instance)
                second_hours = self._theory_hours(second_instance)
                shared_blocks = 2 * min(first_hours, second_hours)
                first_remainder_blocks = max(0, first_hours - second_hours)
                second_remainder_blocks = max(0, second_hours - first_hours)
                feasible_slots = self._common_feasible_slots(first_instance, second_instance, data)
                first_feasible_slots = self._common_feasible_slots(first_instance, None, data)
                second_feasible_slots = self._common_feasible_slots(second_instance, None, data)
                if feasible_slots < shared_blocks:
                    continue
                if first_feasible_slots < shared_blocks + first_remainder_blocks:
                    continue
                if second_feasible_slots < shared_blocks + second_remainder_blocks:
                    continue
                fixed_pressure = max(0, total_windows - feasible_slots)
                student_gap = abs(first_instance.student_count - second_instance.student_count)
                theory_load_gap = abs(first_hours - second_hours)
                tie_break = first_index * max(1, len(second)) + second_index
                cost = (
                    fixed_pressure * self.FIXED_PRESSURE_WEIGHT
                    + student_gap * self.STUDENT_GAP_WEIGHT
                    + theory_load_gap * self.THEORY_LOAD_GAP_WEIGHT
                    + tie_break
                )
                key_pair = (first_index, second_index)
                candidates[key_pair] = _OfferingPair(
                    first=first_instance,
                    second=second_instance,
                    cost=cost,
                    feasible_slots=feasible_slots,
                    first_feasible_slots=first_feasible_slots,
                    second_feasible_slots=second_feasible_slots,
                    shared_blocks=shared_blocks,
                    first_remainder_blocks=first_remainder_blocks,
                    second_remainder_blocks=second_remainder_blocks,
                    breakdown={
                        "fixed_schedule_pressure": fixed_pressure * self.FIXED_PRESSURE_WEIGHT,
                        "student_count_gap": student_gap * self.STUDENT_GAP_WEIGHT,
                        "theory_load_gap": theory_load_gap * self.THEORY_LOAD_GAP_WEIGHT,
                        "deterministic_tie_break": tie_break,
                    },
                )
                pair_vars[key_pair] = model.NewBoolVar(
                    f"staff_pair_{self._slug(first_instance.instance_id)}_{self._slug(second_instance.instance_id)}"
                )

        unmatched_first = [model.NewBoolVar(f"unmatched_first_{index}") for index in range(len(first))]
        unmatched_second = [model.NewBoolVar(f"unmatched_second_{index}") for index in range(len(second))]
        for index in range(len(first)):
            model.Add(
                sum(var for (left, _), var in pair_vars.items() if left == index) + unmatched_first[index] == 1
            )
        for index in range(len(second)):
            model.Add(
                sum(var for (_, right), var in pair_vars.items() if right == index) + unmatched_second[index] == 1
            )

        # Make staff-offering cardinality lexicographically stronger than every
        # quality score combined.  A feasible staff pair therefore cannot be
        # dropped merely because its load/capacity/fixed-lock penalty is large.
        total_candidate_cost = sum(max(0, candidate.cost) for candidate in candidates.values())
        unmatched_penalty = max(
            self.OFFERING_UNMATCHED_PENALTY,
            total_candidate_cost + len(first) + len(second) + 1,
        )
        objective = [candidates[key_pair].cost * var for key_pair, var in pair_vars.items()]
        objective.extend(unmatched_penalty * var for var in unmatched_first)
        objective.extend(unmatched_penalty * var for var in unmatched_second)
        model.Minimize(sum(objective))
        solver = self._new_solver()
        status = solver.Solve(model)
        if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            return _StaffMatchPlan(pairs=tuple(), unmatched=tuple((*first, *second)), total_cost=0)

        selected_pairs = tuple(
            candidates[key_pair]
            for key_pair, var in sorted(pair_vars.items())
            if solver.BooleanValue(var)
        )
        unmatched = tuple(
            [instance for index, instance in enumerate(first) if solver.BooleanValue(unmatched_first[index])]
            + [instance for index, instance in enumerate(second) if solver.BooleanValue(unmatched_second[index])]
        )
        total_cost = sum(pair.cost for pair in selected_pairs) + unmatched_penalty * len(unmatched)
        return _StaffMatchPlan(pairs=selected_pairs, unmatched=unmatched, total_cost=total_cost)

    def _common_feasible_slots(
        self,
        first: NormalizedCourseInstance,
        second: Optional[NormalizedCourseInstance],
        data: DataLoadResult,
    ) -> int:
        pattern = (
            data.departments.day_patterns.get(first.student_dept)
            or data.departments.day_patterns.get("__default__")
            or data.time.working_days
        )
        mask = data.blocking_mask
        room_ids = tuple(str(room_id) for room_id in data.rooms.theory_room_ids)
        required_capacity = max(first.student_count, second.student_count if second else 0)
        feasible = 0
        for day_label in pattern:
            normalized_day = DayNormalizer.normalize_day_name(day_label) or str(day_label).strip().lower()
            for slot_index in range(len(data.time.theory_slots)):
                if mask and mask.is_theory_slot_blocked(
                    first.teacher_id, first.instance_id, normalized_day, slot_index
                ):
                    continue
                if second and mask and mask.is_theory_slot_blocked(
                    second.teacher_id, second.instance_id, normalized_day, slot_index
                ):
                    continue
                if not self._has_common_room(
                    room_ids,
                    required_capacity,
                    first,
                    second,
                    normalized_day,
                    slot_index,
                    data,
                ):
                    continue
                feasible += 1
        return feasible

    @staticmethod
    def _has_common_room(
        room_ids: Sequence[str],
        required_capacity: int,
        first: NormalizedCourseInstance,
        second: Optional[NormalizedCourseInstance],
        day_label: str,
        slot_index: int,
        data: DataLoadResult,
    ) -> bool:
        mask = data.blocking_mask
        for room_id in room_ids:
            metadata = data.room_registry.get(str(room_id), {})
            try:
                capacity = int(float(metadata.get("capacity") or metadata.get("room_max_cap") or 0))
            except (TypeError, ValueError):
                capacity = 0
            if required_capacity > 0 and capacity < required_capacity:
                continue
            if mask and mask.is_theory_variable_blocked(
                first.teacher_id,
                first.instance_id,
                day_label,
                slot_index,
                room_id,
            ):
                continue
            if second and mask and mask.is_theory_variable_blocked(
                second.teacher_id,
                second.instance_id,
                day_label,
                slot_index,
                room_id,
            ):
                continue
            return True
        return False

    @staticmethod
    def _ltp_signature(instance: NormalizedCourseInstance) -> Tuple[int, int, int]:
        return instance.lecture_hours, instance.tutorial_hours, instance.practical_hours

    @staticmethod
    def _theory_hours(instance: NormalizedCourseInstance) -> int:
        return max(0, instance.lecture_hours + instance.tutorial_hours)

    @staticmethod
    def _teacher_key(instance: NormalizedCourseInstance) -> str:
        return str(instance.teacher_id or "").strip().removesuffix(".0")

    @staticmethod
    def _slug(value: object) -> str:
        return re.sub(r"[^A-Za-z0-9]+", "_", str(value or "").strip()).strip("_").lower() or "item"

    @staticmethod
    def _new_solver() -> cp_model.CpSolver:
        solver = cp_model.CpSolver()
        solver.parameters.num_search_workers = 1
        solver.parameters.max_time_in_seconds = 10.0
        solver.parameters.random_seed = 0
        return solver

    @staticmethod
    def _total_windows(key: DepartmentSemesterKey, data: DataLoadResult) -> int:
        pattern = (
            data.departments.day_patterns.get(key.department)
            or data.departments.day_patterns.get("__default__")
            or data.time.working_days
        )
        return len(pattern) * len(data.time.theory_slots)


__all__ = ["KuttyBundlePlanner"]
