from sqlalchemy import JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, CreatedAtMixin


class TextEmbedding(Base, CreatedAtMixin):
    """Cache of embedding vectors, keyed by sha256(model + text).

    Catalog descriptions are embedded once and reused across requests; the key
    carries no tenant data, and only the vector is stored (not the text).
    """

    __tablename__ = "text_embeddings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    model: Mapped[str] = mapped_column(String, nullable=False)
    embedding: Mapped[list[float]] = mapped_column(JSON, nullable=False)
