import uuid
from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ArticleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    article_number: str
    supplier_id: uuid.UUID
    supplier_name: str | None = None
    description: str
    unit_price: Decimal
    currency: str
    unit: str
    quantity: Decimal
    created_at: datetime


class ArticlePage(BaseModel):
    """A page of articles plus the totals the UI needs to render pagination."""

    items: list[ArticleOut]
    total: int
    limit: int
    offset: int


# ---------------------------------------------------------------------------
# Catalog suggestions (Task 2): which negotiated agreements fit a request line
# ---------------------------------------------------------------------------

# Decided in code from the listed differences: none -> equivalent, only minor -> close,
# any major -> alternative.
MatchQuality = Literal["equivalent", "close", "alternative"]


class CatalogMatchLine(BaseModel):
    """One request line to find catalog agreements for (typed or extracted)."""

    description: str = Field(min_length=1)
    unit: str = ""
    unit_price: float | None = None  # the quoted price, to compare against
    quantity: float = 1


class CatalogMatchRequest(BaseModel):
    lines: list[CatalogMatchLine] = Field(max_length=50)
    vendor_name: str | None = None
    vat_id: str | None = None


class CatalogAgreement(BaseModel):
    """A negotiated price for an item with one supplier."""

    article_id: uuid.UUID
    article_number: str
    supplier_id: uuid.UUID
    supplier_name: str
    supplier_vat_id: str | None
    unit_price: Decimal
    unit: str
    currency: str
    # Meaning unconfirmed (minimum order? pack size? contract volume?); shown as information.
    quantity: Decimal
    # Compared with the line's quoted price only when the units match.
    same_unit: bool
    saving_per_unit: Decimal | None  # quoted − negotiated; negative = the quote is cheaper
    saving_total: Decimal | None


class CatalogDifference(BaseModel):
    aspect: str  # "platform"
    detail: str  # "Windows vs macOS"
    impact: Literal["minor", "major"]


class CatalogSuggestion(BaseModel):
    """A catalog item that fits the line, with every supplier's agreement (cheapest first)."""

    item: str
    quality: MatchQuality
    reason: str  # the differences in one line, major first
    differences: list[CatalogDifference] = Field(default_factory=list)  # major first
    agreements: list[CatalogAgreement]


class CatalogLineMatch(BaseModel):
    index: int
    suggestions: list[CatalogSuggestion]


class KnownSupplier(BaseModel):
    id: uuid.UUID
    name: str
    vat_id: str | None


class CatalogMatchResponse(BaseModel):
    lines: list[CatalogLineMatch]
    # The quote's vendor, if it's already in the organization's supplier master.
    known_supplier: KnownSupplier | None = None
    # False when the AI check was unavailable and suggestions are keyword matches only.
    verified: bool
