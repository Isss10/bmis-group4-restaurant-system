"""Application configuration.

All settings are read from environment variables so that **no secret is ever
committed** (OWASP A05:2021 Security Misconfiguration). Copy `.env.example` to
`.env` for local development; `.env` is git-ignored.

Usage:
    from src.common.config import get_settings

    settings = get_settings()
    print(settings.db_name)
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal, Self

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

Environment = Literal["development", "testing", "production"]

# Values that are obviously placeholders. Booting in production with one of
# these would mean every deployment shares a known secret.
_WEAK_SECRETS = frozenset({"", "changeme", "change-me", "secret", "password", "todo", "xxx"})


class Settings(BaseSettings):
    """Runtime configuration for the restaurant system.

    Field names map to environment variables case-insensitively with the
    `APP_` prefix: `Settings.jwt_secret_key` <- `APP_JWT_SECRET_KEY`.
    """

    model_config = SettingsConfigDict(
        env_prefix="APP_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- Application -------------------------------------------------------
    app_name: str = "Restaurant Reservation & Food-Ordering System"
    app_version: str = "0.1.0"
    environment: Environment = "development"

    # --- CORS --------------------------------------------------------------
    # Comma-separated allow-list. Wildcards are rejected in production by the
    # validator below (OWASP A01/A05).
    cors_origins: str = "http://localhost:5173"

    # --- Database (MySQL 8.0) ----------------------------------------------
    db_host: str = "localhost"
    db_port: int = 3306
    db_user: str = "root"
    # Two independent protections, because they cover different leak paths:
    #   repr=False  -> keeps the value out of str(settings), log lines and
    #                  tracebacks.
    #   exclude=True -> keeps the value out of model_dump()/model_dump_json().
    # `repr=False` alone is NOT enough: model_dump() still emits the raw secret,
    # so any debug endpoint, error report or config snapshot that dumps settings
    # would leak the database password. Attribute access is unaffected, so
    # `database_url` below still works.
    db_password: str = Field(default="", repr=False, exclude=True)
    db_name: str = "restaurant"

    # SQLAlchemy pool tuning. pool_recycle must stay below MySQL's
    # wait_timeout (8h default) or the driver hands out connections the server
    # already closed, which surfaces as "MySQL server has gone away".
    db_pool_size: int = 10
    db_max_overflow: int = 20
    db_pool_recycle: int = 3600
    db_echo_sql: bool = False

    # --- Security / JWT ----------------------------------------------------
    jwt_secret_key: str = Field(default="", repr=False, exclude=True)
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = Field(default=60, ge=1, le=1440)
    # Tokens are truncated to this many characters when logged, so a leaked log
    # never contains a usable credential.
    token_log_preview_chars: int = Field(default=8, ge=0, le=32)

    # --- Rate limiting (slowapi) -------------------------------------------
    rate_limit_default: str = "200/minute"
    # Tighter limit for review submission (Objective c: "rate limiting").
    rate_limit_review: str = "5/minute"
    rate_limit_enabled: bool = True

    # --- Reservation domain rules ------------------------------------------
    # How long a temporary seat hold survives before automatic expiry
    # (Objective a: "temporary seat holds with automatic expiry").
    seat_hold_ttl_seconds: int = Field(default=600, ge=30, le=86400)

    # --- Logging -----------------------------------------------------------
    log_level: str = "INFO"
    audit_log_enabled: bool = True

    # -----------------------------------------------------------------------
    # Validation
    # -----------------------------------------------------------------------

    @model_validator(mode="after")
    def _check_production_hygiene(self) -> Self:
        """Refuse to boot production with placeholder secrets or open CORS.

        Runs after all fields are populated, so it sees the *actual*
        environment rather than the class-level default — a `field_validator`
        cannot do that reliably, which is why this is a model validator.

        A misconfiguration that fails loudly at startup is far cheaper than one
        that silently runs an insecure deployment for weeks.
        """
        if self.environment != "production":
            return self

        problems: list[str] = []

        if self.jwt_secret_key.strip().lower() in _WEAK_SECRETS:
            problems.append(
                "APP_JWT_SECRET_KEY must be a strong unique value "
                '(generate one with: python -c "import secrets; print(secrets.token_urlsafe(48))")'
            )
        if self.db_password.strip().lower() in _WEAK_SECRETS:
            problems.append("APP_DB_PASSWORD must be set to a strong unique value")
        if "*" in self.cors_origin_list:
            problems.append("APP_CORS_ORIGINS must not contain '*' in production")
        if len(self.jwt_secret_key) < 32:
            problems.append("APP_JWT_SECRET_KEY must be at least 32 characters")

        if problems:
            detail = "\n  - ".join(problems)
            msg = f"Refusing to start in production with insecure configuration:\n  - {detail}"
            raise ValueError(msg)
        return self

    # -----------------------------------------------------------------------
    # Derived values.
    #
    # These are plain properties, deliberately NOT @computed_field. A computed
    # field is included in model_dump(), which would serialise the full
    # database URL — password included — into anything that dumps settings
    # (a debug endpoint, an error report, a config snapshot in a log).
    # -----------------------------------------------------------------------

    @property
    def database_url(self) -> str:
        """SQLAlchemy URL for MySQL 8 via PyMySQL.

        `charset=utf8mb4` is required: plain `utf8` in MySQL is a 3-byte
        legacy encoding that cannot store emoji or many CJK characters, and
        truncates them with an error or silent data loss.
        """
        return (
            f"mysql+pymysql://{self.db_user}:{self.db_password}"
            f"@{self.db_host}:{self.db_port}/{self.db_name}?charset=utf8mb4"
        )

    @property
    def cors_origin_list(self) -> list[str]:
        """Parse the comma-separated CORS origins into a list."""
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    @property
    def is_testing(self) -> bool:
        return self.environment == "testing"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the cached settings instance.

    Cached so every dependency injection reads the same object and we do not
    re-parse `.env` per request. In tests, call `get_settings.cache_clear()`
    after changing environment variables — otherwise a stale instance survives
    and the test silently validates the wrong configuration.
    """
    return Settings()
