from sqlalchemy.orm import Session

from src.application.review.schemas import ReviewCreate
from src.application.review.service import submit_review
from src.data.schema.review import DishRatingStats, ReviewModeration


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

    moderation = db_session.query(ReviewModeration).filter_by(review_id=review.id).first()
    assert moderation is not None
    assert moderation.status == "pending"

    # 验证贝叶斯统计表是否更新 (验证模块三功能)
    stats = db_session.query(DishRatingStats).filter_by(dish_id=101).first()
    assert stats is not None
    assert stats.review_count == 1
    assert stats.bayesian_score > 0


def test_moderation_update(db_session: Session) -> None:
    from src.application.review.service import get_pending_moderations, update_moderation_status

    payload = ReviewCreate(customer_id=2, dish_id=102, order_id=5002, rating=4)
    review = submit_review(db_session, payload)

    pending = get_pending_moderations(db_session)
    assert len(pending) > 0

    updated = update_moderation_status(db_session, review.id, "approved", staff_id=99)
    assert updated is not None
    assert updated.status == "approved"
    assert updated.moderated_by == 99
