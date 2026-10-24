from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from .service import ReservationService

router = APIRouter()
service = ReservationService()


class ReservationCreateSchema(BaseModel):
    table_id: int
    user_id: str
    reservation_time: str


@router.post("/reservations")
def create_reservation(payload: ReservationCreateSchema) -> dict:
    res = service.create_reservation(
        table_id=str(payload.table_id),
        customer_name=payload.user_id,
        start_time=None,
        end_time=None,
        user_id=payload.user_id,
    )
    if not res:
        raise HTTPException(status_code=400, detail="Reservation failed")
    return {"status": "success", "id": res.id}


@router.post("/reservations/{reservation_id}/cancel")
def cancel_reservation(reservation_id: int) -> dict:
    res = service.cancel_reservation(reservation_id)
    if not res:
        raise HTTPException(status_code=404, detail="Reservation not found")
    return {"status": "cancelled"}
