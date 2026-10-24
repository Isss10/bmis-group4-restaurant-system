from sqlalchemy.orm import Session

from src.application.review.schemas import ReviewCreate
from src.application.review.service import submit_review
from src.data.schema.review import ReviewModeration


def test_submit_review_creates_pending_moderation(db_session: Session) -> None:
    payload = ReviewCreate(
        customer_id=1,
        dish_id=101,
        order_id=5001,
        rating=5,
        content="Very delicious!",
    )

    review = submit_review(db_session, payload)

    assert review.id is not None
    assert review.rating == 5
    assert review.content == "Very delicious!"

    moderation = db_session.query(ReviewModeration).filter_by(review_id=review.id).first()
    assert moderation is not None
    assert moderation.status == "pending"
