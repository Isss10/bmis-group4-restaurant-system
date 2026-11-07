"""Unit tests for the loyalty points, tier and coupon rules.

These tests use SQLite so they run in the fast unit job. MySQL-specific row
locking and concurrent redemption behaviour are covered separately under
``tests/integration`` because SQLite cannot prove them.
"""

from __future__ import annotations

from collections.abc import Generator
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from src.application.membership.loyalty import (
    CouponCreateIn,
    CouponIssueIn,
    CouponQuoteIn,
    LoyaltyService,
    OrderCompletedIn,
    PointsAdjustIn,
    PointsRedeemIn,
)
from src.common.audit import AuditLog
from src.common.errors import ApiError
from src.data.database import Base
from src.data.model_discovery import import_all_models
from src.data.schema.loyalty import (
    CouponDiscountType,
    CouponStacking,
    MembershipTier,
    PointsAllocation,
    PointsLedger,
    PointsTxnType,
    UserCoupon,
    UserCouponStatus,
)


@pytest.fixture
def session() -> Generator[Session, None, None]:
    import_all_models()
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, class_=Session, expire_on_commit=False)
    db = factory()
    db.add_all(
        [
            MembershipTier(
                name="BRONZE",
                min_qualifying_spend=Decimal("0.00"),
                discount_rate=Decimal("0.0000"),
                is_active=True,
            ),
            MembershipTier(
                name="SILVER",
                min_qualifying_spend=Decimal("500.00"),
                discount_rate=Decimal("0.0200"),
                is_active=True,
            ),
            MembershipTier(
                name="GOLD",
                min_qualifying_spend=Decimal("2000.00"),
                discount_rate=Decimal("0.0500"),
                is_active=True,
            ),
        ]
    )
    db.commit()
    try:
        yield db
    finally:
        db.close()
        engine.dispose()


def _award(service: LoyaltyService, *, order_id: str, user_id: str, amount: str):
    return service.award_completed_order(
        OrderCompletedIn(user_id=user_id, paid_amount=Decimal(amount)),
        order_id=order_id,
        actor_id="staff-1",
        actor_role="waiter",
        request_id="req-loyalty",
    )


def test_completed_order_awards_points_once(session: Session) -> None:
    service = LoyaltyService(session)

    first = _award(service, order_id="order-1", user_id="customer-1", amount="105.00")
    second = _award(service, order_id="order-1", user_id="customer-1", amount="105.00")

    assert first.points_awarded == 10
    assert first.duplicate is False
    assert second.duplicate is True
    assert second.points_balance == 10
    assert session.scalar(select(func.count()).select_from(PointsLedger)) == 1


def test_small_order_records_spend_without_creating_zero_point_ledger(session: Session) -> None:
    service = LoyaltyService(session)

    result = _award(service, order_id="order-small", user_id="customer-1", amount="9.99")

    assert result.points_awarded == 0
    assert result.points_balance == 0
    assert session.scalar(select(func.count()).select_from(PointsLedger)) == 0
    assert service.summary("customer-1")["qualifying_spend"] == Decimal("9.99")


def test_redeem_allocates_points_to_earn_lots(session: Session) -> None:
    service = LoyaltyService(session)
    _award(service, order_id="order-1000", user_id="customer-1", amount="1000.00")

    result = service.redeem_points(
        "customer-1",
        PointsRedeemIn(order_id="order-next", points=40),
        request_id="req-redeem",
    )

    assert result.points_balance == 60
    allocations = list(session.scalars(select(PointsAllocation)))
    assert len(allocations) == 1
    assert allocations[0].points == 40
    redemption = session.scalar(
        select(PointsLedger).where(PointsLedger.txn_type == PointsTxnType.REDEEM)
    )
    assert redemption is not None
    assert redemption.points == -40


def test_redeem_rejects_insufficient_balance(session: Session) -> None:
    service = LoyaltyService(session)
    _award(service, order_id="order-100", user_id="customer-1", amount="100.00")

    with pytest.raises(ApiError) as error:
        service.redeem_points(
            "customer-1",
            PointsRedeemIn(order_id="order-next", points=11),
            request_id=None,
        )
    assert "Only 10 points" in error.value.errors[0]["detail"]


def test_expiry_consumes_only_remaining_points_and_is_idempotent(session: Session) -> None:
    service = LoyaltyService(session)
    _award(service, order_id="order-expiry", user_id="customer-1", amount="1000.00")
    service.redeem_points(
        "customer-1",
        PointsRedeemIn(order_id="order-spend", points=40),
        request_id=None,
    )
    earned = session.scalar(select(PointsLedger).where(PointsLedger.txn_type == PointsTxnType.EARN))
    assert earned is not None
    earned.expires_at = datetime.now(UTC).replace(tzinfo=None) - timedelta(seconds=1)
    session.flush()

    first = service.expire_points(actor_id=None, actor_role="system", request_id=None)
    second = service.expire_points(actor_id=None, actor_role="system", request_id=None)

    assert first == {"expired_lots": 1, "expired_points": 60}
    assert second == {"expired_lots": 0, "expired_points": 0}
    assert service.summary("customer-1")["points_balance"] == 0


def test_tier_is_based_on_cumulative_spend_not_redeemable_balance(session: Session) -> None:
    service = LoyaltyService(session)
    _award(service, order_id="order-tier", user_id="customer-1", amount="500.00")
    service.redeem_points(
        "customer-1",
        PointsRedeemIn(order_id="order-redeem", points=50),
        request_id=None,
    )

    summary = service.summary("customer-1")

    assert summary["points_balance"] == 0
    assert summary["qualifying_spend"] == Decimal("500.00")
    assert summary["tier"].name == "SILVER"


def _create_coupon(
    service: LoyaltyService,
    *,
    code: str,
    kind: CouponDiscountType,
    value: str,
    stacking: CouponStacking,
) -> int:
    coupon = service.create_coupon(
        CouponCreateIn(
            code=code,
            name=code,
            discount_type=kind,
            discount_value=Decimal(value),
            min_spend=Decimal("0.00"),
            stacking=stacking,
            valid_from=datetime.now(UTC) - timedelta(days=1),
            valid_until=datetime.now(UTC) + timedelta(days=10),
        ),
        actor_id="manager-1",
        actor_role="manager",
        request_id=None,
    )
    return int(coupon.id)


def test_percentage_then_fixed_coupon_stacking(session: Session) -> None:
    service = LoyaltyService(session)
    percent_id = _create_coupon(
        service,
        code="TEN",
        kind=CouponDiscountType.PERCENT,
        value="10",
        stacking=CouponStacking.STACKABLE,
    )
    fixed_id = _create_coupon(
        service,
        code="MINUS20",
        kind=CouponDiscountType.FIXED,
        value="20",
        stacking=CouponStacking.STACKABLE,
    )
    percent = service.issue_coupon(
        CouponIssueIn(coupon_id=percent_id, user_id="customer-1"),
        actor_id="manager-1",
        actor_role="manager",
        request_id=None,
    )
    fixed = service.issue_coupon(
        CouponIssueIn(coupon_id=fixed_id, user_id="customer-1"),
        actor_id="manager-1",
        actor_role="manager",
        request_id=None,
    )

    quote, _, _ = service.quote_coupons(
        "customer-1",
        CouponQuoteIn(
            order_subtotal=Decimal("100.00"),
            user_coupon_ids=[fixed.id, percent.id],
        ),
    )

    assert quote.coupon_discount == Decimal("30.00")
    assert quote.payable_total == Decimal("70.00")
    assert [item.code for item in quote.applied_coupons] == ["TEN", "MINUS20"]


def test_exclusive_coupon_cannot_combine(session: Session) -> None:
    service = LoyaltyService(session)
    exclusive_id = _create_coupon(
        service,
        code="ONLY",
        kind=CouponDiscountType.FIXED,
        value="20",
        stacking=CouponStacking.EXCLUSIVE,
    )
    stackable_id = _create_coupon(
        service,
        code="EXTRA",
        kind=CouponDiscountType.PERCENT,
        value="5",
        stacking=CouponStacking.STACKABLE,
    )
    owned = [
        service.issue_coupon(
            CouponIssueIn(coupon_id=coupon_id, user_id="customer-1"),
            actor_id="manager-1",
            actor_role="manager",
            request_id=None,
        )
        for coupon_id in (exclusive_id, stackable_id)
    ]

    with pytest.raises(ApiError) as error:
        service.quote_coupons(
            "customer-1",
            CouponQuoteIn(
                order_subtotal=Decimal("100.00"),
                user_coupon_ids=[owned[0].id, owned[1].id],
            ),
        )
    assert "EXCLUSIVE" in error.value.errors[0]["detail"]


def test_coupon_redemption_is_idempotent_for_same_order(session: Session) -> None:
    service = LoyaltyService(session)
    coupon_id = _create_coupon(
        service,
        code="ONCE",
        kind=CouponDiscountType.FIXED,
        value="20",
        stacking=CouponStacking.STACKABLE,
    )
    owned = service.issue_coupon(
        CouponIssueIn(coupon_id=coupon_id, user_id="customer-1"),
        actor_id="manager-1",
        actor_role="manager",
        request_id=None,
    )
    request = CouponQuoteIn(
        order_subtotal=Decimal("100.00"),
        user_coupon_ids=[owned.id],
    )

    _, first_duplicate = service.redeem_coupons(
        "customer-1", request, order_id="order-1", request_id=None
    )
    _, second_duplicate = service.redeem_coupons(
        "customer-1", request, order_id="order-1", request_id=None
    )

    assert first_duplicate is False
    assert second_duplicate is True
    row = session.get(UserCoupon, owned.id)
    assert row is not None
    assert row.status == UserCouponStatus.USED


def test_points_and_coupon_mutations_are_audited(session: Session) -> None:
    service = LoyaltyService(session)
    _award(service, order_id="order-audit", user_id="customer-1", amount="100.00")
    service.adjust_points(
        PointsAdjustIn(
            user_id="customer-1",
            points=5,
            reason="Customer service compensation",
            idempotency_key="adjust-1",
        ),
        actor_id="manager-1",
        actor_role="manager",
        request_id="req-audit",
    )

    actions = list(session.scalars(select(AuditLog.action).order_by(AuditLog.id)))
    assert "points.earned" in actions
    assert "points.adjusted" in actions
