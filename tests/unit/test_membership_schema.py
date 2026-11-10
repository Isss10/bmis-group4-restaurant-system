"""Verify the deployed auth schema and safe rollback without a MySQL dependency.

SQLite exercises portable DDL and storage constraints here. It is deliberately
not evidence for MySQL locking or concurrent authentication behaviour.
"""

from __future__ import annotations

import importlib.util
from argparse import Namespace
from datetime import datetime
from io import StringIO
from pathlib import Path
from types import ModuleType

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, insert, inspect, select, text
from sqlalchemy.exc import IntegrityError

from src.application.reservation.models import Reservation, ReservationStatus
from src.common.audit import AuditLog
from src.data.database import Base
from src.data.schema.membership import AuthPolicyLock, AuthSession, UsedRefreshToken, User

_ROOT = Path(__file__).resolve().parents[2]
_AUTH_TABLES = {
    model.__tablename__ for model in (User, AuthPolicyLock, AuthSession, UsedRefreshToken)
}


def _alembic_config(url: str) -> Config:
    config = Config(str(_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(_ROOT / "src/data/migration"))
    config.cmd_opts = Namespace(x=[f"url={url}"])  # type: ignore[assignment]
    return config


def _migration() -> ModuleType:
    path = _ROOT / "src/data/migration/versions/0004_add_membership_auth.py"
    spec = importlib.util.spec_from_file_location("membership_auth_revision", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_auth_migration_matches_model_and_seeds_lock() -> None:
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        # The prior main-branch migration owns this table, not revision 0004.
        AuditLog.__table__.create(connection)
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


@pytest.mark.parametrize("extra_audit_column", [False, True])
def test_downgrade_preserves_audit_history_and_reupgrade(extra_audit_column: bool) -> None:
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        AuditLog.__table__.create(connection)
        if extra_audit_column:
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
        if extra_audit_column:
            assert "legacy_marker" in {
                column["name"] for column in inspect(connection).get_columns("audit_logs")
            }
        with Operations.context(context):
            migration.upgrade()
        assert connection.scalar(select(AuthPolicyLock.id)) == 1
        assert connection.scalar(select(AuditLog.action)) == "user.role_changed"
    engine.dispose()


def test_offline_mysql_migration_owns_auth_tables_only() -> None:
    output = StringIO()
    context = MigrationContext.configure(
        dialect_name="mysql", opts={"as_sql": True, "output_buffer": output}
    )
    with Operations.context(context):
        _migration().upgrade()
    ddl = output.getvalue()
    assert "audit_logs" not in ddl
    assert "reservations" not in ddl
    for table in _AUTH_TABLES:
        assert f"CREATE TABLE {table}" in ddl
    assert "INSERT INTO auth_policy_lock (id) VALUES (1)" in ddl


def test_membership_is_the_single_head_after_main_migrations() -> None:
    script = ScriptDirectory.from_config(_alembic_config("sqlite://"))
    assert script.get_heads() == ["0004"]
    assert [revision.revision for revision in script.walk_revisions()] == [
        "0004",
        "0003",
        "0002",
        "0001",
    ]
    assert _migration().down_revision == "0003"


def test_main_database_upgrade_and_module_rollback_preserve_business_data(tmp_path: Path) -> None:
    url = f"sqlite:///{(tmp_path / 'main_upgrade.db').as_posix()}"
    config = _alembic_config(url)
    engine = create_engine(url)
    try:
        command.upgrade(config, "0003")
        with engine.begin() as connection:
            before_tables = set(inspect(connection).get_table_names())
            connection.execute(
                insert(AuditLog),
                {
                    "id": 41,
                    "action": "reservation.created",
                    "entity_type": "Reservation",
                    "entity_id": "51",
                },
            )
            connection.execute(
                insert(Reservation),
                {
                    "id": 51,
                    "user_id": "existing-main-customer",
                    "table_id": 3,
                    "reservation_time": datetime(2026, 11, 23, 12),
                    "status": ReservationStatus.CONFIRMED,
                    "created_at": datetime(2026, 11, 8, 12),
                },
            )
            original_audit = connection.execute(select(AuditLog)).mappings().one()
            original_reservation = connection.execute(select(Reservation)).mappings().one()

        for operation in ("upgrade", "downgrade", "upgrade"):
            if operation == "upgrade":
                command.upgrade(config, "head")
            else:
                command.downgrade(config, "0003")
            with engine.connect() as connection:
                assert connection.execute(select(AuditLog)).mappings().one() == original_audit
                assert (
                    connection.execute(select(Reservation)).mappings().one() == original_reservation
                )
                tables = set(inspect(connection).get_table_names())
                assert tables == (
                    before_tables | _AUTH_TABLES if operation == "upgrade" else before_tables
                )
                if operation == "upgrade":
                    assert connection.scalar(select(AuthPolicyLock.id)) == 1

        command.downgrade(config, "base")
        with engine.connect() as connection:
            assert set(inspect(connection).get_table_names()) == {"alembic_version"}
        command.upgrade(config, "head")
        with engine.connect() as connection:
            assert set(inspect(connection).get_table_names()) == before_tables | _AUTH_TABLES
    finally:
        engine.dispose()


def test_auth_migration_has_no_autogenerate_drift(tmp_path: Path) -> None:
    url = f"sqlite:///{(tmp_path / 'auth_drift.db').as_posix()}"
    command.upgrade(_alembic_config(url), "head")
    engine = create_engine(url)
    try:
        with engine.connect() as connection:
            context = MigrationContext.configure(
                connection,
                opts={
                    "compare_type": True,
                    "compare_server_default": True,
                    "include_object": lambda obj, name, kind, reflected, compare_to: (
                        name in _AUTH_TABLES if kind == "table" else True
                    ),
                },
            )
            assert compare_metadata(context, Base.metadata) == []
    finally:
        engine.dispose()
