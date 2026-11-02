"""Verify the deployed auth schema and safe rollback without a MySQL dependency.

SQLite exercises portable DDL and storage constraints here. It is deliberately
not evidence for MySQL locking or concurrent authentication behaviour.
"""

from __future__ import annotations

import importlib.util
from io import StringIO
from pathlib import Path
from types import ModuleType

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, insert, inspect, select, text
from sqlalchemy.exc import IntegrityError

from src.common.audit import AuditLog
from src.data.schema.membership import AuthPolicyLock, AuthSession, UsedRefreshToken, User


def _migration() -> ModuleType:
    path = (
        Path(__file__).resolve().parents[2]
        / "src/data/migration/versions/0002_add_membership_auth.py"
    )
    spec = importlib.util.spec_from_file_location("membership_auth_revision", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_auth_migration_matches_model_and_seeds_lock() -> None:
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        with Operations.context(MigrationContext.configure(connection)):
            _migration().upgrade()
        inspector = inspect(connection)
        for model in (User, AuthPolicyLock, AuthSession, UsedRefreshToken, AuditLog):
            deployed = {
                column["name"]: column for column in inspector.get_columns(model.__tablename__)
            }
            assert set(deployed) == set(model.__table__.columns.keys())
            assert {(name, column["nullable"]) for name, column in deployed.items()} == {
                (column.name, column.nullable) for column in model.__table__.columns
            }
        assert connection.scalar(select(AuthPolicyLock.id)) == 1
        names = {index["name"] for index in inspector.get_indexes("audit_logs")}
        assert {"ix_audit_actor_time", "ix_audit_entity", "ix_audit_action_time"} <= names
    engine.dispose()


def test_migrated_database_enforces_unique_email_and_roles() -> None:
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        with Operations.context(MigrationContext.configure(connection)):
            _migration().upgrade()
        values = {
            "email_normalized": "customer@example.com",
            "display_name": "Customer",
            "password_hash": "synthetic-hash-for-schema-test",
            "role": "customer",
            "is_active": True,
            "auth_version": 1,
            "version": 1,
        }
        connection.execute(insert(User), values)
        with pytest.raises(IntegrityError), connection.begin_nested():
            connection.execute(insert(User), values)
        with pytest.raises(IntegrityError), connection.begin_nested():
            connection.execute(
                insert(User),
                {**values, "email_normalized": "invalid@example.com", "role": "superadmin"},
            )
    engine.dispose()


@pytest.mark.parametrize("preexisting", [False, True])
def test_downgrade_preserves_audit_history_and_reupgrade(preexisting: bool) -> None:
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        if preexisting:
            AuditLog.__table__.create(connection)
            connection.execute(text("ALTER TABLE audit_logs ADD COLUMN legacy_marker VARCHAR(20)"))
        context = MigrationContext.configure(connection)
        migration = _migration()
        with Operations.context(context):
            migration.upgrade()
        connection.execute(
            insert(AuditLog),
            {"action": "user.role_changed", "entity_type": "User", "entity_id": "1"},
        )
        with Operations.context(context):
            migration.downgrade()
        tables = inspect(connection).get_table_names()
        assert "audit_logs" in tables
        assert "users" not in tables
        assert "auth_sessions" not in tables
        assert connection.scalar(select(AuditLog.action)) == "user.role_changed"
        if preexisting:
            assert "legacy_marker" in {
                column["name"] for column in inspect(connection).get_columns("audit_logs")
            }
        with Operations.context(context):
            migration.upgrade()
        assert connection.scalar(select(AuthPolicyLock.id)) == 1
        assert connection.scalar(select(AuditLog.action)) == "user.role_changed"
    engine.dispose()


def test_offline_mysql_migration_contains_safe_audit_ddl() -> None:
    output = StringIO()
    context = MigrationContext.configure(
        dialect_name="mysql", opts={"as_sql": True, "output_buffer": output}
    )
    with Operations.context(context):
        _migration().upgrade()
    ddl = output.getvalue()
    assert "CREATE TABLE IF NOT EXISTS audit_logs" in ddl
    assert "INDEX ix_audit_entity (entity_type, entity_id)" in ddl
    assert "INSERT INTO auth_policy_lock (id) VALUES (1)" in ddl
