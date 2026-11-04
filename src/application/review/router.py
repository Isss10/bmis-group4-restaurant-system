from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from src.application.review.exceptions import DishNotInOrderError
from src.application.review.schemas import ReviewCreate, ReviewResponse
from src.application.review.service import submit_review
from src.data.database import get_db
from src.data.schema.review import Review

router = APIRouter()


@router.post("/", response_model=ReviewResponse, status_code=status.HTTP_201_CREATED)
def create_review(payload: ReviewCreate, db: Annotated[Session, Depends(get_db)]) -> Review:
    try:
        return submit_review(db, payload)
    except DishNotInOrderError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        ) from e
