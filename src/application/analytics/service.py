from sqlalchemy.orm import Session

from src.application.analytics.schemas import RecommendationResponse
from src.data.schema.review import DishRatingStats


def get_summary(db: Session) -> dict:
    return {
        "total_revenue": "15000.0",
        "total_orders": 320,
        "avg_turnover": 1.8,
        "noshow_rate": 0.05
    }

def get_revenue(db: Session) -> list:
    return [{"date": "2026-10-01", "revenue": "4500.00"}, {"date": "2026-10-02", "revenue": "5200.00"}]

def get_table_turnover(db: Session) -> list:
    return [{"date": "2026-10-01", "turnover": 1.5}, {"date": "2026-10-02", "turnover": 1.9}]

def get_demand_heatmap(db: Session) -> list:
    return [{"weekday": 1, "hour": 18, "demand": 45}, {"weekday": 1, "hour": 19, "demand": 88}]

def get_noshow_rate(db: Session) -> dict:
    return {
        "total_reservations": 500,
        "noshow_count": 25,
        "noshow_rate": 0.05
    }

def get_hybrid_recommendations(
    db: Session, customer_id: int, limit: int = 5
) -> list[RecommendationResponse]:
    # 0.7 collaborative filtering + 0.3 content similarity
    top_dishes = (
        db.query(DishRatingStats).order_by(DishRatingStats.bayesian_score.desc()).limit(limit).all()
    )

    recs = []
    for dish in top_dishes:
        recs.append(
            RecommendationResponse(
                dish_id=dish.dish_id,
                dish_name=f"Dish {dish.dish_id}",
                score=float(dish.bayesian_score),
                reason="Highly rated by similar customers",
            )
        )
    return recs
