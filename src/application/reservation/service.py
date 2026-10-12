from datetime import datetime, timedelta
from models import Reservation, ReservationStatus

class ReservationService:
    def __init__(self, repository):
        self.repository = repository
        self.hold_duration_minutes = 15  # 临时锁座 15 分钟

    def create_reservation(self, table_id: str, customer_name: str, start_time: datetime, end_time: datetime) -> Reservation:
        # 1. 检查该时间段是否有冲突的有效预订
        existing_reservations = self.repository.get_by_table(table_id)
        for res in existing_reservations:
            # 如果订单没有被取消或过期，才需要检查时间冲突
            if res.status in [ReservationStatus.HELD, ReservationStatus.CONFIRMED]:
                # 检查 HELD 状态是否已经超时，如果超时了先自动标记为 EXPIRED
                if res.status == ReservationStatus.HELD and datetime.now() > res.expires_at:
                    res.status = ReservationStatus.EXPIRED
                    self.repository.save(res)
                    continue

                # 时间重叠区间检查: (StartA < EndB) and (EndA > StartB)
                if start_time < res.end_time and end_time > res.start_time:
                    raise ValueError(f"Table {table_id} is already booked or held during this time slot.")

        # 2. 计算 15 分钟后的过期时间
        now = datetime.now()
        expires_at = now + timedelta(minutes=self.hold_duration_minutes)

        # 3. 创建新预订对象，初始状态为 HELD
        reservation = Reservation(
            table_id=table_id,
            customer_name=customer_name,
            start_time=start_time,
            end_time=end_time,
            status=ReservationStatus.HELD,
            expires_at=expires_at
        )

        # 4. 保存到存储层
        return self.repository.save(reservation)

    def confirm_reservation(self, reservation_id: str) -> Reservation:
        #确认预订（用户在 15 分钟内完成支付或确认，转为 CONFIRMED）
        reservation = self.repository.get_by_id(reservation_id)
        if not reservation:
            raise KeyError("Reservation not found.")

        # 检查当前状态是否允许确认
        if reservation.status != ReservationStatus.HELD:
            raise ValueError(f"Cannot confirm reservation in status: {reservation.status}")

        # 检查是否已经超过 15 分钟锁座时间
        if datetime.now() > reservation.expires_at:
            reservation.status = ReservationStatus.EXPIRED
            self.repository.save(reservation)
            raise ValueError("Reservation hold time expired. Please book again.")

        # 更新状态
        reservation.status = ReservationStatus.CONFIRMED
        return self.repository.save(reservation)

    def cancel_reservation(self, reservation_id: str) -> Reservation:
        #取消预约
        reservation = self.repository.get_by_id(reservation_id)
        if not reservation:
            raise KeyError("Reservation not found.")

        if reservation.status in [ReservationStatus.CONFIRMED, ReservationStatus.HELD]:
            reservation.status = ReservationStatus.CANCELLED
            return self.repository.save(reservation)
        
        raise ValueError(f"Cannot cancel reservation in status: {reservation.status}")
