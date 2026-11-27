"""add audit_logs table

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-25

Why this migration exists
-------------------------
``src/common/audit.py`` defines the ``AuditLog`` model, and Objective (f)
requires "audit logs" for back-office changes. The model was merged without a
matching migration, so on any database created by ``alembic upgrade head`` the
table simply did not exist and every ``record_audit()`` call raised::

    sqlalchemy.exc.OperationalError: (sqlite3.OperationalError)
    no such table: audit_logs

That failure surfaces only at runtime, on the first audited action — the unit
tests pass because they build the schema from ``Base.metadata`` instead of
running migrations. This file closes that gap.

Column names
------------
``before`` is a reserved word in MySQL 8.0 and SQLite. SQLAlchemy's DDL
compiler quotes it per dialect (`` `before` `` on MySQL, ``"before"`` on
SQLite), so no renaming is needed — but do not hand-write raw DDL against this
table without quoting that column.

Downgrade is a plain drop: nothing else references ``audit_logs``.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "audit_logs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        # Timezone-aware on purpose: audit trails are read across regions and an
        # ambiguous local time is worthless in an investigation. The value is
        # supplied by the application (see AuditLog.occurred_at), so there is no
        # server_default — the DB clock and the app clock would otherwise drift.
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        # NULL for anonymous or system-initiated actions, hence nullable.
        sa.Column("actor_id", sa.String(length=64), nullable=True),
        # Role is snapshotted at action time rather than joined from users, so
        # the history stays correct after someone's role changes.
        sa.Column("actor_role", sa.String(length=32), nullable=True),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("entity_type", sa.String(length=64), nullable=False),
        sa.Column("entity_id", sa.String(length=64), nullable=True),
        # Redacted JSON snapshots; see AuditLog._redact for what is stripped.
        sa.Column("before", sa.JSON(), nullable=True),
        sa.Column("after", sa.JSON(), nullable=True),
        sa.Column("details", sa.JSON(), nullable=True),
        # 45 chars is the length of the longest IPv4-mapped IPv6 address.
        sa.Column("ip_address", sa.String(length=45), nullable=True),
        sa.Column("user_agent", sa.String(length=512), nullable=True),
        sa.Column("request_id", sa.String(length=64), nullable=True),
        sa.Column("message", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_audit_logs")),
        comment="Append-only trail of state-changing back-office actions",
    )

    # Single-column indexes matching the model's `index=True` declarations.
    op.create_index(op.f("ix_audit_logs_occurred_at"), "audit_logs", ["occurred_at"])
    op.create_index(op.f("ix_audit_logs_actor_id"), "audit_logs", ["actor_id"])
    op.create_index(op.f("ix_audit_logs_action"), "audit_logs", ["action"])
    op.create_index(op.f("ix_audit_logs_entity_type"), "audit_logs", ["entity_type"])
    op.create_index(op.f("ix_audit_logs_entity_id"), "audit_logs", ["entity_id"])
    op.create_index(op.f("ix_audit_logs_request_id"), "audit_logs", ["request_id"])

    # Composite indexes for the manager dashboard's two query shapes:
    # "what did this person do" and "who touched this object".
    op.create_index("ix_audit_actor_time", "audit_logs", ["actor_id", "occurred_at"])
    op.create_index("ix_audit_entity", "audit_logs", ["entity_type", "entity_id"])
    op.create_index("ix_audit_action_time", "audit_logs", ["action", "occurred_at"])


def downgrade() -> None:
    op.drop_index("ix_audit_action_time", table_name="audit_logs")
    op.drop_index("ix_audit_entity", table_name="audit_logs")
    op.drop_index("ix_audit_actor_time", table_name="audit_logs")
    op.drop_index(op.f("ix_audit_logs_request_id"), table_name="audit_logs")
    op.drop_index(op.f("ix_audit_logs_entity_id"), table_name="audit_logs")
    op.drop_index(op.f("ix_audit_logs_entity_type"), table_name="audit_logs")
    op.drop_index(op.f("ix_audit_logs_action"), table_name="audit_logs")
    op.drop_index(op.f("ix_audit_logs_actor_id"), table_name="audit_logs")
    op.drop_index(op.f("ix_audit_logs_occurred_at"), table_name="audit_logs")
    op.drop_table("audit_logs")
