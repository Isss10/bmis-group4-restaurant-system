"""HTTP acceptance tests for Member10 authentication and account management.

SQLite here verifies sequential HTTP, authorisation, persisted state and rollback
behaviour. It does not prove MySQL row-lock or concurrent transaction behaviour;
those guarantees require the separate real-MySQL integration/concurrency suite.
"""

from __future__ import annotations

import json
import secrets
from collections.abc import Generator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from src.application.membership.service import MembershipError, MembershipService
from src.common.audit import AuditLog
from src.common.config import Settings
from src.common.security import (
    Role,
    TokenPayload,
    create_access_token,
    hash_password,
    verify_password,
)
from src.data.database import Base
from src.data.repository.membership import MembershipRepository
from src.data.schema.membership import AuthPolicyLock, AuthSession, UsedRefreshToken, User
from src.presentation.api.main import create_app

ORIGIN = "http://localhost:5173"
REFRESH_COOKIE = "restaurant_refresh"
USER_FIELDS = {"id", "email", "display_name", "role", "is_active", "version"}
ACCOUNT_MUTATIONS = ("user.created", "user.role_changed", "user.status_changed")


@dataclass
class AuthHarness:
    client: TestClient
    factory: sessionmaker[Session]
    settings: Settings
    password: str
    user_ids: dict[Role, int]

    def login(self, role: Role = Role.CUSTOMER) -> dict[str, Any]:
        response = self.client.post(
            "/api/v1/auth/login",
            json={"email": f"{role.value}@example.com", "password": self.password},
            headers={"Origin": ORIGIN},
        )
        assert response.status_code == 200, response.text
        return response.json()

    def bearer(self, data: dict[str, Any]) -> dict[str, str]:
        return {"Authorization": f"Bearer {data['access_token']}"}

    def cookie_headers(self, refresh: str, csrf: str) -> dict[str, str]:
        return {
            "Origin": ORIGIN,
            "X-CSRF-Token": csrf,
            "Cookie": f"{REFRESH_COOKIE}={refresh}",
        }


@pytest.fixture(scope="session")
def membership_password() -> str:
    return secrets.token_urlsafe(24)


@pytest.fixture(scope="session")
def membership_password_hash(membership_password: str) -> str:
    return hash_password(membership_password)


@pytest.fixture
def auth_harness(
    settings: Settings, membership_password: str, membership_password_hash: str
) -> Generator[AuthHarness, None, None]:
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)
    with factory() as session:
        session.add(AuthPolicyLock(id=1))
        users = {
            role: User(
                email_normalized=f"{role.value}@example.com",
                display_name=f"Test {role.value}",
                password_hash=membership_password_hash,
                role=role.value,
                is_active=True,
                auth_version=1,
            )
            for role in Role
        }
        session.add_all(users.values())
        session.commit()
        user_ids = {role: user.id for role, user in users.items()}
    cfg = settings.model_copy(update={"rate_limit_enabled": False})
    app = create_app(cfg)
    app.state.membership_session_factory = factory
    try:
        with TestClient(
            app, base_url="https://testserver", raise_server_exceptions=False
        ) as client:
            yield AuthHarness(client, factory, cfg, membership_password, user_ids)
    finally:
        engine.dispose()


def assert_error(response: Any, status: int) -> dict[str, Any]:
    assert response.status_code == status, response.text
    body = response.json()
    assert "error" in body
    error = body["error"]
    assert error["code"] == status
    assert error["message"]
    assert error["request_id"] == response.headers["X-Request-ID"]
    if status == 401:
        assert response.headers["WWW-Authenticate"] == "Bearer"
    return error


def register_body(harness: AuthHarness, **changes: Any) -> dict[str, Any]:
    return {
        "email": "new.customer@example.com",
        "password": harness.password,
        "display_name": "New Customer",
        **changes,
    }


def account_audit_count(session: Session) -> int:
    return (
        session.scalar(
            select(func.count()).select_from(AuditLog).where(AuditLog.action.in_(ACCOUNT_MUTATIONS))
        )
        or 0
    )


def test_registration_persists_only_password_hash_and_customer_role(
    auth_harness: AuthHarness,
) -> None:
    response = auth_harness.client.post(
        "/api/v1/auth/register",
        json=register_body(auth_harness, email="New.Customer@EXAMPLE.COM"),
    )
    assert response.status_code == 201, response.text
    user = response.json()
    assert set(user) == USER_FIELDS
    assert user["email"] == "new.customer@example.com"
    assert user["role"] == "customer"
    assert user["is_active"] is True
    assert user["version"] == 1
    assert auth_harness.password not in response.text
    with auth_harness.factory() as session:
        stored = session.get(User, user["id"])
        assert stored is not None
        assert stored.password_hash != auth_harness.password
        assert verify_password(auth_harness.password, stored.password_hash)
        assert stored.role == "customer"
        assert session.scalar(select(func.count()).select_from(User)) == 5


@pytest.mark.parametrize(
    "extra", [{"role": "admin"}, {"role": "waiter"}, {"is_active": True}, {"auth_version": 99}]
)
def test_public_registration_rejects_privileged_fields(
    auth_harness: AuthHarness, extra: dict[str, Any]
) -> None:
    response = auth_harness.client.post(
        "/api/v1/auth/register", json=register_body(auth_harness, **extra)
    )
    assert_error(response, 422)
    with auth_harness.factory() as session:
        assert session.scalar(select(func.count()).select_from(User)) == 4


@pytest.mark.parametrize(
    "changes",
    [
        {"email": "not-an-email"},
        {"display_name": " "},
        {"display_name": "x" * 81},
        {"password": "short"},
        {"password": "\u5bc6" * 25},
        {"password": "x" * 73},
    ],
)
def test_invalid_registration_leaves_database_unchanged(
    auth_harness: AuthHarness, changes: dict[str, str]
) -> None:
    response = auth_harness.client.post(
        "/api/v1/auth/register", json=register_body(auth_harness, **changes)
    )
    assert_error(response, 422)
    assert auth_harness.password not in response.text
    with auth_harness.factory() as session:
        assert session.scalar(select(func.count()).select_from(User)) == 4


def test_duplicate_registration_is_a_controlled_conflict(auth_harness: AuthHarness) -> None:
    response = auth_harness.client.post(
        "/api/v1/auth/register",
        json=register_body(auth_harness, email="CUSTOMER@EXAMPLE.COM"),
    )
    assert_error(response, 409)
    with auth_harness.factory() as session:
        assert session.scalar(select(func.count()).select_from(User)) == 4


@pytest.mark.parametrize("role", list(Role))
def test_four_roles_login_and_resolve_only_their_own_identity(
    auth_harness: AuthHarness, role: Role
) -> None:
    login = auth_harness.login(role)
    assert login["token_type"] == "bearer"
    assert login["expires_in"] == 3600
    assert login["user"]["id"] == auth_harness.user_ids[role]
    assert login["user"]["role"] == role.value
    identity = auth_harness.client.get(
        "/api/v1/auth/me", headers=auth_harness.bearer(login), params={"user_id": "9999"}
    )
    assert identity.status_code == 200, identity.text
    assert set(identity.json()) == {"user_id", "role", "token_id", "expires_at"}
    assert identity.json()["user_id"] == str(auth_harness.user_ids[role])
    assert identity.json()["role"] == role.value
    profile = auth_harness.client.get(
        "/api/v1/membership/profile", headers=auth_harness.bearer(login)
    )
    assert profile.status_code == 200, profile.text
    assert set(profile.json()) == USER_FIELDS
    assert profile.json()["id"] == auth_harness.user_ids[role]


def test_login_failure_does_not_disclose_account_existence(auth_harness: AuthHarness) -> None:
    failures = []
    for email in ("customer@example.com", "unknown@example.com"):
        response = auth_harness.client.post(
            "/api/v1/auth/login",
            json={"email": email, "password": secrets.token_urlsafe(24)},
        )
        error = assert_error(response, 401)
        failures.append((error["code"], error["message"]))
        assert REFRESH_COOKIE not in response.headers.get("Set-Cookie", "")
        assert "access_token" not in response.json()
    assert failures[0] == failures[1]
    with auth_harness.factory() as session:
        assert session.scalar(select(func.count()).select_from(AuthSession)) == 0


@pytest.mark.parametrize("path", ["/api/v1/auth/me", "/api/v1/membership/profile", "/api/v1/users"])
def test_protected_endpoints_require_authentication(auth_harness: AuthHarness, path: str) -> None:
    assert_error(auth_harness.client.get(path), 401)


@pytest.mark.parametrize("kind", ["forged", "expired", "missing_claim", "unknown_role"])
def test_invalid_access_token_fails_closed(auth_harness: AuthHarness, kind: str) -> None:
    login = auth_harness.login()
    claims = jwt.decode(
        login["access_token"], auth_harness.settings.jwt_secret_key, algorithms=["HS256"]
    )
    key = auth_harness.settings.jwt_secret_key
    if kind == "forged":
        key = secrets.token_urlsafe(48)
    elif kind == "expired":
        claims["exp"] = int((datetime.now(UTC) - timedelta(minutes=1)).timestamp())
    elif kind == "missing_claim":
        del claims["sub"]
    else:
        claims["role"] = "superuser"
    invalid = jwt.encode(claims, key, algorithm="HS256")
    response = auth_harness.client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {invalid}"}
    )
    assert_error(response, 401)


def test_legacy_token_without_persisted_session_is_rejected(auth_harness: AuthHarness) -> None:
    legacy = create_access_token(
        user_id=auth_harness.user_ids[Role.ADMIN], role=Role.ADMIN, settings=auth_harness.settings
    )
    response = auth_harness.client.get(
        "/api/v1/users", headers={"Authorization": f"Bearer {legacy.access_token}"}
    )
    assert_error(response, 401)


def test_login_rate_limit_returns_controlled_429(
    auth_harness: AuthHarness, monkeypatch: pytest.MonkeyPatch
) -> None:
    limiter = auth_harness.client.app.state.limiter
    limiter.reset()
    monkeypatch.setattr(limiter, "enabled", True)
    for _ in range(5):
        response = auth_harness.client.post(
            "/api/v1/auth/login",
            json={"email": "customer@example.com", "password": secrets.token_urlsafe(24)},
        )
        assert_error(response, 401)
    limited = auth_harness.client.post(
        "/api/v1/auth/login",
        json={"email": "customer@example.com", "password": auth_harness.password},
    )
    assert_error(limited, 429)
    assert int(limited.headers["Retry-After"]) > 0
    assert limited.headers["Cache-Control"] == "no-store"
    assert REFRESH_COOKIE not in limited.headers.get("Set-Cookie", "")
    with auth_harness.factory() as session:
        assert session.scalar(select(func.count()).select_from(AuthSession)) == 0


def test_refresh_rotates_cookie_and_replay_revokes_session(auth_harness: AuthHarness) -> None:
    login = auth_harness.login()
    old_refresh = auth_harness.client.cookies[REFRESH_COOKIE]
    headers = auth_harness.cookie_headers(old_refresh, login["csrf_token"])
    refreshed = auth_harness.client.post("/api/v1/auth/refresh", headers=headers)
    assert refreshed.status_code == 200, refreshed.text
    current = refreshed.json()
    assert current["access_token"] != login["access_token"]
    assert auth_harness.client.cookies[REFRESH_COOKIE] != old_refresh
    assert (
        auth_harness.client.get("/api/v1/auth/me", headers=auth_harness.bearer(current)).status_code
        == 200
    )
    with auth_harness.factory() as session:
        assert session.scalar(select(func.count()).select_from(UsedRefreshToken)) == 1
        assert session.scalar(select(func.count()).select_from(AuthSession)) == 1
    assert_error(auth_harness.client.post("/api/v1/auth/refresh", headers=headers), 401)
    assert_error(
        auth_harness.client.get("/api/v1/auth/me", headers=auth_harness.bearer(current)), 401
    )
    with auth_harness.factory() as session:
        stored = session.scalar(select(AuthSession))
        assert stored is not None and stored.revoked_at is not None


def test_refresh_token_cannot_be_used_as_access_token(auth_harness: AuthHarness) -> None:
    auth_harness.login()
    refresh = auth_harness.client.cookies[REFRESH_COOKIE]
    assert_error(
        auth_harness.client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {refresh}"}),
        401,
    )


def test_expired_refresh_does_not_issue_new_session(auth_harness: AuthHarness) -> None:
    login = auth_harness.login()
    with auth_harness.factory() as session:
        stored = session.scalar(select(AuthSession))
        assert stored is not None
        stored.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        session.commit()
    response = auth_harness.client.post(
        "/api/v1/auth/refresh",
        headers=auth_harness.cookie_headers(
            auth_harness.client.cookies[REFRESH_COOKIE], login["csrf_token"]
        ),
    )
    assert_error(response, 401)
    with auth_harness.factory() as session:
        assert session.scalar(select(func.count()).select_from(AuthSession)) == 1
        assert session.scalar(select(func.count()).select_from(UsedRefreshToken)) == 0


@pytest.mark.parametrize("endpoint", ["refresh", "logout"])
@pytest.mark.parametrize("failure", ["missing_csrf", "wrong_csrf", "external_origin", "cross_site"])
def test_cookie_mutations_reject_cross_site_or_missing_csrf(
    auth_harness: AuthHarness, endpoint: str, failure: str
) -> None:
    login = auth_harness.login()
    headers = auth_harness.cookie_headers(
        auth_harness.client.cookies[REFRESH_COOKIE], login["csrf_token"]
    )
    if failure == "missing_csrf":
        del headers["X-CSRF-Token"]
    elif failure == "wrong_csrf":
        headers["X-CSRF-Token"] = secrets.token_urlsafe(24)
    elif failure == "external_origin":
        headers["Origin"] = "https://untrusted.example.com"
    else:
        headers["Sec-Fetch-Site"] = "cross-site"
    response = auth_harness.client.post(f"/api/v1/auth/{endpoint}", headers=headers)
    assert_error(response, 403)
    assert (
        auth_harness.client.get("/api/v1/auth/me", headers=auth_harness.bearer(login)).status_code
        == 200
    )
    with auth_harness.factory() as session:
        stored = session.scalar(select(AuthSession))
        assert stored is not None and stored.revoked_at is None
        assert session.scalar(select(func.count()).select_from(UsedRefreshToken)) == 0


def test_csrf_endpoint_supports_reload_without_disclosing_refresh_token(
    auth_harness: AuthHarness,
) -> None:
    login = auth_harness.login()
    refresh = auth_harness.client.cookies[REFRESH_COOKIE]
    response = auth_harness.client.get("/api/v1/auth/csrf", headers={"Origin": ORIGIN})
    assert response.status_code == 200, response.text
    assert response.json() == {"csrf_token": login["csrf_token"]}
    assert refresh not in response.text
    assert response.headers["Cache-Control"] == "no-store"
    assert_error(
        auth_harness.client.get(
            "/api/v1/auth/csrf", headers={"Origin": "https://untrusted.example.com"}
        ),
        403,
    )


def test_logout_is_idempotent_and_only_revokes_current_session(auth_harness: AuthHarness) -> None:
    other_session = auth_harness.login()
    current = auth_harness.login()
    refresh = auth_harness.client.cookies[REFRESH_COOKIE]
    headers = auth_harness.cookie_headers(refresh, current["csrf_token"])
    response = auth_harness.client.post("/api/v1/auth/logout", headers=headers)
    assert response.status_code == 200, response.text
    assert response.json() == {"logged_out": True}
    assert "Max-Age=0" in response.headers["Set-Cookie"]
    repeated = auth_harness.client.post("/api/v1/auth/logout", headers=headers)
    assert repeated.status_code == 200
    assert_error(
        auth_harness.client.get("/api/v1/auth/me", headers=auth_harness.bearer(current)), 401
    )
    assert_error(auth_harness.client.post("/api/v1/auth/refresh", headers=headers), 401)
    assert (
        auth_harness.client.get(
            "/api/v1/auth/me", headers=auth_harness.bearer(other_session)
        ).status_code
        == 200
    )


@pytest.mark.parametrize("role", [Role.CUSTOMER, Role.WAITER, Role.MANAGER])
def test_non_admin_cannot_manage_accounts(auth_harness: AuthHarness, role: Role) -> None:
    login = auth_harness.login(role)
    headers = auth_harness.bearer(login)
    target = auth_harness.user_ids[Role.CUSTOMER]
    responses = [
        auth_harness.client.get("/api/v1/users", headers=headers),
        auth_harness.client.post(
            "/api/v1/users",
            headers=headers,
            json=register_body(auth_harness, role="admin"),
        ),
        auth_harness.client.patch(
            f"/api/v1/users/{target}/role",
            headers=headers,
            json={"role": "admin", "version": 1},
        ),
        auth_harness.client.patch(
            f"/api/v1/users/{target}/status",
            headers=headers,
            json={"is_active": False, "version": 1},
        ),
    ]
    for response in responses:
        assert_error(response, 403)
    with auth_harness.factory() as session:
        customer = session.get(User, target)
        assert customer is not None
        assert customer.role == "customer" and customer.is_active
        assert session.scalar(select(func.count()).select_from(User)) == 4
        assert account_audit_count(session) == 0


def test_admin_creates_employee_with_audit_and_safe_paginated_listing(
    auth_harness: AuthHarness,
) -> None:
    admin = auth_harness.login(Role.ADMIN)
    headers = {**auth_harness.bearer(admin), "X-Request-ID": "a" * 32}
    created = auth_harness.client.post(
        "/api/v1/users",
        headers=headers,
        json=register_body(auth_harness, email="new.waiter@example.com", role="waiter"),
    )
    assert created.status_code == 201, created.text
    assert set(created.json()) == USER_FIELDS
    assert created.json()["role"] == "waiter"
    listing = auth_harness.client.get(
        "/api/v1/users", headers=headers, params={"page": 2, "page_size": 2}
    )
    assert listing.status_code == 200, listing.text
    page = listing.json()
    assert (page["total"], page["page"], page["page_size"], len(page["items"])) == (5, 2, 2, 2)
    assert all(set(user) == USER_FIELDS for user in page["items"])
    with auth_harness.factory() as session:
        audit = session.scalar(select(AuditLog).where(AuditLog.action == "user.created"))
        assert audit is not None
        assert audit.action == "user.created"
        assert audit.actor_id == str(auth_harness.user_ids[Role.ADMIN])
        assert audit.entity_id == str(created.json()["id"])
        assert audit.request_id == "a" * 32
        assert auth_harness.password not in json.dumps(audit.after)


@pytest.mark.parametrize(
    ("operation", "change", "expected_role", "expected_active"),
    [
        ("role", {"role": "waiter"}, "waiter", True),
        ("status", {"is_active": False}, "customer", False),
    ],
)
def test_admin_changes_revoke_old_tokens_and_audit_the_same_change(
    auth_harness: AuthHarness,
    operation: str,
    change: dict[str, Any],
    expected_role: str,
    expected_active: bool,
) -> None:
    previous = auth_harness.login()
    previous_refresh = auth_harness.client.cookies[REFRESH_COOKIE]
    admin = auth_harness.login(Role.ADMIN)
    target = auth_harness.user_ids[Role.CUSTOMER]
    response = auth_harness.client.patch(
        f"/api/v1/users/{target}/{operation}",
        headers={**auth_harness.bearer(admin), "X-Request-ID": "b" * 32},
        json={**change, "version": 1},
    )
    assert response.status_code == 200, response.text
    assert response.json()["version"] == 2
    assert response.json()["role"] == expected_role
    assert response.json()["is_active"] is expected_active
    assert_error(
        auth_harness.client.get("/api/v1/auth/me", headers=auth_harness.bearer(previous)), 401
    )
    assert_error(
        auth_harness.client.post(
            "/api/v1/auth/refresh",
            headers=auth_harness.cookie_headers(previous_refresh, previous["csrf_token"]),
        ),
        401,
    )
    with auth_harness.factory() as session:
        user = session.get(User, target)
        assert user is not None and user.auth_version == 2
        audit = session.scalar(
            select(AuditLog).where(AuditLog.action == f"user.{operation}_changed")
        )
        assert audit is not None
        assert audit.before == {"role": "customer", "is_active": True}
        assert audit.after == {"role": expected_role, "is_active": expected_active}
        assert audit.actor_id == str(auth_harness.user_ids[Role.ADMIN])
        assert audit.request_id == "b" * 32
    relogin = auth_harness.client.post(
        "/api/v1/auth/login",
        json={"email": "customer@example.com", "password": auth_harness.password},
    )
    if expected_active:
        assert relogin.status_code == 200, relogin.text
        assert relogin.json()["user"]["role"] == expected_role
    else:
        assert_error(relogin, 401)


@pytest.mark.parametrize(
    ("operation", "change"), [("role", {"role": "customer"}), ("status", {"is_active": False})]
)
def test_last_active_admin_cannot_be_removed(
    auth_harness: AuthHarness, operation: str, change: dict[str, Any]
) -> None:
    admin = auth_harness.login(Role.ADMIN)
    target = auth_harness.user_ids[Role.ADMIN]
    response = auth_harness.client.patch(
        f"/api/v1/users/{target}/{operation}",
        headers=auth_harness.bearer(admin),
        json={**change, "version": 1},
    )
    assert_error(response, 409)
    assert (
        auth_harness.client.get("/api/v1/users", headers=auth_harness.bearer(admin)).status_code
        == 200
    )
    with auth_harness.factory() as session:
        user = session.get(User, target)
        assert user is not None and user.role == "admin" and user.is_active
        assert user.version == 1
        assert account_audit_count(session) == 0


def test_stale_version_does_not_mutate_user_or_create_audit(auth_harness: AuthHarness) -> None:
    admin = auth_harness.login(Role.ADMIN)
    target = auth_harness.user_ids[Role.CUSTOMER]
    response = auth_harness.client.patch(
        f"/api/v1/users/{target}/role",
        headers=auth_harness.bearer(admin),
        json={"role": "waiter", "version": 999},
    )
    assert_error(response, 409)
    with auth_harness.factory() as session:
        user = session.get(User, target)
        assert user is not None and user.role == "customer" and user.version == 1
        assert account_audit_count(session) == 0


def test_audit_failure_rolls_back_account_and_session_changes(
    auth_harness: AuthHarness, monkeypatch: pytest.MonkeyPatch
) -> None:
    customer = auth_harness.login()
    admin = auth_harness.login(Role.ADMIN)
    target = auth_harness.user_ids[Role.CUSTOMER]

    def fail_audit(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("Injected audit failure")

    monkeypatch.setattr("src.application.membership.service.record_audit", fail_audit)
    response = auth_harness.client.patch(
        f"/api/v1/users/{target}/status",
        headers=auth_harness.bearer(admin),
        json={"is_active": False, "version": 1},
    )
    assert_error(response, 500)
    assert "Injected audit failure" not in response.text
    with auth_harness.factory() as session:
        user = session.get(User, target)
        assert user is not None and user.is_active and user.version == 1
        assert user.auth_version == 1
        assert account_audit_count(session) == 0
        active = session.scalars(select(AuthSession).where(AuthSession.user_id == target)).all()
        assert active and all(item.revoked_at is None for item in active)
    assert (
        auth_harness.client.get(
            "/api/v1/auth/me", headers=auth_harness.bearer(customer)
        ).status_code
        == 200
    )


def test_permission_revoked_after_guard_is_a_controlled_401(
    auth_harness: AuthHarness, monkeypatch: pytest.MonkeyPatch
) -> None:
    admin = auth_harness.login(Role.ADMIN)
    original_validator = auth_harness.client.app.state.auth_validator

    def revoke_after_authorisation(identity: TokenPayload) -> None:
        original_validator(identity)
        # Simulate another committed admin operation after the HTTP guard ran,
        # before the account service obtains its write lock and rechecks auth.
        with auth_harness.factory() as session:
            user = session.get(User, auth_harness.user_ids[Role.ADMIN])
            assert user is not None
            user.auth_version += 1
            session.commit()

    monkeypatch.setattr(auth_harness.client.app.state, "auth_validator", revoke_after_authorisation)
    response = auth_harness.client.post(
        "/api/v1/users",
        headers=auth_harness.bearer(admin),
        json=register_body(auth_harness, role="waiter"),
    )
    assert_error(response, 401)
    with auth_harness.factory() as session:
        assert session.scalar(select(func.count()).select_from(User)) == 4
        assert account_audit_count(session) == 0


def test_bootstrap_creates_first_admin_once(membership_password: str, settings: Settings) -> None:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)
    try:
        with factory() as session:
            session.add(AuthPolicyLock(id=1))
            session.commit()
            svc = MembershipService(MembershipRepository(session), settings)
            created = svc.bootstrap_admin(
                "first.admin@example.com", membership_password, "First Administrator"
            )
            assert created["role"] == "admin" and created["is_active"]
            assert set(created) == USER_FIELDS
            with pytest.raises(MembershipError) as denied:
                svc.bootstrap_admin("second.admin@example.com", membership_password, "Second Admin")
            assert denied.value.status == 409
        with factory() as session:
            assert session.scalar(select(func.count()).select_from(User)) == 1
            audit = session.scalar(select(AuditLog).where(AuditLog.action == "user.bootstrap"))
            assert audit is not None and audit.entity_id == str(created["id"])
            stored = session.get(User, created["id"])
            assert stored is not None
            assert verify_password(membership_password, stored.password_hash)
    finally:
        engine.dispose()


def test_bootstrap_refuses_database_with_existing_accounts(auth_harness: AuthHarness) -> None:
    with auth_harness.factory() as session:
        svc = MembershipService(MembershipRepository(session), auth_harness.settings)
        with pytest.raises(MembershipError) as denied:
            svc.bootstrap_admin("bootstrap@example.com", auth_harness.password, "Not Allowed")
        assert denied.value.status == 409
        assert session.scalar(select(func.count()).select_from(User)) == 4
        assert (
            session.scalar(
                select(func.count())
                .select_from(AuditLog)
                .where(AuditLog.action == "user.bootstrap")
            )
            == 0
        )


def test_session_material_is_not_exposed_in_profile_or_stored_as_plaintext(
    auth_harness: AuthHarness,
) -> None:
    login = auth_harness.login()
    raw_refresh = auth_harness.client.cookies[REFRESH_COOKIE]
    claims = jwt.decode(
        login["access_token"], auth_harness.settings.jwt_secret_key, algorithms=["HS256"]
    )
    assert not ({"email", "display_name", "password", "password_hash"} & set(claims))
    with auth_harness.factory() as session:
        stored = session.scalar(select(AuthSession))
        assert stored is not None
        assert stored.current_refresh_digest != raw_refresh
        assert len(stored.current_refresh_digest) == 64
    profile = auth_harness.client.get(
        "/api/v1/membership/profile", headers=auth_harness.bearer(login)
    )
    assert raw_refresh not in profile.text
    assert login["access_token"] not in profile.text
    assert auth_harness.password not in profile.text
    assert set(profile.json()) == USER_FIELDS


def test_sensitive_success_responses_disable_caching(auth_harness: AuthHarness) -> None:
    registered = auth_harness.client.post("/api/v1/auth/register", json=register_body(auth_harness))
    login_response = auth_harness.client.post(
        "/api/v1/auth/login",
        json={"email": "customer@example.com", "password": auth_harness.password},
    )
    assert login_response.status_code == 200
    data = login_response.json()
    cookie = login_response.headers["Set-Cookie"]
    assert "HttpOnly" in cookie
    assert "SameSite=strict" in cookie
    assert "Path=/api/v1/auth" in cookie
    csrf = auth_harness.client.get("/api/v1/auth/csrf", headers={"Origin": ORIGIN})
    profile = auth_harness.client.get(
        "/api/v1/membership/profile", headers=auth_harness.bearer(data)
    )
    refreshed = auth_harness.client.post(
        "/api/v1/auth/refresh", headers={"Origin": ORIGIN, "X-CSRF-Token": data["csrf_token"]}
    )
    assert refreshed.status_code == 200
    logged_out = auth_harness.client.post(
        "/api/v1/auth/logout",
        headers={"Origin": ORIGIN, "X-CSRF-Token": refreshed.json()["csrf_token"]},
    )
    for response in (registered, login_response, csrf, profile, refreshed, logged_out):
        assert response.status_code in {200, 201}, response.text
        assert response.headers["Cache-Control"] == "no-store"
        assert response.headers["Pragma"] == "no-cache"
