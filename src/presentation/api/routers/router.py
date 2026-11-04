from datetime import datetime

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from src.application.reservation.service import ReservationService

router = APIRouter(prefix="/reservations", tags=["reservation"])
service = ReservationService()


class ReservationCreateSchema(BaseModel):
    table_id: int
    user_id: str
    reservation_time: datetime


@router.post("")
def create_reservation(payload: ReservationCreateSchema) -> dict:
    res = service.create_reservation(
        table_id=payload.table_id,
        user_id=payload.user_id,
        reservation_time=payload.reservation_time,
    )
    if not res:
        raise HTTPException(status_code=400, detail="Reservation failed")
    return {"status": "success", "id": res["id"]}


@router.post("/{reservation_id}/cancel")
def cancel_reservation(reservation_id: int) -> dict:
    res = service.cancel_reservation(reservation_id)
    if not res:
        raise HTTPException(status_code=404, detail="Reservation not found")
    return {"status": "cancelled"}
