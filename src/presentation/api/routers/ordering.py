from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.ordering.ordering_service import OrderingService
from src.common.envelope import Envelope
from src.data.database import get_db
from src.data.schema.order_schema import DishSchema, OrderCreateSchema, OrderSchema

router = APIRouter()


@router.get("/menu", response_model=Envelope[list[DishSchema]])
async def get_menu(db: Annotated[AsyncSession, Depends(get_db)], category: str | None = None):
    service = OrderingService(db)
    dish_list = await service.get_menu(category=category)
    return Envelope(code=0, message="ok", data=dish_list, request_id=None)


@router.post("/", response_model=Envelope[OrderSchema])
async def create_order(
    request: Request, order_data: OrderCreateSchema, db: Annotated[AsyncSession, Depends(get_db)]
):
    try:
        service = OrderingService(db)
        order = await service.submit_order(order_data)
        return Envelope(
            code=0, message="ok", data=order, request_id=getattr(request.state, "request_id", None)
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.get("/{order_id}", response_model=Envelope[OrderSchema])
async def get_order(request: Request, order_id: int, db: Annotated[AsyncSession, Depends(get_db)]):
    service = OrderingService(db)
    order = await service.get_order_by_id(order_id)
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    return Envelope(
        code=0, message="ok", data=order, request_id=getattr(request.state, "request_id", None)
    )


@router.get("/", response_model=Envelope[list[OrderSchema]])
async def list_orders(request: Request, db: Annotated[AsyncSession, Depends(get_db)]):
    service = OrderingService(db)
    order_list = await service.list_all_orders()
    return Envelope(
        code=0, message="ok", data=order_list, request_id=getattr(request.state, "request_id", None)
    )
