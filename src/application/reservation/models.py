from datetime import datetime, UTC
from sqlalchemy import Column, Date, Time, Integer, UniqueConstraint
from src.data.database import Base


def _utc_now_naive() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


class Reservation(Base):
    __tablename__ = "reservations"

    id = Column(Integer, primary_key=True)
    version = Column(Integer, nullable=False, default=1)

    table_id = Column(Integer, nullable=False)
    slot_date = Column(Date, nullable=False)
    slot_start = Column(Time, nullable=False)

    __mapper__.version_id_col = version

    __table_args__ = (
        UniqueConstraint(
            "table_id",
            "slot_date",
            "slot_start",
            name="uq_reservations_table_slot"
        ),
    )
