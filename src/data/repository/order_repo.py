from sqlalchemy.ext.asyncio import AsyncSession

from src.data.models.order import Order
from src.data.models.order_item import OrderItem


async def create_order(session: AsyncSession, order: Order):
    session.add(order)
    await session.flush()
    return order

async def create_order_item(session: AsyncSession, item: OrderItem):
    session.add(item)
