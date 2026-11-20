from datetime import UTC, datetime
from typing import Any, cast

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from src.application.ordering.models import (
    ALLOWED_TRANSITIONS,
    OrderStatus,
    normalize_order_status,
)
from src.common.errors import illegal_transition
from src.data.models.dish import Dish
from src.data.models.order import Order
from src.data.models.order_item import OrderItem
from src.data.schema.order_schema import OrderCreateSchema


class OrderingService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def submit_order(self, payload: OrderCreateSchema):
        total_price = 0.0
        order_items = []

        for item in payload.items:
            dish = self.db.scalar(select(Dish).where(Dish.id == item.dish_id))
            if not dish:
                raise ValueError(f"Dish with id {item.dish_id} not found")

            item_total = float(dish.price) * item.quantity
            total_price += item_total

            order_items.append(OrderItem(dish_id=dish.id, quantity=item.quantity, price=dish.price))

        if not order_items:
            raise ValueError("Order must contain at least one item")

        new_order = Order(
            customer_name=payload.customer_name,
            total_price=total_price,
            status="pending",
            created_at=datetime.now(UTC).replace(tzinfo=None),
            items=order_items,
        )

        self.db.add(new_order)
        self.db.commit()
        self.db.refresh(new_order)

        return new_order

    async def get_order_by_id(self, order_id: int):
        return self.db.scalar(select(Order).where(Order.id == order_id))

    async def list_all_orders(self):
        return list(self.db.scalars(select(Order)).all())

    async def get_menu(self, category: str | None):
        query = select(Dish)
        if category:
            query = query.where(Dish.category == category)
        return list(self.db.scalars(query).all())

    # ---- Purely additive: staff back-office (FR-ORD-04) -------------------
    # Synchronous on purpose. StaffService hands in a synchronous Session via
    # session_scope(); the AsyncSession annotation on __init__ is a legacy
    # mismatch (get_db yields Session). No existing method is touched.
    def _staff_db(self) -> Session:
        return cast(Session, self.db)

    def list_orders(self) -> list[dict[str, Any]]:
        """All orders as plain dicts, id ascending — copies happen in-session."""
        db = self._staff_db()
        rows = db.scalars(select(Order).order_by(Order.id)).all()
        return [
            {
                "id": int(row.id),
                "customer_name": str(row.customer_name),
                "total_price": float(row.total_price),
                "status": normalize_order_status(str(row.status)).value,
                "created_at": row.created_at,
            }
            for row in rows
        ]

    def set_order_status(self, order_id: int, status: OrderStatus) -> dict[str, Any] | None:
        """Advance one order. None => not found; illegal jump => ApiError 20003.

        Existence is checked before the state machine so PATCH on an unknown id
        is always 404/40001. Writes use the uppercase OrderStatus value, which
        gradually normalises M5's lowercase 'pending' rows.
        """
        db = self._staff_db()
        row = db.scalar(select(Order).where(Order.id == order_id).with_for_update())
        if row is None:
            return None
        current = normalize_order_status(str(row.status))
        if status not in ALLOWED_TRANSITIONS[current]:
            raise illegal_transition(f"{current.value} -> {status.value}")
        row.status = status.value
        db.flush()  # commit is owned by StaffService's session_scope()
        return {
            "id": int(row.id),
            "customer_name": str(row.customer_name),
            "total_price": float(row.total_price),
            "status": status.value,
            "created_at": row.created_at,
        }
