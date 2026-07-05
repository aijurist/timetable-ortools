"""
scripts/seed_full.py
=====================
FULL reset + seed for end-to-end testing.

Wipes all application data, then creates:
  - 1 institution  (Exovance Demo University)
  - 2 departments  (CSE - IT)
  - 1 academic term (Even Sem 2026, ACTIVE)
  - 1 time grid    (Standard Lecture Grid — 33 slots, MON-SAT)
  - 10 courses     (5 CSE - 5 IT)
  - 40 faculty     (20 CSE - 20 IT, each with a login user)
  - 2 HOD users    (1 per dept)
  - 1 admin user
  - 1 super-admin user

Run from the backend root:

    cd backend
    python -m scripts.seed_full

Credentials  (all passwords: Admin@1234)
-------------------------------------------------------------
  super_admin   superadmin@exovance.io
  admin         admin@campus.edu
  hod (CSE)     hod.cse@campus.edu
  hod (IT)      hod.it@campus.edu
  teacher CSE   teacher{1..20}.cse@campus.edu
  teacher IT    teacher{1..20}.it@campus.edu
-------------------------------------------------------------
"""

from __future__ import annotations

import asyncio
import os
import sys
import uuid
from datetime import date

# -- path setup ------------------------------------------------------------
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SRC  = os.path.join(_ROOT, "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

import bcrypt
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.models.faculty    import EmploymentType
from app.models.institution import SchedulingMode, AcademicTermStatus
from app.models.course     import SessionType
from app.models.user       import UserRole

from dotenv import load_dotenv
load_dotenv(os.path.join(_ROOT, ".env"))

DATABASE_URL = os.environ["DATABASE_URL"]
engine       = create_async_engine(DATABASE_URL, echo=False)
Session      = async_sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)

DEFAULT_PASSWORD = "Admin@1234"


def _hash(plain: str) -> str:
    return bcrypt.hashpw(plain.encode(), bcrypt.gensalt()).decode()


# ==============================================================================
#  WIPE
# ==============================================================================

TRUNCATE_TABLES = [
    # Solver / schedule layer (most dependent)
    "solver_jobs",
    "scheduled_sessions",
    "scenario_rules",
    "teaching_assignments",
    "scheduling_targets",
    "course_offerings",
    "offering_buckets",
    "scenarios",
    # Resource layer
    "time_grids",
    "courses",
    "rooms",
    "faculty",
    "student_profiles",
    # Auth / people
    "users",
    # Org layer
    "departments",
    "academic_terms",
    "institutions",
]


async def wipe(db: AsyncSession) -> None:
    print("\n-- Wiping existing data -------------------------------------")
    for table in TRUNCATE_TABLES:
        try:
            await db.execute(text(f"TRUNCATE TABLE {table} CASCADE"))
            print(f"  [*] truncated {table}")
        except Exception as exc:
            # Table may not exist in all migration states — skip gracefully
            print(f"  [!] {table}: {exc}")
            await db.rollback()
            # Re-open the transaction after rollback
            await db.begin()
    await db.commit()


# ==============================================================================
#  INSTITUTION
# ==============================================================================

async def create_institution(db: AsyncSession) -> uuid.UUID:
    inst_id = uuid.uuid4()
    await db.execute(
        text("""
            INSERT INTO institutions
                (id, name, domain, scheduling_mode, timezone,
                 default_class_size, regulatory_body, is_active)
            VALUES
                (:id, :name, :domain, :mode, :tz, :cs, :rb, true)
        """),
        {
            "id":     inst_id,
            "name":   "Exovance Demo University",
            "domain": "demo.exovance.io",
            "mode":   SchedulingMode.TRADITIONAL.value,
            "tz":     "Asia/Kolkata",
            "cs":     60,
            "rb":     "UGC",
        },
    )
    print(f"  [+] Institution: Exovance Demo University  ({inst_id})")
    return inst_id


# ==============================================================================
#  DEPARTMENTS
# ==============================================================================

async def create_department(
    db: AsyncSession,
    inst_id: uuid.UUID,
    name: str,
    code: str,
    description: str,
    class_size: int = 60,
) -> uuid.UUID:
    dept_id = uuid.uuid4()
    await db.execute(
        text("""
            INSERT INTO departments
                (id, institution_id, name, code, description, class_size)
            VALUES
                (:id, :inst, :name, :code, :desc, :cs)
        """),
        {"id": dept_id, "inst": inst_id, "name": name,
         "code": code, "desc": description, "cs": class_size},
    )
    print(f"  [+] Department: {code} — {name}")
    return dept_id


# ==============================================================================
#  ACADEMIC TERM
# ==============================================================================

async def create_term(db: AsyncSession, inst_id: uuid.UUID) -> uuid.UUID:
    term_id = uuid.uuid4()
    await db.execute(
        text("""
            INSERT INTO academic_terms
                (id, institution_id, name, start_date, end_date,
                 term_type, status)
            VALUES
                (:id, :inst, :name, :start, :end, :ttype, :status)
        """),
        {
            "id":     term_id,
            "inst":   inst_id,
            "name":   "Even Sem 2026",
            "start":  date(2026, 1, 6),
            "end":    date(2026, 5, 30),
            "ttype":  "SEMESTER",
            "status": AcademicTermStatus.ACTIVE.value,
        },
    )
    print(f"  [+] Academic term: Even Sem 2026 (ACTIVE)  ({term_id})")
    return term_id


# ==============================================================================
#  TIME GRID  —  33 slots, MON-SAT, 3 periods per day
# ==============================================================================
#
#  Coding convention:
#    A = MON  B = TUE  C = WED  D = THU  E = FRI  F = SAT
#    1-3  = morning (09:00-12:00)
#    4-6  = afternoon (13:00-16:00)
#  SAT only gets morning slots (half-day).
#

def _build_slots() -> dict:
    days = [
        ("MON", "A"),
        ("TUE", "B"),
        ("WED", "C"),
        ("THU", "D"),
        ("FRI", "E"),
        ("SAT", "F"),
    ]

    morning_times = [
        ("09:00", "10:00"),
        ("10:00", "11:00"),
        ("11:00", "12:00"),
    ]
    afternoon_times = [
        ("13:00", "14:00"),
        ("14:00", "15:00"),
        ("15:00", "16:00"),
    ]

    slots: dict = {}
    for day, prefix in days:
        for idx, (start, end) in enumerate(morning_times, 1):
            code = f"{prefix}{idx}"
            slots[code] = {"day": day, "start": start, "end": end, "period": "morning"}

        if day != "SAT":                          # SAT = half-day, no afternoon
            for idx, (start, end) in enumerate(afternoon_times, 4):
                code = f"{prefix}{idx}"
                slots[code] = {"day": day, "start": start, "end": end, "period": "afternoon"}

    return slots   # 3 + (5*6) = 3 + 30 = 33 slots


async def create_time_grid(
    db: AsyncSession,
    term_id: uuid.UUID,
) -> uuid.UUID:
    import json
    grid_id = uuid.uuid4()
    slots   = _build_slots()
    await db.execute(
        text("""
            INSERT INTO time_grids
                (id, academic_term_id, name, slots, is_active)
            VALUES
                (:id, :term, :name, CAST(:slots AS jsonb), true)
        """),
        {
            "id":   grid_id,
            "term": term_id,
            "name": "Standard Lecture Grid (60 min)",
            "slots": json.dumps(slots),
        },
    )
    print(f"  [+] Time grid: Standard Lecture Grid — {len(slots)} slots  ({grid_id})")
    return grid_id


# ==============================================================================
#  ROOMS
# ==============================================================================
#
#  300 students per dept / 60 per section = 5 sections per dept = 10 sections total.
#  We need enough rooms so sections can run in parallel:
#    - 10 lecture halls  (cap 65)  — theory classes
#    -  2 computer labs  (cap 40)  — CS501 / IT501 lab sessions
#    -  1 seminar room   (cap 30)  — small group / tutorials
#  Total: 13 rooms, all under the same institution_id.
#

ROOMS = [
    # code,   name,                       capacity, room_type,         building, tags
    ("LH101", "Lecture Hall 101",         65, "LECTURE",  "Block A", ["PROJECTOR","WHITEBOARD"]),
    ("LH102", "Lecture Hall 102",         65, "LECTURE",  "Block A", ["PROJECTOR","WHITEBOARD"]),
    ("LH103", "Lecture Hall 103",         65, "LECTURE",  "Block A", ["PROJECTOR","WHITEBOARD"]),
    ("LH104", "Lecture Hall 104",         65, "LECTURE",  "Block A", ["PROJECTOR","WHITEBOARD"]),
    ("LH105", "Lecture Hall 105",         65, "LECTURE",  "Block A", ["PROJECTOR","WHITEBOARD"]),
    ("LH201", "Lecture Hall 201",         65, "LECTURE",  "Block B", ["PROJECTOR","WHITEBOARD","SMART_BOARD"]),
    ("LH202", "Lecture Hall 202",         65, "LECTURE",  "Block B", ["PROJECTOR","WHITEBOARD","SMART_BOARD"]),
    ("LH203", "Lecture Hall 203",         65, "LECTURE",  "Block B", ["PROJECTOR","WHITEBOARD","SMART_BOARD"]),
    ("LH204", "Lecture Hall 204",         65, "LECTURE",  "Block B", ["PROJECTOR","WHITEBOARD"]),
    ("LH205", "Lecture Hall 205",         65, "LECTURE",  "Block B", ["PROJECTOR","WHITEBOARD"]),
    ("CL101", "Computer Lab 101",         40, "LAB",      "Block C", ["COMPUTERS","LINUX_WORKSTATION","AC","COMPUTERS"]),
    ("CL102", "Computer Lab 102",         40, "LAB",      "Block C", ["COMPUTERS","LINUX_WORKSTATION","AC","COMPUTERS"]),
    ("SR101", "Seminar Room 101",         30, "SEMINAR",  "Block A", ["WHITEBOARD","AC"]),
]


async def create_rooms(db: AsyncSession, inst_id: uuid.UUID) -> None:
    import json
    for code, name, cap, rtype, building, tags in ROOMS:
        rid = uuid.uuid4()
        await db.execute(
            text("""
                INSERT INTO rooms
                    (id, institution_id, code, name, capacity,
                     room_type, building, tags, is_active)
                VALUES
                    (:id, :inst, :code, :name, :cap,
                     :rtype, :building, CAST(:tags AS jsonb), true)
            """),
            {
                "id":       rid,
                "inst":     inst_id,
                "code":     code,
                "name":     name,
                "cap":      cap,
                "rtype":    rtype,
                "building": building,
                "tags":     json.dumps(tags),
            },
        )
        print(f"  [+] Room: {code}  {name:<30}  cap={cap}  type={rtype}  ({building})")


# ==============================================================================
#  COURSES
# ==============================================================================

CSE_COURSES = [
    ("CS101", "Data Structures",        SessionType.THEORY, 4, 4),
    ("CS201", "Design & Analysis of Algorithms", SessionType.THEORY, 4, 4),
    ("CS301", "Database Management Systems",     SessionType.THEORY, 3, 3),
    ("CS401", "Operating Systems",               SessionType.THEORY, 3, 3),
    ("CS501", "Computer Networks Lab",           SessionType.LAB,    2, 4),
]

IT_COURSES = [
    ("IT101", "Web Technologies",       SessionType.THEORY, 4, 4),
    ("IT201", "Software Engineering",   SessionType.THEORY, 4, 4),
    ("IT301", "Network Security",       SessionType.THEORY, 3, 3),
    ("IT401", "Cloud Computing",        SessionType.THEORY, 3, 3),
    ("IT501", "Full Stack Dev Lab",     SessionType.LAB,    2, 4),
]


async def create_courses(
    db: AsyncSession,
    inst_id: uuid.UUID,
    dept_id: uuid.UUID,
    courses: list[tuple],
) -> list[uuid.UUID]:
    ids = []
    for code, name, stype, credits, weekly_hours in courses:
        cid = uuid.uuid4()
        await db.execute(
            text("""
                INSERT INTO courses
                    (id, institution_id, department_id, code, name,
                     session_type, credits, weekly_hours, room_tags,
                     room_equipment, is_active)
                VALUES
                    (:id, :inst, :dept, :code, :name,
                     :stype, :credits, :wh, CAST('[]' AS jsonb),
                     CAST('[]' AS jsonb), true)
            """),
            {
                "id":      cid,
                "inst":    inst_id,
                "dept":    dept_id,
                "code":    code,
                "name":    name,
                "stype":   stype.value,
                "credits": credits,
                "wh":      weekly_hours,
            },
        )
        ids.append(cid)
        print(f"  [+] Course: {code} — {name}  ({stype.value}, {credits} cr, {weekly_hours}h/wk)")
    return ids


# ==============================================================================
#  TEACHING ASSIGNMENTS
# ==============================================================================
#
#  300 students / 60 per section = 5 sections per course.
#
#  Distribution per course (theory): 3 faculty, sections 2+2+1 = 5
#  Distribution per course (lab):    2 faculty, sections 3+2   = 5
#
#  Layout (faculty index 0-based):
#    course 0 (theory): f[0] 2sec,  f[1] 2sec,  f[2] 1sec
#    course 1 (theory): f[3] 2sec,  f[4] 2sec,  f[5] 1sec
#    course 2 (theory): f[6] 2sec,  f[7] 2sec,  f[8] 1sec
#    course 3 (theory): f[9] 2sec,  f[10] 2sec, f[11] 1sec
#    course 4 (lab):    f[12] 3sec, f[13] 2sec
#

ASSIGNMENT_LAYOUT = [
    # (faculty_index, course_index, section_count)
    (0,  0, 2), (1,  0, 2), (2,  0, 1),   # course 0  => 5 sections
    (3,  1, 2), (4,  1, 2), (5,  1, 1),   # course 1  => 5 sections
    (6,  2, 2), (7,  2, 2), (8,  2, 1),   # course 2  => 5 sections
    (9,  3, 2), (10, 3, 2), (11, 3, 1),   # course 3  => 5 sections
    (12, 4, 3), (13, 4, 2),               # course 4  => 5 sections (lab)
]


async def create_teaching_assignments(
    db: AsyncSession,
    inst_id: uuid.UUID,
    term_id: uuid.UUID,
    dept_id: uuid.UUID,
    dept_code: str,
    faculty_ids: list[uuid.UUID],
    course_ids: list[uuid.UUID],
) -> None:
    count = 0
    for fac_idx, course_idx, section_count in ASSIGNMENT_LAYOUT:
        fac_id    = faculty_ids[fac_idx]
        course_id = course_ids[course_idx]
        aid       = uuid.uuid4()
        await db.execute(
            text("""
                INSERT INTO teaching_assignments
                    (id, institution_id, academic_term_id, department_id,
                     faculty_id, course_id, section_count, is_active)
                VALUES
                    (:id, :inst, :term, :dept,
                     :fac, :course, :sec, true)
            """),
            {
                "id":    aid,
                "inst":  inst_id,
                "term":  term_id,
                "dept":  dept_id,
                "fac":   fac_id,
                "course": course_id,
                "sec":   section_count,
            },
        )
        count += 1

    print(f"  [+] {dept_code}: {count} teaching assignments ({len(ASSIGNMENT_LAYOUT)} rows, 5 sections/course)")


# ==============================================================================
#  FACULTY  (20 per dept + linked user account)
# ==============================================================================

CSE_FACULTY_NAMES = [
    "Dr. Ananya Krishnaswamy", "Prof. Vikram Nair",       "Dr. Meera Pillai",
    "Prof. Suresh Babu",       "Dr. Kavitha Venkatesh",   "Prof. Arjun Menon",
    "Dr. Lakshmi Prasad",      "Prof. Rahul Sharma",      "Dr. Deepa Iyer",
    "Prof. Sanjay Kumar",      "Dr. Priya Rajan",         "Prof. Anil Thomas",
    "Dr. Rekha Nambiar",       "Prof. Manoj Chandran",    "Dr. Swathi Suresh",
    "Prof. Ravi Varma",        "Dr. Nithya Gopal",        "Prof. Binu Mathew",
    "Dr. Sindhu Krishnan",     "Prof. Jayakrishnan P.",
]

IT_FACULTY_NAMES = [
    "Dr. Arun Balakrishnan",   "Prof. Divya Mohan",       "Dr. Sree Latha",
    "Prof. Nikhil Nair",       "Dr. Anjali Subramanian",  "Prof. Harish Menon",
    "Dr. Parvathi Rajeev",     "Prof. Vinod Kumar",       "Dr. Smitha George",
    "Prof. Rajesh Pillai",     "Dr. Sreeja Nair",         "Prof. Abhijith K.",
    "Dr. Gayathri Devi",       "Prof. Sujith Varma",      "Dr. Athira Mohan",
    "Prof. Dileep C.",         "Dr. Lekha Sasi",          "Prof. Jijo Mathew",
    "Dr. Chindu Lal",          "Prof. Akhil Suresh",
]


async def create_faculty_batch(
    db: AsyncSession,
    inst_id: uuid.UUID,
    dept_id: uuid.UUID,
    dept_code: str,
    names: list[str],
) -> list[uuid.UUID]:
    """Create Faculty rows + linked User accounts for all names in the list."""
    fac_ids = []
    for i, name in enumerate(names, 1):
        slug   = dept_code.lower()
        email  = f"teacher{i}.{slug}@campus.edu"
        fac_id = uuid.uuid4()
        usr_id = uuid.uuid4()

        # Alternate employment type: first 14 full-time, last 6 part-time/adjunct
        if i <= 14:
            emp_type = EmploymentType.FULL_TIME.value
            max_hrs  = 20
        elif i <= 18:
            emp_type = EmploymentType.PART_TIME.value
            max_hrs  = 12
        else:
            emp_type = EmploymentType.ADJUNCT.value
            max_hrs  = 8

        await db.execute(
            text("""
                INSERT INTO faculty
                    (id, institution_id, department_id, name,
                     employment_type, max_weekly_hours,
                     availability_blacklist, preferences, is_active)
                VALUES
                    (:id, :inst, :dept, :name,
                     :emp, :hrs,
                     CAST('[]' AS jsonb), CAST('{}' AS jsonb), true)
            """),
            {
                "id":   fac_id, "inst": inst_id, "dept": dept_id,
                "name": name,
                "emp":  emp_type, "hrs": max_hrs,
            },
        )

        await db.execute(
            text("""
                INSERT INTO users
                    (id, institution_id, department_id, department,
                     email, hashed_password, full_name, role,
                     is_active, is_verified)
                VALUES
                    (:id, :inst, :dept_id, :dept_code,
                     :email, :pwd, :name, :role,
                     true, true)
            """),
            {
                "id":        usr_id,
                "inst":      inst_id,
                "dept_id":   dept_id,
                "dept_code": dept_code,
                "email":     email,
                "pwd":       _hash(DEFAULT_PASSWORD),
                "name":      name,
                "role":      UserRole.TEACHER.value,
            },
        )

        # Link Faculty → User
        await db.execute(
            text("UPDATE faculty SET user_id = :usr_id WHERE id = :fac_id"),
            {"usr_id": usr_id, "fac_id": fac_id},
        )

        fac_ids.append(fac_id)

    print(f"  [+] {len(names)} faculty created for {dept_code}")
    return fac_ids


# ==============================================================================
#  HOD USERS
# ==============================================================================

async def create_hod(
    db: AsyncSession,
    inst_id: uuid.UUID,
    dept_id: uuid.UUID,
    dept_code: str,
    name: str,
    email: str,
) -> uuid.UUID:
    fac_id = uuid.uuid4()
    usr_id = uuid.uuid4()

    await db.execute(
        text("""
            INSERT INTO faculty
                (id, institution_id, department_id, name,
                 employment_type, max_weekly_hours,
                 availability_blacklist, preferences, is_active)
            VALUES
                (:id, :inst, :dept, :name,
                 :emp, 8,
                 CAST('[]' AS jsonb), CAST('{}' AS jsonb), true)
        """),
        {
            "id": fac_id, "inst": inst_id, "dept": dept_id,
            "name": name,
            "emp": EmploymentType.FULL_TIME.value,
        },
    )

    await db.execute(
        text("""
            INSERT INTO users
                (id, institution_id, department_id, department,
                 email, hashed_password, full_name, role,
                 is_active, is_verified)
            VALUES
                (:id, :inst, :dept_id, :dept_code,
                 :email, :pwd, :name, :role,
                 true, true)
        """),
        {
            "id":        usr_id,
            "inst":      inst_id,
            "dept_id":   dept_id,
            "dept_code": dept_code,
            "email":     email,
            "pwd":       _hash(DEFAULT_PASSWORD),
            "name":      name,
            "role":      UserRole.TEACHER.value,
        },
    )

    # Link Faculty → User
    await db.execute(
        text("UPDATE faculty SET user_id = :usr_id WHERE id = :fac_id"),
        {"usr_id": usr_id, "fac_id": fac_id},
    )

    # Link faculty as the department's HOD
    await db.execute(
        text("UPDATE departments SET hod_faculty_id = :fac_id WHERE id = :dept_id"),
        {"fac_id": fac_id, "dept_id": dept_id},
    )

    print(f"  [+] HOD: {name} <{email}>  (dept={dept_code})")
    return usr_id


# ==============================================================================
#  ADMIN / SUPER-ADMIN
# ==============================================================================

async def create_admin(
    db: AsyncSession,
    inst_id: uuid.UUID | None,
    email: str,
    name: str,
    role: UserRole,
) -> None:
    uid = uuid.uuid4()
    await db.execute(
        text("""
            INSERT INTO users
                (id, institution_id, email, hashed_password,
                 full_name, role, is_active, is_verified)
            VALUES
                (:id, :inst, :email, :pwd, :name, :role, true, true)
        """),
        {
            "id":   uid,
            "inst": inst_id,
            "email": email,
            "pwd":  _hash(DEFAULT_PASSWORD),
            "name": name,
            "role": role.value,
        },
    )
    print(f"  [+] {role.value}: {name} <{email}>")


# ==============================================================================
#  MAIN
# ==============================================================================

async def seed() -> None:
    async with Session() as db:
        # -- Wipe ----------------------------------------------------------
        await wipe(db)

        # -- Institution ---------------------------------------------------
        print("\n-- Institution ---------------------------------------------")
        inst_id = await create_institution(db)
        await db.commit()

        # -- Departments ---------------------------------------------------
        print("\n-- Departments ---------------------------------------------")
        cse_id = await create_department(
            db, inst_id,
            "Computer Science & Engineering", "CSE",
            "B.Tech Computer Science & Engineering — 300 students",
            class_size=60,
        )
        it_id = await create_department(
            db, inst_id,
            "Information Technology", "IT",
            "B.Tech Information Technology — 300 students",
            class_size=60,
        )
        await db.commit()

        # -- Academic Term -------------------------------------------------
        print("\n-- Academic Term --------------------------------------------")
        term_id = await create_term(db, inst_id)
        await db.commit()

        # -- Time Grid -----------------------------------------------------
        print("\n-- Time Grid ------------------------------------------------")
        await create_time_grid(db, term_id)
        await db.commit()

        # -- Rooms ---------------------------------------------------------
        print("\n-- Rooms (13 total: 10 lecture + 2 lab + 1 seminar) ---------")
        await create_rooms(db, inst_id)
        await db.commit()

        # -- Courses -------------------------------------------------------
        print("\n-- Courses (CSE) --------------------------------------------")
        cse_course_ids = await create_courses(db, inst_id, cse_id, CSE_COURSES)
        await db.commit()

        print("\n-- Courses (IT) ---------------------------------------------")
        it_course_ids = await create_courses(db, inst_id, it_id, IT_COURSES)
        await db.commit()

        # -- Faculty -------------------------------------------------------
        print("\n-- Faculty (CSE) — 20 members -------------------------------")
        cse_faculty_ids = await create_faculty_batch(db, inst_id, cse_id, "CSE", CSE_FACULTY_NAMES)
        await db.commit()

        print("\n-- Faculty (IT) — 20 members --------------------------------")
        it_faculty_ids = await create_faculty_batch(db, inst_id, it_id, "IT", IT_FACULTY_NAMES)
        await db.commit()

        # -- Teaching Assignments ------------------------------------------
        print("\n-- Teaching Assignments (5 sections x 5 courses each dept) --")
        await create_teaching_assignments(
            db, inst_id, term_id, cse_id, "CSE", cse_faculty_ids, cse_course_ids,
        )
        await create_teaching_assignments(
            db, inst_id, term_id, it_id, "IT", it_faculty_ids, it_course_ids,
        )
        await db.commit()

        # -- HODs ----------------------------------------------------------
        print("\n-- HOD Accounts ---------------------------------------------")
        await create_hod(db, inst_id, cse_id, "CSE",
                         "Prof. Ramesh Iyer", "hod.cse@campus.edu")
        await create_hod(db, inst_id, it_id,  "IT",
                         "Prof. Sunitha Rajan", "hod.it@campus.edu")
        await db.commit()

        # -- Admin / Super-Admin -------------------------------------------
        print("\n-- Admin Accounts -------------------------------------------")
        await create_admin(db, inst_id,   "admin@campus.edu",
                           "Campus Admin", UserRole.ADMIN)
        await create_admin(db, None,      "superadmin@exovance.io",
                           "Super Admin",  UserRole.SUPER_ADMIN)
        await db.commit()

    # -- Summary -----------------------------------------------------------
    print("\n" + "=" * 66)
    print("  Seed complete.  All passwords: Admin@1234")
    print("=" * 66)
    rows = [
        ("SUPER_ADMIN",  "superadmin@exovance.io",        "platform-wide"),
        ("ADMIN",        "admin@campus.edu",               "Exovance Demo University"),
        ("HOD",          "hod.cse@campus.edu",             "CSE dept"),
        ("HOD",          "hod.it@campus.edu",              "IT dept"),
        ("TEACHER (x20)", "teacher{1..20}.cse@campus.edu", "CSE — 14 FT - 4 PT - 2 ADJ"),
        ("TEACHER (x20)", "teacher{1..20}.it@campus.edu",  "IT  — 14 FT - 4 PT - 2 ADJ"),
    ]
    print(f"\n  {'Role':<18} {'Email':<36} Notes")
    print(f"  {'-'*18} {'-'*36} {'-'*28}")
    for role, email, notes in rows:
        print(f"  {role:<18} {email:<36} {notes}")
    print()
    print("  Rooms     : 10 lecture halls (cap 65) + 2 computer labs (cap 40) + 1 seminar (cap 30)")
    print("  Time grid : Standard Lecture Grid (60 min) — 33 slots (MON-SAT)")
    print("  Slots     : A1-A6 (MON) - B1-B6 (TUE) - C1-C6 (WED)")
    print("              D1-D6 (THU) - E1-E6 (FRI) - F1-F3 (SAT half-day)")
    print("  Courses   : CS101-CS501 (CSE) + IT101-IT501 (IT)")
    print("  Term      : Even Sem 2026  (ACTIVE, Jan 6 – May 30)")
    print("=" * 66 + "\n")


if __name__ == "__main__":
    asyncio.run(seed())
