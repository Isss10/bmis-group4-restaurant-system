from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from src.application.review.exceptions import DishNotInOrderError
from src.application.review.schemas import (
    DishRankingResponse,
    ReviewCreate,
    ReviewResponse,
)
from src.application.review.service import submit_review
from src.common.envelope import Envelope, success
from src.common.errors import permission_denied
from src.common.middleware import REQUEST_ID_ATTR
from src.common.security import Role, TokenPayload, require_roles
from src.data.database import get_db
from src.data.schema.review import DishRatingStats, Review

router = APIRouter()
Customer = Annotated[TokenPayload, Depends(require_roles(Role.CUSTOMER))]


@router.post("/", response_model=Envelope[ReviewResponse], status_code=status.HTTP_201_CREATED)
def create_review(
    payload: ReviewCreate,
    request: Request,
    identity: Customer,
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    if str(payload.customer_id) != identity.sub:
        raise permission_denied()
    try:
        review: Review = submit_review(db, payload)
        return success(review, request_id=getattr(request.state, REQUEST_ID_ATTR, None))
    except DishNotInOrderError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        ) from e


@router.get("/dishes/ranking", response_model=Envelope[list[DishRankingResponse]])
def get_dish_bayesian_ranking(
    request: Request, db: Annotated[Session, Depends(get_db)], limit: int = 10
) -> dict[str, Any]:
    """Get dish ranking sorted by Bayesian average score descending."""
    rankings = (
        db.query(DishRatingStats).order_by(DishRatingStats.bayesian_score.desc()).limit(limit).all()
    )
    return success(rankings, request_id=getattr(request.state, REQUEST_ID_ATTR, None))
