from __future__ import annotations
from sqlalchemy import String, Numeric
from sqlalchemy.orm import Mapped, mapped_column, relationship
from src.data.database import Base

class Dish(Base):
    __tablename__ = "dish"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    price: Mapped[float] = mapped_column(Numeric(10,2), nullable=False)
    description: Mapped[str | None] = mapped_column(String(255), nullable=True)
    image_url: Mapped[str | None] = mapped_column(String(255), nullable=True)

    order_items: Mapped[list["OrderItem"]] = relationship(
        "OrderItem", back_populates="dish", cascade="all, delete-orphan"
    )
