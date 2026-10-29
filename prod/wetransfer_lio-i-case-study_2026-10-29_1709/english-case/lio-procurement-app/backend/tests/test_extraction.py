"""Extraction pipeline tests: deterministic checks + the /extraction/pdf endpoint.

The model call is stubbed, so these run offline. Fixtures mirror Acme's quotes:
QT-4120 (Greenmantle Moss Studio), where the original pipeline swapped vendor
and customer, read a position number as a quantity, and counted an alternative;
and QT-OF2312380 (verdeform), where the model swapped vendor and recipient
entirely and picked a corporation number as the tax ID.
"""
import io

from pypdf import PdfWriter

from app.schemas.extraction import QuoteExtraction
from app.services import extraction as extraction_service
from app.services.quote_checks import (
    BuyerContext,
    address_key,
    build_extraction,
    normalize_tax_id,
    same_company,
)
from tests.test_smoke import _auth, client

# Acme's buyer identities as seeded (app.seed.ACME_BUYER_IDENTITIES).
ACME = BuyerContext(
    names=("Acme Corp", "Lio Technologies, Inc."),
    addresses=("1160 Folsom Street, Suite 300, San Francisco, CA 94103",
               "2250 Chestnut Street, Suite 210, San Francisco, CA 94123"),
)


def _vendor(name, address=None, *registration_ids) -> dict:
    return {"name": name, "address": address,
            "registration_ids": [{"label": label, "value": value}
                                 for label, value in registration_ids]}


def _line(position, line_type, description, quantity=None, unit=None, list_unit_price=None,
          discount_percent=None, line_total=None) -> dict:
    return {
        "position": position, "line_type": line_type, "description": description,
        "quantity": quantity, "unit": unit, "list_unit_price": list_unit_price,
        "discount_percent": discount_percent, "line_total": line_total,
    }


def qt4120(**overrides) -> QuoteExtraction:
    """A correct transcription of QT-4120; override pieces to simulate model mistakes."""
    quote = {
        "issuer_evidence": ("Greenmantle Moss Studio, LLC | 1450 Industrial Blvd | West "
                            "Sacramento, CA 95691 ... EIN: 85-3252405"),
        "title": "Moss art panel with logo",
        "vendor": _vendor("Greenmantle Moss Studio, LLC",
                          "1450 Industrial Blvd, West Sacramento, CA 95691",
                          ("LLC No.", "202013769990"), ("EIN", "85-3252405"),
                          ("Seller's Permit", "102-7365501")),
        "recipient": {"name": "Lio Technologies, Inc.",
                      "address": "1160 Folsom Street, Suite 300, San Francisco, CA 94103"},
        "department": None,
        "currency": "USD",
        "lines": [
            _line("1", "heading", "Moss Art Panel, Mixed Moss 63 x 31.5 in"),
            _line("2", "item", "Moss Art Panel, Mixed Moss 63 x 31.5 in", 1, "ea.", 894.08, 20,
                  715.26),
            _line("3", "item", 'Logo integration "asklio" horizontal', 1, "ea.", 622.00, None,
                  622.00),
            _line("4", "heading", "Alternative: vertical logo"),
            _line("5", "alternative", 'Logo integration "asklio" vertical', 1, "ea.", 430.00,
                  None, 430.00),
        ],
        "totals": [
            {"kind": "other", "label": "Page subtotal", "amount": 1337.26},
            {"kind": "items_subtotal", "label": "Items subtotal (net)", "amount": 1337.26},
            {"kind": "shipping", "label": "Shipping (net)", "amount": 215.00},
            {"kind": "tax", "label": "Sales tax 8.625% on $1,337.26", "amount": 115.34},
            {"kind": "tax", "label": "Sales tax 8.625% on shipping $215.00", "amount": 18.54},
            {"kind": "grand_total", "label": "Grand total", "amount": 1686.14},
        ],
        "commodity_group_id": 15,
    }
    quote.update(overrides)
    return QuoteExtraction.model_validate(quote)


def _codes(warnings) -> set[str]:
    return {w.code for w in warnings}


# ---------------------------------------------------------------------------
# Deterministic checks (app.services.quote_checks)
# ---------------------------------------------------------------------------

def test_correct_transcription_is_verified():
    data, warnings = build_extraction(qt4120(), buyer=ACME)

    assert warnings == []
    assert data.vendor_name == "Greenmantle Moss Studio, LLC"
    assert data.vat_id == "85-3252405"
    # Headings dropped, alternative excluded, order lines are items only (D9-D11)
    assert [(l.line_type, l.amount, l.unit_price, l.total_price) for l in data.order_lines] == [
        ("item", 1, 715.26, 715.26),       # net unit price (D7)
        ("item", 1, 622.00, 622.00),
    ]
    assert "list $894.08, -20%" in data.order_lines[0].position_description
    assert [l.total_price for l in data.excluded_lines] == [430.00]
    # Cost breakdown (D8/D9): items 1337.26 + shipping 215 + fees 0 + tax 133.88 = 1686.14
    assert (data.shipping_amount, data.fees_amount, data.tax_amount) == (215.00, 0, 133.88)
    assert data.total_cost == 1686.14


def test_shipping_row_inside_the_items_table_goes_to_the_breakdown():
    # Hollis-style: "1.2 Transport, packing and shipping" is a numbered table row, and the
    # quote's "Net total" includes it.
    lines = [
        _line("1.1", "item", 'Moss panel "70:30"', 1, None, 1560.00, None, 1560.00),
        _line("1.2", "shipping", "Transport, packing and shipping", 1, None, 320.00, None, 320.00),
    ]
    totals = [
        {"kind": "items_subtotal", "label": "Net total", "amount": 1880.00},
        {"kind": "tax", "label": "Sales tax 8.625 %", "amount": 162.15},
        {"kind": "grand_total", "label": "Grand total", "amount": 2042.15},
    ]
    data, warnings = build_extraction(qt4120(lines=lines, totals=totals))
    assert warnings == []
    assert [l.total_price for l in data.order_lines] == [1560.00]
    assert data.shipping_amount == 320.00 and data.total_cost == 2042.15


def test_totals_row_repeating_a_table_charge_is_not_double_counted():
    lines = qt4120().model_dump()["lines"] + [
        _line("6", "shipping", "Shipping (net)", 1, None, 215.00, None, 215.00)
    ]
    data, warnings = build_extraction(qt4120(lines=lines))  # totals also list Shipping 215
    assert warnings == []
    assert data.shipping_amount == 215.00


def _totals_without(kind: str) -> list[dict]:
    return [row for row in qt4120().model_dump()["totals"] if row["kind"] != kind]


def test_missing_shipping_charge_breaks_the_grand_total():
    _, warnings = build_extraction(qt4120(totals=_totals_without("shipping")))
    assert [w.code for w in warnings] == ["total_mismatch"]
    assert "= $1,471.14, but the quote's grand total is $1,686.14" in warnings[0].message


def test_tax_rows_mislabelled_as_fees_are_still_tax():
    totals = qt4120().model_dump()["totals"]
    for row in totals:
        if row["kind"] == "tax":
            row["kind"] = "fee"  # the model's mistake seen in the eval
    data, warnings = build_extraction(qt4120(totals=totals))
    assert warnings == []
    assert data.tax_amount == 133.88 and data.fees_amount == 0
    assert [l.line_type for l in data.order_lines] == ["item", "item"]


def test_subtotal_warning_names_the_alternative():
    lines = qt4120().model_dump()["lines"]
    lines[4]["line_type"] = "item"
    del lines[3]
    _, warnings = build_extraction(qt4120(lines=lines))
    subtotal = next(w for w in warnings if w.code == "subtotal_mismatch")
    assert "Without 'Logo integration \"asklio\" vertical' ($430.00)" in subtotal.message


def test_position_number_read_as_quantity_is_flagged():
    lines = qt4120().model_dump()["lines"]
    lines[1]["quantity"] = 2  # the original pipeline's mistake
    data, warnings = build_extraction(qt4120(lines=lines))

    assert "line_arithmetic" in _codes(warnings)
    assert "$1,430.53, but the line total is $715.26" in warnings[0].message


def test_rows_under_an_alternative_heading_are_excluded():
    lines = qt4120().model_dump()["lines"]
    lines[4]["line_type"] = "item"  # the model's usual first-pass mistake on QT-4120
    data, warnings = build_extraction(qt4120(lines=lines))

    assert warnings == []
    assert [l.total_price for l in data.excluded_lines] == [430.00]


def test_priceless_row_is_a_heading_whatever_its_label():
    # Observed in the eval: the model labels the heading row itself "alternative"
    # and the priced row under it "item".
    lines = qt4120().model_dump()["lines"]
    lines[3]["line_type"] = "alternative"
    lines[4]["line_type"] = "item"
    data, warnings = build_extraction(qt4120(lines=lines))

    assert warnings == []
    assert [l.total_price for l in data.excluded_lines] == [430.00]


def test_printed_alternative_markers_are_excluded():
    # Hollis-style: no heading, the marker is in the row itself.
    lines = [
        _line("1.1", "item", 'Moss panel "70:30"', 1, None, 1560.00, None, 1560.00),
        _line("1.1a", "item", "Alternative to the preceding item: ball moss only", 1, None,
              2090.00),
        _line("(Alt.)", "item", "Vertical logo", 1, None, 430.00, None, 430.00),
    ]
    data, _ = build_extraction(qt4120(lines=lines, totals=[]))
    assert [l.total_price for l in data.order_lines] == [1560.00]
    assert [l.total_price for l in data.excluded_lines] == [2090.00, 430.00]


def test_alternative_counted_as_item_breaks_the_subtotal():
    # No printed cue to rely on (heading removed): the subtotal check still catches it.
    lines = qt4120().model_dump()["lines"]
    lines[4]["line_type"] = "item"
    del lines[3]
    _, warnings = build_extraction(qt4120(lines=lines))

    assert {"subtotal_mismatch", "total_mismatch"} <= _codes(warnings)


def test_vendor_matching_the_recipient_is_flagged():
    quote = qt4120(vendor=_vendor("Lio Technologies, Inc.", None, ("EIN", "85-3252405")))
    _, warnings = build_extraction(quote)  # no buyer context configured
    assert "vendor_is_recipient" in _codes(warnings)


def test_full_vendor_recipient_swap_is_caught_by_buyer_identity():
    # verdeform: the model returned vendor = Lio, recipient = verdeform. Vendor and recipient
    # differ, so only knowing who the buyer is can catch it.
    swapped = qt4120(
        vendor=_vendor("Lio Technologies, Inc.",
                       "1160 Folsom Street, Suite 300, San Francisco, CA 94103"),
        recipient={"name": "verdeform", "address": "2200 E Colorado Blvd, Pasadena, CA 91107"},
    )
    _, warnings = build_extraction(swapped)
    assert "vendor_is_buyer" not in _codes(warnings)  # without buyer identities: silent

    _, warnings = build_extraction(swapped, buyer=ACME)
    assert [w.code for w in warnings] == ["vendor_is_buyer"]
    assert "'Lio Technologies, Inc.' is the buyer" in warnings[0].message


def test_vendor_at_a_buyer_address_is_caught_even_under_another_name():
    quote = qt4120(vendor=_vendor("Lio Tech", "1160 Folsom St., Ste 300, San Francisco"))
    _, warnings = build_extraction(quote, buyer=BuyerContext(
        names=("Acme Corp",), addresses=ACME.addresses))
    assert "vendor_is_buyer" in _codes(warnings)
    assert address_key("2200 E Colorado Blvd, Pasadena") == "2200 colorado"


def test_tax_id_is_picked_by_its_printed_label():
    # verdeform footer: "California Corp. No. C4185275 | EIN: 27-1073640"
    quote = qt4120(vendor=_vendor("Bloomcraft Interiors, Inc.", None,
                                  ("California Corp. No.", "C4185275"), ("EIN", "27-1073640")))
    data, warnings = build_extraction(quote, buyer=ACME)
    assert data.vat_id == "27-1073640" and warnings == []

    # Hollis prints "EIN: 94 1985704"; Apple prints "Tax ID: 94-2404110".
    for label, value, expected in [("EIN", "94 1985704", "94-1985704"),
                                   ("Tax ID", "94-2404110", "94-2404110")]:
        data, _ = build_extraction(qt4120(vendor=_vendor("V", None, (label, value))))
        assert data.vat_id == expected


def test_registration_numbers_without_a_tax_id_label_are_not_used():
    quote = qt4120(vendor=_vendor("Bloomcraft Interiors, Inc.", None,
                                  ("California Corp. No.", "C4185275")))
    data, warnings = build_extraction(quote)
    assert data.vat_id == ""
    assert [w.code for w in warnings] == ["tax_id_unclear"]
    assert "California Corp. No.: C4185275" in warnings[0].message


def test_tax_id_labelled_ein_but_not_nine_digits_is_flagged():
    data, warnings = build_extraction(qt4120(vendor=_vendor("V", None, ("EIN", "C4185275"))))
    assert "tax_id_unclear" in _codes(warnings)


def test_department_never_holds_a_company_name():
    data, _ = build_extraction(qt4120(department="Greenmantle Moss Studio, LLC"),
                               requester_department="Facilities")
    assert data.department == "Facilities"

    data, _ = build_extraction(qt4120(department="Purchasing / Engineering"),
                               requester_department="Facilities")
    assert data.department == "Purchasing / Engineering"


def test_tax_id_normalization_and_missing_tax_id():
    assert normalize_tax_id("94 1985704") == "94-1985704"
    assert normalize_tax_id("EIN: 941985704") == "94-1985704"
    assert normalize_tax_id(None) == ""
    # A quote without a tax ID is valid, not a crash (Hartwell).
    data, warnings = build_extraction(qt4120(vendor=_vendor("Hartwell Industrial Tools, Inc.")))
    assert data.vat_id == "" and warnings == []


def test_company_name_matching():
    assert same_company("Lio Technologies, Inc.", "LIO TECHNOLOGIES INC")
    assert same_company("Acme Corp", "ACME Corp")
    assert not same_company("Greenmantle Moss Studio, LLC", "Lio Technologies, Inc.")
    assert not same_company(None, "Acme Corp")


# ---------------------------------------------------------------------------
# POST /extraction/pdf (model call stubbed)
# ---------------------------------------------------------------------------

def _blank_pdf() -> bytes:
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


def _requester_token() -> str:
    return client.post(
        "/auth/signin", json={"email": "requester@acme.com", "password": "demo1234"}
    ).json()["access_token"]


def test_extract_pdf_retries_once_with_the_failed_checks(monkeypatch):
    monkeypatch.setattr(extraction_service.settings, "openai_api_key", "test-key")
    wrong_lines = qt4120().model_dump()["lines"]
    wrong_lines[1]["quantity"] = 2
    responses = [qt4120(lines=wrong_lines), qt4120()]
    calls: list[list[dict]] = []

    def fake_call(messages):
        calls.append(messages)
        return responses[len(calls) - 1]

    monkeypatch.setattr(extraction_service, "_call_model", fake_call)

    r = client.post(
        "/extraction/pdf",
        files={"file": ("QT-4120.pdf", _blank_pdf(), "application/octet-stream")},
        headers=_auth(_requester_token()),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["success"] is True
    assert body["status"] == "verified" and body["warnings"] == []
    assert len(calls) == 2
    # The retry tells the model exactly which check failed.
    assert "but the line total is $715.26" in calls[1][-1]["content"]
    # The first call carried the rendered page as an image, and told the model who the
    # buyer is (Acme's seeded buyer identities).
    assert any(part["type"] == "image_url" for part in calls[0][1]["content"])
    prompt_text = calls[0][1]["content"][0]["text"]
    assert "- name: Lio Technologies, Inc." in prompt_text
    assert "- address: 2250 Chestnut Street" in prompt_text

    data = body["data"]
    assert data["vendorName"] == "Greenmantle Moss Studio, LLC"
    assert (data["shippingAmount"], data["feesAmount"], data["taxAmount"]) == (215.0, 0, 133.88)
    assert data["totalCost"] == 1686.14
    assert [l["totalPrice"] for l in data["orderLines"]] == [715.26, 622.00]
    assert [l["totalPrice"] for l in data["excludedLines"]] == [430.00]
    assert data["commodityGroupName"] == "Office Equipment"


def test_extract_pdf_reports_needs_review_when_the_retry_fails_too(monkeypatch):
    monkeypatch.setattr(extraction_service.settings, "openai_api_key", "test-key")
    swapped = qt4120(vendor=_vendor("Lio Technologies, Inc."),
                     recipient={"name": "verdeform", "address": None})
    monkeypatch.setattr(extraction_service, "_call_model", lambda messages: swapped)

    body = client.post(
        "/extraction/pdf",
        files={"file": ("q.pdf", _blank_pdf(), "application/pdf")},
        headers=_auth(_requester_token()),
    ).json()
    assert body["success"] is True
    # Warn only, never auto-swap (DECISIONS D30): the vendor stays as extracted.
    assert body["status"] == "needs_review"
    assert [w["code"] for w in body["warnings"]] == ["vendor_is_buyer"]
    assert body["data"]["vendorName"] == "Lio Technologies, Inc."


def test_extract_pdf_checks_file_content_not_mime_type():
    r = client.post(
        "/extraction/pdf",
        # Claims to be a PDF, isn't one.
        files={"file": ("fake.pdf", b"hello", "application/pdf")},
        headers=_auth(_requester_token()),
    )
    assert r.status_code == 400


# ---------------------------------------------------------------------------
# Cost breakdown on requests (D8/D9)
# ---------------------------------------------------------------------------

def test_request_stores_cost_breakdown_and_logs_changes():
    token = _requester_token()
    payload = {
        "requestorName": "Rene Requester", "titleShortDescription": "Moss art panel",
        "vendorName": "Greenmantle Moss Studio, LLC", "vatId": "85-3252405",
        "commodityGroupId": 15, "totalCost": 1686.14, "shippingAmount": 215.0,
        "feesAmount": 0, "taxAmount": 133.88, "department": "",
        "orderLines": [
            {"positionDescription": "Moss panel", "unitPrice": 715.26, "amount": 1,
             "unit": "ea.", "totalPrice": 715.26},
            {"positionDescription": "Logo", "unitPrice": 622.0, "amount": 1,
             "unit": "ea.", "totalPrice": 622.0},
        ],
    }
    r = client.post("/requests", json=payload, headers=_auth(token))
    assert r.status_code == 201, r.text
    created = r.json()
    assert (created["shipping_amount"], created["fees_amount"], created["tax_amount"]) == (
        215.0, 0, 133.88)
    assert created["total_cost"] == 1686.14

    update = {k: v for k, v in payload.items() if k != "titleShortDescription"}
    update.update(title="Moss art panel", shippingAmount=150.0, taxAmount=128.27,
                  totalCost=1615.53)
    r = client.put(f"/requests/{created['id']}", json=update, headers=_auth(token))
    assert r.status_code == 200, r.text
    assert r.json()["shipping_amount"] == 150.0 and r.json()["tax_amount"] == 128.27

    activity = client.get(f"/requests/{created['id']}/activity", headers=_auth(token)).json()
    changed = next(a for a in activity if a["action"] == "updated")["detail"]["changed_fields"]
    assert set(changed) == {"shipping_amount", "tax_amount", "total_cost"}

    client.delete(f"/requests/{created['id']}", headers=_auth(token))


# ---------------------------------------------------------------------------
# Buyer identities in organization settings (D29)
# ---------------------------------------------------------------------------

def _admin_token() -> str:
    return client.post(
        "/auth/signin", json={"email": "admin@acme.com", "password": "demo1234"}
    ).json()["access_token"]


def test_acme_is_seeded_with_its_buyer_identities():
    settings = client.get("/organizations/me/settings", headers=_auth(_admin_token())).json()
    assert [i["name"] for i in settings["buyer_identities"]] == ["Lio Technologies, Inc."]
    assert len(settings["buyer_identities"][0]["addresses"]) == 2


def test_settings_patch_only_changes_what_is_sent():
    token = _admin_token()
    before = client.get("/organizations/me/settings", headers=_auth(token)).json()

    # Toggling required fields (what the settings tab sends) must not wipe buyer identities.
    r = client.patch("/organizations/me/settings", json={"required_fields": ["department"]},
                     headers=_auth(token))
    assert r.status_code == 200
    assert r.json()["buyer_identities"] == before["buyer_identities"]
    assert r.json()["required_fields"] == ["department"]

    # Identities are validated at the edge.
    r = client.patch("/organizations/me/settings", json={"buyer_identities": [{"name": ""}]},
                     headers=_auth(token))
    assert r.status_code == 422

    client.patch("/organizations/me/settings", json=before, headers=_auth(token))
    assert client.get("/organizations/me/settings", headers=_auth(token)).json() == before
