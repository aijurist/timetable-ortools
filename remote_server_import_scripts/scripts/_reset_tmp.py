"""
Reset + fix batch_id for AIML students.
Sets student_profiles.batch_id = scheduling_targets.id for AIML S5/S7.
Clears all test selections. Uses uuid.UUID objects so asyncpg sends correct type.
"""
import asyncio
import uuid
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

DATABASE_URL = "postgresql+asyncpg://postgres:dev@localhost:5432/exovance_dev"
AIML_DEPT    = uuid.UUID("6b778751-dfeb-4ad3-ac7a-848bbc595dde")
S5_TARGET    = uuid.UUID("1c08accb-6faa-4f47-83b0-f4ab49b6a5b7")
S7_TARGET    = uuid.UUID("07730e55-08c1-447e-868f-5596a33a96aa")


async def main():
    engine = create_async_engine(DATABASE_URL, echo=False)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async with factory() as db:
        # Clear selections
        r1 = await db.execute(text("DELETE FROM student_registrations"))
        r2 = await db.execute(text("DELETE FROM student_group_selections"))
        r3 = await db.execute(text(
            "UPDATE course_offerings SET booked_seats = 0 WHERE booked_seats > 0"
        ))
        print(f"Cleared {r1.rowcount} registrations, {r2.rowcount} selections, "
              f"reset {r3.rowcount} booked_seats")

        # Set batch_id for S5 students (uuid.UUID params → asyncpg sends as uuid type)
        r4 = await db.execute(text("""
            UPDATE student_profiles sp
            SET batch_id = :target
            FROM users u
            WHERE sp.user_id = u.id
              AND u.department_id = :dept
              AND sp.semester = 5
              AND sp.batch_id IS DISTINCT FROM :target
        """), {"dept": AIML_DEPT, "target": S5_TARGET})
        print(f"Assigned batch_id -> S5 target for {r4.rowcount} students")

        # Set batch_id for S7 students
        r5 = await db.execute(text("""
            UPDATE student_profiles sp
            SET batch_id = :target
            FROM users u
            WHERE sp.user_id = u.id
              AND u.department_id = :dept
              AND sp.semester = 7
              AND sp.batch_id IS DISTINCT FROM :target
        """), {"dept": AIML_DEPT, "target": S7_TARGET})
        print(f"Assigned batch_id -> S7 target for {r5.rowcount} students")

        await db.commit()

    print("Done. Ready for stress test.")
    await engine.dispose()


asyncio.run(main())
