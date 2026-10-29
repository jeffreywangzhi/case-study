from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class PdfParseResponse(BaseModel):
    text: str


class ExtractionRequest(BaseModel):
    text: str


# ---------------------------------------------------------------------------
# What the model returns (OpenAI Structured Outputs, strict JSON schema).
#
# The model only *transcribes*: every field is nullable so "not on the
# document" is a valid answer, and no field asks it to calculate. Net prices,
# totals and consistency checks are computed in code (app.services.quote_checks).
# No defaults: strict mode requires every property to be present.
# ---------------------------------------------------------------------------

LineType = Literal["item", "shipping", "fee", "discount", "alternative", "optional", "heading"]


class QuoteRegistrationId(BaseModel):
    label: str = Field(description="The label as printed, e.g. 'EIN', 'Tax ID', "
                       "'California Corp. No.', 'Seller's Permit', 'LLC No.'.")
    value: str = Field(description="The number exactly as printed.")


class QuoteVendor(BaseModel):
    name: str | None = Field(description="Legal name of the company that issued the quote "
                             "(letterhead, logo, sender line, footer with bank/tax details, "
                             "'Prepared by'). Prefer the legal entity (e.g. 'X, Inc.') over a "
                             "brand name when both are shown.")
    address: str | None
    registration_ids: list[QuoteRegistrationId] = Field(description=(
        "Every tax or registration number printed for the vendor, each with its printed label "
        "(tax IDs, corporation/LLC numbers, permits). Not bank details, not the recipient's "
        "customer number. Empty if none."
    ))


class QuoteRecipient(BaseModel):
    name: str | None = Field(description="Company the quote is addressed to ('Prepared for', "
                             "address window, 'Quote recipient', 'Bill to').")
    address: str | None


class QuoteLine(BaseModel):
    position: str | None = Field(description="Item/position number exactly as printed in the "
                                 "item column (e.g. '2', '1.1a', '(Alt.)'). Never a quantity.")
    line_type: LineType = Field(description=(
        "heading: a group title row with no quantity and no price. "
        "alternative: an either-or variant priced for comparison (marked 'Alternative', '(Alt.)', "
        "'instead of', 'as previous item but', or a unit price with no line total such as 'U.P.'). "
        "optional: an add-on not included in the quoted total. "
        "shipping: a shipping/freight/delivery row inside the items table. "
        "fee: another charge row inside the items table. "
        "discount: a document-level discount row. item: everything else that is purchased."
    ))
    description: str = Field(description="Short product/service name; not the full spec text.")
    quantity: float | None = Field(description="Value in the quantity column. null if none.")
    unit: str | None = Field(description="Unit as printed, e.g. 'ea.', 'sq ft', 'lump sum'.")
    list_unit_price: float | None = Field(description="Unit price as printed, before any discount.")
    discount_percent: float | None = Field(description="Line discount as a positive percent "
                                           "(-20.00% -> 20). null if none.")
    line_total: float | None = Field(description="Value in the line total column as printed. "
                                     "null if the column is empty.")


class QuoteTotalRow(BaseModel):
    kind: Literal["items_subtotal", "shipping", "fee", "tax", "grand_total", "other"] = Field(
        description=(
            "items_subtotal: goods subtotal before shipping and tax (e.g. 'Items subtotal (net)', "
            "'Subtotal', 'Net total'). shipping: shipping/freight. fee: another charge (e.g. "
            "recycling fee). tax: sales tax/VAT/GST. grand_total: the final amount. other: "
            "anything else (e.g. 'Carried forward', page subtotals)."
        )
    )
    label: str = Field(description="The row's label as printed.")
    amount: float


class QuoteExtraction(BaseModel):
    # Generated first on purpose: Structured Outputs fills fields in schema order, so the model
    # reads the letterhead/footer before it commits to who the vendor is (DECISIONS D33).
    issuer_evidence: str = Field(description=(
        "FIRST, transcribe exactly every line of the letterhead, the sender line above the "
        "address window, and the page footer(s), including small or light-gray print visible "
        "only in the page images. This is where the issuing company's legal name and "
        "tax/registration numbers are."
    ))
    title: str = Field(description="2-5 word summary of what is being purchased.")
    vendor: QuoteVendor
    recipient: QuoteRecipient
    department: str | None = Field(description="Only a department of the recipient that the "
                                   "document explicitly names (e.g. 'Attn: Purchasing'). "
                                   "Never a company name. null otherwise.")
    currency: str | None
    lines: list[QuoteLine] = Field(description="Every row of the items table, in document order.")
    totals: list[QuoteTotalRow] = Field(description="Every row of the totals section below the "
                                        "items table, in document order.")
    commodity_group_id: int | None


# ---------------------------------------------------------------------------
# API response (camelCase on the wire — what the frontend's extraction flow consumes)
# ---------------------------------------------------------------------------

class OrderLineData(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    position_description: str = Field(default="", alias="positionDescription")
    unit_price: float = Field(default=0, alias="unitPrice")
    amount: float = 0
    unit: str = ""
    total_price: float = Field(default=0, alias="totalPrice")
    line_type: LineType = Field(default="item", alias="lineType")


class ExtractedVendorData(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    title: str = ""
    vendor_name: str = Field(default="", alias="vendorName")
    vat_id: str = Field(default="", alias="vatId")
    department: str = ""
    # Only what is being bought (items, document-level discounts).
    order_lines: list[OrderLineData] = Field(default_factory=list, alias="orderLines")
    # Alternatives / optional items: shown to the user, not part of the request.
    excluded_lines: list[OrderLineData] = Field(default_factory=list, alias="excludedLines")
    # Cost breakdown on top of the lines: total = lines + shipping + fees + tax.
    shipping_amount: float = Field(default=0, alias="shippingAmount")
    fees_amount: float = Field(default=0, alias="feesAmount")
    tax_amount: float = Field(default=0, alias="taxAmount")
    total_cost: float = Field(default=0, alias="totalCost")
    commodity_group_id: int | None = Field(default=None, alias="commodityGroupId")
    commodity_group_name: str | None = Field(default=None, alias="commodityGroupName")


class ExtractionWarning(BaseModel):
    """A specific reason a person should double-check the extraction."""

    code: str
    field: str
    message: str


class ExtractionResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    success: bool
    data: ExtractedVendorData | None = None
    error: str | None = None
    missing_fields: list[str] | None = Field(default=None, alias="missingFields")
    warnings: list[ExtractionWarning] = Field(default_factory=list)
    # "verified": every consistency check passed; "needs_review": see warnings.
    status: Literal["verified", "needs_review"] | None = None
