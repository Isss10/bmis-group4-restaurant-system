from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from src.application.review.schemas import ModerationListResponse, ModerationUpdateRequest
from src.application.review.service import get_pending_moderations, update_moderation_status
from src.data.database import get_db
from src.data.schema.review import ReviewModeration

router = APIRouter(prefix="/admin/reviews", tags=["Admin Reviews"])


# Temporary auth dependency
def get_current_staff_id() -> int:
    return 1  # Mock Staff ID


@router.get("/moderation", response_model=list[ModerationListResponse])
def list_pending_moderations(
    db: Annotated[Session, Depends(get_db)],
    skip: int = 0,
    limit: int = 50,
) -> list[ReviewModeration]:
    return get_pending_moderations(db, skip, limit)


@router.patch("/{review_id}", response_model=ModerationListResponse)
def moderate_review(
    review_id: int,
    payload: ModerationUpdateRequest,
    db: Annotated[Session, Depends(get_db)],
    staff_id: Annotated[int, Depends(get_current_staff_id)],
) -> ReviewModeration:
    moderation = update_moderation_status(
        db, review_id, payload.status, staff_id, payload.reason
    )
    if not moderation:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Review not found")
    return moderation
