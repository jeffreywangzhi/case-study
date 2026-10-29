"""Organization booking rules for commodity groups (Task 3). Deterministic; no LLM here.

"For us, cable ties always have to be booked under Electrical Engineering, printer toner
under IT Hardware, and small software subscriptions under Office Supplies." This module
guarantees them on every keyword hit, after extraction and whenever a request is saved.
(They are not sent to the extraction model: that cost accuracy elsewhere, see extraction.py.)
"""
import re
from dataclasses import dataclass

from app.schemas.organizations import CommodityRule, OrganizationSettings


@dataclass(frozen=True)
class RuleMatch:
    rule: CommodityRule
    keyword: str

    @property
    def summary(self) -> str:
        return f"Organization rule \"{self.rule.name}\" (matched \"{self.keyword}\")"


def _pattern(keyword: str) -> re.Pattern:
    """Whole words, case-insensitive, optional plural: 'cable tie' matches 'Cable Ties'."""
    words = [re.escape(w) for w in keyword.lower().split()]
    return re.compile(r"\b" + r"\s+".join(words) + r"(?:e?s)?\b", re.IGNORECASE)


def rules_of(settings: dict | None) -> list[CommodityRule]:
    return OrganizationSettings(**(settings or {})).commodity_rules


def match_rule(rules: list[CommodityRule], texts: list[str],
               total: float | None) -> RuleMatch | None:
    """The first rule whose keyword appears in ``texts`` and whose amount limit holds."""
    haystack = "\n".join(t for t in texts if t)
    for rule in rules:
        if rule.max_total is not None and (total is None or total > rule.max_total):
            continue
        for keyword in rule.keywords:
            if _pattern(keyword).search(haystack):
                return RuleMatch(rule, keyword)
    return None
