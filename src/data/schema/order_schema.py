from datetime import datetime

from pydantic import BaseModel, ConfigDict


class DishSchema(BaseModel):
    id: int
    name: str
    category: str
    price: float
    image_url: str | None = None

    model_config = ConfigDict(from_attributes=True)


class OrderItemCreateSchema(BaseModel):
    dish_id: int
    quantity: int


class OrderItemSchema(BaseModel):
    id: int
    dish_id: int
    quantity: int
    price: float
    dish: DishSchema | None = None

    model_config = ConfigDict(from_attributes=True)


class OrderCreateSchema(BaseModel):
    customer_name: str
    items: list[OrderItemCreateSchema]


class OrderSchema(BaseModel):
    id: int
    customer_name: str
    total_price: float
    status: str
    created_at: datetime
    items: list[OrderItemSchema] = []

    model_config = ConfigDict(from_attributes=True)
