from __future__ import annotations
from sqlalchemy import ForeignKey, Integer
from sqlalchemy.orm import Mapped, mapped_column, relationship
from src.data.database import Base

class OrderItem(Base):
    __tablename__ = "order_item"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), nullable=False)
    dish_id: Mapped[int] = mapped_column(ForeignKey("dish.id"), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    dish: Mapped["Dish"] = relationship("Dish", back_populates="order_items")
    order: Mapped["Order"] = relationship("Order", back_populates="items")
