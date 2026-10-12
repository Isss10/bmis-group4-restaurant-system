"""Database engine, session management and the ORM base."""

from __future__ import annotations

import logging
from collections.abc import Generator, Iterator
from contextlib import contextmanager
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, MetaData, create_engine, event, func, select
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    Session,
    mapped_column,
    sessionmaker,
)
from sqlalchemy.pool import QueuePool

from src.common.config import Settings, get_settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Naming convention for constraints and indexes.
# ---------------------------------------------------------------------------
NAMING_CONVENTION: dict[str, str] = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """Declarative base for every ORM model."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class TimestampMixin:
    """Adds server-maintained created_at / updated_at to a model."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )


# ---------------------------------------------------------------------------
# Engine & session factory
# ---------------------------------------------------------------------------
_engine: Engine | None = None
_session_factory: sessionmaker[Session] | None = None


def _build_engine(settings: Settings) -> Engine:
    """Create the SQLAlchemy engine with pooling suited to MySQL 8."""
    engine = create_engine(
        settings.database_url,
        poolclass=QueuePool,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
        pool_recycle=settings.db_pool_recycle,
        pool_pre_ping=True,
        echo=settings.db_echo_sql,
        future=True,
    )

    @event.listens_for(engine, "connect")
    def _set_mysql_session_vars(dbapi_connection: Any, _record: Any) -> None:
        """Pin session variables that the concurrency guarantees rely on."""
        try:
            with dbapi_connection.cursor() as cursor:
                cursor.execute("SET SESSION TRANSACTION ISOLATION LEVEL REPEATABLE READ")
                cursor.execute("SET SESSION sql_mode='STRICT_TRANS_TABLES'")
            dbapi_connection.autocommit = False
        except Exception:
            logger.debug("Could not set MySQL session variables; continuing", exc_info=True)

    return engine


def get_engine(settings: Settings | None = None) -> Engine:
    """Return the process-wide engine, creating it on first use."""
    global _engine
    if _engine is None:
        _engine = _build_engine(settings or get_settings())
    return _engine


def get_session_factory(settings: Settings | None = None) -> sessionmaker[Session]:
    """Return the process-wide Session factory."""
    global _session_factory
    if _session_factory is None:
        _session_factory = sessionmaker(
            bind=get_engine(settings),
            class_=Session,
            expire_on_commit=False,
            autoflush=False,
        )
    return _session_factory


def reset_engine() -> None:
    """Dispose the engine and clear the singletons."""
    global _engine, _session_factory
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _session_factory = None


# ---------------------------------------------------------------------------
# FastAPI dependency
# ---------------------------------------------------------------------------
def get_db() -> Generator[Session, None, None]:
    """Yield a request-scoped session, rolling back on any exception."""
    session = get_session_factory()()
    try:
        yield session
    except SQLAlchemyError:
        session.rollback()
        raise
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


@contextmanager
def session_scope() -> Iterator[Session]:
    """Transactional scope for code outside a request (scripts, jobs, tests)."""
    session = get_session_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


# ---------------------------------------------------------------------------
# Concurrency helpers
# ---------------------------------------------------------------------------
def lock_for_update(session: Session, model: type[Any], *where: Any) -> Any | None:
    """Load one row with SELECT ... FOR UPDATE."""
    stmt = select(model).where(*where).with_for_update()
    return session.execute(stmt).scalar_one_or_none()


def count_for_update(session: Session, model: type[Any], *where: Any) -> int:
    """Count rows matching `where`, locking them for the current transaction."""
    stmt = select(func.count()).select_from(model).where(*where).with_for_update()
    result = session.execute(stmt).scalar_one()
    return int(result or 0)
