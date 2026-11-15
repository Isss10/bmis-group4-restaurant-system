from typing import Annotated
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession
from src.application.ordering.ordering_service import OrderingService
from src.data.database import get_db
from src.data.schema.order_schema import OrderCreateSchema, OrderSchema

router = APIRouter(prefix="/orders", tags=["orders"])

@router.post("/", response_model=OrderSchema)
async def create_order(
    request: Request,
    order_data: OrderCreateSchema,
    db: Annotated[AsyncSession, Depends(get_db)]
):
    try:
        service = OrderingService()
        return await service.submit_order(db, order_data)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


# TODO: Implement get_order_by_id method in OrderingService first
# @router.get("/{order_id}", response_model=OrderSchema)
# async def get_order(order_id: int, db: Annotated[AsyncSession, Depends(get_db)]):
#     service = OrderingService()
#     order = await service.get_order_by_id(db, order_id)
#     if not order:
#         raise HTTPException(status_code=404, detail="Order not found")
#     return order

# TODO: Implement list_all_orders method in OrderingService first
# @router.get("/", response_model=list[OrderSchema])
# async def list_orders(db: Annotated[AsyncSession, Depends(get_db)]):
#     service = OrderingService()
#     return await service.list_all_orders(db)
