"""Loyalty business logic: points, tiers and coupons.

The service owns transaction-sensitive rules but never commits. The router or
the calling module controls the transaction boundary, allowing an order update,
points earning and its audit row to commit atomically.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import ROUND_FLOOR, ROUND_HALF_UP, Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_serializer, model_validator
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from src.common.audit import (
    ACTION_COUPON_CREATED,
    ACTION_COUPON_ISSUED,
    ACTION_COUPON_REDEEMED,
    ACTION_POINTS_ADJUSTED,
    ACTION_POINTS_EARNED,
    ACTION_POINTS_EXPIRED,
    ACTION_POINTS_REDEEMED,
    ACTION_TIER_CONFIGURED,
    record_audit,
)
from src.common.errors import ApiError, ErrorCode, validation_failed
from src.data.repository.loyalty import LoyaltyRepository, PointLot
from src.data.schema.loyalty import (
    Coupon,
    CouponDiscountType,
    CouponStacking,
    LoyaltyOrderEvent,
    MembershipTier,
    PointsAllocation,
    PointsLedger,
    PointsTxnType,
    UserCoupon,
    UserCouponStatus,
)


def _utc_iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


class TierOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    min_qualifying_spend: Decimal
    discount_rate: Decimal
    is_active: bool


class TierConfigIn(BaseModel):
    name: str = Field(min_length=1, max_length=32)
    min_qualifying_spend: Decimal = Field(ge=0, decimal_places=2)
    discount_rate: Decimal = Field(ge=0, le=1, decimal_places=4)
    is_active: bool = True


class PointsLedgerOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    txn_type: PointsTxnType
    points: int
    source_type: str
    source_id: str
    reason: str | None
    expires_at: datetime | None
    created_at: datetime

    @field_serializer("expires_at", "created_at", when_used="json")
    def _utc_datetimes(self, value: datetime | None) -> str | None:
        return _utc_iso(value)


class CouponOut(BaseModel):
    id: int
    user_coupon_id: int
    code: str
    name: str
    discount_type: CouponDiscountType
    discount_value: Decimal
    min_spend: Decimal
    stacking: CouponStacking
    status: UserCouponStatus
    expires_at: datetime

    @field_serializer("expires_at", when_used="json")
    def _utc_expiry(self, value: datetime) -> str:
        serialised = _utc_iso(value)
        if serialised is None:  # pragma: no cover - the field is non-nullable
            raise ValueError("expires_at must not be null")
        return serialised


class MembershipSummaryOut(BaseModel):
    user_id: str
    points_balance: int
    qualifying_spend: Decimal
    tier: TierOut
    available_coupons: list[CouponOut]


class OrderCompletedIn(BaseModel):
    """Payload for the ordering -> loyalty integration boundary."""

    user_id: str = Field(min_length=1, max_length=64)
    paid_amount: Decimal = Field(ge=0, decimal_places=2)


class OrderCompletedOut(BaseModel):
    order_id: str
    user_id: str
    points_awarded: int
    duplicate: bool
    points_balance: int


class PointsRedeemIn(BaseModel):
    order_id: str = Field(min_length=1, max_length=128)
    points: int = Field(gt=0)


class PointsRedeemOut(BaseModel):
    order_id: str
    points_redeemed: int
    points_balance: int
    duplicate: bool


class PointsAdjustIn(BaseModel):
    user_id: str = Field(min_length=1, max_length=64)
    points: int
    reason: str = Field(min_length=1, max_length=500)
    idempotency_key: str = Field(min_length=1, max_length=128)
    expires_at: datetime | None = None

    @model_validator(mode="after")
    def _non_zero(self) -> PointsAdjustIn:
        if self.points == 0:
            raise ValueError("points must not be zero")
        return self


class PointsAdjustOut(BaseModel):
    ledger_id: int
    user_id: str
    points_changed: int
    points_balance: int
    duplicate: bool


class ExpiryRunOut(BaseModel):
    expired_lots: int
    expired_points: int


class CouponCreateIn(BaseModel):
    code: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    name: str = Field(min_length=1, max_length=120)
    discount_type: CouponDiscountType
    discount_value: Decimal = Field(gt=0)
    min_spend: Decimal = Field(default=Decimal("0.00"), ge=0, decimal_places=2)
    stacking: CouponStacking = CouponStacking.STACKABLE
    valid_from: datetime
    valid_until: datetime

    @model_validator(mode="after")
    def _valid_window(self) -> CouponCreateIn:
        if self.valid_until <= self.valid_from:
            raise ValueError("valid_until must be later than valid_from")
        if self.discount_type == CouponDiscountType.PERCENT and self.discount_value > 100:
            raise ValueError("a percentage coupon value must be between 0 and 100")
        return self


class CouponIssueIn(BaseModel):
    coupon_id: int = Field(gt=0)
    user_id: str = Field(min_length=1, max_length=64)
    expires_at: datetime | None = None


class CouponDefinitionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    code: str
    name: str
    discount_type: CouponDiscountType
    discount_value: Decimal
    min_spend: Decimal
    stacking: CouponStacking
    valid_from: datetime
    valid_until: datetime
    is_active: bool

    @field_serializer("valid_from", "valid_until", when_used="json")
    def _utc_validity(self, value: datetime) -> str:
        serialised = _utc_iso(value)
        if serialised is None:  # pragma: no cover - the field is non-nullable
            raise ValueError("coupon validity must not be null")
        return serialised


class CouponIssueOut(BaseModel):
    user_coupon_id: int
    user_id: str
    coupon_id: int
    status: UserCouponStatus
    expires_at: datetime

    @field_serializer("expires_at", when_used="json")
    def _utc_expiry(self, value: datetime) -> str:
        serialised = _utc_iso(value)
        if serialised is None:  # pragma: no cover - the field is non-nullable
            raise ValueError("expires_at must not be null")
        return serialised


class CouponQuoteIn(BaseModel):
    order_subtotal: Decimal = Field(ge=0, decimal_places=2)
    user_coupon_ids: list[int] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def _unique_coupon_ids(self) -> CouponQuoteIn:
        if len(set(self.user_coupon_ids)) != len(self.user_coupon_ids):
            raise ValueError("user_coupon_ids must not contain duplicates")
        return self


class AppliedCouponOut(BaseModel):
    user_coupon_id: int
    code: str
    discount: Decimal


class CouponQuoteOut(BaseModel):
    order_subtotal: Decimal
    tier_name: str
    tier_discount: Decimal
    coupon_discount: Decimal
    total_discount: Decimal
    payable_total: Decimal
    applied_coupons: list[AppliedCouponOut]


class CouponRedeemIn(CouponQuoteIn):
    order_id: str = Field(min_length=1, max_length=128)


class CouponRedeemOut(CouponQuoteOut):
    order_id: str
    duplicate: bool


MONEY = Decimal("0.01")


def utc_now() -> datetime:
    return datetime.now(UTC)


def _db_time(value: datetime) -> datetime:
    """Normalise timestamps for MySQL DATETIME and SQLite test storage.

    MySQL DATETIME has no timezone offset. The application treats every value as
    UTC and strips the marker only at the persistence boundary.
    """
    if value.tzinfo is None:
        return value
    return value.astimezone(UTC).replace(tzinfo=None)


def _quantise(value: Decimal) -> Decimal:
    return value.quantize(MONEY, rounding=ROUND_HALF_UP)


class LoyaltyService:
    """Domain service for points, tiers and coupons."""

    points_per_currency_unit = Decimal("10")
    points_expiry_days = 365
    default_tier_name = "BRONZE"

    def __init__(self, session: Session, repository: LoyaltyRepository | None = None) -> None:
        self.session = session
        self.repository = repository or LoyaltyRepository(session)

    def _current_tier(self, user_id: str) -> tuple[MembershipTier, Decimal]:
        spend = self.repository.cumulative_qualifying_spend(user_id)
        tiers = self.repository.list_tiers()
        if not tiers:
            # A fresh unit-test schema may not have the seeded migration rows.
            # Returning an explicit baseline keeps reads deterministic without
            # silently introducing a second source of configuration.
            return (
                MembershipTier(
                    name=self.default_tier_name,
                    min_qualifying_spend=Decimal("0.00"),
                    discount_rate=Decimal("0.0000"),
                    is_active=True,
                ),
                spend,
            )
        selected = tiers[0]
        for tier in tiers:
            if spend >= tier.min_qualifying_spend:
                selected = tier
            else:
                break
        return selected, spend

    def summary(self, user_id: str) -> dict[str, Any]:
        now = _db_time(utc_now())
        tier, spend = self._current_tier(user_id)
        coupons: list[dict[str, Any]] = []
        for owned in self.repository.list_user_coupons(user_id):
            coupon = owned.coupon
            if (
                owned.status == UserCouponStatus.AVAILABLE
                and coupon.is_active
                and owned.expires_at > now
                and coupon.valid_until > now
            ):
                coupons.append(self._coupon_view(owned))
        return {
            "user_id": user_id,
            "points_balance": self.repository.points_balance(user_id, now=now),
            "qualifying_spend": _quantise(spend),
            "tier": tier,
            "available_coupons": coupons,
        }

    def list_points(
        self,
        user_id: str,
        *,
        page: int,
        page_size: int,
    ) -> tuple[list[PointsLedger], int]:
        return self.repository.list_ledger(
            user_id,
            offset=(page - 1) * page_size,
            limit=page_size,
        )

    def award_completed_order(
        self,
        payload: OrderCompletedIn,
        *,
        order_id: str,
        actor_id: str,
        actor_role: str,
        request_id: str | None,
    ) -> OrderCompletedOut:
        """Idempotently award points when an order reaches COMPLETED.

        M5 may call this method directly inside its completion transaction. The
        HTTP endpoint is an integration fallback for a separate process.
        """
        existing = self.repository.get_order_event(order_id)
        if existing is not None:
            return self._order_result(existing, duplicate=True)

        now = utc_now()
        paid = _quantise(payload.paid_amount)
        earned = int((paid / self.points_per_currency_unit).to_integral_value(rounding=ROUND_FLOOR))
        event = LoyaltyOrderEvent(
            order_id=order_id,
            user_id=payload.user_id,
            paid_amount=paid,
            points_awarded=earned,
            occurred_at=_db_time(now),
            created_at=_db_time(now),
        )

        try:
            with self.session.begin_nested():
                self.repository.add(event)
                if earned:
                    self.repository.add(
                        PointsLedger(
                            user_id=payload.user_id,
                            txn_type=PointsTxnType.EARN,
                            points=earned,
                            source_type="order_completion",
                            source_id=order_id,
                            reason=f"Order {order_id} completed",
                            expires_at=_db_time(now + timedelta(days=self.points_expiry_days)),
                        )
                    )
                self.repository.flush()
        except IntegrityError:
            # A concurrent delivery lost the unique-order race. The savepoint is
            # rolled back; the original transaction can still read the winner.
            winner = self.repository.get_order_event(order_id)
            if winner is None:
                raise
            return self._order_result(winner, duplicate=True)

        if earned:
            record_audit(
                self.session,
                action=ACTION_POINTS_EARNED,
                entity_type="LoyaltyOrderEvent",
                entity_id=order_id,
                actor_id=actor_id,
                actor_role=actor_role,
                after={"user_id": payload.user_id, "points": earned, "order_id": order_id},
                request_id=request_id,
            )
        return self._order_result(event, duplicate=False)

    def _order_result(self, event: LoyaltyOrderEvent, *, duplicate: bool) -> OrderCompletedOut:
        now = _db_time(utc_now())
        return OrderCompletedOut(
            order_id=event.order_id,
            user_id=event.user_id,
            points_awarded=int(event.points_awarded),
            duplicate=duplicate,
            points_balance=self.repository.points_balance(event.user_id, now=now),
        )

    def redeem_points(
        self,
        user_id: str,
        payload: PointsRedeemIn,
        *,
        request_id: str | None,
    ) -> PointsRedeemOut:
        existing = self.repository.find_ledger_event(
            user_id=user_id,
            source_type="points_redemption",
            source_id=payload.order_id,
            txn_type=PointsTxnType.REDEEM,
        )
        now = _db_time(utc_now())
        if existing is not None:
            return PointsRedeemOut(
                order_id=payload.order_id,
                points_redeemed=abs(int(existing.points)),
                points_balance=self.repository.points_balance(user_id, now=now),
                duplicate=True,
            )

        lots = self.repository.point_lots(user_id, now=now, for_update=True)
        available = sum(lot.remaining for lot in lots)
        if available < payload.points:
            raise validation_failed(
                [{"field": "points", "detail": f"Only {available} points are available."}]
            )

        entry = self._consume_lots(
            user_id=user_id,
            lots=lots,
            amount=payload.points,
            txn_type=PointsTxnType.REDEEM,
            source_type="points_redemption",
            source_id=payload.order_id,
            reason=f"Redeemed for order {payload.order_id}",
        )
        record_audit(
            self.session,
            action=ACTION_POINTS_REDEEMED,
            entity_type="PointsLedger",
            entity_id=entry.id,
            actor_id=user_id,
            actor_role="customer",
            before={"points_balance": available},
            after={"points_balance": available - payload.points, "order_id": payload.order_id},
            request_id=request_id,
        )
        return PointsRedeemOut(
            order_id=payload.order_id,
            points_redeemed=payload.points,
            points_balance=available - payload.points,
            duplicate=False,
        )

    def adjust_points(
        self,
        payload: PointsAdjustIn,
        *,
        actor_id: str,
        actor_role: str,
        request_id: str | None,
    ) -> dict[str, Any]:
        existing = self.repository.find_ledger_event(
            user_id=payload.user_id,
            source_type="manual_adjustment",
            source_id=payload.idempotency_key,
            txn_type=PointsTxnType.ADJUST,
        )
        now = _db_time(utc_now())
        if existing is not None:
            return {
                "ledger_id": existing.id,
                "user_id": payload.user_id,
                "points_changed": int(existing.points),
                "points_balance": self.repository.points_balance(payload.user_id, now=now),
                "duplicate": True,
            }

        if payload.points > 0:
            expiry = payload.expires_at or (utc_now() + timedelta(days=self.points_expiry_days))
            entry = PointsLedger(
                user_id=payload.user_id,
                txn_type=PointsTxnType.ADJUST,
                points=payload.points,
                source_type="manual_adjustment",
                source_id=payload.idempotency_key,
                reason=payload.reason,
                expires_at=_db_time(expiry),
            )
            self.repository.add(entry)
            self.repository.flush()
        else:
            lots = self.repository.point_lots(payload.user_id, now=now, for_update=True)
            available = sum(lot.remaining for lot in lots)
            amount = abs(payload.points)
            if available < amount:
                raise validation_failed(
                    [{"field": "points", "detail": f"Only {available} points are available."}]
                )
            entry = self._consume_lots(
                user_id=payload.user_id,
                lots=lots,
                amount=amount,
                txn_type=PointsTxnType.ADJUST,
                source_type="manual_adjustment",
                source_id=payload.idempotency_key,
                reason=payload.reason,
            )

        balance = self.repository.points_balance(payload.user_id, now=now)
        record_audit(
            self.session,
            action=ACTION_POINTS_ADJUSTED,
            entity_type="PointsLedger",
            entity_id=entry.id,
            actor_id=actor_id,
            actor_role=actor_role,
            after={"user_id": payload.user_id, "points": payload.points, "reason": payload.reason},
            request_id=request_id,
        )
        return {
            "ledger_id": entry.id,
            "user_id": payload.user_id,
            "points_changed": payload.points,
            "points_balance": balance,
            "duplicate": False,
        }

    def expire_points(
        self,
        *,
        actor_id: str | None,
        actor_role: str | None,
        request_id: str | None,
    ) -> dict[str, int]:
        """Consume remaining balances of expired lots.

        The operation is safe for repeated cron runs: each expiry ledger row is
        keyed by the source lot and the unique source constraint prevents a
        second deduction.
        """
        now = _db_time(utc_now())
        # The repository is user-scoped; expiry is a system-wide job. Query each
        # user seen in the ledger rather than adding an unconstrained lock query
        # that could block unrelated writes for too long.
        user_ids = self.repository.list_member_ids_with_points()
        expired_events = 0
        expired_points = 0
        for user_id in user_ids:
            lots = self.repository.point_lots(
                str(user_id), now=now, include_expired=True, for_update=True
            )
            for lot in lots:
                expiry = lot.ledger.expires_at
                if expiry is None or expiry > now:
                    continue
                source_id = f"expire-lot:{lot.ledger.id}"
                if self.repository.find_ledger_event(
                    user_id=str(user_id),
                    source_type="expiry_job",
                    source_id=source_id,
                    txn_type=PointsTxnType.EXPIRE,
                ):
                    continue
                entry = PointsLedger(
                    user_id=str(user_id),
                    txn_type=PointsTxnType.EXPIRE,
                    points=-lot.remaining,
                    source_type="expiry_job",
                    source_id=source_id,
                    reason=f"Expired point lot {lot.ledger.id}",
                    expires_at=None,
                )
                self.repository.add(entry)
                self.repository.flush()
                self.repository.add(
                    PointsAllocation(
                        spend_ledger_id=entry.id,
                        earn_ledger_id=lot.ledger.id,
                        points=lot.remaining,
                        created_at=now,
                    )
                )
                self.repository.flush()
                record_audit(
                    self.session,
                    action=ACTION_POINTS_EXPIRED,
                    entity_type="PointsLedger",
                    entity_id=entry.id,
                    actor_id=actor_id,
                    actor_role=actor_role,
                    before={"user_id": str(user_id), "lot_points": lot.remaining},
                    after={"points_balance": self.repository.points_balance(str(user_id), now=now)},
                    request_id=request_id,
                )
                expired_events += 1
                expired_points += lot.remaining
        return {"expired_lots": expired_events, "expired_points": expired_points}

    def _consume_lots(
        self,
        *,
        user_id: str,
        lots: list[PointLot],
        amount: int,
        txn_type: PointsTxnType,
        source_type: str,
        source_id: str,
        reason: str,
    ) -> PointsLedger:
        entry = PointsLedger(
            user_id=user_id,
            txn_type=txn_type,
            points=-amount,
            source_type=source_type,
            source_id=source_id,
            reason=reason,
            expires_at=None,
        )
        self.repository.add(entry)
        self.repository.flush()

        remaining = amount
        now = _db_time(utc_now())
        for lot in lots:
            if remaining <= 0:
                break
            used = min(remaining, lot.remaining)
            self.repository.add(
                PointsAllocation(
                    spend_ledger_id=entry.id,
                    earn_ledger_id=lot.ledger.id,
                    points=used,
                    created_at=now,
                )
            )
            remaining -= used
        if remaining:
            raise RuntimeError("point-lot allocation did not satisfy the requested amount")
        self.repository.flush()
        return entry

    def quote_coupons(
        self,
        user_id: str,
        payload: CouponQuoteIn,
        *,
        lock: bool = False,
        order_id: str | None = None,
    ) -> tuple[CouponQuoteOut, list[UserCoupon], bool]:
        now = _db_time(utc_now())
        owned: list[UserCoupon] = []
        duplicate = False
        for user_coupon_id in payload.user_coupon_ids:
            item = self.repository.get_user_coupon(
                user_coupon_id,
                user_id=user_id,
                for_update=lock,
            )
            if item is None:
                raise ApiError(
                    ErrorCode.RESOURCE_NOT_FOUND,
                    message=f"Coupon ownership {user_coupon_id} was not found.",
                )
            replay = (
                item.status == UserCouponStatus.USED
                and order_id is not None
                and item.order_id == order_id
            )
            if item.status == UserCouponStatus.USED:
                if order_id is not None and item.order_id == order_id:
                    duplicate = True
                else:
                    raise validation_failed(
                        [{"field": "user_coupon_ids", "detail": "The coupon is already used."}]
                    )
            elif item.status != UserCouponStatus.AVAILABLE:
                raise validation_failed(
                    [{"field": "user_coupon_ids", "detail": "The coupon is not available."}]
                )
            coupon = item.coupon
            if replay:
                owned.append(item)
                continue
            if not coupon.is_active:
                raise validation_failed(
                    [{"field": "user_coupon_ids", "detail": "The coupon is inactive."}]
                )
            if item.expires_at <= now or coupon.valid_until <= now:
                raise validation_failed(
                    [{"field": "user_coupon_ids", "detail": "The coupon has expired."}]
                )
            if coupon.valid_from > now:
                raise validation_failed(
                    [{"field": "user_coupon_ids", "detail": "The coupon is not active yet."}]
                )
            owned.append(item)

        exclusive = [item for item in owned if item.coupon.stacking == CouponStacking.EXCLUSIVE]
        if exclusive and len(owned) > 1:
            raise validation_failed(
                [
                    {
                        "field": "user_coupon_ids",
                        "detail": "EXCLUSIVE coupons cannot be combined with other coupons.",
                    }
                ]
            )

        subtotal = _quantise(payload.order_subtotal)
        tier, _ = self._current_tier(user_id)
        tier_discount = _quantise(subtotal * Decimal(tier.discount_rate))
        running = max(Decimal("0.00"), subtotal - tier_discount)
        applied: list[AppliedCouponOut] = []

        ordered = sorted(
            owned,
            key=lambda item: (
                item.coupon.discount_type != CouponDiscountType.PERCENT,
                item.id,
            ),
        )
        for item in ordered:
            coupon = item.coupon
            if subtotal < coupon.min_spend:
                raise validation_failed(
                    [
                        {
                            "field": "user_coupon_ids",
                            "detail": (
                                f"Coupon {coupon.code} requires a minimum spend of "
                                f"{coupon.min_spend}."
                            ),
                        }
                    ]
                )
            if duplicate and order_id is not None and item.status == UserCouponStatus.USED:
                raw_discount = (
                    running * Decimal(coupon.discount_value) / Decimal("100")
                    if coupon.discount_type == CouponDiscountType.PERCENT
                    else Decimal(coupon.discount_value)
                )
            elif coupon.discount_type == CouponDiscountType.PERCENT:
                raw_discount = running * Decimal(coupon.discount_value) / Decimal("100")
            else:
                raw_discount = Decimal(coupon.discount_value)
            discount = min(running, _quantise(raw_discount))
            running = _quantise(running - discount)
            applied.append(
                AppliedCouponOut(
                    user_coupon_id=item.id,
                    code=coupon.code,
                    discount=discount,
                )
            )

        coupon_discount = _quantise(sum((item.discount for item in applied), Decimal("0")))
        total_discount = min(subtotal, _quantise(tier_discount + coupon_discount))
        return (
            CouponQuoteOut(
                order_subtotal=subtotal,
                tier_name=str(tier.name),
                tier_discount=_quantise(tier_discount),
                coupon_discount=coupon_discount,
                total_discount=total_discount,
                payable_total=_quantise(subtotal - total_discount),
                applied_coupons=applied,
            ),
            owned,
            duplicate,
        )

    def redeem_coupons(
        self,
        user_id: str,
        payload: CouponQuoteIn,
        *,
        order_id: str,
        request_id: str | None,
    ) -> tuple[CouponQuoteOut, bool]:
        quote, owned, duplicate = self.quote_coupons(
            user_id,
            payload,
            lock=True,
            order_id=order_id,
        )
        if not duplicate:
            now = _db_time(utc_now())
            for item in owned:
                item.status = UserCouponStatus.USED
                item.used_at = now
                item.order_id = order_id
                record_audit(
                    self.session,
                    action=ACTION_COUPON_REDEEMED,
                    entity_type="UserCoupon",
                    entity_id=item.id,
                    actor_id=user_id,
                    actor_role="customer",
                    before={"status": UserCouponStatus.AVAILABLE.value},
                    after={
                        "status": UserCouponStatus.USED.value,
                        "order_id": order_id,
                    },
                    request_id=request_id,
                )
            self.repository.flush()
        return quote, duplicate

    def create_tier(
        self,
        payload: TierConfigIn,
        *,
        actor_id: str,
        actor_role: str,
        request_id: str | None,
    ) -> MembershipTier:
        tier = self.repository.tier_by_name(payload.name)
        before = None
        if tier is None:
            tier = MembershipTier(
                name=payload.name,
                min_qualifying_spend=payload.min_qualifying_spend,
                discount_rate=payload.discount_rate,
                is_active=payload.is_active,
            )
            self.repository.add(tier)
            self.repository.flush()
        else:
            before = {
                "min_qualifying_spend": str(tier.min_qualifying_spend),
                "discount_rate": str(tier.discount_rate),
                "is_active": tier.is_active,
            }
            tier.min_qualifying_spend = payload.min_qualifying_spend
            tier.discount_rate = payload.discount_rate
            tier.is_active = payload.is_active
            self.repository.flush()
        record_audit(
            self.session,
            action=ACTION_TIER_CONFIGURED,
            entity_type="MembershipTier",
            entity_id=tier.id,
            actor_id=actor_id,
            actor_role=actor_role,
            before=before,
            after={
                "name": tier.name,
                "min_qualifying_spend": str(tier.min_qualifying_spend),
                "discount_rate": str(tier.discount_rate),
            },
            request_id=request_id,
        )
        return tier

    def create_coupon(
        self,
        payload: CouponCreateIn,
        *,
        actor_id: str,
        actor_role: str,
        request_id: str | None,
    ) -> Coupon:
        code = payload.code.strip().upper()
        if self.repository.get_coupon_by_code(code) is not None:
            raise validation_failed(
                [{"field": "code", "detail": "A coupon with this code already exists."}]
            )
        coupon = Coupon(
            code=code,
            name=payload.name,
            discount_type=payload.discount_type,
            discount_value=payload.discount_value,
            min_spend=payload.min_spend,
            stacking=payload.stacking,
            valid_from=_db_time(payload.valid_from),
            valid_until=_db_time(payload.valid_until),
            is_active=True,
        )
        self.repository.add(coupon)
        self.repository.flush()
        record_audit(
            self.session,
            action=ACTION_COUPON_CREATED,
            entity_type="Coupon",
            entity_id=coupon.id,
            actor_id=actor_id,
            actor_role=actor_role,
            after={"code": coupon.code, "name": coupon.name},
            request_id=request_id,
        )
        return coupon

    def issue_coupon(
        self,
        payload: CouponIssueIn,
        *,
        actor_id: str,
        actor_role: str,
        request_id: str | None,
    ) -> UserCoupon:
        existing = self.repository.find_user_coupon(payload.user_id, payload.coupon_id)
        if existing is not None:
            return existing
        coupon = self.repository.get_coupon(payload.coupon_id)
        if coupon is None:
            raise ApiError(ErrorCode.RESOURCE_NOT_FOUND, message="Coupon was not found.")
        expires_at = payload.expires_at or coupon.valid_until
        expires_at = min(_db_time(expires_at), _db_time(coupon.valid_until))
        owned = UserCoupon(
            user_id=payload.user_id,
            coupon_id=coupon.id,
            status=UserCouponStatus.AVAILABLE,
            issued_at=_db_time(utc_now()),
            expires_at=expires_at,
        )
        self.repository.add(owned)
        self.repository.flush()
        record_audit(
            self.session,
            action=ACTION_COUPON_ISSUED,
            entity_type="UserCoupon",
            entity_id=owned.id,
            actor_id=actor_id,
            actor_role=actor_role,
            after={"user_id": payload.user_id, "coupon_id": coupon.id},
            request_id=request_id,
        )
        return owned

    @staticmethod
    def _coupon_view(owned: UserCoupon) -> dict[str, Any]:
        coupon = owned.coupon
        return {
            "id": coupon.id,
            "user_coupon_id": owned.id,
            "code": coupon.code,
            "name": coupon.name,
            "discount_type": coupon.discount_type,
            "discount_value": coupon.discount_value,
            "min_spend": coupon.min_spend,
            "stacking": coupon.stacking,
            "status": owned.status,
            "expires_at": owned.expires_at,
        }
