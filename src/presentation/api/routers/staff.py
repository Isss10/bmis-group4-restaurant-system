from fastapi import APIRouter, Depends

router = APIRouter(tags=["Staff"])

try:
    from src.common.response import success
except ImportError:
    def success(data=None, message="Success"):
        return {"code": 200, "message": message, "data": data}

router = APIRouter(
    tags=["Staff"])

def require_staff_roles():
    return {"role": "waiter"}#等待会员模块完善

@router.get("/staff/reservations")
def get_reservations(current_user: dict = Depends(require_staff_roles)) -> dict:
    """
    Get all reservations for staff.
    """
    #模拟数据:
    mock_data = [{"id": 1, "status": "confirmed", "time": "18:00"}]
    #使用 success() 封包
    return success(data=mock_data, message="Reservation list retrieved")


@router.patch("/staff/reservations/{reservation_id}")
def update_reservation_status(
    reservation_id: int,
    current_user: dict = Depends(require_staff_roles)
) -> dict:
    """
    Update reservation status.
    """
    mock_data = {"reservation_id": reservation_id, "status": "updated"}
    return success(data=mock_data, message="Reservation status updated")


@router.get("/staff/orders")
def get_orders(current_user: dict = Depends(require_staff_roles)) -> dict:
    """
    Get customer orders.
    """
    mock_data = [{"id": 101, "dish": "Pizza", "status": "preparing"}]
    return success(data=mock_data, message="Order list retrieved")


@router.patch("/staff/orders/{order_id}")
def update_order_status(
    order_id: int,
    current_user: dict = Depends(require_staff_roles)
) -> dict:
    """
    Update order status.
    """
    mock_data = {"order_id": order_id, "status": "completed"}
    return success(data=mock_data, message="Order status updated")
