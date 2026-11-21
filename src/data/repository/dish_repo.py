from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.data.models.dish import Dish


async def get_dishes_by_category(session: AsyncSession, category: str | None = None):
    stmt = select(Dish)
    if category:
        stmt = stmt.where(Dish.category == category)
    result = await session.execute(stmt)
    return result.scalars().all()


async def get_dish_by_id(session: AsyncSession, dish_id: int):
    stmt = select(Dish).where(Dish.id == dish_id)
    result = await session.execute(stmt)
    return result.scalar_one_or_none()
