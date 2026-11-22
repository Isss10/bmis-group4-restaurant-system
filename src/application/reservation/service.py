"""Reservation business rules — the state machine and the booking critical section.

This module is the application tier for Objective (a): it holds every *policy*
decision (which transitions are legal, how long a hold lasts, which slots exist)
and delegates every *mechanism* (locks, constraints, audit rows) to
:class:`~src.application.reservation.repository.ReservationRepository`.

Per ARCHITECTURE.md §3 it must not import FastAPI and must not raise
``HTTPException``: it raises :class:`~src.common.errors.ApiError` carrying a
frozen five-digit code, and the router layer's global handler turns that into the
frozen envelope. That is what makes this file testable without an HTTP layer.

The three booking defences (§5)
-------------------------------
:math:`N` simultaneous bookings for one table and slot must produce exactly one
row. Nothing here alone achieves that; the guarantee is the three layers read
together:

* **§5.1 row lock** — ``update_status`` takes ``SELECT ... FOR UPDATE``, so two
  staff members changing *one existing* reservation serialise.
* **§5.2 optimistic version** — ``version_id_col`` makes a lost update raise
  ``StaleDataError``; :meth:`_translate_db_errors` maps it to **20004**.
* **§5.3 unique constraint** — under the frozen READ COMMITTED level an insert
  into a *free* slot takes no gap lock, so two concurrent bookings can both pass
  the application-level check below and race to INSERT. The
  ``uq_active_reservation`` index rejects the loser; :meth:`_translate_db_errors`
  maps that ``IntegrityError`` to **20001**.

The pre-insert conflict check in :meth:`book` therefore exists for **user
experience**, not for correctness: it turns the common, predictable case into a
clean 20001 without an exception path. Correctness comes from the constraint,
which cannot be forgotten by a code path the way a lock can (§5.3).

Hold expiry without a background job (FR-RES-04, §5.5)
------------------------------------------------------
Expiry is correct even if the sweep never runs, because every occupancy query
treats a ``HELD`` row as occupying only while ``expires_at > now``. The sweep
(:meth:`expire_holds`) is an optimisation that keeps the table small and keeps
the §5.3 index consistent with that query; :meth:`book` calls it for the target
slot so a dead hold can never block a real booking.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date, datetime, time, timedelta
from typing import Any, ClassVar

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm.exc import StaleDataError

from src.common.config import get_settings
from src.common.errors import (
    ApiError,
    ErrorCode,
    illegal_transition,
    not_found,
    permission_denied,
    slot_conflict,
    stale_version,
    validation_failed,
)

from .models import (
    ACTIVE_STATUSES,
    TERMINAL_STATUSES,
    ReservationStatus,
    slot_key,
)
from .repository import AuditContext, ReservationRepository, utc_now_naive

# --- The frozen slot grid -------------------------------------------------
# 30 minutes is fixed by the contract (组员快速上手指南 §5: "时段粒度 30/60/90
# 分钟? 其实已经由冻结契约定为 30 分钟"). It is a module constant rather than a
# setting because it is part of the frozen API contract, not a deployment
# preference: changing it changes which slots exist and therefore what every
# client and the seeded dataset mean.
SLOT_MINUTES = 30

# Operating hours. NOT in the frozen contract and NOT among the six open
# business rules, so these are a documented assumption rather than a decision:
# 11:00-22:00 local, last seating 21:30. Confirm with the group before the
# demo — changing them only shifts the availability grid, nothing else.
OPENING_HOUR = 11
CLOSING_HOUR = 22

# Tables known to the restaurant. The seeded dataset specifies 20 tables
# (docs/report/05-database-design.md §5.9), and there is **no dining-tables
# catalog table in the schema yet** — src/data/schema/ holds only membership and
# review models, and reservations stores a bare ``table_id``. FR-RES-01 asks for
# table label, seat count and zone alongside availability, and none of those
# exist anywhere to read. Until the database layer (owner: YUANYUAN XUE,
# ARCHITECTURE.md §6) ships that catalog, availability is reported per numeric
# table_id over this range and the label/seats/zone fields cannot be filled.
# Replace this constant with a read from the catalog table; do not grow it here.
DEFAULT_TABLE_IDS: tuple[int, ...] = tuple(range(1, 21))

# A hold is created for the booking customer; 2 is the common case and matches
# the concurrency test's payload.
DEFAULT_PARTY_SIZE = 2


def slot_grid() -> list[time]:
    """Every bookable slot start, on the frozen 30-minute grid.

    Generated rather than hardcoded so the grid and ``SLOT_MINUTES`` cannot
    disagree. The last slot starts at ``CLOSING_HOUR - SLOT_MINUTES``: a seating
    that begins at closing time is not a seating.
    """
    total_minutes = (CLOSING_HOUR - OPENING_HOUR) * 60
    return [
        time(OPENING_HOUR + offset // 60, offset % 60)
        for offset in range(0, total_minutes, SLOT_MINUTES)
    ]


class ReservationService:
    """Booking flow, state machine and availability (FR-RES-01 … FR-RES-08)."""

    # The legal transitions, exactly as drawn in ARCHITECTURE.md §9. Anything not
    # listed here is rejected with 20003 whatever the HTTP request says —
    # `completed -> seated` must not be reachable.
    #
    # Two entries go slightly beyond the §9 diagram, both required elsewhere:
    # * HELD -> CANCELLED: the acceptance table (RESV-05) lets a customer cancel
    #   a *held* or *confirmed* booking, and §9 draws the cancel arrow only out
    #   of `confirmed`. Cancelling a hold is strictly safer than letting it
    #   expire, so it is allowed.
    # * HELD -> EXPIRED: §9 annotates this edge as "hold expires (§5.5)".
    ALLOWED_TRANSITIONS: ClassVar[dict[ReservationStatus, frozenset[ReservationStatus]]] = {
        ReservationStatus.HELD: frozenset(
            {
                ReservationStatus.CONFIRMED,
                ReservationStatus.CANCELLED,
                ReservationStatus.EXPIRED,
            }
        ),
        ReservationStatus.CONFIRMED: frozenset(
            {
                ReservationStatus.SEATED,
                ReservationStatus.CANCELLED,
                ReservationStatus.NO_SHOW,
            }
        ),
        ReservationStatus.SEATED: frozenset({ReservationStatus.COMPLETED}),
        # Terminal states: no way out. COMPLETED is terminal but *not* active —
        # the meal is over and the table is free again.
        ReservationStatus.COMPLETED: frozenset(),
        ReservationStatus.CANCELLED: frozenset(),
        ReservationStatus.NO_SHOW: frozenset(),
        ReservationStatus.EXPIRED: frozenset(),
    }

    def __init__(self, repository: ReservationRepository | None = None) -> None:
        self.repository = repository or ReservationRepository()

    # -- reads --------------------------------------------------------------
    def list_reservations(self, *, user_id: str | None = None) -> list[dict[str, Any]]:
        """Reservations for the staff list, or one customer's own (FR-RES-06).

        ``user_id`` scopes the result to that customer; omitting it returns
        everything, which only the staff-facing caller may do — the router
        decides which to pass based on the token's role, never on request data.
        """
        if user_id is not None:
            return self.repository.list_for_user(user_id)
        return self.repository.list_all()

    def get_reservation(self, reservation_id: int, *, user_id: str | None = None) -> dict[str, Any]:
        """One reservation, or 40001. Ownership is enforced when ``user_id`` is given."""
        row = self.repository.get(reservation_id)
        if row is None:
            raise not_found("Reservation not found")
        if user_id is not None and row["user_id"] != user_id:
            # 403, not 404: the caller is authenticated and simply may not touch
            # this row. Reporting 404 would hide the ownership rule from the
            # acceptance test that asserts it (RESV-06).
            raise permission_denied()
        return row

    def availability(
        self,
        slot_date: date,
        *,
        table_ids: Iterable[int] | None = None,
        now: datetime | None = None,
    ) -> list[dict[str, Any]]:
        """Free slots per table for one date (FR-RES-01).

        Returns one entry per table with its free slot starts. A slot is free
        when no *occupying* reservation covers it, where occupancy comes from
        :meth:`ReservationRepository._occupancy_filter` — so an expired ``HELD``
        row does not block the slot even if the sweep has never run. That is the
        query-side guarantee FR-RES-04 asks for.

        ``table_label``, ``seats`` and ``zone`` are **not** returned: no table
        catalog exists in the schema (see ``DEFAULT_TABLE_IDS``). The frontend
        must not expect them until that table lands.
        """
        if slot_date < date.today():
            raise validation_failed(
                errors=[{"field": "slot_date", "detail": "slot_date must not be in the past"}],
                message="slot_date must not be in the past",
            )

        wanted = list(table_ids) if table_ids is not None else list(DEFAULT_TABLE_IDS)
        booked = self.repository.booked_slots(slot_date, now=now, table_ids=wanted)
        grid = slot_grid()

        return [
            {
                "table_id": table_id,
                "slot_date": slot_date.isoformat(),
                "free_slots": [
                    slot.isoformat(timespec="minutes")
                    for slot in grid
                    if slot not in booked.get(table_id, [])
                ],
            }
            for table_id in wanted
        ]

    # -- booking ------------------------------------------------------------
    def create_reservation(
        self,
        *,
        user_id: str,
        table_id: int,
        slot_date: date,
        slot_start: time,
        party_size: int = DEFAULT_PARTY_SIZE,
        audit: AuditContext | None = None,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        """Create a ``HELD`` reservation for one discrete slot (FR-RES-02/03).

        Two phases, and only the second one is transactional:

        1. **Validate** (no transaction needed): grid alignment, not in the past,
           sane party size. These are pure functions of the request, so failing
           them before opening a transaction keeps the critical section short —
           §5.1 warns that a long-held lock under load produces lock-wait timeouts
           and deadlocks.
        2. **The critical section**, delegated whole to
           :meth:`ReservationRepository.book_slot`: lock the rows already holding
           this slot (§5.1), release lapsed holds, re-check occupancy, insert, and
           write the audit row — all inside one transaction.

        The check and the insert must share a transaction. Across separate
        transactions a concurrent ``confirm`` or expiry sweep can land between
        them, so the decision would be made on a snapshot the database no longer
        holds. This is the ordering M1's figure 4.5 in
        ``docs/report/04-architecture.md`` draws:
        ``BEGIN → SELECT ... FOR UPDATE → INSERT``.

        Note what the lock does *not* do: under READ COMMITTED a non-existent row
        takes no gap lock, so two requests racing into an *empty* slot both pass
        the check and both attempt the insert. The §5.3 unique index rejects the
        loser and that ``IntegrityError`` becomes 20001 — correctness comes from
        the constraint, the lock only makes the common case graceful (§5.1, §5.3).

        The hold TTL comes from ``settings.seat_hold_ttl_seconds`` (default 600 s)
        so it is configurable without a code change, as §5.5 requires.

        Raises:
            ApiError: 10001 for an invalid slot, 20001 when the slot is taken.
            ApiError: 20004 via ``StaleDataError`` from the §5.2 version check.
        """
        moment = now if now is not None else utc_now_naive()
        self._validate_slot(table_id, slot_date, slot_start, party_size, moment)

        expires_at = moment + timedelta(seconds=get_settings().seat_hold_ttl_seconds)
        try:
            return self.repository.book_slot(
                user_id=user_id,
                table_id=table_id,
                slot_date=slot_date,
                slot_start=slot_start,
                party_size=party_size,
                expires_at=expires_at,
                now=moment,
                audit=audit,
            )
        except (IntegrityError, StaleDataError) as exc:
            # Both are the *expected* outcome of losing a race, not a bug (§5.3:
            # "Duplicate entry ... for key 'uq_active_reservation' is the
            # expected, correct outcome of a losing race").
            raise self._translate_db_error(exc, table_id, slot_date, slot_start) from exc

    # Kept as an alias so callers written against the earlier name — including
    # tests/concurrency/test_concurrent_booking.py, owned by M4/M7 — keep working.
    # `create_reservation` is the canonical name: it is what the group lead and
    # M1's architecture report (figure 4.5) both use.
    book = create_reservation

    def _validate_slot(
        self,
        table_id: int,
        slot_date: date,
        slot_start: time,
        party_size: int,
        now: datetime,
    ) -> None:
        """Reject a slot the grid or the calendar cannot express (10001).

        Grid alignment is not cosmetic: a start that is off-grid can never be
        matched by :meth:`availability`, so the slot would look permanently free
        to customers while the unique index still enforces it — an overbooking
        waiting to happen.
        """
        errors: list[dict[str, Any]] = []

        if table_id <= 0:
            errors.append({"field": "table_id", "detail": "must be a positive integer"})

        if slot_date < now.date():
            errors.append({"field": "slot_date", "detail": "must not be in the past"})

        if slot_start.minute % SLOT_MINUTES or slot_start.second or slot_start.microsecond:
            errors.append(
                {
                    "field": "slot_start",
                    "detail": f"must be aligned to the {SLOT_MINUTES}-minute grid",
                }
            )
        elif slot_start not in slot_grid():
            errors.append(
                {
                    "field": "slot_start",
                    "detail": (
                        f"outside opening hours {OPENING_HOUR:02d}:00-{CLOSING_HOUR:02d}:00"
                    ),
                }
            )

        if party_size <= 0:
            errors.append({"field": "party_size", "detail": "must be a positive integer"})

        if errors:
            raise validation_failed(errors=errors)

    @staticmethod
    def _translate_db_error(
        exc: IntegrityError | StaleDataError,
        table_id: int,
        slot_date: date,
        slot_start: time,
    ) -> Any:
        """Map a database-layer concurrency signal onto the frozen code.

        ``IntegrityError`` on this path means the §5.3 unique index fired → 20001.
        ``StaleDataError`` means the §5.2 version check fired → 20004. Keeping the
        two distinct matters: the concurrency acceptance test asserts on both
        codes separately (``CONCURRENCY_EVIDENCE_CODES``), and collapsing them
        would make the test unable to tell which defence it exercised.
        """
        if isinstance(exc, StaleDataError):
            return stale_version()
        return slot_conflict(slot_key(table_id, slot_date, slot_start))

    # -- state machine ------------------------------------------------------
    def confirm(
        self,
        reservation_id: int,
        *,
        user_id: str | None = None,
        audit: AuditContext | None = None,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        """``HELD -> CONFIRMED`` on explicit customer action (FR-RES-02).

        Confirmation is never implicit: a hold that is not confirmed expires. If
        the hold has already lapsed the row is moved to ``EXPIRED`` first — so
        the §5.3 index releases the slot — and the caller gets **20002** rather
        than a confirmed booking for a slot the system has already given away.

        ``expires_at`` is cleared on success: a confirmed booking has no hold to
        expire, and leaving a stale timestamp would make the sweep reconsider a
        row that is no longer ``HELD``.
        """
        moment = now if now is not None else utc_now_naive()
        row = self.get_reservation(reservation_id, user_id=user_id)

        if row["status"] is ReservationStatus.HELD:
            expires_at = row.get("expires_at")
            if expires_at is not None and expires_at <= moment:
                self.repository.expire_stale_holds(
                    moment,
                    only_slot=(row["table_id"], row["slot_date"], row["slot_start"]),
                    audit=audit,
                )
                raise ApiError(ErrorCode.SEAT_HOLD_EXPIRED)

        return self._transition(
            reservation_id,
            ReservationStatus.CONFIRMED,
            user_id=user_id,
            audit=audit,
            clear_expires_at=True,
        )

    def cancel(
        self,
        reservation_id: int,
        *,
        user_id: str | None = None,
        audit: AuditContext | None = None,
    ) -> dict[str, Any]:
        """Cancel a ``HELD`` or ``CONFIRMED`` booking (RESV-05).

        ``SEATED`` and later are not cancellable: the guest is at the table, and
        the transition is rejected with 20003 by the state machine rather than by
        a special case here.
        """
        return self._transition(
            reservation_id, ReservationStatus.CANCELLED, user_id=user_id, audit=audit
        )

    def mark_no_show(
        self,
        reservation_id: int,
        *,
        audit: AuditContext | None = None,
    ) -> dict[str, Any]:
        """``CONFIRMED -> NO_SHOW`` (FR-RES-07).

        A distinct terminal state, not a flavour of ``CANCELLED``: FR-ANA-04
        computes no-show rate as ``NO_SHOW / (NO_SHOW + COMPLETED)``, which is
        uncomputable if the two are collapsed.
        """
        return self._transition(reservation_id, ReservationStatus.NO_SHOW, audit=audit)

    def set_reservation_status(
        self,
        reservation_id: int,
        status: ReservationStatus,
        *,
        user_id: str | None = None,
        audit: AuditContext | None = None,
    ) -> dict[str, Any]:
        """Move a reservation to any legal state — the staff-facing entry point.

        This is what the back office calls (FR-RES-06, via ``StaffService``). It
        enforces the same ``ALLOWED_TRANSITIONS`` table as the specific verbs
        above; those exist so a customer-facing endpoint cannot be talked into
        an arbitrary state by its caller.

        ``EXPIRED`` is deliberately **not** reachable through here: it is produced
        only by the expiry sweep, so a staff member cannot silently void a hold
        and free a slot without the audit trail naming the action as an expiry.
        """
        if status is ReservationStatus.EXPIRED:
            raise illegal_transition(
                "EXPIRED is set only by the hold-expiry sweep, not by a status update"
            )
        return self._transition(reservation_id, status, user_id=user_id, audit=audit)

    def _transition(
        self,
        reservation_id: int,
        target: ReservationStatus,
        *,
        user_id: str | None = None,
        audit: AuditContext | None = None,
        clear_expires_at: bool = False,
    ) -> dict[str, Any]:
        """Validate against the state machine, then delegate to the repository.

        The set of legal *source* states is derived by inverting
        ``ALLOWED_TRANSITIONS`` and passed down, so the check happens **inside the
        repository's row lock**. Checking here against a separate read would be a
        time-of-check/time-of-use race: two requests could both see ``CONFIRMED``,
        both decide ``SEATED`` is legal, and one would overwrite the other.

        Raises:
            ApiError: 40001 when the row does not exist, 30003 on an ownership
                mismatch, 20003 when the transition is illegal.
            ApiError(20004): via ``StaleDataError`` from the §5.2 version check.
        """
        allowed_from = self._sources_for(target)
        if not allowed_from:
            # No state leads here, so the transition is impossible by construction.
            # HELD is the only such target: a hold is created by book(), never
            # reached from another state. Fail before touching the database.
            raise illegal_transition(f"no state may transition to {_value(target)}")

        try:
            updated = self.repository.update_status(
                reservation_id,
                target,
                allowed_from=allowed_from,
                user_id=user_id,
                clear_expires_at=clear_expires_at,
                audit=audit,
            )
        except (IntegrityError, StaleDataError) as exc:
            if isinstance(exc, StaleDataError):
                raise stale_version() from exc
            raise slot_conflict() from exc

        if updated is None:
            raise not_found("Reservation not found")
        return updated

    @classmethod
    def _sources_for(cls, target: ReservationStatus) -> frozenset[ReservationStatus]:
        """Invert ``ALLOWED_TRANSITIONS``: which states may move to ``target``?"""
        return frozenset(
            source for source, targets in cls.ALLOWED_TRANSITIONS.items() if target in targets
        )

    # -- hold expiry --------------------------------------------------------
    def expire_holds(self, *, audit: AuditContext | None = None) -> int:
        """Sweep every lapsed hold to ``EXPIRED``; return how many (FR-RES-04).

        Exposed as ``POST /reservations/expire-holds`` so the back office can run
        it by hand and so a scheduled job can call the same domain method — the
        two must not diverge, which is why there is exactly one implementation.

        Correctness does **not** depend on this running: :meth:`availability` and
        :meth:`book` both treat an expired hold as non-occupying at query time.
        This sweep keeps the table small and keeps the §5.3 index consistent with
        that predicate.
        """
        return len(self.repository.expire_stale_holds(utc_now_naive(), audit=audit))

    # -- introspection used by tests and the report --------------------------
    @classmethod
    def is_active(cls, status: ReservationStatus) -> bool:
        """Does this state occupy its slot? Mirrors the §5.3 generated column."""
        return status in ACTIVE_STATUSES

    @classmethod
    def is_terminal(cls, status: ReservationStatus) -> bool:
        """Is this state final? A terminal state has no outgoing transitions."""
        return status in TERMINAL_STATUSES


def _value(status: ReservationStatus) -> str:
    """The stored string for a status, for use in error detail text."""
    return status.value if isinstance(status, ReservationStatus) else str(status)
