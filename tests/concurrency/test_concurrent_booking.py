"""Automated concurrent-booking test (Objective d, §5.4).

N workers book the SAME table + slot at the same instant.
Invariant: exactly one succeeds, N-1 receive a conflict,
and the database holds exactly ONE reservation row afterwards.

Skips itself when no real MySQL is configured (APP_DB_HOST).
Requires the reservation booking endpoint from KEYING CHEN's module.
"""

from __future__ import annotations

import os
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.skipif(
    not os.getenv("APP_DB_HOST"),
    reason="Real MySQL required: set APP_DB_HOST to enable this concurrency test.",
)

# ---- Tunables -------------------------------------------------------------
N_WORKERS = 10  # how many customers race for the same slot
REPEATS = 5  # re-run the whole race R times: a flaky race still fails
TABLE_ID = 1
SLOT_DATE = "2026-12-01"
SLOT_START = "19:00:00"


def _one_booking(worker_id: int, results: list[int], lock: threading.Lock) -> None:
    """One worker POSTs a booking; record HTTP status into a shared list."""
    client = TestClient(_build_app())
    payload = {
        "table_id": TABLE_ID,
        "slot_date": SLOT_DATE,
        "slot_start": SLOT_START,
        "party_size": 2,
    }
    resp = client.post("/api/v1/reservations/book", json=payload)
    with lock:
        results.append(resp.status_code)


def _build_app():
    from src.presentation.api.main import create_app

    return create_app()


@pytest.mark.parametrize("run_index", range(REPEATS))
def test_exactly_one_booking_wins(run_index: int) -> None:
    results: list[int] = []
    lock = threading.Lock()

    with ThreadPoolExecutor(max_workers=N_WORKERS) as pool:
        futures = [pool.submit(_one_booking, i, results, lock) for i in range(N_WORKERS)]
        for fut in as_completed(futures):
            fut.result()

    # 201/200 = success; 409/400 = conflict. Count wins vs conflicts.
    wins = [s for s in results if s in (200, 201)]
    conflicts = [s for s in results if s in (400, 409)]

    assert len(wins) == 1, f"run {run_index}: expected 1 win, got {len(wins)}"
    actual_conflicts = len(conflicts)
    expected_conflicts = N_WORKERS - 1
    message = f"run {run_index}: expected {expected_conflicts} conflicts, got {actual_conflicts}"
    assert actual_conflicts == expected_conflicts, message

    # Prove the invariant on the DATABASE, not just the HTTP responses.
    _assert_one_row_in_db()


def _assert_one_row_in_db() -> None:
    """Independent session: reservations table must hold exactly 1 row for
    this (table_id, slot_date, slot_start). Filled in once ORM model lands."""
    from sqlalchemy import text

    from src.data.database import session_scope

    with session_scope() as session:
        count = session.execute(
            text(
                "SELECT COUNT(*) FROM reservations "
                "WHERE table_id = :t AND slot_date = :d AND slot_start = :s"
            ),
            {"t": TABLE_ID, "d": SLOT_DATE, "s": SLOT_START},
        ).scalar_one()
    assert count == 1, f"database rows for this slot = {count}, expected 1"
