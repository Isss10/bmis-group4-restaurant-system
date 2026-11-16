from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.encoders import jsonable_encoder
from slowapi import Limiter
from slowapi.util import get_remote_address
from sqlalchemy.orm import Session

from src.application.review.exceptions import DishNotInOrderError
from src.application.review.schemas import ReviewCreate
from src.application.review.service import submit_review
from src.common.config import get_settings
from src.common.security import Role, get_current_token
from src.data.database import get_db
from src.data.schema.review import DishRatingStats

router = APIRouter()
settings = get_settings()

# Disable rate limiting in testing environment
limiter = Limiter(
    key_func=get_remote_address,
    enabled=settings.rate_limit_enabled and settings.environment != "testing",
)
review_rate_limit = settings.rate_limit_review


@router.post("/", status_code=status.HTTP_201_CREATED)
@limiter.limit(review_rate_limit)
def create_review(
    request: Request,
    payload: ReviewCreate,
    db: Annotated[Session, Depends(get_db)],
    token_payload: Annotated[Any, Depends(get_current_token)],
) -> dict[str, Any]:
    # Extract user role and subject (user ID) from the verified token
    user_role = token_payload.role
    user_id_str = token_payload.sub
    user_id = int(user_id_str) if user_id_str else None

    # Reject if the user is not a customer
    if user_role != Role.CUSTOMER:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only customers can review",
        )
    # Reject if the customer tries to spoof another customer's ID
    if user_id != payload.customer_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot spoof identity",
        )

    try:
        review = submit_review(db, payload)
        # Return the standard envelope format expected by the API contract
        return {
            "code": 0,
            "message": "Success",
            "data": jsonable_encoder(review),
            "request_id": getattr(request.state, "request_id", ""),
        }
    except DishNotInOrderError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        ) from e


@router.get("/dishes/ranking")
def get_dish_bayesian_ranking(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    limit: int = 10,
) -> dict[str, Any]:
    """Get dish ranking sorted by Bayesian average score descending."""
    stats = (
        db.query(DishRatingStats).order_by(DishRatingStats.bayesian_score.desc()).limit(limit).all()
    )
    return {
        "code": 0,
        "message": "Success",
        "data": jsonable_encoder(stats),
        "request_id": getattr(request.state, "request_id", ""),
    }
