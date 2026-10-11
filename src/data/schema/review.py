# src/data/schema/review.py
from datetime import datetime

from sqlalchemy import Column, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship

from src.data.schema.base import Base


class Review(Base):
    __tablename__ = "reviews"

    id = Column(Integer, primary_key=True, autoincrement=True)
    customer_id = Column(Integer, ForeignKey("customers.id"), nullable=False, index=True)
    dish_id = Column(Integer, ForeignKey("dishes.id"), nullable=False, index=True)
    order_id = Column(Integer, ForeignKey("orders.id"), nullable=False, index=True)
    rating = Column(Integer, nullable=False)  # 1-5 星
    content = Column(Text, nullable=True)  # 评论文字,可为空
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    moderation = relationship("ReviewModeration", back_populates="review", uselist=False)


class ReviewModeration(Base):
    __tablename__ = "review_moderation"

    id = Column(Integer, primary_key=True, autoincrement=True)
    review_id = Column(Integer, ForeignKey("reviews.id"), unique=True, nullable=False)
    status = Column(String(20), nullable=False, default="pending")  # pending / approved / hidden
    moderated_by = Column(Integer, ForeignKey("staff.id"), nullable=True)
    moderated_at = Column(DateTime, nullable=True)
    reason = Column(String(200), nullable=True)

    review = relationship("Review", back_populates="moderation")


class DishRatingStats(Base):
    __tablename__ = "dish_rating_stats"

    dish_id = Column(Integer, ForeignKey("dishes.id"), primary_key=True)
    review_count = Column(Integer, nullable=False, default=0)
    bayesian_score = Column(Float, nullable=False, default=0.0)
    global_mean = Column(Float, nullable=False, default=0.0)  # 全局均值,每晚重算
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
