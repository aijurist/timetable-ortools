"""Diagnostic: inspect S5 bucket offerings with batch_number, max_seats etc."""
import asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

DATABASE_URL = "postgresql+asyncpg://postgres:dev@localhost:5432/exovance_dev"
AIML_DEPT = "6b778751-dfeb-4ad3-ac7a-848bbc595dde"


async def main():
    engine = create_async_engine(DATABASE_URL, echo=False)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async with factory() as db:
        # Get scheduling_targets for AIML
        r = await db.execute(text("""
            SELECT id, study_semester FROM scheduling_targets
            WHERE department_id = :dept ORDER BY study_semester
        """), {"dept": AIML_DEPT})
        targets = {row[1]: str(row[0]) for row in r.all()}
        print(f"Scheduling targets: {targets}")

        for sem in (5, 7):
            tid = targets.get(sem)
            if not tid:
                print(f"No target for S{sem}")
                continue

            print(f"\n{'='*60}")
            print(f"S{sem} — target={tid[:8]}")
            print(f"{'='*60}")

            # Get buckets
            r = await db.execute(text("""
                SELECT ob.id, ob.name, ob.selection_policy, ob.min_selection, ob.max_selection
                FROM target_requirements tr
                JOIN offering_buckets ob ON ob.id = tr.bucket_id
                WHERE tr.target_id = :tid
                ORDER BY ob.selection_policy, ob.id
            """), {"tid": tid})
            buckets = r.all()
            print(f"Buckets ({len(buckets)}):")
            for b in buckets:
                print(f"  {str(b[0])[:8]} policy={b[2]:15} min={b[3]} max={b[4]} name={b[1][:40]}")

            # Get offerings per bucket
            r = await db.execute(text("""
                SELECT co.id, co.course_id, co.faculty_id, co.max_seats, co.batch_number,
                       co.group_number, co.study_semester, co.bucket_id, co.booked_seats,
                       c.code AS course_code, f.name AS faculty_name
                FROM course_offerings co
                JOIN target_requirements tr ON tr.bucket_id = co.bucket_id
                LEFT JOIN courses c ON c.id = co.course_id
                LEFT JOIN faculty f ON f.id = co.faculty_id
                WHERE tr.target_id = :tid
                ORDER BY co.bucket_id, co.group_number NULLS LAST, co.batch_number NULLS LAST
                LIMIT 80
            """), {"tid": tid})
            offerings = r.all()
            print(f"\nOfferings ({len(offerings)}):")
            cur_bucket = None
            for o in offerings:
                if o[7] != cur_bucket:
                    cur_bucket = o[7]
                    print(f"  --- bucket={str(cur_bucket)[:8]} ---")
                print(f"    {str(o[0])[:8]} course={o[9] or str(o[1])[:8]} fac={o[10] or 'n/a':20} max={o[3]} bat={o[4]} grp={o[5]} sem={o[6]}")

    await engine.dispose()


asyncio.run(main())
