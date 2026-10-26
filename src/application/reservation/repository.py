from datetime import datetime

from src.data.database import session_scope

from .models import Reservation, ReservationStatus


class ReservationRepository:
    def create(self, user_id: str, table_id: int, reservation_time: datetime) -> dict:
        with session_scope() as session:
            reservation = Reservation(
                user_id=user_id,
                table_id=table_id,
                reservation_time=reservation_time,
                status=ReservationStatus.PENDING,
            )
            session.add(reservation)
            session.flush()
            session.refresh(reservation)
            res_id = reservation.id
            res_time = reservation.reservation_time
            res_status = reservation.status
            return {
                "id": res_id,
                "reservation_time": res_time,
                "status": res_status,
            }

    def update_status(self, reservation_id: int, status: ReservationStatus) -> dict | None:
        with session_scope() as session:
            reservation = (
                session.query(Reservation)
                .filter(Reservation.id == reservation_id)
                .with_for_update()
                .first()
            )
            if not reservation:
                return None
            reservation.status = status  # type:ignore
            session.flush()
            session.refresh(reservation)
            return {
                "id": reservation.id,
                "reservation_time": reservation.reservation_time,
                "status": reservation.status,
            }
            session.flush()
            session.refresh(reservation)
            return {
                "id": reservation.id,
                "reservation_time": reservation.reservation_time,
                "status": reservation.status,
            }
