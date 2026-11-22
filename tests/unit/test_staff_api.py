"""Unit tests for the staff back-office endpoints (Objective b, member3).

Why these exist
---------------
PR #4 shipped the staff router with placeholder handlers; PR #13's contract
alignment then fixed the path, envelope and auth guard but explicitly left
"wiring them to the reservation and ordering services" to the staff module owner.
PR #20 wired the reservation endpoints; this branch wires the order endpoints
to M5's merged OrderingService (FR-ORD-04), and these tests pin the behaviour:

* both list endpoints return what the database actually holds, not mock data;
* both status patches really flip the row, and the order one enforces the
  FR-ORD-04 state machine (illegal jumps surface as the frozen 422/20003);
* missing resources surface as the frozen 404/40001 envelope;
* the require_staff() guard still rejects customers and anonymous callers
  (OWASP A01 — the endpoints must not quietly become public again).

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
from datetime import date, datetime, time, timedelta

import pytest
from fastapi import status
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import src.data.database as db
from src.application.ordering.models import OrderStatus
from src.application.reservation.models import Reservation, ReservationStatus
from src.application.reservation.repository import ReservationRepository, utc_now_naive
from src.common.audit import AuditLog
from src.common.config import Settings
from src.common.security import Role
from src.data.models import Dish, Order, OrderItem
from src.presentation.api.main import create_app

# M2's 7-state contract replaced the free-form reservation_time with a
# discrete slot: a date plus a start time on the frozen 30-minute grid.
_SLOT_DATE = date(2026, 12, 24)
_EARLY = time(18, 0)
_LATE = time(19, 30)
# Orders (M5) still store a full timestamp; pass it explicitly to avoid the
# model's deprecated datetime.utcnow default under Python 3.12+.
_ORDER_CREATED_AT = datetime(2026, 12, 24, 18, 0)

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
    # Only the tables the staff module reads through the two services are
    # needed. Other models use MySQL-specific types SQLite cannot render.
    # Importing Dish/Order/OrderItem resolves their string-based relationships
    # before the tables are created (FK order: dishes, orders, order_items).
    # AuditLog is required: M2's repository.create() now writes an audit row in
    # the same transaction (FR-RES-08), so omitting it breaks every seeded hold.
    Dish.__table__.create(engine)
    Order.__table__.create(engine)
    OrderItem.__table__.create(engine)
    Reservation.__table__.create(engine)
    AuditLog.__table__.create(engine)
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


def _make_order(
    factory: sessionmaker[Session],
    *,
    status: str = "pending",
    customer_name: str = "Alice",
    total_price: float = 12.5,
) -> int:
    """Insert one M5 order row and return its id.

    ``created_at`` is passed explicitly: the model's ``default=datetime.utcnow``
    emits a DeprecationWarning on Python 3.12+, which this suite's
    ``filterwarnings=["error"]`` would turn into a failure on the local 3.13
    environment (CI pins 3.11, where it stays quiet).
    """
    with factory() as session:
        row = Order(
            customer_name=customer_name,
            total_price=total_price,
            status=status,
            created_at=_ORDER_CREATED_AT,
        )
        session.add(row)
        session.commit()
        return int(row.id)


def _create_reservation(*, user_id: str, table_id: int, slot_start: time) -> dict:
    """Seed one HELD reservation via M2's repository (new keyword-only API)."""
    return ReservationRepository().create(
        user_id=user_id,
        table_id=table_id,
        slot_date=_SLOT_DATE,
        slot_start=slot_start,
        party_size=2,
        expires_at=utc_now_naive() + timedelta(minutes=10),
    )


class TestListReservations:
    def test_returns_persisted_rows_oldest_first(self, client, waiter_headers) -> None:
        late = _create_reservation(user_id="u-1", table_id=7, slot_start=_LATE)
        early = _create_reservation(user_id="u-2", table_id=3, slot_start=_EARLY)

        response = client.get(RESERVATIONS_URL, headers=waiter_headers)

        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert body["code"] == 0
        assert [row["id"] for row in body["data"]] == [early["id"], late["id"]]
        first = body["data"][0]
        assert first["user_id"] == "u-2"
        assert first["table_id"] == 3
        assert first["status"] == "HELD"
        # The slot is now a date plus a 30-minute-grid time, not a datetime.
        assert first["slot_date"] == "2026-12-24"
        assert first["slot_start"] == "18:00:00"

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
        created = _create_reservation(user_id="u-9", table_id=5, slot_start=_EARLY)

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
        """A value outside the 7-state vocabulary is rejected by validation.

        ``SEATED`` used to be a convenient invalid value under the old 3-state
        enum, but it is a legal state now, so send a value that is in no state
        at all. A bare 422 literal: starlette renamed
        ``HTTP_422_UNPROCESSABLE_ENTITY`` and this suite runs with
        warnings-as-errors, so the constant's deprecation warning would fail
        the test before its own assertion ran.
        """
        response = client.patch(
            f"{RESERVATIONS_URL}/1",
            json={"status": "NOT_A_STATUS"},
            headers=waiter_headers,
        )

        assert response.status_code == 422
        assert response.json()["code"] == 10001

    def test_patch_illegal_transition_returns_the_frozen_20003(
        self, client, waiter_headers, reservation_db: sessionmaker[Session]
    ) -> None:
        """A legal state the current state cannot reach is rejected by the
        service-layer state machine (ARCHITECTURE.md section 9), not pydantic.
        """
        created = _create_reservation(user_id="u-10", table_id=9, slot_start=_EARLY)

        response = client.patch(
            f"{RESERVATIONS_URL}/{created['id']}",
            json={"status": "COMPLETED"},  # HELD -> COMPLETED skips CONFIRMED/SEATED
            headers=waiter_headers,
        )

        assert response.status_code == 422
        body = response.json()
        assert body["code"] == 20003
        assert body["errors"][0]["field"] == "status"
        with reservation_db() as session:
            row = session.get(Reservation, created["id"])
            assert row is not None
            assert row.status is ReservationStatus.HELD  # unchanged

    def test_patch_without_a_token_is_rejected(self, client) -> None:
        response = client.patch(f"{RESERVATIONS_URL}/1", json={"status": "CONFIRMED"})

        assert response.status_code == status.HTTP_401_UNAUTHORIZED


class TestListOrders:
    def test_returns_persisted_orders(
        self, client, waiter_headers, reservation_db: sessionmaker[Session]
    ) -> None:
        first = _make_order(reservation_db, customer_name="Alice", total_price=12.5)
        second = _make_order(reservation_db, customer_name="Bob", status="ACCEPTED")

        response = client.get(ORDERS_URL, headers=waiter_headers)

        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert body["code"] == 0
        assert [row["id"] for row in body["data"]] == [first, second]
        first_row = body["data"][0]
        assert first_row["customer_name"] == "Alice"
        assert first_row["total_price"] == 12.5
        assert isinstance(first_row["total_price"], float)
        # M5 stores lowercase 'pending'; the read path normalises it.
        assert first_row["status"] == "PENDING"
        assert first_row["created_at"] == "2026-12-24T18:00:00"
        assert "items" not in first_row  # no detached relationship leaks out
        assert body["data"][1]["status"] == "ACCEPTED"

    def test_empty_database_returns_an_empty_list(self, client, waiter_headers) -> None:
        response = client.get(ORDERS_URL, headers=waiter_headers)

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["code"] == 0
        assert response.json()["data"] == []

    def test_customer_is_rejected(self, client, auth_headers) -> None:
        response = client.get(ORDERS_URL, headers=auth_headers(Role.CUSTOMER))

        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert response.json()["code"] == 30003

    def test_anonymous_is_rejected(self, client) -> None:
        response = client.get(ORDERS_URL)

        assert response.status_code == status.HTTP_401_UNAUTHORIZED
        assert response.json()["code"] == 30001


class TestUpdateOrderStatus:
    def test_patch_persists_the_new_status(
        self, client, waiter_headers, reservation_db: sessionmaker[Session]
    ) -> None:
        order_id = _make_order(reservation_db)

        response = client.patch(
            f"{ORDERS_URL}/{order_id}",
            json={"status": "ACCEPTED"},
            headers=waiter_headers,
        )

        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert body["code"] == 0
        assert body["data"]["status"] == "ACCEPTED"
        assert body["data"]["id"] == order_id

        with reservation_db() as session:
            assert session.get(Order, order_id).status == "ACCEPTED"

    @pytest.mark.parametrize(
        ("step", "target"),
        list(
            enumerate(
                [
                    OrderStatus.ACCEPTED,
                    OrderStatus.PREPARING,
                    OrderStatus.SERVED,
                    OrderStatus.COMPLETED,
                ],
                start=1,
            )
        ),
    )
    def test_full_happy_path_reaches_each_status(
        self, client, waiter_headers, reservation_db: sessionmaker[Session], step, target
    ) -> None:
        """Walk the frozen chain PENDING -> ... -> COMPLETED one legal hop at a time."""
        order_id = _make_order(reservation_db)
        chain = [
            OrderStatus.ACCEPTED,
            OrderStatus.PREPARING,
            OrderStatus.SERVED,
            OrderStatus.COMPLETED,
        ]
        for state in chain[:step]:
            response = client.patch(
                f"{ORDERS_URL}/{order_id}",
                json={"status": state.value},
                headers=waiter_headers,
            )
            assert response.status_code == status.HTTP_200_OK, response.text
            assert response.json()["data"]["status"] == state.value
        with reservation_db() as session:
            assert session.get(Order, order_id).status == target.value

    def test_cancel_from_a_non_terminal_status_is_allowed(
        self, client, waiter_headers, reservation_db: sessionmaker[Session]
    ) -> None:
        order_id = _make_order(reservation_db, status="PREPARING")

        response = client.patch(
            f"{ORDERS_URL}/{order_id}",
            json={"status": "CANCELLED"},
            headers=waiter_headers,
        )

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["data"]["status"] == "CANCELLED"

    def test_illegal_transition_returns_the_frozen_20003(
        self, client, waiter_headers, reservation_db: sessionmaker[Session]
    ) -> None:
        order_id = _make_order(reservation_db)  # PENDING -> COMPLETED is not legal
        _make_order(reservation_db, status="COMPLETED")

        response = client.patch(
            f"{ORDERS_URL}/{order_id}",
            json={"status": "COMPLETED"},
            headers=waiter_headers,
        )

        assert response.status_code == 422
        body = response.json()
        assert body["code"] == 20003
        assert body["errors"][0]["field"] == "status"
        with reservation_db() as session:
            assert session.get(Order, order_id).status == "pending"  # unchanged

    def test_terminal_status_cannot_move_again(
        self, client, waiter_headers, reservation_db: sessionmaker[Session]
    ) -> None:
        order_id = _make_order(reservation_db, status="COMPLETED")

        response = client.patch(
            f"{ORDERS_URL}/{order_id}",
            json={"status": "ACCEPTED"},
            headers=waiter_headers,
        )

        assert response.status_code == 422
        assert response.json()["code"] == 20003

    def test_unknown_order_returns_the_frozen_404(self, client, waiter_headers) -> None:
        response = client.patch(
            f"{ORDERS_URL}/999999",
            json={"status": "ACCEPTED"},
            headers=waiter_headers,
        )

        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert response.json()["code"] == 40001

    def test_invalid_status_value_is_rejected_by_validation(self, client, waiter_headers) -> None:
        response = client.patch(
            f"{ORDERS_URL}/1",
            json={"status": "SEATED"},  # not in the FR-ORD-04 vocabulary
            headers=waiter_headers,
        )

        assert response.status_code == 422
        assert response.json()["code"] == 10001

    def test_lowercase_pending_is_compatible(
        self, client, waiter_headers, reservation_db: sessionmaker[Session]
    ) -> None:
        """M5's submit_order writes lowercase 'pending'; patching still works."""
        order_id = _make_order(reservation_db, status="pending")

        response = client.patch(
            f"{ORDERS_URL}/{order_id}",
            json={"status": "ACCEPTED"},
            headers=waiter_headers,
        )

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["data"]["status"] == "ACCEPTED"

    def test_patch_without_a_token_is_rejected(self, client) -> None:
        response = client.patch(f"{ORDERS_URL}/1", json={"status": "ACCEPTED"})

        assert response.status_code == status.HTTP_401_UNAUTHORIZED
