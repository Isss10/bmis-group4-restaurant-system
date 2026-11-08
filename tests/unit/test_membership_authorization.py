"""FR-MEM-02 across mounted modules, using real login-issued sessions.

SQLite verifies HTTP roles, ownership and persisted results, not MySQL locking.
Review order eligibility remains the review/ordering owners' separate contract;
these tests prove who can call that service, not that its current stub verifies orders.
"""

from __future__ import annotations

import secrets
from collections.abc import Generator
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import src.data.database as database
from src.application.reservation.models import Reservation, ReservationStatus
from src.application.reservation.repository import ReservationRepository
from src.application.review.exceptions import DishNotInOrderError
from src.common.config import Settings
from src.common.security import Role, hash_password
from src.data.database import Base, get_db
from src.data.schema.membership import AuthPolicyLock, User
from src.data.schema.review import Review
from src.presentation.api.main import create_app

ORIGIN = "http://localhost:5173"
WHEN = datetime(2026, 12, 24, 19, 30)
STAFF_OPERATIONS = [
    ("GET", "/api/v1/staff/reservations"),
    ("PATCH", "/api/v1/staff/reservations/1"),
    ("GET", "/api/v1/staff/orders"),
    ("PATCH", "/api/v1/staff/orders/1"),
]


@dataclass
class AuthorizationHarness:
    client: TestClient
    factory: sessionmaker[Session]
    password: str
    ids: dict[str, int]

    def login(self, name: str = "customer") -> dict[str, Any]:
        response = self.client.post(
            "/api/v1/auth/login",
            json={"email": f"{name}@example.com", "password": self.password},
            headers={"Origin": ORIGIN},
        )
        assert response.status_code == 200, response.text
        assert response.json()["code"] == 0
        return response.json()["data"]

    def bearer(self, login: dict[str, Any]) -> dict[str, str]:
        return {"Authorization": f"Bearer {login['access_token']}"}

    def booking(self, user_id: str | None = None) -> dict[str, Any]:
        body: dict[str, Any] = {"table_id": 7, "reservation_time": WHEN.isoformat()}
        if user_id is not None:
            body["user_id"] = user_id
        return body

    def review(self, customer_id: int | None = None) -> dict[str, Any]:
        return {
            "customer_id": customer_id if customer_id is not None else self.ids["customer"],
            "dish_id": 12,
            "order_id": 23,
            "rating": 4,
            "content": "Synthetic authorization test",
        }


@pytest.fixture(scope="session")
def authorization_credentials() -> tuple[str, str]:
    password = secrets.token_urlsafe(24)
    return password, hash_password(password)


@pytest.fixture
def authorization(
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
    authorization_credentials: tuple[str, str],
) -> Generator[AuthorizationHarness, None, None]:
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)
    password, hashed = authorization_credentials
    with factory() as session:
        users = {
            name: User(
                email_normalized=f"{name}@example.com",
                display_name=f"Test {name}",
                password_hash=hashed,
                role=Role.CUSTOMER if name == "other" else name,
            )
            for name in [*(role.value for role in Role), "other"]
        }
        session.add(AuthPolicyLock(id=1))
        session.add_all(users.values())
        session.commit()
        ids = {name: user.id for name, user in users.items()}
    # Reservation's existing repository uses session_scope; point it at the same
    # synthetic database as auth and reviews without changing production wiring.
    monkeypatch.setattr(database, "get_session_factory", lambda settings=None: factory)

    def review_session() -> Generator[Session, None, None]:
        with factory() as session:
            yield session

    app = create_app(settings.model_copy(update={"rate_limit_enabled": False}))
    app.state.membership_session_factory = factory
    app.dependency_overrides[get_db] = review_session
    try:
        with TestClient(
            app, base_url="https://testserver", raise_server_exceptions=False
        ) as client:
            yield AuthorizationHarness(client, factory, password, ids)
    finally:
        engine.dispose()


def assert_failure(response: Any, status: int, code: int) -> None:
    assert response.status_code == status, response.text
    body = response.json()
    assert body["code"] == code
    assert body["data"] is None
    assert body["request_id"] == response.headers["X-Request-ID"]
    if status == 401:
        assert response.headers["WWW-Authenticate"] == "Bearer"


@pytest.mark.parametrize("operation", ["create", "cancel", "review"])
def test_customer_writes_require_authentication(
    authorization: AuthorizationHarness, operation: str
) -> None:
    path, body = {
        "create": ("/api/v1/reservations", authorization.booking()),
        "cancel": ("/api/v1/reservations/1/cancel", None),
        "review": ("/api/v1/reviews/", authorization.review()),
    }[operation]
    assert_failure(authorization.client.post(path, json=body), 401, 30001)
    with authorization.factory() as session:
        assert session.scalar(select(func.count()).select_from(Reservation)) == 0
        assert session.scalar(select(func.count()).select_from(Review)) == 0


@pytest.mark.parametrize("role", [Role.WAITER, Role.MANAGER, Role.ADMIN])
def test_staff_roles_cannot_perform_customer_writes(
    authorization: AuthorizationHarness, role: Role
) -> None:
    login = authorization.login(role.value)
    headers = authorization.bearer(login)
    operations = [
        ("/api/v1/reservations", authorization.booking(str(authorization.ids[role.value]))),
        ("/api/v1/reservations/1/cancel", None),
        ("/api/v1/reviews/", authorization.review(authorization.ids[role.value])),
    ]
    for path, body in operations:
        assert_failure(authorization.client.post(path, json=body, headers=headers), 403, 30003)
    with authorization.factory() as session:
        assert session.scalar(select(func.count()).select_from(Reservation)) == 0
        assert session.scalar(select(func.count()).select_from(Review)) == 0


@pytest.mark.parametrize("include_legacy_user_id", [False, True])
def test_customer_booking_uses_verified_subject(
    authorization: AuthorizationHarness, include_legacy_user_id: bool
) -> None:
    login = authorization.login()
    user_id = str(authorization.ids["customer"])
    response = authorization.client.post(
        "/api/v1/reservations",
        json=authorization.booking(user_id if include_legacy_user_id else None),
        headers=authorization.bearer(login),
    )
    assert response.status_code == 200, response.text
    assert response.json()["code"] == 0
    with authorization.factory() as session:
        row = session.get(Reservation, response.json()["data"]["id"])
        assert row is not None and row.user_id == user_id


def test_customer_cannot_create_booking_for_another_identity(
    authorization: AuthorizationHarness,
) -> None:
    login = authorization.login()
    response = authorization.client.post(
        "/api/v1/reservations",
        json=authorization.booking(str(authorization.ids["other"])),
        headers=authorization.bearer(login),
    )
    assert_failure(response, 403, 30003)
    with authorization.factory() as session:
        assert session.scalar(select(func.count()).select_from(Reservation)) == 0


def test_cancel_checks_owner_before_persisting_any_change(
    authorization: AuthorizationHarness,
) -> None:
    customer = authorization.login()
    repo = ReservationRepository()
    other = repo.create(str(authorization.ids["other"]), 1, WHEN)
    own = repo.create(str(authorization.ids["customer"]), 2, WHEN)
    headers = authorization.bearer(customer)
    assert_failure(
        authorization.client.post(f"/api/v1/reservations/{other['id']}/cancel", headers=headers),
        403,
        30003,
    )
    response = authorization.client.post(
        f"/api/v1/reservations/{own['id']}/cancel", headers=headers
    )
    assert response.status_code == 200, response.text
    assert response.json()["data"] == {"status": "cancelled"}
    with authorization.factory() as session:
        other_row = session.get(Reservation, other["id"])
        own_row = session.get(Reservation, own["id"])
        assert other_row is not None and other_row.status == ReservationStatus.PENDING
        assert own_row is not None and own_row.status == ReservationStatus.CANCELLED
    assert_failure(
        authorization.client.post("/api/v1/reservations/999999/cancel", headers=headers),
        404,
        40001,
    )


def test_customer_review_cannot_spoof_another_customer(
    authorization: AuthorizationHarness, monkeypatch: pytest.MonkeyPatch
) -> None:
    customer = authorization.login()

    def must_not_submit(db: Session, payload: Any) -> Review:
        raise AssertionError("Spoofed identity reached the review business service")

    monkeypatch.setattr("src.presentation.api.routers.review.submit_review", must_not_submit)
    assert_failure(
        authorization.client.post(
            "/api/v1/reviews/",
            json=authorization.review(authorization.ids["other"]),
            headers=authorization.bearer(customer),
        ),
        403,
        30003,
    )
    with authorization.factory() as session:
        assert session.scalar(select(func.count()).select_from(Review)) == 0


def test_customer_review_reaches_existing_business_service_as_self(
    authorization: AuthorizationHarness,
) -> None:
    customer = authorization.login()
    response = authorization.client.post(
        "/api/v1/reviews/",
        json=authorization.review(),
        headers=authorization.bearer(customer),
    )
    # This proves authorization and delegation only: M9's current order checker
    # is a stub, so a 201 here is not evidence of completed-order eligibility.
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["code"] == 0
    assert body["request_id"] == response.headers["X-Request-ID"]
    assert body["data"]["customer_id"] == authorization.ids["customer"]
    with authorization.factory() as session:
        row = session.get(Review, body["data"]["id"])
        assert row is not None and row.customer_id == authorization.ids["customer"]
    ranking = authorization.client.get("/api/v1/reviews/dishes/ranking")
    assert ranking.status_code == 200, ranking.text
    assert ranking.json()["code"] == 0
    assert ranking.json()["data"][0]["dish_id"] == 12


def test_authorization_does_not_bypass_review_business_rejection(
    authorization: AuthorizationHarness, monkeypatch: pytest.MonkeyPatch
) -> None:
    customer = authorization.login()

    def reject_order(db: Session, payload: Any) -> Review:
        raise DishNotInOrderError("Synthetic ineligible order")

    monkeypatch.setattr("src.presentation.api.routers.review.submit_review", reject_order)
    response = authorization.client.post(
        "/api/v1/reviews/",
        json=authorization.review(),
        headers=authorization.bearer(customer),
    )
    assert_failure(response, 400, 10001)
    with authorization.factory() as session:
        assert session.scalar(select(func.count()).select_from(Review)) == 0


@pytest.mark.parametrize("role", list(Role))
def test_staff_endpoints_follow_four_role_matrix_and_logout_revocation(
    authorization: AuthorizationHarness, role: Role
) -> None:
    login = authorization.login(role.value)
    headers = authorization.bearer(login)
    for method, path in STAFF_OPERATIONS:
        response = authorization.client.request(method, path, headers=headers)
        if role == Role.CUSTOMER:
            assert_failure(response, 403, 30003)
        else:
            assert response.status_code == 200, response.text
            assert response.json()["code"] == 0
    logout = authorization.client.post(
        "/api/v1/auth/logout", headers={"Origin": ORIGIN, "X-CSRF-Token": login["csrf_token"]}
    )
    assert logout.status_code == 200, logout.text
    for method, path in STAFF_OPERATIONS:
        assert_failure(authorization.client.request(method, path, headers=headers), 401, 30002)


@pytest.mark.parametrize("target_role", [Role.CUSTOMER, Role.WAITER])
def test_admin_disabling_account_invalidates_cross_module_access(
    authorization: AuthorizationHarness, target_role: Role
) -> None:
    target = authorization.login(target_role.value)
    admin = authorization.login("admin")
    disabled = authorization.client.patch(
        f"/api/v1/users/{authorization.ids[target_role.value]}/status",
        headers=authorization.bearer(admin),
        json={"is_active": False, "version": 1},
    )
    assert disabled.status_code == 200, disabled.text
    headers = authorization.bearer(target)
    if target_role == Role.CUSTOMER:
        operations = [
            ("/api/v1/reservations", authorization.booking()),
            ("/api/v1/reservations/1/cancel", None),
            ("/api/v1/reviews/", authorization.review()),
        ]
        for path, body in operations:
            assert_failure(authorization.client.post(path, json=body, headers=headers), 401, 30002)
    else:
        for method, path in STAFF_OPERATIONS:
            assert_failure(authorization.client.request(method, path, headers=headers), 401, 30002)
