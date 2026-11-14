from datetime import datetime

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

    def list_reservations(self) -> list[dict]:
        """Return every reservation, oldest ``reservation_time`` first.

        Added by the staff module owner (Objective b) for the back-office list
        view: ARCHITECTURE.md §7 forbids the staff module from reading the
        ``reservations`` table directly, so the read has to live here, behind
        the reservation module's own boundary. Strictly additive — no existing
        behaviour changes; reservation-module owner please eyeball this in
        review.

        Values are copied into plain dicts *inside* the session scope so the
        caller never touches a detached ORM instance (same discipline as
        ``create`` above).
        """
        with session_scope() as session:
            rows = session.query(Reservation).order_by(Reservation.reservation_time).all()
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
            # The public cancellation route always supplies its verified subject.
            # Check after locking, within the same transaction as the update.
            if user_id is not None and reservation.user_id != user_id:
                raise permission_denied()
            reservation.status = status  # type: ignore
            session.flush()
            session.refresh(reservation)
            return {
                "id": reservation.id,
                "reservation_time": reservation.reservation_time,
                "status": reservation.status,
            }
