from datetime import datetime, timedelta

from .models import Reservation, ReservationStatus
from .repository import ReservationRepository


class ReservationService:
    def __init__(self, repository: ReservationRepository | None = None):
        self.repository = repository or ReservationRepository()
        self.hold_duration_minutes = 15

    def create_reservation(
        self,
        table_id: str,
        customer_name: str,
        start_time: datetime,
        end_time: datetime,
        user_id: str | None = None,
        reservation_time: datetime | None = None,
    ) -> Reservation | None:
        eff_start = start_time or reservation_time or datetime.now()
        return self.repository.create(
            user_id=user_id or customer_name,
            table_id=int(table_id),
            reservation_time=eff_start,
        )

    def cancel_reservation(self, reservation_id: int) -> Reservation | None:
        return self.repository.update_status(
            reservation_id=reservation_id,
            status=ReservationStatus.CANCELLED,
        )
