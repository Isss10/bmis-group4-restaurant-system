"""Shared pytest fixtures.

Tests must never need a real MySQL server to run — CI would become slow and
flaky, and contributors would skip running tests locally. The split is:

* **unit** (default): no database, no network. Always runs in CI.
* **integration**: needs MySQL. Skipped automatically unless
  `APP_DB_HOST` is set, so they run in Docker/CI-with-services and on a
  developer machine that has MySQL up, and are quietly skipped elsewhere.

Set the environment before importing application code, otherwise
`get_settings()` caches development values and every test reads the wrong
configuration.
"""

from __future__ import annotations

import os
import secrets
from collections.abc import Generator
from typing import Any

import pytest
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.sql.functions import now

@compiles(now, "sqlite")
def compile_now_sqlite(element, compiler, **kw):
    return "CURRENT_TIMESTAMP"

os.environ.setdefault("APP_ENVIRONMENT", "testing")
os.environ.setdefault("APP_JWT_SECRET_KEY", secrets.token_urlsafe(48))
os.environ.setdefault("APP_DB_NAME", "restaurant_test")
os.environ.setdefault("APP_CORS_ORIGINS", "http://localhost:5173")

from fastapi.testclient import TestClient

from src.common.config import Settings, get_settings
from src.common.security import Role, create_access_token
from src.presentation.api.main import create_app


@pytest.fixture(autouse=True)
def _reset_settings_cache() -> Generator[None, None, None]:
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def settings() -> Settings:
    return get_settings()


@pytest.fixture
def app(settings: Settings) -> Any:
    return create_app(settings)


@pytest.fixture
def client(app: Any) -> Generator[TestClient, None, None]:
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client


def _make_token(role: Role, user_id: str = "1") -> str:
    return create_access_token(user_id=user_id, role=role).access_token


@pytest.fixture
def customer_token() -> str:
    return _make_token(Role.CUSTOMER)


@pytest.fixture
def waiter_token() -> str:
    return _make_token(Role.WAITER, user_id="101")


@pytest.fixture
def manager_token() -> str:
    return _make_token(Role.MANAGER, user_id="201")


@pytest.fixture
def admin_token() -> str:
    return _make_token(Role.ADMIN, user_id="901")


@pytest.fixture
def auth_headers() -> Any:

    def _build(role: Role, user_id: str = "1") -> dict[str, str]:
        return {"Authorization": f"Bearer {_make_token(role, user_id)}"}

    return _build


@pytest.fixture
def db_session() -> Generator[Any, None, None]:
    if not os.environ.get("APP_DB_HOST"):
        pytest.skip(
            "Integration test requires MySQL. Set APP_DB_HOST (and APP_DB_NAME to a "
            "scratch database) to run it."
        )

    from sqlalchemy.orm import Session

    from src.data.database import Base, get_engine, get_session_factory

    engine = get_engine()
    Base.metadata.create_all(engine)
    factory = get_session_factory()
    session: Session = factory()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(engine)
        from src.data.database import reset_engine

        reset_engine()
