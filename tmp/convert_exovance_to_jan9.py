#!/usr/bin/env python
"""Convert the new exovance live export to the jan9.sqlite (Django) schema.

Reads:  exovance_timetable_live_20260611T045424Z.sqlite  (new SQLAlchemy schema)
        jan9.sqlite                                       (reference old schema + id/value crosswalks)
Writes: exovance_converted_jan9_20260611.sqlite          (old schema, populated from new data)

Mapping decisions (all data-verified, see conversion_report.md):
  departments            -> department_department
  users                  -> authentication_user
  faculty                -> teacher_teacher           (+1 placeholder per teaching dept for unassigned TAs)
  rooms                  -> rooms_room
  courses                -> courseMaster_coursemaster (structure JSON {"L","T","P"} -> hour columns)
  courses room prefs     -> courseMaster_coursemasterroompreference (1 row max per course)
  teaching_assignments   -> course_course (derived layer) + teacherCourse_teachercourse (1 row/section)
  student_profiles       -> student_student
  time_grids.slots JSON  -> timetableMaster_session

teaching_assignments dept semantics (verified against faculty home departments):
  department_id           = student dept  (course_course.for_dept_id_id)
  requested_dept_id       = teaching dept when service-taught, else = department_id
  courses.department_id   = owner dept    (courseMaster.course_dept_id_id)
"""
import sqlite3, json, re, sys
from collections import Counter, defaultdict

BASE = 'D:/data_works_timetable/'
NEW = BASE + 'exovance-2026-06-16-v1.sqlite'
OLD = BASE + 'jan9.sqlite'
OUT = BASE + 'exovance_converted_jan9_20260612.sqlite'

n = sqlite3.connect(NEW); n.row_factory = sqlite3.Row
o = sqlite3.connect(OLD); o.row_factory = sqlite3.Row
import os
if os.path.exists(OUT):
    os.remove(OUT)
w = sqlite3.connect(OUT)

log = []
def note(msg):
    print(msg)
    log.append(msg)

# ---------------------------------------------------------------- 1. DDL clone
ddl = o.execute("""SELECT name, sql FROM sqlite_master
                   WHERE type='table' AND sql IS NOT NULL AND name NOT LIKE 'sqlite_%'""").fetchall()
for r in ddl:
    w.execute(r['sql'])
note(f'DDL: created {len(ddl)} tables from jan9 schema')
w.execute("""CREATE TABLE _conversion_id_map (
    entity TEXT, new_uuid TEXT, old_id TEXT, reused_jan9_id INTEGER, source TEXT)""")

idmap_rows = []
def remember(entity, uuid, old_id, reused, source):
    idmap_rows.append((entity, uuid, str(old_id), 1 if reused else 0, source))

def fix_ts(ts):
    """'2026-05-25 09:30:24.49384+00' -> '2026-05-25T09:30:24.493840+00:00' (old Django style)."""
    if not ts:
        return ts
    ts = ts.replace(' ', 'T')
    m = re.match(r'^(.*?)([+-]\d{2})(:?\d{2})?$', ts)
    if m and m.group(3) is None:
        ts = m.group(1) + m.group(2) + ':00'
    return ts

# ---------------------------------------------------------------- 2. crosswalks from jan9
old_dept_by_name = {r['dept_name']: r['id'] for r in o.execute('SELECT id, dept_name FROM department_department')}
old_course_by_code = {}   # code -> (id, degree_type, regulation, course_type)
for r in o.execute('SELECT id, course_id, degree_type, regulation FROM courseMaster_coursemaster ORDER BY id'):
    old_course_by_code[r['course_id']] = (r['id'], r['degree_type'], r['regulation'])
old_teacher_by_email = {}  # email -> (id, staff_code, teacher_role)
for r in o.execute('''SELECT tt.id, tt.staff_code, tt.teacher_role, au.email
                      FROM teacher_teacher tt JOIN authentication_user au ON tt.teacher_id_id=au.uuid'''):
    old_teacher_by_email[r['email']] = (r['id'], r['staff_code'], r['teacher_role'])
old_room_by_code = {r['room_number']: r['id'] for r in o.execute('SELECT id, room_number FROM rooms_room')}
old_student_by_roll = {r['roll_no']: r['id'] for r in o.execute('SELECT id, roll_no FROM student_student')}
old_cc_key = {}  # (code, for_dept_name, teach_dept_name, year, sem) -> cc id
for r in o.execute('''SELECT cc.id, cm.course_id AS code, d1.dept_name fd, d2.dept_name td,
                             cc.course_year y, cc.course_semester s
                      FROM course_course cc
                      JOIN courseMaster_coursemaster cm ON cc.course_id_id=cm.id
                      JOIN department_department d1 ON cc.for_dept_id_id=d1.id
                      JOIN department_department d2 ON cc.teaching_dept_id_id=d2.id'''):
    old_cc_key[(r['code'], r['fd'], r['td'], r['y'], r['s'])] = r['id']

old_student_types = [r[0] for r in o.execute('SELECT DISTINCT student_type FROM student_student')]
old_student_degrees = [r[0] for r in o.execute('SELECT DISTINCT degree_type FROM student_student')]
note(f'jan9 student_type values: {old_student_types}; degree_type values: {old_student_degrees}')

class IdAlloc:
    """Reuse jan9 id on natural-key match; new entities get ids above jan9 max + 1000."""
    def __init__(self, existing_ids):
        self.used = set(existing_ids)
        self.next = (max(existing_ids) if existing_ids else 0) + 1000
    def take(self, reuse_id=None):
        if reuse_id is not None and reuse_id not in self.used:
            self.used.add(reuse_id)
            return reuse_id, True
        while self.next in self.used:
            self.next += 1
        self.used.add(self.next)
        self.next += 1
        return self.next - 1, False

# ---------------------------------------------------------------- 3. departments
dept_id = {}      # new uuid -> int id
dept_name = {}    # new uuid -> name
alloc = IdAlloc(set())
reused = 0
for r in n.execute('SELECT * FROM departments'):
    rid, was = alloc.take(old_dept_by_name.get(r['name']))
    reused += was
    dept_id[r['id']] = rid
    dept_name[r['id']] = r['name']
    w.execute('INSERT INTO department_department (id, dept_name, date_established, contact_info, hod_id_id) VALUES (?,?,?,?,?)',
              (rid, r['name'], None, r['description'] or '', None))
    remember('department', r['id'], rid, was, 'name match' if was else 'new')
    if not was:
        note(f'  dept with no jan9 name match: {r["name"]!r}')
note(f'departments: {len(dept_id)} converted, {reused} reuse jan9 ids')

# ---------------------------------------------------------------- 4. users -> authentication_user
ROLE2TYPE = {'student': 'student', 'teacher': 'teacher', 'hod': 'teacher',
             'admin': 'admin', 'super_admin': 'admin'}
GENDER = {'MALE': 'M', 'FEMALE': 'F'}
user_role = {}
user_dept = {}
users_n = 0
for r in n.execute('SELECT * FROM users'):
    full = (r['full_name'] or '').strip()
    if ' ' in full:
        first, last = full.rsplit(' ', 1)
    else:
        first, last = full, ''
    user_role[r['id']] = r['role']
    user_dept[r['id']] = r['department_id']
    w.execute('''INSERT INTO authentication_user
        (password, last_login, is_superuser, is_staff, is_active, date_joined,
         uuid, email, first_name, last_name, phone_number, gender, user_type)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)''',
        (r['hashed_password'], fix_ts(r['last_login_at']),
         1 if r['role'] == 'super_admin' else 0,
         1 if r['role'] in ('admin', 'super_admin') else 0,
         r['is_active'], fix_ts(r['created_at']),
         r['id'], r['email'], first, last, r['phone'], GENDER.get(r['gender']), ROLE2TYPE.get(r['role'], r['role'])))
    users_n += 1
note(f'users: {users_n} converted (uuid = new users.id; full_name split on last space)')

# ---------------------------------------------------------------- 5. faculty -> teacher_teacher
DESIG = {'ASSISTANT_PROFESSOR': 'Assistant Professor', 'ASSOCIATE_PROFESSOR': 'Associate Professor',
         'PROFESSOR': 'Professor', 'PROFESSOR_OF_PRACTICE': 'Professor of Practice',
         'DEAN_OF_ACADEMICS': 'Dean of Academics', 'DIRECTOR': 'Director',
         'PRINCIPAL': 'Principal', 'TEACHING_ASSISTANT': 'Teaching Assistant'}
emails = {r['id']: r['email'] for r in n.execute('SELECT id, email FROM users')}

# Department-declared vacancy positions present in the exovance data (names like
# 'New Faculty 3', emails like placeholder3@... / nf1@...): added by the departments
# themselves for yet-to-be-recruited staff and carrying real teaching assignments.
# jan9 modeled the same thing as is_placeholder=1 teachers whose staff_code held the
# label (e.g. 'NEWSTAFF-1') -> convert them the same way.
PLACEHOLDER_NAME = re.compile(r'(?i)^(new|test)\b|new\s*faculty|new\s*staff')
PLACEHOLDER_EMAIL = re.compile(r'(?i)^(nf\d|ns\d|placeholder|newfaculty|newcsecs|itnew|new@|test)')
def is_new_recruit_placeholder(name, email):
    return bool(PLACEHOLDER_NAME.search(name or '') or PLACEHOLDER_EMAIL.search(email or ''))

teacher_id = {}   # faculty uuid -> int id
t_alloc = IdAlloc(set())
reused = sc_emp = sc_old = recruit_ph = 0
for r in n.execute('SELECT * FROM faculty'):
    email = emails.get(r['user_id'])
    old = old_teacher_by_email.get(email)
    rid, was = t_alloc.take(old[0] if old else None)
    reused += was
    teacher_id[r['id']] = rid
    # staff_code priority: new staff_code -> employee_id -> jan9 crosswalk
    staff = (r['staff_code'] or '').strip() or (r['employee_id'] or '').strip() or None
    if staff:
        sc_emp += 1
    elif old and old[1]:
        staff = old[1]; sc_old += 1
    # role: hod flag wins -> mapped designation -> jan9 crosswalk role
    role = 'HOD' if user_role.get(r['user_id']) == 'hod' else (
        DESIG.get(r['designation']) or (old[2] if old else None))
    recruit = is_new_recruit_placeholder(r['name'], email)
    recruit_ph += recruit
    if recruit and not staff:
        staff = r['name']  # jan9 placeholder convention: staff_code carries the label
    w.execute('''INSERT INTO teacher_teacher
        (id, staff_code, teacher_role, teacher_specialisation, teacher_working_hours,
         availability_type, is_industry_professional, resignation_status, resignation_date,
         is_placeholder, placeholder_description, is_special_slot, dept_id_id, teacher_id_id)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
        (rid, staff, role, None, r['max_weekly_hours'], 'regular',
         1 if r['employment_type'] == 'ADJUNCT' else 0,
         'active' if r['is_active'] else 'resigned', None,
         1 if recruit else 0,
         f'Department-declared vacancy (yet-to-be-recruited faculty added by dept in exovance: {r["name"]!r})' if recruit else '',
         0, dept_id.get(user_dept.get(r['user_id'])), r['user_id']))
    remember('teacher', r['id'], rid, was, 'email match' if was else 'new')
note(f'faculty: {len(teacher_id)} converted, {reused} reuse jan9 ids; staff_code from new data: {sc_emp}, from jan9 crosswalk: {sc_old}; '
     f'{recruit_ph} dept-declared vacancy faculty flagged is_placeholder=1 (staff_code = label)')

# ---------------------------------------------------------------- 6. rooms -> rooms_room
TECH = {'HIGH_TECH': 'High-tech', 'ADVANCED': 'Advanced', 'BASIC': 'Basic'}
room_id = {}
r_alloc = IdAlloc(set())
reused = 0
for r in n.execute('SELECT * FROM rooms'):
    try:
        tags = json.loads(r['tags']) if r['tags'] else []
    except Exception:
        tags = []
    if not isinstance(tags, list):
        tags = []
    if r['room_type'] == 'LAB':
        rt = 'Computer-Lab' if 'COMPUTER_LAB' in tags else ('Core-Lab' if 'CORE_LAB' in tags else 'Core-Lab')
        is_lab = 1
    else:
        rt = 'Class-Room'; is_lab = 0
    tech = next((TECH[t] for t in tags if t in TECH), 'None')
    rid, was = r_alloc.take(old_room_by_code.get(r['code']))
    reused += was
    room_id[r['id']] = rid
    w.execute('''INSERT INTO rooms_room
        (id, room_number, block, description, is_lab, room_type, room_min_cap, room_max_cap,
         tech_level, has_projector, has_ac, smart_board, green_board, isLcsAvailable, maintained_by_id_id)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
        (rid, r['code'], r['building'] or '', r['name'] or '', is_lab, rt,
         r['capacity'], r['capacity'], tech,
         1 if 'PROJECTOR' in tags else 0, 1 if 'AC' in tags else 0, 0, 0, 0, None))
    remember('room', r['id'], rid, was, 'code match' if was else 'new')
note(f'rooms: {len(room_id)} converted, {reused} reuse jan9 ids (capacity -> min_cap=max_cap)')

# ---------------------------------------------------------------- 7. courses -> courseMaster_coursemaster
course_id = {}        # new course uuid -> coursemaster int id
course_struct = {}    # new course uuid -> (L,T,P)
c_alloc = IdAlloc(set())
reused = bad_struct = 0
for r in n.execute('SELECT * FROM courses'):
    L = T = P = None
    try:
        s = json.loads(r['structure']) if r['structure'] else None
        if isinstance(s, dict):
            L, T, P = int(s.get('L', 0)), int(s.get('T', 0)), int(s.get('P', 0))
    except Exception:
        pass
    if L is None:  # fallback from session_type + weekly_hours
        bad_struct += 1
        wh = r['weekly_hours'] or 0
        if r['session_type'] == 'LAB':
            L, T, P = 0, 0, wh
        else:
            L, T, P = wh, 0, 0
    # course_type from actual hours (keeps it consistent with hour columns), session_type as tiebreak
    if P > 0 and (L + T) > 0:
        ctype = 'LoT'
    elif P > 0:
        ctype = 'L'
    elif L + T > 0:
        ctype = 'T'
    else:
        ctype = {'THEORY': 'T', 'BOTH': 'LoT', 'LAB': 'L'}.get(r['session_type'], 'T')
    old = old_course_by_code.get(r['code'])
    degree = old[1] if old else 'BE'   # new schema has no degree_type; jan9 crosswalk, default BE (UG college, students are B.E/B.Tech)
    reg = old[2] if old and old[2] else None
    if not reg:
        m = re.search(r'(\d{2})', r['code'] or '')
        if m and 15 <= int(m.group(1)) <= 30:
            reg = '20' + m.group(1)
    rid, was = c_alloc.take(old[0] if old else None)
    reused += was
    course_id[r['id']] = rid
    course_struct[r['id']] = (L, T, P)
    w.execute('''INSERT INTO courseMaster_coursemaster
        (id, course_id, course_name, is_zero_credit_course, lecture_hours, practical_hours,
         tutorial_hours, credits, regulation, course_type, degree_type, course_dept_id_id,
         default_additional_lecture_hours)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)''',
        (rid, r['code'], (r['name'] or '').strip(), 1 if not r['credits'] else 0,
         L, P, T, float(r['credits'] or 0), reg, ctype, degree,
         dept_id.get(r['department_id']), 0))
    remember('course', r['id'], rid, was, 'code match' if was else 'new')
note(f'courses: {len(course_id)} converted, {reused} reuse jan9 ids, {bad_struct} rows without valid structure JSON (fell back to session_type)')

# ---------------------------------------------------------------- 8. room preferences -> cmrp
# old data has exactly 1 cmrp row per course -> emit at most 1 row per course so main.py's
# LEFT JOIN does not multiply rows. Priority: lab_preferred_room_ids[0] -> TA override_lab_room_ids
# (most common) -> preferred_room_ids[0] -> tag-only row (room NULL).
ta_overrides = defaultdict(Counter)   # course uuid -> Counter(room uuid)
for r in n.execute("SELECT course_id, override_lab_room_ids FROM teaching_assignments WHERE override_lab_room_ids IS NOT NULL"):
    try:
        for rm in json.loads(r['override_lab_room_ids']) or []:
            ta_overrides[r['course_id']][rm] += 1
    except Exception:
        pass

def jlist(x):
    try:
        v = json.loads(x) if x else None
        return v if isinstance(v, list) else []
    except Exception:
        return []

cmrp_n = cmrp_from_override = cmrp_tag_only = 0
cmrp_id = 1
for r in n.execute('SELECT * FROM courses'):
    lab_rooms = jlist(r['lab_preferred_room_ids'])
    pref_rooms = jlist(r['preferred_room_ids'])
    lab_tags = jlist(r['lab_room_tags'])
    gen_tags = jlist(r['room_tags'])
    L, T, P = course_struct[r['id']]
    chosen = None; src = None
    if lab_rooms:
        chosen, src = lab_rooms[0], 'course.lab_preferred_room_ids'
    elif ta_overrides.get(r['id']) and P > 0:
        chosen, src = ta_overrides[r['id']].most_common(1)[0][0], 'teaching_assignment override'
        cmrp_from_override += 1
    elif pref_rooms:
        chosen, src = pref_rooms[0], 'course.preferred_room_ids'
    elif not (lab_tags or gen_tags):
        continue  # no preference info at all
    rid = room_id.get(chosen) if chosen else None
    if chosen and rid is None:
        continue  # dangling room reference
    if not chosen:
        cmrp_tag_only += 1
    # tech preference: from chosen room's tech tag, else from course tag lists;
    # NULL when unknown so main.py's COALESCE renders 'standard' like old extracts
    if chosen:
        row = n.execute('SELECT tags FROM rooms WHERE id=?', (chosen,)).fetchone()
        tech = next((TECH[t] for t in jlist(row['tags'] if row else None) if t in TECH), None)
    else:
        tech = next((TECH[t] for t in (lab_tags + gen_tags) if t in TECH), None)
    w.execute('''INSERT INTO courseMaster_coursemasterroompreference
        (id, preference_level, preferred_for, tech_level_preference, lab_type, lab_description,
         course_master_id_id, room_id_id) VALUES (?,?,?,?,?,?,?,?)''',
        (cmrp_id, 10, 'TL' if P > 0 else 'NTL', tech, None, src, course_id[r['id']], rid))
    cmrp_id += 1
    cmrp_n += 1
note(f'room preferences: {cmrp_n} cmrp rows (1 max per course; {cmrp_from_override} via TA overrides, {cmrp_tag_only} tag-only with room NULL)')

# ---------------------------------------------------------------- 9. teaching_assignments -> course_course + teachercourse
# cohort sizes for student_count: students per (dept, year_of_study)
cohort = Counter()
for r in n.execute('''SELECT u.department_id d, sp.year_of_study y, COUNT(*) c
                      FROM student_profiles sp JOIN users u ON sp.user_id=u.id GROUP BY 1,2'''):
    cohort[(r['d'], r['y'])] = r['c']
class_size = {r['id']: r['class_size'] for r in n.execute('SELECT id, class_size FROM departments')}
default_size = n.execute('SELECT default_class_size FROM institutions').fetchone()[0] or 70

tas = n.execute('SELECT * FROM teaching_assignments WHERE is_active=1').fetchall()
groups = {}            # (course, for_dept, teach_dept, year, sem) -> [ta...]
dangling = 0
for ta in tas:
    td = ta['requested_dept_id'] or ta['department_id']
    if ta['course_id'] not in course_id or ta['department_id'] not in dept_id or td not in dept_id:
        dangling += 1
        note(f'  skipped TA {ta["id"]}: dangling reference (course={ta["course_id"]}, dept={ta["department_id"]})')
        continue
    key = (ta['course_id'], ta['department_id'], td, ta['study_year'], ta['study_semester'])
    groups.setdefault(key, []).append(ta)
if dangling:
    note(f'teaching_assignments: {dangling} rows skipped due to dangling FK references in the live export')

ELECTIVE = {'PROFESSIONAL': 'PE'}
new_elective = {r['id']: r['elective_type'] for r in n.execute('SELECT id, elective_type FROM courses')}
new_code = {r['id']: r['code'] for r in n.execute('SELECT id, code FROM courses')}

cc_alloc = IdAlloc(set(old_cc_key.values()))
cc_reused = 0
cc_of_group = {}
for key in groups:
    c_uuid, fd, td, yr, sem = key
    nat = (new_code.get(c_uuid), dept_name.get(fd), dept_name.get(td), yr, sem)
    rid, was = cc_alloc.take(old_cc_key.get(nat))
    cc_reused += was
    cc_of_group[key] = rid
    w.execute('''INSERT INTO course_course
        (id, course_year, course_semester, need_assist_teacher, elective_type, lab_type,
         teaching_status, course_id_id, for_dept_id_id, teaching_dept_id_id, additional_lecture_hours)
        VALUES (?,?,?,?,?,?,?,?,?,?,?)''',
        (rid, yr, sem, 0, ELECTIVE.get(new_elective.get(c_uuid), 'NE'), 'NULL', 'active',
         course_id[c_uuid], dept_id[fd], dept_id[td], 0))
note(f'course_course: {len(groups)} derived offerings (distinct course+for_dept+teaching_dept+year+sem), {cc_reused} reuse jan9 ids')

# placeholder teachers for unassigned TAs, one per teaching dept (jan9 also used placeholder teachers)
placeholder_of_dept = {}
def get_placeholder(dept_uuid):
    if dept_uuid not in placeholder_of_dept:
        rid, _ = t_alloc.take()
        code = n.execute('SELECT code FROM departments WHERE id=?', (dept_uuid,)).fetchone()
        w.execute('''INSERT INTO teacher_teacher
            (id, staff_code, teacher_role, teacher_specialisation, teacher_working_hours,
             availability_type, is_industry_professional, resignation_status, resignation_date,
             is_placeholder, placeholder_description, is_special_slot, dept_id_id, teacher_id_id)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
            (rid, f'UNASSIGNED-{code[0] if code else "?"}', None, None, None, 'regular', 0,
             'active', None, 1,
             'Auto-created during exovance->jan9 conversion: teaching_assignments row had no faculty assigned',
             0, dept_id.get(dept_uuid), None))
        placeholder_of_dept[dept_uuid] = rid
    return placeholder_of_dept[dept_uuid]

# professional electives: a student takes one course from the PE pool, so the cohort
# splits across ALL PE sections of that (dept, year, sem), not one course's sections
pe_sections = Counter()
for key, talist in groups.items():
    c_uuid, fd, td, yr, sem = key
    if new_elective.get(c_uuid) == 'PROFESSIONAL':
        pe_sections[(fd, yr, sem)] += sum(ta['section_count'] or 1 for ta in talist)

tc_n = tc_placeholder = 0
tc_id = 1
for key, talist in groups.items():
    c_uuid, fd, td, yr, sem = key
    if new_elective.get(c_uuid) == 'PROFESSIONAL':
        total_sections = pe_sections[(fd, yr, sem)]
    else:
        total_sections = sum(ta['section_count'] or 1 for ta in talist)
    coh = cohort.get((fd, yr))
    if coh and total_sections:
        scount = max(1, round(coh / total_sections))
    else:
        scount = class_size.get(fd) or default_size
    for ta in talist:
        if ta['faculty_id'] is not None and ta['faculty_id'] in teacher_id:
            tid = teacher_id[ta['faculty_id']]
        else:
            if ta['faculty_id'] is not None:
                note(f'  TA {ta["id"]}: faculty {ta["faculty_id"]} not found in faculty table -> placeholder teacher')
            tid = get_placeholder(td)
            tc_placeholder += 1
        for _ in range(ta['section_count'] or 1):
            w.execute('''INSERT INTO teacherCourse_teachercourse
                (id, student_count, current_students, academic_year, semester,
                 requires_special_scheduling, assist_teacher_type, assist_teacher_2_type,
                 assist_teacher_3_type, asssist_teacher_id, asssist_teacher_2_id,
                 asssist_teacher_3_id, course_id_id, teacher_id_id)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                (tc_id, scount, 0, yr, sem, 0, None, None, None, None, None, None,
                 cc_of_group[key], tid))
            tc_id += 1
            tc_n += 1
note(f'teachercourse: {tc_n} rows (1 per section; section_count expanded), '
     f'{tc_placeholder} unassigned TAs -> {len(placeholder_of_dept)} placeholder teachers; '
     f'student_count = dept-year cohort / total sections, fallback dept class_size / {default_size}')

# ---------------------------------------------------------------- 10. student_profiles -> student_student
term_start_year = int((n.execute('SELECT start_date FROM academic_terms').fetchone()[0] or '2025')[:4])
# jan9 student degree_type is UG/PG (B.E and B.Tech are both UG); student_type (Govt/Mgmt
# quota) does not exist in the new schema -> NULL
DEG = {'B.E': 'UG', 'B.Tech': 'UG'}
s_alloc = IdAlloc(set())
s_n = s_reused = 0
for r in n.execute('SELECT * FROM student_profiles'):
    rid, was = s_alloc.take(old_student_by_roll.get(r['enrollment_number']))
    s_reused += was
    w.execute('''INSERT INTO student_student
        (id, batch, current_semester, year, roll_no, student_type, degree_type,
         timetable_created, dept_id_id, student_id_id)
        VALUES (?,?,?,?,?,?,?,?,?,?)''',
        (rid, term_start_year - ((r['year_of_study'] or 1) - 1), r['semester'], r['year_of_study'],
         r['enrollment_number'], None, DEG.get(r['degree_type'], r['degree_type']),
         0, dept_id.get(user_dept.get(r['user_id'])), r['user_id']))
    remember('student', r['id'], rid, was, 'roll match' if was else 'new')
    s_n += 1
note(f'students: {s_n} converted, {s_reused} reuse jan9 ids; batch = term start year - (year_of_study-1)')

# ---------------------------------------------------------------- 11. time_grids -> timetableMaster_session
grid = n.execute('SELECT slots FROM time_grids WHERE is_active=1').fetchone()
sess_n = 0
if grid and grid['slots']:
    slots = json.loads(grid['slots'])
    seen = {}
    for code, s in slots.items():
        key = (s['start'], s['end'], s.get('type') == 'lab')
        if key not in seen:
            seen[key] = s.get('slot_index', 99)
    rows = sorted(seen.items(), key=lambda kv: (kv[0][2], kv[1], kv[0][0]))
    sid = 1
    pn = ln = 0
    for (start, end, is_lab), _ in rows:
        if is_lab:
            ln += 1; name = f'Lab - {ln}'
        else:
            pn += 1; name = f'Period - {pn}'
        w.execute('INSERT INTO timetableMaster_session (id, name, start_time, end_time, is_lab_time) VALUES (?,?,?,?,?)',
                  (sid, name, start + ':00', end + ':00', 1 if is_lab else 0))
        sid += 1; sess_n += 1
note(f'sessions: {sess_n} distinct period/lab slots expanded from time_grids JSON')

# ---------------------------------------------------------------- finalize
w.executemany('INSERT INTO _conversion_id_map VALUES (?,?,?,?,?)', idmap_rows)
w.commit()

print()
print('row counts in converted DB:')
for t in ['department_department', 'authentication_user', 'teacher_teacher', 'rooms_room',
          'courseMaster_coursemaster', 'courseMaster_coursemasterroompreference',
          'course_course', 'teacherCourse_teachercourse', 'student_student', 'timetableMaster_session']:
    print(' ', t, w.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0])

with open(BASE + 'conversion_log.txt', 'w', encoding='utf-8') as f:
    f.write('\n'.join(log))
w.close(); n.close(); o.close()
print('\nwrote', OUT)
