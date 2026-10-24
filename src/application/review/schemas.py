from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ReviewCreate(BaseModel):
    customer_id: int
    dish_id: int
    order_id: int
    rating: int = Field(ge=1, le=5, description="Rating from 1 to 5")
    content: str | None = Field(default=None, max_length=1000)


class ReviewResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    customer_id: int
    dish_id: int
    order_id: int
    rating: int
    content: str | None
    created_at: datetime
