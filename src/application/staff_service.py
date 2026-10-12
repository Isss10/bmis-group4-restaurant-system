class StaffService:
    def __init__(self, repository):
        self.repository = repository

    def get_reservations(self):
        """
        Return reservation list.
        """
        pass

    def update_reservation_status(self, reservation_id, status):
        """
        Update reservation status.
        """
        pass

    def get_orders(self):
        """
        Return order list.
        """
        pass

    def update_order_status(self, order_id, status):
        """
        Update order status.
        """
        pass
