from typing import Annotated

from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.orm import Session

from src.application.review.exceptions import DishNotInOrderError
from src.application.review.schemas import ReviewCreate, ReviewResponse
from src.application.review.service import submit_review
from src.common.envelope import Envelope, success
from src.common.errors import validation_failed
from src.common.middleware import REQUEST_ID_ATTR
from src.data.database import get_db

# HTTP surface for the ratings & reviews module (Objective c). Lives in the
# presentation tier because ARCHITECTURE.md §3 forbids `fastapi` imports in the
# application tier: the service raises domain exceptions, this file translates
# them into the frozen 5-digit codes. Mounted by convention from
# `src.presentation.api.routers.review` at the frozen base path
# `/api/v1/reviews` (see `_MODULE_ROUTERS` in main.py and the registration
# tests). Moved here from `src/application/review/router.py`, where the old
# loader could no longer find it after the router-location fix, which would
# have silently unmounted the review API.
router = APIRouter(tags=["review"])


@router.post(
    "/",
    response_model=Envelope[ReviewResponse],
    status_code=status.HTTP_201_CREATED,
    summary="Submit an order-verified review",
)
def create_review(
    request: Request,
    payload: ReviewCreate,
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    """Create a review; it enters the moderation queue as PENDING (FR-REV-05)."""
    try:
        review = submit_review(db, payload)
    except DishNotInOrderError as exc:
        # 10001 / 422: the payload references a dish the customer did not
        # order, which fails the order-verification rule (FR-REV-01). The
        # domain exception is translated here, at the tier boundary — the
        # service never imports fastapi.
        raise validation_failed(errors=[{"field": "dish_id", "detail": str(exc)}]) from exc
    return success(
        ReviewResponse.model_validate(review),
        request_id=getattr(request.state, REQUEST_ID_ATTR, None),
    )
