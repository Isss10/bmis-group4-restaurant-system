from datetime import datetime,timedelta

from src.common.errors import permission_denied
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
        def find_overlapping_reservations(
        self,
        table_id: int,
        start_time: datetime,
        end_time: datetime,
        active_statuses: list[ReservationStatus],
    ) -> list[Reservation]:
        with session_scope() as session:
            return (
                session.query(Reservation)
                .filter(
                    Reservation.table_id == table_id,
                    Reservation.status.in_(active_statuses),
                    Reservation.reservation_time < end_time,
                    Reservation.reservation_time + timedelta(minutes=120) > start_time,
                )
                .all()
            )
    def list_reservations(self) -> list[dict]:
        with session_scope() as session:
            rows = (
                session.query(Reservation)
                .order_by(Reservation.reservation_time)
                .all()
            )
            return [
                {
                    "id": row.id,
                    "user_id": row.user_id,
                    "table_id": row.table_id,
                    "reservation_time": row.reservation_time,
                    "status": row.status,
                }
                for row in rows
            ]

    def update_status(
        self,
        reservation_id: int,
        status: ReservationStatus,
        *,
        user_id: str | None = None,
    ) -> dict | None:
        with session_scope() as session:
            reservation = (
                session.query(Reservation)
                .filter(Reservation.id == reservation_id)
                .with_for_update()
                .first()
            )
            if not reservation:
                return None
            if user_id is not None and reservation.user_id != user_id:
                raise permission_denied()
            reservation.status = status
            session.flush()
            session.refresh(reservation)
            return {
                "id": reservation.id,
                "reservation_time": reservation.reservation_time,
                "status": reservation.status,
            }
