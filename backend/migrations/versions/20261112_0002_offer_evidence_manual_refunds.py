"""keep offer evidence on price drops; allow manual refunds without a decision

Revision ID: 20261112_0002
Revises: 20261110_0001
Create Date: 2026-11-12 10:00:00
"""
from alembic import op
import sqlalchemy as sa


revision = "20261112_0002"
down_revision = "20261110_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("price_drops") as batch:
        batch.add_column(sa.Column("offer_merchant", sa.String(length=120), nullable=True))
        batch.add_column(sa.Column("offer_url", sa.String(length=500), nullable=True))
    with op.batch_alter_table("refunds") as batch:
        batch.alter_column("decision_id", existing_type=sa.String(length=36), nullable=True)


def downgrade() -> None:
    with op.batch_alter_table("refunds") as batch:
        batch.alter_column("decision_id", existing_type=sa.String(length=36), nullable=False)
    with op.batch_alter_table("price_drops") as batch:
        batch.drop_column("offer_url")
        batch.drop_column("offer_merchant")
