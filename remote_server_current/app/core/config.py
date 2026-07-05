import json
from typing import Annotated, Any, Literal

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict
from typing_extensions import Self


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- Database ---
    DATABASE_URL: str = Field(
        default="postgresql+asyncpg://postgres:dev@localhost:5432/exovance_dev"
    )
    TEST_DATABASE_URL: str = Field(
        default="postgresql+asyncpg://postgres:dev@localhost:5432/exovance_test"
    )
    # Connection pool tuning — override in production via env vars.
    # IMPORTANT: pool_size + max_overflow must stay below Postgres max_connections.
    # Server: 4 CPU / 16 GB — Postgres max_connections = 500
    # 100 (pool) + 200 (overflow) = 300 max connections from app.
    # Leaves 200 free for admin, migrations, PgBouncer, read replicas.
    # In production, set DATABASE_URL to point at PgBouncer for unlimited scale.
    DB_POOL_SIZE: int = Field(default=100)
    DB_MAX_OVERFLOW: int = Field(default=200)
    # Lower from SQLAlchemy's 30 s default so pool exhaustion fails fast
    # instead of hanging for 30 s per request.
    DB_POOL_TIMEOUT: float = Field(default=10.0)
    # Postgres lock_timeout in milliseconds — applied via connect_args.
    # A contested SELECT FOR UPDATE gives up after this many ms instead of
    # queuing indefinitely, which would pile up pool slots.
    DB_LOCK_TIMEOUT_MS: int = Field(default=5000)

    # --- Uvicorn workers ---
    # Formula: 2 × CPU_cores + 1 = 9 for 4-core server.
    # Set via env var UVICORN_WORKERS in production start command.
    UVICORN_WORKERS: int = Field(default=9)

    # --- Celery / Redis ---
    CELERY_BROKER_URL: str = Field(default="redis://localhost:6379/0")
    CELERY_RESULT_BACKEND: str = Field(default="redis://localhost:6379/1")
    RATE_LIMIT_REDIS_URL: str = Field(default="redis://localhost:6379/2")

    # --- Security ---
    SECRET_KEY: str = Field(default="change-me-to-a-random-32-char-secret")
    ACCESS_TOKEN_EXPIRE_MINUTES: int = Field(default=60)

    # --- LLM ---
    # Pick a provider, set the matching API key, set AGENT_MODEL to the model name.
    #
    # Provider          | Key setting            | Example AGENT_MODEL values
    # ------------------|------------------------|----------------------------
    # claude            | ANTHROPIC_API_KEY      | claude-sonnet-4-6, claude-opus-4-6
    # openai            | OPENAI_API_KEY         | gpt-4o, gpt-4.5-preview, o1, o3-mini
    # github_copilot    | GITHUB_COPILOT_TOKEN   | gpt-4o, claude-3.5-sonnet, o1-mini
    # azure_openai      | AZURE_OPENAI_API_KEY   | your-deployment-name
    # gemini            | GOOGLE_API_KEY         | gemini-1.5-pro, gemini-2.0-flash
    # openrouter        | OPENROUTER_API_KEY     | google/gemini-2.0-flash-exp:free, meta-llama/llama-3.3-70b-instruct:free
    LLM_PROVIDER: Literal["claude", "openai", "github_copilot", "azure_openai", "gemini", "openrouter"] = Field(
        default="claude"
    )

    # Anthropic
    ANTHROPIC_API_KEY: str | None = Field(default=None)

    # OpenAI
    OPENAI_API_KEY: str | None = Field(default=None)

    # GitHub Copilot (OpenAI-compatible, uses your GitHub PAT with Copilot access)
    GITHUB_COPILOT_TOKEN: str | None = Field(default=None)

    # Azure OpenAI
    AZURE_OPENAI_API_KEY: str | None = Field(default=None)
    AZURE_OPENAI_ENDPOINT: str | None = Field(default=None)  # e.g. https://my-resource.openai.azure.com
    AZURE_OPENAI_API_VERSION: str = Field(default="2024-12-01-preview")

    # Google
    GOOGLE_API_KEY: str | None = Field(default=None)
    GOOGLE_CLIENT_ID: str | None = Field(default=None)
    GOOGLE_CLIENT_SECRET: str | None = Field(default=None)
    GOOGLE_CALLBACK_URL: str = Field(default="http://localhost:8000/api/v1/auth/google/callback")
    MOCK_AUTH_BYPASS: bool = Field(default=False)
    # Frontend base URLs — used to redirect back after OAuth exchange
    STUDENT_PORTAL_URL: str = Field(default="http://localhost:3001")
    ADMIN_PORTAL_URL: str = Field(default="http://localhost:3000")

    # OpenRouter (OpenAI-compatible, supports 300+ models)
    OPENROUTER_API_KEY: str | None = Field(default=None)

    AGENT_MODEL: str = Field(default="claude-sonnet-4-6")
    MAX_AUTO_FIX_RETRIES: int = Field(default=3)

    # --- Solver ---
    SOLVER_TIMEOUT_SECONDS: int = Field(default=120)

    # --- SMTP (password-reset email) ---
    SMTP_HOST: str = Field(default="")
    SMTP_PORT: int = Field(default=587)
    SMTP_USER: str = Field(default="")
    SMTP_PASSWORD: str = Field(default="")
    SMTP_FROM: str = Field(default="noreply@exovance.com")
    RESET_PASSWORD_BASE_URL: str = Field(default="http://localhost:3000")

    # --- Selection SSE ---
    # Interval for full cohort seat-count broadcasts (Redis pub/sub fan-out).
    # One MGET + PUBLISH per active dept+semester channel — not per SSE client.
    SELECTION_SEATS_STREAM_INTERVAL_SECONDS: float = Field(default=3.0)

    # --- Notification SSE ---
    # Heartbeat / pub/sub poll interval — notifications are push-only; this
    # only keeps the long-lived connection alive through proxies.
    NOTIFICATION_STREAM_HEARTBEAT_SECONDS: float = Field(default=30.0)

    # --- App ---
    APP_ENV: Literal["development", "staging", "production"] = Field(
        default="development"
    )
    LOG_LEVEL: str = Field(default="INFO")
    ALLOWED_ORIGINS: Annotated[list[str], NoDecode] = Field(
        default=[
            "http://localhost:3000",
            "http://localhost:3001",  # student selection portal
            "http://127.0.0.1:3000",
            "http://127.0.0.1:3001",
            "http://localhost:4000",
        ]
    )

    @field_validator("ALLOWED_ORIGINS", mode="before")
    @classmethod
    def parse_allowed_origins(cls, v: Any) -> Any:
        if isinstance(v, str):
            v = v.strip()
            if not v:
                return []
            # Try JSON array first: '["http://...", "http://..."]'
            if v.startswith("["):
                return json.loads(v)
            # Comma-separated plain string: 'http://localhost:3000,https://app.com'
            return [o.strip() for o in v.split(",") if o.strip()]
        return v

    @model_validator(mode="after")
    def enforce_production_safety(self) -> Self:
        if self.APP_ENV == "production":
            if self.MOCK_AUTH_BYPASS:
                raise ValueError(
                    "MOCK_AUTH_BYPASS must be false when APP_ENV=production"
                )
            if "localhost" in self.GOOGLE_CALLBACK_URL:
                raise ValueError(
                    "GOOGLE_CALLBACK_URL must not use localhost in production"
                )
            if self.SECRET_KEY == "change-me-to-a-random-32-char-secret":
                raise ValueError(
                    "SECRET_KEY must be set to a strong random value in production"
                )
            if len(self.SECRET_KEY) < 32:
                raise ValueError(
                    "SECRET_KEY must be at least 32 characters in production"
                )
        return self


# Singleton — import this everywhere:
#   from app.core.config import settings
settings = Settings()
