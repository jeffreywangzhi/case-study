"""auto approval

Revision ID: 0009
Revises: 0008
Create Date: 2026-10-29

Adds ``procurement_requests.approval_method``: ``manual`` when a buyer or admin
decided, ``auto`` when the organization's auto-approval limit approved it, NULL
while pending. Requests already decided before this migration were decided by
a person, so they are backfilled as ``manual``.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "procurement_requests", sa.Column("approval_method", sa.String(), nullable=True)
    )
    op.create_check_constraint(
        "ck_procurement_request_approval_method",
        "procurement_requests",
        "approval_method IS NULL OR approval_method IN ('manual', 'auto')",
    )
    op.execute(
        "UPDATE procurement_requests SET approval_method = 'manual' "
        "WHERE approval_status IN ('approved', 'rejected')"
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_procurement_request_approval_method", "procurement_requests", type_="check"
    )
    op.drop_column("procurement_requests", "approval_method")
