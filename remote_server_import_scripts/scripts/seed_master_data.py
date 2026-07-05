"""
scripts/seed_master_data.py
============================
Idempotent master data seed from backend/scripts/data/.

Usage (run from backend/):
  PYTHONPATH=src python -m scripts.seed_master_data --institution-id <UUID>

Optional flags:
  --default-password Campus@2024
  --data-dir         scripts/data
  --skip-faculty     --skip-students  --skip-rooms  --skip-courses
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import re
import sys
import uuid
from datetime import date
from pathlib import Path
from typing import Any

import bcrypt
import openpyxl
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from app.core.config import settings  # noqa: E402
from app.models.course import Course, SessionType  # noqa: E402
from app.models.faculty import DesignationType, EmploymentType, Faculty  # noqa: E402
from app.models.institution import (  # noqa: E402
    AcademicTerm, AcademicTermStatus, Department, Institution, SchedulingMode, TermType,
)
from app.models.room import Room, RoomType  # noqa: E402
from app.models.student import StudentProfile  # noqa: E402
from app.models.time_grid import TimeGrid  # noqa: E402
from app.models.user import GenderType, User, UserRole  # noqa: E402

# ---------------------------------------------------------------------------
# Time-grid definition — REC Standard 6-Day Grid
# ---------------------------------------------------------------------------
#
# Unified period list (P1–P12 per day).  Both theory and lab classes use the
# same slots.  Theory occupies 1 slot; lab occupies 2 consecutive slots.
#
# Lab session → slot pairs:
#   L1 = P1+P2   (08:00–09:40)   L2 = P3+P4   (10:00–11:40)
#   L3 = P5+P6   (11:50–13:20)   L4 = P7+P8   (13:20–15:00)
#   L5 = P9+P10  (15:00–16:40)   L6 = P11+P12 (17:20–19:00)
#
# Breaks: 09:40–10:00 (short), 16:40–17:20 (evening)

_REC_DAYS = ["MON", "TUE", "WED", "THU", "FRI", "SAT"]

_UNIFIED_PERIODS: list[tuple[str, str, str, str]] = [
    ("P1",  "08:00", "08:50", "morning"),
    ("P2",  "08:50", "09:40", "morning"),
    ("P3",  "10:00", "10:50", "morning"),
    ("P4",  "10:50", "11:40", "morning"),
    ("P5",  "11:50", "12:40", "morning"),
    ("P6",  "12:40", "13:20", "afternoon"),
    ("P7",  "13:20", "14:10", "afternoon"),
    ("P8",  "14:10", "15:00", "afternoon"),
    ("P9",  "15:00", "15:50", "afternoon"),
    ("P10", "15:50", "16:40", "afternoon"),
    ("P11", "17:20", "18:10", "evening"),
    ("P12", "18:10", "19:00", "evening"),
]

# Consecutive period pairs used for 2-slot lab sessions (see comment block above).
_LAB_PAIR_FAMILIES: list[tuple[str, str, str]] = [
    ("P1", "P2", "L1"),
    ("P3", "P4", "L2"),
    ("P5", "P6", "L3"),
    ("P7", "P8", "L4"),
    ("P9", "P10", "L5"),
    ("P11", "P12", "L6"),
]


def _build_rec_slots() -> dict:
    period_to_family: dict[str, str] = {}
    for p1, p2, fam in _LAB_PAIR_FAMILIES:
        period_to_family[p1] = fam
        period_to_family[p2] = fam

    slots: dict = {}
    for day in _REC_DAYS:
        for code, start, end, period in _UNIFIED_PERIODS:
            entry: dict[str, str] = {
                "day": day,
                "start": start,
                "end": end,
                "period": period,
            }
            if code in period_to_family:
                entry["family"] = period_to_family[code]
            slots[f"{day}_{code}"] = entry
    return slots


# ---------------------------------------------------------------------------
# Pure helpers (no I/O)
# ---------------------------------------------------------------------------

_STOP = {"of", "and", "the", "&", "for", "in", "a"}


def _hash(plain: str) -> str:
    return bcrypt.hashpw(plain.encode(), bcrypt.gensalt()).decode()


def _clean_name(raw: str) -> str:
    return re.sub(r"\s+", " ", str(raw or "").strip())


def _title_case(name: str) -> str:
    """UPPERCASE or lowercase → Title Case, handles hyphens."""
    result = []
    for word in _clean_name(name).split():
        if "-" in word:
            result.append("-".join(p.capitalize() for p in word.split("-")))
        else:
            result.append(word.capitalize())
    return " ".join(result)


def _normalize_phone(raw: Any) -> str | None:
    if not raw:
        return None
    s = str(raw).strip()
    # Handle numeric cells stored as float: 919445751523.0
    if s.endswith(".0") and s[:-2].isdigit():
        s = s[:-2]
    # Strip country code dash: "91-9445751523" → "919445751523"
    s = re.sub(r"^(\d{2})-(\d+)$", r"\1\2", s)
    return s if s else None


def _numeric_str(val: Any) -> str | None:
    """Return integer string from numeric cell (strips .0 from floats)."""
    if val is None or str(val).strip() == "":
        return None
    s = str(val).strip()
    try:
        return str(int(float(s)))
    except (ValueError, OverflowError):
        return s


def _dept_code_from_name(full: str, used: set[str]) -> str:
    """Derive a short code from dept name; avoid collisions by appending digit."""
    name = re.sub(r"^department\s+of\s+", "", full.strip(), flags=re.I)
    words = [w for w in re.split(r"[\s\-_]+", name) if w.lower() not in _STOP]
    if len(words) == 1:
        base = words[0][:4].upper()
    else:
        base = "".join(w[0].upper() for w in words)
    code = base[:10]
    suffix = 2
    while code in used:
        code = f"{base[:9]}{suffix}"
        suffix += 1
    used.add(code)
    return code


def _normalize_dept_name(name: str) -> str:
    """Canonical form for fuzzy dept lookup: strip prefix, lowercase, unify & vs and."""
    n = re.sub(r"(?i)^department\s+of\s+", "", str(name).strip())
    n = re.sub(r"\s+and\s+", " & ", n, flags=re.IGNORECASE)
    return n.strip().lower()


def _parse_pe_ne(val: str) -> tuple[bool, int | None]:
    """Return (is_elective, elective_semester)."""
    v = str(val or "").strip().upper()
    if not v or v in ("NE", ""):
        return False, None
    m = re.match(r"PE\s*(\d+)?", v)
    if m:
        sem_str = m.group(1)
        return True, int(sem_str) if sem_str else None
    return False, None


def _map_designation(raw: str) -> DesignationType | None:
    v = str(raw or "").strip().lower()
    MAP = {
        "professor": DesignationType.PROFESSOR,
        "associate professor": DesignationType.ASSOCIATE_PROFESSOR,
        "assistant professor": DesignationType.ASSISTANT_PROFESSOR,
        "asst. professor": DesignationType.ASSISTANT_PROFESSOR,
        "asst professor": DesignationType.ASSISTANT_PROFESSOR,
        "senior lecturer": DesignationType.SENIOR_LECTURER,
        "lecturer": DesignationType.LECTURER,
        "lab instructor": DesignationType.LAB_INSTRUCTOR,
        "teaching assistant": DesignationType.TEACHING_ASSISTANT,
        "principal": DesignationType.PRINCIPAL,
        "director": DesignationType.DIRECTOR,
        "dean of academics": DesignationType.DEAN_OF_ACADEMICS,
        "dean of student affairs": DesignationType.DEAN_OF_STUDENT_AFFAIRS,
        "dean of research": DesignationType.DEAN_OF_RESEARCH,
        "associate dean": DesignationType.ASSOCIATE_DEAN,
        "emeritus professor": DesignationType.EMERITUS_PROFESSOR,
        "professor of practice": DesignationType.PROFESSOR_OF_PRACTICE,
        "visiting professor": DesignationType.VISITING_PROFESSOR,
        "hod": DesignationType.ASSOCIATE_PROFESSOR,
        "head of the department": DesignationType.ASSOCIATE_PROFESSOR,
        "assistant professor (sg)": DesignationType.ASSISTANT_PROFESSOR,
        "assistant professor (ss)": DesignationType.ASSISTANT_PROFESSOR,
        "vice principal": DesignationType.PRINCIPAL,
        "dean": DesignationType.DEAN_OF_ACADEMICS,
    }
    return MAP.get(v)


def _map_gender(raw: str) -> GenderType | None:
    v = str(raw or "").strip().lower()
    if v in ("male", "m"):
        return GenderType.MALE
    if v in ("female", "f"):
        return GenderType.FEMALE
    if v in ("other", "o"):
        return GenderType.OTHER
    return None


def _map_room_type(raw: str) -> RoomType:
    v = str(raw or "").strip().lower()
    if "lab" in v:
        return RoomType.LAB
    if "seminar" in v:
        return RoomType.SEMINAR
    if "auditorium" in v or "audi" in v:
        return RoomType.AUDITORIUM
    return RoomType.LECTURE


def _parse_bool_col(val: Any) -> bool:
    return str(val or "").strip().lower() in ("1", "true", "yes", "t")


def _derive_year_and_semester(batch_year: int, current_year: int = 2026) -> tuple[int, int]:
    year = max(1, min(4, current_year - int(batch_year) + 1))
    sem = (year - 1) * 2 + 1
    return year, sem


def _parse_degree_type(programme: str) -> str:
    PREFIXES = [
        "B.Tech.", "B.E.", "B.Sc.", "B.Com.", "B.A.",
        "M.Tech.", "M.E.", "M.Sc.", "M.B.A.", "MBA",
        "Ph.D.", "PhD",
    ]
    for p in PREFIXES:
        if programme.startswith(p):
            return p.rstrip(".")
    return programme.split()[0] if programme.split() else "B.Tech."


def _norm_course_name(name: str) -> str:
    """Normalise for fuzzy name-based enrichment lookup (lowercase, collapsed whitespace)."""
    return re.sub(r"\s+", " ", str(name or "").strip().lower())


def _load_csv_enrichment(
    data_dir: Path,
) -> tuple[dict[str, dict], dict[str, dict]]:
    """Load enrichment from all 3 CSV files.

    Returns:
        by_code — {COURSE_CODE_UPPER: best_row}  (primary lookup)
        by_name — {normalised_name: best_row}     (fallback when code doesn't match)

    "Best row" prefers entries that carry a lab_type value.
    """
    all_rows: list[dict] = []
    for fname in ("cs.csv", "core_v2.csv", "core_dept.csv"):
        p = data_dir / fname
        if p.exists():
            with open(p, newline="", encoding="utf-8-sig") as f:
                all_rows.extend(csv.DictReader(f))

    by_code: dict[str, dict] = {}
    by_name: dict[str, dict] = {}

    for row in all_rows:
        code = str(row.get("course_code", "")).strip().upper()
        name_key = _norm_course_name(row.get("course_name", ""))
        is_better = bool(row.get("lab_type"))

        if code:
            if code not in by_code or (is_better and not by_code[code].get("lab_type")):
                by_code[code] = row

        if name_key:
            if name_key not in by_name or (is_better and not by_name[name_key].get("lab_type")):
                by_name[name_key] = row

    return by_code, by_name


def _parse_xlsx_courses(path: Path) -> list[dict]:
    """Parse one dept xlsx → list of {code, name, lecture_credits, tutorial_credits, practical_credits, total_credits}."""
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    ws = wb.active
    courses: list[dict] = []
    current: dict | None = None

    def _fc(v: Any) -> float:
        try:
            return float(v or 0)
        except (TypeError, ValueError):
            return 0.0

    for row in ws.iter_rows(values_only=True):
        component = str(row[8] or "").strip().upper()
        if component == "LECTURE":
            if current:
                courses.append(current)
            code = str(row[0] or "").strip().upper()
            if not code:
                current = None
                continue
            current = {
                "code": code,
                "name": str(row[1] or "").strip() or code,
                "lecture_credits": _fc(row[9]),
                "tutorial_credits": 0.0,
                "practical_credits": 0.0,
                "total_credits": _fc(row[11]),
            }
        elif component == "TUTORIAL" and current is not None:
            current["tutorial_credits"] = _fc(row[9])
        elif component == "PRACTICAL" and current is not None:
            current["practical_credits"] = _fc(row[9])

    if current:
        courses.append(current)
    wb.close()
    return courses


# ---------------------------------------------------------------------------
# Step 0 — Institution
# ---------------------------------------------------------------------------

async def seed_institution(
    db: AsyncSession,
    institution_id: uuid.UUID,
) -> None:
    """Create Rajalakshmi Engineering College if it doesn't exist yet (idempotent by id)."""
    existing = (await db.execute(
        select(Institution.id).where(Institution.id == institution_id)
    )).scalar_one_or_none()

    if existing:
        print(f"    [SKIP] Institution already exists ({institution_id})")
        return

    inst = Institution(
        id=institution_id,
        name="Rajalakshmi Engineering College",
        regulatory_body="AICTE",
        scheduling_mode=SchedulingMode.TRADITIONAL,
        timezone="Asia/Kolkata",
        default_class_size=70,
        is_active=True,
    )
    db.add(inst)
    await db.flush()
    await db.commit()
    print(f"    [OK]   Created institution 'Rajalakshmi Engineering College' → {institution_id}")


# ---------------------------------------------------------------------------
# Step 1 — Departments
# ---------------------------------------------------------------------------

def _collect_dept_names(data_dir: Path) -> tuple[set[str], set[str]]:
    """Return (student_dept_names, faculty_only_dept_names) — sync openpyxl scan."""
    student_depts: set[str] = set()
    faculty_depts: set[str] = set()

    wb = openpyxl.load_workbook(data_dir / "students.xlsx", read_only=True, data_only=True)
    ws = wb.active
    headers = [str(c.value or "").strip() for c in next(ws.iter_rows(max_row=1))]
    dept_col = headers.index("Department") if "Department" in headers else -1
    if dept_col >= 0:
        for row in ws.iter_rows(min_row=2, values_only=True):
            val = str(row[dept_col] or "").strip()
            if val:
                student_depts.add(val)
    wb.close()

    wb2 = openpyxl.load_workbook(data_dir / "faculty.xlsx", read_only=True, data_only=True)
    ws2 = wb2.active
    headers2 = [str(c.value or "").strip() for c in next(ws2.iter_rows(max_row=1))]
    dept_col2 = headers2.index("Department Name") if "Department Name" in headers2 else -1
    if dept_col2 >= 0:
        for row in ws2.iter_rows(min_row=2, values_only=True):
            val = str(row[dept_col2] or "").strip()
            if val:
                faculty_depts.add(val)
    wb2.close()

    faculty_only = faculty_depts - student_depts
    return student_depts, faculty_only


async def seed_departments(
    db: AsyncSession,
    institution_id: uuid.UUID,
    student_depts: set[str],
    faculty_only_depts: set[str],
) -> dict[str, uuid.UUID]:
    """Create departments; return name→id map."""
    used_codes: set[str] = set()
    # Pre-load existing codes to avoid conflicts
    existing = (await db.execute(
        select(Department.code).where(Department.institution_id == institution_id)
    )).scalars().all()
    used_codes.update(existing)

    name_to_id: dict[str, uuid.UUID] = {}
    created = skipped = 0

    all_depts = [(n, "ACADEMIC") for n in student_depts] + [(n, "SERVICE") for n in faculty_only_depts]

    for full_name, dept_type in all_depts:
        # Check existing by name
        row = (await db.execute(
            select(Department.id).where(
                Department.institution_id == institution_id,
                Department.name == full_name,
            )
        )).scalar_one_or_none()
        if row:
            name_to_id[full_name] = row
            skipped += 1
            continue

        code = _dept_code_from_name(full_name, used_codes)
        dept = Department(
            institution_id=institution_id,
            name=full_name,
            code=code,
            dept_type=dept_type,
        )
        db.add(dept)
        await db.flush()
        name_to_id[full_name] = dept.id
        created += 1

    await db.commit()
    print(f"  Departments  → created={created}, skipped={skipped}")
    return name_to_id


# ---------------------------------------------------------------------------
# Step 2 — Faculty
# ---------------------------------------------------------------------------

async def seed_faculty(
    db: AsyncSession,
    institution_id: uuid.UUID,
    data_dir: Path,
    default_password: str,
    dept_map: dict[str, uuid.UUID],
) -> None:
    wb = openpyxl.load_workbook(data_dir / "faculty.xlsx", read_only=True, data_only=True)
    ws = wb.active
    headers = [str(c.value or "").strip() for c in next(ws.iter_rows(max_row=1))]

    def col(name: str):
        return headers.index(name) if name in headers else -1

    c_emp = col("Employee Id")
    c_name = col("Name")
    c_email = col("Email")
    c_phone = col("Phone Number")
    c_dept = col("Department Name")
    c_desig = col("Designation")
    c_gender = col("Gender")

    created = skipped = errors = 0
    hashed = _hash(default_password)

    for row in ws.iter_rows(min_row=2, values_only=True):
        email = str(row[c_email] or "").strip().lower() if c_email >= 0 else ""
        if not email:
            continue

        try:
            existing = (await db.execute(
                select(User.id).where(User.email == email)
            )).scalar_one_or_none()
            if existing:
                skipped += 1
                continue

            name = _title_case(str(row[c_name] or "")) if c_name >= 0 else email
            phone = _normalize_phone(row[c_phone] if c_phone >= 0 else None)
            gender = _map_gender(str(row[c_gender] or "") if c_gender >= 0 else "")
            employee_id = _numeric_str(row[c_emp]) if c_emp >= 0 else None
            dept_name = str(row[c_dept] or "").strip() if c_dept >= 0 else ""
            dept_id = dept_map.get(dept_name)
            designation = _map_designation(str(row[c_desig] or "") if c_desig >= 0 else "")

            user = User(
                institution_id=institution_id,
                email=email,
                hashed_password=hashed,
                full_name=name,
                role=UserRole.TEACHER,
                department_id=dept_id,
                phone=phone,
                gender=gender,
                is_verified=True,
            )
            db.add(user)
            await db.flush()

            faculty = Faculty(
                institution_id=institution_id,
                name=name,
                user_id=user.id,
                employee_id=employee_id,
                employment_type=EmploymentType.FULL_TIME,
                designation=designation,
                max_weekly_hours=20,
            )
            db.add(faculty)
            await db.flush()
            await db.commit()
            created += 1

        except Exception as exc:
            await db.rollback()
            errors += 1
            if errors <= 5:
                print(f"    [WARN] faculty row skipped ({email}): {exc}")

    wb.close()
    print(f"  Faculty      → created={created}, skipped={skipped}, errors={errors}")


# ---------------------------------------------------------------------------
# Step 2b — HOD Assignments
# ---------------------------------------------------------------------------

async def seed_hod_assignments(
    db: AsyncSession,
    institution_id: uuid.UUID,
    data_dir: Path,
) -> None:
    """Link faculty with Designation='Head of the Department' to their departments
    and promote their user role to HOD."""
    wb = openpyxl.load_workbook(data_dir / "faculty.xlsx", read_only=True, data_only=True)
    ws = wb.active
    headers = [str(c.value or "").strip() for c in next(ws.iter_rows(max_row=1))]

    def col(name: str):
        return headers.index(name) if name in headers else -1

    c_email = col("Email")
    c_dept  = col("Department Name")
    c_desig = col("Designation")

    assigned = skipped = errors = 0

    for row in ws.iter_rows(min_row=2, values_only=True):
        desig = str(row[c_desig] or "").strip() if c_desig >= 0 else ""
        if desig != "Head of the Department":
            continue

        email    = str(row[c_email] or "").strip().lower() if c_email >= 0 else ""
        dept_name = str(row[c_dept] or "").strip() if c_dept >= 0 else ""
        if not email or not dept_name:
            skipped += 1
            continue

        try:
            # Resolve user → faculty
            user_row = (await db.execute(
                select(User.id).where(User.email == email)
            )).scalar_one_or_none()
            if not user_row:
                print(f"    [WARN] HOD user not found: {email}")
                skipped += 1
                continue

            faculty_row = (await db.execute(
                select(Faculty.id).where(Faculty.user_id == user_row)
            )).scalar_one_or_none()
            if not faculty_row:
                print(f"    [WARN] HOD faculty record not found: {email}")
                skipped += 1
                continue

            # Resolve department (exact match first, then normalized)
            dept_result = (await db.execute(
                select(Department.id).where(
                    Department.institution_id == institution_id,
                    Department.name == dept_name,
                )
            )).scalar_one_or_none()
            if not dept_result:
                print(f"    [WARN] HOD dept not found: {dept_name!r}")
                skipped += 1
                continue

            # Set hod_faculty_id on the department
            await db.execute(
                text("UPDATE departments SET hod_faculty_id = :fid WHERE id = :did"),
                {"fid": faculty_row, "did": dept_result},
            )
            # Promote user role to HOD
            await db.execute(
                text("UPDATE users SET role = 'hod' WHERE id = :uid"),
                {"uid": user_row},
            )
            await db.flush()
            assigned += 1

        except Exception as exc:
            await db.rollback()
            errors += 1
            if errors <= 5:
                print(f"    [WARN] HOD assignment failed ({email}): {exc}")

    await db.commit()
    wb.close()
    print(f"  HOD links    → assigned={assigned}, skipped={skipped}, errors={errors}")


# ---------------------------------------------------------------------------
# Step 3 — Students
# ---------------------------------------------------------------------------

async def seed_students(
    db: AsyncSession,
    institution_id: uuid.UUID,
    data_dir: Path,
    default_password: str,
    dept_map: dict[str, uuid.UUID],
) -> None:
    wb = openpyxl.load_workbook(data_dir / "students.xlsx", read_only=True, data_only=True)
    ws = wb.active
    headers = [str(c.value or "").strip() for c in next(ws.iter_rows(max_row=1))]

    def col(name: str):
        return headers.index(name) if name in headers else -1

    c_reg = col("Registration Id")
    c_name = col("Name")
    c_email = col("Email")
    c_phone = col("Phone Number")
    c_dept = col("Department")
    c_prog = col("Programme")
    c_batch = col("Batch Year")
    c_gender = col("Gender")

    created = skipped = errors = 0
    hashed = _hash(default_password)

    for row in ws.iter_rows(min_row=2, values_only=True):
        email = str(row[c_email] or "").strip().lower() if c_email >= 0 else ""
        if not email:
            continue

        try:
            existing_user = (await db.execute(
                select(User.id).where(User.email == email)
            )).scalar_one_or_none()
            if existing_user:
                skipped += 1
                continue

            enroll = _numeric_str(row[c_reg]) if c_reg >= 0 else None
            if enroll:
                existing_profile = (await db.execute(
                    select(StudentProfile.id).where(
                        StudentProfile.enrollment_number == enroll
                    )
                )).scalar_one_or_none()
                if existing_profile:
                    skipped += 1
                    continue

            name = _title_case(str(row[c_name] or "")) if c_name >= 0 else email
            phone = _normalize_phone(row[c_phone] if c_phone >= 0 else None)
            gender = _map_gender(str(row[c_gender] or "") if c_gender >= 0 else "")
            dept_name = str(row[c_dept] or "").strip() if c_dept >= 0 else ""
            dept_id = dept_map.get(dept_name)
            programme = str(row[c_prog] or "").strip() if c_prog >= 0 else ""
            batch_year_raw = row[c_batch] if c_batch >= 0 else None
            batch_year = int(float(str(batch_year_raw))) if batch_year_raw else 2022
            year_of_study, semester = _derive_year_and_semester(batch_year)
            degree_type = _parse_degree_type(programme)

            user = User(
                institution_id=institution_id,
                email=email,
                hashed_password=hashed,
                full_name=name,
                role=UserRole.STUDENT,
                department_id=dept_id,
                phone=phone,
                gender=gender,
                is_verified=True,
            )
            db.add(user)
            await db.flush()

            profile = StudentProfile(
                user_id=user.id,
                enrollment_number=enroll,
                degree_type=degree_type,
                program=programme,
                year_of_study=year_of_study,
                semester=semester,
            )
            db.add(profile)
            await db.flush()
            await db.commit()
            created += 1

        except Exception as exc:
            await db.rollback()
            errors += 1
            if errors <= 5:
                print(f"    [WARN] student row skipped ({email}): {exc}")

    wb.close()
    print(f"  Students     → created={created}, skipped={skipped}, errors={errors}")


# ---------------------------------------------------------------------------
# Step 4 — Rooms
# ---------------------------------------------------------------------------

async def seed_rooms(
    db: AsyncSession,
    institution_id: uuid.UUID,
    data_dir: Path,
) -> None:
    created = skipped = errors = 0

    with open(data_dir / "rooms.csv", newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            code = str(row.get("room_number", "")).strip()
            if not code:
                continue

            try:
                existing = (await db.execute(
                    select(Room.id).where(
                        Room.institution_id == institution_id,
                        Room.code == code,
                    )
                )).scalar_one_or_none()
                if existing:
                    skipped += 1
                    continue

                raw_cap = row.get("room_max_cap", "0")
                capacity = int(float(raw_cap)) if raw_cap else 0
                if capacity <= 0:
                    capacity = 30

                room_type = _map_room_type(row.get("room_type", ""))

                raw_room_type = str(row.get("room_type", "")).strip()

                tags: list[str] = []
                is_core_lab_room = raw_room_type == "Core-Lab"
                # Room-type identity tag — used by solver to match course requirements
                if is_core_lab_room:
                    tags.append("CORE_LAB")
                elif raw_room_type == "Laboratory":
                    tags.append("COMPUTER_LAB")
                # Projector / smart board / LCS only relevant for classrooms & computer labs
                if not is_core_lab_room:
                    if _parse_bool_col(row.get("has_projector")):
                        tags.append("PROJECTOR")
                    if _parse_bool_col(row.get("smart_board")):
                        tags.append("SMART_BOARD")
                    if _parse_bool_col(row.get("isLcsAvailable")):
                        tags.append("LCS_AVAILABLE")
                if _parse_bool_col(row.get("has_ac")):
                    tags.append("AC")
                if _parse_bool_col(row.get("green_board")):
                    tags.append("GREEN_BOARD")
                tech = str(row.get("tech_level", "")).strip().lower()
                if not is_core_lab_room:
                    if tech == "high-tech":
                        tags.append("HIGH_TECH")
                    elif tech == "mid-end":
                        tags.append("MID_TECH")
                    elif tech == "advanced":
                        tags.append("ADVANCED")
                    elif tech == "basic":
                        tags.append("BASIC")

                room = Room(
                    institution_id=institution_id,
                    code=code,
                    name=str(row.get("description", code)).strip() or code,
                    capacity=capacity,
                    room_type=room_type,
                    tags=tags or None,
                    building=str(row.get("block", "")).strip() or None,
                )
                db.add(room)
                await db.flush()
                await db.commit()
                created += 1

            except Exception as exc:
                await db.rollback()
                errors += 1
                if errors <= 5:
                    print(f"    [WARN] room row skipped ({code}): {exc}")

    print(f"  Rooms        → created={created}, skipped={skipped}, errors={errors}")


# ---------------------------------------------------------------------------
# Step 5 — Courses
# ---------------------------------------------------------------------------

async def seed_courses(
    db: AsyncSession,
    institution_id: uuid.UUID,
    data_dir: Path,
    dept_map: dict[str, uuid.UUID],
) -> None:
    """Seed courses from 24 dept xlsx files (primary), enriched with lab data from CSVs."""
    enrichment_by_code, enrichment_by_name = _load_csv_enrichment(data_dir)

    room_rows = (await db.execute(
        select(Room.code, Room.id).where(Room.institution_id == institution_id)
    )).all()
    room_code_map: dict[str, uuid.UUID] = {r.code: r.id for r in room_rows}

    db_depts = (await db.execute(
        select(Department.name, Department.id).where(Department.institution_id == institution_id)
    )).all()
    norm_map: dict[str, uuid.UUID] = {_normalize_dept_name(r.name): r.id for r in db_depts}
    norm_map.update({_normalize_dept_name(k): v for k, v in dept_map.items()})

    def _lookup_dept(name: str) -> uuid.UUID | None:
        return dept_map.get(name) or norm_map.get(_normalize_dept_name(name))

    course_dir = data_dir / "course"
    xlsx_files = sorted(course_dir.glob("*.xlsx"))
    created = skipped = errors = 0

    for xlsx_path in xlsx_files:
        # "Department of XYZ_Course_TIMESTAMP.xlsx" → "Department of XYZ"
        dept_name = xlsx_path.stem.split("_Course_")[0].strip()
        dept_id = _lookup_dept(dept_name)
        if dept_id is None:
            print(f"    [WARN] dept not resolved: {dept_name!r}")

        for cd in _parse_xlsx_courses(xlsx_path):
            code = cd["code"]
            try:
                existing = (await db.execute(
                    select(Course.id).where(
                        Course.institution_id == institution_id,
                        Course.code == code,
                    )
                )).scalar_one_or_none()
                if existing:
                    skipped += 1
                    continue

                lc = cd["lecture_credits"]
                tut = cd["tutorial_credits"]
                pc = cd["practical_credits"]
                tc = cd["total_credits"]

                # lecture / tutorial credits = h/week directly; practical credits × 2 = h/week
                lecture_weekly  = int(lc)
                tutorial_weekly = int(tut)
                practical_weekly = int(pc) * 2
                weekly_hours = lecture_weekly + tutorial_weekly + practical_weekly or 3

                if lc > 0 and pc > 0:
                    session_type = SessionType.BOTH
                elif pc > 0:
                    session_type = SessionType.LAB
                else:
                    session_type = SessionType.THEORY

                structure = (
                    {"L": lecture_weekly, "T": tutorial_weekly, "P": practical_weekly}
                    if (lc or tut or pc) else None
                )
                credits = int(tc) if tc > 0 else weekly_hours

                # Match by code first; fall back to normalised course name
                enr = (
                    enrichment_by_code.get(code)
                    or enrichment_by_name.get(_norm_course_name(cd["name"]))
                    or {}
                )
                required_room = str(enr.get("required_room_type") or "").strip()

                room_tags: list[str] = []
                is_core_lab = required_room.upper() in ("CORE-LAB", "CORE_LAB")
                if is_core_lab:
                    room_tags.append("CORE_LAB")
                elif required_room.upper() == "LAB":
                    room_tags.append("COMPUTER_LAB")

                lab_preferred_room_ids: list[str] | None = None
                if is_core_lab:
                    rnum = str(enr.get("room_number") or "").strip()
                    if rnum:
                        room_uuid = room_code_map.get(rnum)
                        if room_uuid:
                            lab_preferred_room_ids = [str(room_uuid)]
                        else:
                            print(f"    [WARN] course {code}: room {rnum!r} not found in DB")

                pe_ne = enr.get("pe/ne") or enr.get("pe") or enr.get("ne") or ""
                is_elective, elective_semester = _parse_pe_ne(pe_ne)

                db.add(Course(
                    institution_id=institution_id,
                    department_id=dept_id,
                    code=code,
                    name=cd["name"],
                    weekly_hours=weekly_hours,
                    session_type=session_type,
                    credits=credits,
                    structure=structure,
                    room_tags=room_tags or None,
                    lab_preferred_room_ids=lab_preferred_room_ids,
                    is_elective=is_elective,
                    elective_semester=elective_semester,
                ))
                await db.flush()
                await db.commit()
                created += 1

            except Exception as exc:
                await db.rollback()
                errors += 1
                if errors <= 5:
                    print(f"    [WARN] course {code} skipped: {exc}")

    print(f"  Courses      → created={created}, skipped={skipped}, errors={errors}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
# Reset helpers
# ---------------------------------------------------------------------------

async def reset_institution_data(db: AsyncSession, institution_id: uuid.UUID) -> None:
    """Delete all seeded data for the institution in FK-safe order."""
    iid = institution_id
    deleted: list[str] = []

    async def _del(label: str, stmt: str) -> None:
        try:
            r = await db.execute(text(stmt), {"iid": iid})
            n = r.rowcount
            if n:
                deleted.append(f"{label}={n}")
        except Exception as exc:
            await db.rollback()
            exc_name = type(exc).__name__
            # ProgrammingError = table not yet created (migration pending) — safe to skip
            if "ProgrammingError" in exc_name:
                pass  # silently skip missing tables
            else:
                print(f"    [SKIP] {label}: {exc_name}")

    print("  Resetting institution data...")

    # Phase 1: deepest derivatives
    scenario_sub = "(SELECT id FROM scenarios WHERE institution_id = :iid)"
    session_sub  = "(SELECT id FROM agent_sessions WHERE user_id IN (SELECT id FROM users WHERE institution_id = :iid))"

    await _del("job_conflicts",      f"DELETE FROM job_conflicts WHERE job_id IN (SELECT id FROM solver_jobs WHERE scenario_id IN {scenario_sub})")
    await _del("agent_messages",     f"DELETE FROM agent_messages WHERE session_id IN {session_sub}")
    await _del("scheduled_sessions", f"DELETE FROM scheduled_sessions WHERE scenario_id IN {scenario_sub}")

    # Phase 2: solver / agent / allocation
    await _del("solver_jobs",      f"DELETE FROM solver_jobs WHERE scenario_id IN {scenario_sub}")
    await _del("agent_sessions",    "DELETE FROM agent_sessions WHERE user_id IN (SELECT id FROM users WHERE institution_id = :iid)")
    await _del("allocation_rules", f"DELETE FROM allocation_rules WHERE scenario_id IN {scenario_sub}")
    await _del("scenario_rules",   f"DELETE FROM scenario_rules WHERE scenario_id IN {scenario_sub}")
    await _del("analytics_snapshots", "DELETE FROM analytics_snapshots WHERE institution_id = :iid")
    await _del("reservations",     "DELETE FROM reservations WHERE institution_id = :iid")

    # Phase 3: exam sub-tree
    exam_sub = "(SELECT id FROM exam_scenarios WHERE institution_id = :iid)"
    await _del("exam_slots",       f"DELETE FROM exam_slots WHERE exam_scenario_id IN {exam_sub}")
    await _del("exam_assignments", f"DELETE FROM exam_assignments WHERE exam_scenario_id IN {exam_sub}")
    await _del("exam_scenarios",    "DELETE FROM exam_scenarios WHERE institution_id = :iid")

    # Phase 4: curriculum / teaching sub-tree
    target_sub = "(SELECT id FROM scheduling_targets WHERE institution_id = :iid)"
    bucket_sub = "(SELECT id FROM offering_buckets WHERE institution_id = :iid)"
    await _del("target_course_demand", f"DELETE FROM target_course_demand WHERE scheduling_target_id IN {target_sub}")
    await _del("target_requirements",  f"DELETE FROM target_requirements WHERE scheduling_target_id IN {target_sub}")
    await _del("course_offerings",     f"DELETE FROM course_offerings WHERE offering_bucket_id IN {bucket_sub}")
    await _del("course_share_configs",  "DELETE FROM course_share_configs WHERE institution_id = :iid")
    await _del("teaching_assignments",  "DELETE FROM teaching_assignments WHERE institution_id = :iid")
    await _del("offering_buckets",      "DELETE FROM offering_buckets WHERE institution_id = :iid")
    await _del("scheduling_targets",    "DELETE FROM scheduling_targets WHERE institution_id = :iid")

    # Phase 5: scenarios (NULL self-ref parent first to avoid FK cycle)
    try:
        await db.execute(
            text("UPDATE scenarios SET parent_scenario_id = NULL WHERE institution_id = :iid"),
            {"iid": iid},
        )
    except Exception:
        await db.rollback()
    await _del("scenarios", "DELETE FROM scenarios WHERE institution_id = :iid")

    # Phase 6: notifications / audit / user profiles
    await _del("notifications",            "DELETE FROM notifications WHERE institution_id = :iid")
    await _del("notification_preferences", "DELETE FROM notification_preferences WHERE user_id IN (SELECT id FROM users WHERE institution_id = :iid)")
    await _del("audit_log",                "DELETE FROM audit_log WHERE institution_id = :iid")
    await _del("student_profiles",         "DELETE FROM student_profiles WHERE user_id IN (SELECT id FROM users WHERE institution_id = :iid)")

    # Phase 7: faculty + ALL users for this institution
    await _del("faculty", "DELETE FROM faculty WHERE institution_id = :iid")
    await _del("users",   "DELETE FROM users WHERE institution_id = :iid")

    # Phase 8: master data (time_grids before academic_terms — real FK)
    await _del("time_grids",      "DELETE FROM time_grids WHERE academic_term_id IN (SELECT id FROM academic_terms WHERE institution_id = :iid)")
    await _del("academic_terms",  "DELETE FROM academic_terms WHERE institution_id = :iid")
    await _del("courses",         "DELETE FROM courses WHERE institution_id = :iid")
    await _del("rooms",           "DELETE FROM rooms WHERE institution_id = :iid")
    await _del("departments",     "DELETE FROM departments WHERE institution_id = :iid")

    await db.commit()
    print(f"  Reset done: {', '.join(deleted) or '(nothing to delete)'}")


# ---------------------------------------------------------------------------
# Academic term seeding
# ---------------------------------------------------------------------------

_DEFAULT_TERM_NAME       = "Odd Semester 2025-26"
_DEFAULT_TERM_START_DATE = date(2025, 7, 1)
_DEFAULT_TERM_END_DATE   = date(2025, 11, 30)


async def seed_academic_term(
    db: AsyncSession,
    institution_id: uuid.UUID,
) -> uuid.UUID:
    """Create the default academic term for the institution (idempotent by name).

    Returns the term UUID — used to attach the time grid.
    """
    existing_id = (await db.execute(
        select(AcademicTerm.id).where(
            AcademicTerm.institution_id == institution_id,
            AcademicTerm.name == _DEFAULT_TERM_NAME,
        ).limit(1)
    )).scalar_one_or_none()

    if existing_id:
        print(f"    [SKIP] Academic term '{_DEFAULT_TERM_NAME}' already exists")
        return existing_id

    term = AcademicTerm(
        institution_id=institution_id,
        name=_DEFAULT_TERM_NAME,
        start_date=_DEFAULT_TERM_START_DATE,
        end_date=_DEFAULT_TERM_END_DATE,
        term_type=TermType.SEMESTER,
        status=AcademicTermStatus.ACTIVE,
        is_active=True,
    )
    db.add(term)
    await db.flush()
    await db.commit()
    print(f"    [OK]   Created academic term '{_DEFAULT_TERM_NAME}' → {term.id}")
    return term.id


# ---------------------------------------------------------------------------
# Admin user seeding
# ---------------------------------------------------------------------------

async def seed_time_grid(
    db: AsyncSession,
    term_id: uuid.UUID,
) -> None:
    """Create the standard REC 6-day time grid for a term (idempotent by name)."""
    grid_name = "Standard 6-Day Grid (REC)"

    existing = (await db.execute(
        select(TimeGrid.id).where(
            TimeGrid.academic_term_id == term_id,
            TimeGrid.name == grid_name,
        ).limit(1)
    )).scalar_one_or_none()

    if existing:
        print(f"    [SKIP] '{grid_name}' already exists for this term")
        return

    slots = _build_rec_slots()
    grid = TimeGrid(
        academic_term_id=term_id,
        name=grid_name,
        is_active=True,
        slots=slots,
    )
    db.add(grid)
    await db.flush()
    await db.commit()
    print(f"    [OK]   Created '{grid_name}' → {len(slots)} slots  "
          f"(6 days × 12 unified periods P1–P12)")


async def seed_admin_users(
    db: AsyncSession,
    institution_id: uuid.UUID,
    password: str,
) -> None:
    """Create admin accounts idempotently."""
    admins = [
        ("hursunss@gmail.com", "Exovance Admin"),
        ("admin@campus.edu.in", "Campus Admin"),
    ]
    hashed = _hash(password)
    created = skipped = 0

    for email, name in admins:
        existing = (await db.execute(
            select(User.id).where(User.email == email)
        )).scalar_one_or_none()

        if existing:
            skipped += 1
            print(f"    [SKIP] {email} (already exists)")
            continue

        user = User(
            institution_id=institution_id,
            email=email,
            hashed_password=hashed,
            full_name=name,
            role=UserRole.ADMIN,
            is_verified=True,
        )
        db.add(user)
        await db.flush()
        await db.commit()
        created += 1
        print(f"    [OK]   {email}")

    print(f"  Admins       → created={created}, skipped={skipped}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def run(
    institution_id: uuid.UUID,
    default_password: str,
    data_dir: Path,
    skip_faculty: bool,
    skip_students: bool,
    skip_rooms: bool,
    skip_courses: bool,
    reset: bool = False,
) -> None:
    engine = create_async_engine(settings.DATABASE_URL, echo=False)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    print(f"\nSeed master data → institution={institution_id}")
    print(f"  data_dir: {data_dir.resolve()}")
    print()

    # Step 0: ensure institution row exists
    async with async_session() as db:
        print("[0] Institution...")
        await seed_institution(db, institution_id)

    # Optional reset: wipe all seeded data under the institution
    if reset:
        async with async_session() as db:
            print("\n[reset] Clearing existing institution data...")
            await reset_institution_data(db, institution_id)
        print()

    # Step 0b: academic term — must exist before time grid and scenarios
    async with async_session() as db:
        print("[0b] Academic term...")
        term_id = await seed_academic_term(db, institution_id)

    # Collect department names synchronously (openpyxl is sync)
    print("\nScanning department names from xlsx files...")
    student_depts, faculty_only_depts = _collect_dept_names(data_dir)
    print(f"  {len(student_depts)} academic depts, {len(faculty_only_depts)} service depts")

    async with async_session() as db:
        print("\n[1/6] Departments...")
        dept_map = await seed_departments(db, institution_id, student_depts, faculty_only_depts)

    if not skip_faculty:
        async with async_session() as db:
            print("\n[2/6] Faculty...")
            await seed_faculty(db, institution_id, data_dir, default_password, dept_map)
        async with async_session() as db:
            print("      HOD assignments...")
            await seed_hod_assignments(db, institution_id, data_dir)
    else:
        print("\n[2/6] Faculty... SKIPPED")

    if not skip_students:
        async with async_session() as db:
            print("\n[3/6] Students...")
            await seed_students(db, institution_id, data_dir, default_password, dept_map)
    else:
        print("\n[3/6] Students... SKIPPED")

    if not skip_rooms:
        async with async_session() as db:
            print("\n[4/6] Rooms...")
            await seed_rooms(db, institution_id, data_dir)
    else:
        print("\n[4/6] Rooms... SKIPPED")

    if not skip_courses:
        async with async_session() as db:
            print("\n[5/6] Courses...")
            await seed_courses(db, institution_id, data_dir, dept_map)
    else:
        print("\n[5/6] Courses... SKIPPED")

    async with async_session() as db:
        print("\n[6/6] Admin users...")
        await seed_admin_users(db, institution_id, default_password)

    async with async_session() as db:
        print("\n[+] Time grid...")
        await seed_time_grid(db, term_id)

    await engine.dispose()
    print("\nSeed complete.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed master data for an institution.")
    parser.add_argument("--institution-id", required=True, type=uuid.UUID)
    parser.add_argument("--default-password", default="DefaultPassword@123")
    parser.add_argument("--data-dir", default="scripts/data", type=Path)
    parser.add_argument("--reset", action="store_true",
                        help="Delete ALL institution data before seeding (admin accounts are re-created by step 6)")
    parser.add_argument("--skip-faculty", action="store_true")
    parser.add_argument("--skip-students", action="store_true")
    parser.add_argument("--skip-rooms", action="store_true")
    parser.add_argument("--skip-courses", action="store_true")
    args = parser.parse_args()

    asyncio.run(
        run(
            institution_id=args.institution_id,
            default_password=args.default_password,
            data_dir=args.data_dir,
            skip_faculty=args.skip_faculty,
            skip_students=args.skip_students,
            skip_rooms=args.skip_rooms,
            skip_courses=args.skip_courses,
            reset=args.reset,
        )
    )


if __name__ == "__main__":
    main()
