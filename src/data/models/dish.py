# ruff: noqa: F821, UP037
from __future__ import annotations

from sqlalchemy import Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.data.database import Base


class Dish(Base):
    __tablename__ = "dishes"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    category: Mapped[str] = mapped_column(String(50), nullable=False)
    price: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    description: Mapped[str | None] = mapped_column(String(255), nullable=True)
    image_url: Mapped[str | None] = mapped_column(String(255), nullable=True)

    order_items: Mapped[list["OrderItem"]] = relationship(
        "src.data.models.order_item.OrderItem", back_populates="dish", cascade="all, delete-orphan"
    )
