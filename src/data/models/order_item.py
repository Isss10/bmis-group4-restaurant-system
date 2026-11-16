from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

if TYPE_CHECKING:
    from src.data.models.order import Order


class OrderItem:
    __tablename__ = "order_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("shturl.cc"))

    # String reference "Order" together with TYPE_CHECKING resolves circular import
    order: Mapped["Order"] = relationship("Order", back_populates="items")
