from fastapi import APIRouter

router = APIRouter(prefix="/staff", tags=["Staff"])


@router.get("/reservations")
def get_reservations()-> dict:
    """
    Get all reservations for staff.
    """
    return {"message": "Reservation list API"}


@router.patch("/reservations/{reservation_id}")
def update_reservation_status(reservation_id: int)-> dict:
    """
    Update reservation status.
    """
    return {"reservation_id": reservation_id, "message": "Update reservation status API"}


@router.get("/orders")
def get_orders()-> dict:
    """
    Get customer orders.
    """
    return {"message": "Order list API"}


@router.patch("/orders/{order_id}")
def update_order_status(order_id: int):
    """
    Update order status.
    """
    return {"order_id": order_id, "message": "Update order status API"}
