from pydantic import BaseModel


class DashboardStats(BaseModel):
    total_revenue: float
    total_orders: int
    hourly_heatmap: dict[str, int]
    no_show_rate: float


class RecommendationResponse(BaseModel):
    dish_id: int
    dish_name: str
    score: float
    reason: str
