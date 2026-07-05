"""
app/core/
=========
Application-wide cross-cutting concerns:

  config.py      → Pydantic BaseSettings; reads .env / environment variables.
  logger.py      → Structured logger instance (use `from app.core.logger import logger`).
  exceptions.py  → Custom HTTP exception classes and global exception handlers.
  security.py    → JWT helpers, password hashing utilities.

Rules:
  - No DB imports here (prevents circular dependencies).
  - No business logic here.
"""

# ---------------------------------------------------------------------------
# TODO: app/core/  — create these files
# ---------------------------------------------------------------------------
#
# [ ] config.py
#       [ ] class Settings(BaseSettings)
#             DATABASE_URL        : str
#             TEST_DATABASE_URL   : str
#             CELERY_BROKER_URL   : str
#             CELERY_RESULT_BACKEND: str
#             SECRET_KEY          : str
#             ACCESS_TOKEN_EXPIRE_MINUTES : int = 60
#             LLM_PROVIDER        : Literal["claude", "gemini"] = "claude"
#             ANTHROPIC_API_KEY   : str | None
#             GOOGLE_API_KEY      : str | None
#             SOLVER_TIMEOUT_SECONDS : int = 120
#             APP_ENV             : Literal["development","staging","production"]
#             LOG_LEVEL           : str = "INFO"
#             ALLOWED_ORIGINS     : list[str] = ["http://localhost:3000"]
#             model_config = SettingsConfigDict(env_file=".env")
#       [ ] settings = Settings()   (singleton, imported everywhere)
#
# [ ] logger.py
#       [ ] configure structlog or stdlib logging with JSON formatter in prod
#       [ ] expose:  logger = logging.getLogger("exovance")
#       [ ] rule: all other modules do `from app.core.logger import logger`
#                 NEVER use print()
#
# [ ] exceptions.py
#       [ ] class AppError(Exception): status_code, detail
#       [ ] class NotFoundError(AppError): status_code=404
#       [ ] class ConflictError(AppError): status_code=409
#       [ ] class SolverError(AppError): status_code=422
#       [ ] class DslCompileError(AppError): status_code=400
#       [ ] async def app_exception_handler(request, exc) -> JSONResponse
#       [ ] async def unhandled_exception_handler(request, exc) -> JSONResponse
#
# [ ] security.py
#       [ ] create_access_token(data: dict) -> str      (uses python-jose)
#       [ ] decode_access_token(token: str) -> dict
#       [ ] hash_password(plain: str) -> str            (uses passlib bcrypt)
#       [ ] verify_password(plain: str, hashed: str) -> bool
# ---------------------------------------------------------------------------
