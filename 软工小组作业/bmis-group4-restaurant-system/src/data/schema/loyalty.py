"""Relational models for the loyalty module.

Points are represented as append-only events. Positive events create point lots;
negative events (redemption, expiry, negative adjustment) consume those lots
through :class:`PointsAllocation`. The user's balance is therefore derived, not
stored on a mutable profile row.

``user_id`` is deliberately a string here. The auth implementation is being
delivered in a separate PR and ``users`` does not exist on main yet. Keeping the
same string representation as the JWT ``sub`` claim lets the loyalty module be
tested and integrated without creating a competing user table. Once the auth
migration lands, a follow-up migration can add the foreign keys without
rewriting the domain API.
"""

from __future__ import annotations

import enum
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.data.database import Base, TimestampMixin


class PointsTxnType(enum.StrEnum):
    """Frozen points-ledger transaction vocabulary."""

    EARN = "EARN"
    REDEEM = "REDEEM"
    EXPIRE = "EXPIRE"
    ADJUST = "ADJUST"


class CouponDiscountType(enum.StrEnum):
    """How a coupon's value is interpreted."""

    PERCENT = "PERCENT"
    FIXED = "FIXED"


class CouponStacking(enum.StrEnum):
    """Whether a coupon may be combined with other coupons."""

    EXCLUSIVE = "EXCLUSIVE"
    STACKABLE = "STACKABLE"


class UserCouponStatus(enum.StrEnum):
    AVAILABLE = "AVAILABLE"
    USED = "USED"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"


class MembershipTier(Base, TimestampMixin):
    """A configurable tier based on cumulative qualifying spend.

    Thresholds live in data, rather than in an ``if/else`` tree, so managers can
    tune them without a code deployment. The migration seeds demo values; the
    group should freeze the final values in the requirements contract before
    submission.
    """

    __tablename__ = "membership_tiers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    min_qualifying_spend: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), nullable=False, default=Decimal("0.00")
    )
    discount_rate: Mapped[Decimal] = mapped_column(
        Numeric(5, 4), nullable=False, default=Decimal("0.0000")
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    __table_args__ = (
        CheckConstraint("min_qualifying_spend >= 0", name="tier_min_spend_non_negative"),
        CheckConstraint(
            "discount_rate >= 0 AND discount_rate <= 1",
            name="tier_discount_rate_fraction",
        ),
        Index("ix_membership_tiers_spend", "min_qualifying_spend"),
    )


class LoyaltyOrderEvent(Base):
    """One successful completed-order event, unique per external order id.

    The row is the idempotency anchor for points earning and also the source of
    cumulative qualifying spend. It intentionally stores only the minimum
    cross-module facts; the ordering module remains the owner of the order.
    """

    __tablename__ = "loyalty_order_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    order_id: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    user_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    paid_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    points_awarded: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        CheckConstraint("paid_amount >= 0", name="order_event_paid_non_negative"),
        CheckConstraint("points_awarded >= 0", name="order_event_points_non_negative"),
    )


class PointsLedger(Base, TimestampMixin):
    """Append-only points event.

    Positive rows are point lots. Negative rows consume existing lots through
    allocations. A negative row's ``points`` value is never edited after insert.
    """

    __tablename__ = "points_ledger"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    txn_type: Mapped[PointsTxnType] = mapped_column(Enum(PointsTxnType), nullable=False, index=True)
    points: Mapped[int] = mapped_column(Integer, nullable=False)
    source_type: Mapped[str] = mapped_column(String(32), nullable=False)
    source_id: Mapped[str] = mapped_column(String(128), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )

    __table_args__ = (
        CheckConstraint("points <> 0", name="points_non_zero"),
        UniqueConstraint(
            "user_id",
            "source_type",
            "source_id",
            "txn_type",
            name="uq_points_event_source",
        ),
        Index("ix_points_user_created", "user_id", "created_at"),
    )


class PointsAllocation(Base):
    """Links a negative points event to the positive lots it consumed."""

    __tablename__ = "points_allocations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    spend_ledger_id: Mapped[int] = mapped_column(
        ForeignKey("points_ledger.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    earn_ledger_id: Mapped[int] = mapped_column(
        ForeignKey("points_ledger.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    points: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        CheckConstraint("points > 0", name="allocation_points_positive"),
        UniqueConstraint(
            "spend_ledger_id",
            "earn_ledger_id",
            name="uq_points_allocation_pair",
        ),
    )


class Coupon(Base, TimestampMixin):
    """A coupon definition created by a manager or administrator."""

    __tablename__ = "coupons"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    discount_type: Mapped[CouponDiscountType] = mapped_column(
        Enum(CouponDiscountType), nullable=False
    )
    discount_value: Mapped[Decimal] = mapped_column(Numeric(12, 4), nullable=False)
    min_spend: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), nullable=False, default=Decimal("0.00")
    )
    stacking: Mapped[CouponStacking] = mapped_column(
        Enum(CouponStacking), nullable=False, default=CouponStacking.STACKABLE
    )
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    valid_until: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    __table_args__ = (
        CheckConstraint("discount_value > 0", name="coupon_value_positive"),
        CheckConstraint("min_spend >= 0", name="coupon_min_spend_non_negative"),
        Index("ix_coupons_validity", "valid_from", "valid_until"),
    )


class UserCoupon(Base, TimestampMixin):
    """A coupon owned by one customer."""

    __tablename__ = "user_coupons"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    coupon_id: Mapped[int] = mapped_column(
        ForeignKey("coupons.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    status: Mapped[UserCouponStatus] = mapped_column(
        Enum(UserCouponStatus), nullable=False, default=UserCouponStatus.AVAILABLE
    )
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    order_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    coupon: Mapped[Coupon] = relationship(Coupon, lazy="selectin")

    __table_args__ = (
        UniqueConstraint("user_id", "coupon_id", name="uq_user_coupon_ownership"),
        Index("ix_user_coupons_user_status", "user_id", "status"),
    )
