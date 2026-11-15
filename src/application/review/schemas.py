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


class DishRankingResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    dish_id: int
    review_count: int
    bayesian_score: float
    global_mean: float


class ModerationUpdateRequest(BaseModel):
    status: str = Field(pattern="^(approved|hidden)$")
    reason: str | None = None


class ModerationListResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    review_id: int
    status: str
    moderated_by: int | None
    created_at: datetime
