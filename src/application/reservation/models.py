"""Reservation ORM model — the booking invariant is enforced at this layer.

Why the shape of this table matters
-----------------------------------
ARCHITECTURE.md §5 gives the booking guarantee three layers, and only the third
one is a database property rather than a code path that can be forgotten:

1. ``SELECT ... FOR UPDATE`` serialises two writers on an *existing* row (§5.1).
2. ``version_id_col`` optimistic locking turns a lost update into
   ``StaleDataError`` → error code 20004 (§5.2).
3. ``uq_active_reservation`` makes a duplicate *active* booking impossible
   (§5.3). Under the frozen READ COMMITTED isolation level an insert into a free
   slot takes no gap lock, so two concurrent bookings can both pass every
   application-level check and race to INSERT. The unique constraint is what
   rejects the loser, which the service maps to error code 20001.

Layer 3 is also the reason this table stores a **discrete slot**
(``slot_date`` + ``slot_start``) instead of a free-form time range: only a
discrete key can be made unique by a constraint. A range overlap check can never
be expressed as a MySQL unique index (ARCHITECTURE.md §12, "Discrete slots").

The ``active_slot_key`` generated column
----------------------------------------
The uniqueness must apply only to *active* reservations — a cancelled, expired,
no-show or completed booking must release its slot, or a table could never be
rebooked. PostgreSQL would use a partial index; **MySQL has no partial index**
(8.0.13 added *functional* indexes, which cannot filter rows — see §5.3). So the
contract uses a generated column that is NULL for every non-active status, plus
a unique index on it. MySQL's unique index permits multiple NULLs, so finished
rows fall out of the constraint automatically while at most one active row can
hold e.g. ``5#2026-12-01#19:00:00``.

``CONCAT`` and ``CASE WHEN`` are both deterministic (a requirement for generated
columns) and are available in MySQL 8 and SQLite 3.44+, which is why one
expression serves both backends — ``sqlalchemy.Computed`` cannot take a
per-dialect variant, so the expression must be portable instead. SQLite's
``sqlite_version`` must therefore be >= 3.44; the project's own test environment
and ``ubuntu-latest`` both satisfy that.

Timezone note
-------------
Every datetime column here is **naive UTC**. That is deliberate and load-bearing:
``created_at`` used to default to ``datetime.utcnow()``, which is deprecated in
3.12, and mixing aware and naive values in one table makes the hold-expiry
comparison (``expires_at < now``) raise or silently mis-order rows. Use
:func:`_utc_now_naive` rather than ``datetime.utcnow()`` or an aware ``now()``.
"""

from __future__ import annotations

import enum
from datetime import UTC, date, datetime, time
from typing import Any, ClassVar

from sqlalchemy import (
    Column,
    Computed,
    Date,
    DateTime,
    Enum,
    Index,
    Integer,
    String,
    Time,
    UniqueConstraint,
)

from src.data.database import Base


def _utc_now_naive() -> datetime:
    """Current UTC time as a naive datetime.

    Naive, not aware: every DateTime column in this table is declared without
    ``timezone=True``, and SQLAlchemy warns when an aware value is bound to one.
    ``pyproject.toml`` sets ``filterwarnings = ["error"]``, so that warning would
    fail the test suite. See the module docstring.
    """
    return datetime.now(UTC).replace(tzinfo=None)


class ReservationStatus(enum.StrEnum):
    """The seven-state reservation vocabulary (FR-RES-05, ARCHITECTURE.md §9).

    ``StrEnum`` so the value written to the database, the value in the JWT-facing
    API and the value compared in Python are all the same uppercase string.

    Why ``NO_SHOW`` is not a flavour of ``CANCELLED`` (FR-RES-07): the analytics
    dashboard computes no-show rate as ``NO_SHOW / (NO_SHOW + COMPLETED)``
    (FR-ANA-04). Collapsing the two makes that metric uncomputable, because a
    guest who never arrived and a guest who cancelled in advance are then
    indistinguishable.

    Why ``COMPLETED`` is its own state: only a completed reservation unlocks dish
    reviews (FR-REV-01, "only customers who actually ordered"), so review
    eligibility is a query over this column rather than a guess from timestamps.
    """

    HELD = "HELD"
    """Slot reserved but unconfirmed; expires automatically (FR-RES-02/04)."""

    CONFIRMED = "CONFIRMED"
    """Customer explicitly confirmed; the hold no longer expires."""

    SEATED = "SEATED"
    """Guest arrived and was seated by staff."""

    COMPLETED = "COMPLETED"
    """Meal finished. Terminal, and the review-eligibility gate."""

    CANCELLED = "CANCELLED"
    """Cancelled by the customer or by staff. Terminal."""

    NO_SHOW = "NO_SHOW"
    """Confirmed but the guest never arrived. Terminal (FR-RES-07)."""

    EXPIRED = "EXPIRED"
    """A ``HELD`` row whose ``expires_at`` passed. Terminal (FR-RES-04)."""


# Statuses that occupy a slot. This set is the single source of truth for two
# things that must never disagree: the ``active_slot_key`` generated column
# expression (embedded in SQL, see ACTIVE_SLOT_KEY_SQL) and the Python-side
# availability query. If they ever diverge the constraint and the query would
# disagree about whether a slot is free, which is exactly the kind of silent
# overbooking the constraint exists to prevent.
ACTIVE_STATUSES: frozenset[ReservationStatus] = frozenset(
    {
        ReservationStatus.HELD,
        ReservationStatus.CONFIRMED,
        ReservationStatus.SEATED,
    }
)

# Terminal statuses: no transition out of these, and none of them occupies a
# slot. COMPLETED is terminal but *not* active — the meal is over, the table is
# free again.
TERMINAL_STATUSES: frozenset[ReservationStatus] = frozenset(
    {
        ReservationStatus.COMPLETED,
        ReservationStatus.CANCELLED,
        ReservationStatus.NO_SHOW,
        ReservationStatus.EXPIRED,
    }
)

# The generated-column expression, quoted as a literal list so this file and the
# migration cannot drift apart silently. It mirrors ACTIVE_STATUSES; a test
# asserts the two agree (see tests/unit/test_reservation_repository.py) because
# the SQL text cannot be derived from the Python set at DDL time.
ACTIVE_STATUS_SQL_LIST = "'HELD','CONFIRMED','SEATED'"

ACTIVE_SLOT_KEY_SQL = (
    f"CASE WHEN status IN ({ACTIVE_STATUS_SQL_LIST}) "
    "THEN CONCAT(table_id, '#', slot_date, '#', slot_start) "
    "ELSE NULL END"
)


class Reservation(Base):
    """One booking of one table for one discrete slot.

    ``__mapper_args__`` wires ``version`` as SQLAlchemy's ``version_id_col``: on
    every UPDATE the ORM adds ``AND version = <expected>`` to the WHERE clause
    and increments the column. Zero rows matching means another transaction
    committed first, and SQLAlchemy raises ``StaleDataError`` instead of
    overwriting it — the service maps that to error code 20004 (§5.2).
    """

    __tablename__ = "reservations"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)

    # Owner of the booking. Derived server-side from the JWT `sub` claim, never
    # trusted from the request body (ARCHITECTURE.md §7: a client-supplied user
    # id is how one customer books or cancels on behalf of another).
    user_id = Column(String(50), nullable=False, index=True)

    table_id = Column(Integer, nullable=False)

    # The discrete slot. Replaces the former free-form reservation_time/end_time
    # range: only a discrete key can back the unique constraint (§5.3).
    slot_date = Column(Date, nullable=False)
    slot_start = Column(Time, nullable=False)

    party_size = Column(Integer, nullable=False, default=2)

    status: Column[ReservationStatus] = Column(
        Enum(ReservationStatus),
        default=ReservationStatus.HELD,
        nullable=False,
    )

    # Optimistic-lock counter (§5.2). Never written by application code — the ORM
    # maintains it; a manual assignment is silently discarded.
    version = Column(Integer, nullable=False, default=1)

    # Hold expiry (FR-RES-02/04): set to created_at + seat_hold_ttl_seconds while
    # HELD. NULL means "no hold pending", which is the case for every confirmed
    # or terminal row.
    expires_at = Column(DateTime, nullable=True)

    created_at = Column(DateTime, default=_utc_now_naive, nullable=True)
    updated_at = Column(DateTime, default=_utc_now_naive, onupdate=_utc_now_naive, nullable=True)

    # Layer 3 of the booking guarantee. STORED (not VIRTUAL) so the unique index
    # has real values to index and so a MySQL 8 unique index over it is a plain
    # index rather than an expression index. Recomputed by the database on every
    # status change, which is what frees a slot the moment a booking is
    # cancelled — no application code has to remember to release it.
    active_slot_key = Column(
        String(64),
        Computed(ACTIVE_SLOT_KEY_SQL, persisted=True),
        nullable=True,
    )

    __table_args__ = (
        # The name is frozen by ARCHITECTURE.md §5.3: the concurrency test and
        # the technical report both refer to `uq_active_reservation`, and the
        # expected MySQL error text is "Duplicate entry ... for key
        # 'uq_active_reservation'".
        UniqueConstraint("active_slot_key", name="uq_active_reservation"),
        # Serves the availability query (FR-RES-01): "for this date, which slots
        # of which tables are free?" — date first because it is the equality
        # predicate, then table_id for the grouping.
        Index("ix_reservations_slot_date_table_id", "slot_date", "table_id"),
    )

    # ClassVar because RUF012 otherwise reads a mutable default as per-instance
    # state. It is read once by SQLAlchemy when the mapper is configured; the
    # version column is incremented by the ORM on every UPDATE, never by us.
    __mapper_args__: ClassVar[dict[str, Any]] = {"version_id_col": version}

    def __repr__(self) -> str:
        return (
            f"<Reservation {self.id} table={self.table_id} "
            f"slot={self.slot_date}T{self.slot_start} {self.status}>"
        )


def slot_key(table_id: int, slot_date: date, slot_start: time) -> str:
    """Build a human-readable key naming a (table, slot), for conflict messages.

    Used by the service to produce a precise conflict message ("conflicts on
    5#2026-12-01#19:00:00") and by tests to refer to a slot.

    Dialect caveat — read before relying on byte-equality with the stored column
    --------------------------------------------------------------------------
    This does **not** always equal what ``active_slot_key`` holds in the database.
    ``CONCAT`` renders the ``TIME`` column through the backend's own type
    affinity: MySQL writes ``19:00:00``, SQLite writes ``19:00:00.000000``. So on
    SQLite this helper's output is a *prefix* of the stored key, not the whole
    string.

    That is harmless for what this function is actually used for. The §5.3
    uniqueness is enforced by the generated column comparing *itself to itself*
    within one backend, so the constraint is correct on both — two active rows for
    the same slot collide whether the shared spelling carries microseconds or not.
    The only consumer of this helper's exact text is the conflict *message*, which
    is advisory. Tests must therefore assert against the stored column's own value
    (or a prefix), never against this helper across dialects.
    """
    return f"{table_id}#{slot_date.isoformat()}#{slot_start.isoformat()}"
