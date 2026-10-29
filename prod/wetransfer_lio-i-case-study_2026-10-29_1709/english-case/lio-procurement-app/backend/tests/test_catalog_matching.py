"""Catalog suggestions (Task 2): retrieval, price comparison, model check, and catalog links.

Offline: without an API key the matcher uses strict keyword matching; the model
path is tested with stubbed embeddings and a stubbed judge.
"""
import uuid
from decimal import Decimal

from app.models import Article
from app.schemas.articles import CatalogMatchLine
from app.services import catalog_matching
from app.services.catalog_matching import (
    _Judgement,
    agreement,
    bm25_scores,
    keyword_match,
    keyword_overlap,
    normalize_unit,
    tokens,
)
from tests.test_smoke import TestingSession, _auth, client


def _token(email: str = "requester@acme.com") -> str:
    return client.post(
        "/auth/signin", json={"email": email, "password": "demo1234"}
    ).json()["access_token"]


def _article(search: str) -> dict:
    page = client.get(f"/articles?search={search}&limit=100", headers=_auth(_token())).json()
    return min(page["items"], key=lambda a: float(a["unit_price"]))


# ---------------------------------------------------------------------------
# Deterministic pieces
# ---------------------------------------------------------------------------

def test_units_are_compared_on_a_canonical_form():
    assert normalize_unit("ea.") == normalize_unit("piece") == normalize_unit("PCS") == "piece"
    assert normalize_unit("sq ft") == normalize_unit("sqft") == "sq ft"
    assert normalize_unit("lin ft") == "ft"
    assert normalize_unit("lump sum") == "lump sum"  # unknown units stay as they are


def test_bm25_ranks_the_matching_item_first():
    descriptions = ["Docking station USB-C, dual 4K", "Toner cartridge cyan",
                    "Last-mile delivery standard"]
    scores = bm25_scores("usb-c docking station", [tokens(d) for d in descriptions])
    assert scores.index(max(scores)) == 0
    assert keyword_overlap("Delivery and installation", "Last-mile delivery standard") == 0.5
    # Half the words, but only one shared word: not a clear match.
    assert not keyword_match("Delivery and installation", "Last-mile delivery standard")
    assert keyword_match("cyan toner", "Toner cartridge cyan")
    assert keyword_match("toner", "Toner cartridge cyan")  # one-word query: all of it


def test_price_comparison_only_when_units_match():
    with TestingSession() as db:
        article = db.query(Article).filter(Article.description == "Toner cartridge cyan").first()
        price = Decimal(str(article.unit_price))
        line = CatalogMatchLine(description="cyan toner", unit="ea.",
                                unit_price=float(price + 10), quantity=3)
        a = agreement(article, line)
        assert a.same_unit and a.saving_per_unit == Decimal("10.00")
        assert a.saving_total == Decimal("30.00")

        cheaper_quote = agreement(article, line.model_copy(update={"unit_price": float(price - 5)}))
        assert cheaper_quote.saving_per_unit == Decimal("-5.00")  # the quote is cheaper

        other_unit = agreement(article, line.model_copy(update={"unit": "sq ft"}))
        assert not other_unit.same_unit and other_unit.saving_per_unit is None


# ---------------------------------------------------------------------------
# POST /articles/match and GET /articles/suggest
# ---------------------------------------------------------------------------

def test_match_without_ai_uses_strict_keywords_and_says_so():
    r = client.post("/articles/match", headers=_auth(_token()), json={"lines": [
        {"description": "Toner cartridge cyan", "unit": "ea.", "unit_price": 150, "quantity": 2},
        {"description": "Grinding machine HW-GS 450", "unit": "ea.", "unit_price": 15000},
    ]})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["verified"] is False
    toner, grinder = body["lines"]
    assert toner["suggestions"][0]["item"] == "Toner cartridge cyan"
    prices = [float(a["unit_price"]) for a in toner["suggestions"][0]["agreements"]]
    assert prices == sorted(prices) and len(prices) == 6  # every supplier, cheapest first
    best = toner["suggestions"][0]["agreements"][0]
    assert float(best["saving_per_unit"]) == 150 - prices[0]
    assert grinder["suggestions"] == []  # nothing in the catalog: no suggestion


def test_match_with_ai_keeps_only_what_the_judge_accepts(monkeypatch):
    monkeypatch.setattr(catalog_matching.settings, "openai_api_key", "test-key")
    monkeypatch.setattr(catalog_matching, "embed", lambda db, texts: [[0.0] for _ in texts])
    seen = {}

    def fake_judge(lines, candidates):
        seen["candidates"] = [[c.item.description for c in cands] for cands in candidates]
        moss = next(i for i, c in enumerate(candidates[0], start=1)
                    if c.item.description.startswith("Framed preserved moss panel"))
        return _Judgement.model_validate({"lines": [
            {"line": 0, "matches": [{"candidate": moss, "quality": "similar",
                                     "reason": "Standard framed panel; quote is made to measure."}]},
            # Every candidate rejected: "nothing fits" is a valid answer.
            {"line": 1, "matches": [{"candidate": i, "quality": "not_a_match",
                                     "reason": "Different product type."}
                                    for i in range(1, len(candidates[1]) + 1)]},
        ]})

    monkeypatch.setattr(catalog_matching, "judge", fake_judge)
    body = client.post("/articles/match", headers=_auth(_token()), json={"lines": [
        {"description": "Moss Art Panel, Mixed Moss 63 x 31.5 in", "unit": "ea.",
         "unit_price": 715.26},
        {"description": "Delivery and installation", "unit": "lump sum", "unit_price": 2000},
    ]}).json()

    assert body["verified"] is True
    assert any("moss" in d.lower() for d in seen["candidates"][0])  # retrieval found it
    [suggestion] = body["lines"][0]["suggestions"]
    assert suggestion["quality"] == "similar" and "made to measure" in suggestion["reason"]
    assert body["lines"][1]["suggestions"] == []


def test_match_falls_back_to_keywords_when_the_model_fails(monkeypatch):
    monkeypatch.setattr(catalog_matching.settings, "openai_api_key", "test-key")

    def broken(*_args, **_kwargs):
        raise RuntimeError("API down")

    monkeypatch.setattr(catalog_matching, "embed", broken)
    body = client.post("/articles/match", headers=_auth(_token()), json={"lines": [
        {"description": "Toner cartridge cyan"}]}).json()
    assert body["verified"] is False
    assert body["lines"][0]["suggestions"][0]["item"] == "Toner cartridge cyan"


def test_known_supplier_by_name_or_tax_id():
    hudson = client.get("/suppliers?search=Hudson Systems", headers=_auth(_token())).json()[0]
    for vendor in [{"vendor_name": "HUDSON SYSTEMS, INC."}, {"vat_id": hudson["vat_id"]}]:
        body = client.post("/articles/match", headers=_auth(_token()),
                           json={"lines": [], **vendor}).json()
        assert body["known_supplier"]["name"] == "Hudson Systems Inc."
    body = client.post("/articles/match", headers=_auth(_token()),
                       json={"lines": [], "vendor_name": "Bloomcraft Interiors, Inc."}).json()
    assert body["known_supplier"] is None  # an off-catalog vendor


def test_suggest_typeahead_and_tenant_isolation():
    r = client.get("/articles/suggest?q=toner cartridge cyan", headers=_auth(_token()))
    assert r.status_code == 200
    assert r.json()[0]["item"] == "Toner cartridge cyan"

    # Walmart has no catalog: it never sees Acme's agreements.
    other = _token("admin@walmart.com")
    assert client.get("/articles/suggest?q=toner cartridge cyan", headers=_auth(other)).json() == []
    body = client.post("/articles/match", headers=_auth(other), json={"lines": [
        {"description": "Toner cartridge cyan"}]}).json()
    assert body["lines"][0]["suggestions"] == []


# ---------------------------------------------------------------------------
# Catalog links on request lines
# ---------------------------------------------------------------------------

def _payload(lines: list[dict]) -> dict:
    return {
        "requestorName": "Rene Requester", "titleShortDescription": "Toner",
        "vendorName": "Montclair Supply Corp.", "vatId": "", "commodityGroupId": 29,
        "totalCost": sum(l["totalPrice"] for l in lines), "department": "", "orderLines": lines,
    }


def test_request_line_links_a_catalog_article_with_a_price_snapshot():
    token = _token()
    toner = _article("Toner cartridge cyan")
    line = {"positionDescription": toner["description"], "unitPrice": float(toner["unit_price"]),
            "amount": 2, "unit": toner["unit"], "totalPrice": 2 * float(toner["unit_price"]),
            "articleId": toner["id"]}
    r = client.post("/requests", json=_payload([line]), headers=_auth(token))
    assert r.status_code == 201, r.text
    created = r.json()
    [stored] = created["order_lines"]
    assert stored["article_id"] == toner["id"]
    assert stored["catalog_unit_price"] == float(toner["unit_price"])  # from the article
    actions = [a["action"] for a in client.get(f"/requests/{created['id']}/activity",
                                               headers=_auth(token)).json()]
    assert "catalog_applied" in actions

    # The snapshot is the price at the time of use: a later catalog change doesn't rewrite it.
    with TestingSession() as db:
        db.get(Article, uuid.UUID(toner["id"])).unit_price = 1.00
        db.commit()
    update = {k: v for k, v in _payload([line]).items() if k != "titleShortDescription"}
    update["title"] = "Toner (2)"
    r = client.put(f"/requests/{created['id']}", json=update, headers=_auth(token))
    assert r.status_code == 200, r.text
    assert r.json()["order_lines"][0]["catalog_unit_price"] == float(toner["unit_price"])

    with TestingSession() as db:  # restore the seed price for other tests
        db.get(Article, uuid.UUID(toner["id"])).unit_price = float(toner["unit_price"])
        db.commit()
    client.delete(f"/requests/{created['id']}", headers=_auth(token))


def test_request_line_rejects_an_article_from_outside_the_catalog():
    line = {"positionDescription": "x", "unitPrice": 1, "amount": 1, "unit": "piece",
            "totalPrice": 1, "articleId": "00000000-0000-0000-0000-000000000000"}
    r = client.post("/requests", json=_payload([line]), headers=_auth(_token()))
    assert r.status_code == 422
    assert "Unknown catalog article" in r.json()["detail"]
