from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from src.application.reservation.service import ReservationService
from src.common.envelope import success
from src.common.errors import not_found, validation_failed
from src.common.middleware import REQUEST_ID_ATTR
from src.common.security import CurrentUser, Role, TokenPayload, require_roles
from src.presentation.api.pending import (
    RESERVED_RESPONSES,
    pending_endpoint,
    reserved_contract,
)

# HTTP surface for the reservation module (Objective a). Renamed from
# `routers/router.py`: the loader looks up `src.presentation.api.routers.<module>`
# by module name, so a file called `router.py` was invisible to it and none of
# these endpoints were ever mounted. No internal prefix here — the loader mounts
# this router at the frozen base path `/api/v1/reservations` (manual §4.2), and a
# second prefix in the file produced double-prefixed routes (as PR #4's staff
# router demonstrated).
router = APIRouter(tags=["reservation"])
service = ReservationService()
StaffIdentity = Annotated[
    TokenPayload,
    Depends(require_roles(Role.WAITER, Role.MANAGER, Role.ADMIN)),
]


class ReservationCreateSchema(BaseModel):
    table_id: int
    user_id: str
    reservation_time: datetime


@router.post("")
def create_reservation(payload: ReservationCreateSchema, request: Request) -> dict:
    res = service.create_reservation(
        table_id=payload.table_id,
        user_id=payload.user_id,
        reservation_time=payload.reservation_time,
    )
    if not res:
        # 10001 / 422 via the frozen envelope instead of a bare 400 dict. The
        # service returns a falsy result when the booking cannot be recorded;
        # the concurrency safety net (unique constraint → 20001) lives in the
        # repository layer and surfaces as ApiError before reaching here.
        raise validation_failed(message="Reservation failed")
    return success(
        {"status": "success", "id": res["id"]},
        request_id=getattr(request.state, REQUEST_ID_ATTR, None),
    )


@router.post("/{reservation_id}/cancel")
def cancel_reservation(reservation_id: int, request: Request) -> dict:
    res = service.cancel_reservation(reservation_id)
    if not res:
        raise not_found("Reservation not found")
    return success(
        {"status": "cancelled"},
        request_id=getattr(request.state, REQUEST_ID_ATTR, None),
    )


@router.get(
    "",
    status_code=501,
    summary="List reservations (reserved)",
    responses=RESERVED_RESPONSES,
    openapi_extra=reserved_contract("FR-RES-06"),
)
def list_reservations(identity: CurrentUser) -> None:
    del identity
    pending_endpoint("Reservation listing")


@router.get(
    "/availability",
    status_code=501,
    summary="Query table availability (reserved)",
    responses=RESERVED_RESPONSES,
    openapi_extra=reserved_contract("FR-RES-01"),
)
def list_availability(identity: CurrentUser) -> None:
    del identity
    pending_endpoint("Table availability")


@router.post(
    "/{reservation_id}/confirm",
    status_code=501,
    summary="Confirm a held reservation (reserved)",
    responses=RESERVED_RESPONSES,
    openapi_extra=reserved_contract("FR-RES-02"),
)
def confirm_reservation(reservation_id: int, identity: CurrentUser) -> None:
    del reservation_id, identity
    pending_endpoint("Reservation confirmation")


@router.patch(
    "/{reservation_id}/status",
    status_code=501,
    summary="Change reservation status (reserved)",
    responses=RESERVED_RESPONSES,
    openapi_extra=reserved_contract("FR-RES-05/FR-RES-06"),
)
def change_reservation_status(
    reservation_id: int,
    identity: StaffIdentity,
    payload: dict[str, Any] | None = None,
) -> None:
    del reservation_id, identity, payload
    pending_endpoint("Reservation status transition")


@router.post(
    "/expire-holds",
    status_code=501,
    summary="Expire stale seat holds (reserved)",
    responses=RESERVED_RESPONSES,
    openapi_extra=reserved_contract("FR-RES-04"),
)
def expire_reservation_holds(identity: StaffIdentity) -> None:
    del identity
    pending_endpoint("Seat-hold expiry")
