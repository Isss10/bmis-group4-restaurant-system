"""MySQL integration tests for loyalty idempotency and coupon row locking."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from threading import Barrier
from typing import Any

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.application.membership.loyalty import CouponQuoteIn, LoyaltyService, OrderCompletedIn
from src.common.errors import ApiError
from src.data.database import get_session_factory
from src.data.schema.loyalty import (
    Coupon,
    CouponDiscountType,
    CouponStacking,
    PointsLedger,
    UserCoupon,
    UserCouponStatus,
)

pytestmark = pytest.mark.integration


def test_completed_order_event_is_concurrently_idempotent(db_session: Session) -> None:
    db_session.commit()
    factory = get_session_factory()
    barrier = Barrier(2)

    def deliver() -> bool:
        with factory() as session:
            barrier.wait(timeout=10)
            result = LoyaltyService(session).award_completed_order(
                OrderCompletedIn(user_id="customer-1", paid_amount=Decimal("100.00")),
                order_id="concurrent-order-1",
                actor_id="waiter-1",
                actor_role="waiter",
                request_id=None,
            )
            session.commit()
            return bool(result.duplicate)

    with ThreadPoolExecutor(max_workers=2) as pool:
        duplicates = list(pool.map(lambda _: deliver(), range(2)))

    assert sorted(duplicates) == [False, True]
    with factory() as session:
        event_points = session.scalar(select(func.count()).select_from(PointsLedger))
        assert event_points == 1


def test_same_user_coupon_can_only_be_redeemed_once_concurrently(
    db_session: Session,
) -> None:
    now = datetime.now(UTC).replace(tzinfo=None)
    coupon = Coupon(
        code="CONCURRENT",
        name="Concurrent coupon",
        discount_type=CouponDiscountType.FIXED,
        discount_value=Decimal("10.00"),
        min_spend=Decimal("0.00"),
        stacking=CouponStacking.STACKABLE,
        valid_from=now - timedelta(days=1),
        valid_until=now + timedelta(days=1),
        is_active=True,
    )
    db_session.add(coupon)
    db_session.flush()
    owned = UserCoupon(
        user_id="customer-1",
        coupon_id=coupon.id,
        status=UserCouponStatus.AVAILABLE,
        issued_at=now,
        expires_at=now + timedelta(days=1),
    )
    db_session.add(owned)
    db_session.commit()
    owner_id = int(owned.id)

    factory = get_session_factory()
    barrier = Barrier(2)

    def redeem(order_id: str) -> tuple[str, Any]:
        with factory() as session:
            barrier.wait(timeout=10)
            try:
                quote, duplicate = LoyaltyService(session).redeem_coupons(
                    "customer-1",
                    CouponQuoteIn(
                        order_subtotal=Decimal("100.00"),
                        user_coupon_ids=[owner_id],
                    ),
                    order_id=order_id,
                    request_id=None,
                )
                session.commit()
                return "ok", (quote.payable_total, duplicate)
            except ApiError as exc:
                session.rollback()
                return "conflict", exc

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(redeem, ["order-a", "order-b"]))

    assert [kind for kind, _ in outcomes].count("ok") == 1
    assert [kind for kind, _ in outcomes].count("conflict") == 1
    with factory() as session:
        stored = session.get(UserCoupon, owner_id)
        assert stored is not None
        assert stored.status == UserCouponStatus.USED
        assert stored.order_id in {"order-a", "order-b"}
