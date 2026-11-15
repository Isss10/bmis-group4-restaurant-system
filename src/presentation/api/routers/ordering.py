from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from src.data.database import get_db
from src.application.ordering.ordering_service import OrderingService
from src.data.schema.order_schema import DishSchema, OrderCreateSchema, OrderSchema

# create router instance
router = APIRouter(tags=["Orders"])

# get dish menu, support category filter
@router.get("/menu", response_model=list[DishSchema])
async def get_menu(
    category: str | None = Query(None, description="Filter dishes by category"),
    db: AsyncSession = Depends(get_db)
):
    return await OrderingService.browse_menu(db, category)

# create new order
@router.post("/", response_model=OrderSchema)
async def create_order(
    order_data: OrderCreateSchema,
    db: AsyncSession = Depends(get_db)
):
    try:
        return await OrderingService.submit_order(db, order_data)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))