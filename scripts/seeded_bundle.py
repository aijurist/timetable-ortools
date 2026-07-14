"""Two-phase deterministic 2nd-year (semester-3) timetable solve, fit AROUND the fixed
senior (sem 5/7) schedule.

Phase 1: one fixed direct pass for all 19 departments around the seniors
         (every senior teacher/room/lab-session from the uploaded CSVs is reserved
         before scheduling each sem-3 department, dept-by-dept on a shared calendar).
Phase 2: LOCK each department's phase-1 labs and re-optimize ONLY theory for 25+25
         bundling. Bundling only frees theory-room slots, so locking labs guarantees
         phase-1 feasibility is preserved for every department.

Run (from the project root, with the venv active):
    # Normal sequential batching -> served output (output/timetables/seeded/, *_second_year.csv)
    PYTHONPATH=. python scripts/seeded_bundle.py

    # Parallel batch scheduling (Batch 1 || Batch 2 in different rooms, same session)
    # -> SEPARATE output (output/timetables/parallel/, *_second_year_parallel.csv);
    #    never touches the served seeded/ files. Feature is flag-gated + off by default.
    PARALLEL_BATCH=1 PYTHONPATH=. python scripts/seeded_bundle.py

    # DEBUG_DEPT=1 additionally prints each department's per-seed solve status.

Inputs : data/2/2/<Department>_course_data.csv, prod/{theory,lab}_schedule_lock.csv
         (senior locks), data/block_wise/new.csv (rooms),
         data/{core,computer}_lab_mapping.csv, data/pop.csv
Outputs: output/timetables/seeded_schedule[_parallel].json and
         data/{theory,lab}_schedule_second_year[_parallel].csv (senior-upload column format).
Then render with scripts/viz_seeded.py and scripts/viz_rooms.py (honour the same PARALLEL_BATCH flag).
"""
import logging; logging.disable(logging.CRITICAL)
import os, time, sys, json
from pathlib import Path
from collections import defaultdict
from types import SimpleNamespace
import pandas as pd
from ortools.sat.python import cp_model
from src.config.manager import ConfigManager
from src.constraints.cross_system.combined_lab_reuse import (
    annotate_stable_combined_entries,
    bind_stable_prior_footprints,
    collect_footprint_groups,
)
from src.constraints.cross_system.combined_lab_presolve import (
    CombinedPreallocationPlan,
    PreallocationInstance,
    build_maximal_section_groups,
    solve_combined_preallocation,
)
from src.data.data_loader import DataLoader
from src.data.preprocessing import DataPreprocessor
from src.models.model_builder import ModelBuilder
from src.runtime.extractor import ScheduleExtractor

base = Path.cwd()
COMB_FAMILY = {"CS23332": "DBMS", "CB23333": "DBMS", "CS23333": "OOPS"}
COMB = set(COMB_FAMILY)
COMB_ROOM_POOLS = {
    "DBMS": ("A104/105", "ANEW104", "KS02"),
    "OOPS": ("ANEW101", "ANEW102", "ANEW103"),
}
ANEW_NUMS = {"ANEW101","ANEW102","ANEW103","ANEW104","A104/105","KS02"}
L2T = {"L1": (0,1), "L2": (2,3), "L3": (3,4,5), "L4": (5,6), "L5": (7,8)}


def _day_token(value):
    token = str(value or "").strip().lower()
    return {"wednesday": "wed", "thursday": "thur", "friday": "fri"}.get(token, token)
ORDER = [
    # Combined-lab departments are kept in the established compact-to-large order.
    # The CSE-only filtered run is independently certified 5/5 feasible; a global
    # eight-department run still needs combined-footprint presolve to remove the
    # remaining sequential order dependence.
    "Computer Science and Design",
    "Computer Science and Business Systems",
    "Computer Science and Engineering Cyber Security",
    "Artificial Intelligence and Machine Learning",
    "Information Technology",
    "Artificial Intelligence and Data Science",
    "Computer Science & Engineering A",
    "Computer Science & Engineering B",
    # workshop / single-section lab-dense depts (use dept-private specialised labs, not ANEW)
    "Robotics and Automation", "Aeronautical Engineering", "Biomedical Engineering",
    "Civil Engineering", "Automobile Engineering",
    # flexible remainder
    "Electronics and Communication Engineering", "Biotechnology", "Mechatronics Engineering",
    "Mechanical Engineering", "Food Technology", "Electrical and Electronics Engineering",
    "Chemical Engineering",
]
DEPT_FILTER = tuple(
    token.strip() for token in os.environ.get("DEPT_FILTER", "").split(",") if token.strip()
)
if DEPT_FILTER:
    unknown = sorted(set(DEPT_FILTER) - set(ORDER))
    if unknown:
        raise ValueError(f"Unknown DEPT_FILTER department(s): {unknown}")
    ORDER = [department for department in ORDER if department in DEPT_FILTER]
PHASE1_DEPT_FILTER = frozenset(
    token.strip()
    for token in os.environ.get("PHASE1_DEPT_FILTER", "").split(",")
    if token.strip()
)
rooms_df = pd.read_csv("data/block_wise/new.csv", keep_default_na=False)
rid2num = {str(r["id"]): r["room_number"] for _, r in rooms_df.iterrows()}
big_nums = set(r["room_number"] for _, r in rooms_df.iterrows()
               if str(r.get("room_max_cap") or "0").replace(".","",1).isdigit() and float(r["room_max_cap"] or 0) >= 140)
room_cap = {r["room_number"]: (float(r["room_max_cap"]) if str(r.get("room_max_cap") or "0").replace(".","",1).isdigit() else 140.0) for _, r in rooms_df.iterrows()}
def _max_share(rn):
    return max(2, int(room_cap.get(rn, 140.0) // 70))

PARALLEL = os.environ.get("PARALLEL_BATCH") == "1"
# Optional run isolation: set RUN_TAG to write all JSON + CSV outputs into a separate
# folder (output/timetables/<RUN_TAG>/) so a run does not overwrite the default outputs.
RUN_TAG = os.environ.get("RUN_TAG", "").strip()
OUTDIR = (base / "output" / "timetables" / RUN_TAG) if RUN_TAG else (base / "output" / "timetables")
CSVDIR = OUTDIR if RUN_TAG else (base / "data")
OUTDIR.mkdir(parents=True, exist_ok=True)
# Phase-2 (theory bundling re-optimization) per-department time budget, seconds.
PHASE1_TIME = int(os.environ.get("PHASE1_TIME", "90"))
PHASE2_TIME = int(os.environ.get("PHASE2_TIME", "150"))
SOLVER_WORKERS = max(1, int(os.environ.get("SOLVER_WORKERS", "12")))
DIRECT_SINGLE_WORKER = os.environ.get("DIRECT_SINGLE_WORKER", "0") == "1"
DETERMINISTIC_TIE_BREAKER = int(os.environ.get("DETERMINISTIC_TIE_BREAKER", "1"))
OPTIMIZE_PHASE1 = os.environ.get("OPTIMIZE_PHASE1", "1") != "0"
PHASE1_OBJECTIVE_SCOPE = os.environ.get("PHASE1_OBJECTIVE_SCOPE", "lab_cells").strip().lower()
COMBINED_CELL_PACKING_WEIGHT = int(os.environ.get("COMBINED_CELL_PACKING_WEIGHT", "10000"))
PACK_COMBINED_CELLS = os.environ.get("PACK_COMBINED_CELLS", "1") != "0"
GLOBAL_COMBINED_PRESOLVE = os.environ.get("GLOBAL_COMBINED_PRESOLVE", "1") != "0"
COMBINED_PRESOLVE_TIME = float(os.environ.get("COMBINED_PRESOLVE_TIME", "120"))
PHASE1_ABSOLUTE_GAP = max(0.0, float(os.environ.get("PHASE1_ABSOLUTE_GAP", "0")))
FIXED_THEORY_CSV = Path(os.environ.get("FIXED_THEORY_CSV", "prod/theory_schedule_lock.csv"))
FIXED_LAB_CSV = Path(os.environ.get("FIXED_LAB_CSV", "prod/lab_schedule_lock.csv"))

def build(dept, rseed=1, parallel=None, late_mode="hard", interleave=True, combined_strict=True, lunch_mode="hard"):
    if lunch_mode != "hard":
        raise ValueError("Second-year production solves require hard lunch alignment")
    if parallel is None:
        parallel = PARALLEL
    cross = {"bundled_theory": {"enabled": True, "priority": 2, "weight": 1.0,
              "params": {"eligible_cohorts": ["*_S3"], "force_maximal_pairing": True,
                         "solo_penalty_weight": 50, "pair_load_gap_penalty_weight": 5,
                         "enforce_shared_room": True,
                         # per-slot partial pairing: unequal-hour courses bundle their
                         # overlapping hours, the longer course's extra hour(s) go solo.
                         "allow_partial_pairing": True}}}
    # Section late-day cap: keep each section mostly done before 3pm — at most 2 days
    # may run into 3:10-5pm. It stays HARD for ordinary courses; external combined
    # DBMS/OOPS/DB-Tech activities are exempt from this cap.
    if late_mode:
        cross["section_late_day"] = {"enabled": True, "priority": 6, "weight": 1.0,
              "params": {"mode": late_mode, "max_late_days": 2, "single_section_max_late_days": 2,
                         "soft_penalty_weight": 40, "late_theory_slots": [7, 8], "late_lab_sessions": ["L5"],
                         # External trainers handle these courses, so their placements
                         # do not consume a section's ordinary after-3pm allowance.
                         "excluded_course_codes": sorted(COMB),
                         # direct per-late-theory-slot penalty: pulls theory out of 3:10/4:10pm
                         # even on lab-late days (helps combined-heavy depts like CSE).
                         "late_theory_penalty_weight": 8}}
    # Lunch (11-2 = slots 3,4,5): always a HARD per-section guarantee.
    cross["lunch_alignment"] = {"enabled": True, "priority": 9, "weight": 1.0,
          "params": {"lunch_slot_window": [3, 4, 5], "minimum_free_slots": 1,
                     "penalty_weight": 300, "global_soft": False}}
    # Combined labs (DBMS / OOP-Java / DB-Tech): room-lock each section into ONE room for
    # all 4 blocks (trainer stays put) and split the 6 ANEW rooms into two FIXED disjoint
    # 3-room pools (DBMS+DB-Tech: A104/105+ANEW104+KS02[210-cap,3 sections]; OOP-Java: ANEW101/102/103).
    # Fixed (not solver-chosen) so the split holds globally across the per-department solve.
    clab = {"enforce_stable_pairing": True, "same_department_only": False,
            "solo_penalty_weight": 1000, "max_pair_pool": 8,
            # ANEW/A104 rooms remain capacity-limited to pairs; KS02 may form a
            # stable group of three, or remain at one/two when no third compatible
            # section is available. Physical-cell minimization favours filling it.
            "max_stable_group_size": 3,
            # The shared facility operates across all six calendar days because
            # departments keep their own Mon-Fri or Tue-Sat working pattern. L3 is
            # unavailable to every DBMS/OOPS/DB-Tech section.
            "blocked_sessions": ["L3"]}
    if combined_strict:  # room-lock + fixed 3+3 pools; relaxed only as a last-resort fallback
        clab["room_lock"] = True
        clab["room_pools_fixed"] = [
            [["CS23332", "CB23333"], list(COMB_ROOM_POOLS["DBMS"])],
            [["CS23333"], list(COMB_ROOM_POOLS["OOPS"])]]
    cross["combined_lab"] = {"enabled": True, "priority": 3, "weight": 1.0, "params": clab}
    # Batch interleave: opposite batches of different courses may share a lab slot (half
    # cohorts), compressing labs so sections finish earlier. Combined-lab courses are
    # whole-section (both halves) and owned by combined_lab, so they are excluded here.
    if interleave:
        cross["batch_interleave"] = {"enabled": True, "priority": 5, "weight": 1.0,
              "params": {"batch_threshold": 35, "whole_section_courses": ["CS23332", "CS23333", "CB23333"]}}
        cross["group_non_overlap"] = {"params": {"skip_labs": True}}
    lab = {}
    if dept == "Computer Science and Design":
        # CSD was independently certified only with this ordinary-lab teacher
        # presence rule disabled. Combined DBMS/OOPS trainers are already exempt;
        # this preserves the approved CSD-specific production exception.
        lab["teacher_daily_presence_lab"] = {"enabled": False}
    if parallel:
        # gate the parallel-batch feature ON (separate output; default runs unaffected).
        # Scope = dept-private core-labs only (exclude shared-pool computer-lab courses).
        # Parallel-batch scope: dept-private 2-room core-labs + pinned computer-labs
        # (each pinned to a specific 2-room set, so no shared-pool contention).
        # Combined-lab courses (CS23332/CS23333/CB23333) never qualify (140-cap ANEW).
        PBC = ["EC23321", "IT23331", "BM23322", "AE23331",
               "CB23331", "CB23332", "CD23331", "CD23332", "CS23422"]
        cross["teacher_overlap"] = {"params": {"parallel_batch_enabled": True, "parallel_batch_courses": PBC}}
        lab["room_single_assignment"] = {"params": {"parallel_batch_enabled": True, "parallel_batch_courses": PBC}}
        lab["parallel_batch_lab"] = {"enabled": True, "params": {"min_eligible_rooms": 2, "parallel_batch_courses": PBC}}
    ov = {"paths": {"courses_csv": f"data/2/2/{dept}_course_data.csv"}, "grouping": {"section_based_cohorts": ["*_S3"]},
          "constraints": {"cross_system": cross, "lab": lab}}
    cfg = ConfigManager(base_dir=base).load("config/scheduler.yaml", overrides=ov)
    res = DataLoader(cfg, base_dir=base).load()
    data = DataPreprocessor(cfg).build_extended_container(data=res)
    return ModelBuilder(config=cfg).build(data=data), data


def _phase1_lab_objective_terms(constraint_model):
    """Return the ordinary-lab terms used by the focused Phase 1 objective.

    Theory is fully re-optimized in Phase 2 after those optimal labs are locked.
    The caller adds shared combined-lab cell terms after cross-department occupancy
    is known, then installs one joint objective.
    """
    if not OPTIMIZE_PHASE1 or PHASE1_OBJECTIVE_SCOPE != "lab_cells":
        return [], 0, 0
    objective = constraint_model.extras.get("objective", {})
    penalties = objective.get("penalties", ()) if isinstance(objective, dict) else ()
    lab_terms = []
    stable_pair_terms = []
    for entry in penalties:
        if not isinstance(entry, tuple) or len(entry) < 3:
            continue
        weight, variable, tag = entry[:3]
        tag = str(tag)
        if tag.startswith("lab_interleave:"):
            lab_terms.append(int(weight) * variable)
        elif not PACK_COMBINED_CELLS and tag.startswith("combined_lab:solo"):
            # Independent department certification does not need to compact a
            # global room pool.  Keep only the direct stable-partner objective.
            stable_pair_terms.append(int(weight) * variable)
    return lab_terms + stable_pair_terms, len(lab_terms), len(stable_pair_terms)


def _configure_solver(solver, *, time_limit, absolute_gap_limit=0.0):
    """Apply one reproducible CP-SAT configuration to both solve phases."""
    solver.parameters.max_time_in_seconds = time_limit
    solver.parameters.num_search_workers = 1 if DIRECT_SINGLE_WORKER else SOLVER_WORKERS
    solver.parameters.random_seed = DETERMINISTIC_TIE_BREAKER
    solver.parameters.randomize_search = False
    if absolute_gap_limit > 0:
        solver.parameters.absolute_gap_limit = absolute_gap_limit

# ---- production fixed-schedule seed ----
# ``sen_room_slots`` is deliberately cross-domain: fixed labs are expanded to
# their covered 50-minute theory slots, so a newly generated theory class can
# never reuse a room occupied by a fixed lab (and vice versa).
sen_room_slots = set(); sen_hard_room_slots = set()
sen_teacher = defaultdict(set); load_seniors_lab = defaultdict(int)
fixed_combined_records = []
def load_seniors():
    missing = [str(path) for path in (FIXED_THEORY_CSV, FIXED_LAB_CSV) if not path.is_file()]
    if missing:
        raise FileNotFoundError(f"Missing production schedule lock file(s): {', '.join(missing)}")
    t = pd.read_csv(FIXED_THEORY_CSV, keep_default_na=False)
    l = pd.read_csv(FIXED_LAB_CSV, keep_default_na=False)
    for _, r in t.iterrows():
        try: sl = int(r["slot_index"])
        except (TypeError, ValueError): continue
        day = _day_token(r["day"]); room_slot = (str(r["room_number"]), day, sl)
        sen_room_slots.add(room_slot); sen_hard_room_slots.add(room_slot)
        sen_teacher[str(r["teacher_id"])].add((day, sl))
    for _, r in l.iterrows():
        day = _day_token(r["day"]); sess = str(r["session_name"])
        room_number = str(r["room_number"])
        load_seniors_lab[(room_number, day, sess)] += 1
        is_external_combined = str(r.get("course_code", "")).strip().upper() in COMB
        if is_external_combined:
            fixed_combined_records.append(r.to_dict())
        for s in L2T.get(sess, ()):
            sen_room_slots.add((room_number, day, s))
            if not is_external_combined:
                sen_hard_room_slots.add((room_number, day, s))
                sen_teacher[str(r["teacher_id"])].add((day, s))
load_seniors()


def _collect_combined_preallocation_instances():
    """Build the exact section identities/candidate cells used by department models."""
    collected = {}
    fixed_footprint_path = base / "config" / "combined_lab_fixed_footprints.json"
    fixed_footprints = (
        json.loads(fixed_footprint_path.read_text(encoding="utf-8"))
        if fixed_footprint_path.is_file()
        else {}
    )
    # The master DBMS/OOPS plan must always cover every department in ORDER.
    # PHASE1_DEPT_FILTER is diagnostic-only: it limits the downstream
    # departmental solves, not the shared plan they are solved around.
    for dept in ORDER:
        course_path = base / "data" / "2" / "2" / f"{dept}_course_data.csv"
        if not course_path.is_file():
            continue
        course_codes = {
            str(value).strip().upper()
            for value in pd.read_csv(course_path, usecols=["course_code"], keep_default_na=False)["course_code"]
        }
        if not course_codes.intersection(COMB):
            continue
        cm, _data = build(dept)
        lab_block = cm.variables.lab
        requirements = getattr(lab_block, "requirements", {}) or {}
        patterns = getattr(lab_block, "day_patterns", {}) or {}
        for teacher_id, course_map in lab_block.assignments.items():
            for instance_id, day_map in course_map.items():
                requirement = requirements.get(instance_id)
                code = str(getattr(requirement, "course_code", "")).strip().upper()
                family = COMB_FAMILY.get(code)
                if requirement is None or family is None:
                    continue
                pattern = tuple(_day_token(day) for day in (patterns.get(instance_id, ()) or ()))
                allowed = set()
                for day_index, session_map in day_map.items():
                    if not (0 <= day_index < len(pattern)):
                        continue
                    actual_day = pattern[day_index]
                    for session_name, room_map in session_map.items():
                        if str(session_name) == "L3":
                            continue
                        for room_id in room_map:
                            room = str(rid2num.get(str(room_id), str(room_id)))
                            if room not in COMB_ROOM_POOLS[family]:
                                continue
                            if any((room, actual_day, slot) in sen_hard_room_slots for slot in L2T.get(session_name, ())):
                                continue
                            allowed.add((room, actual_day, str(session_name)))
                section_id = getattr(requirement, "section_id", None)
                section_token = str(section_id if section_id is not None else requirement.group_id)
                configured_footprint = (
                    fixed_footprints.get(dept, {})
                    .get(family, {})
                    .get(section_token)
                )
                if configured_footprint:
                    required_cells = {
                        (str(room), _day_token(day), str(session))
                        for room, day, session in configured_footprint
                    }
                    if not required_cells.issubset(allowed):
                        missing = sorted(required_cells - allowed)
                        raise ValueError(
                            f"Invalid fixed combined footprint for {dept}/{family}/{section_token}: {missing}"
                        )
                    allowed = required_cells
                instance = PreallocationInstance(
                    department_key=dept,
                    instance_id=str(instance_id),
                    family=family,
                    course_code=code,
                    teacher_id=str(teacher_id),
                    section_key=(str(requirement.department), section_token),
                    day_pattern=pattern,
                    required_sessions=int(getattr(requirement, "required_sessions", 0) or 0),
                    allowed_cells=tuple(sorted(allowed)),
                )
                collected[instance.key] = instance
    return tuple(sorted(collected.values(), key=lambda instance: instance.key))


def _precompute_combined_plan():
    if not GLOBAL_COMBINED_PRESOLVE:
        return CombinedPreallocationPlan("DISABLED", {}, tuple(), None, 0.0)
    instances = _collect_combined_preallocation_instances()
    if not instances:
        return CombinedPreallocationPlan("EMPTY", {}, tuple(), 0.0, 0.0)
    capacities = {
        room: _max_share(room)
        for rooms in COMB_ROOM_POOLS.values()
        for room in rooms
    }
    hint_path = base / "config" / "combined_lab_pairing_hints.json"
    hint_payload = json.loads(hint_path.read_text(encoding="utf-8")) if hint_path.is_file() else {}
    preferred_clusters = {
        (str(department), str(family).upper()): tuple(tuple(map(str, cluster)) for cluster in clusters)
        for department, families in hint_payload.items()
        for family, clusters in families.items()
    }
    forced_path = base / "config" / "combined_lab_forced_groups.json"
    forced_payload = json.loads(forced_path.read_text(encoding="utf-8")) if forced_path.is_file() else {}
    forced_clusters = {
        str(family).upper(): tuple(
            tuple((str(department), str(section_token)) for department, section_token in cluster)
            for cluster in clusters
        )
        for family, clusters in forced_payload.items()
    }
    groups = build_maximal_section_groups(
        instances,
        capacities,
        preferred_clusters=preferred_clusters,
        forced_clusters=forced_clusters,
    )
    plan = solve_combined_preallocation(
        groups=groups,
        room_capacities=capacities,
        fixed_occupancy=load_seniors_lab,
        # Same-subject double days are allowed only where capacity needs them.
        # Every section block above the preferred two per day is minimized; four
        # remains an emergency ceiling because the fixed room topology makes a
        # stricter global cap infeasible.
        # This is not a teacher workload cap; external trainers remain exempt.
        max_daily_sessions=2,
        max_section_daily_sessions=4,
        preferred_section_daily_sessions=2,
        time_limit_seconds=COMBINED_PRESOLVE_TIME,
        # The master plan must be reproducible. Parallel CP-SAT workers can return
        # different tied optima whose downstream departmental feasibility differs.
        workers=1,
    )
    sizes = defaultdict(int)
    for group in groups:
        sizes[(group.family, group.size)] += 1
    print(
        "COMBINED PRESOLVE: "
        f"{plan.status} sections={len(instances)} groups={len(groups)} "
        f"sizes={dict(sorted(sizes.items()))} time={plan.wall_time_seconds:.2f}s",
        flush=True,
    )
    payload = {
        "status": plan.status,
        "wall_time_seconds": plan.wall_time_seconds,
        "objective_value": plan.objective_value,
        "groups": [
            {
                "group_id": group.group_id,
                "family": group.family,
                "size": group.size,
                "members": [
                    {
                        "department": member.department_key,
                        "instance_id": member.instance_id,
                        "course_code": member.course_code,
                        "teacher_id": member.teacher_id,
                        "section_key": list(member.section_key),
                    }
                    for member in group.members
                ],
                "footprint": [list(cell) for cell in plan.assignments.get(group.members[0].key, ())],
            }
            for group in groups
        ],
    }
    (OUTDIR / "combined_lab_preallocation.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    if plan.status not in {"OPTIMAL", "FEASIBLE"}:
        raise RuntimeError(f"Global combined-lab presolve failed: {plan.status}")
    return plan


COMBINED_PLAN = _precompute_combined_plan()
COMBINED_PLAN_OCCUPANCY = defaultdict(int)
for footprint in COMBINED_PLAN.assignments.values():
    for cell in footprint:
        COMBINED_PLAN_OCCUPANCY[cell] += 1


def _lock_department_combined_plan(model, lab_block, department):
    """Force one department's combined variables to its global presolve footprint."""
    current_occupancy = defaultdict(int)
    requirements = getattr(lab_block, "requirements", {}) or {}
    patterns = getattr(lab_block, "day_patterns", {}) or {}
    seen_instances = set()
    for _teacher_id, course_map in lab_block.assignments.items():
        for instance_id, day_map in course_map.items():
            requirement = requirements.get(instance_id)
            code = str(getattr(requirement, "course_code", "")).strip().upper()
            if code not in COMB:
                continue
            plan_key = (department, str(instance_id))
            footprint = COMBINED_PLAN.assignments.get(plan_key)
            if footprint is None:
                raise KeyError(f"Missing combined presolve assignment for {plan_key}")
            selected_cells = set(footprint)
            pattern = tuple(_day_token(day) for day in (patterns.get(instance_id, ()) or ()))
            for day_index, session_map in day_map.items():
                if not (0 <= day_index < len(pattern)):
                    continue
                actual_day = pattern[day_index]
                for session_name, room_map in session_map.items():
                    for room_id, variable in room_map.items():
                        room = str(rid2num.get(str(room_id), str(room_id)))
                        cell = (room, actual_day, str(session_name))
                        model.Add(variable == int(cell in selected_cells))
            if plan_key not in seen_instances:
                seen_instances.add(plan_key)
                for cell in footprint:
                    current_occupancy[cell] += 1
    return current_occupancy

# =================== PHASE 1: deterministic direct placement ===================
def phase1(rseed):
    labbusy = defaultdict(int); thbusy = set(); hardbusy = set(); tbusy = defaultdict(set)
    # course code(s) occupying each GENERAL 140 computer-lab cell (non-ANEW big rooms).
    # Enforces "same subject only" in a shared 140 lab across departments: two different
    # subjects may never co-schedule in one 140 cell; only same-subject 70/70 pairs.
    labcode = defaultdict(set)
    # seed seniors
    for k, v in load_seniors_lab.items(): labbusy[k] += v
    thbusy |= sen_room_slots
    hardbusy |= sen_hard_room_slots
    # Reserve every global combined footprint before ordinary scheduling starts.
    # Combined variables use hardbusy and can enter these shared cells; ordinary
    # lab/theory variables use thbusy and must schedule around them.
    for room, day, session in COMBINED_PLAN_OCCUPANCY:
        for slot in L2T.get(session, ()):
            thbusy.add((room, day, slot))
    for t, s in sen_teacher.items(): tbusy[t] |= s
    combined_history = list(fixed_combined_records)
    prior_combined_groups = collect_footprint_groups(combined_history, COMB_FAMILY)
    lab_values = {}; theory_values = {}; per_lab_occ = {}; per_lab_teacher = {}; per_th_room = {}; per_th_teacher = {}
    dept_parallel = {}; dept_late_mode = {}; dept_interleave = {}; dept_combined = {}; dept_lunch_mode = {}
    infeasible = []; p1_recs = []
    solve_order = [dept for dept in ORDER if not PHASE1_DEPT_FILTER or dept in PHASE1_DEPT_FILTER]
    for dept in solve_order:
        def attempt(parallel, late_mode, interleave, combined_strict=True, lunch_mode="hard"):
            cm, data = build(dept, parallel=parallel, late_mode=late_mode, interleave=interleave, combined_strict=combined_strict, lunch_mode=lunch_mode)
            model = cm.model; tb = cm.variables.theory; lb = cm.variables.lab
            planned_current = (
                _lock_department_combined_plan(model, lb, dept)
                if COMBINED_PLAN.assignments else defaultdict(int)
            )
            phase1_base_terms, phase1_lab_count, phase1_pair_count = _phase1_lab_objective_terms(cm)
            # reserve labs + theory + teachers
            anew_cell = defaultdict(list)   # (rn,aday,sess) -> [(course_code, students, var), ...]
            for tid, cmap in lb.assignments.items():
                for inst, dmap in cmap.items():
                    pat = lb.day_patterns.get(inst, ())
                    _req = lb.requirements.get(inst)
                    code = getattr(_req, "course_code", None) or str(inst)
                    students = int(getattr(_req, "student_count", 0) or 0)
                    for di, smap in dmap.items():
                        aday = _day_token(pat[di]) if 0 <= di < len(pat) else None
                        if aday is None: continue
                        for sess, rmap in smap.items():
                            is_external_combined = str(code).strip().upper() in COMB
                            tconf = (not is_external_combined) and any(
                                (aday, s) in tbusy.get(str(tid), set()) for s in L2T.get(sess, ())
                            )
                            for rid, var in rmap.items():
                                rn = rid2num.get(str(rid), str(rid))
                                conflict_slots = hardbusy if is_external_combined else thbusy
                                room_conflict = any((rn, aday, s) in conflict_slots for s in L2T.get(sess, ()))
                                if tconf or room_conflict: model.Add(var == 0); continue
                                if rn in big_nums or rn in ANEW_NUMS: anew_cell[(rn, aday, sess)].append((code, students, var))
                                elif labbusy.get((rn, aday, sess), 0) >= 1: model.Add(var == 0)
            combined_cell_terms = []
            for (rn, aday, sess), items in anew_cell.items():
                # block combined-lab cell entirely if seniors (or already-placed depts)
                # hold THEORY in that room during any slot the lab session spans
                cell = (rn, aday, sess)
                planned_other = max(
                    0,
                    COMBINED_PLAN_OCCUPANCY.get(cell, 0) - planned_current.get(cell, 0),
                )
                cap = max(0, _max_share(rn) - labbusy.get(cell, 0) - planned_other)
                model.Add(sum(v for _, _, v in items) <= cap)
                # Phase 1 previously replaced the global objective with ordinary
                # batch-interleave terms, accidentally dropping combined_lab:solo.
                # As a result, DBMS/OOPS sections scattered across otherwise-free
                # ANEW cells and later departments became infeasible.  Charge once
                # per NEW physical combined-lab cell (not once per section), while
                # already-occupied cells remain free so later departments pack into
                # their remaining capacity.
                combined_vars = [
                    v for code, _students, v in items
                    if str(code).strip().upper() in COMB and rn in ANEW_NUMS
                ]
                if PACK_COMBINED_CELLS and combined_vars and labbusy.get((rn, aday, sess), 0) == 0:
                    cell_used = model.NewBoolVar(f"combined_cell_used_{rn}_{aday}_{sess}")
                    model.AddMaxEquality(cell_used, combined_vars)
                    combined_cell_terms.append(cell_used)
                # 140 GENERAL computer labs (not the ANEW combined pool): usable ONLY to
                # co-schedule two sections of the SAME course from the SAME department
                # (a within-dept 70/70 pair, e.g. 64+64). Everything else -> 70 or 35 lab.
                #   * prior occupancy (seniors or an earlier department) makes the cell
                #     off-limits -> no cross-department / cross-cohort sharing
                #   * on an empty cell, each <=70 course must place 0 or 2 sections (a pair,
                #     never a lone 1); a lone <=70 class is steered out to a 70/35 lab
                #   * a >70 class keeps a singleton fallback (cannot fit a 70 or 35 room)
                if rn in big_nums and rn not in ANEW_NUMS:
                    if labbusy.get((rn, aday, sess), 0) > 0:
                        for _, _, v in items:
                            model.Add(v == 0)                 # occupied -> no cross-dept sharing
                    else:
                        bycode = defaultdict(list); csize = {}
                        for code, students, v in items:
                            bycode[code].append(v); csize[code] = students
                        for code, vs in bycode.items():
                            if csize[code] <= 70:
                                pair = model.NewBoolVar(f"pair140_{rn}_{aday}_{sess}_{code}")
                                model.Add(sum(vs) == 2 * pair)   # 0 or 2 -> pair only, no lone
            reuse_result = (
                SimpleNamespace(bindings=tuple(), candidate_bindings=0)
                if COMBINED_PLAN.assignments
                else bind_stable_prior_footprints(
                    model=model,
                    lab_block=lb,
                    prior_groups=prior_combined_groups,
                    family_by_code=COMB_FAMILY,
                    room_number_by_id=rid2num,
                    cell_occupancy=labbusy,
                    max_share=_max_share,
                )
            )
            if OPTIMIZE_PHASE1 and PHASE1_OBJECTIVE_SCOPE == "lab_cells":
                objective_terms = list(phase1_base_terms)
                objective_terms.extend(COMBINED_CELL_PACKING_WEIGHT * term for term in combined_cell_terms)
                if objective_terms:
                    model.Minimize(sum(objective_terms))
            if os.environ.get("DEBUG_DEPT") == "1" and (phase1_base_terms or combined_cell_terms):
                print(
                    "      phase1 objective: "
                    f"{phase1_lab_count} ordinary lab-cell terms + "
                    f"{phase1_pair_count} stable-pair terms + "
                    f"{len(combined_cell_terms)} physical combined-cell terms; "
                    f"{reuse_result.candidate_bindings} reusable full footprints",
                    flush=True,
                )
            for tid, skmap in tb.room_assignments.items():
                for sk, dmap in skmap.items():
                    pat = tb.course_day_patterns.get(sk, ())
                    for di, slmap in dmap.items():
                        aday = _day_token(pat[di]) if 0 <= di < len(pat) else None
                        if aday is None: continue
                        for slot, rmap in slmap.items():
                            tconf = (aday, slot) in tbusy.get(str(tid), set())
                            for rid, var in rmap.items():
                                rn = rid2num.get(str(rid), str(rid))
                                if (rn, aday, slot) in thbusy or tconf: model.Add(var == 0)
            s = cp_model.CpSolver(); _configure_solver(
                s,
                time_limit=PHASE1_TIME,
                absolute_gap_limit=PHASE1_ABSOLUTE_GAP,
            )
            s.parameters.stop_after_first_solution = not OPTIMIZE_PHASE1
            st = s.StatusName(s.Solve(model))
            if os.environ.get("DEBUG_DEPT") == "1" and st in ("OPTIMAL", "FEASIBLE"):
                selected_reuse = [
                    binding for binding in reuse_result.bindings if s.Value(binding.literal)
                ]
                if selected_reuse:
                    print(
                        f"      stable cross-dept reuse: {len(selected_reuse)} sections -> "
                        + "; ".join(
                            f"{binding.current_instance_id} with {','.join(binding.prior_member_keys)}"
                            for binding in selected_reuse
                        ),
                        flush=True,
                    )
            return st, cm, data, model, tb, lb, s
        # Late-day and lunch caps both remain hard. External combined courses are
        # exempt from the late-day cap in the constraint itself, so no soft fallback
        # is needed. Half-cohort batch interleave remains enabled.
        department_late_mode = "soft" if dept == "Computer Science and Design" else "hard"
        candidates = [(PARALLEL, department_late_mode, True, True, "hard")]
        first = candidates[0]
        used_parallel, used_late, used_il, used_cs, used_lunch = (
            PARALLEL,
            department_late_mode,
            True,
            True,
            "hard",
        )
        st = cm = data = model = tb = lb = s = None
        for cand_par, cand_late, cand_il, cand_cs, cand_lunch in candidates:
            st, cm, data, model, tb, lb, s = attempt(cand_par, cand_late, cand_il, cand_cs, cand_lunch)
            if st in ("OPTIMAL", "FEASIBLE"):
                used_parallel, used_late, used_il, used_cs, used_lunch = cand_par, cand_late, cand_il, cand_cs, cand_lunch
                if (cand_par, cand_late, cand_il, cand_cs, cand_lunch) != first:
                    print(f"    [fallback] {dept} -> late={cand_late} lunch={cand_lunch} ({st})", flush=True)
                break
        if os.environ.get("DEBUG_DEPT") == "1":
            proof = ""
            if st in ("OPTIMAL", "FEASIBLE"):
                proof = f" obj={s.ObjectiveValue():.1f} bound={s.BestObjectiveBound():.1f}"
            print(
                f"    {dept[:30]:30s} -> {st}{proof} "
                f"(late={used_late} lunch={used_lunch} il={used_il} strict={used_cs})",
                flush=True,
            )
        if st not in ("OPTIMAL", "FEASIBLE"):
            infeasible.append(dept); continue
        if os.environ.get("DEBUG_CONSECUTIVE") == "1":
            for result in cm.constraint_results:
                if "Consecutive Lab Batches" in result.name or "Lab Session Coverage" in result.name:
                    print(f"      {result.name}: {result.status} {result.details}", flush=True)
            configured_codes = set(
                cm.variables.lab.requirements[course_id].course_code
                for teacher_map in cm.variables.lab.assignments.values()
                for course_id in teacher_map
                if cm.variables.lab.requirements[course_id].course_code in
                {"BM23321", "BM23322", "FT23311", "FT23312", "BT23321", "BT23331"}
            )
            for teacher_id, course_map in cm.variables.lab.assignments.items():
                for course_id, day_map in course_map.items():
                    requirement = cm.variables.lab.requirements.get(course_id)
                    if not requirement or requirement.course_code not in configured_codes:
                        continue
                    selected = []
                    pattern = cm.variables.lab.day_patterns.get(course_id, ())
                    for day_index, session_map in day_map.items():
                        for session_name, room_map in session_map.items():
                            for room_id, var in room_map.items():
                                if s.Value(var):
                                    selected.append((pattern[day_index], session_name, rid2num.get(str(room_id), str(room_id))))
                    print(f"      consecutive selection {course_id}/{requirement.course_code}: {selected}", flush=True)
        dept_parallel[dept] = used_parallel
        dept_late_mode[dept] = used_late
        dept_interleave[dept] = used_il
        dept_combined[dept] = used_cs
        dept_lunch_mode[dept] = used_lunch
        # record lab var values (for locking) + occupancy
        lv = {}
        for tid, cmap in lb.assignments.items():
            for inst, dmap in cmap.items():
                for di, smap in dmap.items():
                    for sess, rmap in smap.items():
                        for rid, var in rmap.items():
                            if s.Value(var): lv[var.Name()] = 1
        lab_values[dept] = lv
        tv = {}
        for _teacher_id, section_map in tb.room_assignments.items():
            for _section_key, day_map in section_map.items():
                for _day_index, slot_map in day_map.items():
                    for _slot_index, room_map in slot_map.items():
                        for _room_id, variable in room_map.items():
                            if s.Value(variable):
                                tv[variable.Name()] = 1
        theory_values[dept] = tv
        ext = ScheduleExtractor(data, cm).extract(SimpleNamespace(response=s.ResponseProto()))
        locc = defaultdict(int); lteach = defaultdict(set); throom = set(); tteach = defaultdict(set)
        for e in ext.lab_entries:
            rn = str(e.room_number or e.room_id); day = _day_token(getattr(e, "day", ""))
            is_external_combined = str(e.course_code).strip().upper() in COMB
            # Planned combined occupancy was reserved globally before the pass. Do
            # not add it again to labbusy, or later departments would see it twice.
            if not (COMBINED_PLAN.assignments and is_external_combined):
                labbusy[(rn, day, e.session_name)] += 1
            locc[(rn, day, e.session_name)] += 1
            # record the subject occupying general 140 computer-lab cells (same-subject rule)
            if rn in big_nums and rn not in ANEW_NUMS:
                labcode[(rn, day, e.session_name)].add(getattr(e, "course_code", None))
            for sc in L2T.get(e.session_name, ()):
                # Reserve the physical room for later departments' theory models.
                thbusy.add((rn, day, sc))
                if not is_external_combined:
                    hardbusy.add((rn, day, sc))
                    tbusy[str(e.teacher_id)].add((day, sc))
                    lteach[str(e.teacher_id)].add((day, sc))
        combined_history.extend(
            e for e in ext.lab_entries if str(e.course_code).strip().upper() in COMB
        )
        prior_combined_groups = collect_footprint_groups(combined_history, COMB_FAMILY)
        for e in ext.theory_entries:
            rn = str(e.room_number or e.room_id); day = _day_token(getattr(e, "day", ""))
            room_slot = (rn, day, e.slot_index)
            thbusy.add(room_slot); hardbusy.add(room_slot); throom.add(room_slot)
            if e.teacher_id: tbusy[str(e.teacher_id)].add((day, e.slot_index)); tteach[str(e.teacher_id)].add((day, e.slot_index))
        per_lab_occ[dept] = locc; per_lab_teacher[dept] = lteach; per_th_room[dept] = throom; per_th_teacher[dept] = tteach
        # phase-1 schedule records (same shape as the phase-2 JSON) so the placement can be
        # inspected/verified immediately, before the long phase-2 bundling runs.
        for e in ext.theory_entries:
            p1_recs.append({"dept": dept, "kind":"theory","course":str(e.course_code),"group":str(e.group_id),
                            "day":_day_token(getattr(e,"day","")),"slot":e.slot_index,"session":None,
                            "room":str(e.room_number or e.room_id),"teacher":str(e.teacher_name or ""),"is_comb":False})
        for e in ext.lab_entries:
            p1_recs.append({"dept": dept, "kind":"lab","course":str(e.course_code),"group":str(e.group_id),
                            "day":_day_token(getattr(e,"day","")),"slot":None,"session":e.session_name,
                            "room":str(e.room_number or e.room_id),"teacher":str(e.teacher_name or ""),
                            "is_comb":str(e.course_code) in COMB,
                            "batch":str(getattr(e,"batch_label",None) or getattr(e,"batch_info",None) or "")})
    return infeasible, lab_values, theory_values, per_lab_occ, per_lab_teacher, per_th_room, per_th_teacher, dept_parallel, dept_late_mode, dept_interleave, dept_combined, p1_recs, dept_lunch_mode

phase1_order = [dept for dept in ORDER if not PHASE1_DEPT_FILTER or dept in PHASE1_DEPT_FILTER]
print(f"PHASE 1: deterministic direct pass for {len(phase1_order)} departments around production locks...", flush=True)
t0 = time.time()
res1 = phase1(DETERMINISTIC_TIE_BREAKER)
infeas = res1[0]
print(
    f"  [direct] {len(phase1_order)-len(infeas)}/{len(phase1_order)} fit ({time.time()-t0:.0f}s)"
    + ("" if infeas else " ALL FIT"),
    flush=True,
)
used_seed = DETERMINISTIC_TIE_BREAKER
infeasible, lab_values, theory_values, per_lab_occ, per_lab_teacher, per_th_room, per_th_teacher, dept_parallel, dept_late_mode, dept_interleave, dept_combined, p1_recs, dept_lunch_mode = res1
print(f"PHASE 1 done (tie-breaker {used_seed}): {len(phase1_order)-len(infeasible)}/{len(phase1_order)} fit" + (f", dropped {infeasible}" if infeasible else "") + "\n", flush=True)
# write a phase-1 JSON snapshot (labs + phase-1 theory) so placement/pairing can be
# verified immediately, without waiting for the phase-2 bundling to finish.
_p1_suf = "_parallel" if PARALLEL else ""
_p1_out = OUTDIR / f"seeded_schedule_phase1{_p1_suf}.json"
_p1_out.parent.mkdir(parents=True, exist_ok=True)
_p1_out.write_text(json.dumps(p1_recs), encoding="utf-8")
print(f"  phase-1 JSON: {len(p1_recs)} records -> {_p1_out}", flush=True)
fit_depts = [d for d in phase1_order if d not in infeasible]

# Precompute fixed lab footprints (production locks + all fitted departments'
# phase-1 labs).  Phase 2 re-solves theory only, so these rooms and teachers must
# be reserved explicitly across department models.
fixed_lab_teacher = defaultdict(set)
for t, s in sen_teacher.items(): fixed_lab_teacher[t] |= s   # includes senior theory too (fine, they're fixed)
fixed_lab_room_slots = set()
for d in fit_depts:
    for t, s in per_lab_teacher[d].items(): fixed_lab_teacher[t] |= s
    for (room_number, day, session_name), occupancy in per_lab_occ[d].items():
        if occupancy:
            for slot_index in L2T.get(session_name, ()):
                fixed_lab_room_slots.add((room_number, day, slot_index))

# =================== PHASE 2: lock labs, re-optimize theory for bundling ===================
print("PHASE 2: locking labs, re-optimizing theory for 25+25 bundling...", flush=True)
cur_th_room = {d: set(per_th_room[d]) for d in fit_depts}
cur_th_teacher = {d: {t: set(v) for t, v in per_th_teacher[d].items()} for d in fit_depts}
all_recs = []
full_theory = []; full_lab = []   # full extractor entries -> senior-format CSVs
for dept in fit_depts:
    # others' theory reservation
    res_rooms = set(sen_room_slots) | fixed_lab_room_slots
    for d in fit_depts:
        if d != dept: res_rooms |= cur_th_room[d]
    res_teacher = defaultdict(set)
    for t, s in fixed_lab_teacher.items(): res_teacher[t] |= s
    for d in fit_depts:
        if d != dept:
            for t, s in cur_th_teacher[d].items(): res_teacher[t] |= s
    cm, data = build(dept, parallel=dept_parallel.get(dept, PARALLEL), late_mode=dept_late_mode.get(dept, "hard"), interleave=dept_interleave.get(dept, True), combined_strict=dept_combined.get(dept, True), lunch_mode=dept_lunch_mode.get(dept, "hard"))
    model = cm.model; tb = cm.variables.theory; lb = cm.variables.lab
    # LOCK labs to phase-1
    lv = lab_values[dept]
    for tid, cmap in lb.assignments.items():
        for inst, dmap in cmap.items():
            for di, smap in dmap.items():
                for sess, rmap in smap.items():
                    for rid, var in rmap.items():
                        model.Add(var == (1 if var.Name() in lv else 0))
    # Seed Phase 2 with the complete feasible Phase-1 theory assignment. The
    # optimizer may move it to improve 25+25 bundling, but feasibility is no
    # longer rediscovered from scratch.
    tv = theory_values.get(dept, {})
    for _teacher_id, section_map in tb.room_assignments.items():
        for _section_key, day_map in section_map.items():
            for _day_index, slot_map in day_map.items():
                for _slot_index, room_map in slot_map.items():
                    for _room_id, variable in room_map.items():
                        model.AddHint(variable, 1 if variable.Name() in tv else 0)
    # reserve theory rooms + teachers (others)
    for tid, skmap in tb.room_assignments.items():
        for sk, dmap in skmap.items():
            pat = tb.course_day_patterns.get(sk, ())
            for di, slmap in dmap.items():
                aday = pat[di] if 0 <= di < len(pat) else None
                if aday is None: continue
                for slot, rmap in slmap.items():
                    tconf = (aday, slot) in res_teacher.get(str(tid), set())
                    for rid, var in rmap.items():
                        rn = rid2num.get(str(rid), str(rid))
                        if (rn, aday, slot) in res_rooms or tconf: model.Add(var == 0)
    s = cp_model.CpSolver(); _configure_solver(s, time_limit=PHASE2_TIME)
    st = s.StatusName(s.Solve(model))
    ext = ScheduleExtractor(data, cm).extract(SimpleNamespace(response=s.ResponseProto())) if st in ("OPTIMAL","FEASIBLE") else None
    if ext is None:
        print(f"  {dept[:38]:38s} -> {st} (phase2 failed! keeping phase-1)", flush=True)
        continue
    # update current theory occupancy for this dept
    nroom = set(); nteach = defaultdict(set)
    for e in ext.theory_entries:
        rn = str(e.room_number or e.room_id); day = _day_token(getattr(e,"day",""))
        nroom.add((rn, day, e.slot_index))
        if e.teacher_id: nteach[str(e.teacher_id)].add((day, e.slot_index))
    cur_th_room[dept] = nroom; cur_th_teacher[dept] = nteach
    full_theory.extend(ext.theory_entries); full_lab.extend(ext.lab_entries)
    for e in ext.theory_entries:
        all_recs.append({"dept": dept, "kind":"theory","course":str(e.course_code),"group":str(e.group_id),
                         "day":_day_token(getattr(e,"day","")),"slot":e.slot_index,"session":None,
                         "room":str(e.room_number or e.room_id),"teacher":str(e.teacher_name or ""),"is_comb":False})
    for e in ext.lab_entries:
        all_recs.append({"dept": dept, "kind":"lab","course":str(e.course_code),"group":str(e.group_id),
                         "day":_day_token(getattr(e,"day","")),"slot":None,"session":e.session_name,
                         "room":str(e.room_number or e.room_id),"teacher":str(e.teacher_name or ""),
                         "is_comb":str(e.course_code) in COMB,
                         "batch":str(getattr(e,"batch_label",None) or getattr(e,"batch_info",None) or "")})
    objective = f" obj={s.ObjectiveValue():.1f} bound={s.BestObjectiveBound():.1f}" if st in ("OPTIMAL", "FEASIBLE") else ""
    print(f"  {dept[:38]:38s} -> {st}{objective}", flush=True)

SUF = "_parallel" if PARALLEL else ""
outp = OUTDIR / f"seeded_schedule{SUF}.json"
outp.write_text(json.dumps(all_recs), encoding="utf-8")
# Make cross-department DBMS/OOPS grouping explicit in schedule.json and the lab CSV.
# Each co_schedule_id represents one complete, stable four-session footprint.
full_lab = list(annotate_stable_combined_entries(full_lab, COMB_FAMILY))
# App-compatible full-fidelity payload. Unlike seeded_schedule.json, this keeps
# every extractor field needed for Kutty halves, group chips and lab batches.
schedule_path = OUTDIR / "schedule.json"
schedule_path.write_text(json.dumps({
    "lab_entries": [entry.to_dict() for entry in full_lab],
    "theory_entries": [entry.to_dict() for entry in full_theory],
}, indent=2), encoding="utf-8")
# bundle count
import re
from collections import defaultdict as dd
cell = dd(list)
for r in all_recs:
    if r["kind"]=="theory":
        m=re.search(r"sec(\d+)",r["group"]); sec=m.group(1) if m else "0"
        cell[(r["dept"],sec,r["day"],r["slot"],r["room"])].append(r["course"])
nbun = sum(1 for v in cell.values() if len(set(v))>=2)
print(f"\nsaved {len(all_recs)} records -> {outp}")
print(f"bundles: {nbun} cells = {nbun*2} theory courses as 25+25 | depts scheduled: {len(fit_depts)}")

# ---- write two CSVs in the exact senior-upload format (2nd year alone) ----
import csv
def g(e, a):
    v = getattr(e, a, None); return "" if v is None else v
TH_COLS = [("day","day"),("time_slot","slot_label"),("slot_index","slot_index"),
    ("course_instance_id","course_instance_id"),("course_code","course_code"),("course_name","course_name"),
    ("session_type","session_type"),("session_number","session_number"),("teacher_id","teacher_id"),
    ("teacher_name","teacher_name"),("staff_code","staff_code"),("room_id","room_id"),("room_number","room_number"),
    ("block","block"),("student_count","student_count"),("lecture_hours","lecture_hours"),
    ("tutorial_hours","tutorial_hours"),("schedule_type","schedule_type"),("is_co_scheduled","is_co_scheduled"),
    ("capacity_info","capacity_info"),("partner_instance_id","partner_instance_id"),("bundle_half","bundle_half"),
    ("section_id","section_id"),("group_name","group_name"),
    ("group_index","group_index"),("department","department"),("semester","semester"),("day_pattern","day_pattern")]
LAB_COLS = [("day","day"),("session_name","session_name"),("time_range","session_time"),
    ("course_instance_id","course_instance_id"),("course_code","course_code"),("course_code_display","course_code_display"),
    ("course_name","course_name"),("practical_hours","practical_hours"),("teacher_id","teacher_id"),
    ("teacher_name","teacher_name"),("staff_code","staff_code"),("room_id","room_id"),("room_number","room_number"),
    ("block","block"),("capacity","capacity"),("student_count","student_count"),("total_students","total_students"),
    ("is_batched","is_batched"),("batch_info","batch_info"),("num_batches","num_batches"),
    ("schedule_type","schedule_type"),("group_name","group_name"),("group_index","group_index"),
    ("department","department"),("semester","semester"),("day_pattern","day_pattern"),
    ("is_co_scheduled","is_co_scheduled"),("co_schedule_id","co_schedule_id"),
    ("co_schedule_group_size","co_schedule_group_size"),("co_schedule_partner_teachers","co_schedule_partner_teachers"),
    ("co_schedule_info","co_schedule_info"),("batch_number","batch_number"),("batch_label","batch_label"),
    ("capacity_info","capacity_info")]
def write_csv(path, cols, entries):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f); w.writerow([c for c, _ in cols])
        for e in entries: w.writerow([g(e, a) for _, a in cols])
tp = CSVDIR / f"theory_schedule_second_year{SUF}.csv"
lp = CSVDIR / f"lab_schedule_second_year{SUF}.csv"
write_csv(tp, TH_COLS, full_theory); write_csv(lp, LAB_COLS, full_lab)
print(f"theory CSV: {len(full_theory)} rows -> {tp}")
print(f"lab CSV:    {len(full_lab)} rows -> {lp}")
