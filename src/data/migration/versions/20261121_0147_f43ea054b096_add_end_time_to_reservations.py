"""add end_time to reservations

Revision ID: f43ea054b096
Revises: 0004
Create Date: 2026-11-21 01:47:54.439975+00:00
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# Alembic revision identifiers. Do not change these by hand.
revision: str = 'f43ea054b096'
down_revision: Union[str, None] = '0004'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Apply the schema change."""
    op.add_column('reservations', sa.Column('end_time', sa.DateTime(), nullable=False))
    op.add_column('reservations', sa.Column('expires_at', sa.DateTime(), nullable=True))


def downgrade() -> None:
    """Reverse the schema change."""
    op.drop_column('reservations', 'expires_at')
