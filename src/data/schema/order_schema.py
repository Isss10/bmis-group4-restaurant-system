from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime

class DishSchema(BaseModel):
    id: int
    name: str
    category: str
    price: float
    image_url: Optional[str] = None

    class Config:
        orm_mode = True


class OrderItemCreateSchema(BaseModel):
    dish_id: int
    quantity: int


class OrderItemSchema(BaseModel):
    id: int
    dish_id: int
    quantity: int
    price: float
    dish: Optional[DishSchema] = None

    class Config:
        orm_mode = True


class OrderCreateSchema(BaseModel):
    customer_name: str
    items: List[OrderItemCreateSchema]


class OrderSchema(BaseModel):
    id: int
    customer_name: str
    total_price: float
    status: str
    created_at: datetime
    items: List[OrderItemSchema] = []

    class Config:
        orm_mode = True