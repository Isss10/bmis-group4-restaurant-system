from datetime import datetime, timedelta
from .models import Reservation, ReservationStatus
from .repository import ReservationRepository


class ReservationService:
    def __init__(self, repository):
        self.repository = repository
        self.hold_duration_minutes = 15

    def create_reservation(
        self, table_id: str, customer_name: str, start_time: datetime, end_time: datetime
    ) -> Reservation:
        existing_reservations = self.repository.get_by_table(table_id)
        for res in existing_reservations:
            if res.status in [ReservationStatus.HELD, ReservationStatus.CONFIRMED]:
                if res.status == ReservationStatus.HELD and datetime.now() > res.expires_at:
                    res.status = ReservationStatus.EXPIRED
                    self.repository.save(res)
                    continue

                if start_time < res.end_time and end_time > res.start_time:
                    raise ValueError(
                        f"Table {table_id} is already booked or held during this time slot."
                    )

        now = datetime.now()
        expires_at = now + timedelta(minutes=self.hold_duration_minutes)

        reservation = Reservation(
            table_id=table_id,
            customer_name=customer_name,
            start_time=start_time,
            end_time=end_time,
            status=ReservationStatus.HELD,
            expires_at=expires_at,
        )
        return self.repository.save(reservation)

    def confirm_reservation(self, reservation_id: str) -> Reservation:
        reservation = self.repository.get_by_id(reservation_id)
        if not reservation:
            raise KeyError("Reservation not found.")

        if reservation.status != ReservationStatus.HELD:
            raise ValueError(f"Cannot confirm reservation in status: {reservation.status}")

        if datetime.now() > reservation.expires_at:
            reservation.status = ReservationStatus.EXPIRED
            self.repository.save(reservation)
            raise ValueError("Reservation hold time expired. Please book again.")

        reservation.status = ReservationStatus.CONFIRMED
        return self.repository.save(reservation)

    def cancel_reservation(self, reservation_id: str) -> Reservation:
        reservation = self.repository.get_by_id(reservation_id)
        if not reservation:
            raise KeyError("Reservation not found.")

        if reservation.status in [ReservationStatus.CONFIRMED, ReservationStatus.HELD]:
            reservation.status = ReservationStatus.CANCELLED
            return self.repository.save(reservation)

        raise ValueError(f"Cannot cancel reservation in status: {reservation.status}")
