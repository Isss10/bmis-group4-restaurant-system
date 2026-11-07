"""add review moderation and rating-stats tables

Revision ID: 0001
Revises:
Create Date: 2026-10-12

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "reviews",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("customer_id", sa.Integer(), nullable=False),
        sa.Column("dish_id", sa.Integer(), nullable=False),
        sa.Column("order_id", sa.Integer(), nullable=False),
        sa.Column("rating", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_reviews")),
    )
    op.create_index(op.f("ix_reviews_customer_id"), "reviews", ["customer_id"])
    op.create_index(op.f("ix_reviews_dish_id"), "reviews", ["dish_id"])
    op.create_index(op.f("ix_reviews_order_id"), "reviews", ["order_id"])

    op.create_table(
        "review_moderation",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("review_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("moderated_by", sa.Integer(), nullable=True),
        sa.Column("moderated_at", sa.DateTime(), nullable=True),
        sa.Column("reason", sa.String(length=200), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["review_id"],
            ["reviews.id"],
            name=op.f("fk_review_moderation_review_id_reviews"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_review_moderation")),
        sa.UniqueConstraint("review_id", name=op.f("uq_review_moderation_review_id")),
    )

    op.create_table(
        "dish_rating_stats",
        sa.Column("dish_id", sa.Integer(), nullable=False),
        sa.Column("review_count", sa.Integer(), nullable=False),
        sa.Column("bayesian_score", sa.Float(), nullable=False),
        sa.Column("global_mean", sa.Float(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("dish_id", name=op.f("pk_dish_rating_stats")),
    )


def downgrade() -> None:
    op.drop_table("dish_rating_stats")
    op.drop_table("review_moderation")
    op.drop_index(op.f("ix_reviews_order_id"), table_name="reviews")
    op.drop_index(op.f("ix_reviews_dish_id"), table_name="reviews")
    op.drop_index(op.f("ix_reviews_customer_id"), table_name="reviews")
    op.drop_table("reviews")
