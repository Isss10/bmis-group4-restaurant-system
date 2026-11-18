from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

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
            stmt = select(Dish).where(Dish.id == item.dish_id)
            result = await self.db.execute(stmt)
            dish = result.scalar_one_or_none()

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
        await self.db.commit()
        await self.db.refresh(new_order)

        return new_order

    async def get_order_by_id(self, order_id: int):
        stmt = select(Order).where(Order.id == order_id)
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def list_all_orders(self):
        stmt = select(Order)
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def get_menu(self, category: str | None):
        stmt = select(Dish)
        if category:
            stmt = stmt.where(Dish.category == category)
        result = await self.db.execute(stmt)
        return list(result.scalars().all())
