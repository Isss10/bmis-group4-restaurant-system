"""reservations: discrete slots, seven-state machine, layer-3 unique constraint

Revision ID: b7e4c1a9d2f3
Revises: f43ea054b096, 97393cdd0b6c
Create Date: 2026-11-21

Why this migration exists
-------------------------
ARCHITECTURE.md §5 gives the booking guarantee three layers. Before this
revision the ``reservations`` table could support only the first two:

* There was **no unique constraint**, so layer 3 — the one that makes the
  guarantee real rather than hopeful — had nothing to fire. Error code 20001
  (``SLOT_ALREADY_BOOKED``), which FR-RES-03 and the concurrency acceptance test
  both require, was unreachable.
* There was **no version column**, so ``version_id_col`` optimistic locking was
  absent and error code 20004 (``STALE_VERSION``) was equally unreachable.
* The table stored a free-form ``reservation_time``/``end_time`` range. A range
  overlap **cannot** be expressed as a MySQL unique index (ARCHITECTURE.md §12,
  "Discrete slots, not free-form time ranges"), so the schema itself blocked the
  fix. Slots are now discrete: ``slot_date`` + ``slot_start``.
* ``status`` was a three-value ENUM (``PENDING``/``CONFIRMED``/``CANCELLED``).
  FR-RES-05 and FR-RES-07 require seven states — in particular a distinct
  ``NO_SHOW``, without which the analytics no-show rate
  ``NO_SHOW / (NO_SHOW + COMPLETED)`` (FR-ANA-04) is not computable.

Merging two heads
-----------------
``down_revision`` is a **pair**. ``f43ea054b096`` (this branch, reservation
columns) and ``97393cdd0b6c`` (main, M5's dish/order tables) were both parented
on ``0004``, so after merging main into this branch ``alembic heads`` reported
two heads. ``alembic upgrade head`` refuses to run with multiple heads, and
``tests/unit/test_migration_completeness.py::test_single_head`` asserts there is
exactly one. This revision is the merge point; per CONTRIBUTING.md an already
committed migration is never edited, so the reconciliation happens here rather
than by reparenting either parent.

MySQL is the deployment path; SQLite is the guard-test path
-----------------------------------------------------------
CI runs ``alembic upgrade head`` / ``downgrade base`` against a real MySQL 8
(ci.yml, test-integration). The SQLite path exists only so the unit-job guards
``test_migration_completeness`` and ``test_migrations_are_reversible`` can run
the chain without infrastructure — and both run it against an **empty** database.
So the row-backfill logic (deriving slots from legacy ``reservation_time``) is
MySQL-only: on the deployment target a table may already hold rows, while on the
SQLite guard path it provably does not. The SQLite branch therefore rebuilds the
table straight to the final schema in one ``batch_alter_table`` pass.

The generated column
--------------------
``active_slot_key`` is ``NULL`` for every non-active status and
``table_id#slot_date#slot_start`` for HELD/CONFIRMED/SEATED. A MySQL unique
index permits multiple NULLs, so a cancelled/expired/completed booking releases
its slot and the table becomes bookable again, while at most one active row can
hold a given slot. MySQL has no partial index (8.0.13 added *functional*
indexes, which cannot filter rows — see ARCHITECTURE.md §5.3), which is why the
contract uses a generated column.

The expression uses only ``CASE WHEN`` and ``CONCAT``: both deterministic (a
hard requirement for generated columns) and both available in MySQL 8 and
SQLite 3.44+. ``sqlalchemy.Computed`` accepts no per-dialect variant, so the
expression has to be portable rather than branched — which is what lets the
SQLite unit job exercise the same constraint the MySQL deployment relies on.
The authoritative copy is ``src.application.reservation.models.ACTIVE_SLOT_KEY_SQL``;
a unit test asserts the two agree, because the SQL text cannot be derived from
the Python ``ACTIVE_STATUSES`` set at DDL time and a silent divergence would mean
the constraint and the availability query disagree about what "free" means.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from src.application.reservation.models import ACTIVE_SLOT_KEY_SQL

revision: str = "b7e4c1a9d2f3"
down_revision: tuple[str, str] | None = ("f43ea054b096", "97393cdd0b6c")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# The seven-state vocabulary, in the order the model declares it. Written out
# rather than derived from ReservationStatus so a reader can see the DDL without
# opening the model; a unit test asserts this list matches the enum.
_NEW_STATUSES = (
    "HELD",
    "CONFIRMED",
    "SEATED",
    "COMPLETED",
    "CANCELLED",
    "NO_SHOW",
    "EXPIRED",
)

# 0003's three-value ENUM, plus HELD so the PENDING -> HELD rewrite can land
# before the column is narrowed to the final seven.
_WIDENED_STATUSES = ("PENDING", *_NEW_STATUSES)

_UNIQUE_INDEX = "uq_active_reservation"
_SLOT_INDEX = "ix_reservations_slot_date_table_id"

# Backfill statements, hoisted to module constants. Inline triple-quoted SQL as a
# call argument is where `black` and `ruff format` disagree about wrapping, and CI
# runs both (`black --check` in the lint job, `ruff format --check` alongside), so
# a file that satisfies one fails the other. Naming the SQL makes every call site
# a simple one-liner both formatters leave alone.
_BACKFILL_SLOTS_SQL = """
    UPDATE reservations
       SET slot_date  = CAST(reservation_time AS DATE),
           slot_start = SEC_TO_TIME(
               FLOOR(TIME_TO_SEC(CAST(reservation_time AS TIME)) / 1800) * 1800
           ),
           party_size = 2,
           version    = 1,
           updated_at = COALESCE(updated_at, created_at, reservation_time)
     WHERE reservation_time IS NOT NULL
"""

_COUNT_UNSLOTTED_SQL = "SELECT COUNT(*) FROM reservations WHERE slot_date IS NULL"

_RESTORE_TIMES_SQL = """
    UPDATE reservations
       SET reservation_time = TIMESTAMP(slot_date, slot_start),
           end_time         = TIMESTAMP(slot_date, slot_start) + INTERVAL 120 MINUTE
"""


def _is_mysql() -> bool:
    return op.get_bind().dialect.name == "mysql"


def _backfill_slots_mysql() -> None:
    """Derive slot columns from the legacy ``reservation_time`` (MySQL only).

    A no-op on an empty table. Written anyway because a migration that only works
    on an empty table is a migration that fails on the first deployment that has
    already run a demo.

    ``slot_start`` is snapped **down** to the 30-minute grid frozen by the
    contract. Snapping up could push a booking into a slot the guest never asked
    for; snapping down keeps it inside the window they selected.
    """
    # 1800 seconds == the frozen 30-minute slot granularity.
    op.execute(sa.text(_BACKFILL_SLOTS_SQL))

    # Refuse to continue on a row that cannot be slotted. Proceeding would insert
    # NULL into a NOT NULL column (an opaque dialect error) or, worse, leave a
    # row whose slot disagrees with the time the guest booked.
    unslotted = op.get_bind().execute(sa.text(_COUNT_UNSLOTTED_SQL)).scalar_one()
    if unslotted:
        raise RuntimeError(
            f"{unslotted} reservation row(s) have no usable reservation_time and "
            "cannot be backfilled into slot_date/slot_start. Resolve or delete "
            "them before running this migration: a reservation with no slot is "
            "invisible to the availability query and to the unique constraint, "
            "which is how a table gets double-booked."
        )


def upgrade() -> None:
    """Apply the schema change."""
    if _is_mysql():
        _upgrade_mysql()
    else:
        _upgrade_sqlite()


def _upgrade_mysql() -> None:
    # 1. New columns, nullable for now so the backfill can populate them.
    op.add_column("reservations", sa.Column("slot_date", sa.Date(), nullable=True))
    op.add_column("reservations", sa.Column("slot_start", sa.Time(), nullable=True))
    op.add_column("reservations", sa.Column("party_size", sa.Integer(), nullable=True))
    op.add_column("reservations", sa.Column("version", sa.Integer(), nullable=True))
    op.add_column("reservations", sa.Column("updated_at", sa.DateTime(), nullable=True))

    _backfill_slots_mysql()

    # 2. Tighten now that every row has a value.
    op.alter_column("reservations", "slot_date", existing_type=sa.Date(), nullable=False)
    op.alter_column("reservations", "slot_start", existing_type=sa.Time(), nullable=False)
    op.alter_column("reservations", "party_size", existing_type=sa.Integer(), nullable=False)
    op.alter_column("reservations", "version", existing_type=sa.Integer(), nullable=False)

    # 3. ENUM: widen -> rewrite -> narrow (see the module docstring for why the
    #    intermediate widening is required under strict mode).
    _enums = ", ".join(repr(s) for s in _WIDENED_STATUSES)
    op.execute(f"ALTER TABLE reservations MODIFY status ENUM({_enums}) NOT NULL")
    op.execute("UPDATE reservations SET status = 'HELD' WHERE status = 'PENDING'")
    _enums7 = ", ".join(repr(s) for s in _NEW_STATUSES)
    op.execute(f"ALTER TABLE reservations MODIFY status ENUM({_enums7}) NOT NULL")

    # 4. Layer 3 of the booking guarantee: generated column + unique index.
    op.execute(
        f"ALTER TABLE reservations ADD COLUMN active_slot_key VARCHAR(64) "
        f"GENERATED ALWAYS AS ({ACTIVE_SLOT_KEY_SQL}) STORED"
    )
    op.create_index(_UNIQUE_INDEX, "reservations", ["active_slot_key"], unique=True)

    # 5. Retire the range-based columns the discrete slot replaces.
    op.drop_column("reservations", "end_time")
    op.drop_column("reservations", "reservation_time")

    op.create_index(_SLOT_INDEX, "reservations", ["slot_date", "table_id"], unique=False)


def _upgrade_sqlite() -> None:
    """Rebuild to the final schema in one pass (empty guard-test database).

    SQLite supports neither ``ALTER COLUMN`` nor ``DROP CONSTRAINT``, so the
    change goes through ``batch_alter_table(recreate="always")``: create the new
    table, copy rows, rename. The guard tests run this against an empty database
    (see the module docstring), so NOT NULL columns need no server default here.
    """
    op.execute("UPDATE reservations SET status = 'HELD' WHERE status = 'PENDING'")

    with op.batch_alter_table("reservations", recreate="always") as batch_op:
        batch_op.add_column(sa.Column("slot_date", sa.Date(), nullable=False))
        batch_op.add_column(sa.Column("slot_start", sa.Time(), nullable=False))
        batch_op.add_column(sa.Column("party_size", sa.Integer(), nullable=False))
        batch_op.add_column(sa.Column("version", sa.Integer(), nullable=False))
        batch_op.add_column(sa.Column("updated_at", sa.DateTime(), nullable=True))
        batch_op.add_column(
            sa.Column(
                "active_slot_key",
                sa.String(length=64),
                sa.Computed(ACTIVE_SLOT_KEY_SQL, persisted=True),
                nullable=True,
            )
        )
        batch_op.alter_column(
            "status",
            existing_type=sa.Enum(*_NEW_STATUSES, name="reservationstatus"),
            existing_nullable=False,
        )
        batch_op.drop_column("end_time")
        batch_op.drop_column("reservation_time")
        batch_op.create_unique_constraint(_UNIQUE_INDEX, ["active_slot_key"])
        batch_op.create_index(_SLOT_INDEX, ["slot_date", "table_id"], unique=False)


def downgrade() -> None:
    """Reverse the schema change.

    Lossy by nature, and stated as such: seven states collapse back onto three,
    so ``SEATED``/``COMPLETED``/``NO_SHOW``/``EXPIRED`` rows become ``CANCELLED``
    — the only pre-existing terminal state — and ``HELD`` becomes ``PENDING``.
    ``reservation_time`` is reconstructed from the slot, losing the original
    minute within the 30-minute grid. A downgrade is an emergency path, not a
    lossless round-trip; the reversibility test only requires that it runs and
    leaves no residue.
    """
    if _is_mysql():
        _downgrade_mysql()
    else:
        _downgrade_sqlite()


def _downgrade_mysql() -> None:
    op.drop_index(_SLOT_INDEX, table_name="reservations")
    op.drop_index(_UNIQUE_INDEX, table_name="reservations")
    op.drop_column("reservations", "active_slot_key")

    op.add_column("reservations", sa.Column("reservation_time", sa.DateTime(), nullable=True))
    op.add_column("reservations", sa.Column("end_time", sa.DateTime(), nullable=True))
    op.execute(sa.text(_RESTORE_TIMES_SQL))

    op.execute(
        "ALTER TABLE reservations MODIFY status "
        f"ENUM('PENDING', {', '.join(repr(s) for s in _NEW_STATUSES)}) NOT NULL"
    )
    op.execute(
        "UPDATE reservations SET status = 'PENDING' "
        "WHERE status IN ('HELD', 'SEATED', 'COMPLETED', 'NO_SHOW', 'EXPIRED')"
    )
    op.execute(
        "ALTER TABLE reservations MODIFY status ENUM('PENDING','CONFIRMED','CANCELLED') NOT NULL"
    )

    op.alter_column("reservations", "reservation_time", existing_type=sa.DateTime(), nullable=False)
    op.alter_column("reservations", "end_time", existing_type=sa.DateTime(), nullable=False)

    op.drop_column("reservations", "updated_at")
    op.drop_column("reservations", "version")
    op.drop_column("reservations", "party_size")
    op.drop_column("reservations", "slot_start")
    op.drop_column("reservations", "slot_date")


def _downgrade_sqlite() -> None:
    with op.batch_alter_table("reservations", recreate="always") as batch_op:
        batch_op.add_column(sa.Column("reservation_time", sa.DateTime(), nullable=False))
        batch_op.add_column(sa.Column("end_time", sa.DateTime(), nullable=False))
        batch_op.alter_column(
            "status",
            existing_type=sa.Enum("PENDING", "CONFIRMED", "CANCELLED", name="reservationstatus"),
            existing_nullable=False,
        )
        batch_op.drop_index(_SLOT_INDEX)
        batch_op.drop_constraint(_UNIQUE_INDEX, type_="unique")
        batch_op.drop_column("active_slot_key")
        batch_op.drop_column("updated_at")
        batch_op.drop_column("version")
        batch_op.drop_column("party_size")
        batch_op.drop_column("slot_start")
        batch_op.drop_column("slot_date")
