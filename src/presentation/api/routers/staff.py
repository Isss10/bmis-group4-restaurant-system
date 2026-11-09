from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request

from src.common.envelope import success
from src.common.middleware import REQUEST_ID_ATTR
from src.common.security import TokenPayload, require_staff

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


@router.get("/reservations")
def get_reservations(request: Request, _identity: StaffIdentity) -> Any:
    """List all reservations for staff (FR-RES-06)."""
    mock_data = [{"id": 1, "status": "confirmed", "time": "18:00"}]
    return success(
        mock_data,
        message="Reservation list retrieved",
        request_id=getattr(request.state, REQUEST_ID_ATTR, None),
    )


@router.patch("/reservations/{reservation_id}")
def update_reservation_status(
    reservation_id: int, request: Request, _identity: StaffIdentity
) -> Any:
    """Update a reservation's status (FR-RES-06)."""
    mock_data = {"reservation_id": reservation_id, "status": "updated"}
    return success(
        mock_data,
        message="Reservation status updated",
        request_id=getattr(request.state, REQUEST_ID_ATTR, None),
    )


@router.get("/orders")
def get_orders(request: Request, _identity: StaffIdentity) -> Any:
    """List customer orders for staff (FR-ORD-04)."""
    mock_data = [{"id": 101, "dish": "Pizza", "status": "preparing"}]
    return success(
        mock_data,
        message="Order list retrieved",
        request_id=getattr(request.state, REQUEST_ID_ATTR, None),
    )


@router.patch("/orders/{order_id}")
def update_order_status(order_id: int, request: Request, _identity: StaffIdentity) -> Any:
    """Update an order's status (FR-ORD-04)."""
    mock_data = {"order_id": order_id, "status": "completed"}
    return success(
        mock_data,
        message="Order status updated",
        request_id=getattr(request.state, REQUEST_ID_ATTR, None),
    )
