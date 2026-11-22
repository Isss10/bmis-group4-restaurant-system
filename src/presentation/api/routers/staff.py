from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from src.application.ordering.models import OrderStatus
from src.application.reservation.models import ReservationStatus
from src.application.staff_service import StaffService
from src.common.envelope import success
from src.common.errors import not_found
from src.common.middleware import REQUEST_ID_ATTR
from src.common.security import TokenPayload, require_staff

# HTTP surface for the staff back-office (Objective b). Mounted by the loader at
# the frozen base path `/api/v1/staff` (manual §4.2). The path/envelope/auth
# groundwork came in with PR #13's contract alignment; the reservation endpoints
# were wired to the real reservation service in PR #20 and the order endpoints
# now go through the same facade to M5's merged OrderingService (FR-ORD-04).
#
# Cross-module rule (ARCHITECTURE.md §7): staff must not read another module's
# tables directly, so every call goes through that module's service, reached via
# the staff module's own StaffService facade.
router = APIRouter(tags=["staff"])

service = StaffService()

StaffIdentity = Annotated[TokenPayload, Depends(require_staff())]


class ReservationStatusUpdateSchema(BaseModel):
    """Body for the back-office status patch."""

    status: ReservationStatus
    """Target state from the 7-state ReservationStatus vocabulary (FR-RES-06)."""


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


class OrderStatusUpdateSchema(BaseModel):
    """Body for the back-office order status patch."""

    status: OrderStatus
    """Target state from the FR-ORD-04 frozen vocabulary (uppercase)."""


@router.get("/orders")
def get_orders(request: Request, _identity: StaffIdentity) -> Any:
    """List customer orders for staff (FR-ORD-04)."""
    data = service.list_orders()
    return success(
        data,
        message="Order list retrieved",
        request_id=getattr(request.state, REQUEST_ID_ATTR, None),
    )


@router.patch("/orders/{order_id}")
def update_order_status(
    order_id: int,
    payload: OrderStatusUpdateSchema,
    request: Request,
    _identity: StaffIdentity,
) -> Any:
    """Advance an order's status (FR-ORD-04)."""
    updated = service.update_order_status(order_id, payload.status)
    if updated is None:
        raise not_found(f"Order {order_id} not found")
    return success(
        updated,
        message="Order status updated",
        request_id=getattr(request.state, REQUEST_ID_ATTR, None),
    )
