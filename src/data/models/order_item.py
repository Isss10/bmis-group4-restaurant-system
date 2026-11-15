# ruff: noqa: F821, UP037
from __future__ import annotations
from sqlalchemy import Integer
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.data.database import Base

class OrderItem(Base):
    __tablename__ = "order_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    dish: Mapped["Dish"] = relationship("Dish", back_populates="order_items")
    order: Mapped["Order"] = relationship("Order", back_populates="items")

from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from src.data.models.dish import Dish
    from src.data.models.order import Order
