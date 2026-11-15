from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from src.application.reservation.models import ReservationStatus
from src.application.staff_service import StaffService
from src.common.envelope import success
from src.common.errors import not_found
from src.common.middleware import REQUEST_ID_ATTR
from src.common.security import TokenPayload, require_staff

# HTTP surface for the staff back-office (Objective b). Mounted by the loader at
# the frozen base path `/api/v1/staff` (manual §4.2). The path/envelope/auth
# groundwork came in with PR #13's contract alignment; this branch wires the
# reservation endpoints to the real reservation service (the follow-up PR #4's
# header comment called out) and leaves the order endpoints placeholder-only
# until the ordering module ships a backend to call — inventing order data here
# would only mislead the three frontends.
#
# Cross-module rule (ARCHITECTURE.md §7): staff must not read the reservations
# table directly, so every call goes through the reservation module's service,
# reached via the staff module's own StaffService facade.
router = APIRouter(tags=["staff"])

service = StaffService()

StaffIdentity = Annotated[TokenPayload, Depends(require_staff())]


class ReservationStatusUpdateSchema(BaseModel):
    """Body for the back-office status patch."""

    status: ReservationStatus
    """Target state: PENDING, CONFIRMED or CANCELLED (frozen vocabulary)."""


@router.get("/reservations")
def get_reservations(request: Request, _identity: StaffIdentity) -> Any:
    """List all reservations for staff (FR-RES-06)."""
    data = service.list_reservations()
    return success(
        data,
        message="Reservation list retrieved",
        request_id=getattr(request.state, REQUEST_ID_ATTR, None),
    )


@router.patch("/reservations/{reservation_id}")
def update_reservation_status(
    reservation_id: int,
    payload: ReservationStatusUpdateSchema,
    request: Request,
    _identity: StaffIdentity,
) -> Any:
    """Update a reservation's status (FR-RES-06)."""
    updated = service.update_reservation_status(reservation_id, payload.status)
    if updated is None:
        raise not_found("Reservation not found")
    return success(
        updated,
        message="Reservation status updated",
        request_id=getattr(request.state, REQUEST_ID_ATTR, None),
    )


@router.get("/orders")
def get_orders(request: Request, _identity: StaffIdentity) -> Any:
    """List customer orders for staff (FR-ORD-04). Placeholder.

    The ordering module has no backend yet (its service tier is empty), so
    there is nothing real to return. A 200 with placeholder data is kept only
    so the mounted route and the auth guard stay exercised; replace with the
    ordering service call once member5's backend lands.
    """
    placeholder: list[dict[str, Any]] = []
    return success(
        placeholder,
        message="Order list not yet implemented",
        request_id=getattr(request.state, REQUEST_ID_ATTR, None),
    )


@router.patch("/orders/{order_id}")
def update_order_status(order_id: int, request: Request, _identity: StaffIdentity) -> Any:
    """Update an order's status (FR-ORD-04). Placeholder — see get_orders."""
    raise not_found(f"Order {order_id} not found: ordering backend not implemented yet")
