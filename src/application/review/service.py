from sqlalchemy.orm import Session

from src.application.review.exceptions import DishNotInOrderError
from src.application.review.schemas import ReviewCreate
from src.data.schema.review import Review, ReviewModeration


class OrderServiceStub:
    """Temporary stub to verify order."""

    def verify_customer_ordered_dish(
        self, db: Session, customer_id: int, order_id: int, dish_id: int
    ) -> bool:
        return True


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
    return new_review
