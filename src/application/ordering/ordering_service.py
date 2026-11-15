from sqlalchemy.ext.asyncio import AsyncSession
from src.data.repository.dish_repo import get_dishes_by_category, get_dish_by_id
from src.data.repository.order_repo import create_order, create_order_item
from src.data.models.order import Order
from src.data.models.order_item import OrderItem
from src.data.schema.order_schema import OrderCreateSchema


class OrderingService:
    @staticmethod
    async def browse_menu(session: AsyncSession, category: str | None = None):
        return await get_dishes_by_category(session, category)

    @staticmethod
    async def submit_order(session: AsyncSession, dto: OrderCreateSchema):
        total_price = 0.0
        order_items = []

        for item_dto in dto.items:
            dish_id = item_dto.dish_id
            quantity = item_dto.quantity
            dish = await get_dish_by_id(session, dish_id)
            if not dish:
                raise ValueError(f"Dish id={dish_id} does not exist")
            subtotal = dish.price * quantity
            total_price += subtotal
            order_items.append({
                "dish_id": dish.id,
                "quantity": quantity,
                "price": dish.price
            })

        # 创建主订单
        order = Order(
            customer_name=dto.customer_name,
            total_price=total_price,
            status="pending"
        )
        order = await create_order(session, order)

        for oi in order_items:
            order_item = OrderItem(
                order_id=order.id,
                dish_id=oi["dish_id"],
                quantity=oi["quantity"],
                price=oi["price"]
            )
            await create_order_item(session, order_item)

        await session.commit()
        await session.refresh(order)
        return order