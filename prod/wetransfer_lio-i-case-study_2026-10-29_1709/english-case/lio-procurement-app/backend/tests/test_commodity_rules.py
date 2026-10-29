"""Organization booking rules (Task 3): "cable ties always under Electrical Engineering,
printer toner under IT Hardware, small software subscriptions under Office Supplies".

None of the five sample quotes contains these items, so the rules are tested here directly.
"""
from app.schemas.organizations import CommodityRule
from app.seed import ACME_COMMODITY_RULES
from app.services import extraction as extraction_service
from app.services.commodity_rules import match_rule
from tests.test_extraction import _blank_pdf, _line, qt4120
from tests.test_smoke import _auth, client

ACME_RULES = [CommodityRule(**r) for r in ACME_COMMODITY_RULES]


def _token(email: str) -> str:
    return client.post(
        "/auth/signin", json={"email": email, "password": "demo1234"}
    ).json()["access_token"]


def _group(texts: list[str], total: float = 100) -> int | None:
    match = match_rule(ACME_RULES, texts, total)
    return match.rule.commodity_group_id if match else None


def test_acme_rules_match_the_customers_examples():
    assert _group(["Cable ties 8 in, nylon, pack of 100"]) == 11
    assert _group(["Zip ties black UV-resistant"]) == 11
    assert _group(["Toner cartridge cyan"]) == 29
    assert _group(["HP 26A black toner, 2 pack"]) == 29
    assert _group(["Notion team plan", "SaaS subscription, 12 months"], total=480) == 2001
    assert _group(["Design software license, annual"], total=999) == 2001


def test_small_means_at_most_the_limit():
    assert _group(["Software subscription, enterprise"], total=1000) == 2001
    assert _group(["Software subscription, enterprise"], total=1000.01) is None


def test_rules_only_match_whole_words():
    assert _group(["Electrical tape 3/4 in"]) is None
    assert _group(["Tonerless printer paper"]) is None  # not "toner"
    assert _group(["Moss art panel"]) is None


def _payload(commodity_group_id: int, description: str, total: float = 300) -> dict:
    return {
        "requestorName": "Rene Requester", "titleShortDescription": description,
        "vendorName": "Montclair Supply Corp.", "vatId": "", "commodityGroupId": commodity_group_id,
        "totalCost": total, "department": "",
        "orderLines": [{"positionDescription": description, "unitPrice": total, "amount": 1,
                        "unit": "piece", "totalPrice": total}],
    }


def test_saving_a_request_applies_the_rule_and_logs_why():
    token = _token("requester@acme.com")
    # The requester picked "204 Toner Cartridges" (Office & Administration).
    r = client.post("/requests", json=_payload(204, "Toner cartridge cyan"), headers=_auth(token))
    assert r.status_code == 201, r.text
    created = r.json()
    assert created["commodity_group_id"] == 29
    activity = client.get(f"/requests/{created['id']}/activity", headers=_auth(token)).json()
    applied = next(a for a in activity if a["action"] == "commodity_rule_applied")
    assert "Printer toner" in applied["summary"] and applied["detail"]["requested"] == 204

    # Editing it back doesn't stick either.
    update = {k: v for k, v in _payload(204, "Toner cartridge cyan").items()
              if k != "titleShortDescription"}
    update["title"] = "Toner"
    r = client.put(f"/requests/{created['id']}", json=update, headers=_auth(token))
    assert r.json()["commodity_group_id"] == 29
    client.delete(f"/requests/{created['id']}", headers=_auth(token))


def test_no_rule_no_change_and_other_tenants_are_untouched():
    token = _token("requester@acme.com")
    r = client.post("/requests", json=_payload(15, "Moss art panel"), headers=_auth(token))
    assert r.json()["commodity_group_id"] == 15
    client.delete(f"/requests/{r.json()['id']}", headers=_auth(token))

    walmart = _token("admin@walmart.com")  # Walmart has no booking rules
    r = client.post("/requests", json=_payload(204, "Toner cartridge cyan"), headers=_auth(walmart))
    assert r.status_code == 201, r.text
    assert r.json()["commodity_group_id"] == 204
    client.delete(f"/requests/{r.json()['id']}", headers=_auth(walmart))


def test_extraction_applies_the_rule_over_the_classifier(monkeypatch):
    monkeypatch.setattr(extraction_service.settings, "openai_api_key", "test-key")
    lines = [_line("1", "item", "Cable ties 8 in, nylon, pack of 100", 10, "pack", 12.50, None,
                   125.00)]
    totals = [{"kind": "grand_total", "label": "Total", "amount": 125.00}]
    quote = qt4120(title="Cable ties", lines=lines, totals=totals, commodity_group_id=49)
    seen = {}

    def fake_call(messages):
        seen["prompt"] = messages[1]["content"][0]["text"]
        return quote

    monkeypatch.setattr(extraction_service, "_call_model", fake_call)
    body = client.post(
        "/extraction/pdf", files={"file": ("q.pdf", _blank_pdf(), "application/pdf")},
        headers=_auth(_token("requester@acme.com")),
    ).json()
    assert body["data"]["commodityGroupId"] == 11  # the model said 49 Consumables
    assert body["data"]["commodityGroupName"] == "Electrical Engineering"
    assert "Cable ties" in body["data"]["commodityRule"]
    # Applied in code, not sent to the model (it cost extraction accuracy).
    assert "booking rules" not in seen["prompt"]


def test_rules_are_seeded_and_validated():
    admin = _token("admin@acme.com")
    settings = client.get("/organizations/me/settings", headers=_auth(admin)).json()
    assert [r["name"] for r in settings["commodity_rules"]] == [
        "Cable ties", "Printer toner", "Small software subscriptions"]
    groups = client.get("/commodity-groups", headers=_auth(admin)).json()
    assert any(g["id"] == 2001 and g["name"] == "Office Supplies" for g in groups)

    bad = [{"name": "x", "keywords": ["x"], "commodity_group_id": 999999}]
    r = client.patch("/organizations/me/settings", json={"commodity_rules": bad},
                     headers=_auth(admin))
    assert r.status_code == 422 and "999999" in r.json()["detail"]
