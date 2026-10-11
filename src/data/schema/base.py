# src/data/schema/base.py
from sqlalchemy.orm import DeclarativeBase

class Base(DeclarativeBase):
    """SQLAlchemy declarative base for all ORM models."""
    pass