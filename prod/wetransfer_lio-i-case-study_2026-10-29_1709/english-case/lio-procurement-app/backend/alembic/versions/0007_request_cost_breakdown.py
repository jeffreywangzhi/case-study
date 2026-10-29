"""request cost breakdown

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-29

Stores what a quote charges on top of its items separately from the order
lines, so that ``total_cost = sum(order line totals) + shipping_amount +
fees_amount + tax_amount``. Order lines are only what is being bought (see
DECISIONS.md D8/D9). Nullable: existing requests have no recorded breakdown.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_COLUMNS = ("shipping_amount", "fees_amount", "tax_amount")


def upgrade() -> None:
    for column in _COLUMNS:
        op.add_column(
            "procurement_requests", sa.Column(column, sa.Numeric(12, 2), nullable=True)
        )


def downgrade() -> None:
    for column in reversed(_COLUMNS):
        op.drop_column("procurement_requests", column)
