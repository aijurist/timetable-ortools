"""Room-centric visualization: for each room, its full weekly usage across ALL
semesters (2nd-year sem-3 from seeded_schedule.json + seniors sem-5/7 from the
uploaded CSVs), grouped by block. Useful for spotting room clashes at a glance.

Reads output/timetables/seeded_schedule.json (or ..._parallel.json when PARALLEL_BATCH=1).
Writes rooms.html into output/timetables/seeded/ (or parallel/).

Run (after seeded_bundle.py):
    PYTHONPATH=. python scripts/viz_rooms.py                     # served (seeded/)
    PARALLEL_BATCH=1 PYTHONPATH=. python scripts/viz_rooms.py    # separate parallel/ output
"""
import json, re, html
from pathlib import Path
from collections import defaultdict
import pandas as pd

import os
base = Path.cwd()
_PAR = os.environ.get("PARALLEL_BATCH") == "1"
OUT = base / "output" / "timetables" / ("parallel" if _PAR else "seeded")
OUT.mkdir(parents=True, exist_ok=True)

DAYS = ["monday", "tuesday", "wed", "thur", "fri", "saturday"]
DLBL = {"monday":"Mon","tuesday":"Tue","wed":"Wed","thur":"Thu","fri":"Fri","saturday":"Sat"}
THSLOTS = ["8:00","9:00","10:00","11:00","12:00","1:00","2:00","3:10","4:10"]
LABSESS = ["L1","L2","L3","L4","L5"]
ABBR = {"Computer Science & Engineering":"CSE","Computer Science & Engineering (Cyber Security)":"CSE-Cy",
        "Artificial Intelligence & Data Science":"AI&DS","Artificial Intelligence & Machine Learning":"AI&ML",
        "Information Technology":"IT","Computer Science & Design":"CSD","Computer Science & Business Systems":"CSBS",
        "Electronics & Communication Engineering":"ECE","Biomedical Engineering":"BME","Biotechnology":"BT",
        "Mechatronics Engineering":"MCT","Mechanical Engineering":"MECH","Food Technology":"FT",
        "Electrical & Electronics Engineering":"EEE","Chemical Engineering":"CHEM","Robotics and Automation":"ROBO",
        "Robotics & Automation":"ROBO","Civil Engineering":"CIVIL","Automobile Engineering":"AUTO","Aeronautical Engineering":"AERO"}
def dab(d):
    d = d.replace(" and ", " & ")
    return ABBR.get(d, (d[:5]))
def daynorm(d):
    d = str(d).strip().lower()
    return {"mon":"monday","tue":"tuesday","tues":"tuesday","wednesday":"wed","thursday":"thur","thu":"thur","friday":"fri","sat":"saturday"}.get(d, d)

# room -> {'theory': {day:{slot:[..]}}, 'lab': {day:{sess:[..]}}}, block lookup
rooms_df = pd.read_csv("data/block_wise/new.csv", keep_default_na=False)
num2block = {r["room_number"]: r["block"] for _, r in rooms_df.iterrows()}
th = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))
lab = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))

def add_theory(room, day, slot, dept, course, sem, sem3):
    day = daynorm(day)
    if day in DAYS and 0 <= slot < 9:
        th[room][day][slot].append((dept, course, sem, sem3))
def add_lab(room, day, sess, dept, course, sem, sem3):
    day = daynorm(day)
    if day in DAYS and sess in LABSESS:
        lab[room][day][sess].append((dept, course, sem, sem3))

# 2nd-year (sem 3)
recs = json.loads((base / "output" / "timetables" / f"seeded_schedule{'_parallel' if _PAR else ''}.json").read_text(encoding="utf-8"))
for r in recs:
    if r["kind"] == "theory": add_theory(r["room"], r["day"], r["slot"], dab(r["dept"]), r["course"], 3, True)
    else: add_lab(r["room"], r["day"], r["session"], dab(r["dept"]), r["course"] + (f" [{r['batch']}]" if r.get("batch") else ""), 3, True)
# seniors (sem 5/7)
st = pd.read_csv("data/theory_schedule_combined_only_latest_uploads.csv", keep_default_na=False)
sl = pd.read_csv("data/lab_schedule_combined_only_latest_uploads.csv", keep_default_na=False)
for _, r in st.iterrows():
    try: slot = int(r["slot_index"])
    except (TypeError, ValueError): continue
    add_theory(str(r["room_number"]), r["day"], slot, dab(str(r["department"])), str(r["course_code"]), int(r["semester"]), False)
for _, r in sl.iterrows():
    add_lab(str(r["room_number"]), r["day"], str(r["session_name"]), dab(str(r["department"])), str(r["course_code"]), int(r["semester"]), False)

CSS = """<style>
body{font-family:Segoe UI,Arial;margin:14px;background:#f6f7f9;color:#222}
h1{margin-bottom:4px}h2{margin:20px 0 3px;color:#2c3e50}h3{margin:12px 0 2px;font-size:14px}
table{border-collapse:collapse;margin:0 0 8px;width:100%;table-layout:fixed}
th,td{border:1px solid #ccd;padding:3px 4px;font-size:10px;text-align:center;vertical-align:top}
th{background:#2c3e50;color:#fff;font-size:9px}td.day{background:#eceff3;font-weight:700;width:40px}
td.s3{background:#eafbea}td.sen{background:#eef2f7;color:#556}
.d{font-weight:700}.c{color:#555}.sm{font-size:8px;color:#888}
.leg span{display:inline-block;padding:2px 8px;margin:2px;border-radius:4px;font-size:11px}
a{color:#06c;text-decoration:none}
</style>"""
LEG = ("<div class='leg'>Room usage across all years: "
       "<span class='s3' style='background:#eafbea'>Sem-3 (2nd year)</span>"
       "<span class='sen' style='background:#eef2f7'>Seniors (Sem 5/7)</span> "
       "&nbsp; cell shows DEPT &bull; course &bull; sem</div>")

def cell_html(items):
    out = []
    for dept, course, sem, s3 in items:
        out.append(f"<span class='d'>{html.escape(dept)}</span> <span class='c'>{html.escape(course)}</span> <span class='sm'>s{sem}</span>")
    return "<br>".join(out)

def theory_grid(room):
    g = th[room]
    o = ["<table><tr><th>Day</th>" + "".join(f"<th>{t}</th>" for t in THSLOTS) + "</tr>"]
    for day in DAYS:
        row = [f"<td class='day'>{DLBL[day]}</td>"]
        for si in range(9):
            it = g.get(day, {}).get(si, [])
            if not it: row.append("<td></td>")
            else:
                cls = "s3" if any(x[3] for x in it) else "sen"
                row.append(f"<td class='{cls}'>" + cell_html(it) + "</td>")
        o.append("<tr>" + "".join(row) + "</tr>")
    o.append("</table>"); return "\n".join(o)

def lab_grid(room):
    g = lab[room]
    o = ["<table><tr><th>Day</th>" + "".join(f"<th>{s}</th>" for s in LABSESS) + "</tr>"]
    for day in DAYS:
        row = [f"<td class='day'>{DLBL[day]}</td>"]
        for s in LABSESS:
            it = g.get(day, {}).get(s, [])
            if not it: row.append("<td></td>")
            else:
                cls = "s3" if any(x[3] for x in it) else "sen"
                row.append(f"<td class='{cls}'>" + cell_html(it) + "</td>")
        o.append("<tr>" + "".join(row) + "</tr>")
    o.append("</table>"); return "\n".join(o)

used_rooms = sorted(set(th.keys()) | set(lab.keys()))
byblock = defaultdict(list)
for rm in used_rooms: byblock[num2block.get(rm, "Other")].append(rm)

body = [f"<html><head><meta charset='utf-8'>{CSS}</head><body>",
        "<h1>Room-wise Timetable — all rooms, all semesters</h1>",
        f"<p><a href='index.html'>&larr; department view</a> &nbsp;|&nbsp; {len(used_rooms)} rooms in use</p>", LEG]
for block in sorted(byblock):
    body.append(f"<h2>{html.escape(str(block))}</h2>")
    for rm in byblock[block]:
        has_th = rm in th; has_lab = rm in lab
        body.append(f"<h3>Room {html.escape(rm)}</h3>")
        if has_th: body.append(theory_grid(rm))
        if has_lab: body.append(lab_grid(rm))
body.append("</body></html>")
(OUT / "rooms.html").write_text("\n".join(body), encoding="utf-8")
print(f"room-wise view: {len(used_rooms)} rooms -> {OUT/'rooms.html'}")
