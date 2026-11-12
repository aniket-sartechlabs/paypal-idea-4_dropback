"""add catalog and claim columns that development created directly from the models

Development databases are created with metadata.create_all, so these columns existed
locally but were never in a migration. Production (alembic upgrade head) needs them.

Revision ID: 20261112_0004
Revises: 20261112_0003
Create Date: 2026-11-12 17:00:00
"""
from alembic import op
import sqlalchemy as sa


revision = "20261112_0004"
down_revision = "20261112_0003"
branch_labels = None
depends_on = None

PRODUCT_COLUMNS = [
    sa.Column("competitor_name", sa.String(length=120), nullable=True),
    sa.Column("competitor_url", sa.String(length=500), nullable=True),
    sa.Column("weight_lbs", sa.Numeric(6, 2), nullable=True),
]
DECISION_COLUMNS = [
    sa.Column("customer_claim", sa.Boolean(), nullable=False, server_default=sa.false()),
    sa.Column("customer_notes", sa.Text(), nullable=False, server_default=""),
    sa.Column("ai_drafted_message", sa.Text(), nullable=False, server_default=""),
    sa.Column("merchant_message", sa.Text(), nullable=False, server_default=""),
    sa.Column("competitor_name", sa.String(length=120), nullable=True),
    sa.Column("competitor_price", sa.Numeric(10, 2), nullable=True),
]


def _missing(table: str, columns: list[sa.Column]) -> list[sa.Column]:
    present = {column["name"] for column in sa.inspect(op.get_bind()).get_columns(table)}
    return [column for column in columns if column.name not in present]


def upgrade() -> None:
    # Skip columns a database created by create_all already has.
    for table, columns in (("products", PRODUCT_COLUMNS), ("refund_decisions", DECISION_COLUMNS)):
        missing = _missing(table, columns)
        if missing:
            with op.batch_alter_table(table) as batch:
                for column in missing:
                    batch.add_column(column.copy())


def downgrade() -> None:
    with op.batch_alter_table("refund_decisions") as batch:
        for column in reversed(DECISION_COLUMNS):
            batch.drop_column(column.name)
    with op.batch_alter_table("products") as batch:
        for column in reversed(PRODUCT_COLUMNS):
            batch.drop_column(column.name)
