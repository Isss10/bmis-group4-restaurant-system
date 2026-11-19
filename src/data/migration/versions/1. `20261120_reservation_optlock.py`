"""feat: alter reservations table: add version, split reservation_time, add unique constraint

Revision ID: 20261120_reservation_optlock
Revises: 97393cdd0b6c
Create Date: 2026-11-20

"""
from alembic import op
import sqlalchemy as sa


revision = '20261120_reservation_optlock'
down_revision = '97393cdd0b6c'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("reservations") as batch_op:
        batch_op.add_column(sa.Column("version", sa.Integer(), nullable=False, server_default="1"))
        batch_op.drop_column("reservation_time")
        batch_op.add_column(sa.Column("slot_date", sa.Date(), nullable=False))
        batch_op.add_column(sa.Column("slot_start", sa.Time(), nullable=False))
        batch_op.create_unique_constraint(
            "uq_reservations_table_slot",
            ["table_id", "slot_date", "slot_start"]
        )


def downgrade() -> None:
    with op.batch_alter_table("reservations") as batch_op:
        batch_op.drop_constraint("uq_reservations_table_slot", type_="unique")
        batch_op.drop_column("slot_start")
        batch_op.drop_column("slot_date")
        batch_op.drop_column("version")
        batch_op.add_column(sa.Column("reservation_time", sa.DateTime(), nullable=False))
