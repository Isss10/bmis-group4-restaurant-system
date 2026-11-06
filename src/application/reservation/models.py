import enum
from datetime import UTC, datetime

from sqlalchemy import Column, DateTime, Enum, Integer, String

from src.data.database import Base


def _utc_now_naive() -> datetime:
    """Current UTC time as a naive datetime.

    ``datetime.utcnow()`` is deprecated since Python 3.12 and emits a
    DeprecationWarning. This project declares ``requires-python = ">=3.11,<3.13"``,
    so 3.12 is a *supported* interpreter, and ``pyproject.toml`` sets
    ``filterwarnings = ["error"]`` — which promotes that warning to an exception.
    The result was that **every insert into ``reservations`` failed** on 3.12,
    while CI (pinned to 3.11) stayed green.

    The column is ``DateTime`` (naive, no ``timezone=True``), so the value must
    stay naive: feeding an aware datetime into a naive column makes SQLAlchemy
    warn about losing the offset, which the same filter would again turn into an
    error. Stripping ``tzinfo`` after reading the clock yields exactly what
    ``datetime.utcnow()`` used to yield — same instant, same naive
    representation — so the schema, the stored bytes and migration 0003 are all
    unchanged.

    Making this column ``DateTime(timezone=True)`` like ``audit_logs`` would be
    the better long-term design, but that is a schema change requiring its own
    migration and the module owner's sign-off, not a drive-by edit.
    """
    return datetime.now(UTC).replace(tzinfo=None)


class ReservationStatus(enum.StrEnum):
    PENDING = "PENDING"
    CONFIRMED = "CONFIRMED"
    CANCELLED = "CANCELLED"


class Reservation(Base):
    __tablename__ = "reservations"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    user_id = Column(String(50), nullable=False)
    table_id = Column(Integer, nullable=False)
    reservation_time = Column(DateTime, nullable=False)
    status: Column[ReservationStatus] = Column(
        Enum(ReservationStatus), default=ReservationStatus.PENDING, nullable=False
    )
    created_at = Column(DateTime, default=_utc_now_naive)
