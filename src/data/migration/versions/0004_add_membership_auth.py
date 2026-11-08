"""Add membership accounts and revocable sessions; retain audit history on rollback.

Revision ID: 0004
Revises: 0003

Audit storage belongs to revision 0002 and reservations to revision 0003.
This revision owns only membership accounts and sessions. Rolling it back to
0003 leaves those shared tables and their existing data untouched. A full
rollback to base still follows the older revisions' own downgrade semantics.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("email_normalized", sa.String(254), nullable=False),
        sa.Column("display_name", sa.String(80), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("role", sa.String(32), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("auth_version", sa.Integer(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "role IN ('customer', 'waiter', 'manager', 'admin')",
            name=op.f("ck_users_valid_role"),
        ),
        sa.CheckConstraint(
            "auth_version >= 1 AND version >= 1", name=op.f("ck_users_positive_versions")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
        sa.UniqueConstraint("email_normalized", name=op.f("uq_users_email_normalized")),
        mysql_engine="InnoDB",
    )
    op.create_table(
        "auth_policy_lock",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_auth_policy_lock")),
        mysql_engine="InnoDB",
    )
    policy_table = sa.table("auth_policy_lock", sa.column("id", sa.Integer()))
    op.bulk_insert(policy_table, [{"id": 1}])
    op.create_table(
        "auth_sessions",
        sa.Column("id", sa.String(64), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("current_refresh_digest", sa.String(64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_auth_sessions_user_id_users")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_auth_sessions")),
        sa.UniqueConstraint(
            "current_refresh_digest", name=op.f("uq_auth_sessions_current_refresh_digest")
        ),
        mysql_engine="InnoDB",
    )
    op.create_index(op.f("ix_auth_sessions_user_id"), "auth_sessions", ["user_id"])
    op.create_table(
        "used_refresh_tokens",
        sa.Column("digest", sa.String(64), nullable=False),
        sa.Column("session_id", sa.String(64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["auth_sessions.id"],
            name=op.f("fk_used_refresh_tokens_session_id_auth_sessions"),
        ),
        sa.PrimaryKeyConstraint("digest", name=op.f("pk_used_refresh_tokens")),
        mysql_engine="InnoDB",
    )
    op.create_index(
        op.f("ix_used_refresh_tokens_session_id"), "used_refresh_tokens", ["session_id"]
    )


def downgrade() -> None:
    # Revision 0002 owns audit_logs; rolling back this revision leaves it alone.
    # InnoDB requires these indexes while the foreign keys exist. Dropping each
    # child table removes its indexes and constraints together.
    op.drop_table("used_refresh_tokens")
    op.drop_table("auth_sessions")
    op.drop_table("auth_policy_lock")
    op.drop_table("users")
