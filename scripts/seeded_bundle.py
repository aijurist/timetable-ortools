"""Two-phase seeded 2nd-year (semester-3) timetable solve, fit AROUND the fixed
senior (sem 5/7) schedule.

Phase 1: first-solution multi-seed until all 19 departments fit around the seniors
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

Inputs : data/2/2/<Department>_course_data.csv, data/{theory,lab}_schedule_combined_only_latest_uploads.csv
         (seniors), data/block_wise/new.csv (rooms), data/{core,computer}_lab_mapping.csv, data/pop.csv
Outputs: output/timetables/seeded_schedule[_parallel].json and
         data/{theory,lab}_schedule_second_year[_parallel].csv (senior-upload column format).
Then render with scripts/viz_seeded.py and scripts/viz_rooms.py (honour the same PARALLEL_BATCH flag).
"""
import logging; logging.disable(logging.CRITICAL)
import time, sys, json
from pathlib import Path
from collections import defaultdict
from types import SimpleNamespace
import pandas as pd
from ortools.sat.python import cp_model
from src.config.manager import ConfigManager
from src.data.data_loader import DataLoader
from src.data.preprocessing import DataPreprocessor
from src.models.model_builder import ModelBuilder
from src.runtime.extractor import ScheduleExtractor

base = Path.cwd()
COMB = {"CS23332", "CS23333", "CB23333"}
ANEW_NUMS = {"ANEW101","ANEW102","ANEW103","ANEW104","A104/105","KS02"}
L2T = {"L1": (0,1), "L2": (2,3), "L3": (4,5), "L4": (5,6), "L5": (7,8)}
ORDER = [
    # combined-lab (ANEW) CS-family depts FIRST, smallest->largest. With KS02 (210-cap,
    # 3 sections) replacing KSL02 in Pool 1, the DBMS pool has enough capacity for CSE
    # (biggest, last) to fit its strict-pool room-locked combined labs. Validated.
    "Computer Science and Design",
    "Computer Science and Business Systems",
    "Computer Science and Engineering Cyber Security",
    "Artificial Intelligence and Machine Learning",
    "Information Technology",
    "Artificial Intelligence and Data Science",
    "Computer Science and Engineering",
    # workshop / single-section lab-dense depts (use dept-private specialised labs, not ANEW)
    "Robotics and Automation", "Aeronautical Engineering", "Biomedical Engineering",
    "Civil Engineering", "Automobile Engineering",
    # flexible remainder
    "Electronics and Communication Engineering", "Biotechnology", "Mechatronics Engineering",
    "Mechanical Engineering", "Food Technology", "Electrical and Electronics Engineering",
    "Chemical Engineering",
]
rooms_df = pd.read_csv("data/block_wise/new.csv", keep_default_na=False)
rid2num = {str(r["id"]): r["room_number"] for _, r in rooms_df.iterrows()}
big_nums = set(r["room_number"] for _, r in rooms_df.iterrows()
               if str(r.get("room_max_cap") or "0").replace(".","",1).isdigit() and float(r["room_max_cap"] or 0) >= 140)
room_cap = {r["room_number"]: (float(r["room_max_cap"]) if str(r.get("room_max_cap") or "0").replace(".","",1).isdigit() else 140.0) for _, r in rooms_df.iterrows()}
def _max_share(rn):
    return max(2, int(room_cap.get(rn, 140.0) // 70))

import os
PARALLEL = os.environ.get("PARALLEL_BATCH") == "1"
# Optional run isolation: set RUN_TAG to write all JSON + CSV outputs into a separate
# folder (output/timetables/<RUN_TAG>/) so a run does not overwrite the default outputs.
RUN_TAG = os.environ.get("RUN_TAG", "").strip()
OUTDIR = (base / "output" / "timetables" / RUN_TAG) if RUN_TAG else (base / "output" / "timetables")
CSVDIR = OUTDIR if RUN_TAG else (base / "data")
OUTDIR.mkdir(parents=True, exist_ok=True)
# Phase-2 (theory bundling re-optimization) per-department time budget, seconds.
PHASE2_TIME = int(os.environ.get("PHASE2_TIME", "150"))

def build(dept, rseed=1, parallel=None, late_mode="hard", interleave=True, combined_strict=True):
    if parallel is None:
        parallel = PARALLEL
    cross = {"bundled_theory": {"enabled": True, "priority": 2, "weight": 1.0,
              "params": {"eligible_cohorts": ["*_S3"], "force_maximal_pairing": False,
                         "solo_penalty_weight": 50, "enforce_shared_room": True,
                         # per-slot partial pairing: unequal-hour courses bundle their
                         # overlapping hours, the longer course's extra hour(s) go solo.
                         "allow_partial_pairing": True}}}
    # Section late-day cap: keep each section mostly done before 3pm — at most 2 days
    # may run into 3:10-5pm. Applied HARD per department where feasible; a department
    # that can't meet the hard cap falls back to SOFT (see the phase-1 attempt loop).
    if late_mode:
        cross["section_late_day"] = {"enabled": True, "priority": 6, "weight": 1.0,
              "params": {"mode": late_mode, "max_late_days": 2, "single_section_max_late_days": 2,
                         "soft_penalty_weight": 40, "late_theory_slots": [7, 8], "late_lab_sessions": ["L5"]}}
    # Combined labs (DBMS / OOP-Java / DB-Tech): room-lock each section into ONE room for
    # all 4 blocks (trainer stays put) and split the 6 ANEW rooms into two FIXED disjoint
    # 3-room pools (DBMS+DB-Tech: A104/105+ANEW104+KS02[210-cap,3 sections]; OOP-Java: ANEW101/102/103).
    # Fixed (not solver-chosen) so the split holds globally across the per-department solve.
    clab = {"enforce_stable_pairing": True, "same_department_only": False,
            "solo_penalty_weight": 1000, "max_pair_pool": 8}
    if combined_strict:  # room-lock + fixed 3+3 pools; relaxed only as a last-resort fallback
        clab["room_lock"] = True
        clab["room_pools_fixed"] = [
            [["CS23332", "CB23333"], ["A104/105", "ANEW104", "KS02"]],
            [["CS23333"], ["ANEW101", "ANEW102", "ANEW103"]]]
    cross["combined_lab"] = {"enabled": True, "priority": 3, "weight": 1.0, "params": clab}
    # Batch interleave: opposite batches of different courses may share a lab slot (half
    # cohorts), compressing labs so sections finish earlier. Combined-lab courses are
    # whole-section (both halves) and owned by combined_lab, so they are excluded here.
    if interleave:
        cross["batch_interleave"] = {"enabled": True, "priority": 5, "weight": 1.0,
              "params": {"batch_threshold": 35, "whole_section_courses": ["CS23332", "CS23333", "CB23333"]}}
        cross["group_non_overlap"] = {"params": {"skip_labs": True}}
    lab = {}
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

# ---- seniors seed ----
sen_theory_room = set(); sen_teacher = defaultdict(set); load_seniors_lab = defaultdict(int)
def load_seniors():
    t = pd.read_csv("data/theory_schedule_combined_only_latest_uploads.csv", keep_default_na=False)
    l = pd.read_csv("data/lab_schedule_combined_only_latest_uploads.csv", keep_default_na=False)
    for _, r in t.iterrows():
        try: sl = int(r["slot_index"])
        except (TypeError, ValueError): continue
        day = str(r["day"]).lower(); sen_theory_room.add((str(r["room_number"]), day, sl))
        sen_teacher[str(r["teacher_id"])].add((day, sl))
    for _, r in l.iterrows():
        day = str(r["day"]).lower(); sess = str(r["session_name"])
        load_seniors_lab[(str(r["room_number"]), day, sess)] += 1
        for s in L2T.get(sess, ()): sen_teacher[str(r["teacher_id"])].add((day, s))
load_seniors()

# =================== PHASE 1: first-solution, multi-seed until all-18 fit ===================
def phase1(rseed):
    labbusy = defaultdict(int); thbusy = set(); tbusy = defaultdict(set)
    # course code(s) occupying each GENERAL 140 computer-lab cell (non-ANEW big rooms).
    # Enforces "same subject only" in a shared 140 lab across departments: two different
    # subjects may never co-schedule in one 140 cell; only same-subject 70/70 pairs.
    labcode = defaultdict(set)
    # seed seniors
    for k, v in load_seniors_lab.items(): labbusy[k] += v
    thbusy |= sen_theory_room
    for t, s in sen_teacher.items(): tbusy[t] |= s
    lab_values = {}; per_lab_occ = {}; per_lab_teacher = {}; per_th_room = {}; per_th_teacher = {}
    dept_parallel = {}; dept_late_mode = {}; dept_interleave = {}; dept_combined = {}
    infeasible = []; p1_recs = []
    for dept in ORDER:
        def attempt(parallel, late_mode, interleave, combined_strict=True):
            cm, data = build(dept, parallel=parallel, late_mode=late_mode, interleave=interleave, combined_strict=combined_strict)
            model = cm.model; tb = cm.variables.theory; lb = cm.variables.lab
            # reserve labs + theory + teachers
            anew_cell = defaultdict(list)   # (rn,aday,sess) -> [(course_code, students, var), ...]
            for tid, cmap in lb.assignments.items():
                for inst, dmap in cmap.items():
                    pat = lb.day_patterns.get(inst, ())
                    _req = lb.requirements.get(inst)
                    code = getattr(_req, "course_code", None) or str(inst)
                    students = int(getattr(_req, "student_count", 0) or 0)
                    for di, smap in dmap.items():
                        aday = pat[di] if 0 <= di < len(pat) else None
                        if aday is None: continue
                        for sess, rmap in smap.items():
                            tconf = any((aday, s) in tbusy.get(str(tid), set()) for s in L2T.get(sess, ()))
                            for rid, var in rmap.items():
                                rn = rid2num.get(str(rid), str(rid))
                                if tconf: model.Add(var == 0); continue
                                if rn in big_nums or rn in ANEW_NUMS: anew_cell[(rn, aday, sess)].append((code, students, var))
                                elif labbusy.get((rn, aday, sess), 0) >= 1: model.Add(var == 0)
            for (rn, aday, sess), items in anew_cell.items():
                # block combined-lab cell entirely if seniors (or already-placed depts)
                # hold THEORY in that room during any slot the lab session spans
                theory_block = any((rn, aday, s) in thbusy for s in L2T.get(sess, ()))
                cap = 0 if theory_block else max(0, _max_share(rn) - labbusy.get((rn, aday, sess), 0))
                model.Add(sum(v for _, _, v in items) <= cap)
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
            for tid, skmap in tb.room_assignments.items():
                for sk, dmap in skmap.items():
                    pat = tb.course_day_patterns.get(sk, ())
                    for di, slmap in dmap.items():
                        aday = pat[di] if 0 <= di < len(pat) else None
                        if aday is None: continue
                        for slot, rmap in slmap.items():
                            tconf = (aday, slot) in tbusy.get(str(tid), set())
                            for rid, var in rmap.items():
                                rn = rid2num.get(str(rid), str(rid))
                                if (rn, aday, slot) in thbusy or tconf: model.Add(var == 0)
            s = cp_model.CpSolver(); s.parameters.max_time_in_seconds = 90
            s.parameters.num_search_workers = 12; s.parameters.stop_after_first_solution = True; s.parameters.random_seed = rseed
            st = s.StatusName(s.Solve(model))
            return st, cm, data, model, tb, lb, s
        # Fallback chain: HARD late-cap first, then relax to SOFT. Combined labs keep STRICT
        # room-lock + fixed 3+3 pools per department (combined_strict=True) throughout.
        # Batch-interleave is OFF for now (il=False). Combined-heavy depts (CSE, AIDS) whose
        # combined labs need the late L5 session naturally fall back to the SOFT late-cap.
        candidates = [(PARALLEL, "hard", False, True), (PARALLEL, "soft", False, True)]
        if PARALLEL:
            candidates += [(False, "hard", False, True), (False, "soft", False, True)]
        first = candidates[0]
        used_parallel, used_late, used_il, used_cs = PARALLEL, "hard", False, True
        st = cm = data = model = tb = lb = s = None
        for cand_par, cand_late, cand_il, cand_cs in candidates:
            st, cm, data, model, tb, lb, s = attempt(cand_par, cand_late, cand_il, cand_cs)
            if st in ("OPTIMAL", "FEASIBLE"):
                used_parallel, used_late, used_il, used_cs = cand_par, cand_late, cand_il, cand_cs
                if (cand_par, cand_late, cand_il, cand_cs) != first:
                    print(f"    [fallback] {dept} -> late={cand_late} ({st})", flush=True)
                break
        if os.environ.get("DEBUG_DEPT") == "1":
            print(f"    {dept[:34]:34s} -> {st} (late={used_late} il={used_il} strict={used_cs})", flush=True)
        if st not in ("OPTIMAL", "FEASIBLE"):
            infeasible.append(dept); continue
        dept_parallel[dept] = used_parallel
        dept_late_mode[dept] = used_late
        dept_interleave[dept] = used_il
        dept_combined[dept] = used_cs
        # record lab var values (for locking) + occupancy
        lv = {}
        for tid, cmap in lb.assignments.items():
            for inst, dmap in cmap.items():
                for di, smap in dmap.items():
                    for sess, rmap in smap.items():
                        for rid, var in rmap.items():
                            if s.Value(var): lv[var.Name()] = 1
        lab_values[dept] = lv
        ext = ScheduleExtractor(data, cm).extract(SimpleNamespace(response=s.ResponseProto()))
        locc = defaultdict(int); lteach = defaultdict(set); throom = set(); tteach = defaultdict(set)
        for e in ext.lab_entries:
            rn = str(e.room_number or e.room_id); day = str(getattr(e, "day", "")).lower()
            labbusy[(rn, day, e.session_name)] += 1; locc[(rn, day, e.session_name)] += 1
            # record the subject occupying general 140 computer-lab cells (same-subject rule)
            if rn in big_nums and rn not in ANEW_NUMS:
                labcode[(rn, day, e.session_name)].add(getattr(e, "course_code", None))
            for sc in L2T.get(e.session_name, ()): tbusy[str(e.teacher_id)].add((day, sc)); lteach[str(e.teacher_id)].add((day, sc))
        for e in ext.theory_entries:
            rn = str(e.room_number or e.room_id); day = str(getattr(e, "day", "")).lower()
            thbusy.add((rn, day, e.slot_index)); throom.add((rn, day, e.slot_index))
            if e.teacher_id: tbusy[str(e.teacher_id)].add((day, e.slot_index)); tteach[str(e.teacher_id)].add((day, e.slot_index))
        per_lab_occ[dept] = locc; per_lab_teacher[dept] = lteach; per_th_room[dept] = throom; per_th_teacher[dept] = tteach
        # phase-1 schedule records (same shape as the phase-2 JSON) so the placement can be
        # inspected/verified immediately, before the long phase-2 bundling runs.
        for e in ext.theory_entries:
            p1_recs.append({"dept": dept, "kind":"theory","course":str(e.course_code),"group":str(e.group_id),
                            "day":str(getattr(e,"day","")).lower(),"slot":e.slot_index,"session":None,
                            "room":str(e.room_number or e.room_id),"teacher":str(e.teacher_name or ""),"is_comb":False})
        for e in ext.lab_entries:
            p1_recs.append({"dept": dept, "kind":"lab","course":str(e.course_code),"group":str(e.group_id),
                            "day":str(getattr(e,"day","")).lower(),"slot":None,"session":e.session_name,
                            "room":str(e.room_number or e.room_id),"teacher":str(e.teacher_name or ""),
                            "is_comb":str(e.course_code) in COMB,
                            "batch":str(getattr(e,"batch_label",None) or getattr(e,"batch_info",None) or "")})
    return infeasible, lab_values, per_lab_occ, per_lab_teacher, per_th_room, per_th_teacher, dept_parallel, dept_late_mode, dept_interleave, dept_combined, p1_recs

print("PHASE 1: first-solution multi-seed to fit all 18 around seniors...", flush=True)
best = None
for rseed in range(1, 13):
    t0 = time.time(); res1 = phase1(rseed); infeas = res1[0]
    print(f"  [seed {rseed}] {len(ORDER)-len(infeas)}/{len(ORDER)} fit ({time.time()-t0:.0f}s)" + ("" if infeas else " ALL FIT"), flush=True)
    if best is None or len(infeas) < len(best[0][0]): best = (res1, rseed)
    if not infeas: break
res1, used_seed = best
infeasible, lab_values, per_lab_occ, per_lab_teacher, per_th_room, per_th_teacher, dept_parallel, dept_late_mode, dept_interleave, dept_combined, p1_recs = res1
print(f"PHASE 1 done (seed {used_seed}): {len(ORDER)-len(infeasible)}/{len(ORDER)} fit" + (f", dropped {infeasible}" if infeasible else "") + "\n", flush=True)
# write a phase-1 JSON snapshot (labs + phase-1 theory) so placement/pairing can be
# verified immediately, without waiting for the phase-2 bundling to finish.
_p1_suf = "_parallel" if PARALLEL else ""
_p1_out = OUTDIR / f"seeded_schedule_phase1{_p1_suf}.json"
_p1_out.parent.mkdir(parents=True, exist_ok=True)
_p1_out.write_text(json.dumps(p1_recs), encoding="utf-8")
print(f"  phase-1 JSON: {len(p1_recs)} records -> {_p1_out}", flush=True)
fit_depts = [d for d in ORDER if d not in infeasible]

# precompute fixed lab-teacher footprint (seniors + all fitted depts' locked labs)
fixed_lab_teacher = defaultdict(set)
for t, s in sen_teacher.items(): fixed_lab_teacher[t] |= s   # includes senior theory too (fine, they're fixed)
for d in fit_depts:
    for t, s in per_lab_teacher[d].items(): fixed_lab_teacher[t] |= s

# =================== PHASE 2: lock labs, re-optimize theory for bundling ===================
print("PHASE 2: locking labs, re-optimizing theory for 25+25 bundling...", flush=True)
cur_th_room = {d: set(per_th_room[d]) for d in fit_depts}
cur_th_teacher = {d: {t: set(v) for t, v in per_th_teacher[d].items()} for d in fit_depts}
all_recs = []
full_theory = []; full_lab = []   # full extractor entries -> senior-format CSVs
for dept in fit_depts:
    # others' theory reservation
    res_rooms = set(sen_theory_room)
    for d in fit_depts:
        if d != dept: res_rooms |= cur_th_room[d]
    res_teacher = defaultdict(set)
    for t, s in fixed_lab_teacher.items(): res_teacher[t] |= s
    for d in fit_depts:
        if d != dept:
            for t, s in cur_th_teacher[d].items(): res_teacher[t] |= s
    cm, data = build(dept, parallel=dept_parallel.get(dept, PARALLEL), late_mode=dept_late_mode.get(dept, "hard"), interleave=dept_interleave.get(dept, True), combined_strict=dept_combined.get(dept, True))
    model = cm.model; tb = cm.variables.theory; lb = cm.variables.lab
    # LOCK labs to phase-1
    lv = lab_values[dept]
    for tid, cmap in lb.assignments.items():
        for inst, dmap in cmap.items():
            for di, smap in dmap.items():
                for sess, rmap in smap.items():
                    for rid, var in rmap.items():
                        model.Add(var == (1 if var.Name() in lv else 0))
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
    s = cp_model.CpSolver(); s.parameters.max_time_in_seconds = PHASE2_TIME; s.parameters.num_search_workers = 12
    st = s.StatusName(s.Solve(model))
    ext = ScheduleExtractor(data, cm).extract(SimpleNamespace(response=s.ResponseProto())) if st in ("OPTIMAL","FEASIBLE") else None
    if ext is None:
        print(f"  {dept[:38]:38s} -> {st} (phase2 failed! keeping phase-1)", flush=True)
        continue
    # update current theory occupancy for this dept
    nroom = set(); nteach = defaultdict(set)
    for e in ext.theory_entries:
        rn = str(e.room_number or e.room_id); day = str(getattr(e,"day","")).lower()
        nroom.add((rn, day, e.slot_index))
        if e.teacher_id: nteach[str(e.teacher_id)].add((day, e.slot_index))
    cur_th_room[dept] = nroom; cur_th_teacher[dept] = nteach
    full_theory.extend(ext.theory_entries); full_lab.extend(ext.lab_entries)
    for e in ext.theory_entries:
        all_recs.append({"dept": dept, "kind":"theory","course":str(e.course_code),"group":str(e.group_id),
                         "day":str(getattr(e,"day","")).lower(),"slot":e.slot_index,"session":None,
                         "room":str(e.room_number or e.room_id),"teacher":str(e.teacher_name or ""),"is_comb":False})
    for e in ext.lab_entries:
        all_recs.append({"dept": dept, "kind":"lab","course":str(e.course_code),"group":str(e.group_id),
                         "day":str(getattr(e,"day","")).lower(),"slot":None,"session":e.session_name,
                         "room":str(e.room_number or e.room_id),"teacher":str(e.teacher_name or ""),
                         "is_comb":str(e.course_code) in COMB,
                         "batch":str(getattr(e,"batch_label",None) or getattr(e,"batch_info",None) or "")})
    print(f"  {dept[:38]:38s} -> {st}", flush=True)

SUF = "_parallel" if PARALLEL else ""
outp = OUTDIR / f"seeded_schedule{SUF}.json"
outp.write_text(json.dumps(all_recs), encoding="utf-8")
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
    ("capacity_info","capacity_info"),("partner_instance_id","partner_instance_id"),("group_name","group_name"),
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
