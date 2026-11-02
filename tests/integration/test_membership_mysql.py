"""Real-MySQL proofs of authentication transactions, locks and migrations.

Only the disposable database named ``restaurant_test`` is accepted. The tests
reuse the project's MySQL fixture and independent sessions; SQLite is never
used as a substitute for the InnoDB concurrency behaviour tested here.
"""

from __future__ import annotations

import os
import secrets
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
from typing import Any

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import MetaData, func, inspect, select, text
from sqlalchemy.orm import Session, sessionmaker

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
from src.data.database import get_engine, get_session_factory, reset_engine
from src.data.repository.membership import MembershipRepository
from src.data.schema.membership import AuthPolicyLock, AuthSession, UsedRefreshToken, User

pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
def scratch_database_only() -> Settings:
    """Run before the shared db_session fixture can create/drop any tables."""
    if not os.environ.get("APP_DB_HOST"):
        pytest.skip("Real-MySQL membership checks require APP_DB_HOST and restaurant_test")
    cfg = get_settings()
    if cfg.environment != "testing" or cfg.db_name != "restaurant_test":
        pytest.fail("Refusing destructive integration checks outside testing/restaurant_test")
    engine = get_engine()
    if engine.dialect.name != "mysql" or engine.url.database != "restaurant_test":
        pytest.fail("Membership transaction tests require MySQL restaurant_test")
    with engine.connect() as connection:
        if connection.scalar(text("SELECT DATABASE()")) != "restaurant_test":
            pytest.fail("Connected database is not restaurant_test")
    return cfg


@pytest.fixture
def mysql_factory(scratch_database_only: Settings, db_session: Session) -> sessionmaker[Session]:
    """The shared fixture owns schema creation/cleanup; workers own sessions."""
    if db_session.get(AuthPolicyLock, 1) is None:
        db_session.add(AuthPolicyLock(id=1))
        db_session.commit()
    return get_session_factory()


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


def test_alembic_up_down_up_builds_membership_from_empty_mysql(
    scratch_database_only: Settings,
) -> None:
    """Own only an initially empty restaurant_test schema; never erase other data."""
    engine = get_engine()
    if inspect(engine).get_table_names():
        pytest.fail("Fresh-migration check requires empty restaurant_test; refusing to erase data")
    root = Path(__file__).resolve().parents[2]
    cfg = Config(str(root / "alembic.ini"))
    cfg.set_main_option("script_location", str(root / "src/data/migration"))
    cfg.set_main_option("prepend_sys_path", str(root))
    cfg.set_main_option("path_separator", "os")
    expected = {
        User.__tablename__,
        AuthSession.__tablename__,
        UsedRefreshToken.__tablename__,
        AuthPolicyLock.__tablename__,
        AuditLog.__tablename__,
    }
    try:
        command.upgrade(cfg, "head")
        assert expected <= set(inspect(engine).get_table_names())
        with Session(engine) as session:
            assert session.get(AuthPolicyLock, 1) is not None
            audit = AuditLog(
                action="user.status_changed",
                entity_type="User",
                entity_id="historical",
                after={"is_active": False},
            )
            session.add(audit)
            session.commit()
            audit_id = audit.id
        command.downgrade(cfg, "base")
        assert set(inspect(engine).get_table_names()) == {"audit_logs", "alembic_version"}
        with Session(engine) as session:
            retained = session.get(AuditLog, audit_id)
            assert retained is not None and retained.entity_id == "historical"
            assert retained.after == {"is_active": False}
        command.upgrade(cfg, "head")
        assert expected <= set(inspect(engine).get_table_names())
        with Session(engine) as session:
            assert session.get(AuthPolicyLock, 1) is not None
            assert session.scalar(select(func.count()).select_from(User)) == 0
            assert session.get(AuditLog, audit_id) is not None
            assert session.scalar(select(func.count()).select_from(AuditLog)) == 1
    finally:
        # The schema was verified empty before this test created anything.
        # MySQL DDL is not transactional: clean up even partially applied DDL.
        owned = MetaData()
        owned.reflect(bind=engine)
        owned.drop_all(bind=engine)
        reset_engine()
