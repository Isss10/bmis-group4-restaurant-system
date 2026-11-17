from datetime import datetime

from .models import ReservationStatus
from .repository import ReservationRepository


class ReservationService:
    def __init__(self, repository: ReservationRepository | None = None):
        self.repository = repository or ReservationRepository()

    def create_reservation(
        self,
        table_id: int,
        user_id: str,
        reservation_time: datetime,
    ) -> dict:
        return self.repository.create(
            user_id=user_id,
            table_id=table_id,
            reservation_time=reservation_time,
        )

    def cancel_reservation(self, reservation_id: int) -> dict | None:
        return self.repository.update_status(
            reservation_id=reservation_id,
            status=ReservationStatus.CANCELLED,
        )
