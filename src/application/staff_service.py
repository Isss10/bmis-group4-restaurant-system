"""Application-tier facade for the staff back-office (Objective b).

The staff module never touches another module's tables (ARCHITECTURE.md §7):
every reservation read/write goes through the reservation module's service, and
every order read/write through the ordering module's service. Both are reached
through this facade so the presentation tier stays module-agnostic.
"""

from typing import Any, cast

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from src.application.ordering.models import OrderStatus
from src.application.ordering.ordering_service import OrderingService
from src.application.reservation.models import ReservationStatus
from src.application.reservation.service import ReservationService
from src.data.database import session_scope


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

    def _ordering(self, session: Session) -> OrderingService:
        # M5's __init__ is annotated AsyncSession while get_db()/session_scope()
        # actually yield a synchronous Session (src/data/database.py L203).
        # Cast only to satisfy that legacy annotation; her signature is NOT
        # changed in this PR. See PR description / ask member5 to review.
        return OrderingService(cast(AsyncSession, session))

    def list_orders(self) -> list[dict[str, Any]]:
        """All orders for the staff list view (FR-ORD-04)."""
        with session_scope() as session:
            return self._ordering(session).list_orders()

    def update_order_status(self, order_id: int, status: OrderStatus) -> dict[str, Any] | None:
        """Advance an order's status; ``None`` when the row does not exist."""
        with session_scope() as session:
            return self._ordering(session).set_order_status(order_id, status)
