"""Unit tests for src.common.config — settings parsing and production guards."""

from __future__ import annotations

from typing import ClassVar

import pytest
from pydantic import ValidationError

from src.common.config import Settings, get_settings


class TestDatabaseUrl:
    def test_url_targets_mysql_via_pymysql(self) -> None:
        """技术选型 fixes MySQL 8.0; the driver string must match."""
        cfg = Settings(db_user="app", db_password="pw", db_host="db", db_port=3306, db_name="r")
        assert cfg.database_url.startswith("mysql+pymysql://")

    def test_url_includes_credentials_host_and_database(self) -> None:
        cfg = Settings(
            db_user="app",
            db_password="pw",
            db_host="db.example",
            db_port=3307,
            db_name="rdb",
        )
        assert "app:pw@db.example:3307/rdb" in cfg.database_url

    def test_url_forces_utf8mb4(self) -> None:
        """MySQL's legacy 3-byte `utf8` silently breaks emoji and some CJK.

        Objective (c)/(d) store customer names and dish descriptions, so this
        charset is a correctness requirement, not a preference.
        """
        assert "charset=utf8mb4" in Settings().database_url

    def test_database_url_is_excluded_from_serialisation(self) -> None:
        """The URL contains the password and must not leak via model_dump().

        This is why `database_url` is a plain property rather than a
        `computed_field` — a computed field would be serialised into any config
        dump, error report or debug endpoint.
        """
        cfg = Settings(db_password="super-secret-value")
        dumped = cfg.model_dump()
        assert "database_url" not in dumped
        assert "super-secret-value" not in str(dumped.values())

    def test_password_is_hidden_from_repr(self) -> None:
        """repr() shows up in tracebacks and log lines; the password must not."""
        cfg = Settings(db_password="super-secret-value", jwt_secret_key="another-secret-value")
        rendered = repr(cfg)
        assert "super-secret-value" not in rendered
        assert "another-secret-value" not in rendered


class TestCorsParsing:
    def test_single_origin(self) -> None:
        assert Settings(cors_origins="http://localhost:5173").cors_origin_list == [
            "http://localhost:5173"
        ]

    def test_multiple_origins_are_split_and_trimmed(self) -> None:
        cfg = Settings(cors_origins="https://a.com , https://b.com,https://c.com")
        assert cfg.cors_origin_list == ["https://a.com", "https://b.com", "https://c.com"]

    def test_empty_entries_are_dropped(self) -> None:
        assert Settings(cors_origins="https://a.com,,,").cors_origin_list == ["https://a.com"]

    def test_empty_string_yields_no_origins(self) -> None:
        assert Settings(cors_origins="").cors_origin_list == []


class TestEnvironmentFlags:
    # The production branch must satisfy the boot-time hygiene guard in
    # Settings._check_production_hygiene, otherwise constructing the object
    # raises before the flags can be read. These secrets are fictional test
    # values; supplying them for every branch is harmless for development and
    # testing, and keeps the parametrisation to a single argument.
    #
    # ClassVar: this is a constant shared by all test methods, not a
    # per-instance default. Annotating it says so, and stops the mutable-default
    # check (RUF012) that would otherwise fire on every dict class attribute.
    _VALID_PRODUCTION_SECRETS: ClassVar[dict[str, str]] = {
        "jwt_secret_key": "a-genuinely-long-and-unique-test-secret-value",
        "db_password": "a-genuinely-unique-test-db-password",
        "cors_origins": "https://restaurant.example.com",
    }

    @pytest.mark.parametrize(
        ("environment", "expected_production", "expected_testing"),
        [
            ("development", False, False),
            ("testing", False, True),
            ("production", True, False),
        ],
    )
    def test_flags_follow_environment(
        self, environment: str, expected_production: bool, expected_testing: bool
    ) -> None:
        cfg = Settings(
            environment=environment,  # type: ignore[arg-type]
            **self._VALID_PRODUCTION_SECRETS,
        )
        assert cfg.is_production is expected_production
        assert cfg.is_testing is expected_testing

    def test_unknown_environment_is_rejected(self) -> None:
        with pytest.raises(ValidationError):
            Settings(environment="staging")  # type: ignore[arg-type]


class TestProductionGuards:
    """A production deployment with a placeholder secret must fail at startup.

    Failing loudly at boot is far cheaper than running an insecure deployment
    where anyone can forge an admin token.
    """

    # ClassVar: a constant shared by every method in this class, not a
    # per-instance default. See the note in TestEnvironmentFlags above.
    _SAFE: ClassVar[dict[str, str]] = {
        "environment": "production",
        "jwt_secret_key": "a-genuinely-long-and-unique-production-secret-value",
        "db_password": "a-genuinely-unique-production-db-password",
        "cors_origins": "https://restaurant.example.com",
    }

    def test_valid_production_settings_are_accepted(self) -> None:
        assert Settings(**self._SAFE).environment == "production"

    @pytest.mark.parametrize(
        "weak",
        ["", "changeme", "change-me", "secret", "password", "todo", "xxx"],
    )
    def test_placeholder_jwt_secret_is_rejected(self, weak: str) -> None:
        with pytest.raises(ValidationError, match="APP_JWT_SECRET_KEY"):
            Settings(**{**self._SAFE, "jwt_secret_key": weak})

    def test_case_insensitive_placeholder_is_rejected(self) -> None:
        """`ChangeMe` is the same mistake as `changeme`."""
        with pytest.raises(ValidationError, match="APP_JWT_SECRET_KEY"):
            Settings(**{**self._SAFE, "jwt_secret_key": "ChangeMe"})

    def test_short_jwt_secret_is_rejected(self) -> None:
        """HS256 needs at least 256 bits of key material."""
        with pytest.raises(ValidationError, match="at least 32 characters"):
            Settings(**{**self._SAFE, "jwt_secret_key": "too-short"})

    def test_placeholder_db_password_is_rejected(self) -> None:
        with pytest.raises(ValidationError, match="APP_DB_PASSWORD"):
            Settings(**{**self._SAFE, "db_password": "changeme"})

    def test_wildcard_cors_is_rejected(self) -> None:
        with pytest.raises(ValidationError, match=r"must not contain '\*'"):
            Settings(**{**self._SAFE, "cors_origins": "*"})

    def test_wildcard_among_valid_origins_is_still_rejected(self) -> None:
        with pytest.raises(ValidationError, match=r"must not contain '\*'"):
            Settings(**{**self._SAFE, "cors_origins": "https://a.com,*"})

    def test_all_problems_are_reported_together(self) -> None:
        """Report every misconfiguration at once, not one per restart cycle."""
        with pytest.raises(ValidationError) as excinfo:
            Settings(
                environment="production",
                jwt_secret_key="short",
                db_password="changeme",
                cors_origins="*",
            )
        message = str(excinfo.value)
        assert "APP_JWT_SECRET_KEY" in message
        assert "APP_DB_PASSWORD" in message
        assert "APP_CORS_ORIGINS" in message

    @pytest.mark.parametrize("environment", ["development", "testing"])
    def test_development_and_testing_are_not_blocked(self, environment: str) -> None:
        """Local development must work without inventing strong secrets."""
        cfg = Settings(environment=environment, jwt_secret_key="", db_password="")  # type: ignore[arg-type]
        assert cfg.environment == environment


class TestFieldBounds:
    @pytest.mark.parametrize("minutes", [0, -1, 1441, 99999])
    def test_token_lifetime_must_be_a_sane_duration(self, minutes: int) -> None:
        """A 0-minute token never works; a multi-day token cannot be revoked."""
        with pytest.raises(ValidationError):
            Settings(access_token_expire_minutes=minutes)

    def test_reasonable_token_lifetime_is_accepted(self) -> None:
        assert Settings(access_token_expire_minutes=30).access_token_expire_minutes == 30

    @pytest.mark.parametrize("ttl", [0, 29, 86401])
    def test_seat_hold_ttl_must_be_bounded(self, ttl: int) -> None:
        """Objective (a) requires holds to expire; an unbounded TTL locks a table forever."""
        with pytest.raises(ValidationError):
            Settings(seat_hold_ttl_seconds=ttl)

    def test_default_seat_hold_ttl_is_ten_minutes(self) -> None:
        assert Settings().seat_hold_ttl_seconds == 600


class TestSettingsCache:
    def test_get_settings_returns_the_same_instance(self) -> None:
        """Caching avoids re-parsing .env on every request."""
        assert get_settings() is get_settings()

    def test_cache_clear_produces_a_fresh_instance(self) -> None:
        first = get_settings()
        get_settings.cache_clear()
        assert get_settings() is not first

    def test_cache_picks_up_new_environment_values(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Documents the footgun: you must clear the cache after changing env."""
        get_settings()
        monkeypatch.setenv("APP_DB_NAME", "changed_by_test")
        # Stale without clearing — this assertion documents the behaviour.
        assert get_settings().db_name != "changed_by_test"
        get_settings.cache_clear()
        assert get_settings().db_name == "changed_by_test"
