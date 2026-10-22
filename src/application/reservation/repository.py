from typing import Optional
from src.data.database import Base
from .models import Reservation, ReservationStatus
class ReservationRepository:

    def create(self, user_id: str, table_id: int, reservation_time) -> Reservation:
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
            return reservation

    def get_by_id_with_lock(self, reservation_id: int) -> Optional[Reservation]:
        """使用 with_for_update 进行悲观加锁，防止并发冲突"""
        with session_scope() as session:
            return (
                session.query(Reservation)
                .filter(Reservation.id == reservation_id)
                .with_for_update()
                .first()
            )

    def update_status(self, reservation_id: int, status: ReservationStatus) -> Optional[Reservation]:
        with session_scope() as session:
            reservation = (
                session.query(Reservation)
                .filter(Reservation.id == reservation_id)
                .with_for_update()
                .first()
            )
            if reservation:
                reservation.status = status
                session.flush()
                session.refresh(reservation)
            return reservation
