"""Reserved HTTP surface for the manager analytics dashboard."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from src.common.security import Role, TokenPayload, require_roles
from src.presentation.api.pending import (
    RESERVED_RESPONSES,
    pending_endpoint,
    reserved_contract,
)

router = APIRouter(tags=["analytics"])

ManagerIdentity = Annotated[
    TokenPayload,
    Depends(require_roles(Role.MANAGER, Role.ADMIN)),
]


@router.get(
    "/summary",
    status_code=501,
    summary="Dashboard summary (reserved)",
    responses=RESERVED_RESPONSES,
    openapi_extra=reserved_contract("FR-ANA-01/FR-ANA-04"),
)
def dashboard_summary(identity: ManagerIdentity) -> None:
    del identity
    pending_endpoint("Analytics dashboard")


@router.get(
    "/revenue",
    status_code=501,
    summary="Revenue trend (reserved)",
    responses=RESERVED_RESPONSES,
    openapi_extra=reserved_contract("FR-ANA-01"),
)
def revenue_trend(identity: ManagerIdentity) -> None:
    del identity
    pending_endpoint("Revenue trend")


@router.get(
    "/table-turnover",
    status_code=501,
    summary="Table turnover (reserved)",
    responses=RESERVED_RESPONSES,
    openapi_extra=reserved_contract("FR-ANA-02"),
)
def table_turnover(identity: ManagerIdentity) -> None:
    del identity
    pending_endpoint("Table turnover")


@router.get(
    "/demand-heatmap",
    status_code=501,
    summary="Hourly demand heat map (reserved)",
    responses=RESERVED_RESPONSES,
    openapi_extra=reserved_contract("FR-ANA-03"),
)
def demand_heatmap(identity: ManagerIdentity) -> None:
    del identity
    pending_endpoint("Demand heat map")


@router.get(
    "/no-show-rate",
    status_code=501,
    summary="No-show rate (reserved)",
    responses=RESERVED_RESPONSES,
    openapi_extra=reserved_contract("FR-ANA-04"),
)
def no_show_rate(identity: ManagerIdentity) -> None:
    del identity
    pending_endpoint("No-show rate")


@router.get(
    "/recommendations",
    status_code=501,
    summary="Dish recommendations (reserved)",
    responses=RESERVED_RESPONSES,
    openapi_extra=reserved_contract("FR-ANA-05"),
)
def recommendations(identity: ManagerIdentity) -> None:
    del identity
    pending_endpoint("Recommendations")
