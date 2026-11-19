from sqlalchemy import Column, Integer, String, DateTime, Enum, ForeignKey, UniqueConstraint
from sqlalchemy.orm import relationship
from datetime import datetime
from .base import Base

class RestaurantTable(Base):
    __tablename__ = "restaurant_tables"

    id = Column(Integer, primary_key=True, autoincrement=True)
    table_number = Column(String(20), unique=True, nullable=False)
    capacity = Column(Integer, nullable=False)
    status = Column(Enum("available", "reserved"), default="available")
    # 乐观锁版本字段
    version = Column(Integer, nullable=False, default=1)

    bookings = relationship("Booking", back_populates="table")


class Booking(Base):
    __tablename__ = "bookings"

    id = Column(Integer, primary_key=True, autoincrement=True)
    customer_id = Column(Integer, ForeignKey("customers.id"), nullable=False)
    table_id = Column(Integer, ForeignKey("restaurant_tables.id"), nullable=False)
    booking_datetime = Column(DateTime, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("table_id", "booking_datetime", name="uk_table_booking_time"),
    )

    customer = relationship("Customer")
    table = relationship("RestaurantTable", back_populates="bookings")
