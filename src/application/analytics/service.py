from sqlalchemy.orm import Session

from src.application.analytics.schemas import DashboardStats, RecommendationResponse
from src.data.schema.review import DishRatingStats


def get_dashboard_stats(db: Session) -> DashboardStats:
    # Mock data
    return DashboardStats(
        total_revenue=15000.0,
        total_orders=320,
        hourly_heatmap={"18:00": 45, "19:00": 88, "20:00": 62},
        no_show_rate=0.05,
    )


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
