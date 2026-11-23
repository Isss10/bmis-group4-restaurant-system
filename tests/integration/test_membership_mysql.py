"""Real-MySQL proofs of authentication transactions, locks and migrations.

Use the MySQL server configured for ``restaurant_test``. Each case creates its
own temporary schema so CI's migration smoke test and other modules can keep
their tables and Alembic markers.
"""

from __future__ import annotations

import os
import secrets
from argparse import Namespace
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from threading import Barrier
from typing import Any

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import MetaData, Table, create_engine, func, inspect, select, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.schema import CreateSchema, DropSchema

from src.application.membership.service import MembershipError, MembershipService
from src.common.audit import AuditLog
from src.common.config import Settings, get_settings
from src.common.security import (
    InvalidTokenError,
    Role,
    TokenPayload,
    decode_access_token,
    hash_password,
)
from src.data.repository.membership import MembershipRepository
from src.data.schema.membership import AuthPolicyLock, AuthSession, UsedRefreshToken, User

pytestmark = pytest.mark.integration


@pytest.fixture
def scratch_database_only() -> Settings:
    """Allow schema creation only on the configured MySQL test server."""
    if not os.environ.get("APP_DB_HOST"):
        pytest.skip("Real-MySQL membership checks require APP_DB_HOST and restaurant_test")
    cfg = get_settings()
    if cfg.environment != "testing" or cfg.db_name != "restaurant_test":
        pytest.fail("Membership transaction tests require testing/restaurant_test")
    return cfg


@pytest.fixture
def membership_engine(scratch_database_only: Settings) -> Iterator[Engine]:
    schema_name = f"restaurant_test_auth_{secrets.token_hex(8)}"
    admin = create_engine(scratch_database_only.database_url)
    try:
        with admin.begin() as connection:
            if connection.scalar(text("SELECT DATABASE()")) != "restaurant_test":
                pytest.fail("Connected database is not restaurant_test")
            connection.execute(CreateSchema(schema_name))

        try:
            engine = create_engine(
                admin.url.set(database=schema_name), isolation_level="READ COMMITTED"
            )
            try:
                yield engine
            finally:
                engine.dispose()
        finally:
            # Only the schema created by this fixture can be dropped.
            with admin.begin() as connection:
                connection.execute(DropSchema(schema_name))
    finally:
        admin.dispose()


def migration_config(engine: Engine) -> Config:
    root = Path(__file__).resolve().parents[2]
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "src/data/migration"))
    config.set_main_option("prepend_sys_path", str(root))
    config.set_main_option("path_separator", "os")
    url = engine.url.render_as_string(hide_password=False)
    config.cmd_opts = Namespace(x=[f"url={url}"])  # type: ignore[assignment]
    return config


@pytest.fixture
def mysql_factory(membership_engine: Engine) -> sessionmaker[Session]:
    """Use deployed membership tables and one independent session per worker."""
    command.upgrade(migration_config(membership_engine), "0004")
    return sessionmaker(bind=membership_engine, expire_on_commit=False, autoflush=False)


def service(factory: sessionmaker[Session], cfg: Settings) -> MembershipService:
    return MembershipService(MembershipRepository(factory()), cfg)


def seed_users(factory: sessionmaker[Session], roles: list[Role]) -> tuple[str, list[int]]:
    password = secrets.token_urlsafe(24)
    hashed = hash_password(password)
    with factory() as session:
        users = [
            User(
                email_normalized=f"member{index}@example.com",
                display_name=f"Member {index}",
                password_hash=hashed,
                role=role.value,
                is_active=True,
                auth_version=1,
            )
            for index, role in enumerate(roles)
        ]
        session.add_all(users)
        session.commit()
        return password, [user.id for user in users]


def login(
    factory: sessionmaker[Session], cfg: Settings, email: str, password: str
) -> tuple[TokenPayload, str]:
    svc = service(factory, cfg)
    try:
        result = svc.login(email, password)
        return decode_access_token(result.data["access_token"], cfg), result.refresh
    finally:
        svc.repo.session.close()


def race_two(work: Callable[[int], int]) -> list[int]:
    barrier = Barrier(2, timeout=15)

    def run(index: int) -> int:
        barrier.wait()
        return work(index)

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(run, index) for index in range(2)]
        return [future.result(timeout=60) for future in futures]


@pytest.mark.concurrency
def test_parallel_registration_keeps_one_normalized_email(
    mysql_factory: sessionmaker[Session], scratch_database_only: Settings
) -> None:
    password = secrets.token_urlsafe(24)

    def register(index: int) -> int:
        svc = service(mysql_factory, scratch_database_only)
        try:
            svc.register(
                email=["SAME@EXAMPLE.COM", "same@example.com"][index],
                password=password,
                display_name=f"Concurrent customer {index}",
            )
            return 201
        except MembershipError as exc:
            return exc.status
        finally:
            svc.repo.session.close()

    assert sorted(race_two(register)) == [201, 409]
    with mysql_factory() as session:
        users = session.scalars(select(User)).all()
        assert len(users) == 1
        assert users[0].email_normalized == "same@example.com"
        assert users[0].role == "customer"


@pytest.mark.concurrency
def test_parallel_refresh_issues_one_successor_then_replay_revokes_family(
    mysql_factory: sessionmaker[Session], scratch_database_only: Settings
) -> None:
    password, _ = seed_users(mysql_factory, [Role.CUSTOMER])
    identity, refresh = login(mysql_factory, scratch_database_only, "member0@example.com", password)

    def rotate(_index: int) -> int:
        svc = service(mysql_factory, scratch_database_only)
        try:
            svc.refresh(refresh)
            return 200
        except MembershipError as exc:
            return exc.status
        finally:
            svc.repo.session.close()

    assert sorted(race_two(rotate)) == [200, 401]
    with mysql_factory() as session:
        assert session.scalar(select(func.count()).select_from(AuthSession)) == 1
        assert session.scalar(select(func.count()).select_from(UsedRefreshToken)) == 1
        stored = session.get(AuthSession, identity.sid)
        assert stored is not None and stored.revoked_at is not None


@pytest.mark.concurrency
@pytest.mark.parametrize("target_self", [True, False], ids=["self-demotion", "mutual-demotion"])
def test_parallel_admin_demotions_preserve_one_active_admin(
    mysql_factory: sessionmaker[Session], scratch_database_only: Settings, target_self: bool
) -> None:
    password, user_ids = seed_users(mysql_factory, [Role.ADMIN, Role.ADMIN])
    actors = [
        login(mysql_factory, scratch_database_only, f"member{index}@example.com", password)[0]
        for index in range(2)
    ]

    def demote(index: int) -> int:
        svc = service(mysql_factory, scratch_database_only)
        try:
            target = user_ids[index if target_self else 1 - index]
            svc.change_user(target, actor=actors[index], version=1, role=Role.CUSTOMER)
            return 200
        except MembershipError as exc:
            return exc.status
        except InvalidTokenError:
            return 401
        finally:
            svc.repo.session.close()

    outcomes = race_two(demote)
    assert outcomes.count(200) == 1
    assert all(status in {200, 401, 409} for status in outcomes)
    with mysql_factory() as session:
        admins = session.scalars(
            select(User).where(User.role == Role.ADMIN.value, User.is_active.is_(True))
        ).all()
        assert len(admins) == 1
        assert (
            session.scalar(
                select(func.count())
                .select_from(AuditLog)
                .where(AuditLog.action == "user.role_changed")
            )
            == 1
        )


def test_audit_failure_rolls_back_user_and_session_revocation_in_mysql(
    mysql_factory: sessionmaker[Session],
    scratch_database_only: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    password, user_ids = seed_users(mysql_factory, [Role.ADMIN, Role.CUSTOMER])
    admin, _ = login(mysql_factory, scratch_database_only, "member0@example.com", password)
    customer, _ = login(mysql_factory, scratch_database_only, "member1@example.com", password)

    def fail_audit(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("Injected audit failure")

    monkeypatch.setattr("src.application.membership.service.record_audit", fail_audit)
    svc = service(mysql_factory, scratch_database_only)
    try:
        with pytest.raises(RuntimeError, match="Injected audit failure"):
            svc.change_user(user_ids[1], actor=admin, version=1, is_active=False)
    finally:
        svc.repo.session.close()
    with mysql_factory() as session:
        user = session.get(User, user_ids[1])
        assert user is not None and user.is_active
        assert (user.version, user.auth_version) == (1, 1)
        stored_session = session.get(AuthSession, customer.sid)
        assert stored_session is not None and stored_session.revoked_at is None
        assert (
            session.scalar(
                select(func.count())
                .select_from(AuditLog)
                .where(AuditLog.action == "user.status_changed")
            )
            == 0
        )


def test_mysql_membership_upgrade_and_rollback_preserve_prior_data(
    membership_engine: Engine,
) -> None:
    config = migration_config(membership_engine)
    command.upgrade(config, "0003")
    with membership_engine.begin() as connection:
        main_tables = set(inspect(connection).get_table_names())
        # The deployed 0003 columns are stable even when the current reservation
        # or audit models evolve. Keep the historical fixture tied to revision 0003.
        metadata = MetaData()
        audit = Table("audit_logs", metadata, autoload_with=connection)
        reservation = Table("reservations", metadata, autoload_with=connection)
        connection.execute(
            audit.insert(),
            {
                "id": 41,
                "occurred_at": datetime(2026, 11, 8, 12),
                "action": "reservation.created",
                "entity_type": "Reservation",
                "entity_id": "51",
                "after": {"status": "CONFIRMED"},
            },
        )
        connection.execute(
            reservation.insert(),
            {
                "id": 51,
                "user_id": "existing-main-customer",
                "table_id": 3,
                "reservation_time": datetime(2026, 11, 23, 12),
                "status": "CONFIRMED",
                "created_at": datetime(2026, 11, 8, 12),
            },
        )
        original_audit = connection.execute(select(audit)).mappings().one()
        original_reservation = connection.execute(select(reservation)).mappings().one()

    auth_tables = {
        model.__tablename__ for model in (User, AuthSession, UsedRefreshToken, AuthPolicyLock)
    }
    for upgrade in (True, False, True):
        if upgrade:
            command.upgrade(config, "0004")
        else:
            command.downgrade(config, "0003")
        with membership_engine.connect() as connection:
            assert set(inspect(connection).get_table_names()) == (
                main_tables | auth_tables if upgrade else main_tables
            )
            assert connection.execute(select(audit)).mappings().one() == original_audit
            assert connection.execute(select(reservation)).mappings().one() == original_reservation
            if upgrade:
                assert connection.scalar(select(AuthPolicyLock.id)) == 1
                assert connection.scalar(select(func.count()).select_from(User)) == 0
