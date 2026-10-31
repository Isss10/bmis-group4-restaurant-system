class StaffService:
    def __init__(self, repository):
        self.repository = repository

    def get_reservations(self):
        """
        Return reservation list.
        """
        # 模拟数据
        return [{"id": 1, "status": "booked", "table_id": 5}]

    def update_reservation_status(self, reservation_id, status):
        """
        Update reservation status.
        """
        return {"reservation_id": reservation_id, "status": status, "message": "updated"}

    def get_orders(self):
        """
        Return order list.
        """
        return [{"id": 101, "items": ["pizza"], "status": "pending"}]

    def update_order_status(self, order_id, status):
        """
        Update order status.
        """
        return {"order_id": order_id, "status": status, "message": "updated"}
