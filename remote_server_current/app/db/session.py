import uuid
from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from app.core.config import settings
from app.core.logger import logger

# ---------------------------------------------------------------------------
# Engine — one per process, shared across all requests
# ---------------------------------------------------------------------------
# PgBouncer transaction pooling reassigns server connections per transaction;
# SQLAlchemy must not pool connections locally (NullPool) and asyncpg must not
# cache prepared statements (statement_cache_size=0).
_use_pgbouncer = "pgbouncer" in settings.DATABASE_URL

_engine_kwargs: dict = {
    "echo": settings.APP_ENV == "development",
    "pool_pre_ping": True,
    "connect_args": {
        "statement_cache_size": 0,
        "prepared_statement_cache_size": 0,
        # PgBouncer transaction mode reuses server connections; unique names avoid
        # DuplicatePreparedStatementError across pooled backend connections.
        "prepared_statement_name_func": lambda: f"__asyncpg_{uuid.uuid4()}__",
    },
}

if _use_pgbouncer:
    _engine_kwargs["poolclass"] = NullPool
else:
    _engine_kwargs.update(
        pool_size=settings.DB_POOL_SIZE,
        max_overflow=settings.DB_MAX_OVERFLOW,
        pool_timeout=settings.DB_POOL_TIMEOUT,
    )

engine = create_async_engine(settings.DATABASE_URL, **_engine_kwargs)

# ---------------------------------------------------------------------------
# Session factory
# ---------------------------------------------------------------------------
AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    expire_on_commit=False,      # objects stay usable after commit
    autoflush=False,
)


# ---------------------------------------------------------------------------
# FastAPI dependency — yields one session per request
# ---------------------------------------------------------------------------
async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise


# ---------------------------------------------------------------------------
# Lifespan helpers — called from app.main
# ---------------------------------------------------------------------------
async def init_db() -> None:
    """Verify the engine can reach the database on startup."""
    try:
        async with engine.begin() as conn:
            await conn.run_sync(lambda _: None)  # no-op ping
        logger.info("Database connection pool initialised.")
    except Exception as exc:
        logger.error("Could not connect to database", exc=exc)
        raise


async def close_db() -> None:
    """Dispose the connection pool on shutdown."""
    await engine.dispose()
    logger.info("Database connection pool closed.")
