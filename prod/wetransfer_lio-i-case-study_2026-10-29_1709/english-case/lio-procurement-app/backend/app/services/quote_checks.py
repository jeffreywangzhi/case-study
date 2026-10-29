"""Deterministic post-processing of a model's quote transcription. No LLM here.

The model transcribes what is printed; this module decides what it means:
which rows become order lines, the net unit price, the shipping/fees/tax
breakdown, and whether the numbers are consistent with the quote's own
subtotals (total = order lines + shipping + fees + tax). Every failed check
becomes a specific warning instead of a silent "success".
"""
import re
from decimal import ROUND_HALF_UP, Decimal

from app.schemas.extraction import (
    ExtractedVendorData,
    ExtractionWarning,
    OrderLineData,
    QuoteExtraction,
    QuoteLine,
)

CENT = Decimal("0.01")
# Printed figures are rounded per line; allow a couple of cents of drift.
MONEY_TOLERANCE = Decimal("0.02")

# Order lines are only what is being bought; shipping and fees go in the cost breakdown.
ORDER_LINE_TYPES = {"item", "discount"}
CHARGE_LINE_TYPES = {"shipping", "fee"}
EXCLUDED_LINE_TYPES = {"alternative", "optional"}

# Warning codes worth one self-correction attempt by the model.
RETRYABLE_CODES = {
    "line_arithmetic",
    "subtotal_mismatch",
    "total_mismatch",
    "vendor_is_recipient",
    "vendor_missing",
}

TAX_LABEL = re.compile(r"\b(tax|vat|gst|hst)\b", re.IGNORECASE)
# Printed markers for either-or variants and add-ons (QT-4120 "(Alt.)", Hollis "Alternative to
# the preceding item", headings like "Alternative: vertical logo").
ALTERNATIVE_CUE = re.compile(r"\balternative\b|\(alt\.?\)|^alt\.?$", re.IGNORECASE)
OPTIONAL_CUE = re.compile(r"\boptional\b", re.IGNORECASE)

_COMPANY_SUFFIXES = re.compile(
    r"\b(inc|llc|ltd|corp|corporation|co|company|gmbh|ag|lp|plc|group|holdings)\b"
)


def _dec(value: float | None) -> Decimal | None:
    return None if value is None else Decimal(str(value))


def _money(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def _fmt(value: Decimal) -> str:
    return f"${value:,.2f}"


def _num(value: Decimal) -> str:
    """Plain number without trailing zeros: Decimal('20.0') -> '20', Decimal('13.78') -> '13.78'."""
    return f"{value.normalize():f}"


def normalize_company(name: str | None) -> str:
    """Lowercase, drop punctuation and legal suffixes: 'Lio Technologies, Inc.' -> 'lio technologies'."""
    cleaned = re.sub(r"[^a-z0-9 ]", " ", (name or "").lower())
    cleaned = _COMPANY_SUFFIXES.sub(" ", cleaned)
    return " ".join(cleaned.split())


def same_company(a: str | None, b: str | None) -> bool:
    left, right = normalize_company(a), normalize_company(b)
    if not left or not right:
        return False
    return left == right or left in right or right in left


def normalize_tax_id(tax_id: str | None) -> str:
    """US EINs are 9 digits printed as XX-XXXXXXX; '94 1985704' -> '94-1985704'."""
    raw = (tax_id or "").strip()
    digits = re.sub(r"\D", "", raw)
    if len(digits) == 9:
        return f"{digits[:2]}-{digits[2:]}"
    return raw


def apply_printed_cues(lines: list[QuoteLine]) -> list[QuoteLine]:
    """Reclassify items the document itself marks as alternative/optional (DECISIONS D10/D11).

    A row is excluded if its position or description carries a marker, or if it sits
    under an "Alternative..."/"Optional..." heading (until the next heading). The
    subtotal check remains the safety net if a cue ever misfires.
    """
    section: str | None = None
    result = []
    for line in lines:
        # A row with no quantity and no price is a heading, whatever the model labelled it.
        priceless = (line.quantity is None and line.list_unit_price is None
                     and line.line_total is None)
        if line.line_type == "heading" or priceless:
            if line.line_type != "heading":
                line = line.model_copy(update={"line_type": "heading"})
            text = line.description.strip()
            section = ("alternative" if ALTERNATIVE_CUE.match(text)
                       else "optional" if OPTIONAL_CUE.match(text) else None)
            result.append(line)
            continue
        kind = line.line_type
        if kind == "item":
            markers = f"{line.position or ''} {line.description}"
            if ALTERNATIVE_CUE.search(markers):
                kind = "alternative"
            elif OPTIONAL_CUE.search(markers):
                kind = "optional"
            elif section:
                kind = section
        result.append(line if kind == line.line_type else line.model_copy(update={"line_type": kind}))
    return result


def _totals_kind(kind: str, label: str) -> str:
    """Trust the printed label over the model's kind for tax: 'Sales tax 8.625%' is never a fee."""
    if kind in ("shipping", "fee", "other") and TAX_LABEL.search(label):
        return "tax"
    return kind


def _subtotal_hint(items_sum: Decimal, subtotal: Decimal, item_lines: list[OrderLineData],
                   excluded_lines: list[OrderLineData]) -> str:
    """Name the single line that explains the gap, if there is one."""
    for line in item_lines:
        if abs(items_sum - Decimal(str(line.total_price)) - subtotal) <= MONEY_TOLERANCE:
            return (f" Without '{line.position_description}' ({_fmt(Decimal(str(line.total_price)))})"
                    " the items match the subtotal; it may be an alternative or optional item.")
    for line in excluded_lines:
        if abs(items_sum + Decimal(str(line.total_price)) - subtotal) <= MONEY_TOLERANCE:
            return (f" Including '{line.position_description}' "
                    f"({_fmt(Decimal(str(line.total_price)))}) would match the subtotal; it may "
                    "not be an alternative.")
    return " A line may be missing, duplicated, or an alternative."


def _order_line(line: QuoteLine, field: str, warnings: list[ExtractionWarning]) -> OrderLineData:
    """Turn a transcribed row into a line with a net unit price (DECISIONS D7)."""
    quantity = _dec(line.quantity) or Decimal(1)  # lump sums print no quantity
    list_price = _dec(line.list_unit_price)
    discount = _dec(line.discount_percent) or Decimal(0)
    printed_total = _dec(line.line_total)

    expected = None
    if list_price is not None:
        expected = _money(quantity * list_price * (1 - discount / 100))

    if printed_total is not None:
        total = printed_total  # what the vendor actually charges is the source of truth
        if expected is not None and abs(expected - total) > MONEY_TOLERANCE:
            discount_text = f" at -{_num(discount)}%" if discount else ""
            warnings.append(ExtractionWarning(
                code="line_arithmetic",
                field=field,
                message=(f"{line.description}: {_num(quantity)} x {_fmt(list_price)}{discount_text} "
                         f"= {_fmt(expected)}, but the line total is {_fmt(total)}."),
            ))
    elif expected is not None:
        total = expected
    else:
        total = Decimal(0)
        warnings.append(ExtractionWarning(
            code="line_price_missing", field=field,
            message=f"{line.description}: no price found for this line.",
        ))

    description = line.description.strip()
    if discount and list_price is not None:
        description += f" (list {_fmt(list_price)}, -{_num(discount)}%)"

    return OrderLineData(
        position_description=description,
        unit_price=float(_money(total / quantity)) if quantity else float(total),
        amount=float(quantity),
        unit=(line.unit or "").strip(),
        total_price=float(total),
        line_type=line.line_type,
    )


def build_extraction(
    quote: QuoteExtraction,
    *,
    organization_names: list[str] | tuple[str, ...] = (),
    requester_department: str | None = None,
) -> tuple[ExtractedVendorData, list[ExtractionWarning]]:
    """Map the transcription to the request shape and run every consistency check."""
    warnings: list[ExtractionWarning] = []

    # --- totals section: classify rows; a row labelled as tax is tax ---------
    totals = [(_totals_kind(row.kind, row.label), row) for row in quote.totals]
    charges = [row for kind, row in totals if kind in ("shipping", "fee")]
    tax = sum((Decimal(str(row.amount)) for kind, row in totals if kind == "tax"), Decimal(0))
    subtotals = [Decimal(str(row.amount)) for kind, row in totals if kind == "items_subtotal"]
    grand_totals = [Decimal(str(row.amount)) for kind, row in totals if kind == "grand_total"]
    subtotal = subtotals[-1] if subtotals else None
    grand_total = grand_totals[-1] if grand_totals else None

    lines = apply_printed_cues(quote.lines)
    # Headings are context only; they never become lines (DECISIONS D11).
    order_rows = [line for line in lines if line.line_type in ORDER_LINE_TYPES]
    table_charge_rows = [line for line in lines if line.line_type in CHARGE_LINE_TYPES]
    excluded_rows = [line for line in lines if line.line_type in EXCLUDED_LINE_TYPES]

    order_lines = [_order_line(line, f"orderLines[{i}]", warnings)
                   for i, line in enumerate(order_rows)]
    # Alternatives keep their own arithmetic out of the warnings: they aren't being bought.
    excluded_lines = [_order_line(line, "", []) for line in excluded_rows]

    # --- shipping and fees go in the cost breakdown, not the lines (D9) ------
    # Rows inside the items table (Hollis "1.2 Transport") and rows in the totals section
    # (QT-4120 "Shipping (net)") both count, unless the totals row repeats a table row.
    table_charges = [_order_line(line, f"charges[{i}]", warnings)
                     for i, line in enumerate(table_charge_rows)]
    repeated = {(line.line_type, Decimal(str(line.total_price))) for line in table_charges}

    def charge_total(kind: str) -> Decimal:
        in_table = sum((Decimal(str(line.total_price)) for line in table_charges
                        if line.line_type == kind), Decimal(0))
        in_totals = sum((Decimal(str(row.amount)) for row in charges
                         if row.kind == kind and (kind, Decimal(str(row.amount))) not in repeated),
                        Decimal(0))
        return in_table + in_totals

    shipping = charge_total("shipping")
    fees = charge_total("fee")

    # --- the quote's own subtotals are the answer key ------------------------
    def total_of(rows) -> Decimal:
        return sum((Decimal(str(line.total_price)) for line in rows), Decimal(0))

    item_lines = [line for line in order_lines if line.line_type == "item"]
    items_sum = total_of(item_lines)
    lines_sum = total_of(order_lines)  # items + document-level discounts
    computed_total = lines_sum + shipping + fees + tax

    # Some quotes' "net total" already includes charge rows from the table (Hollis).
    if subtotal is not None and min(abs(items_sum - subtotal),
                                    abs(items_sum + total_of(table_charges) - subtotal)
                                    ) > MONEY_TOLERANCE:
        warnings.append(ExtractionWarning(
            code="subtotal_mismatch", field="orderLines",
            message=(f"Item lines add up to {_fmt(items_sum)}, but the quote's items subtotal is "
                     f"{_fmt(subtotal)}." + _subtotal_hint(items_sum, subtotal, item_lines,
                                                           excluded_lines)),
        ))

    if grand_total is not None and abs(computed_total - grand_total) > MONEY_TOLERANCE:
        warnings.append(ExtractionWarning(
            code="total_mismatch", field="totalCost",
            message=(f"Items {_fmt(lines_sum)} + shipping {_fmt(shipping)} + fees {_fmt(fees)} + "
                     f"tax {_fmt(tax)} = {_fmt(computed_total)}, but the quote's grand total is "
                     f"{_fmt(grand_total)}."),
        ))
    total_cost = grand_total if grand_total is not None else computed_total

    # --- vendor vs recipient (DECISIONS D13) ---------------------------------
    vendor_name = (quote.vendor.name or "").strip()
    if not vendor_name:
        warnings.append(ExtractionWarning(
            code="vendor_missing", field="vendorName",
            message="No vendor name found on the document.",
        ))
    else:
        buyer_names = [quote.recipient.name, *organization_names]
        if any(same_company(vendor_name, buyer) for buyer in buyer_names):
            warnings.append(ExtractionWarning(
                code="vendor_is_recipient", field="vendorName",
                message=(f"'{vendor_name}' looks like the buying company, not the vendor. "
                         "Check the letterhead or footer for the vendor's name."),
            ))

    # --- department comes from the requester unless the document names one (D12)
    department = (quote.department or "").strip()
    if department and any(same_company(department, n) for n in
                          [vendor_name, quote.recipient.name, *organization_names]):
        department = ""  # a company name is never a department
    department = department or (requester_department or "")

    data = ExtractedVendorData(
        title=quote.title.strip(),
        vendor_name=vendor_name,
        vat_id=normalize_tax_id(quote.vendor.tax_id),
        department=department,
        order_lines=order_lines,
        excluded_lines=excluded_lines,
        shipping_amount=float(_money(shipping)),
        fees_amount=float(_money(fees)),
        tax_amount=float(_money(tax)),
        total_cost=float(_money(total_cost)),
        commodity_group_id=quote.commodity_group_id,
    )
    return data, warnings
