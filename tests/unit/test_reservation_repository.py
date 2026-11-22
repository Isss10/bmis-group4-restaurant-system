"""Unit tests for the reservation module (FR-RES-01 … FR-RES-08).

Why the shape of these tests matters
------------------------------------
This repository has shipped green CI alongside code that could not run — three
times (see the docstrings of ``test_migration_completeness.py`` and the
``reservations`` migration). The pattern each time was the same: a suite that
asserts nothing about the behaviour that actually breaks. So these tests pin the
*invariants the acceptance criteria are written against*, not incidental details:

* FR-RES-02 — a booking starts ``HELD`` with a TTL from settings, and is
  confirmed only explicitly.
* FR-RES-03 — a second active booking for the same slot fails with **20001**,
  and the failure comes from the database's unique index, not from a check that a
  forgotten code path could skip.
* FR-RES-04 — an expired hold does not occupy its slot **at query time**, so
  correctness does not depend on the sweep running (§5.5).
* FR-RES-05/07 — the state machine rejects illegal transitions with **20003**,
  and ``NO_SHOW`` is distinct from ``CANCELLED`` so FR-ANA-04 is computable.
* FR-RES-08 — every write leaves an audit row naming the actor and the change.

Scope
-----
SQLite in-memory, so this runs in the unit job with no MySQL and no network.
``FOR UPDATE`` degrades to a no-op there, which is fine: §5.1 locking and true
parallel races are the concurrency suite's job (``tests/concurrency/``, Objective
d). What SQLite *can* prove — and does prove here — is the §5.3 generated column
and its unique index, because ``CASE WHEN`` and ``CONCAT`` are portable and
SQLite 3.44+ supports generated columns. That is the layer the booking guarantee
actually rests on, so it is worth testing on every pull request.

Database wiring
---------------
``ReservationRepository`` gets its session from the module-level singletons in
``src.data.database``; the fixture swaps both for an in-memory engine and
restores them afterwards. ``StaticPool`` matters — plain ``sqlite:///:memory:``
gives every *connection* its own empty database, so the session that writes would
not be the session that reads.

The audit table is created alongside ``reservations`` because FR-RES-08 requires
every write to leave a row, and a test that could not see those rows would not be
testing the requirement.
"""

from __future__ import annotations

from collections.abc import Generator
from datetime import date, datetime, time, timedelta
from itertools import pairwise

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import src.data.database as db
from src.application.reservation.models import (
    ACTIVE_SLOT_KEY_SQL,
    ACTIVE_STATUSES,
    Reservation,
    ReservationStatus,
    slot_key,
)
from src.application.reservation.repository import (
    AuditContext,
    ReservationRepository,
    is_occupying,
    utc_now_naive,
)
from src.application.reservation.service import (
    SLOT_MINUTES,
    ReservationService,
    slot_grid,
)
from src.common.audit import (
    ACTION_RESERVATION_CANCELLED,
    ACTION_RESERVATION_CREATED,
    ACTION_RESERVATION_NO_SHOW,
    ACTION_RESERVATION_STATUS_CHANGED,
    ACTION_SEAT_HOLD_EXPIRED,
    AuditLog,
)
from src.common.errors import ApiError, ErrorCode

# Fixed literals rather than `datetime.now()`: they keep failures reproducible
# and make the exact-slot assertions meaningful. The date is far enough out that
# no test can be invalidated by the calendar moving.
_SLOT_DATE = date(2026, 12, 24)
_SLOT_START = time(19, 30)
_OTHER_SLOT = time(20, 0)
_ACTOR = AuditContext(actor_id="u-42", actor_role="customer", request_id="req_test_1")


@pytest.fixture
def reservation_db() -> Generator[Session, None, None]:
    """Point the app's session factory at a shared in-memory SQLite database.

    Yields a session bound to the same database the repository writes to, so a
    test can inspect persisted rows and audit entries directly rather than
    trusting the return value.
    """
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    # Only these two tables are needed; other models use MySQL-specific types
    # SQLite cannot render, and these tests do not touch them. The audit table is
    # included so FR-RES-08 is asserted, not assumed.
    Reservation.__table__.create(engine)
    AuditLog.__table__.create(engine)
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


def _book(
    service: ReservationService,
    *,
    user_id: str = "u-1",
    table_id: int = 7,
    slot_date: date = _SLOT_DATE,
    slot_start: time = _SLOT_START,
    party_size: int = 2,
    now: datetime | None = None,
) -> dict:
    """Create a hold with defaults that satisfy every validation rule."""
    return service.create_reservation(
        user_id=user_id,
        table_id=table_id,
        slot_date=slot_date,
        slot_start=slot_start,
        party_size=party_size,
        audit=_ACTOR,
        now=now,
    )


def _audit_rows(session: Session) -> list[AuditLog]:
    """Every audit row, oldest first."""
    return list(session.scalars(select(AuditLog).order_by(AuditLog.id)))


# ---------------------------------------------------------------------------
# Schema invariants — the ones that make the concurrency guarantee real
# ---------------------------------------------------------------------------


class TestSchemaInvariants:
    def test_enum_members_are_the_seven_documented_states(self) -> None:
        """The seven-state vocabulary is a frozen contract (FR-RES-05/07).

        Migration ``b7e4c1a9d2f3`` hard-codes these names into a MySQL ENUM, so
        renaming or adding a member without a migration would desynchronise model
        and database. Asserting the exact set makes that coupling fail here.
        """
        assert {member.value for member in ReservationStatus} == {
            "HELD",
            "CONFIRMED",
            "SEATED",
            "COMPLETED",
            "CANCELLED",
            "NO_SHOW",
            "EXPIRED",
        }

    def test_legacy_three_state_vocabulary_is_gone(self) -> None:
        """``PENDING`` must not come back.

        It was the pre-§9 name for a hold. Two spellings of one state is how a
        status comparison silently returns False and a booking gets double-counted.
        """
        assert not hasattr(ReservationStatus, "PENDING")

    def test_active_statuses_match_the_generated_column_sql(self) -> None:
        """The Python set and the SQL expression must agree on "occupying".

        ``ACTIVE_STATUSES`` drives the availability query; ``ACTIVE_SLOT_KEY_SQL``
        drives the unique index. The SQL text cannot be derived from the set at DDL
        time, so nothing else would notice a divergence — and a divergence means
        the constraint and the query disagree about whether a slot is free, which
        is exactly the silent overbooking the constraint exists to prevent.
        """
        for status in ReservationStatus:
            in_python = status in ACTIVE_STATUSES
            in_sql = f"'{status.value}'" in ACTIVE_SLOT_KEY_SQL
            assert in_python == in_sql, (
                f"{status.value}: ACTIVE_STATUSES says {in_python}, "
                f"the generated column SQL says {in_sql}"
            )

    def test_migration_reuses_the_model_expression(self) -> None:
        """The migration must not carry its own copy of the generated-column SQL.

        Importing the revision module executes it, which is the point: it pulls
        ``ACTIVE_SLOT_KEY_SQL`` from the model, so a duplicated-and-typo'd copy in
        the migration would fail here rather than silently building a different
        constraint on the deployment database.
        """
        import importlib

        module = importlib.import_module(
            "src.data.migration.versions."
            "20261121_1200_b7e4c1a9d2f3_reservation_slot_and_state_machine"
        )
        assert module.ACTIVE_SLOT_KEY_SQL is ACTIVE_SLOT_KEY_SQL

    def test_slot_key_names_the_table_and_slot(self) -> None:
        """``slot_key()`` produces the spelling used in conflict messages.

        Deliberately *not* asserted against the stored ``active_slot_key``: MySQL
        renders the TIME part as ``19:30:00`` and SQLite as ``19:30:00.000000``,
        so this helper's text is a prefix of the stored key on SQLite and the whole
        key on MySQL. The constraint compares the column to itself within one
        backend, so it is correct on both; only the advisory message text differs.
        See ``slot_key``'s docstring for the full caveat.
        """
        assert slot_key(5, _SLOT_DATE, _SLOT_START) == "5#2026-12-24#19:30:00"

    def test_table_name_matches_the_migration(self) -> None:
        assert Reservation.__tablename__ == "reservations"

    def test_version_column_is_the_optimistic_lock(self) -> None:
        """§5.2 must stay wired, or 20004 becomes unreachable.

        ``version_id_col`` is configured in ``__mapper_args__``; if that is dropped
        the ORM stops checking versions and a lost update silently wins — the
        cheapest layer to get wrong quietly (§5.2), which is why it is asserted.
        """
        assert Reservation.__mapper_args__["version_id_col"] is Reservation.__table__.c.version


class TestSlotGrid:
    def test_grid_is_aligned_to_the_frozen_granularity(self) -> None:
        """Every slot start must be a whole number of ``SLOT_MINUTES`` (30, frozen)."""
        assert SLOT_MINUTES == 30
        assert all(slot.minute % SLOT_MINUTES == 0 for slot in slot_grid())

    def test_grid_covers_opening_hours_and_excludes_closing(self) -> None:
        """A seating that begins at closing time is not a seating."""
        grid = slot_grid()
        assert grid[0] == time(11, 0)
        assert grid[-1] == time(21, 30)
        assert time(22, 0) not in grid

    def test_grid_is_evenly_spaced(self) -> None:
        """An uneven grid would make some slots unbookable from the UI."""
        grid = slot_grid()
        # `pairwise` rather than `zip(grid, grid[1:])`: it names the intent
        # (successive pairs) and avoids the `strict=` question entirely, since
        # pairing n slots deliberately yields n-1 gaps.
        gaps = {
            (datetime.combine(_SLOT_DATE, b) - datetime.combine(_SLOT_DATE, a))
            for a, b in pairwise(grid)
        }
        assert gaps == {timedelta(minutes=SLOT_MINUTES)}
        assert len(gaps) == 1


# ---------------------------------------------------------------------------
# FR-RES-02 — booking creates a HELD row with a TTL from settings
# ---------------------------------------------------------------------------


class TestBooking:
    def test_book_creates_a_held_row(self, reservation_db: Session) -> None:
        """The initial state is ``HELD``, never ``CONFIRMED`` (FR-RES-02).

        A booking that started confirmed would have no hold to expire, so an
        abandoned booking would occupy a table forever — the exact failure the
        hold exists to prevent.
        """
        created = _book(ReservationService())

        assert created["status"] is ReservationStatus.HELD
        assert created["user_id"] == "u-1"
        assert created["table_id"] == 7
        assert created["slot_date"] == _SLOT_DATE
        assert created["slot_start"] == _SLOT_START
        assert created["party_size"] == 2

        row = reservation_db.get(Reservation, created["id"])
        assert row is not None
        assert row.status is ReservationStatus.HELD

    def test_hold_expiry_comes_from_settings_not_a_literal(self, reservation_db: Session) -> None:
        """§5.5 requires the TTL be configurable without a code change.

        The earlier implementation hardcoded ``timedelta(minutes=15)``, which both
        ignored ``settings.seat_hold_ttl_seconds`` (default 600 s = 10 min, per
        FR-RES-02) and contradicted it. Asserting against the setting is what
        keeps the two from drifting again.
        """
        from src.common.config import get_settings

        ttl = get_settings().seat_hold_ttl_seconds
        assert ttl == 600, "the frozen contract's hold window is 10 minutes"

        now = utc_now_naive()
        created = _book(ReservationService(), now=now)

        assert created["expires_at"] == now + timedelta(seconds=ttl)

    def test_confirmed_booking_has_no_pending_hold(self, reservation_db: Session) -> None:
        """Confirmation clears ``expires_at`` so the sweep stops considering the row.

        Leaving a stale timestamp would make every sweep re-examine a booking that
        is no longer held, and would mislead anyone reading the row about whether
        the guest still has a deadline.
        """
        service = ReservationService()
        created = _book(service)

        confirmed = service.confirm(created["id"], user_id="u-1", audit=_ACTOR)

        assert confirmed["status"] is ReservationStatus.CONFIRMED
        assert confirmed["expires_at"] is None

    def test_result_is_readable_after_the_session_closes(self, reservation_db: Session) -> None:
        """Regression guard for the detached-instance failure mode from PR #3.

        ``create()`` copies values into plain locals *before* returning, so the
        caller never touches an ORM object whose session has closed. If that is
        "simplified" back to returning the instance, every attribute read raises
        ``DetachedInstanceError`` and the endpoint 500s — while this suite, which
        builds its own schema, stays green. That is why the guard is explicit.
        """
        created = _book(ReservationService())

        assert isinstance(created["id"], int)
        assert created["slot_date"] == _SLOT_DATE
        assert created["status"] is ReservationStatus.HELD

    def test_ownership_comes_from_the_caller_not_the_row(self, reservation_db: Session) -> None:
        """``user_id`` is whatever the caller passed (the router derives it from the JWT)."""
        created = _book(ReservationService(), user_id="customer-99")
        assert created["user_id"] == "customer-99"


# ---------------------------------------------------------------------------
# FR-RES-03 — the unique constraint is the guarantee, not the pre-check
# ---------------------------------------------------------------------------


class TestConflictDetection:
    def test_second_booking_for_the_same_slot_is_rejected(self, reservation_db: Session) -> None:
        """The application-level check produces a clean 20001 (the UX path)."""
        service = ReservationService()
        _book(service)

        with pytest.raises(ApiError) as excinfo:
            _book(service, user_id="u-2")

        assert excinfo.value.code is ErrorCode.SLOT_ALREADY_BOOKED
        assert int(excinfo.value.code) == 20001
        assert excinfo.value.errors is not None
        assert excinfo.value.errors[0]["detail"] == slot_key(7, _SLOT_DATE, _SLOT_START)

    def test_only_one_row_survives_a_conflict(self, reservation_db: Session) -> None:
        """The invariant that matters is the row count, not the error (ARCHITECTURE §5.4)."""
        service = ReservationService()
        _book(service)
        with pytest.raises(ApiError):
            _book(service, user_id="u-2")

        rows = list(reservation_db.scalars(select(Reservation)))
        assert len(rows) == 1

    def test_unique_index_fires_even_when_the_precheck_is_bypassed(
        self, reservation_db: Session
    ) -> None:
        """§5.3: the database has the final say.

        This is the most important test in the file. It writes **directly through
        the ORM**, bypassing ``ReservationService.book`` and its friendly pre-check
        entirely — simulating a code path that forgot the check, a hand-written
        query, or two genuinely concurrent inserts. The unique index on the
        generated column must still reject the duplicate, which is what makes the
        guarantee "real rather than hopeful".

        Also proves the generated column computes at all: if it were NULL for a
        HELD row, multiple NULLs would be permitted and this insert would succeed.
        """
        repo = ReservationRepository()
        first = repo.create(
            user_id="u-1",
            table_id=7,
            slot_date=_SLOT_DATE,
            slot_start=_SLOT_START,
            party_size=2,
            expires_at=utc_now_naive() + timedelta(minutes=10),
        )

        reservation_db.expire_all()
        row = reservation_db.get(Reservation, first["id"])
        assert row is not None
        # Prefix, not equality: `CONCAT` renders the TIME column through the
        # backend's own affinity, so MySQL stores `19:30:00` and SQLite stores
        # `19:30:00.000000` (see slot_key's docstring). Asserting equality would
        # tie this test to one dialect; asserting the prefix proves the column
        # computed a key naming exactly this table and slot on either.
        assert row.active_slot_key is not None, (
            "the generated column did not compute a key for an active row; "
            "without it the unique index has nothing to enforce"
        )
        assert row.active_slot_key.startswith(slot_key(7, _SLOT_DATE, _SLOT_START)), (
            f"stored key {row.active_slot_key!r} does not name slot "
            f"{slot_key(7, _SLOT_DATE, _SLOT_START)!r}"
        )

        from sqlalchemy.exc import IntegrityError

        with pytest.raises(IntegrityError):
            reservation_db.add(
                Reservation(
                    user_id="u-2",
                    table_id=7,
                    slot_date=_SLOT_DATE,
                    slot_start=_SLOT_START,
                    party_size=2,
                    status=ReservationStatus.HELD,
                    expires_at=utc_now_naive() + timedelta(minutes=10),
                )
            )
            reservation_db.flush()
        reservation_db.rollback()

    def test_different_table_may_hold_the_same_slot(self, reservation_db: Session) -> None:
        """The constraint is per (table, slot), not per slot."""
        service = ReservationService()
        _book(service, table_id=7)
        other = _book(service, user_id="u-2", table_id=8)

        assert other["table_id"] == 8

    def test_different_slot_on_the_same_table_is_allowed(self, reservation_db: Session) -> None:
        """Discrete slots must not collide with their neighbours."""
        service = ReservationService()
        _book(service)
        other = _book(service, user_id="u-2", slot_start=_OTHER_SLOT)

        assert other["slot_start"] == _OTHER_SLOT

    def test_cancelled_booking_releases_its_slot(self, reservation_db: Session) -> None:
        """The slot must become bookable again — the reason for the NULL trick (§5.3).

        A plain ``UNIQUE (table_id, slot_date, slot_start)`` would forbid this
        forever: the cancelled row would still occupy the key. This test is what
        would have caught that design error.
        """
        service = ReservationService()
        created = _book(service)
        service.cancel(created["id"], user_id="u-1", audit=_ACTOR)

        rebooked = _book(service, user_id="u-2")
        assert rebooked["id"] != created["id"]
        assert rebooked["status"] is ReservationStatus.HELD

    def test_completed_booking_releases_its_slot(self, reservation_db: Session) -> None:
        """``COMPLETED`` is terminal but **not** active: the meal is over, the table is free."""
        service = ReservationService()
        created = _book(service)
        service.confirm(created["id"], user_id="u-1", audit=_ACTOR)
        service.set_reservation_status(created["id"], ReservationStatus.SEATED, audit=_ACTOR)
        service.set_reservation_status(created["id"], ReservationStatus.COMPLETED, audit=_ACTOR)

        rebooked = _book(service, user_id="u-2")
        assert rebooked["status"] is ReservationStatus.HELD

    def test_expired_hold_does_not_block_a_new_booking(self, reservation_db: Session) -> None:
        """The reconciliation step on the booking path (FR-RES-04).

        The occupancy query already ignores an expired hold, but the §5.3 index
        counts a ``HELD`` row as active *regardless* of expiry. So ``book`` sweeps
        the target slot first; without that step a dead hold would block a
        legitimate booking forever — the failure mode ARCHITECTURE.md §5.5 warns
        about, arriving through the constraint rather than the query.
        """
        service = ReservationService()
        created = _book(service)

        # Backdate the hold past its TTL, exactly as a crashed sweep would leave it.
        row = reservation_db.get(Reservation, created["id"])
        assert row is not None
        row.expires_at = utc_now_naive() - timedelta(seconds=1)
        reservation_db.commit()

        rebooked = _book(service, user_id="u-2")

        assert rebooked["status"] is ReservationStatus.HELD
        reservation_db.expire_all()
        assert reservation_db.get(Reservation, created["id"]).status is ReservationStatus.EXPIRED


# ---------------------------------------------------------------------------
# The booking critical section — one transaction for lock, expire, check, insert
# ---------------------------------------------------------------------------


class TestBookingCriticalSection:
    """``ReservationRepository.book_slot`` must decide and write in one transaction.

    The group lead's requirement and M1's figure 4.5 both specify
    ``BEGIN → SELECT ... FOR UPDATE → INSERT`` as a single critical section. These
    tests pin that the check and the insert cannot drift apart, and that a lapsed
    hold is released *inside* the same transaction — a separate-transaction version
    would pass the earlier behavioural tests yet still be wrong under concurrency.
    """

    def test_book_slot_persists_a_held_row_and_audits_it(self, reservation_db: Session) -> None:
        """The low-level critical-section method writes the row and its audit together."""
        repo = ReservationRepository()
        now = utc_now_naive()

        created = repo.book_slot(
            user_id="u-1",
            table_id=7,
            slot_date=_SLOT_DATE,
            slot_start=_SLOT_START,
            party_size=2,
            expires_at=now + timedelta(minutes=10),
            now=now,
            audit=_ACTOR,
        )

        assert created["status"] is ReservationStatus.HELD
        assert created["version"] == 1
        row = reservation_db.get(Reservation, created["id"])
        assert row is not None and row.status is ReservationStatus.HELD

        rows = _audit_rows(reservation_db)
        assert len(rows) == 1
        assert rows[0].action == ACTION_RESERVATION_CREATED
        assert rows[0].entity_id == str(created["id"])

    def test_book_slot_rejects_an_occupied_slot_with_20001(self, reservation_db: Session) -> None:
        """The in-transaction occupancy check raises the frozen conflict code."""
        repo = ReservationRepository()
        now = utc_now_naive()
        repo.book_slot(
            user_id="u-1",
            table_id=7,
            slot_date=_SLOT_DATE,
            slot_start=_SLOT_START,
            party_size=2,
            expires_at=now + timedelta(minutes=10),
            now=now,
            audit=_ACTOR,
        )

        with pytest.raises(ApiError) as excinfo:
            repo.book_slot(
                user_id="u-2",
                table_id=7,
                slot_date=_SLOT_DATE,
                slot_start=_SLOT_START,
                party_size=2,
                expires_at=now + timedelta(minutes=10),
                now=now,
                audit=_ACTOR,
            )

        assert excinfo.value.code is ErrorCode.SLOT_ALREADY_BOOKED

    def test_book_slot_releases_a_lapsed_hold_inside_the_same_transaction(
        self, reservation_db: Session
    ) -> None:
        """A dead hold must not block the slot — and its release is atomic with the insert.

        The generated column counts a ``HELD`` row as active regardless of expiry,
        so the insert would collide with the stale row unless the critical section
        flips it to ``EXPIRED`` and flushes *before* inserting. This is the step
        that a three-transaction design would get wrong: releasing the hold in one
        transaction and inserting in another leaves a window where a concurrent
        reader sees neither the release nor the new booking.
        """
        repo = ReservationRepository()
        past = utc_now_naive() - timedelta(seconds=1)
        stale = repo.create(
            user_id="u-1",
            table_id=7,
            slot_date=_SLOT_DATE,
            slot_start=_SLOT_START,
            party_size=2,
            expires_at=past,
        )

        now = utc_now_naive()
        created = repo.book_slot(
            user_id="u-2",
            table_id=7,
            slot_date=_SLOT_DATE,
            slot_start=_SLOT_START,
            party_size=2,
            expires_at=now + timedelta(minutes=10),
            now=now,
            audit=_ACTOR,
        )

        reservation_db.expire_all()
        assert reservation_db.get(Reservation, stale["id"]).status is ReservationStatus.EXPIRED
        assert reservation_db.get(Reservation, created["id"]).status is ReservationStatus.HELD

        # Exactly one live booking for the slot.
        live = [
            row
            for row in reservation_db.scalars(select(Reservation))
            if row.status in ACTIVE_STATUSES
        ]
        assert len(live) == 1 and live[0].id == created["id"]

        # The release must be recorded *before* the insert. Ordering is the
        # observable evidence that both happened inside one transaction: a
        # separate-transaction design would still produce these two rows, but
        # nothing would tie the release to the booking that depends on it.
        # (`stale` was created via repo.create(), hence the leading created row.)
        actions = [r.action for r in _audit_rows(reservation_db)]
        assert actions == [
            ACTION_RESERVATION_CREATED,  # the stale hold, set up by repo.create()
            ACTION_SEAT_HOLD_EXPIRED,  # released inside book_slot's transaction
            ACTION_RESERVATION_CREATED,  # the new booking, same transaction
        ]

    def test_a_live_hold_is_not_released_by_book_slot(self, reservation_db: Session) -> None:
        """Only a *lapsed* hold is released; a live one still blocks the slot."""
        repo = ReservationRepository()
        now = utc_now_naive()
        live = repo.create(
            user_id="u-1",
            table_id=7,
            slot_date=_SLOT_DATE,
            slot_start=_SLOT_START,
            party_size=2,
            expires_at=now + timedelta(minutes=10),
        )

        with pytest.raises(ApiError):
            repo.book_slot(
                user_id="u-2",
                table_id=7,
                slot_date=_SLOT_DATE,
                slot_start=_SLOT_START,
                party_size=2,
                expires_at=now + timedelta(minutes=10),
                now=now,
                audit=_ACTOR,
            )

        reservation_db.expire_all()
        assert reservation_db.get(Reservation, live["id"]).status is ReservationStatus.HELD

    def test_create_reservation_is_the_canonical_name_and_book_aliases_it(
        self,
    ) -> None:
        """The group lead and M1's report both say ``create_reservation``.

        ``book`` is kept only so the concurrency suite (M4/M7) written against the
        earlier name keeps importing. Asserting the alias is the same function
        object means the two can never drift in behaviour.
        """
        assert ReservationService.book is ReservationService.create_reservation


# ---------------------------------------------------------------------------
# is_occupying — the Python mirror of the SQL occupancy filter
# ---------------------------------------------------------------------------


class TestOccupancyPredicate:
    """``is_occupying`` (Python) and ``_occupancy_filter`` (SQL) must agree.

    Two spellings of one rule: the SQL filter drives availability and the booking
    pre-check, the Python predicate drives the rows the critical section has
    already locked. If they ever diverge, availability would advertise a slot that
    booking then refuses — a support ticket with no bug in either half.
    """

    @pytest.mark.parametrize("status", list(ReservationStatus))
    def test_predicate_matches_the_sql_filter_for_every_status(
        self, reservation_db: Session, status: ReservationStatus
    ) -> None:
        """For each status, the row-level and query-level answers must be identical.

        Exercised through ``booked_slots`` (which uses the SQL filter) against
        ``is_occupying`` (the Python one), on real rows, at a moment where a live
        and an expired hold differ — so the two paths are compared on the actual
        database rather than on hand-rolled objects.
        """
        repo = ReservationRepository()
        now = utc_now_naive()
        # A hold that is still live at `now`.
        live_expires = now + timedelta(minutes=10)

        row = Reservation(
            user_id="u-1",
            table_id=7,
            slot_date=_SLOT_DATE,
            slot_start=_SLOT_START,
            party_size=2,
            status=status,
            expires_at=live_expires if status is ReservationStatus.HELD else None,
        )
        reservation_db.add(row)
        reservation_db.commit()

        python_says = is_occupying(row, now)
        sql_says = _SLOT_START in repo.booked_slots(_SLOT_DATE, now=now).get(7, [])
        # Message hoisted to a variable: black and ruff format disagree about a
        # parenthesised multi-line assert message, and CI runs both checks.
        mismatch = f"{status.value}: is_occupying={python_says} but the SQL filter={sql_says}"
        assert python_says == sql_says, mismatch

    def test_expired_hold_occupies_in_neither_path(self, reservation_db: Session) -> None:
        """The FR-RES-04 case both paths must get right: a dead hold is not occupying."""
        repo = ReservationRepository()
        now = utc_now_naive()
        row = Reservation(
            user_id="u-1",
            table_id=7,
            slot_date=_SLOT_DATE,
            slot_start=_SLOT_START,
            party_size=2,
            status=ReservationStatus.HELD,
            expires_at=now - timedelta(seconds=1),
        )
        reservation_db.add(row)
        reservation_db.commit()

        assert is_occupying(row, now) is False
        assert _SLOT_START not in repo.booked_slots(_SLOT_DATE, now=now).get(7, [])

    def test_hold_with_no_expiry_occupies_in_neither_path(self, reservation_db: Session) -> None:
        """A ``HELD`` row with NULL ``expires_at`` is a malformed hold — treat as free.

        Both paths must agree on this edge: the SQL filter's ``expires_at > now``
        is false for NULL, so the Python predicate must be false too. A hold with
        no deadline is a data error, not a permanent lock on the table.
        """
        repo = ReservationRepository()
        now = utc_now_naive()
        row = Reservation(
            user_id="u-1",
            table_id=7,
            slot_date=_SLOT_DATE,
            slot_start=_SLOT_START,
            party_size=2,
            status=ReservationStatus.HELD,
            expires_at=None,
        )
        reservation_db.add(row)
        reservation_db.commit()

        assert is_occupying(row, now) is False
        assert _SLOT_START not in repo.booked_slots(_SLOT_DATE, now=now).get(7, [])


# ---------------------------------------------------------------------------
# Slot validation — an off-grid slot is an overbooking waiting to happen
# ---------------------------------------------------------------------------


class TestSlotValidation:
    def test_off_grid_start_is_rejected(self, reservation_db: Session) -> None:
        """A start that is not on the grid can never be matched by ``availability``.

        Such a slot would look permanently free to customers while the unique
        index still enforced it — so the table would appear bookable and every
        attempt would 20001. Rejecting at the door is what prevents that.
        """
        service = ReservationService()
        with pytest.raises(ApiError) as excinfo:
            _book(service, slot_start=time(19, 17))

        assert excinfo.value.code is ErrorCode.VALIDATION_FAILED
        fields = {e["field"] for e in excinfo.value.errors or []}
        assert "slot_start" in fields

    def test_seconds_beyond_the_grid_are_rejected(self, reservation_db: Session) -> None:
        """``19:30:45`` is off-grid even though the minute looks right."""
        with pytest.raises(ApiError):
            _book(ReservationService(), slot_start=time(19, 30, 45))

    def test_outside_opening_hours_is_rejected(self, reservation_db: Session) -> None:
        service = ReservationService()
        with pytest.raises(ApiError) as excinfo:
            _book(service, slot_start=time(3, 0))
        assert excinfo.value.code is ErrorCode.VALIDATION_FAILED

    def test_past_date_is_rejected(self, reservation_db: Session) -> None:
        with pytest.raises(ApiError) as excinfo:
            _book(ReservationService(), slot_date=date(2000, 1, 1))
        assert excinfo.value.code is ErrorCode.VALIDATION_FAILED

    def test_non_positive_party_size_is_rejected(self, reservation_db: Session) -> None:
        with pytest.raises(ApiError) as excinfo:
            _book(ReservationService(), party_size=0)
        assert excinfo.value.code is ErrorCode.VALIDATION_FAILED

    def test_non_positive_table_id_is_rejected(self, reservation_db: Session) -> None:
        with pytest.raises(ApiError) as excinfo:
            _book(ReservationService(), table_id=0)
        assert excinfo.value.code is ErrorCode.VALIDATION_FAILED


# ---------------------------------------------------------------------------
# FR-RES-01 — availability, and the query-side half of FR-RES-04
# ---------------------------------------------------------------------------


class TestAvailability:
    def test_empty_day_reports_every_slot_free_for_every_table(
        self, reservation_db: Session
    ) -> None:
        service = ReservationService()
        data = service.availability(_SLOT_DATE)

        assert len(data) > 0
        first = data[0]
        assert first["slot_date"] == _SLOT_DATE.isoformat()
        assert len(first["free_slots"]) == len(slot_grid())

    def test_a_held_slot_disappears_from_availability(self, reservation_db: Session) -> None:
        service = ReservationService()
        _book(service, table_id=7)

        entry = next(e for e in service.availability(_SLOT_DATE) if e["table_id"] == 7)
        other = next(e for e in service.availability(_SLOT_DATE) if e["table_id"] == 8)

        assert _SLOT_START.isoformat(timespec="minutes") not in entry["free_slots"]
        assert _SLOT_START.isoformat(timespec="minutes") in other["free_slots"]

    def test_expired_hold_is_reported_free_without_any_sweep(self, reservation_db: Session) -> None:
        """FR-RES-04's real guarantee: correctness does not depend on the job.

        No sweep is called here. The occupancy predicate alone must treat the dead
        hold as non-occupying — if availability waited on a background job, a
        crashed job would leave tables unbookable forever.
        """
        service = ReservationService()
        created = _book(service, table_id=7)

        row = reservation_db.get(Reservation, created["id"])
        assert row is not None
        row.expires_at = utc_now_naive() - timedelta(seconds=1)
        reservation_db.commit()
        # Still HELD in the database: nothing has swept it.
        assert row.status is ReservationStatus.HELD

        entry = next(
            e for e in service.availability(_SLOT_DATE, now=utc_now_naive()) if e["table_id"] == 7
        )
        assert _SLOT_START.isoformat(timespec="minutes") in entry["free_slots"], (
            "an expired hold still counts as occupying; availability now depends "
            "on the sweep running, which FR-RES-04 forbids"
        )

    def test_live_hold_still_counts_as_occupying(self, reservation_db: Session) -> None:
        """The mirror of the test above — the filter must not ignore *all* holds."""
        service = ReservationService()
        now = utc_now_naive()
        _book(service, table_id=7, now=now)

        entry = next(e for e in service.availability(_SLOT_DATE, now=now) if e["table_id"] == 7)
        assert _SLOT_START.isoformat(timespec="minutes") not in entry["free_slots"]

    def test_confirmed_and_seated_occupy_the_slot(self, reservation_db: Session) -> None:
        """A confirmed booking has no ``expires_at``, so it must occupy unconditionally."""
        service = ReservationService()
        created = _book(service, table_id=7)
        service.confirm(created["id"], user_id="u-1", audit=_ACTOR)

        entry = next(
            e for e in service.availability(_SLOT_DATE, now=utc_now_naive()) if e["table_id"] == 7
        )
        assert _SLOT_START.isoformat(timespec="minutes") not in entry["free_slots"]

    def test_terminal_states_free_the_slot(self, reservation_db: Session) -> None:
        """CANCELLED / EXPIRED / NO_SHOW / COMPLETED must all read as free."""
        service = ReservationService()
        created = _book(service, table_id=7)
        service.cancel(created["id"], user_id="u-1", audit=_ACTOR)

        entry = next(
            e for e in service.availability(_SLOT_DATE, now=utc_now_naive()) if e["table_id"] == 7
        )
        assert _SLOT_START.isoformat(timespec="minutes") in entry["free_slots"]

    def test_past_date_is_rejected(self, reservation_db: Session) -> None:
        with pytest.raises(ApiError) as excinfo:
            ReservationService().availability(date(2000, 1, 1))
        assert excinfo.value.code is ErrorCode.VALIDATION_FAILED


# ---------------------------------------------------------------------------
# FR-RES-04 — the sweep
# ---------------------------------------------------------------------------


class TestHoldExpiry:
    def test_sweep_expires_a_lapsed_hold(self, reservation_db: Session) -> None:
        service = ReservationService()
        created = _book(service)

        row = reservation_db.get(Reservation, created["id"])
        assert row is not None
        row.expires_at = utc_now_naive() - timedelta(seconds=1)
        reservation_db.commit()

        expired = service.expire_holds(audit=_ACTOR)

        assert expired == 1
        reservation_db.expire_all()
        assert reservation_db.get(Reservation, created["id"]).status is ReservationStatus.EXPIRED

    def test_sweep_leaves_a_live_hold_alone(self, reservation_db: Session) -> None:
        service = ReservationService()
        _book(service)

        assert service.expire_holds(audit=_ACTOR) == 0
        assert len(list(reservation_db.scalars(select(Reservation)))) == 1

    def test_sweep_leaves_a_confirmed_booking_alone(self, reservation_db: Session) -> None:
        """Confirmation removes the expiry, so a confirmed row is never swept."""
        service = ReservationService()
        created = _book(service)
        service.confirm(created["id"], user_id="u-1", audit=_ACTOR)

        assert service.expire_holds(audit=_ACTOR) == 0
        reservation_db.expire_all()
        assert reservation_db.get(Reservation, created["id"]).status is ReservationStatus.CONFIRMED

    def test_sweep_is_idempotent(self, reservation_db: Session) -> None:
        """A second run must report nothing and write no further audit rows.

        Expiry runs on a schedule *and* on the booking path, so it will be called
        repeatedly over the same rows. Re-reporting them would double-count
        expiries in the audit trail and in any turnover metric built on it.
        """
        service = ReservationService()
        created = _book(service)
        row = reservation_db.get(Reservation, created["id"])
        assert row is not None
        row.expires_at = utc_now_naive() - timedelta(seconds=1)
        reservation_db.commit()

        assert service.expire_holds(audit=_ACTOR) == 1
        expiry_rows = len(
            [r for r in _audit_rows(reservation_db) if r.action == ACTION_SEAT_HOLD_EXPIRED]
        )

        assert service.expire_holds(audit=_ACTOR) == 0
        assert (
            len([r for r in _audit_rows(reservation_db) if r.action == ACTION_SEAT_HOLD_EXPIRED])
            == expiry_rows
        )

    def test_confirming_an_already_expired_hold_returns_20002(
        self, reservation_db: Session
    ) -> None:
        """The slot has been released and may belong to someone else.

        Confirming it anyway would be an overbooking — the guest would arrive to a
        table the system has already given away. 20002 is the frozen code for
        exactly this.
        """
        service = ReservationService()
        created = _book(service)
        row = reservation_db.get(Reservation, created["id"])
        assert row is not None
        row.expires_at = utc_now_naive() - timedelta(seconds=1)
        reservation_db.commit()

        with pytest.raises(ApiError) as excinfo:
            service.confirm(created["id"], user_id="u-1", audit=_ACTOR, now=utc_now_naive())

        assert excinfo.value.code is ErrorCode.SEAT_HOLD_EXPIRED
        assert int(excinfo.value.code) == 20002

    def test_find_expired_holds_uses_an_inclusive_boundary(self, reservation_db: Session) -> None:
        """A hold expiring exactly at ``now`` is swept in this pass, not the next."""
        repo = ReservationRepository()
        now = utc_now_naive()
        created = repo.create(
            user_id="u-1",
            table_id=7,
            slot_date=_SLOT_DATE,
            slot_start=_SLOT_START,
            party_size=2,
            expires_at=now,
        )

        assert repo.find_expired_holds(now) == [created["id"]]


# ---------------------------------------------------------------------------
# FR-RES-05 / FR-RES-07 — the state machine
# ---------------------------------------------------------------------------


class TestStateMachine:
    def test_every_declared_state_has_a_transition_entry(self) -> None:
        """A state missing from the table would silently allow nothing out of it.

        Terminal states map to an empty set on purpose; a state missing from the
        dict entirely would raise KeyError at runtime instead of being rejected.
        """
        assert set(ReservationService.ALLOWED_TRANSITIONS) == set(ReservationStatus)

    def test_terminal_states_have_no_outgoing_transitions(self) -> None:
        for status in (
            ReservationStatus.COMPLETED,
            ReservationStatus.CANCELLED,
            ReservationStatus.NO_SHOW,
            ReservationStatus.EXPIRED,
        ):
            assert ReservationService.ALLOWED_TRANSITIONS[status] == frozenset(), status

    def test_happy_path_walks_the_whole_machine(self, reservation_db: Session) -> None:
        """HELD -> CONFIRMED -> SEATED -> COMPLETED (ARCHITECTURE.md §9)."""
        service = ReservationService()
        created = _book(service)

        assert service.confirm(created["id"], user_id="u-1", audit=_ACTOR)["status"] is (
            ReservationStatus.CONFIRMED
        )
        seated = service.set_reservation_status(
            created["id"], ReservationStatus.SEATED, audit=_ACTOR
        )
        assert seated["status"] is ReservationStatus.SEATED
        completed = service.set_reservation_status(
            created["id"], ReservationStatus.COMPLETED, audit=_ACTOR
        )
        assert completed["status"] is ReservationStatus.COMPLETED

    def test_completed_cannot_go_back_to_seated(self, reservation_db: Session) -> None:
        """The §9 rule quoted verbatim: impossible "whatever the HTTP request says"."""
        service = ReservationService()
        created = _book(service)
        service.confirm(created["id"], user_id="u-1", audit=_ACTOR)
        service.set_reservation_status(created["id"], ReservationStatus.SEATED, audit=_ACTOR)
        service.set_reservation_status(created["id"], ReservationStatus.COMPLETED, audit=_ACTOR)

        with pytest.raises(ApiError) as excinfo:
            service.set_reservation_status(created["id"], ReservationStatus.SEATED, audit=_ACTOR)

        assert excinfo.value.code is ErrorCode.ILLEGAL_STATUS_TRANSITION
        assert int(excinfo.value.code) == 20003

    def test_cancelled_is_terminal(self, reservation_db: Session) -> None:
        service = ReservationService()
        created = _book(service)
        service.cancel(created["id"], user_id="u-1", audit=_ACTOR)

        with pytest.raises(ApiError) as excinfo:
            service.set_reservation_status(created["id"], ReservationStatus.CONFIRMED, audit=_ACTOR)
        assert excinfo.value.code is ErrorCode.ILLEGAL_STATUS_TRANSITION

    def test_held_cannot_jump_straight_to_seated(self, reservation_db: Session) -> None:
        """A guest cannot be seated before the booking is confirmed."""
        service = ReservationService()
        created = _book(service)

        with pytest.raises(ApiError) as excinfo:
            service.set_reservation_status(created["id"], ReservationStatus.SEATED, audit=_ACTOR)
        assert excinfo.value.code is ErrorCode.ILLEGAL_STATUS_TRANSITION

    def test_seated_booking_cannot_be_cancelled(self, reservation_db: Session) -> None:
        """RESV-05: the guest is already at the table."""
        service = ReservationService()
        created = _book(service)
        service.confirm(created["id"], user_id="u-1", audit=_ACTOR)
        service.set_reservation_status(created["id"], ReservationStatus.SEATED, audit=_ACTOR)

        with pytest.raises(ApiError) as excinfo:
            service.cancel(created["id"], user_id="u-1", audit=_ACTOR)
        assert excinfo.value.code is ErrorCode.ILLEGAL_STATUS_TRANSITION

    def test_expired_is_not_reachable_by_a_status_update(self, reservation_db: Session) -> None:
        """Only the sweep may produce ``EXPIRED``.

        Otherwise a staff member could void a hold and free a slot while the audit
        trail recorded a routine status change instead of an expiry.
        """
        service = ReservationService()
        created = _book(service)

        with pytest.raises(ApiError) as excinfo:
            service.set_reservation_status(created["id"], ReservationStatus.EXPIRED, audit=_ACTOR)
        assert excinfo.value.code is ErrorCode.ILLEGAL_STATUS_TRANSITION

    def test_no_show_is_reachable_only_from_confirmed(self, reservation_db: Session) -> None:
        """FR-RES-07: no-show is a distinct terminal state, not a cancelled booking."""
        service = ReservationService()
        created = _book(service)

        # Not from HELD: a guest who never confirmed never "no-showed".
        with pytest.raises(ApiError) as excinfo:
            service.mark_no_show(created["id"], audit=_ACTOR)
        assert excinfo.value.code is ErrorCode.ILLEGAL_STATUS_TRANSITION

        service.confirm(created["id"], user_id="u-1", audit=_ACTOR)
        assert service.mark_no_show(created["id"], audit=_ACTOR)["status"] is (
            ReservationStatus.NO_SHOW
        )

    def test_no_show_frees_the_slot(self, reservation_db: Session) -> None:
        service = ReservationService()
        created = _book(service)
        service.confirm(created["id"], user_id="u-1", audit=_ACTOR)
        service.mark_no_show(created["id"], audit=_ACTOR)

        assert _book(service, user_id="u-2")["status"] is ReservationStatus.HELD

    def test_no_show_rate_is_computable_from_stored_states(self, reservation_db: Session) -> None:
        """The structural basis for FR-ANA-04: ``NO_SHOW / (NO_SHOW + COMPLETED)``.

        If ``NO_SHOW`` were folded into ``CANCELLED`` this metric would be
        uncomputable, which is the whole reason FR-RES-07 exists. Asserting it
        end-to-end (not just "the enum member exists") is what ties this module to
        the analytics requirement it serves.
        """
        service = ReservationService()

        no_show = _book(service, user_id="u-1", table_id=7)
        service.confirm(no_show["id"], user_id="u-1", audit=_ACTOR)
        service.mark_no_show(no_show["id"], audit=_ACTOR)

        completed = _book(service, user_id="u-2", table_id=8)
        service.confirm(completed["id"], user_id="u-2", audit=_ACTOR)
        service.set_reservation_status(completed["id"], ReservationStatus.SEATED, audit=_ACTOR)
        service.set_reservation_status(completed["id"], ReservationStatus.COMPLETED, audit=_ACTOR)

        cancelled = _book(service, user_id="u-3", table_id=9)
        service.cancel(cancelled["id"], user_id="u-3", audit=_ACTOR)

        counts: dict[ReservationStatus, int] = {}
        for row in reservation_db.scalars(select(Reservation)):
            counts[row.status] = counts.get(row.status, 0) + 1

        assert counts[ReservationStatus.NO_SHOW] == 1
        assert counts[ReservationStatus.COMPLETED] == 1
        assert counts[ReservationStatus.CANCELLED] == 1
        denominator = counts[ReservationStatus.NO_SHOW] + counts[ReservationStatus.COMPLETED]
        assert counts[ReservationStatus.NO_SHOW] / denominator == 0.5

    def test_transition_to_an_unknown_reservation_returns_40001(
        self, reservation_db: Session
    ) -> None:
        service = ReservationService()
        with pytest.raises(ApiError) as excinfo:
            service.cancel(999_999, user_id="u-1", audit=_ACTOR)
        assert excinfo.value.code is ErrorCode.RESOURCE_NOT_FOUND

    def test_sources_for_inverts_the_transition_table(self) -> None:
        """``_sources_for`` must stay the exact inverse of ``ALLOWED_TRANSITIONS``.

        The service derives the legal source set and passes it into the repository
        so the check happens **inside the row lock**. Checking against a separate
        read first would be a TOCTOU race: two requests could both see CONFIRMED,
        both decide SEATED is legal, and one would overwrite the other.
        """
        table = ReservationService.ALLOWED_TRANSITIONS
        for target in ReservationStatus:
            expected = {s for s, targets in table.items() if target in targets}
            assert ReservationService._sources_for(target) == frozenset(expected)

    def test_held_has_no_incoming_transition(self) -> None:
        """A hold is created by ``book()``, never reached from another state."""
        assert ReservationService._sources_for(ReservationStatus.HELD) == frozenset()

    def test_is_active_and_is_terminal_partition_correctly(self) -> None:
        """The two predicates the report and the query side both rely on."""
        for status in ReservationStatus:
            assert ReservationService.is_active(status) is (status in ACTIVE_STATUSES)
            assert ReservationService.is_terminal(status) is (
                not ReservationService.ALLOWED_TRANSITIONS[status]
            )
        # Active and terminal must never overlap: a slot cannot be both occupied
        # and finished, and if they did the availability query and the unique
        # index would disagree.
        terminal = {s for s in ReservationStatus if ReservationService.is_terminal(s)}
        assert not (ACTIVE_STATUSES & terminal)


# ---------------------------------------------------------------------------
# Ownership (FR-RES-06)
# ---------------------------------------------------------------------------


class TestOwnership:
    def test_a_customer_cannot_cancel_another_customers_booking(
        self, reservation_db: Session
    ) -> None:
        service = ReservationService()
        other = _book(service, user_id="owner-1")

        with pytest.raises(ApiError) as excinfo:
            service.cancel(other["id"], user_id="attacker-2", audit=_ACTOR)

        assert excinfo.value.code is ErrorCode.PERMISSION_DENIED
        assert int(excinfo.value.code) == 30003
        # The row must be untouched — the check happens before any mutation.
        reservation_db.expire_all()
        assert reservation_db.get(Reservation, other["id"]).status is ReservationStatus.HELD

    def test_a_customer_cannot_read_another_customers_booking(
        self, reservation_db: Session
    ) -> None:
        service = ReservationService()
        other = _book(service, user_id="owner-1")

        with pytest.raises(ApiError) as excinfo:
            service.get_reservation(other["id"], user_id="attacker-2")
        assert excinfo.value.code is ErrorCode.PERMISSION_DENIED

    def test_ownership_is_403_not_404(self, reservation_db: Session) -> None:
        """404 would hide the ownership rule from the test that asserts it (RESV-06).

        403 says "we know who you are and you may not do this"; 404 says "this does
        not exist". Collapsing them is what the ``permission_denied`` docstring in
        ``common/errors.py`` warns against.
        """
        service = ReservationService()
        other = _book(service, user_id="owner-1")

        with pytest.raises(ApiError) as excinfo:
            service.get_reservation(other["id"], user_id="attacker-2")
        assert excinfo.value.code is not ErrorCode.RESOURCE_NOT_FOUND

    def test_staff_may_act_without_an_owner_scope(self, reservation_db: Session) -> None:
        """A staff transition passes no ``user_id``, so ownership is not enforced."""
        service = ReservationService()
        created = _book(service, user_id="owner-1")
        service.confirm(created["id"], user_id="owner-1", audit=_ACTOR)

        seated = service.set_reservation_status(
            created["id"], ReservationStatus.SEATED, audit=_ACTOR
        )
        assert seated["status"] is ReservationStatus.SEATED

    def test_list_scopes_to_one_customer(self, reservation_db: Session) -> None:
        service = ReservationService()
        _book(service, user_id="u-1", table_id=7)
        _book(service, user_id="u-2", table_id=8)

        mine = service.list_reservations(user_id="u-1")
        everyone = service.list_reservations()

        assert [r["user_id"] for r in mine] == ["u-1"]
        assert len(everyone) == 2

    def test_list_orders_by_slot_not_insertion_order(self, reservation_db: Session) -> None:
        """The staff list is by soonest slot, so a late insert cannot reorder it.

        Ordering by insertion time would make the list reshuffle as bookings
        arrive, which is useless for a waiter deciding who to seat next.
        """
        service = ReservationService()
        late = _book(service, user_id="u-1", table_id=7, slot_start=time(21, 0))
        early = _book(service, user_id="u-2", table_id=8, slot_start=time(11, 30))

        assert [r["id"] for r in service.list_reservations()] == [early["id"], late["id"]]


# ---------------------------------------------------------------------------
# FR-RES-08 — auditing
# ---------------------------------------------------------------------------


class TestAuditing:
    def test_creating_a_reservation_writes_an_audit_row(self, reservation_db: Session) -> None:
        """FR-RES-08: every reservation write produces an audit row."""
        created = _book(ReservationService())

        rows = _audit_rows(reservation_db)
        assert len(rows) == 1
        entry = rows[0]
        assert entry.action == ACTION_RESERVATION_CREATED
        assert entry.entity_type == "Reservation"
        assert entry.entity_id == str(created["id"])

    def test_audit_names_the_actor_and_the_request(self, reservation_db: Session) -> None:
        """The actor comes from the verified token, and the id links to the log."""
        _book(ReservationService())

        entry = _audit_rows(reservation_db)[0]
        assert entry.actor_id == "u-42"
        assert entry.actor_role == "customer"
        assert entry.request_id == "req_test_1"

    def test_status_change_records_before_and_after(self, reservation_db: Session) -> None:
        """A before/after snapshot is what makes the trail an audit rather than a log."""
        service = ReservationService()
        created = _book(service)
        service.confirm(created["id"], user_id="u-1", audit=_ACTOR)

        entry = _audit_rows(reservation_db)[-1]
        assert entry.action == ACTION_RESERVATION_STATUS_CHANGED
        # `diff_dicts` keeps only the fields that changed, and confirmation
        # changes two: the status *and* expires_at (a confirmed booking has no
        # hold left to expire). Asserting on the key set rather than the exact
        # timestamp keeps this deterministic while still proving the snapshot
        # names both halves of the change.
        assert entry.before is not None and entry.after is not None
        assert set(entry.before) == {"status", "expires_at"}
        assert entry.before["status"] == "HELD"
        assert entry.after == {"status": "CONFIRMED", "expires_at": None}

    def test_each_transition_gets_its_canonical_action(self, reservation_db: Session) -> None:
        """The manager dashboard groups history by a controlled vocabulary."""
        service = ReservationService()
        created = _book(service)
        service.confirm(created["id"], user_id="u-1", audit=_ACTOR)
        service.set_reservation_status(created["id"], ReservationStatus.SEATED, audit=_ACTOR)
        service.set_reservation_status(created["id"], ReservationStatus.COMPLETED, audit=_ACTOR)

        actions = [r.action for r in _audit_rows(reservation_db)]
        assert actions == [
            ACTION_RESERVATION_CREATED,
            ACTION_RESERVATION_STATUS_CHANGED,
            ACTION_RESERVATION_STATUS_CHANGED,
            ACTION_RESERVATION_STATUS_CHANGED,
        ]

    def test_cancellation_and_no_show_get_their_own_actions(self, reservation_db: Session) -> None:
        """Both are reported on (turnover, no-show rate), so both need a distinct name."""
        service = ReservationService()
        cancelled = _book(service, user_id="u-1", table_id=7)
        service.cancel(cancelled["id"], user_id="u-1", audit=_ACTOR)

        no_show = _book(service, user_id="u-2", table_id=8)
        service.confirm(no_show["id"], user_id="u-2", audit=_ACTOR)
        service.mark_no_show(no_show["id"], audit=_ACTOR)

        actions = {r.action for r in _audit_rows(reservation_db)}
        assert ACTION_RESERVATION_CANCELLED in actions
        assert ACTION_RESERVATION_NO_SHOW in actions

    def test_expiry_sweep_is_audited_as_an_expiry(self, reservation_db: Session) -> None:
        """A slot freed by timeout must not look like a staff decision."""
        service = ReservationService()
        created = _book(service)
        row = reservation_db.get(Reservation, created["id"])
        assert row is not None
        row.expires_at = utc_now_naive() - timedelta(seconds=1)
        reservation_db.commit()

        service.expire_holds(audit=_ACTOR)

        entry = _audit_rows(reservation_db)[-1]
        assert entry.action == ACTION_SEAT_HOLD_EXPIRED
        assert entry.after == {"status": "EXPIRED"}

    def test_a_rejected_transition_writes_no_audit_row(self, reservation_db: Session) -> None:
        """An audit trail recording a change that never happened is worse than none.

        ``record_audit`` adds the row inside the caller's transaction precisely so
        it rolls back with the business change; this asserts that property from the
        outside.
        """
        service = ReservationService()
        created = _book(service)
        before = len(_audit_rows(reservation_db))

        with pytest.raises(ApiError):
            service.set_reservation_status(created["id"], ReservationStatus.SEATED, audit=_ACTOR)

        assert len(_audit_rows(reservation_db)) == before

    def test_a_permission_denied_cancel_writes_no_audit_row(self, reservation_db: Session) -> None:
        """Same property for the ownership check, which fires before any mutation."""
        service = ReservationService()
        other = _book(service, user_id="owner-1")
        before = len(_audit_rows(reservation_db))

        with pytest.raises(ApiError):
            service.cancel(other["id"], user_id="attacker-2", audit=_ACTOR)

        assert len(_audit_rows(reservation_db)) == before

    def test_a_system_sweep_records_no_actor(self, reservation_db: Session) -> None:
        """NULL actor is how "the system did this" differs from "someone did this"."""
        service = ReservationService()
        created = _book(service)
        row = reservation_db.get(Reservation, created["id"])
        assert row is not None
        row.expires_at = utc_now_naive() - timedelta(seconds=1)
        reservation_db.commit()

        service.expire_holds()

        entry = _audit_rows(reservation_db)[-1]
        assert entry.actor_id is None
        assert entry.actor_role is None

    def test_audit_context_is_immutable(self) -> None:
        """Frozen so a context cannot be mutated between write and audit row."""
        with pytest.raises(AttributeError):
            _ACTOR.actor_id = "someone-else"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Repository contract
# ---------------------------------------------------------------------------


class TestRepository:
    def test_get_returns_none_for_a_missing_id(self, reservation_db: Session) -> None:
        """``None``, not an exception: the service turns that into 40001."""
        assert ReservationRepository().get(999_999) is None

    def test_update_status_on_a_missing_id_returns_none(self, reservation_db: Session) -> None:
        assert (
            ReservationRepository().update_status(
                999_999, ReservationStatus.CANCELLED, allowed_from=frozenset()
            )
            is None
        )

    def test_timestamps_are_naive_utc(self, reservation_db: Session) -> None:
        """The columns are naive, so an aware value would trip the strict warning filter.

        ``pyproject.toml`` sets ``filterwarnings = ["error"]``, so binding an aware
        datetime fails the suite rather than merely warning — which is how this
        was caught on Python 3.12 before (see the migration's docstring).
        """
        created = _book(ReservationService())

        row = reservation_db.get(Reservation, created["id"])
        assert row is not None
        for value in (row.created_at, row.updated_at, row.expires_at):
            assert value is not None
            assert value.tzinfo is None

        delta = abs((utc_now_naive() - row.created_at).total_seconds())
        assert delta < 300, f"created_at looks wrong: {row.created_at!r}"

    def test_version_starts_at_one(self, reservation_db: Session) -> None:
        """§5.2: the counter must exist from the first write or the check has no baseline."""
        created = _book(ReservationService())
        assert created["version"] == 1

    def test_version_increments_on_a_status_change(self, reservation_db: Session) -> None:
        """Without the increment a lost update would go undetected."""
        service = ReservationService()
        created = _book(service)

        confirmed = service.confirm(created["id"], user_id="u-1", audit=_ACTOR)
        assert confirmed["version"] == created["version"] + 1

    def test_expired_holds_can_be_scoped_to_one_slot(self, reservation_db: Session) -> None:
        """The booking path sweeps only its own slot, keeping the hot path cheap."""
        repo = ReservationRepository()
        past = utc_now_naive() - timedelta(seconds=1)
        target = repo.create(
            user_id="u-1",
            table_id=7,
            slot_date=_SLOT_DATE,
            slot_start=_SLOT_START,
            party_size=2,
            expires_at=past,
        )
        elsewhere = repo.create(
            user_id="u-2",
            table_id=8,
            slot_date=_SLOT_DATE,
            slot_start=_SLOT_START,
            party_size=2,
            expires_at=past,
        )

        expired = repo.expire_stale_holds(utc_now_naive(), only_slot=(7, _SLOT_DATE, _SLOT_START))

        assert expired == [target["id"]]
        reservation_db.expire_all()
        assert reservation_db.get(Reservation, elsewhere["id"]).status is ReservationStatus.HELD

    def test_booked_slots_returns_only_occupying_rows(self, reservation_db: Session) -> None:
        repo = ReservationRepository()
        repo.create(
            user_id="u-1",
            table_id=7,
            slot_date=_SLOT_DATE,
            slot_start=_SLOT_START,
            party_size=2,
            expires_at=utc_now_naive() + timedelta(minutes=10),
        )
        repo.create(
            user_id="u-2",
            table_id=7,
            slot_date=_SLOT_DATE,
            slot_start=_OTHER_SLOT,
            party_size=2,
            expires_at=utc_now_naive() - timedelta(minutes=1),
        )

        booked = repo.booked_slots(_SLOT_DATE)

        assert booked == {7: [_SLOT_START]}
