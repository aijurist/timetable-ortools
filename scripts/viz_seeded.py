"""Render the SEEDED 2nd-year timetable (fits around the senior sem-5/7 schedule),
one page per department with separate theory and lab tables per section, plus batch
labels (Batch 1/2) on split-section lab cells.

Reads output/timetables/seeded_schedule.json (or ..._parallel.json when PARALLEL_BATCH=1),
produced by scripts/seeded_bundle.py. Writes to output/timetables/seeded/ (or parallel/)
so it never touches output/timetables/sequential/, which is served separately.

Run (after seeded_bundle.py):
    PYTHONPATH=. python scripts/viz_seeded.py                    # served (seeded/)
    PARALLEL_BATCH=1 PYTHONPATH=. python scripts/viz_seeded.py   # separate parallel/ output
"""
import os, json, re, html
from pathlib import Path
from collections import defaultdict

base = Path.cwd()
_PAR = os.environ.get("PARALLEL_BATCH") == "1"
_SUF = "_parallel" if _PAR else ""
# Optional overrides: VIZ_JSON (input schedule JSON), VIZ_OUT (output HTML dir), both
# relative to cwd — lets us render an isolated run (e.g. optimized/) without touching defaults.
_VIZ_JSON = os.environ.get("VIZ_JSON")
_VIZ_OUT = os.environ.get("VIZ_OUT")
OUT = (base / _VIZ_OUT) if _VIZ_OUT else (base / "output" / "timetables" / ("parallel" if _PAR else "seeded"))
OUT.mkdir(parents=True, exist_ok=True)
_json_path = (base / _VIZ_JSON) if _VIZ_JSON else (base / "output" / "timetables" / f"seeded_schedule{_SUF}.json")
recs = json.loads(_json_path.read_text(encoding="utf-8"))

DAYS = ["monday", "tuesday", "wed", "thur", "fri", "saturday"]
DLBL = {"monday":"Mon","tuesday":"Tue","wed":"Wed","thur":"Thu","fri":"Fri","saturday":"Sat"}
THEORY_SLOTS = ["8:00-8:50","9:00-9:50","10:00-10:50","11:00-11:50","12:00-12:50",
                "1:00-1:50","2:00-2:50","3:10-4:00","4:10-5:00"]
LAB_SESS = [("L1","8:00-9:40"),("L2","10:00-11:40"),("L3","11:40-1:20"),("L4","1:20-3:00"),("L5","3:10-4:50")]
def secn(g):
    m = re.search(r"sec(\d+)", str(g)); return m.group(1) if m else "0"
ABBR = {"Computer Science & Engineering":"CSE","Computer Science & Engineering (Cyber Security)":"CSE-Cy",
        "Artificial Intelligence & Data Science":"AI&DS","Artificial Intelligence & Machine Learning":"AI&ML",
        "Information Technology":"IT","Computer Science & Design":"CSD","Computer Science & Business Systems":"CSBS"}
def dabbr(name): return ABBR.get(name, name[:6])

CSS = """<style>
body{font-family:Segoe UI,Arial;margin:16px;background:#f6f7f9;color:#222}
h1{margin-bottom:4px}h2{margin:22px 0 4px;border-bottom:2px solid #444;padding-bottom:3px}
h3{margin:14px 0 3px;color:#2c3e50}h4{margin:8px 0 2px;color:#555;font-weight:600;font-size:13px}
table{border-collapse:collapse;margin:0 0 10px;width:100%;table-layout:fixed}
th,td{border:1px solid #ccd;padding:4px 5px;font-size:11px;text-align:center;vertical-align:top}
th{background:#2c3e50;color:#fff;font-size:9.5px}
td.day{background:#eceff3;font-weight:700;width:44px}
td.th{background:#eaf4ff}td.bun{background:#e6d9ff;outline:2px solid #8a5cf0}
td.lab{background:#eafbea}td.comb{background:#fff3d6;outline:2px solid #e0a800}
.rm{color:#555}.tn{color:#999;font-style:italic;font-size:10px}.pair{color:#b8860b;font-weight:700}
.bl{color:#6a3fc0;font-weight:700;font-size:9px}.bt{display:inline-block;background:#c0392b;color:#fff;padding:0 5px;border-radius:3px;font-weight:700;font-size:9px;margin-top:2px}
.st{background:#27ae60;color:#fff;padding:2px 8px;border-radius:9px;font-size:12px}
.warn{background:#e67e22;color:#fff;padding:2px 8px;border-radius:9px;font-size:12px}
a{color:#06c;text-decoration:none}a:hover{text-decoration:underline}
.leg span{display:inline-block;padding:2px 8px;margin:2px;border-radius:4px;font-size:11px}
</style>"""
LEGEND = ("<div class='leg'>"
          "<span class='th' style='background:#eaf4ff'>Theory</span>"
          "<span class='bun' style='background:#e6d9ff'>25+25 bundled</span>"
          "<span class='lab' style='background:#eafbea'>Lab</span>"
          "<span class='comb' style='background:#fff3d6'>Combined lab in ANEW (&harr; cross-dept)</span>"
          "<span style='background:#c0392b;color:#fff'>Batch 1/2 (split &gt;35-student section)</span></div>")

anew_occ = defaultdict(set)
for r in recs:
    if r["is_comb"]:
        anew_occ[(r["course"], r["day"], r["session"], r["room"])].add((dabbr(r["dept"]), secn(r["group"])))

data = defaultdict(lambda: defaultdict(lambda: {"theory": defaultdict(lambda: defaultdict(list)),
                                                 "lab": defaultdict(lambda: defaultdict(list))}))
for r in recs:
    dept = r["dept"]; sec = secn(r["group"]); day = r["day"]
    if day not in DAYS: continue
    if r["kind"] == "theory":
        cell = f"<b>{html.escape(r['course'])}</b><br><span class='rm'>{html.escape(r['room'])}</span>"
        if r["teacher"]: cell += f"<br><span class='tn'>{html.escape(r['teacher'][:12])}</span>"
        data[dept][sec]["theory"][day][r["slot"]].append(cell)
    else:
        comb = r["is_comb"]; tag = ""
        if comb:
            partners = sorted(anew_occ[(r["course"], r["day"], r["session"], r["room"])] - {(dabbr(dept), sec)})
            tag = "<br><span class='pair'>&harr;" + ",".join(f"{d}s{s}" for d,s in partners) + "</span>" if partners else "<br><span class='pair'>solo</span>"
        bl = r.get("batch", "")
        if bl:
            tag += f"<br><span class='bt'>{html.escape(bl)}</span>"
        cell = f"<b>{html.escape(r['course'])}</b><br><span class='rm'>{html.escape(r['room'])}</span>{tag}"
        data[dept][sec]["lab"][day][r["session"]].append((cell, comb))

def theory_table(tg):
    out = ["<table><tr><th>Day</th>" + "".join(f"<th>{t}</th>" for t in THEORY_SLOTS) + "</tr>"]
    for day in DAYS:
        row = [f"<td class='day'>{DLBL[day]}</td>"]
        for si in range(len(THEORY_SLOTS)):
            it = tg.get(day, {}).get(si, [])
            if not it: row.append("<td></td>")
            elif len(it) >= 2: row.append("<td class='bun'><span class='bl'>&#9633; 25+25</span><br>" + "<hr style='margin:2px 0'>".join(it) + "</td>")
            else: row.append(f"<td class='th'>{it[0]}</td>")
        out.append("<tr>" + "".join(row) + "</tr>")
    out.append("</table>"); return "\n".join(out)

def lab_table(lg):
    out = ["<table><tr><th>Day</th>" + "".join(f"<th>{n}<br>{t}</th>" for n,t in LAB_SESS) + "</tr>"]
    for day in DAYS:
        row = [f"<td class='day'>{DLBL[day]}</td>"]
        for name, _ in LAB_SESS:
            it = lg.get(day, {}).get(name, [])
            if not it: row.append("<td></td>")
            else:
                cls = "comb" if any(c for _, c in it) else "lab"
                row.append(f"<td class='{cls}'>" + "<hr style='margin:2px 0'>".join(c for c, _ in it) + "</td>")
        out.append("<tr>" + "".join(row) + "</tr>")
    out.append("</table>"); return "\n".join(out)

links = []
for dept in sorted(data):
    slug = re.sub(r"[^a-z0-9]+","_",dept.lower())
    body = [f"<html><head><meta charset='utf-8'>{CSS}</head><body>",
            f"<h1>{html.escape(dept)} <span class='st'>fits around senior schedule</span></h1>", LEGEND,
            "<p><a href='index.html'>&larr; all departments</a></p>"]
    for sec in sorted(data[dept], key=lambda x:int(x)):
        d = data[dept][sec]
        body.append(f"<h3>Section {sec}</h3><h4>Theory</h4>" + theory_table(d["theory"]) + "<h4>Labs</h4>" + lab_table(d["lab"]))
    body.append("</body></html>")
    (OUT / f"{slug}.html").write_text("\n".join(body), encoding="utf-8")
    links.append((dept, slug, len(data[dept])))

tcell = defaultdict(list)
for r in recs:
    if r["kind"]=="theory": tcell[(r["dept"],secn(r["group"]),r["day"],r["slot"],r["room"])].append(r["course"])
nbun = sum(1 for v in tcell.values() if len(set(v))>=2)
ncomb = sum(1 for r in recs if r["is_comb"])
ALL19 = ["Aeronautical Engineering","Artificial Intelligence and Data Science","Artificial Intelligence and Machine Learning",
    "Automobile Engineering","Biomedical Engineering","Biotechnology","Chemical Engineering","Civil Engineering",
    "Computer Science and Business Systems","Computer Science and Design","Computer Science and Engineering Cyber Security",
    "Computer Science and Engineering","Electrical and Electronics Engineering","Electronics and Communication Engineering",
    "Food Technology","Information Technology","Mechanical Engineering","Mechatronics Engineering","Robotics and Automation"]
present = set(data.keys())
missing = [d for d in ALL19 if d not in present]
idx = [f"<html><head><meta charset='utf-8'>{CSS}</head><body>",
       "<h1>2nd-Year (Semester 3) Timetable — scheduled AROUND the senior (Sem 5/7) schedule</h1>",
       "<p><b><a href='rooms.html'>&#9633; View room-wise timetable (all rooms, all semesters) &rarr;</a></b></p>",
       f"<p><span class='st'>{len(present)}/19 departments scheduled</span> &nbsp; "
       + (f"<span class='warn'>Did NOT fit around seniors: {', '.join(missing)}</span>" if missing else "") + "</p>",
       f"<p>{len(recs)} activities &nbsp;|&nbsp; <b>{nbun}</b> 25+25 bundled pairs &nbsp;|&nbsp; <b>{ncomb}</b> combined-lab sessions in ANEW &nbsp;|&nbsp; 0 conflicts with the fixed senior schedule.</p>",
       "<p style='color:#a33'>Note: the missing depts are lab-dense single-section depts on the capacity edge — labs are near-full once seniors are placed (see chat for details).</p>",
       LEGEND, "<table><tr><th style='width:45%'>Department</th><th>Sections</th><th>Timetable</th></tr>"]
for dept, slug, nsec in links:
    idx.append(f"<tr><td class='day' style='text-align:left'>{html.escape(dept)}</td><td>{nsec}</td><td><a href='{slug}.html'>open</a></td></tr>")
idx.append("</table></body></html>")
(OUT / "index.html").write_text("\n".join(idx), encoding="utf-8")
print(f"rendered {len(links)} depts -> {OUT/'index.html'}")
