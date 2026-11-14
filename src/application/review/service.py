from sqlalchemy import func
from sqlalchemy.orm import Session

from src.application.review.exceptions import DishNotInOrderError
from src.application.review.schemas import ReviewCreate
from src.data.schema.review import DishRatingStats, Review, ReviewModeration

# Bayesian ranking m parameter (frozen contract)
M_PARAMETER = 15.0


class OrderServiceStub:
    """Temporary stub to verify order."""

    def verify_customer_ordered_dish(
        self, db: Session, customer_id: int, order_id: int, dish_id: int
    ) -> bool:
        return True


def update_dish_bayesian_stats(db: Session, dish_id: int) -> None:
    """Calculate and update Bayesian average score for a specific dish."""
    # 1. Get review count v and average rating R
    stats = (
        db.query(func.count(Review.id), func.avg(Review.rating))
        .filter(Review.dish_id == dish_id)
        .first()
    )
    review_count = stats[0] or 0
    avg_rating = float(stats[1] or 0.0)

    # 2. Get global mean C (default 3.0)
    global_avg = db.query(func.avg(Review.rating)).scalar()
    global_mean = float(global_avg or 3.0)

    # 3. Calculate Bayesian average: (v / (v + m)) * R + (m / (v + m)) * C
    if review_count + M_PARAMETER == 0:
        bayesian_score = 0.0
    else:
        bayesian_score = (review_count / (review_count + M_PARAMETER)) * avg_rating + (
            M_PARAMETER / (review_count + M_PARAMETER)
        ) * global_mean

    # 4. Update or insert into stats table
    rating_stat = db.query(DishRatingStats).filter(DishRatingStats.dish_id == dish_id).first()
    if rating_stat:
        rating_stat.review_count = review_count
        rating_stat.bayesian_score = round(bayesian_score, 4)
        rating_stat.global_mean = round(global_mean, 4)
    else:
        rating_stat = DishRatingStats(
            dish_id=dish_id,
            review_count=review_count,
            bayesian_score=round(bayesian_score, 4),
            global_mean=round(global_mean, 4),
        )
        db.add(rating_stat)

    db.commit()


def submit_review(
    db: Session,
    payload: ReviewCreate,
    order_service: OrderServiceStub | None = None,
) -> Review:
    if order_service is None:
        order_service = OrderServiceStub()

    is_valid = order_service.verify_customer_ordered_dish(
        db, payload.customer_id, payload.order_id, payload.dish_id
    )
    if not is_valid:
        raise DishNotInOrderError("Dish not in order.")

    new_review = Review(
        customer_id=payload.customer_id,
        dish_id=payload.dish_id,
        order_id=payload.order_id,
        rating=payload.rating,
        content=payload.content,
    )
    db.add(new_review)
    db.flush()

    moderation = ReviewModeration(review_id=new_review.id, status="pending")
    db.add(moderation)
    db.commit()
    db.refresh(new_review)

    # Update stats after submission
    update_dish_bayesian_stats(db, payload.dish_id)

    return new_review


# --- Moderation Services ---
def get_pending_moderations(db: Session, skip: int = 0, limit: int = 50) -> list[ReviewModeration]:
    return (
        db.query(ReviewModeration)
        .filter(ReviewModeration.status == "pending")
        .offset(skip)
        .limit(limit)
        .all()
    )


def update_moderation_status(
    db: Session, review_id: int, status: str, staff_id: int, reason: str | None = None
) -> ReviewModeration | None:
    moderation = db.query(ReviewModeration).filter(ReviewModeration.review_id == review_id).first()
    if moderation:
        moderation.status = status
        moderation.moderated_by = staff_id
        moderation.moderated_at = func.now()
        moderation.reason = reason
        db.commit()
        db.refresh(moderation)
    return moderation
