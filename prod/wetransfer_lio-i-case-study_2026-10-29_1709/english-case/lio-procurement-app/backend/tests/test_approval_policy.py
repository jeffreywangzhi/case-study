"""Auto-approval below the organization's limit (bonus task).

Acme is seeded with a $2,000 limit (gross total); other organizations have none.
Each test uses its own vendor names so the split check never sees other tests' requests.
"""
from app.services.approval_policy import evaluate
from tests.test_smoke import _auth, client


def _token(email: str = "requester@acme.com") -> str:
    return client.post(
        "/auth/signin", json={"email": email, "password": "demo1234"}
    ).json()["access_token"]


def _create(token: str, total: float, vendor: str, **extra) -> dict:
    payload = {
        "requestorName": "Rene Requester", "titleShortDescription": "Office supplies",
        "vendorName": vendor, "vatId": "", "commodityGroupId": 15, "totalCost": total,
        "department": "", "orderLines": [{"positionDescription": "Item", "unitPrice": total,
                                          "amount": 1, "unit": "piece", "totalPrice": total}],
        **extra,
    }
    r = client.post("/requests", json=payload, headers=_auth(token))
    assert r.status_code == 201, r.text
    return r.json()


def _update(token: str, request: dict, total: float | None = None, **changes) -> dict:
    total = request["total_cost"] if total is None else total
    payload = {
        "requestorName": request["requestor_name"], "title": changes.pop("title", request["title"]),
        "vendorName": changes.pop("vendor", request["vendor_name"]), "vatId": "",
        "commodityGroupId": request["commodity_group_id"], "totalCost": total, "department": "",
        "orderLines": [{"positionDescription": "Item", "unitPrice": total, "amount": 1,
                        "unit": "piece", "totalPrice": total}],
        **changes,
    }
    r = client.put(f"/requests/{request['id']}", json=payload, headers=_auth(token))
    assert r.status_code == 200, r.text
    return r.json()


def _actions(token: str, request: dict) -> list[tuple[str, str]]:
    activity = client.get(f"/requests/{request['id']}/activity", headers=_auth(token)).json()
    return [(a["action"], a["summary"]) for a in reversed(activity)]


def _cleanup(token: str, *requests: dict) -> None:
    for request in requests:
        client.delete(f"/requests/{request['id']}", headers=_auth(token))


# ---------------------------------------------------------------------------
# The policy (pure)
# ---------------------------------------------------------------------------

def test_policy_strictly_below_the_limit():
    assert evaluate(None, 10).auto_approve is False  # no limit configured: a buyer decides
    assert evaluate(2000, 1999.99).auto_approve is True
    assert evaluate(2000, 2000.00).auto_approve is False  # "below $2,000": $2,000 needs a buyer
    assert evaluate(2000, 2042.15).auto_approve is False  # Hollis, gross


def test_policy_safeguards():
    check = evaluate(2000, 974.00, charges_incomplete=True)
    assert check.auto_approve is False and "may be understated" in check.reason


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------

def test_request_under_the_limit_is_auto_approved():
    token = _token()
    request = _create(token, 1686.14, "Auto Vendor One")
    assert request["approval_status"] == "approved"
    assert request["approval_method"] == "auto"
    assert request["approved_by"] is None  # no person approved it
    assert ("auto_approved",
            "Auto-approved: $1,686.14 is below the $2,000.00 auto-approval limit."
            ) in _actions(token, request)
    _cleanup(token, request)


def test_request_at_or_above_the_limit_needs_a_buyer():
    token = _token()
    at_limit = _create(token, 2000.00, "Auto Vendor Two")
    hollis = _create(token, 2042.15, "Auto Vendor Three")
    assert at_limit["approval_status"] == hollis["approval_status"] == "pending"
    assert at_limit["approval_method"] is None
    _cleanup(token, at_limit, hollis)


def test_understated_total_after_a_vendor_switch_needs_a_buyer():
    token = _token()
    request = _create(token, 974.00, "Auto Vendor Four", chargesIncomplete=True)
    assert request["approval_status"] == "pending"
    [(action, summary)] = [a for a in _actions(token, request) if a[0] == "approval_required"]
    assert "shipping, fees and tax weren't entered" in summary
    _cleanup(token, request)


def test_possible_split_needs_a_buyer():
    token = _token()
    first = _create(token, 1200.00, "Split Supplies Inc.")
    second = _create(token, 1200.00, "SPLIT SUPPLIES, INC")  # same vendor, written differently
    assert first["approval_status"] == "approved"
    assert second["approval_status"] == "pending"
    [summary] = [s for a, s in _actions(token, second) if a == "approval_required"]
    assert "possible split" in summary and "$2,400.00" in summary
    _cleanup(token, first, second)


def test_other_organizations_keep_manual_approval():
    token = _token("admin@walmart.com")
    request = _create(token, 50.00, "Auto Vendor Five")
    assert request["approval_status"] == "pending"
    _cleanup(token, request)


# ---------------------------------------------------------------------------
# Edits after approval
# ---------------------------------------------------------------------------

def test_editing_an_auto_approved_request_over_the_limit_sends_it_back():
    token = _token()
    request = _create(token, 1900.00, "Auto Vendor Six")
    assert request["approval_method"] == "auto"

    raised = _update(token, request, total=5000.00)
    assert raised["approval_status"] == "pending" and raised["approval_method"] is None
    assert any(a == "approval_reset" and "Back to pending" in s for a, s in _actions(token, raised))

    lowered = _update(token, raised, total=1500.00)
    assert lowered["approval_status"] == "approved" and lowered["approval_method"] == "auto"
    _cleanup(token, request)


def test_editing_a_buyer_approved_request():
    token, buyer = _token(), _token("buyer@acme.com")
    request = _create(token, 3000.00, "Auto Vendor Seven")
    approved = client.patch(f"/requests/{request['id']}/approval", json={"decision": "approved"},
                            headers=_auth(buyer)).json()
    assert approved["approval_method"] == "manual"

    # A typo fix keeps the buyer's approval...
    renamed = _update(token, approved, title="Office supplies (Q4)")
    assert renamed["approval_status"] == "approved" and renamed["approval_method"] == "manual"
    # ...a different vendor doesn't (closes "approve, then edit freely").
    switched = _update(token, renamed, vendor="Auto Vendor Eight")
    assert switched["approval_status"] == "pending"
    _cleanup(token, request)


def test_rejected_stays_rejected():
    token, buyer = _token(), _token("buyer@acme.com")
    request = _create(token, 2500.00, "Auto Vendor Nine")
    client.patch(f"/requests/{request['id']}/approval", json={"decision": "rejected"},
                 headers=_auth(buyer))
    edited = _update(token, {**request, "approval_status": "rejected"}, total=100.00)
    assert edited["approval_status"] == "rejected"
    _cleanup(token, request)


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------

def test_threshold_setting_is_validated_and_admin_editable():
    admin = _token("admin@acme.com")
    assert client.get("/organizations/me/settings",
                      headers=_auth(admin)).json()["auto_approval_threshold"] == 2000
    r = client.patch("/organizations/me/settings", json={"auto_approval_threshold": 0},
                     headers=_auth(admin))
    assert r.status_code == 422  # must be positive; null switches auto-approval off
    r = client.patch("/organizations/me/settings", json={"auto_approval_threshold": 2000},
                     headers=_auth(admin))
    assert r.status_code == 200
