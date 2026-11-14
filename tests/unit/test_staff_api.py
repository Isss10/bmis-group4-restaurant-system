"""Unit tests for the staff back-office endpoints (Objective b, member3).

Why these exist
---------------
PR #4 shipped the staff router with placeholder handlers; PR #13's contract
alignment then fixed the path, envelope and auth guard but explicitly left
"wiring them to the reservation and order services" to the staff module owner.
This branch performs that wiring for the reservation endpoints, and these
tests pin the new behaviour:

* the list endpoint returns what the reservation repository actually holds,
  oldest first — not mock data;
* the status patch really flips the row in the database;
* missing reservations surface as the frozen 404/40001 envelope;
* the require_staff() guard still rejects customers and anonymous callers
  (OWASP A01 — the endpoints must not quietly become public again);
* the order endpoints stay honest placeholders until the ordering module
  ships a backend (an empty list reads as "nothing to show", a patch on any
  order id reads as "no such order", because none can exist yet).

Scope
-----
SQLite in-memory only, so this runs in the unit job with no MySQL and no
network. The database wiring mirrors ``test_reservation_repository.py``: the
module-level engine/factory singletons are swapped for an in-memory engine
with ``StaticPool`` (one shared connection, so the session that writes is the
session that reads) and restored afterwards.
"""

from __future__ import annotations

from collections.abc import Generator
from datetime import datetime

import pytest
from fastapi import status
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import src.data.database as db
from src.application.reservation.models import Reservation, ReservationStatus
from src.application.reservation.repository import ReservationRepository
from src.common.config import Settings
from src.common.security import Role
from src.presentation.api.main import create_app

# Fixed literal timestamps keep the ordering assertions exact.
_EARLY = datetime(2026, 12, 24, 18, 0)
_LATE = datetime(2026, 12, 24, 19, 30)

RESERVATIONS_URL = "/api/v1/staff/reservations"
ORDERS_URL = "/api/v1/staff/orders"


@pytest.fixture
def reservation_db() -> Generator[sessionmaker[Session], None, None]:
    """Point the app's session factory at a shared in-memory SQLite database.

    Yields the *factory* (not a live session): the app's shutdown hook runs
    ``reset_engine()`` when the TestClient closes, which disposes this engine,
    so any session still open at fixture teardown would explode with
    "cannot operate on a closed database". Tests that need to inspect rows
    open a short-lived session with ``with reservation_db() as session:`` and
    let it close inside the test body. Same singleton-swap pattern as
    ``test_reservation_repository.py``, adjusted for the TestClient lifetime.
    """
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    # Only the reservations table is needed; other models use MySQL-specific
    # types that SQLite cannot render, and these tests do not touch them.
    Reservation.__table__.create(engine)
    factory = sessionmaker(bind=engine, class_=Session, expire_on_commit=False)

    saved_engine, saved_factory = db._engine, db._session_factory
    db._engine = engine
    db._session_factory = factory

    try:
        yield factory
    finally:
        # reset_engine() in the app's shutdown hook has already disposed the
        # engine and nulled the singletons by this point; restore whatever was
        # there before and dispose again (idempotent) for symmetry.
        db._engine, db._session_factory = saved_engine, saved_factory
        engine.dispose()


@pytest.fixture
def client(
    reservation_db: sessionmaker[Session], settings: Settings
) -> Generator[TestClient, None, None]:
    """A TestClient whose app reads and writes the fixture's SQLite database.

    ``create_app`` installs the membership module's ``auth_validator``, which
    requires session-scoped tokens (``sid`` + ``auth_version``) backed by the
    membership tables. That is the membership module's concern, not the staff
    module's: these tests exercise the staff router's own behaviour — the
    reservation wiring, the frozen envelope and the ``require_staff()`` role
    guard — so the validator is switched off and JWT signature verification
    (still fully active in ``get_current_token``) runs against the plain
    role-only tokens minted by the ``auth_headers`` fixture. Keeping the
    membership DB out is what keeps this file in the fast, MySQL-free unit
    job; the login-flow integration belongs to the membership suite.
    """
    app = create_app(settings)
    app.state.auth_validator = None
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def waiter_headers(auth_headers) -> dict[str, str]:
    return auth_headers(Role.WAITER, user_id="101")


class TestListReservations:
    def test_returns_persisted_rows_oldest_first(self, client, waiter_headers) -> None:
        repo = ReservationRepository()
        late = repo.create(user_id="u-1", table_id=7, reservation_time=_LATE)
        early = repo.create(user_id="u-2", table_id=3, reservation_time=_EARLY)

        response = client.get(RESERVATIONS_URL, headers=waiter_headers)

        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert body["code"] == 0
        assert [row["id"] for row in body["data"]] == [early["id"], late["id"]]
        first = body["data"][0]
        assert first["user_id"] == "u-2"
        assert first["table_id"] == 3
        assert first["status"] == "PENDING"
        # Naive datetimes serialise as ISO-8601 without an offset.
        assert first["reservation_time"] == "2026-12-24T18:00:00"

    def test_empty_database_returns_an_empty_list(self, client, waiter_headers) -> None:
        response = client.get(RESERVATIONS_URL, headers=waiter_headers)

        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert body["code"] == 0
        assert body["data"] == []

    def test_manager_is_also_allowed(self, client, auth_headers) -> None:
        response = client.get(RESERVATIONS_URL, headers=auth_headers(Role.MANAGER, user_id="201"))

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["code"] == 0

    def test_customer_is_rejected(self, client, auth_headers) -> None:
        response = client.get(RESERVATIONS_URL, headers=auth_headers(Role.CUSTOMER))

        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert response.json()["code"] == 30003

    def test_anonymous_is_rejected(self, client) -> None:
        response = client.get(RESERVATIONS_URL)

        assert response.status_code == status.HTTP_401_UNAUTHORIZED
        assert response.json()["code"] == 30001


class TestUpdateReservationStatus:
    def test_patch_persists_the_new_status(
        self, client, waiter_headers, reservation_db: sessionmaker[Session]
    ) -> None:
        created = ReservationRepository().create(user_id="u-9", table_id=5, reservation_time=_EARLY)

        response = client.patch(
            f"{RESERVATIONS_URL}/{created['id']}",
            json={"status": "CONFIRMED"},
            headers=waiter_headers,
        )

        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert body["code"] == 0
        assert body["data"]["status"] == "CONFIRMED"

        with reservation_db() as session:
            row = session.get(Reservation, created["id"])
            assert row is not None
            assert row.status is ReservationStatus.CONFIRMED

    def test_patch_unknown_reservation_returns_the_frozen_404(self, client, waiter_headers) -> None:
        response = client.patch(
            f"{RESERVATIONS_URL}/999999",
            json={"status": "CANCELLED"},
            headers=waiter_headers,
        )

        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert response.json()["code"] == 40001

    def test_patch_with_an_invalid_status_is_rejected(self, client, waiter_headers) -> None:
        """The body's status must be one of the three frozen enum members.

        A bare 422 literal: starlette renamed ``HTTP_422_UNPROCESSABLE_ENTITY``
        and this suite runs with warnings-as-errors, so the constant's
        deprecation warning would fail the test before its own assertion ran.
        """
        response = client.patch(
            f"{RESERVATIONS_URL}/1",
            json={"status": "SEATED"},  # not in the frozen vocabulary
            headers=waiter_headers,
        )

        assert response.status_code == 422

    def test_patch_without_a_token_is_rejected(self, client) -> None:
        response = client.patch(f"{RESERVATIONS_URL}/1", json={"status": "CONFIRMED"})

        assert response.status_code == status.HTTP_401_UNAUTHORIZED


class TestOrderEndpointsStayPlaceholders:
    """The ordering module has no backend yet, so these endpoints must not
    pretend orders exist. When member5's service lands, replace these tests
    with real ones — they are the module's reminder of the open dependency.
    """

    def test_get_orders_returns_an_empty_list(self, client, waiter_headers) -> None:
        response = client.get(ORDERS_URL, headers=waiter_headers)

        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert body["code"] == 0
        assert body["data"] == []

    def test_patch_order_reports_not_found(self, client, waiter_headers) -> None:
        response = client.patch(
            f"{ORDERS_URL}/1", json={"status": "COMPLETED"}, headers=waiter_headers
        )

        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert response.json()["code"] == 40001

    def test_get_orders_still_requires_staff(self, client, auth_headers) -> None:
        response = client.get(ORDERS_URL, headers=auth_headers(Role.CUSTOMER))

        assert response.status_code == status.HTTP_403_FORBIDDEN
