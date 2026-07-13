"""
reimport_all.py
===============
Full reimport: wipes + rebuilds the entire session/cohort/pool structure
for the given scenario from the two legacy CSV files.

Order:
  0. WIPE:    scheduled_sessions → offering_buckets (cascade) → scheduling_targets COHORT
  1. ENTITIES: rooms / faculty / courses / PE-OE TAs  (idempotent)
  2. IMPORT:   sessions from lab + theory CSV
  3. COHORTS:  OfferingBuckets + CourseOfferings from grouping_telemetry.json
  4. PE/OE:    CHOOSE_COURSE pool buckets per dept/sem → TRs to cohort targets
  5. FIX:      Supplementary buckets for sessions still NULL after step 3+4

Usage (from backend/):
    python -X utf8 scripts/reimport_all.py
    python -X utf8 scripts/reimport_all.py --dry-run
    python -X utf8 scripts/reimport_all.py --scenario-id <uuid>
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import os
import re
import sys
import uuid
from collections import Counter, defaultdict
from pathlib import Path

import pandas as pd
try:
    import psycopg2
    import psycopg2.extras
    _PSYCOPG_VER = 2
except ModuleNotFoundError:
    import psycopg  # type: ignore[import]
    import psycopg.rows  # type: ignore[import]
    _PSYCOPG_VER = 3


def _execute_values(cur, sql: str, rows: list, template: str | None = None) -> None:
    """Compatibility shim for psycopg2.extras.execute_values on both psycopg2 and psycopg3."""
    if _PSYCOPG_VER == 2:
        psycopg2.extras.execute_values(cur, sql, rows, template=template)  # type: ignore[name-defined]
    else:
        # psycopg3: rewrite VALUES %s with individual placeholders and executemany.
        # PostgreSQL caps a single query at 65535 parameters — one big multi-row
        # INSERT with every row flattened into one param list blows past that for
        # any row count beyond ~65535/num_columns (e.g. 9362 rows for a 7-column
        # table). Chunk into batches sized to stay safely under the limit
        # regardless of how many columns this particular INSERT has.
        if not rows:
            return
        num_cols = len(rows[0])
        max_rows_per_batch = max(1, 60_000 // num_cols)  # headroom under 65535
        placeholders = template if template else f"({','.join(['%s'] * num_cols)})"
        for start in range(0, len(rows), max_rows_per_batch):
            batch = rows[start:start + max_rows_per_batch]
            flat: list = []
            value_placeholders: list[str] = []
            for row in batch:
                value_placeholders.append(placeholders)
                flat.extend(row)
            stmt = sql.replace("VALUES %s", "VALUES " + ", ".join(value_placeholders))
            cur.execute(stmt, flat)

# ── Paths ──────────────────────────────────────────────────────────────────────
SCRIPT_DIR  = Path(__file__).parent.resolve()
BACKEND_DIR = SCRIPT_DIR.parent
_SRC_DIR    = BACKEND_DIR / "src"
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

import importlib.util

_cse_s7_spec = importlib.util.spec_from_file_location(
    "cse_s7_per_group_pe",
    _SRC_DIR / "app" / "services" / "cse_s7_per_group_pe.py",
)
_cse_s7 = importlib.util.module_from_spec(_cse_s7_spec)
assert _cse_s7_spec.loader is not None
_cse_s7_spec.loader.exec_module(_cse_s7)
is_cse_s7_per_group_pe_pool = _cse_s7.is_cse_s7_per_group_pe_pool
CSE_LEGACY_DEPT_NAME = _cse_s7.CSE_LEGACY_DEPT_NAME
CSE_S7_PER_GROUP_PE_GENERAL_CODES = _cse_s7.CSE_S7_PER_GROUP_PE_GENERAL_CODES
CSE_S7_STUDY_SEMESTER = _cse_s7.CSE_S7_STUDY_SEMESTER

SEEDS_DIR   = BACKEND_DIR / "data" / "legacy_seeds"

LAB_CSV           = SEEDS_DIR / "lab_schedule_final_done.csv"
THEORY_CSV        = SEEDS_DIR / "theory_schedule_final_done.csv"
PE_COURSE_MAP_CSV = SEEDS_DIR / "pe_course_map.csv"
ELIGIBILITY_BACKUP_CSV = SEEDS_DIR / "student_course_eligibility_backup.csv"

# Telemetry JSON from the legacy course group optimizer (groups labs by dept/sem)
TELEMETRY_FILES = [
    SEEDS_DIR / "grouping_telemetry.json",
    SCRIPT_DIR / "grouping_telemetry.json",
]
# Override with env var for dev machines with a different output path
if os.environ.get("TELEMETRY_PATH"):
    TELEMETRY_FILES = [Path(os.environ["TELEMETRY_PATH"])]

DEFAULT_SCENARIO: str | None = None  # auto-detected from DB at runtime

BCRYPT_PLACEHOLDER = "$2b$12$PLACEHOLDER_SEEDED_USER_DO_NOT_LOGIN_xxxxxxxxxxxxxxxxxxxxxxxx"

# ── Slot / time definitions (matches legacy scheduler config) ─────────────────
THEORY_TIMES: list[tuple[str, str]] = [
    ("08:00", "08:50"), ("09:00", "09:50"), ("10:00", "10:50"),
    ("11:00", "11:50"), ("12:00", "12:50"), ("13:20", "14:10"),
    ("14:10", "15:00"), ("15:00", "15:50"), ("16:00", "16:50"),
    ("17:00", "17:50"), ("18:00", "18:50"),
]
LAB_TIMES: dict[str, tuple[str, str]] = {
    "L1": ("08:00", "09:40"), "L2": ("10:00", "11:40"),
    "L3": ("11:50", "13:20"), "L4": ("13:20", "15:00"),
    "L5": ("15:00", "16:40"), "L6": ("17:00", "18:40"),
}
CANONICAL_DAYS = ["MON", "TUE", "WED", "THU", "FRI", "SAT"]
_DAY_ABBR: dict[str, str] = {
    "monday": "MON", "tuesday": "TUE", "wednesday": "WED", "wed": "WED",
    "thursday": "THU", "thur": "THU", "friday": "FRI", "fri": "FRI",
    "saturday": "SAT",
}

# ── Dept name mapping ─────────────────────────────────────────────────────────
LEGACY_TO_DB_FRAGMENT: dict[str, str] = {
    "Aeronautical Engineering":                         "Aeronautical",
    "Artificial Intelligence & Data Science":           "Artificial Intelligence and Data Science",
    "Artificial Intelligence & Machine Learning":       "Artificial Intelligence and Machine Learning",
    "Automobile Engineering":                           "Automobile Engineering",
    "Biomedical Engineering":                           "Biomedical Engineering",
    "Biotechnology":                                    "Biotechnology",
    "Chemical Engineering":                             "Chemical Engineering",
    "Civil Engineering":                                "Civil Engineering",
    "Computer Science & Business Systems":              "Computer Science and Business Systems",
    "Computer Science & Design":                        "Computer Science and Design",
    "Computer Science & Engineering":                   'Computer Science and Engineering"',  # exact-end trick
    "Computer Science & Engineering (Cyber Security)":  "Cyber Security",
    "Electrical & Electronics Engineering":             "Electrical and Electronics",
    "Electronics & Communication Engineering":          "Electronics and Communication",
    "Food Technology":                                  "Food Technology",
    "Information Technology":                           "Information Technology",
    "Mechanical Engineering":                           "Mechanical Engineering",
    "Mechatronics Engineering":                         "Mechatronics",
    "Robotics & Automation":                            "Robotics",
}

_SKIP_TEACHERS = {
    "unknown teacher", "new faculty", "", "nan", "unassigned-ms",
    "new faculty 2", "nf1 nan", "nf2 nan",
}


def _normalize_faculty_name(name: str) -> str:
    """Strip title prefixes (Dr., Prof., Mr., Ms.) and normalize whitespace."""
    n = re.sub(r'^(Dr\.?\s*|Prof\.?\s*|Mr\.?\s*|Ms\.?\s*|Mrs\.?\s*)+', '', name.strip(), flags=re.I)
    return re.sub(r'\s+', ' ', n).lower().strip()


def _normalize_staff_code(raw) -> str:
    """Canonicalize a staff_code so '101345.0' (pandas float-string, as written
    by lab_schedule.csv) and '101345' (plain string, as written by
    theory_schedule.csv) resolve to the SAME faculty instead of splitting one
    teacher into two faculty rows."""
    s = str(raw or "").strip()
    if not s or s.lower() == "nan":
        return ""
    try:
        f = float(s)
        if f.is_integer():
            return str(int(f))
    except ValueError:
        pass
    return s.lower()


def _build_fac_by_norm(rows: list) -> dict[str, str]:
    """Build normalized-name → faculty_id lookup from DB faculty rows."""
    result: dict[str, str] = {}
    for r in rows:
        if r["name"]:
            result[_normalize_faculty_name(r["name"])] = str(r["id"])
    return result


def _resolve_faculty_id(
    teacher: str,
    scode: str,
    *,
    fac_by_code: dict[str, str],
    fac_by_name: dict[str, str],
    fac_by_norm: dict[str, str] | None = None,
) -> str | None:
    """Resolve faculty by staff_code, exact name, normalized name (Dr./Prof. stripped),
    or legacy swapped CSV columns."""
    teacher_k = teacher.strip().lower()
    scode_k = _normalize_staff_code(scode)
    if not teacher_k and not scode_k:
        return None
    result = (
        fac_by_code.get(scode_k)
        or fac_by_name.get(teacher_k)
        or fac_by_name.get(scode_k)  # staff_code column sometimes holds display name
    )
    if result or fac_by_norm is None:
        return result
    # Fallback: strip Dr./Prof. prefix and try again
    return (
        fac_by_norm.get(_normalize_faculty_name(teacher))
        or fac_by_norm.get(_normalize_faculty_name(scode))
    )

_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _get_redis_url() -> str:
    """Read CELERY_BROKER_URL (Redis) from .env or environment."""
    env = BACKEND_DIR / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            for key in ("CELERY_BROKER_URL=", "REDIS_URL="):
                if line.startswith(key):
                    return line.split("=", 1)[1].strip()
    return os.getenv("CELERY_BROKER_URL", os.getenv("REDIS_URL", "redis://localhost:6379/0"))


def _flush_offering_seats_cache(dry_run: bool) -> int:
    """Delete all offering:seats:*, selection:menu:*, and selection:cohort_seats:* keys from Redis.

    After a reimport every offering UUID is regenerated, so any cached seat
    counters, selection menus, and cohort-seat caches are stale and must be wiped.
    Returns the number of keys deleted.
    """
    try:
        import redis as _redis
        r = _redis.from_url(_get_redis_url(), decode_responses=True)
        patterns = ["offering:seats:*", "selection:menu:*", "selection:cohort_seats:*"]
        all_keys = []
        for pattern in patterns:
            keys = r.keys(pattern)
            if keys:
                all_keys.extend(keys)
        if not all_keys:
            r.close()
            return 0
        if not dry_run:
            # Delete in chunks to be safe if there are many keys
            chunk_size = 1000
            for i in range(0, len(all_keys), chunk_size):
                chunk = all_keys[i:i+chunk_size]
                r.delete(*chunk)
        r.close()
        return len(all_keys)
    except Exception as exc:
        print(f"  [WARN] Redis flush skipped: {exc}")
        return 0


def _get_dsn() -> str:
    db_url: str | None = None
    env = BACKEND_DIR / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            if line.startswith("DATABASE_URL="):
                db_url = line.split("=", 1)[1].strip()
                break
    db_url = db_url or os.getenv("DATABASE_URL", "")
    dsn = db_url.replace("postgresql+asyncpg://", "postgresql://").replace("postgresql+psycopg2://", "postgresql://")
    if not dsn:
        sys.exit("DATABASE_URL not found")
    return dsn


def _is_blank(val) -> bool:
    return val is None or (isinstance(val, float) and str(val) == "nan") or str(val).strip() in ("", "nan", "NaN")


def _is_uuid(s: str) -> bool:
    return bool(_UUID_RE.match(s))


def _day_abbr(day: str) -> str:
    return _DAY_ABBR.get(str(day).lower().strip(), str(day).upper()[:3])


def build_dept_id_map(cur) -> dict[str, str]:
    cur.execute("SELECT id::text, name FROM departments ORDER BY name")
    db_depts = cur.fetchall()
    result: dict[str, str] = {}
    for legacy_name, fragment in LEGACY_TO_DB_FRAGMENT.items():
        frag = fragment.rstrip('"')
        exact_end = fragment.endswith('"')
        matches = [
            r for r in db_depts
            if (r["name"].endswith(frag) if exact_end else frag.lower() in r["name"].lower())
        ]
        if len(matches) == 1:
            result[legacy_name] = matches[0]["id"]
        elif len(matches) == 0:
            print(f"  [WARN] No dept match for '{legacy_name}'")
        else:
            best = min(matches, key=lambda r: len(r["name"]))
            result[legacy_name] = best["id"]
    return result


# General PE pool code in schedule CSV, e.g. AE23PE31, CS23PE32, EC23PE32
_PE_GENERAL_CODE_RE = re.compile(r'^[A-Z]{2,4}\d{2}PE\d+$', re.IGNORECASE)

# pe_course_map.csv DEPT column → legacy department name in schedule CSV
PE_DEPT_ABBR_TO_LEGACY: dict[str, str] = {
    "AERO": "Aeronautical Engineering",
    "AIDS": "Artificial Intelligence & Data Science",
    "AIML": "Artificial Intelligence & Machine Learning",
    "AUTO": "Automobile Engineering",
    "BME": "Biomedical Engineering",
    "BT": "Biotechnology",
    "CHEM": "Chemical Engineering",
    "CIVIL": "Civil Engineering",
    "CSBS": "Computer Science & Business Systems",
    "CSD": "Computer Science & Design",
    "CSE": "Computer Science & Engineering",
    "CSECS": "Computer Science & Engineering (Cyber Security)",
    "EEE": "Electrical & Electronics Engineering",
    "ECE": "Electronics & Communication Engineering",
    "FT": "Food Technology",
    "IT": "Information Technology",
    "MECH": "Mechanical Engineering",
    "MCT": "Mechatronics Engineering",
    "RA": "Robotics & Automation",
}

_PE_MAP_SLOT_COLS = ("PE1", "PE2", "PE3", "PE4", "PE5")
_PE_MAP_SUBJECT_COLS = ("PE1_SUBJECT", "PE2_SUBJECT", "PE3_SUBJECT", "PE4_SUBJECT", "PE5_SUBJECT")


def _elective_type(code: str, pe_slot_codes: set[str] | None = None) -> str | None:
    cu = code.upper()
    if "PE" in cu:
        return "PROFESSIONAL"
    if "OE" in cu:
        return "OPEN"
    # Slot codes listed explicitly in pe_course_map.csv (e.g. CS23A31, IT23D11).
    # Using the CSV as ground truth avoids false positives from any regex heuristic.
    if pe_slot_codes and cu in pe_slot_codes:
        return "PROFESSIONAL"
    return None



def _is_pe_general_code(code: str) -> bool:
    return bool(_PE_GENERAL_CODE_RE.match(code.strip().upper()))


def _normalize_subject_name(name: str) -> str:
    return re.sub(r'\s+', ' ', name.strip().lower())


def load_pe_course_map() -> tuple[
    dict[tuple[str, int, str], dict],
    dict[str, tuple[str, int, str]],
]:
    """Load pe_course_map.csv.

    Returns:
        pools: (legacy_dept, sem, general_code) → {general_code, dept_abbr, sem, slot_codes}
        slot_to_pool: slot course code → (legacy_dept, sem, general_code)
    """
    pools: dict[tuple[str, int, str], dict] = {}
    slot_to_pool: dict[str, tuple[str, int, str]] = {}
    if not PE_COURSE_MAP_CSV.exists():
        print(f"  [WARN] PE course map not found: {PE_COURSE_MAP_CSV}")
        return pools, slot_to_pool

    df = pd.read_csv(PE_COURSE_MAP_CSV)
    df.columns = [str(c).strip().upper() for c in df.columns]
    seen_rows: set[tuple[str, int, str]] = set()

    for _, row in df.iterrows():
        general = str(row.get("GENERAL CODE") or row.get("GENERAL_CODE") or "").strip().upper()
        if not general:
            continue
        dept_abbr = str(row.get("DEPT") or "").strip().upper()
        legacy_dept = PE_DEPT_ABBR_TO_LEGACY.get(dept_abbr)
        if not legacy_dept:
            print(f"  [WARN] Unknown PE map dept abbr '{dept_abbr}' for {general}")
            continue
        sem_raw = row.get("SEM")
        if _is_blank(sem_raw):
            continue
        sem = int(float(sem_raw))
        row_key = (legacy_dept, sem, general)
        if row_key in seen_rows:
            continue
        seen_rows.add(row_key)

        slot_codes: list[str] = []
        slot_subjects: list[str] = []
        for slot_col, subject_col in zip(_PE_MAP_SLOT_COLS, _PE_MAP_SUBJECT_COLS):
            raw = row.get(slot_col)
            if _is_blank(raw):
                continue
            slot = str(raw).strip().upper()
            if slot:
                slot_codes.append(slot)
                slot_to_pool[slot] = row_key
                subj_raw = row.get(subject_col)
                slot_subjects.append(
                    str(subj_raw).strip() if not _is_blank(subj_raw) else ""
                )

        per_group_raw = row.get("PER_GROUP")
        if _is_blank(per_group_raw):
            per_group = False
        else:
            raw_pg = str(per_group_raw).strip().lower()
            try:
                per_group = int(float(raw_pg)) == 1
            except ValueError:
                per_group = raw_pg in ("true", "yes", "y")

        pools[row_key] = {
            "general_code": general,
            "dept_abbr": dept_abbr,
            "legacy_dept": legacy_dept,
            "sem": sem,
            "slot_codes": slot_codes,
            "slot_subjects": slot_subjects,
            "per_group": per_group,
        }

    print(f"  PE course map: {len(pools)} pools, {len(slot_to_pool)} slot codes")
    return pools, slot_to_pool


def _subject_matches_catalog(subject_norm: str, catalog_name: str) -> bool:
    cat_norm = _normalize_subject_name(catalog_name)
    if not cat_norm:
        return False
    return cat_norm == subject_norm or cat_norm in subject_norm or subject_norm in cat_norm


def build_pe_name_to_slot_maps(
    lab_df: pd.DataFrame,
    theory_df: pd.DataFrame,
    pe_pools: dict[tuple[str, int, str], dict],
    slot_course_names: dict[str, str] | None = None,
) -> dict[tuple[str, int, str], list[tuple[str, str]]]:
    """Map schedule subject names → PE slot codes per pool (ordered pairs)."""
    slot_course_names = slot_course_names or {}
    name_maps: dict[tuple[str, int, str], list[tuple[str, str]]] = {}
    for pool_key, pool in pe_pools.items():
        legacy_dept, sem, general = pool_key
        slot_codes: list[str] = pool["slot_codes"]
        if not slot_codes:
            continue

        norm_to_slot: dict[str, str] = {}
        mapped_slots: set[str] = set()

        # Explicit PE1_SUBJECT… columns in pe_course_map.csv (highest priority).
        for slot, subject in zip(slot_codes, pool.get("slot_subjects") or []):
            if not subject:
                continue
            norm = _normalize_subject_name(subject)
            if norm and slot not in mapped_slots:
                norm_to_slot[norm] = slot
                mapped_slots.add(slot)

        # Rows already coded with slot course codes in the schedule CSV.
        for df in (theory_df, lab_df):
            for _, r in df.iterrows():
                code = str(r.get("course_code") or "").strip().upper()
                if code not in slot_codes:
                    continue
                dept = str(r.get("department") or "").strip()
                if dept != legacy_dept:
                    continue
                sem_raw = r.get("semester")
                row_sem = int(float(sem_raw)) if not _is_blank(sem_raw) else None
                if row_sem != sem:
                    continue
                raw_name = str(r.get("course_name") or "").strip()
                norm = _normalize_subject_name(raw_name)
                if norm and code not in mapped_slots:
                    norm_to_slot[norm] = code
                    mapped_slots.add(code)

        seen_norm: set[str] = set()
        general_subjects: list[str] = []
        for df in (theory_df, lab_df):
            for _, r in df.iterrows():
                code = str(r.get("course_code") or "").strip().upper()
                if code != general:
                    continue
                dept = str(r.get("department") or "").strip()
                if dept != legacy_dept:
                    continue
                sem_raw = r.get("semester")
                row_sem = int(float(sem_raw)) if not _is_blank(sem_raw) else None
                if row_sem != sem:
                    continue
                raw_name = str(r.get("course_name") or "").strip()
                norm = _normalize_subject_name(raw_name)
                if norm and norm not in seen_norm:
                    seen_norm.add(norm)
                    general_subjects.append(raw_name)

        # Match remaining subjects using course-catalog names for slot codes.
        for raw_name in general_subjects:
            norm = _normalize_subject_name(raw_name)
            if norm in norm_to_slot:
                continue
            for slot in slot_codes:
                if slot in mapped_slots:
                    continue
                if _subject_matches_catalog(norm, slot_course_names.get(slot, "")):
                    norm_to_slot[norm] = slot
                    mapped_slots.add(slot)
                    break

        unmapped_subjects = [
            s for s in general_subjects
            if _normalize_subject_name(s) not in norm_to_slot
        ]
        unmapped_slots = [s for s in slot_codes if s not in mapped_slots]
        if unmapped_subjects and unmapped_slots:
            if len(unmapped_subjects) == len(unmapped_slots):
                print(
                    f"  [WARN] PE pool {general} S{sem}: subject→slot matched by "
                    f"CSV order fallback — add PE*_SUBJECT columns to pe_course_map.csv"
                )
                for raw_name, slot in zip(unmapped_subjects, unmapped_slots):
                    norm_to_slot[_normalize_subject_name(raw_name)] = slot
                    mapped_slots.add(slot)
            else:
                print(
                    f"  [WARN] PE pool {general} S{sem}: could not map subjects "
                    f"{unmapped_subjects!r} to slots {unmapped_slots!r}"
                )

        pairs: list[tuple[str, str]] = []
        seen_pair_norm: set[str] = set()
        for raw_name in general_subjects:
            norm = _normalize_subject_name(raw_name)
            slot = norm_to_slot.get(norm)
            if slot and norm not in seen_pair_norm:
                pairs.append((raw_name, slot))
                seen_pair_norm.add(norm)
        name_maps[pool_key] = pairs

    return name_maps


def _load_slot_course_names(
    cur,
    inst_id: str,
    pe_pools: dict[tuple[str, int, str], dict],
) -> dict[str, str]:
    """Load catalog display names for PE slot codes already in the courses table."""
    slot_codes = {
        slot
        for pool in pe_pools.values()
        for slot in pool["slot_codes"]
    }
    if not slot_codes:
        return {}
    cur.execute(
        """SELECT code, name FROM courses
           WHERE institution_id = %s::uuid AND upper(code) = ANY(%s)""",
        (inst_id, [c.upper() for c in slot_codes]),
    )
    return {
        str(r["code"]).strip().upper(): str(r["name"] or "")
        for r in cur.fetchall()
    }


def _resolve_pe_pool_key(
    code: str,
    dept: str,
    sem: int,
    pe_pools: dict[tuple[str, int, str], dict],
    slot_to_pool: dict[str, tuple[str, int, str]],
) -> tuple[str, int, str] | None:
    """Return (legacy_dept, sem, general_code) pool key for a PE schedule row."""
    cu = code.strip().upper()
    if _is_pe_general_code(cu):
        key = (dept, sem, cu)
        return key if key in pe_pools else None
    pool_key = slot_to_pool.get(cu)
    if pool_key and pool_key[0] == dept and pool_key[1] == sem:
        return pool_key
    return None


def _group_suffix(group_name: str) -> str:
    """'Chemical Engineering_S5_G8' → 'G8'."""
    parts = group_name.strip().split("_")
    return parts[-1] if parts else group_name.strip()


def _cohort_group_number(group_name: str) -> int | None:
    """Parse trailing cohort index from group_name, e.g. '..._G8' → 8."""
    m = re.search(r'_G(\d+)\s*$', group_name.strip(), re.IGNORECASE)
    if not m:
        return None
    parsed = int(m.group(1))
    return parsed if parsed > 0 else None


def _ta_id_from_row(r) -> str:
    """Normalize course_instance_id from a CSV row to session_id prefix."""
    raw = r.get("course_instance_id")
    if _is_blank(raw):
        return ""
    raw_str = str(raw).strip()
    if _is_uuid(raw_str):
        return raw_str
    return str(int(float(raw_str)))


def _max_seats_from_row(r, is_lab: bool) -> int | None:
    """Derive per-offering seat cap from legacy CSV columns.

    Lab rows: ``capacity`` (e.g. 140) or ``capacity_info`` ``66/140``.
    Theory rows: ``capacity_info`` ``66/70`` (max after slash).

    Oversized-room correction: when capacity_info is ``student_count/room_cap``
    and the section fills less than 55 % of the room (room_cap >= 100), the
    big room is an artifact of room assignment, not a real doubling of seats.
    In that case use student_count rounded up to the nearest 10 instead of
    the raw room capacity.  e.g. ``62/140`` → 70 (not 140).
    """
    cap_info = str(r.get("capacity_info") or "").strip()
    if cap_info and "/" in cap_info:
        try:
            parts = cap_info.rsplit("/", 1)
            sc = int(float(parts[0].strip()))
            mx = int(float(parts[1].strip()))
            if mx > 0:
                if sc > 0 and mx >= 100 and sc / mx < 0.55:
                    # Room is clearly oversized — round student count up to nearest 10
                    return math.ceil(sc / 10) * 10
                return mx
        except (ValueError, IndexError):
            pass
    if is_lab:
        raw = r.get("capacity")
        if not _is_blank(raw):
            v = int(float(raw))
            if v > 0:
                return v
    return None

# ═══════════════════════════════════════════════════════════════════════════════
# ═══════════════════════════════════════════════════════════════════════════════
# BACKUP & RESTORE STUDENT ELIGIBILITY
# ═══════════════════════════════════════════════════════════════════════════════

def backup_student_course_eligibility_to_csv(cur, term_id: str, csv_path: Path) -> int:
    """Backup student PE/OE course allocations to a CSV file."""
    print(f"\n── Backing up Student Eligibility to CSV ─────────────────────────")
    cur.execute("""
        SELECT
            sp.enrollment_number,
            u.email,
            c.code AS course_code,
            sce.study_semester,
            sce.source,
            sce.department_id::text AS department_id
        FROM student_course_eligibility sce
        JOIN student_profiles sp ON sp.id = sce.student_id
        JOIN users u ON u.id = sp.user_id
        JOIN courses c ON c.id = sce.course_id
        WHERE sce.academic_term_id = %s
    """, (term_id,))
    rows = cur.fetchall()
    
    # Ensure directory exists
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    
    with open(csv_path, mode="w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["enrollment_number", "email", "course_code", "study_semester", "source", "department_id"])
        for r in rows:
            writer.writerow([
                r["enrollment_number"] or "",
                r["email"] or "",
                r["course_code"] or "",
                r["study_semester"],
                r["source"],
                r["department_id"]
            ])
            
    print(f"  Backed up {len(rows)} student eligibility records to {csv_path.name}")
    return len(rows)


def restore_student_course_eligibility_from_csv(cur, term_id: str, csv_path: Path, dry_run: bool) -> None:
    """Restore student PE/OE course allocations from a CSV file."""
    print(f"\n── Restoring Student Eligibility from CSV ────────────────────────")
    if not csv_path.exists():
        print(f"  [WARN] Backup CSV file not found: {csv_path}")
        return

    # Read CSV
    backup_rows = []
    with open(csv_path, mode="r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for r in reader:
            backup_rows.append(r)

    if not backup_rows:
        print("  No student course eligibility records found in backup CSV.")
        return

    if dry_run:
        print(f"  (dry) Would restore {len(backup_rows)} student eligibility records")
        return

    # Fetch mapping of email -> student_profile.id
    cur.execute("""
        SELECT u.email, sp.id::text AS student_id
        FROM student_profiles sp
        JOIN users u ON u.id = sp.user_id
    """)
    email_to_student_id = {r["email"].lower(): r["student_id"] for r in cur.fetchall()}

    # Fetch mapping of course_code -> course.id
    cur.execute("SELECT code, id::text AS course_id FROM courses")
    code_to_course_id = {r["code"].strip().upper(): r["course_id"] for r in cur.fetchall()}

    rows_to_insert = []
    skipped_students = 0
    skipped_courses = 0

    for row in backup_rows:
        email = row["email"].lower()
        course_code = row["course_code"].strip().upper()
        
        student_id = email_to_student_id.get(email)
        course_id = code_to_course_id.get(course_code)
        
        if not student_id:
            skipped_students += 1
            continue
        if not course_id:
            skipped_courses += 1
            continue

        rows_to_insert.append((
            str(uuid.uuid4()),
            student_id,
            course_id,
            term_id,
            row["department_id"],
            int(row["study_semester"]),
            row["source"]
        ))

    if skipped_students:
        print(f"  [WARN] Skipped {skipped_students} records due to missing student profiles")
    if skipped_courses:
        print(f"  [WARN] Skipped {skipped_courses} records due to missing courses")

    if rows_to_insert:
        _execute_values(
            cur,
            """INSERT INTO student_course_eligibility (
                id, student_id, course_id, academic_term_id, department_id, study_semester, source
            ) VALUES %s
            ON CONFLICT ON CONSTRAINT uq_student_course_eligibility_scope DO NOTHING""",
            rows_to_insert
        )
        print(f"  Restored {len(rows_to_insert)} student eligibility records")


# STEP 0 — WIPE
# ═══════════════════════════════════════════════════════════════════════════════

def step0_wipe(cur, scenario_id: str, term_id: str, dry_run: bool) -> None:
    print("\n── Step 0: WIPE ───────────────────────────────────────────────────")

    if dry_run:
        cur.execute("SELECT COUNT(*) FROM scheduled_sessions WHERE scenario_id = %s", (scenario_id,))
        n = cur.fetchone()["count"]
        cur.execute("SELECT COUNT(*) FROM offering_buckets WHERE scenario_id = %s", (scenario_id,))
        nb = cur.fetchone()["count"]
        cur.execute(
            "SELECT COUNT(*) FROM scheduling_targets WHERE academic_term_id = %s AND target_type='COHORT'",
            (term_id,)
        )
        nt = cur.fetchone()["count"]
        cur.execute(
            "SELECT COUNT(*) FROM student_group_selections WHERE academic_term_id = %s",
            (term_id,)
        )
        ns = cur.fetchone()["count"]
        cur.execute(
            "SELECT COUNT(*) FROM elective_pools WHERE academic_term_id = %s",
            (term_id,)
        )
        nep = cur.fetchone()["count"]
        cur.execute(
            "SELECT COUNT(*) FROM student_course_eligibility WHERE academic_term_id = %s",
            (term_id,)
        )
        ne = cur.fetchone()["count"]
        nr = _flush_offering_seats_cache(dry_run=True)
        print(f"  (dry) Would delete: {n} sessions, {nb} offering_buckets, {nt} COHORT targets, "
              f"{ns} student selections, {nep} elective_pools, {ne} student eligibility rows, {nr} Redis seat keys")
        return

    # 0a: NULL offering_id to avoid FK violations before bucket delete
    cur.execute(
        "UPDATE scheduled_sessions SET offering_id = NULL WHERE scenario_id = %s", (scenario_id,)
    )
    print(f"  NULLed offering_id on {cur.rowcount} sessions")

    # 0b: delete target_requirements that point to this scenario's buckets
    cur.execute("""
        DELETE FROM target_requirements
        WHERE bucket_id IN (
            SELECT id FROM offering_buckets WHERE scenario_id = %s
        )
    """, (scenario_id,))
    print(f"  Deleted {cur.rowcount} target_requirements")

    # 0c: delete course_offerings for this scenario's buckets
    cur.execute("""
        DELETE FROM course_offerings
        WHERE bucket_id IN (
            SELECT id FROM offering_buckets WHERE scenario_id = %s
        )
    """, (scenario_id,))
    print(f"  Deleted {cur.rowcount} course_offerings")

    # 0d: delete offering_buckets
    cur.execute("DELETE FROM offering_buckets WHERE scenario_id = %s", (scenario_id,))
    print(f"  Deleted {cur.rowcount} offering_buckets")

    # 0e: delete scheduled_sessions
    cur.execute("DELETE FROM scheduled_sessions WHERE scenario_id = %s", (scenario_id,))
    print(f"  Deleted {cur.rowcount} scheduled_sessions")

    # 0f: delete COHORT scheduling_targets for this term
    cur.execute(
        "DELETE FROM scheduling_targets WHERE academic_term_id = %s AND target_type = 'COHORT'",
        (term_id,)
    )
    print(f"  Deleted {cur.rowcount} COHORT scheduling_targets")

    # 0g: wipe all student selections for this term so stale offering_id references
    # don't survive the reimport (every offering_id is regenerated with a new UUID).
    cur.execute(
        "DELETE FROM student_group_selections WHERE academic_term_id = %s",
        (term_id,)
    )
    print(f"  Deleted {cur.rowcount} student_group_selections")

    # 0g2: clear elective_pools for this term — they are regenerated in Step 4
    # alongside the offering_buckets, so stale rows must be removed first to
    # avoid duplicate-label conflicts on the uq_elective_pool_label constraint.
    cur.execute(
        "DELETE FROM elective_pools WHERE academic_term_id = %s",
        (term_id,)
    )
    print(f"  Deleted {cur.rowcount} elective_pools")

    # 0g3: clear student_course_eligibility for this term
    cur.execute(
        "DELETE FROM student_course_eligibility WHERE academic_term_id = %s",
        (term_id,)
    )
    print(f"  Deleted {cur.rowcount} student_course_eligibility rows")

    # 0h: flush stale offering:seats:* keys from Redis — every offering UUID is
    # regenerated so old counters are orphaned and would produce "Unknown bucket"
    # errors in the selection service until the keys expire naturally.
    n_redis = _flush_offering_seats_cache(dry_run=False)
    print(f"  Flushed {n_redis} Redis offering:seats:* keys")


# ═══════════════════════════════════════════════════════════════════════════════
# STEP 1 — ENTITY SETUP (idempotent)
# ═══════════════════════════════════════════════════════════════════════════════

def step1_entities(cur, lab_df: pd.DataFrame, theory_df: pd.DataFrame,
                   inst_id: str, term_id: str, dept_id_map: dict, dry_run: bool) -> None:
    print("\n── Step 1: ENTITIES ───────────────────────────────────────────────")

    # ── Rooms ──────────────────────────────────────────────────────────────────
    cur.execute("SELECT code FROM rooms WHERE institution_id = %s", (inst_id,))
    existing_rooms = {r["code"].strip() for r in cur.fetchall()}
    cap_map: dict[str, int] = {}
    for _, r in lab_df.iterrows():
        rn = str(r.get("room_number") or "").strip()
        cap_raw = r.get("capacity")
        if rn and not _is_blank(cap_raw):
            cap_map[rn] = max(cap_map.get(rn, 0), int(float(cap_raw)))
    block_map: dict[str, str] = {}
    for df in [lab_df, theory_df]:
        for _, r in df.iterrows():
            rn = str(r.get("room_number") or "").strip()
            blk = str(r.get("block") or "").strip()
            if rn and blk and blk != "nan":
                block_map[rn] = blk
    lab_rooms = set(lab_df["room_number"].dropna().str.strip())
    all_rooms = set(lab_df["room_number"].dropna().str.strip()) | set(theory_df["room_number"].dropna().str.strip())
    rooms_created = 0
    for room_num in sorted(all_rooms - existing_rooms):
        if not room_num or room_num.lower() == "nan":
            continue
        cap = cap_map.get(room_num, 60)
        building = block_map.get(room_num, "")
        rtype = "LAB" if room_num in lab_rooms else "LECTURE"
        name = f"{room_num} ({building})" if building else room_num
        if not dry_run:
            cur.execute(
                """INSERT INTO rooms (id, institution_id, code, name, capacity, room_type,
                       is_active, created_at, updated_at, building)
                   VALUES (%s::uuid,%s::uuid,%s,%s,%s,%s,true,NOW(),NOW(),%s)
                   ON CONFLICT DO NOTHING""",
                (str(uuid.uuid4()), inst_id, room_num, name, cap, rtype, building or None),
            )
        rooms_created += 1
    print(f"  Rooms:   {rooms_created} created (skipped {len(existing_rooms)} existing)")

    # ── Faculty ────────────────────────────────────────────────────────────────
    cur.execute("SELECT id::text, name, staff_code FROM faculty WHERE institution_id = %s", (inst_id,))
    existing_by_code: dict[str, str] = {}
    existing_by_name: dict[str, str] = {}
    existing_by_norm: dict[str, str] = {}
    for r in cur.fetchall():
        if r["staff_code"]:
            existing_by_code[_normalize_staff_code(r["staff_code"])] = r["id"]
        existing_by_name[r["name"].strip().lower()] = r["id"]
        existing_by_norm[_normalize_faculty_name(r["name"])] = r["id"]
    cur.execute("SELECT email FROM users WHERE institution_id = %s", (inst_id,))
    existing_emails = {r["email"].lower() for r in cur.fetchall()}

    faculty_info: dict[str, dict] = {}
    for df in [lab_df, theory_df]:
        for _, r in df.iterrows():
            name = str(r.get("teacher_name") or "").strip()
            scode = str(r.get("staff_code") or "").strip()
            dept = str(r.get("department") or "").strip()
            if not name or name.lower() in _SKIP_TEACHERS:
                continue
            scode_norm = _normalize_staff_code(scode)
            key = scode_norm if scode_norm else name.lower()
            if key not in faculty_info:
                faculty_info[key] = {"name": name, "scode": scode_norm, "dept": dept}

    fac_created = fac_updated = fac_no_dept = 0
    for key, info in sorted(faculty_info.items()):
        if info["scode"] and info["scode"] in existing_by_code:
            continue
        if info["name"].lower() in existing_by_name:
            pass  # fall through to backfill check below
        elif _normalize_faculty_name(info["name"]) in existing_by_norm:
            # e.g. CSV has "K Raju", DB has "Dr. K Raju" — same person, skip creation
            existing_id = existing_by_norm[_normalize_faculty_name(info["name"])]
            if info["scode"] and not dry_run:
                cur.execute(
                    "UPDATE faculty SET staff_code = %s, updated_at = NOW() WHERE id = %s::uuid"
                    " AND (staff_code IS NULL OR staff_code = '')",
                    (info["scode"], existing_id),
                )
                if cur.rowcount:
                    existing_by_code[info["scode"]] = existing_id
                    fac_updated += 1
            continue
        if info["name"].lower() in existing_by_name:
            dept_id = dept_id_map.get(info["dept"])
            backfilled = False
            if info["scode"] and dept_id and not dry_run:
                cur.execute(
                    """UPDATE faculty f
                       SET staff_code = %s, updated_at = NOW()
                       FROM users u
                       WHERE f.user_id = u.id
                         AND f.institution_id = %s::uuid
                         AND lower(f.name) = lower(%s)
                         AND u.department_id = %s::uuid
                         AND (f.staff_code IS NULL OR f.staff_code = '')""",
                    (info["scode"], inst_id, info["name"], dept_id),
                )
                if cur.rowcount:
                    backfilled = True
                    fac_updated += cur.rowcount
                    cur.execute(
                        """SELECT f.id::text FROM faculty f
                           JOIN users u ON u.id = f.user_id
                           WHERE f.institution_id = %s::uuid
                             AND lower(f.name) = lower(%s)
                             AND u.department_id = %s::uuid
                             AND lower(f.staff_code) = lower(%s)
                           LIMIT 1""",
                        (inst_id, info["name"], dept_id, info["scode"]),
                    )
                    row = cur.fetchone()
                    if row:
                        existing_by_code[info["scode"]] = row["id"]
            if backfilled or not info["scode"]:
                continue
            # Same display name already exists but this staff_code is new — create a
            # dept-linked row (e.g. placeholder "New Faculty 1" tied to AIML).
        dept_id = dept_id_map.get(info["dept"])
        if not dept_id and info["dept"] and info["dept"].lower() not in ("nan", ""):
            fac_no_dept += 1
        base_email = (
            f"{info['scode'].strip()}@rec.ac.in" if info["scode"]
            else info["name"].lower().replace(" ", ".").replace("..", ".").replace("'", "") + "@rec.ac.in"
        )
        email = base_email
        sfx = 2
        while email.lower() in existing_emails:
            email = f"{base_email.rsplit('@', 1)[0]}{sfx}@rec.ac.in"
            sfx += 1
        if not dry_run:
            user_id = str(uuid.uuid4())
            fac_id = str(uuid.uuid4())
            cur.execute(
                """INSERT INTO users (id, institution_id, email, hashed_password, full_name,
                       role, is_active, is_verified, created_at, updated_at, department_id)
                   VALUES (%s::uuid,%s::uuid,%s,%s,%s,'teacher',true,true,NOW(),NOW(),%s)
                   ON CONFLICT (email) DO NOTHING""",
                (user_id, inst_id, email, BCRYPT_PLACEHOLDER, info["name"], dept_id),
            )
            cur.execute(
                """INSERT INTO faculty (id, institution_id, name, user_id, staff_code,
                       employment_type, max_weekly_hours, is_active, created_at, updated_at)
                   VALUES (%s::uuid,%s::uuid,%s,%s::uuid,%s,'FULL_TIME',20,true,NOW(),NOW())
                   ON CONFLICT DO NOTHING""",
                (fac_id, inst_id, info["name"], user_id, info["scode"] if info["scode"] else None),
            )
        existing_emails.add(email.lower())
        if info["scode"]:
            existing_by_code[info["scode"]] = "new"
        existing_by_name[info["name"].lower()] = "new"
        fac_created += 1
    if fac_updated:
        print(f"  Faculty: {fac_created} created, {fac_updated} staff_code backfilled")
    else:
        print(f"  Faculty: {fac_created} created")
    if fac_no_dept:
        print(f"  [WARN] {fac_no_dept} faculty created without dept link (unmapped dept in CSV)")

    # ── Courses ────────────────────────────────────────────────────────────────
    cur.execute("SELECT code FROM courses WHERE institution_id = %s", (inst_id,))
    existing_courses = {r["code"].strip().upper() for r in cur.fetchall()}
    courses: dict[str, dict] = {}
    for df, stype in [(lab_df, "LAB"), (theory_df, "THEORY")]:
        for _, r in df.iterrows():
            code = str(r.get("course_code") or "").strip().upper()
            if not code or code == "NAN" or code in existing_courses or code in courses:
                continue
            name = str(r.get("course_name") or "").strip()
            dept = str(r.get("department") or "").strip()
            sem_raw = r.get("semester")
            if stype == "LAB":
                hours_raw = r.get("practical_hours")
            else:
                lh = r.get("lecture_hours") or 0
                th = r.get("tutorial_hours") or 0
                hours_raw = (0 if _is_blank(lh) else float(lh)) + (0 if _is_blank(th) else float(th))
            hours = max(int(float(hours_raw)) if not _is_blank(hours_raw) else 3, 1)
            sem = int(float(sem_raw)) if not _is_blank(sem_raw) else None
            courses[code] = {"name": name, "dept": dept, "sem": sem, "stype": stype, "hours": hours}

    # PE slot courses from pe_course_map.csv (letter-slot codes PE1–PE5)
    pe_pools, _slot_to_pool = load_pe_course_map()
    _pe_slot_codes = set(_slot_to_pool.keys())
    slot_course_names = _load_slot_course_names(cur, inst_id, pe_pools)
    pe_name_maps = build_pe_name_to_slot_maps(
        lab_df, theory_df, pe_pools, slot_course_names=slot_course_names,
    )
    slot_display_names: dict[str, str] = {}
    for pool in pe_pools.values():
        for slot_code, subject in zip(
            pool["slot_codes"], pool.get("slot_subjects") or [],
        ):
            if subject:
                slot_display_names[slot_code] = subject
    for pairs in pe_name_maps.values():
        for display_name, slot_code in pairs:
            slot_display_names.setdefault(slot_code, display_name)
    for pool in pe_pools.values():
        for slot_code in pool["slot_codes"]:
            if slot_code in existing_courses or slot_code in courses:
                continue
            courses[slot_code] = {
                "name": slot_display_names.get(slot_code, slot_code),
                "dept": pool["legacy_dept"],
                "sem": pool["sem"],
                "stype": "THEORY",
                "hours": 3,
            }

    courses_created = 0
    for code, info in sorted(courses.items()):
        dept_id = dept_id_map.get(info["dept"])
        if not dry_run:
            cur.execute(
                """INSERT INTO courses
                       (id, institution_id, code, name, weekly_hours, session_type,
                        credits, is_active, created_at, updated_at,
                        department_id, elective_semester, elective_type,
                        room_tags_soft, preferred_room_ids_soft,
                        lab_preferred_room_ids_soft, lab_room_tags_soft)
                   VALUES (%s::uuid,%s::uuid,%s,%s,%s,%s,3,true,NOW(),NOW(),%s,%s,%s,false,false,false,false)
                   ON CONFLICT DO NOTHING""",
                (
                    str(uuid.uuid4()), inst_id, code, info["name"],
                    info["hours"], info["stype"],
                    dept_id, info["sem"], _elective_type(code, _pe_slot_codes),
                ),
            )
        existing_courses.add(code)
        courses_created += 1
    slot_names_fixed = 0
    if not dry_run:
        for pool in pe_pools.values():
            for slot_code, subject in zip(
                pool["slot_codes"], pool.get("slot_subjects") or [],
            ):
                if not subject or slot_code not in existing_courses:
                    continue
                cur.execute(
                    """UPDATE courses SET name = %s, updated_at = NOW()
                       WHERE institution_id = %s::uuid AND upper(code) = %s""",
                    (subject, inst_id, slot_code.upper()),
                )
                if cur.rowcount:
                    slot_names_fixed += 1
    print(f"  Courses: {courses_created} created", end="")
    if slot_names_fixed:
        print(f", {slot_names_fixed} PE slot names corrected")
    else:
        print()

    # ── Teaching Assignments (PE/OE only – needed for telemetry lookup) ────────
    cur.execute("SELECT id::text, code FROM courses WHERE institution_id = %s", (inst_id,))
    course_lk = {r["code"].strip().upper(): r["id"] for r in cur.fetchall()}
    cur.execute("SELECT id::text, name, staff_code FROM faculty WHERE institution_id = %s", (inst_id,))
    _fac_rows_step1 = cur.fetchall()
    faculty_by_code: dict[str, str] = {}
    faculty_by_name: dict[str, str] = {}
    faculty_by_norm: dict[str, str] = _build_fac_by_norm(_fac_rows_step1)
    for r in _fac_rows_step1:
        if r["staff_code"]:
            faculty_by_code[_normalize_staff_code(r["staff_code"])] = r["id"]
        faculty_by_name[r["name"].strip().lower()] = r["id"]
    cur.execute(
        "SELECT course_id::text, faculty_id::text FROM teaching_assignments WHERE academic_term_id = %s",
        (term_id,)
    )
    existing_ta = {(r["course_id"], r["faculty_id"]) for r in cur.fetchall()}

    ta_created = 0
    seen_ta: set = set()
    for df in [lab_df, theory_df]:
        for _, r in df.iterrows():
            code = str(r.get("course_code") or "").strip().upper()
            if not code or not _elective_type(code, _pe_slot_codes):
                continue
            dept = str(r.get("department") or "").strip()
            name = str(r.get("teacher_name") or "").strip()
            scode = str(r.get("staff_code") or "").strip().lower()
            course_id = course_lk.get(code)
            if not course_id:
                continue
            fac_id = _resolve_faculty_id(
                name, scode,
                fac_by_code=faculty_by_code,
                fac_by_name=faculty_by_name,
                fac_by_norm=faculty_by_norm,
            )
            if not fac_id:
                continue
            dept_id = dept_id_map.get(dept)
            key = (course_id, fac_id)
            if key in existing_ta or key in seen_ta:
                continue
            seen_ta.add(key)
            sem_raw = r.get("semester")
            sem = int(float(sem_raw)) if not _is_blank(sem_raw) else 1
            if not dry_run:
                cur.execute(
                    """INSERT INTO teaching_assignments
                           (id, institution_id, academic_term_id, department_id,
                            course_id, faculty_id, section_count, is_active,
                            created_at, updated_at, study_semester)
                       VALUES (%s::uuid,%s::uuid,%s::uuid,%s::uuid,
                               %s::uuid,%s::uuid,1,true,NOW(),NOW(),%s)
                       ON CONFLICT ON CONSTRAINT uq_teaching_assignment DO NOTHING""",
                    (str(uuid.uuid4()), inst_id, term_id, dept_id, course_id, fac_id, sem),
                )
            ta_created += 1
    print(f"  TAs:     {ta_created} PE/OE TAs created")

    # Slot-level TAs for mapped PE subjects (pe_course_map PE1–PE5 codes)
    pe_subject_lookup: dict[tuple[str, int, str], dict[str, str]] = {}
    for pool_key, pairs in pe_name_maps.items():
        pe_subject_lookup[pool_key] = {
            _normalize_subject_name(name): slot for name, slot in pairs
        }
    slot_ta_created = 0
    for df in [lab_df, theory_df]:
        for _, r in df.iterrows():
            code = str(r.get("course_code") or "").strip().upper()
            if not _is_pe_general_code(code):
                continue
            dept = str(r.get("department") or "").strip()
            sem_raw = r.get("semester")
            sem = int(float(sem_raw)) if not _is_blank(sem_raw) else 1
            pe_pool_key = _resolve_pe_pool_key(code, dept, sem, pe_pools, _slot_to_pool)
            if not pe_pool_key:
                continue
            cname_norm = _normalize_subject_name(str(r.get("course_name") or ""))
            slot_code = pe_subject_lookup.get(pe_pool_key, {}).get(cname_norm)
            if not slot_code:
                continue
            slot_course_id = course_lk.get(slot_code)
            if not slot_course_id:
                continue
            name = str(r.get("teacher_name") or "").strip()
            scode = str(r.get("staff_code") or "").strip().lower()
            fac_id = _resolve_faculty_id(
                name, scode,
                fac_by_code=faculty_by_code,
                fac_by_name=faculty_by_name,
                fac_by_norm=faculty_by_norm,
            )
            if not fac_id:
                continue
            dept_id = dept_id_map.get(dept)
            key = (slot_course_id, fac_id)
            if key in existing_ta or key in seen_ta:
                continue
            seen_ta.add(key)
            if not dry_run:
                cur.execute(
                    """INSERT INTO teaching_assignments
                           (id, institution_id, academic_term_id, department_id,
                            course_id, faculty_id, section_count, is_active,
                            created_at, updated_at, study_semester)
                       VALUES (%s::uuid,%s::uuid,%s::uuid,%s::uuid,
                               %s::uuid,%s::uuid,1,true,NOW(),NOW(),%s)
                       ON CONFLICT ON CONSTRAINT uq_teaching_assignment DO NOTHING""",
                    (str(uuid.uuid4()), inst_id, term_id, dept_id, slot_course_id, fac_id, sem),
                )
            slot_ta_created += 1
    if slot_ta_created:
        print(f"  TAs:     {slot_ta_created} PE slot TAs created")


# ═══════════════════════════════════════════════════════════════════════════════
# STEP 2 — IMPORT SESSIONS
# ═══════════════════════════════════════════════════════════════════════════════

def _build_time_grid_slots() -> dict:
    slots: dict = {}
    for abbr in CANONICAL_DAYS:
        for idx, (start, end) in enumerate(THEORY_TIMES):
            period = "lunch" if idx == 4 else ("morning" if idx < 4 else "afternoon")
            slots[f"{abbr}_T{idx}"] = {
                "day": abbr, "start": start, "end": end,
                "period": period, "type": "theory", "slot_index": idx,
            }
        for name, (start, end) in LAB_TIMES.items():
            num = name[1:]
            period = "afternoon" if int(num) >= 4 else "morning"
            slots[f"{abbr}_L{num}"] = {
                "day": abbr, "start": start, "end": end,
                "period": period, "type": "lab", "session_name": name,
            }
    return slots


def step2_import(cur, lab_df: pd.DataFrame, theory_df: pd.DataFrame,
                 scenario_id: str, term_id: str, dry_run: bool) -> None:
    print("\n── Step 2: IMPORT SESSIONS ────────────────────────────────────────")

    # Ensure TimeGrid
    cur.execute("SELECT selected_time_grid_id FROM scenarios WHERE id = %s", (scenario_id,))
    row = cur.fetchone()
    existing_tg_id = str(row["selected_time_grid_id"]) if row and row["selected_time_grid_id"] else None
    new_slots = _build_time_grid_slots()
    if existing_tg_id:
        cur.execute("SELECT slots FROM time_grids WHERE id = %s", (existing_tg_id,))
        tg_row = cur.fetchone()
        existing = tg_row["slots"] if tg_row else {}
        merged = {**new_slots, **existing}
        added = set(merged) - set(existing)
        if not dry_run and added:
            cur.execute(
                "UPDATE time_grids SET slots = %s, updated_at = NOW() WHERE id = %s",
                (json.dumps(merged), existing_tg_id)
            )
        print(f"  TimeGrid {existing_tg_id[:8]}...  ({len(added)} new slots merged)")
    else:
        tg_id = str(uuid.uuid4())
        if not dry_run:
            cur.execute(
                """INSERT INTO time_grids (id, academic_term_id, name, slots, is_active, created_at, updated_at)
                   VALUES (%s,%s,%s,%s,true,NOW(),NOW())""",
                (tg_id, term_id, "Legacy Scheduler Import", json.dumps(new_slots))
            )
            cur.execute("UPDATE scenarios SET selected_time_grid_id = %s WHERE id = %s", (tg_id, scenario_id))
        print(f"  Created TimeGrid {tg_id[:8]}...")

    # Lookups
    cur.execute("SELECT id, code FROM rooms WHERE code IS NOT NULL")
    room_lk = {r["code"].strip(): str(r["id"]) for r in cur.fetchall()}
    cur.execute("SELECT id, name, staff_code FROM faculty")
    _fac_rows_s2 = cur.fetchall()
    faculty_lk: dict[str, str] = {}
    fac_norm_lk: dict[str, str] = {}
    for r in _fac_rows_s2:
        if r["name"]:
            faculty_lk[r["name"].strip().lower()] = str(r["id"])
            fac_norm_lk[_normalize_faculty_name(r["name"])] = str(r["id"])
        if r["staff_code"]:
            faculty_lk[_normalize_staff_code(r["staff_code"])] = str(r["id"])
    cur.execute("SELECT id, code FROM courses WHERE code IS NOT NULL")
    course_lk = {r["code"].strip().upper(): str(r["id"]) for r in cur.fetchall()}

    # PE subject lookup for resolving general PE codes (e.g. AD23PE31) → slot course_id
    _pe_pools_s2, _slot_to_pool_s2 = load_pe_course_map()
    _pe_slot_codes_s3 = set(_slot_to_pool_s2.keys())
    _pe_name_maps_s2 = build_pe_name_to_slot_maps(lab_df, theory_df, _pe_pools_s2)
    _pe_subj_lk_s2: dict[tuple, dict[str, str]] = {
        pool_key: {_normalize_subject_name(name): slot for name, slot in pairs}
        for pool_key, pairs in _pe_name_maps_s2.items()
    }

    def _resolve_pe_course(code: str, dept: str, sem: int | None, cname: str) -> str | None:
        """Try to map a PE general code + course_name → slot course_id."""
        if sem is None or not _is_pe_general_code(code):
            return None
        pool_key = _resolve_pe_pool_key(code, dept, sem, _pe_pools_s2, _slot_to_pool_s2)
        if not pool_key:
            return None
        slot = _pe_subj_lk_s2.get(pool_key, {}).get(_normalize_subject_name(cname))
        if not slot:
            return None
        return course_lk.get(slot)

    miss_rooms: set = set()
    miss_faculty: set = set()
    miss_courses: set = set()
    rows: list[dict] = []

    def _resolve_fac(teacher: str, scode: str) -> str | None:
        tk = teacher.strip().lower()
        sk = _normalize_staff_code(scode)
        return (
            faculty_lk.get(sk)
            or faculty_lk.get(tk)
            or fac_norm_lk.get(_normalize_faculty_name(teacher))
            or fac_norm_lk.get(_normalize_faculty_name(scode))
            or None
        )

    # Lab rows
    for _, r in lab_df.iterrows():
        room_num = str(r.get("room_number") or "").strip()
        room_id = room_lk.get(room_num)
        if not room_id:
            miss_rooms.add(room_num or "(empty)")
            continue
        teacher = str(r.get("teacher_name") or "").strip()
        scode = str(r.get("staff_code") or "").strip()
        fac_id = _resolve_fac(teacher, scode)
        if not fac_id:
            miss_faculty.add(teacher or scode or "(empty)")
            continue
        day = str(r.get("day") or "").lower().strip()
        session = str(r.get("session_name") or "").strip()
        slot = f"{_day_abbr(day)}_L{str(session).upper().lstrip('L')}"
        ta_id = str(r.get("course_instance_id") or "")
        if _is_uuid(ta_id):
            cur.execute(
                "SELECT course_id::text FROM teaching_assignments WHERE id = %s::uuid", (ta_id,)
            )
            cr = cur.fetchone()
            course_id = cr["course_id"] if cr else ta_id
        else:
            code = str(r.get("course_code") or "").strip().upper()
            course_id = course_lk.get(code, "")
            if not course_id:
                dept_s2 = str(r.get("department") or "").strip()
                sem_raw_s2 = r.get("semester")
                sem_s2 = int(float(sem_raw_s2)) if not _is_blank(sem_raw_s2) else None
                cname_s2 = str(r.get("course_name") or "").strip()
                course_id = _resolve_pe_course(code, dept_s2, sem_s2, cname_s2) or ""
            if not course_id:
                miss_courses.add(code or "(empty)")
                continue
        batch_num = r.get("batch_number")
        batch_sfx = f"_B{int(batch_num)}" if not _is_blank(batch_num) else ""
        rows.append({
            "id": str(uuid.uuid4()), "scenario_id": scenario_id,
            "session_id": f"{ta_id}_{slot}{batch_sfx}",
            "course_id": course_id, "faculty_id": fac_id,
            "room_id": room_id, "slot_code": slot, "is_pinned": False, "offering_id": None,
        })

    # Theory rows
    for _, r in theory_df.iterrows():
        room_num = str(r.get("room_number") or "").strip()
        room_id = room_lk.get(room_num)
        if not room_id:
            miss_rooms.add(room_num or "(empty)")
            continue
        teacher = str(r.get("teacher_name") or "").strip()
        scode = str(r.get("staff_code") or "").strip()
        fac_id = _resolve_fac(teacher, scode)
        if not fac_id:
            miss_faculty.add(teacher or scode or "(empty)")
            continue
        day = str(r.get("day") or "").lower().strip()
        slot_raw = r.get("slot_index")
        if _is_blank(slot_raw):
            continue
        slot = f"{_day_abbr(day)}_T{int(slot_raw)}"
        ta_id = str(r.get("course_instance_id") or "")
        if _is_uuid(ta_id):
            cur.execute(
                "SELECT course_id::text FROM teaching_assignments WHERE id = %s::uuid", (ta_id,)
            )
            cr = cur.fetchone()
            course_id = cr["course_id"] if cr else ta_id
        else:
            code = str(r.get("course_code") or "").strip().upper()
            course_id = course_lk.get(code, "")
            if not course_id:
                dept_s2 = str(r.get("department") or "").strip()
                sem_raw_s2 = r.get("semester")
                sem_s2 = int(float(sem_raw_s2)) if not _is_blank(sem_raw_s2) else None
                cname_s2 = str(r.get("course_name") or "").strip()
                course_id = _resolve_pe_course(code, dept_s2, sem_s2, cname_s2) or ""
            if not course_id:
                miss_courses.add(code or "(empty)")
                continue
        session_num = r.get("session_number")
        seq = int(session_num) if not _is_blank(session_num) else 1
        rows.append({
            "id": str(uuid.uuid4()), "scenario_id": scenario_id,
            "session_id": f"{ta_id}_{slot}_S{seq}",
            "course_id": course_id, "faculty_id": fac_id,
            "room_id": room_id, "slot_code": slot, "is_pinned": False, "offering_id": None,
        })

    print(f"  Parsed: {len(rows)} sessions  "
          f"({len(miss_rooms)} room misses, {len(miss_faculty)} faculty misses, "
          f"{len(miss_courses)} course misses)")
    if miss_rooms:
        print(f"  [WARN] Room misses:    {sorted(miss_rooms)[:10]}")
    if miss_faculty:
        print(f"  [WARN] Faculty misses: {sorted(miss_faculty)[:10]}")
    if miss_courses:
        print(f"  [WARN] Course misses:  {sorted(miss_courses)[:10]}")

    if not dry_run:
        _execute_values(
            cur,
            """INSERT INTO scheduled_sessions
                   (id, scenario_id, session_id, course_id, faculty_id, room_id,
                    slot_code, is_pinned, offering_id, created_at)
               VALUES %s""",
            [
                (r["id"], r["scenario_id"], r["session_id"], r["course_id"],
                 r["faculty_id"], r["room_id"], r["slot_code"], r["is_pinned"],
                 r["offering_id"])
                for r in rows
            ],
            template="(%s,%s,%s,%s,%s,%s,%s,%s,%s,NOW())",
        )
        print(f"  Inserted {len(rows)} scheduled_sessions")


# ═══════════════════════════════════════════════════════════════════════════════
# STEP 3 — COHORT BUCKETS FROM CSV group_name COLUMN
# ═══════════════════════════════════════════════════════════════════════════════

def step3_cohorts(cur, lab_df: pd.DataFrame, theory_df: pd.DataFrame,
                  scenario_id: str, term_id: str, inst_id: str,
                  dept_id_map: dict, dry_run: bool) -> dict[tuple[str, int], list[str]]:
    """Build CHOOSE_FACULTY per-group buckets from CSV group_name column.

    Bucket structure
    ----------------
    One ``CHOOSE_FACULTY`` bucket per unique ``group_name`` per (dept, semester).
    Each bucket holds all unique (course, faculty) offerings assigned to that group.

    Why group = bucket:
      Within one group (e.g. AIDS_S5_G3) the SAME COURSE may be taught by multiple
      faculty in parallel sections.  The student picks ONE faculty → CHOOSE_FACULTY.
      Across ALL group buckets the student covers every required unique course.

    PE/OE elective courses are excluded here — handled by step 4 (CHOOSE_COURSE).
    """
    print("\n── Step 3: COHORT BUCKETS FROM CSV group_name ─────────────────────")

    # Build PE slot code set so _elective_type can identify slot codes (e.g. IT23D11)
    # without relying on a regex heuristic that causes false positives (e.g. IT23C15).
    _, _slot_to_pool_s3 = load_pe_course_map()
    _pe_slot_codes_s3 = set(_slot_to_pool_s3.keys())

    # DB lookups
    cur.execute("SELECT id::text, code FROM courses WHERE institution_id = %s", (inst_id,))
    course_lk: dict[str, str] = {r["code"].strip().upper(): r["id"] for r in cur.fetchall()}

    cur.execute("SELECT id::text, name, staff_code FROM faculty WHERE institution_id = %s", (inst_id,))
    _fac_rows_s3 = cur.fetchall()
    fac_by_code: dict[str, str] = {}
    fac_by_name: dict[str, str] = {}
    fac_by_norm_s3 = _build_fac_by_norm(_fac_rows_s3)
    for r in _fac_rows_s3:
        if r["staff_code"]:
            fac_by_code[_normalize_staff_code(r["staff_code"])] = r["id"]
        fac_by_name[r["name"].strip().lower()] = r["id"]

    def _resolve_fac(teacher: str, scode: str) -> str | None:
        return _resolve_faculty_id(
            teacher, scode,
            fac_by_code=fac_by_code,
            fac_by_name=fac_by_name,
            fac_by_norm=fac_by_norm_s3,
        )

    # ── Collect offerings keyed by (dept, sem, group_name) ──
    # groups_data[(dept, sem, group_name)] = {(course_id, faculty_id, ta_id, batch_num), ...}
    groups_data: dict[tuple, set] = defaultdict(set)
    # Per-offering seat cap from CSV capacity / capacity_info (e.g. lab 140, theory 70).
    cohort_offering_caps: dict[tuple, int | None] = {}
    # Per-offering capacity vote counts — a co-scheduled row's inflated room capacity
    # (e.g. 140 for a session sharing a room with another section, while only 70
    # students actually sit it) must not win over the offering's real, repeated cap.
    cohort_offering_cap_counts: dict[tuple, "Counter[int]"] = defaultdict(Counter)
    # course_name_map[course_id] = (code, name)
    course_name_map: dict[str, tuple[str, str]] = {}
    # Track all seen groups (including electives) so COHORT targets are created for every dept/sem
    all_seen_groups: dict[tuple[str, int], set[str]] = defaultdict(set)

    for df, is_lab_df in [(theory_df, False), (lab_df, True)]:
        for _, r in df.iterrows():
            gname = str(r.get("group_name") or "").strip()
            if not gname or gname == "nan":
                continue
            dept = str(r.get("department") or "").strip()
            sem_raw = r.get("semester")
            if _is_blank(sem_raw):
                continue
            sem = int(float(sem_raw))
            all_seen_groups[(dept, sem)].add(gname)

            code = str(r.get("course_code") or "").strip().upper()
            if not code or code == "NAN":
                continue
            # Skip PE/OE — step 4 handles them
            if _elective_type(code, _pe_slot_codes_s3):
                continue
            course_id = course_lk.get(code)
            if not course_id:
                continue
            teacher = str(r.get("teacher_name") or "").strip()
            scode = str(r.get("staff_code") or "").strip()
            fac_id = _resolve_fac(teacher, scode)
            if not fac_id:
                continue
            # Keep course_instance_id for precise per-group session linking.
            # Each row shares a ta_id with other sessions of the SAME group+course+faculty.
            raw_ta = str(r.get("course_instance_id") or "").strip()
            if raw_ta and raw_ta not in ("nan", "NaN", ""):
                ta_id = str(int(float(raw_ta))) if not _is_uuid(raw_ta) else raw_ta
            else:
                ta_id = ""
            # For batched labs, record each batch as a SEPARATE offering so students
            # can choose Batch 1 or Batch 2.  batch_num=None means non-batched.
            # When num_batches > 1 but CSV only lists one batch's sessions (common in
            # legacy exports), still create offerings for every batch slot.
            batch_num: int | None = None
            row_cap = _max_seats_from_row(r, is_lab_df)

            def _register_offering(bn: int | None) -> None:
                offering_key = (course_id, fac_id, ta_id, bn)
                groups_data[(dept, sem, gname)].add(offering_key)
                cap_key = (dept, sem, gname, *offering_key)
                if row_cap is not None:
                    cohort_offering_cap_counts[cap_key][row_cap] += 1
                    cohort_offering_caps[cap_key] = (
                        cohort_offering_cap_counts[cap_key].most_common(1)[0][0]
                    )

            if is_lab_df:
                is_batched_val = str(r.get("is_batched") or "False").strip().lower()
                if is_batched_val in ("true", "1", "yes"):
                    raw_batch = r.get("batch_number")
                    batch_num = int(float(raw_batch)) if not _is_blank(raw_batch) else None
                    raw_num_batches = r.get("num_batches")
                    num_batches = (
                        int(float(raw_num_batches))
                        if not _is_blank(raw_num_batches)
                        else (batch_num or 1)
                    )
                    if batch_num is not None and num_batches > 1:
                        for bn in range(1, num_batches + 1):
                            _register_offering(bn)
                        cname = str(r.get("course_name") or "").strip()
                        if course_id not in course_name_map:
                            course_name_map[course_id] = (code, cname)
                        continue

            _register_offering(batch_num)
            cname = str(r.get("course_name") or "").strip()
            if course_id not in course_name_map:
                course_name_map[course_id] = (code, cname)

    # Reconcile capacity across every faculty teaching the SAME (dept, sem, group,
    # course, batch) — a bigger room appearing on only one of a teacher's weekly
    # rows (same headcount both days) is a room-assignment artifact, not a real
    # seat increase. If even one teacher/row for this course+batch shows the true
    # (smaller) quota, every teacher sharing it gets that quota too — a per-(course,
    # faculty) mode can't recover this when one teacher's own rows are ALL inflated.
    course_min_seats_s3: dict[tuple, int] = {}
    for cap_key, counts in cohort_offering_cap_counts.items():
        dept_k, sem_k, gname_k, course_id_k, _fac_k, _ta_k, bn_k = cap_key
        group_key = (dept_k, sem_k, gname_k, course_id_k, bn_k)
        smallest = min(counts)
        prev = course_min_seats_s3.get(group_key)
        course_min_seats_s3[group_key] = min(prev, smallest) if prev is not None else smallest
    for cap_key in cohort_offering_caps:
        dept_k, sem_k, gname_k, course_id_k, _fac_k, _ta_k, bn_k = cap_key
        group_key = (dept_k, sem_k, gname_k, course_id_k, bn_k)
        if group_key in course_min_seats_s3:
            cohort_offering_caps[cap_key] = course_min_seats_s3[group_key]

    # ── Group by (dept, sem) to get sorted list of group names ────────────────
    dept_sem_groups: dict[tuple[str, int], list[str]] = defaultdict(list)
    for (dept, sem), gnames in all_seen_groups.items():
        dept_sem_groups[(dept, sem)] = list(gnames)
    for key in dept_sem_groups:
        dept_sem_groups[key].sort()

    # Pre-load existing TAs so we can ensure every (course, faculty) pair has a TA row.
    # ON CONFLICT handles races; this set prevents redundant INSERTs within one run.
    cur.execute(
        "SELECT course_id::text, faculty_id::text FROM teaching_assignments WHERE academic_term_id = %s",
        (term_id,)
    )
    ta_exists: set[tuple[str, str]] = {(r["course_id"], r["faculty_id"]) for r in cur.fetchall()}
    core_ta_created = 0

    total_buckets = total_offerings = total_linked = 0
    cohort_buckets: dict[tuple[str, int], list[str]] = defaultdict(list)

    for (dept, sem), group_names in sorted(dept_sem_groups.items()):
        dept_id = dept_id_map.get(dept)
        if not dept_id:
            continue

        cur.execute("SELECT name FROM departments WHERE id = %s::uuid", (dept_id,))
        row = cur.fetchone()
        dept_name = row["name"] if row else dept

        # ── Create COHORT SchedulingTarget ────────────────────────────────────
        target_id = str(uuid.uuid4())
        if not dry_run:
            cur.execute(
                """INSERT INTO scheduling_targets
                       (id, institution_id, academic_term_id, department_id, name,
                        target_type, study_semester, class_count, size, is_active,
                        created_at, updated_at)
                   VALUES (%s::uuid,%s::uuid,%s::uuid,%s::uuid,%s,'COHORT',%s,%s,0,true,NOW(),NOW())
                   ON CONFLICT DO NOTHING""",
                (target_id, inst_id, term_id, dept_id,
                 f"{dept_name} Sem {sem}", sem, len(group_names)),
            )
            cur.execute(
                """SELECT id::text FROM scheduling_targets
                   WHERE department_id = %s::uuid AND study_semester = %s
                     AND academic_term_id = %s::uuid AND target_type = 'COHORT'
                   LIMIT 1""",
                (dept_id, sem, term_id),
            )
            existing = cur.fetchone()
            if existing:
                target_id = existing["id"]

        # ── One CHOOSE_FACULTY bucket per group ───────────────────────────────
        bucket_ids_here: list[str] = []
        # offering_key → offering_id for session linking
        # Key: (course_id, fac_id, ta_id, batch_num) — batch_num=None for non-batched.
        # ta_id (course_instance_id prefix in session_id) allows precise per-group linking.
        # max_seats comes from CSV capacity / capacity_info via cohort_offering_caps.
        offering_link_map: dict[tuple[str, str, str, int | None], str] = {}

        for g_idx, gname in enumerate(group_names):
            g_num = g_idx + 1
            pairs = groups_data[(dept, sem, gname)]
            if not pairs:
                # No core courses for this group (e.g. they only take electives like CSE Sem 7)
                # Skip creating an empty CHOOSE_FACULTY bucket for this group.
                continue

            # Extract a readable group label from the group_name string
            # "Aeronautical Engineering_S5_G3" → "G3"
            label_parts = gname.split("_")
            g_label = label_parts[-1] if label_parts else f"G{g_num}"
            bucket_name = f"{dept_name} Sem {sem} · {g_label}"[:100]

            bucket_id = str(uuid.uuid4())
            if not dry_run:
                cur.execute(
                    """INSERT INTO offering_buckets
                           (id, institution_id, academic_term_id, department_id, name,
                            min_selection, max_selection, selection_policy, scenario_id,
                            is_active, created_at, updated_at)
                       VALUES (%s::uuid,%s::uuid,%s::uuid,%s::uuid,%s,1,1,'CHOOSE_FACULTY',%s,true,NOW(),NOW())""",
                    (bucket_id, inst_id, term_id, dept_id, bucket_name, scenario_id),
                )
            bucket_ids_here.append(bucket_id)
            cohort_buckets[(dept_id, sem)].append(bucket_id)
            total_buckets += 1

            # One CourseOffering per unique (course_id, faculty_id, ta_id, batch_num).
            # Batched labs produce two offerings (batch 1 and batch 2) each with max_seats.
            # Sort key replaces None with -1 so None < int comparisons don't fail.
            def _pair_key(p: tuple) -> tuple:
                return (p[0], p[1], p[2], p[3] if p[3] is not None else -1)
            for course_id, fac_id, ta_id, batch_num in sorted(pairs, key=_pair_key):
                # Ensure a TeachingAssignment row exists for this (course, faculty) so the
                # timetable has a canonical faculty→course→dept link regardless of PE/core type.
                if (course_id, fac_id) not in ta_exists:
                    ta_exists.add((course_id, fac_id))
                    if not dry_run:
                        if not dept_id:
                            print(f"  [WARN] TA for course={course_id} fac={fac_id} "
                                  f"has no dept_id ('{dept}' not in dept_id_map) — created without dept link")
                        cur.execute(
                            """INSERT INTO teaching_assignments
                                   (id, institution_id, academic_term_id, department_id,
                                    course_id, faculty_id, section_count, is_active,
                                    created_at, updated_at, study_semester)
                               VALUES (%s::uuid,%s::uuid,%s::uuid,%s::uuid,
                                       %s::uuid,%s::uuid,1,true,NOW(),NOW(),%s)
                               ON CONFLICT ON CONSTRAINT uq_teaching_assignment DO NOTHING""",
                            (str(uuid.uuid4()), inst_id, term_id, dept_id, course_id, fac_id, sem),
                        )
                    core_ta_created += 1

                max_seats = cohort_offering_caps.get((dept, sem, gname, course_id, fac_id, ta_id, batch_num))
                offering_id = str(uuid.uuid4())
                if not dry_run:
                    cur.execute(
                        """INSERT INTO course_offerings
                               (id, bucket_id, course_id, faculty_id, group_number,
                                study_semester, max_seats, batch_number, created_at)
                           VALUES (%s::uuid,%s::uuid,%s::uuid,%s::uuid,%s,%s,%s,%s,NOW())""",
                        (offering_id, bucket_id, course_id, fac_id, g_num, sem, max_seats, batch_num),
                    )
                offering_link_map[(course_id, fac_id, ta_id, batch_num)] = offering_id
                total_offerings += 1

            # TR: COHORT target → this group bucket
            if not dry_run:
                cur.execute(
                    """INSERT INTO target_requirements (id, target_id, bucket_id, created_at)
                       VALUES (%s::uuid,%s::uuid,%s::uuid,NOW())
                       ON CONFLICT ON CONSTRAINT uq_target_bucket DO NOTHING""",
                    (str(uuid.uuid4()), target_id, bucket_id),
                )

        # ── Link sessions → offerings ─────────────────────────────────────────
        # • Batched lab offering  (batch_num != None): match "{ta_id}_%_B{batch_num}"
        # • Non-batched / theory  (batch_num is None): match "{ta_id}_%"  (no _Bn suffix)
        # • Fallback (no ta_id): match by course_id + faculty_id
        for (course_id, fac_id, ta_id, batch_num), offering_id in offering_link_map.items():
            if not dry_run:
                if ta_id and batch_num is not None:
                    cur.execute(
                        """UPDATE scheduled_sessions
                           SET offering_id = %s::uuid
                           WHERE scenario_id = %s AND course_id = %s
                             AND session_id LIKE %s
                             AND offering_id IS NULL""",
                        (offering_id, scenario_id, course_id, f"{ta_id}_%_B{batch_num}"),
                    )
                elif ta_id:
                    # Non-batched: must NOT end with a _Bn suffix so we don't steal
                    # sessions that belong to a batched offering of the same ta_id.
                    cur.execute(
                        """UPDATE scheduled_sessions
                           SET offering_id = %s::uuid
                           WHERE scenario_id = %s AND course_id = %s
                             AND session_id LIKE %s
                             AND session_id !~ '_B[0-9]+$'
                             AND offering_id IS NULL""",
                        (offering_id, scenario_id, course_id, f"{ta_id}_%"),
                    )
                else:
                    # Fallback (no ta_id): match by course_id + faculty_id
                    cur.execute(
                        """UPDATE scheduled_sessions
                           SET offering_id = %s::uuid
                           WHERE scenario_id = %s AND course_id = %s AND faculty_id = %s
                             AND offering_id IS NULL""",
                        (offering_id, scenario_id, course_id, fac_id),
                    )
                total_linked += cur.rowcount

        print(f"  {dept} s{sem}  groups={len(group_names)}  "
              f"buckets={len(bucket_ids_here)}  offerings+={total_offerings}  linked+={total_linked}")

    dry_note = "  (dry-run: link counts are 0 — sessions not yet wiped/re-inserted)" if dry_run else ""
    print(f"\n  Total: {total_buckets} CHOOSE_FACULTY group buckets, "
          f"{total_offerings} offerings, {total_linked} sessions linked{dry_note}")
    if core_ta_created:
        print(f"  Core TAs ensured: {core_ta_created} (would be created if not already existing)")
    return dict(cohort_buckets)


# ═══════════════════════════════════════════════════════════════════════════════
# STEP 4 — PE / OE POOLS
# ═══════════════════════════════════════════════════════════════════════════════

def step4_pe_oe_pools(cur, lab_df: pd.DataFrame, theory_df: pd.DataFrame,
                      scenario_id: str, term_id: str, inst_id: str,
                      dept_id_map: dict, dry_run: bool) -> None:
    print("\n── Step 4: PE / OE POOLS ──────────────────────────────────────────")

    cur.execute("SELECT id::text, code FROM courses WHERE institution_id = %s", (inst_id,))
    course_lk = {r["code"].strip().upper(): r["id"] for r in cur.fetchall()}

    cur.execute("SELECT id::text, name, staff_code FROM faculty WHERE institution_id = %s", (inst_id,))
    _fac_rows_s4 = cur.fetchall()
    fac_by_code: dict[str, str] = {}
    fac_by_name: dict[str, str] = {}
    fac_by_norm_s4 = _build_fac_by_norm(_fac_rows_s4)
    for r in _fac_rows_s4:
        if r["staff_code"]:
            fac_by_code[_normalize_staff_code(r["staff_code"])] = r["id"]
        fac_by_name[r["name"].strip().lower()] = r["id"]

    # SchedulingTargets (COHORT) for TR linking
    cur.execute(
        """SELECT id::text, department_id::text, study_semester
           FROM scheduling_targets
           WHERE institution_id = %s AND academic_term_id = %s AND target_type = 'COHORT'""",
        (inst_id, term_id),
    )
    sched_targets: dict[tuple, list[str]] = defaultdict(list)
    for r in cur.fetchall():
        sched_targets[(r["department_id"], r["study_semester"])].append(r["id"])

    pe_pools, slot_to_pool = load_pe_course_map()
    pe_slot_codes = set(slot_to_pool.keys())
    slot_course_names = _load_slot_course_names(cur, inst_id, pe_pools)
    pe_name_maps = build_pe_name_to_slot_maps(
        lab_df, theory_df, pe_pools, slot_course_names=slot_course_names,
    )
    # normalized subject name → slot code per pool
    pe_subject_lookup: dict[tuple[str, int, str], dict[str, str]] = {}
    for pool_key, pairs in pe_name_maps.items():
        pe_subject_lookup[pool_key] = {
            _normalize_subject_name(name): slot for name, slot in pairs
        }

    # Collect PE/OE entries. PE pools use pe_course_map general code (PE1–PE5 grouped).
    # OE and unmapped PE fall back to CSV group_name cohort grouping.
    pools: dict[tuple, list] = defaultdict(list)
    pool_entry_meta: dict[tuple, dict] = {}
    pool_cohort_groups: dict[tuple, set[str]] = defaultdict(set)
    # CSE S7 per-group PE: sessions use general PE code; offerings use slot code.
    pool_session_course_codes: dict[tuple, str] = {}
    seen_pool_entries: set = set()
    for df, is_lab in [(theory_df, False), (lab_df, True)]:
        for _, r in df.iterrows():
            code = str(r.get("course_code") or "").strip().upper()
            et = _elective_type(code, pe_slot_codes)
            if not et:
                continue
            gname = str(r.get("group_name") or "").strip()
            if not gname or gname.lower() == "nan":
                continue
            dept = str(r.get("department") or "").strip()
            sem_raw = r.get("semester")
            sem = int(float(sem_raw)) if not _is_blank(sem_raw) else 1
            cname = str(r.get("course_name") or "").strip()
            cname_norm = _normalize_subject_name(cname)

            pe_pool_key = (
                _resolve_pe_pool_key(code, dept, sem, pe_pools, slot_to_pool)
                if et == "PROFESSIONAL"
                else None
            )
            slot_code = code
            per_group_pe = is_cse_s7_per_group_pe_pool(pe_pool_key)
            if pe_pool_key is not None and not per_group_pe:
                pool_key = ("pe", *pe_pool_key)
                subject_map = pe_subject_lookup.get(pe_pool_key, {})
                slot_code = subject_map.get(cname_norm) or code
                course_id = course_lk.get(slot_code) or course_lk.get(code)
            else:
                pool_key = ("cohort", dept, sem, gname, et)
                if pe_pool_key is not None and per_group_pe:
                    subject_map = pe_subject_lookup.get(pe_pool_key, {})
                    slot_code = subject_map.get(cname_norm) or code
                    course_id = course_lk.get(slot_code) or course_lk.get(code)
                    pool_session_course_codes[pool_key] = pe_pool_key[2]
                else:
                    course_id = course_lk.get(code)

            if not course_id:
                continue
            teacher = str(r.get("teacher_name") or "").strip()
            scode = str(r.get("staff_code") or "").strip().lower()
            fac_id = _resolve_faculty_id(
                teacher, scode,
                fac_by_code=fac_by_code,
                fac_by_name=fac_by_name,
                fac_by_norm=fac_by_norm_s4,
            )
            ta_id = _ta_id_from_row(r)
            row_cap = _max_seats_from_row(r, is_lab)

            # Real lab-room-capacity batch splits (e.g. 70 -> 35+35) are flagged
            # explicitly via is_batched/batch_number/num_batches in the CSV — NOT
            # inferred from how many CSV rows a teacher has. A teacher's lab that
            # meets twice a week (4 weekly hours = 2 CSV rows, one per meeting day)
            # is still ONE un-split section and must collapse to ONE offering, not
            # be mistaken for two batches. Theory rows never carry this flag.
            batch_nums: list[int | None] = [None]
            if is_lab:
                is_batched_val = str(r.get("is_batched") or "False").strip().lower()
                if is_batched_val in ("true", "1", "yes"):
                    raw_batch = r.get("batch_number")
                    single_bn = int(float(raw_batch)) if not _is_blank(raw_batch) else None
                    raw_num_batches = r.get("num_batches")
                    num_batches = (
                        int(float(raw_num_batches))
                        if not _is_blank(raw_num_batches)
                        else (single_bn or 1)
                    )
                    if num_batches > 1:
                        batch_nums = list(range(1, num_batches + 1))
                    elif single_bn is not None:
                        batch_nums = [single_bn]

            # Distinguishes genuinely separate sections taught by the same faculty
            # for the same course/pool (e.g. two distinct Vijayalakshmi sections of
            # IT23PE41) from the same section's repeated weekly meeting rows, which
            # share one course_instance_id and must still collapse to one offering.
            instance_id = str(r.get("course_instance_id") or "").strip()
            for bn in batch_nums:
                entry_key = (pool_key, course_id, fac_id or "", bn, instance_id)
                if entry_key not in seen_pool_entries:
                    seen_pool_entries.add(entry_key)
                    pools[pool_key].append((course_id, fac_id, slot_code, cname, bn, instance_id))
                    pool_entry_meta[entry_key] = {
                        "max_seats": row_cap,
                        "cap_counts": Counter({row_cap: 1}) if row_cap is not None else Counter(),
                        "ta_ids": {ta_id} if ta_id else set(),
                    }
                else:
                    meta = pool_entry_meta[entry_key]
                    if ta_id:
                        meta.setdefault("ta_ids", set()).add(ta_id)
                    if row_cap is not None:
                        meta.setdefault("cap_counts", Counter())[row_cap] += 1
                        # Mode, not max — a single merged-session row's inflated
                        # capacity shouldn't override the canonical per-section seat
                        # count shared by every other row for this teacher. Applies
                        # to dept-wide "pe" pools AND CSE S7 per-group cohort pools
                        # (e.g. CSE) alike — same row-inflation bug either way.
                        meta["max_seats"] = meta["cap_counts"].most_common(1)[0][0]
            pool_cohort_groups[pool_key].add(gname)

    # Reconcile capacity across every faculty teaching the SAME (pool_key, course,
    # batch) — a bigger room appearing on only one of a teacher's weekly rows (same
    # headcount both days) is a room-assignment artifact, not a real seat increase.
    # If even one teacher/row for this course+batch shows the true (smaller) quota,
    # every teacher sharing it gets that quota too — a per-entry mode can't recover
    # this when a single teacher's own rows are ALL inflated (no clean row to pick).
    course_min_seats: dict[tuple, int] = {}
    for (pk, cid, _fid, bn, _iid), meta in pool_entry_meta.items():
        caps = meta.get("cap_counts")
        if not caps:
            continue
        group_key = (pk, cid, bn)
        smallest = min(caps)
        prev = course_min_seats.get(group_key)
        course_min_seats[group_key] = min(prev, smallest) if prev is not None else smallest
    for (pk, cid, _fid, bn, _iid), meta in pool_entry_meta.items():
        group_key = (pk, cid, bn)
        if group_key in course_min_seats:
            meta["max_seats"] = course_min_seats[group_key]

    total_pool_buckets = 0
    for pool_key, entries in sorted(pools.items()):
        if pool_key[0] == "pe":
            _, dept, sem, general_code = pool_key
            et = "PROFESSIONAL"
            gnames = pool_cohort_groups.get(pool_key, set())
            cohort_g = None
            if len(gnames) == 1:
                cohort_g = _cohort_group_number(next(iter(gnames)))
            session_course_id = course_lk.get(general_code)
        else:
            _, dept, sem, gname, et = pool_key
            general_code = pool_session_course_codes.get(pool_key)
            session_course_id = (
                course_lk.get(general_code) if general_code else None
            )
            cohort_g = _cohort_group_number(gname)

        dept_id = dept_id_map.get(dept)
        if not dept_id:
            continue
        cur.execute("SELECT name FROM departments WHERE id = %s::uuid", (dept_id,))
        dept_name_row = cur.fetchone()
        dept_name = dept_name_row["name"] if dept_name_row else dept

        if pool_key[0] == "pe" and general_code:
            pool_kind = "PE"
            pool_name = f"{dept} Sem {sem} · PE · {general_code}"[:100]
            ep_label = f"PE-{general_code}"[:32]
        else:
            g_label = _group_suffix(gname)
            pool_kind = "PE" if et == "PROFESSIONAL" else "OE"
            pool_name = f"{dept} Sem {sem} · {pool_kind} · {g_label}"[:100]
            ep_label = f"{pool_kind}-{g_label}"

        et_str = "PROFESSIONAL" if et == "PROFESSIONAL" else "OPEN"

        # Check if pool bucket already exists for this scenario
        cur.execute(
            "SELECT id::text FROM offering_buckets WHERE scenario_id = %s AND name = %s",
            (scenario_id, pool_name),
        )
        existing_pool = cur.fetchone()
        if existing_pool:
            print(f"  SKIP  {pool_name} (already exists)")
            continue

        print(f"  + Pool  {pool_name}  ({len(entries)} options)  [elective_pool label={ep_label}]")
        bucket_id = str(uuid.uuid4())
        ep_id = str(uuid.uuid4())

        if not dry_run:
            cur.execute(
                """INSERT INTO offering_buckets
                       (id, institution_id, academic_term_id, department_id,
                        name, min_selection, max_selection, selection_policy,
                        scenario_id, is_active, created_at, updated_at)
                   VALUES (%s::uuid,%s::uuid,%s::uuid,%s::uuid,
                           %s,1,1,'CHOOSE_COURSE',%s,true,NOW(),NOW())""",
                (bucket_id, inst_id, term_id, dept_id, pool_name, scenario_id),
            )

            # Populate planning-level elective_pools table so the planning UI
            # and TeachingAssignment.elective_pool_id FK have a valid target.
            cur.execute(
                """INSERT INTO elective_pools
                       (id, institution_id, academic_term_id, department_id,
                        study_semester, label, elective_type, is_active,
                        created_at, updated_at)
                   VALUES (%s::uuid,%s::uuid,%s::uuid,%s::uuid,
                           %s,%s,%s,true,NOW(),NOW())
                   ON CONFLICT ON CONSTRAINT uq_elective_pool_label DO NOTHING
                   RETURNING id::text""",
                (ep_id, inst_id, term_id, dept_id, sem, ep_label, et_str),
            )
            ep_row = cur.fetchone()
            # If the pool already existed (conflict), fetch its real id
            if not ep_row:
                cur.execute(
                    """SELECT id::text FROM elective_pools
                       WHERE academic_term_id = %s::uuid
                         AND department_id = %s::uuid
                         AND study_semester = %s
                         AND label = %s""",
                    (term_id, dept_id, sem, ep_label),
                )
                ep_row = cur.fetchone()
            ep_id = ep_row["id"] if ep_row else ep_id

        for g_idx, (course_id, fac_id, code, cname, bn, instance_id) in enumerate(entries, 1):
            offering_id = str(uuid.uuid4())
            offering_group = cohort_g if cohort_g is not None else g_idx
            entry_key = (pool_key, course_id, fac_id or "", bn, instance_id)
            meta = pool_entry_meta.get(entry_key, {})
            max_seats = meta.get("max_seats")
            ta_ids = meta.get("ta_ids") or set()
            link_course_id = session_course_id or course_id
            if not dry_run:
                cur.execute(
                    """INSERT INTO course_offerings
                           (id, bucket_id, course_id, faculty_id, group_number,
                            study_semester, max_seats, batch_number, created_at)
                       VALUES (%s::uuid,%s::uuid,%s::uuid,%s::uuid,%s,%s,%s,%s,NOW())""",
                    (offering_id, bucket_id, course_id, fac_id or None,
                     offering_group, sem, max_seats, bn),
                )
                linked = 0
                if ta_ids:
                    # Same ta_id covers theory + every lab batch (they share one
                    # course_instance_id) — session_id alone disambiguates:
                    # batched lab sessions end "_B{n}", theory/non-batched end "_S{n}"
                    # or have no suffix at all. Without this split, the bn=None
                    # (theory) entry — built first, since theory_df is iterated
                    # before lab_df — would greedily claim every "_B{n}" lab session
                    # too (first writer wins via "offering_id IS NULL"), leaving the
                    # real batch offerings with zero linked sessions.
                    for tid in ta_ids:
                        if bn is not None:
                            cur.execute(
                                """UPDATE scheduled_sessions
                                   SET offering_id = %s::uuid
                                   WHERE scenario_id = %s AND course_id = %s
                                     AND session_id LIKE %s
                                     AND offering_id IS NULL""",
                                (offering_id, scenario_id, link_course_id, f"{tid}_%_B{bn}"),
                            )
                        else:
                            cur.execute(
                                """UPDATE scheduled_sessions
                                   SET offering_id = %s::uuid
                                   WHERE scenario_id = %s AND course_id = %s
                                     AND session_id LIKE %s
                                     AND session_id !~ '_B[0-9]+$'
                                     AND offering_id IS NULL""",
                                (offering_id, scenario_id, link_course_id, f"{tid}_%"),
                            )
                        linked += cur.rowcount
                elif fac_id:
                    cur.execute(
                        """UPDATE scheduled_sessions
                           SET offering_id = %s::uuid
                           WHERE scenario_id = %s AND course_id = %s
                             AND faculty_id = %s
                             AND offering_id IS NULL""",
                        (offering_id, scenario_id, link_course_id, fac_id),
                    )
                    linked = cur.rowcount
                else:
                    cur.execute(
                        """UPDATE scheduled_sessions
                           SET offering_id = %s::uuid
                           WHERE scenario_id = %s AND course_id = %s
                             AND offering_id IS NULL""",
                        (offering_id, scenario_id, link_course_id),
                    )
                    linked = cur.rowcount
                if linked:
                    print(f"      {code}  → linked {linked} sessions")

                # Link TA — prefer slot course, fall back to general PE code session course
                ta_course_ids = [course_id]
                if link_course_id and link_course_id != course_id:
                    ta_course_ids.append(link_course_id)
                for ta_cid in ta_course_ids:
                    if fac_id:
                        cur.execute(
                            """UPDATE teaching_assignments
                               SET elective_pool_id = %s::uuid
                               WHERE academic_term_id = %s::uuid
                                 AND course_id = %s::uuid
                                 AND faculty_id = %s::uuid
                                 AND elective_pool_id IS NULL""",
                            (ep_id, term_id, ta_cid, fac_id),
                        )
                    else:
                        cur.execute(
                            """UPDATE teaching_assignments
                               SET elective_pool_id = %s::uuid
                               WHERE academic_term_id = %s::uuid
                                 AND course_id = %s::uuid
                                 AND elective_pool_id IS NULL""",
                            (ep_id, term_id, ta_cid),
                        )

        # TargetRequirements: all COHORT targets for this dept/sem → this pool bucket
        target_ids = sched_targets.get((dept_id, sem), [])
        for tid in target_ids:
            if not dry_run:
                cur.execute(
                    """INSERT INTO target_requirements (id, target_id, bucket_id, created_at)
                       VALUES (%s::uuid,%s::uuid,%s::uuid,NOW())
                       ON CONFLICT DO NOTHING""",
                    (str(uuid.uuid4()), tid, bucket_id),
                )

        total_pool_buckets += 1

    print(f"\n  {total_pool_buckets} PE/OE pool buckets created")


# ═══════════════════════════════════════════════════════════════════════════════
# STEP 5 — FIX UNLINKED
# ═══════════════════════════════════════════════════════════════════════════════

def step5_fix_unlinked(cur, lab_df: pd.DataFrame, theory_df: pd.DataFrame,
                       scenario_id: str, term_id: str, inst_id: str,
                       dept_id_map: dict, dry_run: bool) -> None:
    print("\n── Step 5: FIX UNLINKED ───────────────────────────────────────────")

    # CSV index: str(course_instance_id) → {dept, semester, course_code}
    csv_index: dict[str, dict] = {}
    for df in [lab_df, theory_df]:
        for _, r in df.iterrows():
            raw = r.get("course_instance_id")
            if _is_blank(raw):
                continue
            ta_id = str(int(float(raw)))
            if ta_id in csv_index:
                continue
            dept = str(r.get("department") or "").strip()
            sem_raw = r.get("semester")
            code = str(r.get("course_code") or "").strip()
            if dept and not _is_blank(sem_raw) and code:
                csv_index[ta_id] = {"dept": dept, "semester": int(float(sem_raw)), "course_code": code}

    # Find unlinked (course_id, faculty_id) pairs
    cur.execute(
        """SELECT DISTINCT ss.course_id, ss.faculty_id, c.code AS course_code
           FROM scheduled_sessions ss
           LEFT JOIN courses c ON c.id::text = ss.course_id
           WHERE ss.scenario_id = %s AND ss.offering_id IS NULL""",
        (scenario_id,),
    )
    unlinked_pairs = cur.fetchall()
    print(f"  Unlinked (course_id, faculty_id) pairs: {len(unlinked_pairs)}")

    if not unlinked_pairs:
        print("  All sessions already linked!")
        return

    # Resolve dept/sem for each unlinked pair via CSV
    pair_to_meta: dict[tuple[str, str], dict] = {}
    for pair in unlinked_pairs:
        course_id, fac_id = pair["course_id"], pair["faculty_id"]
        cur.execute(
            "SELECT session_id FROM scheduled_sessions WHERE scenario_id = %s AND course_id = %s AND faculty_id = %s LIMIT 1",
            (scenario_id, course_id, fac_id),
        )
        row = cur.fetchone()
        if not row:
            continue
        ta_id_str = row["session_id"].split("_")[0]
        csv_row = csv_index.get(ta_id_str)
        if not csv_row:
            continue
        dept_id = dept_id_map.get(csv_row["dept"])
        if not dept_id:
            continue
        pair_to_meta[(course_id, fac_id)] = {
            "dept_id": dept_id, "dept": csv_row["dept"],
            "sem": csv_row["semester"], "course_code": pair["course_code"],
        }

    # Group by (dept_id, sem) → create Supplementary bucket + offerings
    pe_pools_s5, _ = load_pe_course_map()
    cse_s7_pe_codes: set[str] = set(CSE_S7_PER_GROUP_PE_GENERAL_CODES)
    for pool_key, pool in pe_pools_s5.items():
        if is_cse_s7_per_group_pe_pool(pool_key):
            cse_s7_pe_codes.update(pool["slot_codes"])

    by_dept_sem: dict[tuple[str, int], list[tuple[str, str]]] = defaultdict(list)
    skipped_cse_s7_pe = 0
    for (course_id, fac_id), meta in pair_to_meta.items():
        code_u = str(meta["course_code"] or "").strip().upper()
        if (
            meta["dept"] == CSE_LEGACY_DEPT_NAME
            and meta["sem"] == CSE_S7_STUDY_SEMESTER
            and code_u in cse_s7_pe_codes
        ):
            skipped_cse_s7_pe += 1
            continue
        by_dept_sem[(meta["dept_id"], meta["sem"])].append((course_id, fac_id))

    if skipped_cse_s7_pe:
        print(
            f"  Skipped {skipped_cse_s7_pe} CSE S7 PE pair(s) "
            f"(belong in per-group PE pools, not Supplementary)"
        )

    total_buckets = total_offerings = total_linked = total_trs = 0

    for (dept_id, sem), pairs in sorted(by_dept_sem.items()):
        cur.execute("SELECT name FROM departments WHERE id = %s::uuid", (dept_id,))
        dept_name_row = cur.fetchone()
        dept_name = dept_name_row["name"] if dept_name_row else dept_id[:8]

        # Supplementary bucket
        sup_name = f"{dept_name} Sem {sem} · Supplementary"
        cur.execute(
            "SELECT id::text FROM offering_buckets WHERE scenario_id = %s AND name = %s",
            (scenario_id, sup_name),
        )
        existing = cur.fetchone()
        if existing:
            bucket_id = existing["id"]
        else:
            bucket_id = str(uuid.uuid4())
            if not dry_run:
                cur.execute(
                    """INSERT INTO offering_buckets
                           (id, institution_id, academic_term_id, department_id, name,
                            min_selection, max_selection, selection_policy, scenario_id,
                            is_active, created_at, updated_at)
                       VALUES (%s::uuid,%s::uuid,%s::uuid,%s::uuid,%s,1,100,'CHOOSE_FACULTY',%s,true,NOW(),NOW())""",
                    (bucket_id, inst_id, term_id, dept_id, sup_name, scenario_id),
                )
            total_buckets += 1

        # TRs for Supplementary bucket
        if not dry_run:
            cur.execute(
                """SELECT id::text FROM scheduling_targets
                   WHERE department_id = %s::uuid AND study_semester = %s
                     AND academic_term_id = %s::uuid AND target_type = 'COHORT'""",
                (dept_id, sem, term_id),
            )
            for tr_row in cur.fetchall():
                cur.execute(
                    """INSERT INTO target_requirements (id, target_id, bucket_id, created_at)
                       VALUES (%s::uuid,%s::uuid,%s::uuid,NOW())
                       ON CONFLICT ON CONSTRAINT uq_target_bucket DO NOTHING""",
                    (str(uuid.uuid4()), tr_row["id"], bucket_id),
                )
                total_trs += 1

        for course_id, fac_id in pairs:
            meta = pair_to_meta[(course_id, fac_id)]
            # Ensure TA exists
            cur.execute(
                """SELECT id FROM teaching_assignments
                   WHERE academic_term_id = %s::uuid AND course_id = %s::uuid AND faculty_id = %s::uuid""",
                (term_id, course_id, fac_id),
            )
            if not cur.fetchone() and not dry_run:
                cur.execute(
                    """INSERT INTO teaching_assignments
                           (id, institution_id, academic_term_id, department_id,
                            course_id, faculty_id, section_count, is_active,
                            created_at, updated_at, study_semester)
                       VALUES (%s::uuid,%s::uuid,%s::uuid,%s::uuid,
                               %s::uuid,%s::uuid,1,true,NOW(),NOW(),%s)
                       ON CONFLICT ON CONSTRAINT uq_teaching_assignment DO NOTHING""",
                    (str(uuid.uuid4()), inst_id, term_id, dept_id,
                     course_id, fac_id, meta["sem"]),
                )

            # CourseOffering
            offering_id = str(uuid.uuid4())
            if not dry_run:
                cur.execute(
                    """INSERT INTO course_offerings
                           (id, bucket_id, course_id, faculty_id, group_number, study_semester, created_at)
                       VALUES (%s::uuid,%s::uuid,%s::uuid,%s::uuid,0,%s,NOW())""",
                    (offering_id, bucket_id, course_id, fac_id, meta["sem"]),
                )
            total_offerings += 1

            # Link sessions
            if not dry_run:
                cur.execute(
                    """UPDATE scheduled_sessions
                       SET offering_id = %s::uuid
                       WHERE scenario_id = %s AND course_id = %s AND faculty_id = %s
                         AND offering_id IS NULL""",
                    (offering_id, scenario_id, course_id, fac_id),
                )
                total_linked += cur.rowcount

        print(f"  {dept_name} Sem {sem}: {len(pairs)} pairs → Supplementary bucket")

    print(f"\n  Fix unlinked: {total_buckets} buckets, {total_offerings} offerings, {total_linked} linked, {total_trs} TRs")


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════════

def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--scenario-id", default=None,
                    help="UUID of scenario to reimport into. Auto-detects most recent COMPLETED scenario if omitted.")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    for p in (LAB_CSV, THEORY_CSV):
        if not p.exists():
            sys.exit(f"CSV not found: {p}")

    print(f"Loading CSVs: {LAB_CSV.name}, {THEORY_CSV.name}")
    lab_df    = pd.read_csv(LAB_CSV)
    theory_df = pd.read_csv(THEORY_CSV)
    print(f"  {len(lab_df)} lab rows, {len(theory_df)} theory rows")

    dsn  = _get_dsn()
    if _PSYCOPG_VER == 2:
        conn = psycopg2.connect(dsn)
        conn.autocommit = False
        cur  = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    else:
        conn = psycopg.connect(dsn, row_factory=psycopg.rows.dict_row)  # type: ignore[name-defined]
        conn.autocommit = False
        cur  = conn.cursor()

    try:
        # Institution + term
        cur.execute("SELECT id::text FROM institutions LIMIT 1")
        inst_id = cur.fetchone()["id"]
        # Auto-detect scenario if not provided
        scenario_id_arg = args.scenario_id
        if not scenario_id_arg:
            cur.execute(
                """SELECT id::text FROM scenarios
                   WHERE status = 'COMPLETED'
                   ORDER BY updated_at DESC LIMIT 1"""
            )
            auto_row = cur.fetchone()
            if not auto_row:
                sys.exit("No COMPLETED scenario found. Pass --scenario-id explicitly.")
            scenario_id_arg = auto_row["id"]
            print(f"Auto-detected scenario: {scenario_id_arg[:8]}...")

        cur.execute(
            "SELECT academic_term_id::text FROM scenarios WHERE id = %s",
            (scenario_id_arg,)
        )
        row = cur.fetchone()
        if not row:
            sys.exit(f"Scenario {scenario_id_arg} not found")
        term_id = row["academic_term_id"]
        print(f"\nScenario: {scenario_id_arg[:8]}  Term: {term_id[:8]}  Inst: {inst_id[:8]}")
        if args.dry_run:
            print("DRY RUN — nothing will be written\n")

        dept_id_map = build_dept_id_map(cur)
        print(f"Dept map: {len(dept_id_map)} entries")

        # Backup student eligibility records
        backup_student_course_eligibility_to_csv(cur, term_id, ELIGIBILITY_BACKUP_CSV)

        step0_wipe(cur, scenario_id_arg, term_id, args.dry_run)

        step1_entities(cur, lab_df, theory_df, inst_id, term_id, dept_id_map, args.dry_run)
        step2_import(cur, lab_df, theory_df, scenario_id_arg, term_id, args.dry_run)
        step3_cohorts(cur, lab_df, theory_df, scenario_id_arg, term_id, inst_id, dept_id_map, args.dry_run)
        step4_pe_oe_pools(cur, lab_df, theory_df, scenario_id_arg, term_id, inst_id, dept_id_map, args.dry_run)
        step5_fix_unlinked(cur, lab_df, theory_df, scenario_id_arg, term_id, inst_id, dept_id_map, args.dry_run)

        # Restore student eligibility records
        restore_student_course_eligibility_from_csv(cur, term_id, ELIGIBILITY_BACKUP_CSV, args.dry_run)

        # ── Final stats (within the same transaction — reflects what will be committed) ──
        cur.execute(
            """SELECT COUNT(*) total,
                      COUNT(offering_id) linked,
                      COUNT(*)-COUNT(offering_id) unlinked
               FROM scheduled_sessions WHERE scenario_id = %s""",
            (scenario_id_arg,),
        )
        r = cur.fetchone()
        cur.execute(
            """SELECT
                   COUNT(*) FILTER (WHERE session_id LIKE '%%_B1') b1_total,
                   COUNT(*) FILTER (WHERE session_id LIKE '%%_B1' AND offering_id IS NOT NULL) b1_linked,
                   COUNT(*) FILTER (WHERE session_id LIKE '%%_B2') b2_total,
                   COUNT(*) FILTER (WHERE session_id LIKE '%%_B2' AND offering_id IS NOT NULL) b2_linked
               FROM scheduled_sessions WHERE scenario_id = %s""",
            (scenario_id_arg,),
        )
        b = cur.fetchone()

        # ── Step 6: Validation ──────────────────────────────────────────────────
        print(f"\n── Step 6: VALIDATION {'(projected)' if args.dry_run else ''} ──────────────────────────────────────")
        cur.execute(
            "SELECT COUNT(*) FROM offering_buckets WHERE scenario_id = %s", (scenario_id_arg,)
        )
        total_buckets_v = cur.fetchone()["count"]
        cur.execute(
            """SELECT COUNT(*) FROM offering_buckets ob
               WHERE ob.scenario_id = %s
                 AND NOT EXISTS (
                     SELECT 1 FROM course_offerings co WHERE co.bucket_id = ob.id
                 )""",
            (scenario_id_arg,),
        )
        empty_buckets = cur.fetchone()["count"]
        cur.execute(
            """SELECT COUNT(*) FROM scheduling_targets
               WHERE academic_term_id = %s AND target_type = 'COHORT'""",
            (term_id,),
        )
        total_targets = cur.fetchone()["count"]
        cur.execute(
            """SELECT COUNT(*) FROM scheduling_targets st
               WHERE st.academic_term_id = %s AND st.target_type = 'COHORT'
                 AND NOT EXISTS (
                     SELECT 1 FROM target_requirements tr WHERE tr.target_id = st.id
                 )""",
            (term_id,),
        )
        targets_no_tr = cur.fetchone()["count"]
        cur.execute(
            """SELECT COUNT(*) FROM elective_pools
               WHERE academic_term_id = %s""",
            (term_id,),
        )
        total_pe_pools = cur.fetchone()["count"]

        null_icon  = lambda n: "✅" if n == 0 else "❌"
        print(f"  Sessions:       {r['linked']}/{r['total']} linked  {null_icon(r['unlinked'])}  ({r['unlinked']} NULL)")
        print(f"  Batch B1:       {b['b1_linked']}/{b['b1_total']} linked")
        print(f"  Batch B2:       {b['b2_linked']}/{b['b2_total']} linked")
        print(f"  Buckets:        {total_buckets_v} total,  {empty_buckets} empty  {null_icon(empty_buckets)}")
        print(f"  COHORT targets: {total_targets} total,  {targets_no_tr} without TRs  {null_icon(targets_no_tr)}")
        print(f"  PE/OE pools:    {total_pe_pools}")

        overall_ok = r["unlinked"] == 0 and empty_buckets == 0 and targets_no_tr == 0
        print(f"\n  {'✅ All checks passed' if overall_ok else '⚠️  Issues found — review above'}")

        print(f"\n{'='*60}")

        if args.dry_run:
            conn.rollback()
            print("Dry run — nothing written.")
        else:
            conn.commit()
            print("Committed ✓")

    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    main()
