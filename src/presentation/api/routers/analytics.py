from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from src.application.analytics.schemas import DashboardStats, RecommendationResponse
from src.application.analytics.service import get_dashboard_stats, get_hybrid_recommendations
from src.data.database import get_db

router = APIRouter(prefix="/analytics", tags=["Analytics"])


@router.get("/dashboard", response_model=DashboardStats)
def get_manager_dashboard(db: Annotated[Session, Depends(get_db)]) -> DashboardStats:
    return get_dashboard_stats(db)


@router.get("/recommendations/{customer_id}", response_model=list[RecommendationResponse])
def recommend_for_customer(
    customer_id: int, db: Annotated[Session, Depends(get_db)]
) -> list[RecommendationResponse]:
    return get_hybrid_recommendations(db, customer_id)
