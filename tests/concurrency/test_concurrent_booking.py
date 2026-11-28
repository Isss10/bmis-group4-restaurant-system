"""Real-MySQL concurrent reservation acceptance test (Objective d, section 5.4).

Each of ten runs sends 50 simultaneous POST requests for one table and slot.
Expected: exactly one successful booking, 49 HTTP 409 / business-code 20001
conflicts, and exactly one active reservation in the database.

SAFETY: This writes REAL bookings. Use only an independently migrated,
dedicated MySQL TEST database. Never use a production or shared database.
Existing records are not deleted. Set BOOKING_TEST_DB_NAME to the exact
database name when the name does not contain "test".
"""

from __future__ import annotations

import os
import secrets
import threading
from collections.abc import Generator
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from src.data.database import session_scope

# These markers are already registered under [tool.pytest.ini_options].
# Adding a marker makes the test selectable, NOT proof it has run.
pytestmark = [
    pytest.mark.concurrency,
    pytest.mark.integration,
    pytest.mark.slow,
    pytest.mark.skipif(
        not os.getenv("APP_DB_HOST"),
        reason="Real MySQL required: set APP_DB_HOST for the dedicated test database.",
    ),
]

N_WORKERS = 50
REPEATS = 10  # provisional: reviewer said 5 was insufficient; confirm threshold
TABLE_ID = 1
SLOT_START = time(19, 0)
SUCCESS_STATUSES = (200, 201)
CONFLICT_STATUS = 409
CONFLICT_CODE = 20001


@dataclass(frozen=True)
class BookingResult:
    status_code: int
    body: dict[str, Any]


def _reservation_time_for_run(run_index: int) -> datetime:
    """Use ten distinct, future slots; override date when rerunning the test.

    BOOKING_TEST_START_DATE should be YYYY-MM-DD and must refer to an
    unoccupied table/slot in the dedicated database.
    """
    specified_start = os.getenv("BOOKING_TEST_START_DATE")
    if specified_start:
        start_date = date.fromisoformat(specified_start)
    else:
        start_date = date.today() + timedelta(days=7)
    return datetime.combine(start_date + timedelta(days=run_index), SLOT_START)


def _build_app() -> Any:
    from src.presentation.api.main import create_app

    return create_app()


def _require_dedicated_mysql() -> None:
    """Fail closed before sending booking requests to an unsafe database."""
    with session_scope() as session:
        dialect = session.get_bind().dialect.name
        if dialect != "mysql":
            pytest.fail(f"Expected MySQL for this test; connected to {dialect!r}")

        actual_name = session.execute(text("SELECT DATABASE()")).scalar_one()
        expected_name = os.getenv("BOOKING_TEST_DB_NAME")
        if not actual_name:
            pytest.fail("MySQL has no selected database.")
        if expected_name:
            if actual_name.lower() != expected_name.lower():
                pytest.fail(
                    f"Connected to database {actual_name!r}, "
                    f"expected {expected_name!r}; no requests were sent."
                )
        elif "test" not in actual_name.lower():
            pytest.fail(
                f"Database {actual_name!r} does not look like a dedicated "
                "test database. Set BOOKING_TEST_DB_NAME to its exact name "
                "only after verifying that it is safe for disposable bookings."
            )


def _active_rows_for_slot(reservation_time: datetime) -> int:
    """Count persisted active bookings in an independent ORM session."""
    with session_scope() as session:
        rows = session.execute(
            text(
                "SELECT COUNT(*) FROM reservations "
                "WHERE table_id = :table_id "
                "AND reservation_time = :reservation_time "
                "AND status IN ('PENDING', 'CONFIRMED')"
            ),
            {"table_id": TABLE_ID, "reservation_time": reservation_time},
        ).scalar_one()
    return int(rows)


def _one_booking(
    app: Any,
    barrier: threading.Barrier,
    token: str,
    reservation_time: datetime,
) -> BookingResult:
    """Send a request with other workers after all reach the same barrier."""
    client = TestClient(app)
    try:
        barrier.wait(timeout=60)
        response = client.post(
            "/api/v1/reservations",
            json={
                "table_id": TABLE_ID,
                "reservation_time": reservation_time.isoformat(timespec="seconds"),
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        body = response.json()
        if not isinstance(body, dict):
            raise AssertionError(f"Expected a JSON response object, got: {body!r}")
        return BookingResult(response.status_code, body)
    finally:
        client.close()


@pytest.fixture(scope="module")
def booking_identity() -> Generator[tuple[Any, str], None, None]:
    """Register and authenticate one customer in the dedicated test database."""
    _require_dedicated_mysql()
    app = _build_app()
    email = f"booking-ci-{secrets.token_hex(8)}@example.com"
    password = f"Aa1!{secrets.token_urlsafe(24)}"

    with TestClient(app) as client:
        registered = client.post(
            "/api/v1/auth/register",
            json={
                "email": email,
                "password": password,
                "display_name": "Concurrency Test Customer",
            },
        )
        register_code = registered.json().get("code")
        assert registered.status_code == 201, "Test customer registration failed"
        assert register_code == 0, "Registration returned a business error"

        logged_in = client.post(
            "/api/v1/auth/login",
            json={"email": email, "password": password},
        )
        login_code = logged_in.json().get("code")
        assert logged_in.status_code == 200, "Test customer login failed"
        assert login_code == 0, "Login returned a business error"
        token = logged_in.json()["data"]["access_token"]
        if not isinstance(token, str) or not token:
            pytest.fail("Login did not return a valid access token")

        profile = client.get(
            "/api/v1/membership/profile",
            headers={"Authorization": f"Bearer {token}"},
        )
        profile_code = profile.json().get("code")
        assert profile.status_code == 200, "Test customer authentication failed"
        assert profile_code == 0, "Profile returned a business error"
        assert profile.json()["data"]["role"] == "customer"

        yield app, token


@pytest.mark.parametrize("run_index", range(REPEATS))
def test_exactly_one_booking_wins(run_index: int, booking_identity: tuple[Any, str]) -> None:
    """Verify all HTTP responses and the database state for each race."""
    app, customer_token = booking_identity
    _require_dedicated_mysql()

    reservation_time = _reservation_time_for_run(run_index)
    before = _active_rows_for_slot(reservation_time)
    assert before == 0, (
        f"Run {run_index}: slot {reservation_time} already has {before} "
        "active booking(s). Choose unused slots with BOOKING_TEST_START_DATE; "
        "the test does not delete other people's data."
    )

    barrier = threading.Barrier(N_WORKERS)
    with ThreadPoolExecutor(max_workers=N_WORKERS) as pool:
        futures = [
            pool.submit(_one_booking, app, barrier, customer_token, reservation_time)
            for _ in range(N_WORKERS)
        ]
        results = [future.result() for future in as_completed(futures)]

    message = f"Run {run_index}: received {len(results)} of {N_WORKERS} responses"
    assert len(results) == N_WORKERS, message
    successes = [
        r for r in results if r.status_code in SUCCESS_STATUSES and r.body.get("code", 0) == 0
    ]
    conflicts = [
        r
        for r in results
        if r.status_code == CONFLICT_STATUS and r.body.get("code") == CONFLICT_CODE
    ]
    unexpected = [
        r
        for r in results
        if not (r.status_code in SUCCESS_STATUSES and r.body.get("code", 0) == 0)
        and not (r.status_code == CONFLICT_STATUS and r.body.get("code") == CONFLICT_CODE)
    ]

    assert len(successes) == 1, (
        f"Run {run_index}, slot {reservation_time}: "
        f"expected 1 successful booking, found {len(successes)}; "
        f"response summary: {[(r.status_code, r.body.get('code')) for r in results]}"
    )
    assert len(conflicts) == N_WORKERS - 1, (
        f"Run {run_index}, slot {reservation_time}: "
        f"expected {N_WORKERS - 1} HTTP 409 / code 20001 conflicts, "
        f"found {len(conflicts)}. Unexpected responses: {unexpected[:5]!r}"
    )

    after = _active_rows_for_slot(reservation_time)
    assert after == 1, (
        f"Run {run_index}, slot {reservation_time}: "
        f"expected exactly one active database reservation, found {after}"
    )
