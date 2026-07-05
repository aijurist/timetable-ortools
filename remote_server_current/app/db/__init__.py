"""
app/db/
=======
Async database layer.

  session.py   → AsyncEngine factory, AsyncSessionLocal, get_db() FastAPI dependency.
  base.py      → Declarative Base that all ORM models inherit from; also imports
                 all model modules so Alembic autogenerate picks them up.
  migrations/  → Alembic env.py and version scripts (auto-generated).

Connection string is read from `app.core.config.Settings.DATABASE_URL`.
Uses asyncpg driver: `postgresql+asyncpg://..."
"""

# ---------------------------------------------------------------------------
# TODO: app/db/  — create these files
# ---------------------------------------------------------------------------
#
# [ ] session.py
#       [ ] create async engine:
#             engine = create_async_engine(settings.DATABASE_URL, echo=False,
#                                          pool_size=10, max_overflow=20)
#       [ ] AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)
#       [ ] async def get_db() -> AsyncGenerator[AsyncSession, None]:
#                 """FastAPI dependency — yields a session, closes on exit."""
#                 async with AsyncSessionLocal() as session:
#                     yield session
#       [ ] async def init_db(): await engine.begin() ... (called in lifespan)
#       [ ] async def close_db(): await engine.dispose()
#
# [ ] base.py
#       [ ] class Base(DeclarativeBase): pass
#       [ ] import all ORM model modules here so Alembic sees them:
#             from app.models import scenario, schedule, constraint,
#                                    course, room, faculty, time_grid  # noqa: F401
#
# [ ] migrations/ (Alembic — run `alembic init alembic` then configure)
#       [ ] env.py  → set target_metadata = Base.metadata
#                     use run_async_migrations() with asyncpg
#       [ ] alembic.ini → sqlalchemy.url = read from env
#       [ ] versions/001_initial_schema.py     → create all core tables
#       [ ] versions/002_seed_constraint_definitions.py → seed Tier 2 rows
# ---------------------------------------------------------------------------
