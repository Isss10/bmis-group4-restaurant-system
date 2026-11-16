from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from src.application.reservation.service import ReservationService
from src.common.envelope import success
from src.common.errors import permission_denied, validation_failed
from src.common.security import Role, TokenPayload, require_roles

router = APIRouter(tags=["reservation"])
service = ReservationService()
Customer = Annotated[TokenPayload, Depends(require_roles(Role.CUSTOMER))]


class ReservationCreateSchema(BaseModel):
    table_id: int
    reservation_time: datetime
    user_id: str | None = None


def _format_status_lowercase(res: Any) -> Any:
    if isinstance(res, dict):
        if "status" in res and res["status"] is not None:
            val = res["status"]
            if hasattr(val, "value"):
                res["status"] = val.value.lower()
            else:
                res["status"] = str(val).lower()
    return res


@router.post("")
def create_reservation(
    payload: ReservationCreateSchema, request: Request, identity: Customer
) -> dict:
    if payload.user_id is not None and payload.user_id != identity.sub:
        raise permission_denied()

    try:
        res = service.create_reservation(
            table_id=payload.table_id,
            user_id=identity.sub,
            reservation_time=payload.reservation_time,
        )
    except ValueError as exc:
        raise validation_failed(message=str(exc)) from exc

    if not res:
        raise validation_failed(message="Reservation failed")

    return success(_format_status_lowercase(res))


@router.post("/{reservation_id}/cancel")
def cancel_reservation(reservation_id: int, identity: Customer) -> dict:
    try:
        res = service.cancel_reservation(reservation_id, user_id=identity.sub)
    except ValueError as exc:
        raise validation_failed(message=str(exc)) from exc

    if not res:
        raise HTTPException(status_code=404, detail="Reservation not found")

    return success(_format_status_lowercase(res))
