from datetime import UTC, datetime, timedelta

from .models import ReservationStatus
from .repository import ReservationRepository


class ReservationService:
    ALLOWED_TRANSITIONS = {
        ReservationStatus.PENDING: {
            ReservationStatus.CONFIRMED,
            ReservationStatus.CANCELLED,
        },
        ReservationStatus.CONFIRMED: {
            ReservationStatus.CANCELLED,
        },
        ReservationStatus.CANCELLED: set(),
    }

    def __init__(self, repository: ReservationRepository | None = None):
        self.repository = repository or ReservationRepository()

    def list_reservations(self) -> list[dict]:
        return self.repository.list_reservations()

    def release_expired_holds(self) -> int:
        now = datetime.now(UTC).replace(tzinfo=None)
        expired_ids = self.repository.find_expired_holds(now)
        count = 0
        for res_id in expired_ids:
            self.repository.update_status(res_id, ReservationStatus.CANCELLED)
            count += 1
        return count

    def create_reservation(
        self,
        user_id: str,
        table_id: int,
        reservation_time: datetime,
    ) -> dict:
        end_time = reservation_time + timedelta(minutes=120)
        active_statuses = [ReservationStatus.PENDING, ReservationStatus.CONFIRMED]
        conflicts = self.repository.find_overlapping_reservations(
            table_id=table_id,
            start_time=reservation_time,
            end_time=end_time,
            active_statuses=active_statuses,
        )
        if conflicts:
            raise ValueError("Time slot is already booked.")

        expires_at = datetime.now(UTC).replace(tzinfo=None) + timedelta(minutes=15)

        return self.repository.create(
            user_id=user_id,
            table_id=table_id,
            reservation_time=reservation_time,
            end_time=end_time,
            expires_at=expires_at,
            status=ReservationStatus.PENDING,
        )

    def cancel_reservation(self, reservation_id: int, user_id: str | None = None) -> dict | None:
        return self.repository.update_status(
            reservation_id, ReservationStatus.CANCELLED, user_id=user_id
        )

    def set_reservation_status(self, reservation_id: int, status: ReservationStatus) -> dict | None:
        return self.repository.update_status(reservation_id, status)
