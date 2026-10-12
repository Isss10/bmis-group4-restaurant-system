"""Database engine, session management and the ORM base.

This module is the foundation for the concurrency guarantees required by
Objective (d). Three mechanisms work together — **all three are needed**, none
is sufficient on its own:

1. **Transactions** with an explicit isolation level, so a booking either
   fully commits or fully rolls back.
2. **Optimistic locking** via SQLAlchemy's ``version_id_col`` — an UPDATE that
   does not match the expected version raises ``StaleDataError`` instead of
   silently overwriting a concurrent change.
3. **A unique constraint** as the last-resort safety net. If two requests ever
   slip past the application-level checks, the database itself rejects the
   duplicate row. This is what makes the guarantee real rather than hopeful.

Additionally, ``SELECT ... FOR UPDATE`` (pessimistic locking) is available via
:func:`with_for_update` for the booking critical section.

MySQL 8.0 notes
---------------
* InnoDB is required — MyISAM has no transactions or row locks.
* ``REPEATABLE READ`` is MySQL's default and is what we use.
* ``pool_recycle`` must be shorter than MySQL's ``wait_timeout`` (8 hours by
  default) or the pool hands out connections the server already closed,
  producing ``MySQL server has gone away`` errors under load.
"""

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
# Without this, MySQL invents names like `idx_fk_1`, which makes Alembic
# autogenerate produce noisy diffs and can break on a second run. Explicit
# names keep migrations reproducible — the stated purpose of Alembic here.
NAMING_CONVENTION: dict[str, str] = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """Declarative base for every ORM model.

    All models across all five modules must inherit from this so that
    ``Base.metadata`` sees the complete schema — Alembic autogenerate and
    ``create_all`` both depend on it.
    """

    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class TimestampMixin:
    """Adds server-maintained created_at / updated_at to a model.

    ``server_default``/``onupdate`` mean the database sets these values, so
    they are correct even for rows inserted by a migration or a raw script —
    not just rows created through the ORM.
    """

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
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
        pool_pre_ping=True,  # discard dead connections instead of erroring
        echo=settings.db_echo_sql,
        # The session, not the connection, owns the transaction boundary.
        # This is what lets `session.commit()` be meaningful and what makes
        # a failed booking roll back completely.
        future=True,
    )

    @event.listens_for(engine, "connect")
    def _set_mysql_session_vars(dbapi_connection: Any, _record: Any) -> None:
        """Pin session variables that the concurrency guarantees rely on.

        ``FOR UPDATE`` combined with InnoDB gives row-level locking. We also
        make sure the connection is not in autocommit mode, which would
        silently defeat every transaction in the application.
        """
        try:
            with dbapi_connection.cursor() as cursor:
                cursor.execute(
                    "SET SESSION TRANSACTION ISOLATION LEVEL REPEATABLE READ"
                )
                cursor.execute("SET SESSION sql_mode='STRICT_TRANS_TABLES'")
            dbapi_connection.autocommit = False
        except Exception:  # non-MySQL backends (tests) lack these
            logger.debug(
                "Could not set MySQL session variables; continuing", exc_info=True
            )

    return engine


def get_engine(settings: Settings | None = None) -> Engine:
    """Return the process-wide engine, creating it on first use."""
    global _engine  # module-level singleton is intentional
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
            # Do NOT autoflush mid-transaction on reads: it turns a simple
            # SELECT into an unexpected write and complicates deadlock analysis.
            autoflush=False,
        )
    return _session_factory


def reset_engine() -> None:
    """Dispose the engine and clear the singletons.

    Call this in tests between cases, and on application shutdown. Disposing
    matters: an undisposed pool leaks MySQL connections until the server hits
    ``max_connections`` and starts refusing new ones.
    """
    global _engine, _session_factory
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _session_factory = None


# ---------------------------------------------------------------------------
# FastAPI dependency
# ---------------------------------------------------------------------------
def get_db() -> Generator[Session, None, None]:
    """Yield a request-scoped session, rolling back on any exception.

    This is the pattern every route should depend on:

        @router.get("/tables")
        def list_tables(db: Session = Depends(get_db)): ...

    The rollback-on-error is what prevents a half-applied booking from
    persisting. ``expire_on_commit=False`` means returned objects stay readable
    after commit, so a response model can be built without a second query.
    """
    session = get_session_factory()()
    try:
        yield session
    except SQLAlchemyError:
        # Roll back explicitly before re-raising so the connection returns to
        # the pool in a clean state rather than holding an aborted transaction.
        session.rollback()
        raise
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


@contextmanager
def session_scope() -> Iterator[Session]:
    """Transactional scope for code outside a request (scripts, jobs, tests).

    Usage:
        with session_scope() as session:
            session.add(table)
        # commits on clean exit, rolls back on exception

    The seat-hold expiry job uses this rather than `get_db`, which is tied to
    FastAPI's request lifecycle.
    """
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
    """Load one row with ``SELECT ... FOR UPDATE``.

    This takes an exclusive InnoDB row lock held until the transaction ends.
    Any other transaction attempting to lock or update the same row blocks
    until we commit or roll back — which is exactly how two simultaneous
    bookings for the same table and time slot are serialised.

    Args:
        session: active session, must be inside a transaction.
        model: the ORM class to query.
        *where: SQLAlchemy filter expressions.

    Returns:
        The locked row, or None if no row matched.

    Warning:
        Keep the locked region **short**. A long-held row lock under load
        causes lock-wait timeouts (MySQL default 50s) and deadlocks. Do no
        network calls or slow computation between locking and committing.
    """
    stmt = select(model).where(*where).with_for_update()
    return session.execute(stmt).scalar_one_or_none()


def count_for_update(session: Session, model: type[Any], *where: Any) -> int:
    """Count rows matching `where`, locking them for the current transaction.

    Used by the booking conflict check: we must count *and* lock in the same
    statement, otherwise another transaction can insert a conflicting row
    between our count and our insert.
    """
    stmt = select(func.count()).select_from(model).where(*where).with_for_update()
    result = session.execute(stmt).scalar_one()
    return int(result or 0)