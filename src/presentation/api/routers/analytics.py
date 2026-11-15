from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from src.application.analytics.schemas import RecommendationResponse
from src.application.analytics.service import get_hybrid_recommendations
from src.data.database import get_db
from src.application.analytics.service import get_summary, get_revenue, get_table_turnover, get_demand_heatmap, get_noshow_rate

router = APIRouter(prefix="/analytics", tags=["Analytics"])




@router.get("/recommendations/{customer_id}", response_model=list[RecommendationResponse])
def recommend_for_customer(
    customer_id: int, db: Annotated[Session, Depends(get_db)]
) -> list[RecommendationResponse]:
    return get_hybrid_recommendations(db, customer_id)

@router.get("/summary")
def api_get_summary(db: Annotated[Session, Depends(get_db)]):
    return get_summary(db)

@router.get("/revenue")
def api_get_revenue(db: Annotated[Session, Depends(get_db)]):
    return get_revenue(db)

@router.get("/table-turnover")
def api_get_table_turnover(db: Annotated[Session, Depends(get_db)]):
    return get_table_turnover(db)

@router.get("/demand-heatmap")
def api_get_demand_heatmap(db: Annotated[Session, Depends(get_db)]):
    return get_demand_heatmap(db)

@router.get("/no-show-rate")
def api_get_noshow_rate(db: Annotated[Session, Depends(get_db)]):
    return get_noshow_rate(db)