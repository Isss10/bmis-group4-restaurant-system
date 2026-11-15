from fastapi import APIRouter, Depends, Query, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from src.common.envelope import Envelope
from src.common.middleware import REQUEST_ID_ATTR
from src.data.database import get_db
from src.application.ordering.ordering_service import OrderingService
from src.data.schema.order_schema import DishSchema, OrderCreateSchema, OrderSchema

# Create router instance for ordering module, base prefix matches project API contract
router = APIRouter(tags=["Orders Module"], prefix="/api/v1/orders")


# GET /api/v1/orders/menu
# Browse dish menu, support filtering dishes by category query parameter
@router.get("/menu")
async def get_menu(
    request: Request,
    category: str | None = Query(None, description="Filter dishes by category"),
    db: AsyncSession = Depends(get_db)
):
    dish_list = await OrderingService.browse_menu(db, category)
    # Return unified response envelope defined by project specification
    return Envelope(
        code=0,
        message="ok",
        data=dish_list,
        request_id=getattr(request.state, REQUEST_ID_ATTR, None)
    )


# POST /api/v1/orders
# Submit and create a new customer food order
@router.post("/")
async def create_order(
    request: Request,
    order_data: OrderCreateSchema,
    db: AsyncSession = Depends(get_db)
):
    try:
        order_result = await OrderingService.submit_order(db, order_data)
        # Return unified response envelope defined by project specification
        return Envelope(
            code=0,
            message="ok",
            data=order_result,
            request_id=getattr(request.state, REQUEST_ID_ATTR, None)
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))