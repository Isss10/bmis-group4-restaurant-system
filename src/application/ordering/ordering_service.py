from sqlalchemy.ext.asyncio import AsyncSession
from src.data.schema.order_schema import OrderCreateSchema

class OrderingService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def submit_order(self, payload: OrderCreateSchema):
        return {
            "id": 1,
            "customer_name": payload.customer_name,
            "total_price": 99.0,
            "status": "pending",
            "created_at": "2026-11-16T10:00:00",
            "items": []
        }

    async def get_order_by_id(self, order_id: int):
        return None

    async def list_all_orders(self):
        return []

    async def get_menu(self, category: str | None):
        all_dishes = [
            {"id":1, "name":"Coke", "category":"drink", "price":5.0, "image_url":None},
            {"id":2, "name":"Rice", "category":"food", "price":12.0, "image_url":None}
        ]
        if category:
            return [d for d in all_dishes if d["category"] == category]
        return all_dishes
