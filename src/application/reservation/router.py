from datetime import datetime

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from .service import ReservationService

router = APIRouter(prefix="/reservations", tags=["Reservations"])
service = ReservationService()


class ReservationCreateSchema(BaseModel):
    user_id: str
    table_id: int
    reservation_time: datetime


@router.post("/", status_code=status.HTTP_201_CREATED)
def create_reservation(payload: ReservationCreateSchema):
    try:
        res = service.create_reservation(
            user_id=payload.user_id,
            table_id=payload.table_id,
            reservation_time=payload.reservation_time,
        )
        return {"success": True, "data": res}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post("/{reservation_id}/cancel")
def cancel_reservation(reservation_id: int):
    res = service.cancel_reservation(reservation_id)
    if not res:
        raise HTTPException(status_code=404, detail="Reservation not found")
    return {"success": True, "data": res}
