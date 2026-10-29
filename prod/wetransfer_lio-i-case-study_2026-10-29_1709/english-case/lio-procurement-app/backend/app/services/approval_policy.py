"""Auto-approval below the organization's limit (bonus task).

"Requiring a buyer to sign off on every single request wastes too much of their
time. Anything below $2,000 shouldn't need approval at all."

A request is approved automatically when its total cost (gross: lines + shipping +
fees + tax) is strictly below ``OrganizationSettings.auto_approval_threshold`` and
none of the safeguards applies:

- its shipping/fees/tax were reset when a catalog agreement switched the vendor and
  nobody re-entered them, so the total is understated;
- together with the requester's other recent requests to the same vendor it reaches
  the limit (a possible split to stay under it).

Organizations without a limit keep "every request needs a buyer".
"""
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ProcurementRequest
from app.services.quote_checks import same_company

SPLIT_WINDOW = timedelta(days=7)


@dataclass(frozen=True)
class ApprovalCheck:
    auto_approve: bool
    reason: str  # why it was or wasn't auto-approved, for the activity log


def _usd(value: Decimal) -> str:
    return f"${value:,.2f}"


def evaluate(
    threshold: float | None,
    total_cost: float,
    *,
    charges_incomplete: bool = False,
    recent_same_vendor: list[ProcurementRequest] = (),
    vendor_name: str = "",
) -> ApprovalCheck:
    """Decide whether a request can skip the buyer. Pure: no database access."""
    if threshold is None:
        return ApprovalCheck(False, "This organization requires a buyer to approve every request.")
    limit, total = Decimal(str(threshold)), Decimal(str(total_cost or 0))
    if total >= limit:
        return ApprovalCheck(False, f"{_usd(total)} is not below the {_usd(limit)} "
                                    "auto-approval limit.")
    if charges_incomplete:
        return ApprovalCheck(False, (
            f"Needs a buyer: shipping, fees and tax weren't entered after the vendor changed, so "
            f"the {_usd(total)} total may be understated (auto-approval limit {_usd(limit)})."
        ))
    combined = total + sum((Decimal(str(r.total_cost or 0)) for r in recent_same_vendor),
                           Decimal(0))
    if recent_same_vendor and combined >= limit:
        count = len(recent_same_vendor)
        return ApprovalCheck(False, (
            f"Needs a buyer: possible split. With {count} other request{'s' if count > 1 else ''} "
            f"to {vendor_name} by the same requester in the last {SPLIT_WINDOW.days} days, the "
            f"total is {_usd(combined)} (auto-approval limit {_usd(limit)})."
        ))
    return ApprovalCheck(True, f"Auto-approved: {_usd(total)} is below the {_usd(limit)} "
                               "auto-approval limit.")


def recent_requests_to_vendor(
    db: Session, request: ProcurementRequest, now: datetime | None = None
) -> list[ProcurementRequest]:
    """The same requester's other non-rejected requests to the same vendor, last 7 days."""
    since = (now or datetime.now(timezone.utc)) - SPLIT_WINDOW
    candidates = db.scalars(
        select(ProcurementRequest).where(
            ProcurementRequest.organization_id == request.organization_id,
            ProcurementRequest.created_by == request.created_by,
            ProcurementRequest.id != request.id,
            ProcurementRequest.approval_status != "rejected",
            ProcurementRequest.created_at >= since,
        )
    )
    return [r for r in candidates if same_company(r.vendor_name, request.vendor_name)]
