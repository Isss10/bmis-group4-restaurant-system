from sqlalchemy import String, Float
from sqlalchemy.orm import Mapped, mapped_column, relationship
from src.data.database import Base

class Dish(Base):
    __tablename__ = "dishes"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    category: Mapped[str] = mapped_column(String(50), nullable=False)
    price: Mapped[float] = mapped_column(Float, nullable=False)
    image_url: Mapped[str | None] = mapped_column(String(255), nullable=True)

    order_items: Mapped[list["OrderItem"]] = relationship("OrderItem", back_populates="dish")