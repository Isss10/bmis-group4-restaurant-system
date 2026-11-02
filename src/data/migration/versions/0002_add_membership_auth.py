"""Add membership accounts and revocable sessions; retain audit history on rollback.

Revision ID: 0002
Revises: 0001

The shared AuditLog model predates any migration for its table. A fresh database
needs that table before account-management transactions can write an audit row.
An existing audit_logs table is left untouched; downgrade always retains audit
history, including a table first created here. Authentication tables are owned by
this revision and are removed by downgrade.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _ensure_audit_logs() -> None:
    """Create the missing shared table without changing existing audit storage."""
    context = op.get_context()
    if context.as_sql:
        if context.dialect.name != "mysql":
            raise RuntimeError("Offline audit-table creation requires the MySQL dialect")
        # MySQL has no CREATE INDEX IF NOT EXISTS. Keeping indexes inside the
        # conditional table DDL makes offline SQL safe for a pre-existing table.
        op.execute(
            """CREATE TABLE IF NOT EXISTS audit_logs (
                id INTEGER NOT NULL AUTO_INCREMENT,
                occurred_at DATETIME NOT NULL,
                actor_id VARCHAR(64) NULL,
                actor_role VARCHAR(32) NULL,
                action VARCHAR(64) NOT NULL,
                entity_type VARCHAR(64) NOT NULL,
                entity_id VARCHAR(64) NULL,
                `before` JSON NULL,
                `after` JSON NULL,
                details JSON NULL,
                ip_address VARCHAR(45) NULL,
                user_agent VARCHAR(512) NULL,
                request_id VARCHAR(64) NULL,
                message TEXT NULL,
                CONSTRAINT pk_audit_logs PRIMARY KEY (id),
                INDEX ix_audit_logs_occurred_at (occurred_at),
                INDEX ix_audit_logs_actor_id (actor_id),
                INDEX ix_audit_logs_action (action),
                INDEX ix_audit_logs_entity_type (entity_type),
                INDEX ix_audit_logs_entity_id (entity_id),
                INDEX ix_audit_logs_request_id (request_id),
                INDEX ix_audit_actor_time (actor_id, occurred_at),
                INDEX ix_audit_entity (entity_type, entity_id),
                INDEX ix_audit_action_time (action, occurred_at)
            ) ENGINE=InnoDB"""
        )
        return
    if sa.inspect(op.get_bind()).has_table("audit_logs"):
        return
    op.create_table(
        "audit_logs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("actor_id", sa.String(64), nullable=True),
        sa.Column("actor_role", sa.String(32), nullable=True),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("entity_type", sa.String(64), nullable=False),
        sa.Column("entity_id", sa.String(64), nullable=True),
        sa.Column("before", sa.JSON(), nullable=True),
        sa.Column("after", sa.JSON(), nullable=True),
        sa.Column("details", sa.JSON(), nullable=True),
        sa.Column("ip_address", sa.String(45), nullable=True),
        sa.Column("user_agent", sa.String(512), nullable=True),
        sa.Column("request_id", sa.String(64), nullable=True),
        sa.Column("message", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_audit_logs")),
        mysql_engine="InnoDB",
    )
    for column in ("occurred_at", "actor_id", "action", "entity_type", "entity_id", "request_id"):
        op.create_index(f"ix_audit_logs_{column}", "audit_logs", [column])
    op.create_index("ix_audit_actor_time", "audit_logs", ["actor_id", "occurred_at"])
    op.create_index("ix_audit_entity", "audit_logs", ["entity_type", "entity_id"])
    op.create_index("ix_audit_action_time", "audit_logs", ["action", "occurred_at"])


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
    _ensure_audit_logs()


def downgrade() -> None:
    # Audit history intentionally survives rollback of the module that wrote it.
    # InnoDB requires these indexes while the foreign keys exist. Dropping each
    # child table removes its indexes and constraints together.
    op.drop_table("used_refresh_tokens")
    op.drop_table("auth_sessions")
    op.drop_table("auth_policy_lock")
    op.drop_table("users")
