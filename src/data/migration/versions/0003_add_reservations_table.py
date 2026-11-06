"""add reservations table

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-31

Why this migration exists
-------------------------
The ``Reservation`` model shipped in PR #3 (``src/application/reservation/models.py``)
declared ``__tablename__ = "reservations"`` but **no migration created that
table**. A database built with ``alembic upgrade head`` therefore had no
``reservations`` table, and the first ``ReservationRepository.create()`` call
raised ``OperationalError: no such table: reservations``.

The unit suite stayed green the whole time. Two reasons, both structural:

1. ``tests/conftest.py`` builds its schema with ``Base.metadata.create_all()``,
   which creates every table a *mapped* model declares — including ones with no
   migration. So tests never notice a missing migration.
2. No CI job ran ``alembic upgrade head``. The only occurrence of ``alembic``
   in ``ci.yml`` was a comment. So the pipeline never built a database the way
   deployment does.

This is the same class of defect as ``audit_logs`` (fixed in 0002), recurring
within six days. Two accompanying changes stop it recurring again:

* ``tests/unit/test_migration_completeness.py`` now discovers mapped models
  automatically instead of relying on a hand-maintained import list, so a model
  with no migration fails the unit job immediately.
* The ``test-integration`` job now runs ``alembic upgrade head`` before the
  tests, so the pipeline exercises the real deployment path.

Column notes
------------
The DDL mirrors ``src/application/reservation/models.py`` exactly:

* ``status`` is a MySQL ``ENUM`` of ``ReservationStatus`` members. SQLite renders
  it as ``VARCHAR(9)`` — the length of the longest member (``CANCELLED``).
* ``created_at`` is nullable with an application-side default. The model passes
  ``datetime.utcnow`` (see the note below), so the column has no server default
  and a row inserted without going through the ORM gets ``NULL``.
* ``ix_reservations_id`` is redundant with the primary key but the model
  declares ``index=True`` on ``id``, so the migration reproduces it. Keeping
  model and migration identical matters: ``alembic revision --autogenerate``
  must produce an empty diff, otherwise every developer sees phantom changes.

Known follow-up (NOT changed here, needs the module owner's agreement)
----------------------------------------------------------------------
``models.py`` uses ``default=datetime.utcnow``. ``datetime.utcnow()`` is
deprecated since Python 3.12 and returns a *naive* timestamp. CI runs Python
3.11 so nothing fails today, but on 3.12+ a deprecation warning is emitted at
insert time — and ``pyproject.toml`` sets ``filterwarnings = ["error"]``, so a
future interpreter bump turns that into a test failure. The rest of the codebase
uses ``datetime.now(timezone.utc)``. Changing it alters naive-vs-aware semantics
for the whole reservation module, so it is flagged rather than silently fixed.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "reservations",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.String(length=50), nullable=False),
        sa.Column("table_id", sa.Integer(), nullable=False),
        sa.Column("reservation_time", sa.DateTime(), nullable=False),
        sa.Column(
            "status",
            sa.Enum("PENDING", "CONFIRMED", "CANCELLED", name="reservationstatus"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_reservations"),
    )
    op.create_index("ix_reservations_id", "reservations", ["id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_reservations_id", table_name="reservations")
    op.drop_table("reservations")
