"""catalog matching

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-29

- ``text_embeddings``: cache of embedding vectors keyed by model + text hash, so
  catalog descriptions are embedded once (JSON on both Postgres and SQLite; at
  ~400 distinct descriptions per tenant, cosine similarity in Python is fast).
- ``order_lines.article_id`` / ``catalog_unit_price``: which catalog agreement a
  line uses and the negotiated price at the time, so agreement use is measurable.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "text_embeddings",
        sa.Column("key", sa.String(64), primary_key=True),
        sa.Column("model", sa.String(), nullable=False),
        sa.Column("embedding", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.add_column(
        "order_lines",
        sa.Column(
            "article_id",
            sa.Uuid(),
            sa.ForeignKey("articles.id", name="fk_order_lines_article_id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index("ix_order_lines_article_id", "order_lines", ["article_id"])
    op.add_column(
        "order_lines", sa.Column("catalog_unit_price", sa.Numeric(12, 2), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("order_lines", "catalog_unit_price")
    op.drop_index("ix_order_lines_article_id", table_name="order_lines")
    op.drop_constraint("fk_order_lines_article_id", "order_lines", type_="foreignkey")
    op.drop_column("order_lines", "article_id")
    op.drop_table("text_embeddings")
