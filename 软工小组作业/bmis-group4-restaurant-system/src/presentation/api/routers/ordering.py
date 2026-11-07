"""Reserved HTTP surface for menu browsing and order management.

The routes are mounted now so frontend and inter-module integration can target
stable paths. Every handler intentionally returns HTTP 501 until the ordering
service is implemented; no mock order is returned as if it were persisted.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends

from src.common.security import CurrentUser, Role, TokenPayload, require_roles
from src.presentation.api.pending import (
    RESERVED_RESPONSES,
    pending_endpoint,
    reserved_contract,
)

router = APIRouter(tags=["ordering"])

StaffIdentity = Annotated[
    TokenPayload,
    Depends(require_roles(Role.WAITER, Role.MANAGER, Role.ADMIN)),
]


@router.get(
    "/menu",
    status_code=501,
    summary="Browse the menu (reserved)",
    responses=RESERVED_RESPONSES,
    openapi_extra=reserved_contract("FR-ORD-01"),
)
def browse_menu(identity: CurrentUser) -> None:
    del identity
    pending_endpoint("Menu browsing")


@router.get(
    "/menu/{dish_id}",
    status_code=501,
    summary="View dish details (reserved)",
    responses=RESERVED_RESPONSES,
    openapi_extra=reserved_contract("FR-ORD-01"),
)
def get_dish(dish_id: int, identity: CurrentUser) -> None:
    del dish_id, identity
    pending_endpoint("Dish details")


@router.post(
    "",
    status_code=501,
    summary="Submit an order (reserved)",
    responses=RESERVED_RESPONSES,
    openapi_extra=reserved_contract("FR-ORD-02/FR-ORD-03"),
)
def submit_order(
    identity: CurrentUser,
    payload: dict[str, Any] | None = None,
) -> None:
    del payload, identity
    pending_endpoint("Order submission")


@router.get(
    "/{order_id}",
    status_code=501,
    summary="View an order (reserved)",
    responses=RESERVED_RESPONSES,
    openapi_extra=reserved_contract("FR-ORD-02"),
)
def get_order(order_id: str, identity: CurrentUser) -> None:
    del order_id, identity
    pending_endpoint("Order lookup")


@router.patch(
    "/{order_id}/status",
    status_code=501,
    summary="Update order status (reserved)",
    responses=RESERVED_RESPONSES,
    openapi_extra=reserved_contract("FR-ORD-04"),
)
def update_order_status(
    order_id: str,
    identity: StaffIdentity,
    payload: dict[str, Any] | None = None,
) -> None:
    del order_id, payload, identity
    pending_endpoint("Order status update")
