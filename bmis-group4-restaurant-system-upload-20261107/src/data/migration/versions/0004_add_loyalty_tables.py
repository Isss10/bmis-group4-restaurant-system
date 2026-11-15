"""add points, tiers and coupon tables for the loyalty module

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-07
"""

from collections.abc import Sequence
from decimal import Decimal

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
    ]


def upgrade() -> None:
    op.create_table(
        "membership_tiers",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(length=32), nullable=False),
        sa.Column("min_qualifying_spend", sa.Numeric(12, 2), nullable=False),
        sa.Column("discount_rate", sa.Numeric(5, 4), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        *_timestamps(),
        sa.CheckConstraint(
            "min_qualifying_spend >= 0",
            name=op.f("ck_membership_tiers_tier_min_spend_non_negative"),
        ),
        sa.CheckConstraint(
            "discount_rate >= 0 AND discount_rate <= 1",
            name=op.f("ck_membership_tiers_tier_discount_rate_fraction"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_membership_tiers")),
        sa.UniqueConstraint("name", name=op.f("uq_membership_tiers_name")),
        mysql_engine="InnoDB",
    )
    op.create_index(
        "ix_membership_tiers_spend",
        "membership_tiers",
        ["min_qualifying_spend"],
        unique=False,
    )

    op.create_table(
        "loyalty_order_events",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("order_id", sa.String(length=128), nullable=False),
        sa.Column("user_id", sa.String(length=64), nullable=False),
        sa.Column("paid_amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("points_awarded", sa.Integer(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "paid_amount >= 0",
            name=op.f("ck_loyalty_order_events_order_event_paid_non_negative"),
        ),
        sa.CheckConstraint(
            "points_awarded >= 0",
            name=op.f("ck_loyalty_order_events_order_event_points_non_negative"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_loyalty_order_events")),
        sa.UniqueConstraint("order_id", name=op.f("uq_loyalty_order_events_order_id")),
        mysql_engine="InnoDB",
    )
    op.create_index(
        "ix_loyalty_order_events_user_id",
        "loyalty_order_events",
        ["user_id"],
        unique=False,
    )

    op.create_table(
        "points_ledger",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.String(length=64), nullable=False),
        sa.Column(
            "txn_type",
            sa.Enum("EARN", "REDEEM", "EXPIRE", "ADJUST", name="pointstxntype"),
            nullable=False,
        ),
        sa.Column("points", sa.Integer(), nullable=False),
        sa.Column("source_type", sa.String(length=32), nullable=False),
        sa.Column("source_id", sa.String(length=128), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.CheckConstraint("points <> 0", name=op.f("ck_points_ledger_points_non_zero")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_points_ledger")),
        sa.UniqueConstraint(
            "user_id",
            "source_type",
            "source_id",
            "txn_type",
            name="uq_points_event_source",
        ),
        mysql_engine="InnoDB",
    )
    op.create_index("ix_points_ledger_user_id", "points_ledger", ["user_id"], unique=False)
    op.create_index("ix_points_ledger_txn_type", "points_ledger", ["txn_type"], unique=False)
    op.create_index("ix_points_ledger_expires_at", "points_ledger", ["expires_at"], unique=False)
    op.create_index(
        "ix_points_user_created",
        "points_ledger",
        ["user_id", "created_at"],
        unique=False,
    )

    op.create_table(
        "points_allocations",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("spend_ledger_id", sa.Integer(), nullable=False),
        sa.Column("earn_ledger_id", sa.Integer(), nullable=False),
        sa.Column("points", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "points > 0", name=op.f("ck_points_allocations_allocation_points_positive")
        ),
        sa.ForeignKeyConstraint(
            ["earn_ledger_id"],
            ["points_ledger.id"],
            name=op.f("fk_points_allocations_earn_ledger_id_points_ledger"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["spend_ledger_id"],
            ["points_ledger.id"],
            name=op.f("fk_points_allocations_spend_ledger_id_points_ledger"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_points_allocations")),
        sa.UniqueConstraint(
            "spend_ledger_id",
            "earn_ledger_id",
            name="uq_points_allocation_pair",
        ),
        mysql_engine="InnoDB",
    )
    op.create_index(
        "ix_points_allocations_spend_ledger_id",
        "points_allocations",
        ["spend_ledger_id"],
        unique=False,
    )
    op.create_index(
        "ix_points_allocations_earn_ledger_id",
        "points_allocations",
        ["earn_ledger_id"],
        unique=False,
    )

    op.create_table(
        "coupons",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column(
            "discount_type",
            sa.Enum("PERCENT", "FIXED", name="coupondiscounttype"),
            nullable=False,
        ),
        sa.Column("discount_value", sa.Numeric(12, 4), nullable=False),
        sa.Column("min_spend", sa.Numeric(12, 2), nullable=False),
        sa.Column(
            "stacking",
            sa.Enum("EXCLUSIVE", "STACKABLE", name="couponstacking"),
            nullable=False,
        ),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("valid_until", sa.DateTime(timezone=True), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        *_timestamps(),
        sa.CheckConstraint("discount_value > 0", name=op.f("ck_coupons_coupon_value_positive")),
        sa.CheckConstraint("min_spend >= 0", name=op.f("ck_coupons_coupon_min_spend_non_negative")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_coupons")),
        sa.UniqueConstraint("code", name=op.f("uq_coupons_code")),
        mysql_engine="InnoDB",
    )
    op.create_index("ix_coupons_validity", "coupons", ["valid_from", "valid_until"], unique=False)

    op.create_table(
        "user_coupons",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.String(length=64), nullable=False),
        sa.Column("coupon_id", sa.Integer(), nullable=False),
        sa.Column(
            "status",
            sa.Enum("AVAILABLE", "USED", "EXPIRED", "CANCELLED", name="usercouponstatus"),
            nullable=False,
        ),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("order_id", sa.String(length=128), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(
            ["coupon_id"],
            ["coupons.id"],
            name=op.f("fk_user_coupons_coupon_id_coupons"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_user_coupons")),
        sa.UniqueConstraint("user_id", "coupon_id", name="uq_user_coupon_ownership"),
        mysql_engine="InnoDB",
    )
    op.create_index("ix_user_coupons_user_id", "user_coupons", ["user_id"], unique=False)
    op.create_index("ix_user_coupons_coupon_id", "user_coupons", ["coupon_id"], unique=False)
    op.create_index("ix_user_coupons_order_id", "user_coupons", ["order_id"], unique=False)
    op.create_index(
        "ix_user_coupons_user_status",
        "user_coupons",
        ["user_id", "status"],
        unique=False,
    )

    tier_table = sa.table(
        "membership_tiers",
        sa.column("name", sa.String),
        sa.column("min_qualifying_spend", sa.Numeric),
        sa.column("discount_rate", sa.Numeric),
        sa.column("is_active", sa.Boolean),
    )
    op.bulk_insert(
        tier_table,
        [
            {
                "name": "BRONZE",
                "min_qualifying_spend": Decimal("0.00"),
                "discount_rate": Decimal("0.0000"),
                "is_active": True,
            },
            {
                "name": "SILVER",
                "min_qualifying_spend": Decimal("500.00"),
                "discount_rate": Decimal("0.0200"),
                "is_active": True,
            },
            {
                "name": "GOLD",
                "min_qualifying_spend": Decimal("2000.00"),
                "discount_rate": Decimal("0.0500"),
                "is_active": True,
            },
            {
                "name": "PLATINUM",
                "min_qualifying_spend": Decimal("5000.00"),
                "discount_rate": Decimal("0.0800"),
                "is_active": True,
            },
        ],
    )


def downgrade() -> None:
    op.drop_index("ix_user_coupons_user_status", table_name="user_coupons")
    op.drop_index("ix_user_coupons_order_id", table_name="user_coupons")
    op.drop_index("ix_user_coupons_coupon_id", table_name="user_coupons")
    op.drop_index("ix_user_coupons_user_id", table_name="user_coupons")
    op.drop_table("user_coupons")

    op.drop_index("ix_coupons_validity", table_name="coupons")
    op.drop_table("coupons")

    op.drop_index("ix_points_allocations_earn_ledger_id", table_name="points_allocations")
    op.drop_index("ix_points_allocations_spend_ledger_id", table_name="points_allocations")
    op.drop_table("points_allocations")

    op.drop_index("ix_points_user_created", table_name="points_ledger")
    op.drop_index("ix_points_ledger_expires_at", table_name="points_ledger")
    op.drop_index("ix_points_ledger_txn_type", table_name="points_ledger")
    op.drop_index("ix_points_ledger_user_id", table_name="points_ledger")
    op.drop_table("points_ledger")

    op.drop_index("ix_loyalty_order_events_user_id", table_name="loyalty_order_events")
    op.drop_table("loyalty_order_events")

    op.drop_index("ix_membership_tiers_spend", table_name="membership_tiers")
    op.drop_table("membership_tiers")
