"""Data access for the reservation module — the only place SQL appears (§3).

Layering
--------
ARCHITECTURE.md §3 confines SQL to ``src/data/`` and business rules to
``src/application/``. This file is the reservation module's data-access boundary:
it owns sessions and queries, and deliberately holds **no policy**. Which
transitions are legal lives in
:class:`~src.application.reservation.service.ReservationService.ALLOWED_TRANSITIONS`;
this module only enforces, atomically, what the service hands down.

Transactions and audit
----------------------
Every method opens its own :func:`session_scope` and returns **plain dicts**, never
ORM instances. Returning an instance would detach it the moment the scope commits,
and the first attribute read in the caller would raise ``DetachedInstanceError`` —
the defect that made every endpoint in PR #3 return 500 while import-time checks
stayed green.

FR-RES-08 requires an audit row for every reservation write, and
:func:`src.common.audit.record_audit` adds the row to the caller's session
*without committing* so it lands or rolls back together with the business change.
That atomicity is only possible if the audit write happens **inside** the same
``session_scope``, which is why the write methods take an :class:`AuditContext`
rather than auditing after the fact.

Concurrency layers owned here
-----------------------------
* §5.1 — ``with_for_update()`` on the status-transition path, so two staff
  members changing one reservation serialise.
* §5.2 — the ORM's ``version_id_col`` (see the model) raises ``StaleDataError``
  on a lost update. Deliberately **not** caught here: the service maps it to
  20004, and swallowing it at this layer would hide which defence fired.
* §5.3 — the ``uq_active_reservation`` unique index raises ``IntegrityError`` on
  a duplicate active slot. Also not caught here, for the same reason.

Hold expiry and correctness
---------------------------
FR-RES-04 requires expiry to stay correct even when the cleanup job is down. Two
independent mechanisms provide that:

1. Every occupancy query filters ``HELD`` rows on ``expires_at > now``
   (:meth:`ReservationRepository._occupancy_filter`), so a dead hold never counts
   as occupying a slot. This is the mechanism that actually guarantees
   correctness, because it is evaluated on every read.
2. :meth:`ReservationRepository.expire_stale_holds` marks those rows ``EXPIRED``.
   That keeps the table small *and* reconciles the §5.3 generated column with
   mechanism 1, because the unique index counts a ``HELD`` row as active
   regardless of expiry. The booking critical section
   (:meth:`ReservationRepository.book_slot`) releases a lapsed hold for its own
   slot inside the same transaction, so a dead hold can never block a legitimate
   new booking; this method additionally serves the whole-table sweep behind
   ``POST /expire-holds`` and the ``confirm`` path.

The periodic job is therefore an optimisation, not a dependency — the property
ARCHITECTURE.md §5.5 asks for.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from typing import Any

from sqlalchemy import and_, or_, select

from src.common.audit import (
    ACTION_RESERVATION_CANCELLED,
    ACTION_RESERVATION_CREATED,
    ACTION_RESERVATION_NO_SHOW,
    ACTION_RESERVATION_STATUS_CHANGED,
    ACTION_SEAT_HOLD_EXPIRED,
    diff_dicts,
    record_audit,
    serialise_for_audit,
)
from src.common.errors import (
    ApiError,
    ErrorCode,
    illegal_transition,
    permission_denied,
    slot_conflict,
)
from src.data.database import session_scope

from .models import ACTIVE_STATUSES, Reservation, ReservationStatus, slot_key

logger = logging.getLogger(__name__)

# Fields captured in every audit before/after snapshot: who held the slot, which
# slot, and what changed. ``diff_dicts`` narrows these to the changed ones.
_SNAPSHOT_FIELDS = ("status", "expires_at")

# Occupying statuses other than HELD. HELD is handled separately because its
# occupancy is conditional on the hold not having expired (FR-RES-04).
_NON_HOLD_ACTIVE_STATUSES = tuple(s for s in ACTIVE_STATUSES if s is not ReservationStatus.HELD)


def is_occupying(row: Reservation, now: datetime) -> bool:
    """Does this row occupy its slot at ``now``? The Python mirror of the SQL filter.

    ``ReservationRepository._occupancy_filter`` expresses this rule in SQL for the
    availability and booking queries; the booking critical section needs the same
    rule over rows it has already loaded and locked, where re-issuing a query would
    be pointless. Two spellings of one rule is a divergence risk — if they ever
    disagree, availability would advertise a slot that booking then refuses, or
    booking would accept a slot availability said was taken. A unit test asserts
    the two agree over every status, live-hold and expired-hold combination.
    """
    if row.status not in ACTIVE_STATUSES:
        return False
    if row.status is not ReservationStatus.HELD:
        # CONFIRMED and SEATED have no expiry: they occupy unconditionally.
        return True
    return row.expires_at is not None and row.expires_at > now


def utc_now_naive() -> datetime:
    """Current UTC time as a naive datetime, matching every column in this table.

    Naive on purpose — the DateTime columns are declared without
    ``timezone=True``, and binding an aware value makes SQLAlchemy warn, which
    ``filterwarnings = ["error"]`` turns into a failure.
    """
    return datetime.now(UTC).replace(tzinfo=None)


@dataclass(frozen=True, slots=True)
class AuditContext:
    """Who is acting, and which request they came from (FR-RES-08).

    Frozen so a context cannot be mutated between the write and the audit row
    that describes it. Every field is optional: the expiry sweep runs with no
    actor at all, and ``record_audit`` stores NULL for a system-initiated action.
    """

    actor_id: str | None = None
    actor_role: str | None = None
    request_id: str | None = None
    ip_address: str | None = None
    user_agent: str | None = None

    def as_kwargs(self) -> dict[str, Any]:
        """The subset of ``record_audit``'s keyword arguments this carries."""
        return {
            "actor_id": self.actor_id,
            "actor_role": self.actor_role,
            "request_id": self.request_id,
            "ip_address": self.ip_address,
            "user_agent": self.user_agent,
        }


class ReservationRepository:
    """Queries and writes for the ``reservations`` table."""

    # -- serialisation ------------------------------------------------------
    @staticmethod
    def _row_to_dict(row: Reservation) -> dict[str, Any]:
        """Flatten a row into plain values, readable after the session closes."""
        return {
            "id": row.id,
            "user_id": row.user_id,
            "table_id": row.table_id,
            "slot_date": row.slot_date,
            "slot_start": row.slot_start,
            "party_size": row.party_size,
            "status": row.status,
            "version": row.version,
            "expires_at": row.expires_at,
            "created_at": row.created_at,
            "updated_at": row.updated_at,
        }

    @staticmethod
    def _snapshot(row: Reservation) -> dict[str, Any]:
        """A JSON-safe before/after snapshot for the audit row."""
        return {name: serialise_for_audit(getattr(row, name)) for name in _SNAPSHOT_FIELDS}

    # -- occupancy ----------------------------------------------------------
    @staticmethod
    def _occupancy_filter(now: datetime) -> Any:
        """A SQL predicate true for rows occupying their slot at ``now``.

        This is the query-side half of FR-RES-04. ``HELD`` counts only while its
        hold is still live, so an expired hold stops occupying the slot the
        instant it expires — whether or not the cleanup job has ever run. Every
        other active status occupies unconditionally: a ``CONFIRMED`` or
        ``SEATED`` booking has no expiry.

        Note the deliberate difference from the §5.3 unique index, which counts
        ``HELD`` as active regardless of expiry. That is why the booking critical
        section (:meth:`book_slot`) releases a lapsed hold inside its own
        transaction: it reconciles the index with this predicate.

        :func:`is_occupying` is the row-level mirror of this SQL predicate, for
        the rows ``book_slot`` has already loaded and locked. A test asserts the
        two agree over every status and hold state.
        """
        return or_(
            and_(Reservation.status == ReservationStatus.HELD, Reservation.expires_at > now),
            Reservation.status.in_(_NON_HOLD_ACTIVE_STATUSES),
        )

    # -- reads --------------------------------------------------------------
    def get(self, reservation_id: int) -> dict[str, Any] | None:
        """One reservation as a plain dict, or ``None`` if it does not exist."""
        with session_scope() as session:
            row = session.get(Reservation, reservation_id)
            return self._row_to_dict(row) if row is not None else None

    def list_all(self) -> list[dict[str, Any]]:
        """Every reservation, soonest slot first — the staff list (FR-RES-06)."""
        return self._list_by(select(Reservation))

    def list_for_user(self, user_id: str) -> list[dict[str, Any]]:
        """One customer's own reservations (FR-RES-06: customers see only theirs)."""
        return self._list_by(select(Reservation).where(Reservation.user_id == user_id))

    @staticmethod
    def _list_by(stmt: Any) -> list[dict[str, Any]]:
        """Run a reservation SELECT with the canonical ordering."""
        with session_scope() as session:
            ordered = stmt.order_by(Reservation.slot_date, Reservation.slot_start, Reservation.id)
            return [ReservationRepository._row_to_dict(row) for row in session.scalars(ordered)]

    def booked_slots(
        self,
        slot_date: date,
        *,
        now: datetime | None = None,
        table_ids: Iterable[int] | None = None,
    ) -> dict[int, list[time]]:
        """Occupied ``table_id -> [slot_start, ...]`` for one date (FR-RES-01).

        Built on :meth:`_occupancy_filter`, so an expired ``HELD`` row is absent
        and its slot reads as free even when the cleanup job is dead. Availability
        must not depend on a background process being alive — that dependency is
        the classic failure mode ARCHITECTURE.md §5.5 warns about.
        """
        moment = now if now is not None else utc_now_naive()
        with session_scope() as session:
            stmt = select(Reservation.table_id, Reservation.slot_start).where(
                and_(Reservation.slot_date == slot_date, self._occupancy_filter(moment))
            )
            wanted = list(table_ids) if table_ids is not None else None
            if wanted:
                stmt = stmt.where(Reservation.table_id.in_(wanted))
            occupied: dict[int, list[time]] = {}
            for table_id, slot_start in session.execute(stmt).all():
                occupied.setdefault(table_id, []).append(slot_start)
            return occupied

    def find_expired_holds(self, now: datetime) -> list[int]:
        """Ids of ``HELD`` rows whose hold has lapsed and are not yet ``EXPIRED``.

        ``<=`` rather than ``<`` so a hold expiring exactly at ``now`` is swept in
        this pass instead of waiting for the next tick.
        """
        with session_scope() as session:
            rows = session.scalars(
                select(Reservation.id).where(
                    and_(
                        Reservation.status == ReservationStatus.HELD,
                        Reservation.expires_at.is_not(None),
                        Reservation.expires_at <= now,
                    )
                )
            ).all()
            return list(rows)

    # -- writes -------------------------------------------------------------
    def book_slot(
        self,
        *,
        user_id: str,
        table_id: int,
        slot_date: date,
        slot_start: time,
        party_size: int,
        expires_at: datetime,
        now: datetime,
        audit: AuditContext | None = None,
    ) -> dict[str, Any]:
        """The booking **critical section**: one transaction for check and insert.

        Everything that decides whether this slot can be taken runs inside a single
        ``session_scope``, in this order:

        1. ``SELECT ... FOR UPDATE`` on the rows already holding this exact slot
           (§5.1). Under READ COMMITTED a *non-existent* row takes no gap lock, so
           this serialises us against status changes on rows that exist — it does
           not, and cannot, stop two inserts racing into an empty slot. That is
           layer 3's job, not this one's.
        2. Expire any lapsed ``HELD`` row found there, and **flush before
           inserting**. The flush matters: the §5.3 generated column recomputes to
           NULL for ``EXPIRED``, so without it the stale row would still carry an
           active key and the insert would collide with a booking that has
           actually timed out.
        3. Re-check occupancy in-transaction. If a row still occupies the slot,
           raise 20001 here — a clean answer with no exception unwinding from the
           database.
        4. Insert and write the ``reservation.created`` audit row, so both commit
           or roll back together (FR-RES-08).

        Why steps 1-3 belong in one transaction rather than three: across separate
        transactions a concurrent ``confirm`` or expiry sweep can land between our
        check and our insert, so the decision would be made on a snapshot the
        database no longer has. Keeping them together means the occupancy we check
        is the occupancy we insert against.

        Raises:
            ApiError: 20001 when the slot is occupied by a live reservation.
            sqlalchemy.exc.IntegrityError: two requests raced and the §5.3 unique
                index rejected this insert. Deliberately **not** caught here — the
                service maps it to 20001, and swallowing it at this layer would
                hide which defence actually fired.
        """
        with session_scope() as session:
            # Step 1: lock whatever already holds this slot.
            existing = list(
                session.scalars(
                    select(Reservation)
                    .where(
                        and_(
                            Reservation.table_id == table_id,
                            Reservation.slot_date == slot_date,
                            Reservation.slot_start == slot_start,
                        )
                    )
                    .with_for_update()
                )
            )

            # Step 2: release lapsed holds inside this transaction, then flush so
            # the generated column drops their active key before we insert.
            for row in existing:
                if (
                    row.status is ReservationStatus.HELD
                    and row.expires_at is not None
                    and row.expires_at <= now
                ):
                    before = self._snapshot(row)
                    row.status = ReservationStatus.EXPIRED
                    session.flush()
                    changed_before, changed_after = diff_dicts(before, self._snapshot(row))
                    record_audit(
                        session,
                        action=ACTION_SEAT_HOLD_EXPIRED,
                        entity_type="Reservation",
                        entity_id=row.id,
                        before=changed_before,
                        after=changed_after,
                        **(audit.as_kwargs() if audit else {}),
                    )

            # Step 3: the in-transaction conflict check, using the shared
            # occupancy predicate so this path and availability() cannot disagree.
            for row in existing:
                session.refresh(row)
            if any(is_occupying(row, now) for row in existing):
                raise slot_conflict(slot_key(table_id, slot_date, slot_start))

            # Step 4: insert under the constraint, audit in the same transaction.
            row = Reservation(
                user_id=user_id,
                table_id=table_id,
                slot_date=slot_date,
                slot_start=slot_start,
                party_size=party_size,
                status=ReservationStatus.HELD,
                expires_at=expires_at,
            )
            session.add(row)
            session.flush()
            session.refresh(row)
            result = self._row_to_dict(row)

            record_audit(
                session,
                action=ACTION_RESERVATION_CREATED,
                entity_type="Reservation",
                entity_id=row.id,
                before=None,
                after=self._snapshot(row),
                **(audit.as_kwargs() if audit else {}),
            )
            return result

    def create(
        self,
        *,
        user_id: str,
        table_id: int,
        slot_date: date,
        slot_start: time,
        party_size: int,
        expires_at: datetime | None,
        audit: AuditContext | None = None,
    ) -> dict[str, Any]:
        """Insert a new ``HELD`` reservation and audit it in the same transaction.

        Raises:
            sqlalchemy.exc.IntegrityError: the §5.3 unique index rejected the row
                because another active reservation already holds this slot. Left
                to propagate on purpose — the service translates it to 20001, and
                catching it here would hide which defence layer fired.
        """
        with session_scope() as session:
            row = Reservation(
                user_id=user_id,
                table_id=table_id,
                slot_date=slot_date,
                slot_start=slot_start,
                party_size=party_size,
                status=ReservationStatus.HELD,
                expires_at=expires_at,
            )
            session.add(row)
            # Flush inside the scope so a unique-constraint violation surfaces
            # here, while the transaction can still roll back cleanly.
            session.flush()
            session.refresh(row)
            result = self._row_to_dict(row)

            record_audit(
                session,
                action=ACTION_RESERVATION_CREATED,
                entity_type="Reservation",
                entity_id=row.id,
                before=None,
                after=self._snapshot(row),
                **(audit.as_kwargs() if audit else {}),
            )
            return result

    def update_status(
        self,
        reservation_id: int,
        status: ReservationStatus,
        *,
        allowed_from: frozenset[ReservationStatus] | None = None,
        user_id: str | None = None,
        clear_expires_at: bool = False,
        audit_action: str | None = None,
        audit: AuditContext | None = None,
    ) -> dict[str, Any] | None:
        """Move one reservation to ``status`` under a row lock (§5.1).

        Args:
            reservation_id: target row.
            status: the state to move to.
            allowed_from: states this transition may start from, computed by the
                service from ``ALLOWED_TRANSITIONS``. ``None`` skips the check,
                which only the internal expiry sweep uses — every caller-facing
                path passes a set, so policy stays in the service while atomicity
                stays here.
            user_id: when given, the row must belong to this user or the call
                raises 30003 *before* any write is attempted.
            clear_expires_at: null out ``expires_at``, used when a hold is
                confirmed and must stop being eligible for expiry.
            audit_action: override the default action name for this transition.
            audit: actor/request metadata for the audit row.

        Returns:
            The updated row as a dict, or ``None`` if no such reservation exists.

        Raises:
            ApiError: 20003 when the current state is not in ``allowed_from``,
                30003 on an ownership mismatch.
            sqlalchemy.orm.exc.StaleDataError: the §5.2 version check found the
                row had changed since it was read; the service maps it to 20004.
        """
        with session_scope() as session:
            # §5.1: lock the row for this transaction so two simultaneous status
            # changes serialise instead of racing. Kept short — no I/O between
            # the lock and the commit (§5.1).
            row = session.scalar(
                select(Reservation).where(Reservation.id == reservation_id).with_for_update()
            )
            if row is None:
                return None

            if user_id is not None and row.user_id != user_id:
                # Raised before any mutation, so a rejected caller leaves no
                # partial write and no audit row behind.
                raise permission_denied()

            current = row.status
            if allowed_from is not None and current not in allowed_from:
                raise illegal_transition(
                    f"{_status_value(current)} -> {_status_value(status)} is not permitted"
                )

            before = self._snapshot(row)
            row.status = status
            if clear_expires_at:
                row.expires_at = None
            session.flush()
            session.refresh(row)

            changed_before, changed_after = diff_dicts(before, self._snapshot(row))
            record_audit(
                session,
                action=audit_action or _default_action(status),
                entity_type="Reservation",
                entity_id=row.id,
                before=changed_before,
                after=changed_after,
                **(audit.as_kwargs() if audit else {}),
            )
            return self._row_to_dict(row)

    def expire_stale_holds(
        self,
        now: datetime,
        *,
        only_slot: tuple[int, date, time] | None = None,
        audit: AuditContext | None = None,
    ) -> list[int]:
        """Mark lapsed ``HELD`` rows ``EXPIRED``; return their ids (FR-RES-04).

        Callable unscoped (the periodic sweep) or narrowed to one
        ``(table_id, slot_date, slot_start)`` slot (the booking path, so a dead
        hold cannot block a new booking through the §5.3 index). Idempotent: an
        already-``EXPIRED`` row is not matched, so a second call returns an empty
        list and writes no audit rows.

        Each row goes through :meth:`update_status` with ``allowed_from={HELD}``,
        so a hold that a waiter confirmed between the query and the lock is
        **skipped** rather than clobbered. Skipping is the correct outcome and is
        why the 20003 is caught here instead of propagating: that guest now has a
        confirmed booking, and an expiry sweep that cancelled it — or that crashed
        halfway and left the remaining holds unswept — would be worse than doing
        nothing. The lock plus the state check make the sweep safe to run
        concurrently with bookings.
        """
        expired: list[int] = []
        for reservation_id in self.find_expired_holds(now):
            if only_slot is not None and not self._matches_slot(reservation_id, only_slot):
                continue
            try:
                updated = self.update_status(
                    reservation_id,
                    ReservationStatus.EXPIRED,
                    allowed_from=frozenset({ReservationStatus.HELD}),
                    audit_action=ACTION_SEAT_HOLD_EXPIRED,
                    audit=audit,
                )
            except ApiError as exc:
                # Only the state-machine rejection is expected here (someone moved
                # the row out of HELD first). Anything else — a permission or
                # not-found error — means this call site is wrong, and swallowing
                # it would hide a real bug behind a silently short sweep.
                if exc.code is not ErrorCode.ILLEGAL_STATUS_TRANSITION:
                    raise
                logger.debug("hold %s no longer HELD at expiry time; skipping", reservation_id)
                continue
            if updated is not None:
                expired.append(reservation_id)
        return expired

    def _matches_slot(self, reservation_id: int, only_slot: tuple[int, date, time]) -> bool:
        """Does this reservation sit exactly on ``only_slot``?"""
        table_id, slot_date, slot_start = only_slot
        existing = self.get(reservation_id)
        return (
            existing is not None
            and existing["table_id"] == table_id
            and existing["slot_date"] == slot_date
            and existing["slot_start"] == slot_start
        )


def _status_value(status: ReservationStatus | Any) -> str:
    """The stored string for a status, tolerating a raw string from the database."""
    return status.value if isinstance(status, ReservationStatus) else str(status)


def _default_action(target: ReservationStatus) -> str:
    """Pick the canonical audit action for a transition into ``target``.

    Uses the ``ACTION_*`` vocabulary from ``src.common.audit`` so the manager
    dashboard can group reservation history by a controlled name rather than free
    text. Cancellation and no-show get their own actions because both are
    reported on (turnover and the no-show rate, FR-ANA-02/04); every other
    transition is a generic status change carrying the before/after snapshot.
    """
    if target is ReservationStatus.CANCELLED:
        return ACTION_RESERVATION_CANCELLED
    if target is ReservationStatus.NO_SHOW:
        return ACTION_RESERVATION_NO_SHOW
    return ACTION_RESERVATION_STATUS_CHANGED
