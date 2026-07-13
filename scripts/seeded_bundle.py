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
ANEW_NUMS = {"ANEW101","ANEW102","ANEW103","ANEW104","A104/105","KSL02"}
L2T = {"L1": (0,1), "L2": (2,3), "L3": (4,5), "L4": (5,6), "L5": (7,8)}
ORDER = [
    # combined-lab (ANEW) CS-family depts FIRST, smallest->largest: the small ones claim
    # their few shared ANEW cells before the flexible big depts fill the remainder.
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

import os
PARALLEL = os.environ.get("PARALLEL_BATCH") == "1"

def build(dept, rseed=1, parallel=None):
    if parallel is None:
        parallel = PARALLEL
    cross = {"bundled_theory": {"enabled": True, "priority": 2, "weight": 1.0,
              "params": {"eligible_cohorts": ["*_S3"], "force_maximal_pairing": False,
                         "solo_penalty_weight": 50, "enforce_shared_room": True,
                         # per-slot partial pairing: unequal-hour courses bundle their
                         # overlapping hours, the longer course's extra hour(s) go solo.
                         "allow_partial_pairing": True}}}
    lab = {}
    if parallel:
        # gate the parallel-batch feature ON (separate output; default runs unaffected).
        # Scope = dept-private core-labs only (exclude shared-pool computer-lab courses).
        PBC = ["EC23321", "IT23331", "BM23322", "AE23331"]
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
    # seed seniors
    for k, v in load_seniors_lab.items(): labbusy[k] += v
    thbusy |= sen_theory_room
    for t, s in sen_teacher.items(): tbusy[t] |= s
    lab_values = {}; per_lab_occ = {}; per_lab_teacher = {}; per_th_room = {}; per_th_teacher = {}
    dept_parallel = {}
    infeasible = []
    for dept in ORDER:
        def attempt(parallel):
            cm, data = build(dept, parallel=parallel)
            model = cm.model; tb = cm.variables.theory; lb = cm.variables.lab
            # reserve labs + theory + teachers
            anew_cell = defaultdict(list)
            for tid, cmap in lb.assignments.items():
                for inst, dmap in cmap.items():
                    pat = lb.day_patterns.get(inst, ())
                    for di, smap in dmap.items():
                        aday = pat[di] if 0 <= di < len(pat) else None
                        if aday is None: continue
                        for sess, rmap in smap.items():
                            tconf = any((aday, s) in tbusy.get(str(tid), set()) for s in L2T.get(sess, ()))
                            for rid, var in rmap.items():
                                rn = rid2num.get(str(rid), str(rid))
                                if tconf: model.Add(var == 0); continue
                                if rn in big_nums or rn in ANEW_NUMS: anew_cell[(rn, aday, sess)].append(var)
                                elif labbusy.get((rn, aday, sess), 0) >= 1: model.Add(var == 0)
            for (rn, aday, sess), vs in anew_cell.items():
                # block combined-lab cell entirely if seniors (or already-placed depts)
                # hold THEORY in that room during any slot the lab session spans
                theory_block = any((rn, aday, s) in thbusy for s in L2T.get(sess, ()))
                cap = 0 if theory_block else max(0, 2 - labbusy.get((rn, aday, sess), 0))
                model.Add(sum(vs) <= cap)
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
            s.parameters.num_search_workers = 8; s.parameters.stop_after_first_solution = True; s.parameters.random_seed = rseed
            st = s.StatusName(s.Solve(model))
            return st, cm, data, model, tb, lb, s
        used_parallel = PARALLEL
        st, cm, data, model, tb, lb, s = attempt(PARALLEL)
        if st not in ("OPTIMAL", "FEASIBLE") and PARALLEL:
            # per-department fallback: this dept could not be fully parallelised
            # around the seniors, so schedule it sequentially instead.
            used_parallel = False
            st, cm, data, model, tb, lb, s = attempt(False)
        if os.environ.get("DEBUG_DEPT") == "1":
            print(f"    {dept[:34]:34s} -> {st}", flush=True)
        if st not in ("OPTIMAL", "FEASIBLE"):
            infeasible.append(dept); continue
        dept_parallel[dept] = used_parallel
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
            for sc in L2T.get(e.session_name, ()): tbusy[str(e.teacher_id)].add((day, sc)); lteach[str(e.teacher_id)].add((day, sc))
        for e in ext.theory_entries:
            rn = str(e.room_number or e.room_id); day = str(getattr(e, "day", "")).lower()
            thbusy.add((rn, day, e.slot_index)); throom.add((rn, day, e.slot_index))
            if e.teacher_id: tbusy[str(e.teacher_id)].add((day, e.slot_index)); tteach[str(e.teacher_id)].add((day, e.slot_index))
        per_lab_occ[dept] = locc; per_lab_teacher[dept] = lteach; per_th_room[dept] = throom; per_th_teacher[dept] = tteach
    return infeasible, lab_values, per_lab_occ, per_lab_teacher, per_th_room, per_th_teacher, dept_parallel

print("PHASE 1: first-solution multi-seed to fit all 18 around seniors...", flush=True)
best = None
for rseed in range(1, 13):
    t0 = time.time(); res1 = phase1(rseed); infeas = res1[0]
    print(f"  [seed {rseed}] {len(ORDER)-len(infeas)}/{len(ORDER)} fit ({time.time()-t0:.0f}s)" + ("" if infeas else " ALL FIT"), flush=True)
    if best is None or len(infeas) < len(best[0][0]): best = (res1, rseed)
    if not infeas: break
res1, used_seed = best
infeasible, lab_values, per_lab_occ, per_lab_teacher, per_th_room, per_th_teacher, dept_parallel = res1
print(f"PHASE 1 done (seed {used_seed}): {len(ORDER)-len(infeasible)}/{len(ORDER)} fit" + (f", dropped {infeasible}" if infeasible else "") + "\n", flush=True)
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
    cm, data = build(dept, parallel=dept_parallel.get(dept, PARALLEL))
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
    s = cp_model.CpSolver(); s.parameters.max_time_in_seconds = 150; s.parameters.num_search_workers = 8
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
                         "is_comb":str(e.course_code) in COMB})
    print(f"  {dept[:38]:38s} -> {st}", flush=True)

SUF = "_parallel" if PARALLEL else ""
outp = base / "output" / "timetables" / f"seeded_schedule{SUF}.json"
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
tp = base / "data" / f"theory_schedule_second_year{SUF}.csv"
lp = base / "data" / f"lab_schedule_second_year{SUF}.csv"
write_csv(tp, TH_COLS, full_theory); write_csv(lp, LAB_COLS, full_lab)
print(f"theory CSV: {len(full_theory)} rows -> {tp}")
print(f"lab CSV:    {len(full_lab)} rows -> {lp}")
