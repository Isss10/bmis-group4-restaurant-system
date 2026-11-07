"""HTTP surface for points, membership tiers and coupon functionality.

This router is mounted by ``main.py`` at ``/api/v1/membership``. Endpoint paths
are grouped here so ordering and frontend clients have one integration boundary.
Authentication and role management remain the membership-auth module's concern.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy.orm import Session

from src.application.membership.loyalty import (
    CouponCreateIn,
    CouponDefinitionOut,
    CouponIssueIn,
    CouponIssueOut,
    CouponOut,
    CouponQuoteIn,
    CouponQuoteOut,
    CouponRedeemIn,
    CouponRedeemOut,
    ExpiryRunOut,
    LoyaltyService,
    MembershipSummaryOut,
    OrderCompletedIn,
    OrderCompletedOut,
    PointsAdjustIn,
    PointsAdjustOut,
    PointsLedgerOut,
    PointsRedeemIn,
    PointsRedeemOut,
    TierConfigIn,
    TierOut,
)
from src.common.envelope import Envelope, Page, paginate, success
from src.common.middleware import REQUEST_ID_ATTR
from src.common.security import CurrentUser, Role, TokenPayload, require_roles, require_staff
from src.data.database import get_db

router = APIRouter(tags=["membership"])


def _loyalty_openapi(api_id: str) -> dict[str, str]:
    """Attach a stable module contract marker to each loyalty operation."""
    return {
        "x-module": "loyalty",
        "x-contract-id": api_id,
        "x-implementation-status": "implemented",
    }


CustomerIdentity = Annotated[TokenPayload, Depends(require_roles(Role.CUSTOMER))]
ManagerIdentity = Annotated[TokenPayload, Depends(require_roles(Role.MANAGER, Role.ADMIN))]
StaffIdentity = Annotated[TokenPayload, Depends(require_staff())]
DbSession = Annotated[Session, Depends(get_db)]


def _request_id(request: Request) -> str | None:
    return getattr(request.state, REQUEST_ID_ATTR, None)


def _service(db: Session) -> LoyaltyService:
    return LoyaltyService(db)


@router.get(
    "/me",
    response_model=Envelope[MembershipSummaryOut],
    summary="Get current member points, tier and available coupons",
    openapi_extra=_loyalty_openapi("LOY-01"),
)
def get_membership_summary(
    request: Request,
    identity: CustomerIdentity,
    db: DbSession,
) -> dict:
    return success(
        _service(db).summary(identity.sub),
        request_id=_request_id(request),
    )


@router.get(
    "/points",
    response_model=Envelope[Page[PointsLedgerOut]],
    summary="List the current customer's append-only points ledger",
    openapi_extra=_loyalty_openapi("LOY-02"),
)
def list_points(
    request: Request,
    identity: CustomerIdentity,
    db: DbSession,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> dict:
    items, total = _service(db).list_points(
        identity.sub,
        page=page,
        page_size=page_size,
    )
    data = paginate(
        [PointsLedgerOut.model_validate(item) for item in items],
        total=total,
        page=page,
        page_size=page_size,
    )
    return success(data, request_id=_request_id(request))


@router.post(
    "/points/redeem",
    response_model=Envelope[PointsRedeemOut],
    summary="Redeem points for an order",
    openapi_extra=_loyalty_openapi("LOY-03"),
)
def redeem_points(
    payload: PointsRedeemIn,
    request: Request,
    identity: CustomerIdentity,
    db: DbSession,
) -> dict:
    result = _service(db).redeem_points(
        identity.sub,
        payload,
        request_id=_request_id(request),
    )
    db.commit()
    return success(result, request_id=_request_id(request))


@router.post(
    "/admin/points/adjust",
    response_model=Envelope[PointsAdjustOut],
    summary="Adjust a member's points (manager/admin)",
    openapi_extra=_loyalty_openapi("LOY-11"),
)
def adjust_points(
    payload: PointsAdjustIn,
    request: Request,
    identity: ManagerIdentity,
    db: DbSession,
) -> dict:
    result = _service(db).adjust_points(
        payload,
        actor_id=identity.sub,
        actor_role=str(identity.role),
        request_id=_request_id(request),
    )
    db.commit()
    return success(result, request_id=_request_id(request))


@router.post(
    "/admin/points/expire",
    response_model=Envelope[ExpiryRunOut],
    summary="Run point-expiry processing (manager/admin or scheduled caller)",
    openapi_extra=_loyalty_openapi("LOY-12"),
)
def expire_points(
    request: Request,
    identity: ManagerIdentity,
    db: DbSession,
) -> dict:
    result = _service(db).expire_points(
        actor_id=identity.sub,
        actor_role=str(identity.role),
        request_id=_request_id(request),
    )
    db.commit()
    return success(result, request_id=_request_id(request))


@router.get(
    "/tiers",
    response_model=Envelope[list[TierOut]],
    summary="List membership tiers",
    openapi_extra=_loyalty_openapi("LOY-04"),
)
def list_tiers(
    request: Request,
    identity: CurrentUser,
    db: DbSession,
) -> dict:
    del identity
    tiers = [TierOut.model_validate(item) for item in _service(db).repository.list_tiers()]
    return success(tiers, request_id=_request_id(request))


@router.post(
    "/tiers",
    response_model=Envelope[TierOut],
    status_code=status.HTTP_201_CREATED,
    summary="Create or update a membership tier (manager/admin)",
    openapi_extra=_loyalty_openapi("LOY-05"),
)
def configure_tier(
    payload: TierConfigIn,
    request: Request,
    identity: ManagerIdentity,
    db: DbSession,
) -> dict:
    tier = _service(db).create_tier(
        payload,
        actor_id=identity.sub,
        actor_role=str(identity.role),
        request_id=_request_id(request),
    )
    result = TierOut.model_validate(tier)
    db.commit()
    return success(result, request_id=_request_id(request))


@router.get(
    "/coupons",
    response_model=Envelope[list[CouponOut]],
    summary="List the current customer's available coupons",
    openapi_extra=_loyalty_openapi("LOY-06"),
)
def list_coupons(
    request: Request,
    identity: CustomerIdentity,
    db: DbSession,
) -> dict:
    summary = _service(db).summary(identity.sub)
    return success(summary["available_coupons"], request_id=_request_id(request))


@router.post(
    "/coupons",
    response_model=Envelope[CouponDefinitionOut],
    status_code=status.HTTP_201_CREATED,
    summary="Create a coupon definition (manager/admin)",
    openapi_extra=_loyalty_openapi("LOY-07"),
)
def create_coupon(
    payload: CouponCreateIn,
    request: Request,
    identity: ManagerIdentity,
    db: DbSession,
) -> dict:
    coupon = _service(db).create_coupon(
        payload,
        actor_id=identity.sub,
        actor_role=str(identity.role),
        request_id=_request_id(request),
    )
    result = CouponDefinitionOut.model_validate(coupon)
    db.commit()
    return success(result, request_id=_request_id(request))


@router.post(
    "/coupons/issue",
    response_model=Envelope[CouponIssueOut],
    status_code=status.HTTP_201_CREATED,
    summary="Issue a coupon to a customer (manager/admin)",
    openapi_extra=_loyalty_openapi("LOY-08"),
)
def issue_coupon(
    payload: CouponIssueIn,
    request: Request,
    identity: ManagerIdentity,
    db: DbSession,
) -> dict:
    owned = _service(db).issue_coupon(
        payload,
        actor_id=identity.sub,
        actor_role=str(identity.role),
        request_id=_request_id(request),
    )
    result = CouponIssueOut(
        user_coupon_id=owned.id,
        user_id=owned.user_id,
        coupon_id=owned.coupon_id,
        status=owned.status,
        expires_at=owned.expires_at,
    )
    db.commit()
    return success(result, request_id=_request_id(request))


@router.post(
    "/coupons/quote",
    response_model=Envelope[CouponQuoteOut],
    summary="Quote tier and coupon discounts without consuming a coupon",
    openapi_extra=_loyalty_openapi("LOY-09"),
)
def quote_coupons(
    payload: CouponQuoteIn,
    request: Request,
    identity: CustomerIdentity,
    db: DbSession,
) -> dict:
    quote, _, _ = _service(db).quote_coupons(identity.sub, payload)
    return success(quote, request_id=_request_id(request))


@router.post(
    "/coupons/redeem",
    response_model=Envelope[CouponRedeemOut],
    summary="Atomically consume coupons for an order",
    openapi_extra=_loyalty_openapi("LOY-10"),
)
def redeem_coupons(
    payload: CouponRedeemIn,
    request: Request,
    identity: CustomerIdentity,
    db: DbSession,
) -> dict:
    quote, duplicate = _service(db).redeem_coupons(
        identity.sub,
        payload,
        order_id=payload.order_id,
        request_id=_request_id(request),
    )
    db.commit()
    result = CouponRedeemOut(
        **quote.model_dump(),
        order_id=payload.order_id,
        duplicate=duplicate,
    )
    return success(result, request_id=_request_id(request))


@router.post(
    "/events/orders/{order_id}/completed",
    response_model=Envelope[OrderCompletedOut],
    summary="Integration event: award points for a completed order",
    openapi_extra=_loyalty_openapi("LOY-13"),
)
def order_completed(
    order_id: str,
    payload: OrderCompletedIn,
    request: Request,
    identity: StaffIdentity,
    db: DbSession,
) -> dict:
    result = _service(db).award_completed_order(
        payload,
        order_id=order_id,
        actor_id=identity.sub,
        actor_role=str(identity.role),
        request_id=_request_id(request),
    )
    db.commit()
    return success(result, request_id=_request_id(request))
