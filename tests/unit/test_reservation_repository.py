"""Unit tests for the reservation module (PR #3, merged 2026-10-28).

Why these exist
---------------
The reservation module landed on ``main`` with **zero test coverage** — all
three files showed 0.0% in the unit job. Untested code that is already merged is
the most dangerous kind: the pipeline reports green, and the first person to
touch it has no safety net.

These tests pin the behaviour the repository actually has today. They are
deliberately descriptive rather than aspirational: where the current
implementation has a rough edge, the test documents it with a comment instead of
silently asserting something the code does not do.

Scope
-----
SQLite in-memory only, so this runs in the unit job on every pull request with
no MySQL and no network. ``FOR UPDATE`` degrades to a no-op on SQLite, which is
fine here — we are testing the repository's own logic (what it persists, what it
returns, how it handles a missing row), not MySQL's row-locking. Locking is the
concurrency suite's job (Objective d, ``tests/concurrency/``).

Database wiring
---------------
``ReservationRepository`` obtains its session through ``src.data.database.
session_scope()``, which reads two module-level singletons. The fixture replaces
both with an in-memory engine and restores them afterwards via
``reset_engine()``, so no test can leak a SQLite engine into the next one.

``StaticPool`` matters: plain ``sqlite:///:memory:`` gives every *connection* its
own empty database, so the session that writes would not be the session that
reads. ``StaticPool`` hands out the single same connection every time.
"""

from __future__ import annotations

from collections.abc import Generator
from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import src.data.database as db
from src.application.reservation.models import Reservation, ReservationStatus
from src.application.reservation.repository import ReservationRepository
from src.application.reservation.service import ReservationService

# A fixed future-ish timestamp. Using a literal rather than `datetime.now()`
# keeps failures reproducible and makes the assertions exact.
_WHEN = datetime(2026, 12, 24, 19, 30)


@pytest.fixture
def reservation_db() -> Generator[Session, None, None]:
    """Point the app's session factory at a shared in-memory SQLite database.

    Yields a session bound to the same database the repository writes to, so a
    test can inspect persisted rows directly rather than trusting the
    repository's return value.
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

    session = factory()
    try:
        yield session
    finally:
        session.close()
        db._engine, db._session_factory = saved_engine, saved_factory
        db.reset_engine()
        engine.dispose()


class TestReservationRepository:
    def test_create_persists_a_pending_row(self, reservation_db: Session) -> None:
        repo = ReservationRepository()

        result = repo.create(user_id="u-42", table_id=7, reservation_time=_WHEN)

        row = reservation_db.scalar(select(Reservation).where(Reservation.user_id == "u-42"))
        assert row is not None, "create() must actually persist a row"
        assert row.table_id == 7
        assert row.reservation_time == _WHEN
        assert row.status is ReservationStatus.PENDING
        assert result["id"] == row.id

    def test_create_result_is_readable_after_the_session_closes(
        self, reservation_db: Session
    ) -> None:
        """Regression guard for the detached-instance failure mode.

        ``create()`` reads its values into plain locals *before* returning, so
        the caller never touches an ORM object whose session has already closed.
        If someone "simplifies" that back to returning the ORM object, every
        attribute access on it raises ``DetachedInstanceError`` and the endpoint
        500s — while the test suite, which builds its own schema, stays green.
        """
        result = ReservationRepository().create(user_id="u-1", table_id=1, reservation_time=_WHEN)

        # Touching the values must not need a live session.
        assert isinstance(result["id"], int)
        assert result["reservation_time"] == _WHEN
        assert result["status"] is ReservationStatus.PENDING

    def test_update_status_flips_the_row_and_returns_it(self, reservation_db: Session) -> None:
        repo = ReservationRepository()
        created = repo.create(user_id="u-2", table_id=3, reservation_time=_WHEN)

        updated = repo.update_status(created["id"], ReservationStatus.CONFIRMED)

        assert updated is not None
        assert updated["status"] is ReservationStatus.CONFIRMED
        reservation_db.expire_all()
        row = reservation_db.get(Reservation, created["id"])
        assert row is not None
        assert row.status is ReservationStatus.CONFIRMED

    def test_update_status_on_a_missing_id_returns_none(self, reservation_db: Session) -> None:
        """A missing reservation must be None, not an exception.

        The service layer relies on this to distinguish "cancelled" from
        "never existed", and the router turns None into a 404.
        """
        assert ReservationRepository().update_status(999_999, ReservationStatus.CANCELLED) is None

    def test_created_at_is_naive_utc_and_survives_strict_warnings(
        self, reservation_db: Session
    ) -> None:
        """Regression guard for a failure that only appeared on Python 3.12+.

        ``created_at`` used ``default=datetime.utcnow``. That function is
        deprecated since 3.12, and this project supports 3.12 (``requires-python
        = ">=3.11,<3.13"``) with ``filterwarnings = ["error"]``, so the
        DeprecationWarning became an exception and **every insert into
        reservations failed** on 3.12 while CI — pinned to 3.11 — stayed green.

        The column is naive ``DateTime``, so the replacement must return a naive
        value too; an aware one would make SQLAlchemy warn about the lost offset
        and fail the same way. This test runs under the strict-warning filter
        and asserts the value is naive and current, so reintroducing either
        problem fails here on any supported interpreter.
        """
        created = ReservationRepository().create(user_id="u-3", table_id=9, reservation_time=_WHEN)

        row = reservation_db.get(Reservation, created["id"])
        assert row is not None
        assert row.created_at is not None
        assert row.created_at.tzinfo is None, (
            "created_at must stay naive: the column is DateTime without "
            "timezone=True, and an aware value triggers a SQLAlchemy warning "
            "that filterwarnings=['error'] would turn into a failure."
        )
        # Sanity: it is a plausible "now", not the epoch or the reservation time.
        delta = abs((datetime.now(UTC).replace(tzinfo=None) - row.created_at).total_seconds())
        assert delta < 300, f"created_at looks wrong: {row.created_at!r}"


class TestReservationService:
    def test_service_delegates_to_the_repository_by_default(self) -> None:
        """Covers the `repository or ReservationRepository()` branch.

        The default-constructed service must still work, which is how the router
        uses it. This does not touch the database — it only checks the wiring.
        """
        service = ReservationService()
        assert isinstance(service.repository, ReservationRepository)

    def test_service_accepts_an_injected_repository(self, reservation_db: Session) -> None:
        service = ReservationService(repository=ReservationRepository())

        result = service.create_reservation(table_id=5, user_id="u-9", reservation_time=_WHEN)

        assert result["status"] is ReservationStatus.PENDING
        assert result["reservation_time"] == _WHEN

    def test_cancel_reservation_returns_the_cancelled_state(self, reservation_db: Session) -> None:
        service = ReservationService(repository=ReservationRepository())
        created = service.create_reservation(table_id=5, user_id="u-9", reservation_time=_WHEN)

        cancelled = service.cancel_reservation(created["id"])

        assert cancelled is not None
        assert cancelled["status"] is ReservationStatus.CANCELLED

    def test_cancel_unknown_reservation_returns_none(self, reservation_db: Session) -> None:
        service = ReservationService(repository=ReservationRepository())
        assert service.cancel_reservation(123_456) is None


class TestReservationStatus:
    def test_enum_members_are_the_documented_vocabulary(self) -> None:
        """The three states are the frozen contract for this module.

        Migration 0003 hard-codes these names into a MySQL ENUM, so renaming or
        adding a member without a migration would desynchronise model and
        database. This test makes that coupling fail loudly here.
        """
        assert {member.value for member in ReservationStatus} == {
            "PENDING",
            "CONFIRMED",
            "CANCELLED",
        }

    def test_table_name_matches_the_migration(self) -> None:
        assert Reservation.__tablename__ == "reservations"
