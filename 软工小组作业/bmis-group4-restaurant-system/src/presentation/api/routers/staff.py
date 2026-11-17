from typing import Annotated, Any

from fastapi import APIRouter, Depends

from src.common.security import TokenPayload, require_staff
from src.presentation.api.pending import (
    RESERVED_RESPONSES,
    pending_endpoint,
    reserved_contract,
)

# HTTP surface for the staff back-office (Objective b). Mounted by the loader at
# the frozen base path `/api/v1/staff` (manual §4.2). Three contract fixes versus
# the version merged in PR #4, all forced by this branch's router-location change
# that actually mounts this file for the first time:
#   1. No internal `/staff/` prefix — the loader already adds `/api/v1/staff`, so
#      keeping it produced `/api/v1/staff/staff/reservations`.
#   2. `success()` comes from the real `src.common.envelope`. The old import of
#      `src.common.response` does not exist, so the try/except silently fell back
#      to a hand-rolled `{"code": 200, ...}` body that is not the frozen envelope
#      (the contract's success code is 0, not 200).
#   3. Auth uses the real `require_staff()` guard (waiter/manager/admin) instead
#      of `require_staff_roles()`, which returned a hardcoded dict and enforced
#      nothing — every back-office endpoint was publicly reachable (OWASP A01).
#
# The handlers still return placeholder data; wiring them to the reservation and
# order services is the staff module owner's follow-up (PR #4 scope). This file's
# job here is to mount at the correct path, speak the frozen contract, and be
# access-controlled — not to finish the module.
router = APIRouter(tags=["staff"])

StaffIdentity = Annotated[TokenPayload, Depends(require_staff())]


@router.get(
    "/reservations",
    status_code=501,
    summary="List reservations (reserved)",
    responses=RESERVED_RESPONSES,
    openapi_extra=reserved_contract("FR-RES-06"),
)
def get_reservations(identity: StaffIdentity) -> None:
    """List all reservations for staff (FR-RES-06)."""
    del identity
    pending_endpoint("Staff reservation list")


@router.patch(
    "/reservations/{reservation_id}",
    status_code=501,
    summary="Update reservation status (reserved)",
    responses=RESERVED_RESPONSES,
    openapi_extra=reserved_contract("FR-RES-06"),
)
def update_reservation_status(
    reservation_id: int,
    identity: StaffIdentity,
    payload: dict[str, Any] | None = None,
) -> None:
    """Update a reservation's status (FR-RES-06)."""
    del reservation_id, identity, payload
    pending_endpoint("Staff reservation status update")


@router.get(
    "/orders",
    status_code=501,
    summary="List customer orders (reserved)",
    responses=RESERVED_RESPONSES,
    openapi_extra=reserved_contract("FR-ORD-04"),
)
def get_orders(identity: StaffIdentity) -> None:
    """List customer orders for staff (FR-ORD-04)."""
    del identity
    pending_endpoint("Staff order list")


@router.patch(
    "/orders/{order_id}",
    status_code=501,
    summary="Update order status (reserved)",
    responses=RESERVED_RESPONSES,
    openapi_extra=reserved_contract("FR-ORD-04"),
)
def update_order_status(
    order_id: int,
    identity: StaffIdentity,
    payload: dict[str, Any] | None = None,
) -> None:
    """Update an order's status (FR-ORD-04)."""
    del order_id, identity, payload
    pending_endpoint("Staff order status update")
