"""merchant onboarding: workspace owner, connected PayPal app, margin and retailer policy

Revision ID: 20261112_0003
Revises: 20261112_0002
Create Date: 2026-11-12 16:00:00
"""
from alembic import op
import sqlalchemy as sa


revision = "20261112_0003"
down_revision = "20261112_0002"
branch_labels = None
depends_on = None

COLUMNS = [
    sa.Column("gross_margin_percentage", sa.Numeric(7, 3), nullable=False, server_default="30"),
    sa.Column("allowed_retailers", sa.Text(), nullable=False, server_default=""),
    sa.Column("store_url", sa.String(length=255), nullable=False, server_default=""),
    sa.Column("owner_email", sa.String(length=254), nullable=False, server_default=""),
    sa.Column("owner_password_hash", sa.String(length=255), nullable=False, server_default=""),
    sa.Column("paypal_client_id", sa.String(length=255), nullable=False, server_default=""),
    sa.Column("paypal_client_secret_enc", sa.Text(), nullable=False, server_default=""),
    sa.Column("paypal_webhook_id", sa.String(length=64), nullable=False, server_default=""),
    sa.Column("paypal_connected_at", sa.DateTime(), nullable=True),
    sa.Column("onboarding_completed_at", sa.DateTime(), nullable=True),
]


def upgrade() -> None:
    with op.batch_alter_table("merchant_settings") as batch:
        for column in COLUMNS:
            batch.add_column(column.copy())


def downgrade() -> None:
    with op.batch_alter_table("merchant_settings") as batch:
        for column in reversed(COLUMNS):
            batch.drop_column(column.name)
