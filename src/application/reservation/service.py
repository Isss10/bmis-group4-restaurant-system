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

    def list_reservations(self) -> list[dict]:
        """List all reservations, oldest first.

        Added by the staff module owner (Objective b): the back-office needs a
        read API that stays on the reservation module's side of the boundary
        (ARCHITECTURE.md §7 — staff must call this service, never the table).
        Strictly additive.
        """
        return self.repository.list_reservations()

    def set_reservation_status(self, reservation_id: int, status: ReservationStatus) -> dict | None:
        """Set a reservation to ``status`` without an ownership check.

        Added by the staff module owner (Objective b) for the back-office
        status workflow (e.g. marking PENDING -> CONFIRMED at the door).
        Unlike :meth:`cancel_reservation` there is no ``user_id`` guard, because
        the caller is staff acting on behalf of the restaurant, not the
        customer who owns the row. The state-machine legality of the
        transition is the reservation module's own follow-up (Objective a,
        ALLOWED_TRANSITIONS); this method deliberately performs the mechanical
        write only, reusing the repository's existing locked update.
        """
        return self.repository.update_status(reservation_id=reservation_id, status=status)

    def cancel_reservation(self, reservation_id: int, *, user_id: str | None = None) -> dict | None:
        return self.repository.update_status(
            reservation_id=reservation_id,
            status=ReservationStatus.CANCELLED,
            user_id=user_id,
        )
