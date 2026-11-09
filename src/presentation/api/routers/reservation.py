from datetime import datetime

from fastapi import APIRouter, Request
from pydantic import BaseModel

from src.application.reservation.service import ReservationService
from src.common.envelope import success
from src.common.errors import not_found, validation_failed
from src.common.middleware import REQUEST_ID_ATTR

# HTTP surface for the reservation module (Objective a). Renamed from
# `routers/router.py`: the loader looks up `src.presentation.api.routers.<module>`
# by module name, so a file called `router.py` was invisible to it and none of
# these endpoints were ever mounted. No internal prefix here — the loader mounts
# this router at the frozen base path `/api/v1/reservations` (manual §4.2), and a
# second prefix in the file produced double-prefixed routes (as PR #4's staff
# router demonstrated).
router = APIRouter(tags=["reservation"])
service = ReservationService()


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
