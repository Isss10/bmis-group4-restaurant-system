from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.data.database import Base, TimestampMixin


class Review(Base, TimestampMixin):
    __tablename__ = "reviews"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    customer_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    dish_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    order_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    rating: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str | None] = mapped_column(Text, nullable=True)

    moderation = relationship("ReviewModeration", back_populates="review", uselist=False)


class ReviewModeration(Base, TimestampMixin):
    __tablename__ = "review_moderation"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    review_id: Mapped[int] = mapped_column(
    Integer, ForeignKey("reviews.id"), nullable=False, unique=True
)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    moderated_by: Mapped[int | None] = mapped_column(Integer, nullable=True)
    moderated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    reason: Mapped[str | None] = mapped_column(String(200), nullable=True)

    review = relationship("Review", back_populates="moderation")


class DishRatingStats(Base, TimestampMixin):
    __tablename__ = "dish_rating_stats"

    dish_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    review_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    bayesian_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    global_mean: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
