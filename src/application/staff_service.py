"""Application-tier facade for the staff back-office (Objective b).

The staff module never touches another module's tables (ARCHITECTURE.md §7):
every reservation read and write goes through the reservation module's
service. This file is where the eventual order-facing methods will live once
the ordering module ships its backend; until then the order endpoints in
``src/presentation/api/routers/staff.py`` stay placeholder-only.
"""

from src.application.reservation.models import ReservationStatus
from src.application.reservation.service import ReservationService


class StaffService:
    """Back-office workflows, composed from other modules' services."""

    def __init__(self, reservation_service: ReservationService | None = None) -> None:
        self._reservations = reservation_service or ReservationService()

    def list_reservations(self) -> list[dict]:
        """All reservations, oldest first — the staff list view (FR-RES-06)."""
        return self._reservations.list_reservations()

    def update_reservation_status(
        self, reservation_id: int, status: ReservationStatus
    ) -> dict | None:
        """Move a reservation to ``status``; ``None`` when it does not exist."""
        return self._reservations.set_reservation_status(reservation_id, status)
