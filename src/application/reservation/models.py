import enum
from datetime import UTC, datetime

from sqlalchemy import Column, DateTime, Enum, Integer, String

from src.data.database import Base


def _utc_now_naive() -> datetime:
    """Current UTC time as a naive datetime."""
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
    end_time = Column(DateTime, nullable=False)
    expires_at = Column(DateTime, nullable=True)
    status = Column(Enum(ReservationStatus), default=ReservationStatus.PENDING, nullable=False)
    created_at = Column(DateTime, default=_utc_now_naive)
