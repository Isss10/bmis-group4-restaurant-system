"""Persistence operations for the loyalty module.

All SQL lives in this filesystem layer. Application services receive plain
values and ORM objects through methods here, so the domain layer remains
framework independent and can be unit tested without HTTP.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from src.data.schema.loyalty import (
    Coupon,
    LoyaltyOrderEvent,
    MembershipTier,
    PointsAllocation,
    PointsLedger,
    UserCoupon,
)


@dataclass(frozen=True)
class PointLot:
    """A positive ledger row and the part that has not yet been consumed."""

    ledger: PointsLedger
    remaining: int


class LoyaltyRepository:
    """Query and persist loyalty aggregates using the caller's transaction."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, value: object) -> None:
        self.session.add(value)

    def flush(self) -> None:
        self.session.flush()

    def get_order_event(
        self, order_id: str, *, for_update: bool = False
    ) -> LoyaltyOrderEvent | None:
        stmt = select(LoyaltyOrderEvent).where(LoyaltyOrderEvent.order_id == order_id)
        if for_update:
            stmt = stmt.with_for_update()
        return self.session.execute(stmt).scalar_one_or_none()

    def cumulative_qualifying_spend(self, user_id: str) -> Decimal:
        stmt = select(func.coalesce(func.sum(LoyaltyOrderEvent.paid_amount), 0)).where(
            LoyaltyOrderEvent.user_id == user_id
        )
        value = self.session.execute(stmt).scalar_one()
        return Decimal(value or 0)

    def list_tiers(self, *, active_only: bool = True) -> list[MembershipTier]:
        stmt = select(MembershipTier)
        if active_only:
            stmt = stmt.where(MembershipTier.is_active.is_(True))
        stmt = stmt.order_by(
            MembershipTier.min_qualifying_spend.asc(),
            MembershipTier.id.asc(),
        )
        return list(self.session.scalars(stmt))

    def tier_by_name(self, name: str) -> MembershipTier | None:
        return self.session.execute(
            select(MembershipTier).where(MembershipTier.name == name)
        ).scalar_one_or_none()

    def point_lots(
        self,
        user_id: str,
        *,
        now: datetime,
        include_expired: bool = False,
        for_update: bool = False,
    ) -> list[PointLot]:
        """Return positive lots with their remaining balances.

        Expired lots are excluded by default, satisfying the contract that an
        expired hold must not count even when the expiry job has not run yet.
        Locks are taken on positive ledger rows so concurrent redemptions on the
        same member serialise before their allocation calculations.
        """
        stmt = (
            select(PointsLedger)
            .where(
                PointsLedger.user_id == user_id,
                PointsLedger.points > 0,
            )
            .order_by(
                PointsLedger.expires_at.asc(),
                PointsLedger.created_at.asc(),
                PointsLedger.id.asc(),
            )
        )
        if not include_expired:
            stmt = stmt.where((PointsLedger.expires_at.is_(None)) | (PointsLedger.expires_at > now))
        if for_update:
            stmt = stmt.with_for_update()
        lots = list(self.session.scalars(stmt))
        if not lots:
            return []

        allocated_stmt = (
            select(
                PointsAllocation.earn_ledger_id,
                func.coalesce(func.sum(PointsAllocation.points), 0),
            )
            .where(PointsAllocation.earn_ledger_id.in_([lot.id for lot in lots]))
            .group_by(PointsAllocation.earn_ledger_id)
        )
        allocated = {
            int(earn_id): int(points)
            for earn_id, points in self.session.execute(allocated_stmt).all()
        }

        result: list[PointLot] = []
        for lot in lots:
            remaining = int(lot.points) - allocated.get(int(lot.id), 0)
            if remaining > 0:
                result.append(PointLot(ledger=lot, remaining=remaining))
        return result

    def points_balance(self, user_id: str, *, now: datetime) -> int:
        return sum(lot.remaining for lot in self.point_lots(user_id, now=now))

    def list_ledger(
        self,
        user_id: str,
        *,
        offset: int,
        limit: int,
    ) -> tuple[list[PointsLedger], int]:
        count_stmt = (
            select(func.count()).select_from(PointsLedger).where(PointsLedger.user_id == user_id)
        )
        total = int(self.session.execute(count_stmt).scalar_one())
        stmt = (
            select(PointsLedger)
            .where(PointsLedger.user_id == user_id)
            .order_by(PointsLedger.created_at.desc(), PointsLedger.id.desc())
            .offset(offset)
            .limit(limit)
        )
        return list(self.session.scalars(stmt)), total

    def list_member_ids_with_points(self) -> list[str]:
        stmt = select(PointsLedger.user_id).distinct().order_by(PointsLedger.user_id)
        return [str(user_id) for user_id in self.session.scalars(stmt)]

    def find_ledger_event(
        self,
        *,
        user_id: str,
        source_type: str,
        source_id: str,
        txn_type: object,
    ) -> PointsLedger | None:
        stmt = select(PointsLedger).where(
            PointsLedger.user_id == user_id,
            PointsLedger.source_type == source_type,
            PointsLedger.source_id == source_id,
            PointsLedger.txn_type == txn_type,
        )
        return self.session.execute(stmt).scalar_one_or_none()

    def get_coupon(self, coupon_id: int, *, for_update: bool = False) -> Coupon | None:
        stmt = select(Coupon).where(Coupon.id == coupon_id)
        if for_update:
            stmt = stmt.with_for_update()
        return self.session.execute(stmt).scalar_one_or_none()

    def get_coupon_by_code(self, code: str) -> Coupon | None:
        return self.session.execute(select(Coupon).where(Coupon.code == code)).scalar_one_or_none()

    def get_user_coupon(
        self,
        user_coupon_id: int,
        *,
        user_id: str,
        for_update: bool = False,
    ) -> UserCoupon | None:
        stmt = select(UserCoupon).where(
            UserCoupon.id == user_coupon_id,
            UserCoupon.user_id == user_id,
        )
        if for_update:
            stmt = stmt.with_for_update()
        return self.session.execute(stmt).scalar_one_or_none()

    def list_user_coupons(self, user_id: str) -> list[UserCoupon]:
        stmt = (
            select(UserCoupon)
            .options(selectinload(UserCoupon.coupon))
            .where(UserCoupon.user_id == user_id)
            .order_by(UserCoupon.issued_at.desc(), UserCoupon.id.desc())
        )
        return list(self.session.scalars(stmt))

    def find_user_coupon(self, user_id: str, coupon_id: int) -> UserCoupon | None:
        return self.session.execute(
            select(UserCoupon)
            .options(selectinload(UserCoupon.coupon))
            .where(
                UserCoupon.user_id == user_id,
                UserCoupon.coupon_id == coupon_id,
            )
        ).scalar_one_or_none()
