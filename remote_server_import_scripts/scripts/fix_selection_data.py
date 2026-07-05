"""
Fix selection data issues before stress testing:

1. Change supplementary CHOOSE_FACULTY buckets → FIXED_BATCH
   (any bucket whose name contains ' - Sup' or has group_number=0 and only 1 offering)
   These are orphan-session containers, not student-selectable choices.
   Without this fix, AI23521 appears in BOTH grp=0 (supplementary) AND grp=5,
   causing "Each selected offering must be a different course" ValidationError
   for ALL AIML S5 student confirm attempts.

2. Seed PE eligibility for AIML S5 and S7 students
   Students need student_course_eligibility rows for PE courses to see the PE
   CHOOSE_COURSE bucket in their selection menu.  Currently they only have
   CORE_AUTO rows (seeded for CHOOSE_FACULTY courses), so the PE bucket is
   filtered out silently and confirm fails with "Must select exactly N offerings".
"""

import psycopg2
import uuid

CONN_STR = "dbname=exovance_dev user=postgres password=dev host=localhost port=5432"

TERM_ID   = "fd9f461a-1d43-4dd1-bc61-bfefa93ee363"
AIML_DEPT = "6b778751-dfeb-4ad3-ac7a-848bbc595dde"
AIDS_DEPT = "2cf9aac7-eb7f-4126-b409-4442b39cdb5b"

# PE course IDs
AI23PE31 = "7770ad3e-bb4b-4819-b1da-70313a74097d"  # AIML S5
AI23PE41 = "6f70720b-3bbe-483f-9a98-6867e82aa78a"  # AIML S7


def fix_supplementary_buckets(cur):
    """Change supplementary CHOOSE_FACULTY buckets to FIXED_BATCH."""

    # Find all buckets named with ' Sup' (supplementary from reimport step 5
    # or fix_unlinked_sessions.py).
    cur.execute("""
        SELECT id, name, selection_policy
        FROM offering_buckets
        WHERE selection_policy = 'CHOOSE_FACULTY'
          AND name ILIKE '%% Sup%%'
    """)
    sup_buckets = cur.fetchall()
    print(f"Found {len(sup_buckets)} supplementary CHOOSE_FACULTY bucket(s):")
    for b in sup_buckets:
        print(f"  {str(b[0])[:8]} — {b[1][:60]}")

    if not sup_buckets:
        print("  (none — nothing to fix)")
        return 0

    ids = [b[0] for b in sup_buckets]
    cur.execute(
        """
        UPDATE offering_buckets
        SET selection_policy = 'FIXED_BATCH'
        WHERE id = ANY(%s::uuid[])
        """,
        ([str(i) for i in ids],),
    )
    n = cur.rowcount
    print(f"  → Changed {n} bucket(s) to FIXED_BATCH ✓")
    return n


def seed_pe_eligibility(cur, dept_id: str, study_semester: int, pe_course_id: str, dept_label: str):
    """Insert PE eligibility rows for all students in dept+semester."""

    # Get all student_profiles for this dept/semester
    cur.execute(
        """
        SELECT sp.id
        FROM student_profiles sp
        JOIN users u ON u.id = sp.user_id
        WHERE u.department_id = %s AND sp.semester = %s
        """,
        (dept_id, study_semester),
    )
    profiles = [row[0] for row in cur.fetchall()]
    print(f"\n{dept_label} S{study_semester} — {len(profiles)} students, seeding PE eligibility for {pe_course_id}:")

    if not profiles:
        print("  (no students found)")
        return 0

    rows = [
        (
            str(uuid.uuid4()),
            str(p),
            pe_course_id,
            TERM_ID,
            dept_id,
            study_semester,
            "PE",
        )
        for p in profiles
    ]

    cur.executemany(
        """
        INSERT INTO student_course_eligibility
            (id, student_id, course_id, academic_term_id, department_id, study_semester, source)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT ON CONSTRAINT uq_student_course_eligibility_scope DO NOTHING
        """,
        rows,
    )
    n = cur.rowcount
    print(f"  → Inserted {n} new PE eligibility row(s) (skipped {len(rows)-n} existing) ✓")
    return n


def reset_seat_counts(cur):
    """Reset all booked_seats to 0 for a clean test run."""
    cur.execute("""
        UPDATE course_offerings
        SET booked_seats = 0
        WHERE booked_seats > 0
    """)
    n = cur.rowcount
    print(f"\nReset booked_seats → 0 for {n} offering(s) ✓")


def drop_existing_selections(cur):
    """Remove any existing CONFIRMED/DRAFT selections and registrations for a clean run."""
    cur.execute("DELETE FROM student_registrations RETURNING id")
    regs = cur.rowcount
    cur.execute("DELETE FROM student_group_selections RETURNING id")
    sels = cur.rowcount
    print(f"Cleared {regs} registrations and {sels} group selections ✓")


def flush_redis_seat_counters():
    """Delete all offering:seats:* keys from Redis so the test starts fresh."""
    try:
        import redis
        r = redis.Redis(host="localhost", port=6379, db=0)
        keys = r.keys("offering:seats:*")
        if keys:
            r.delete(*keys)
            print(f"Flushed {len(keys)} Redis seat counter key(s) ✓")
        else:
            print("Redis seat counters: (already empty)")
        # Also flush menu caches
        menu_keys = r.keys("selection:menu:*")
        if menu_keys:
            r.delete(*menu_keys)
            print(f"Flushed {len(menu_keys)} menu cache key(s) ✓")
    except Exception as exc:
        print(f"Redis flush warning: {exc}")


def main():
    conn = psycopg2.connect(CONN_STR)
    conn.autocommit = False
    cur = conn.cursor()

    print("=" * 60)
    print("STEP 1 — Fix supplementary bucket policies")
    print("=" * 60)
    fix_supplementary_buckets(cur)

    print("\n" + "=" * 60)
    print("STEP 2 — Seed PE eligibility")
    print("=" * 60)
    seed_pe_eligibility(cur, AIML_DEPT, 5, AI23PE31, "AIML")
    seed_pe_eligibility(cur, AIML_DEPT, 7, AI23PE41, "AIML")

    print("\n" + "=" * 60)
    print("STEP 3 — Clear existing selections (clean test run)")
    print("=" * 60)
    drop_existing_selections(cur)
    reset_seat_counts(cur)

    conn.commit()
    cur.close()
    conn.close()

    print("\n" + "=" * 60)
    print("STEP 4 — Flush Redis seat counters")
    print("=" * 60)
    flush_redis_seat_counters()

    print("\n✓ Fix complete. Ready for stress test.")


if __name__ == "__main__":
    main()
