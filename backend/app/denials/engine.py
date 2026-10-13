"""Deterministic denial classification.

A claim is not a denial merely because an adjustment exists. Contractual
write-offs and patient-responsibility amounts stay outside the denied amount.
The active mapping version decides which CARC codes count as denials.
"""

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from app.denials.catalog import BUNDLED_CODES, CATEGORY_PRIORITY, PATIENT_RESPONSIBILITY_CODES

ZERO = Decimal("0.00")


@dataclass(frozen=True)
class MappingRule:
    category: str
    is_denial: bool
    version: int = 1
    effective_from: date | None = None
    effective_to: date | None = None


@dataclass
class ClassifiedAdjustment:
    group_code: str
    reason_code: str
    amount: Decimal
    category: str
    is_denial: bool


@dataclass
class DenialAssessment:
    is_denied: bool
    scope: str
    denied_amount: Decimal
    primary_category: str | None
    primary_carc: str | None
    category_amounts: dict[str, Decimal] = field(default_factory=dict)
    adjustments: list[ClassifiedAdjustment] = field(default_factory=list)


def classify_adjustment(
    group_code: str,
    reason_code: str,
    amount: Decimal,
    mappings: dict[tuple[str, str], MappingRule],
    as_of: date | None = None,
) -> ClassifiedAdjustment:
    if group_code == "PR" and reason_code in PATIENT_RESPONSIBILITY_CODES:
        return ClassifiedAdjustment(group_code, reason_code, amount, "patient_responsibility", False)
    rule = mappings.get(("CARC", reason_code))
    if rule is not None and _rule_is_effective(rule, as_of):
        return ClassifiedAdjustment(group_code, reason_code, amount, rule.category, rule.is_denial)
    if group_code == "PR":
        return ClassifiedAdjustment(group_code, reason_code, amount, "patient_responsibility", False)
    return ClassifiedAdjustment(group_code, reason_code, amount, "unclassified", False)


def _rule_is_effective(rule: MappingRule, as_of: date | None) -> bool:
    if as_of is None:
        return True
    if rule.effective_from and as_of < rule.effective_from:
        return False
    if rule.effective_to and as_of > rule.effective_to:
        return False
    return True


def assess_denial(
    *,
    status_code: str,
    charge_amount: Decimal,
    paid_amount: Decimal,
    patient_responsibility: Decimal | None,
    adjustments: list[tuple[str, str, Decimal]],
    mappings: dict[tuple[str, str], MappingRule],
    count_partial: bool = True,
    as_of: date | None = None,
) -> DenialAssessment:
    classified = [
        classify_adjustment(group, reason, amount, mappings, as_of) for group, reason, amount in adjustments
    ]
    if status_code == "22":
        return DenialAssessment(False, "none", ZERO, None, None, {}, classified)

    category_amounts: dict[str, Decimal] = defaultdict(lambda: ZERO)
    contractual = ZERO
    for item in classified:
        if item.is_denial:
            category_amounts[item.category] += item.amount
        elif item.category == "contractual":
            contractual += item.amount
    denied_amount = sum(category_amounts.values(), ZERO)
    has_denial = any(item.is_denial for item in classified)
    status_denied = status_code == "4"
    if not has_denial and not status_denied:
        return DenialAssessment(False, "none", ZERO, None, None, {}, classified)

    if not has_denial and status_denied:
        responsibility = patient_responsibility or ZERO
        denied_amount = charge_amount - paid_amount - responsibility - contractual
        if denied_amount < ZERO:
            denied_amount = ZERO
        category_amounts["unclassified"] = denied_amount

    scope = "full" if paid_amount == ZERO else "partial"
    is_denied = scope == "full" or (scope == "partial" and count_partial)
    primary_category = _primary_category(category_amounts)
    primary_carc = _primary_carc(classified, primary_category)
    return DenialAssessment(
        is_denied=is_denied,
        scope=scope if is_denied or scope == "partial" else "none",
        denied_amount=denied_amount.quantize(Decimal("0.01")),
        primary_category=primary_category,
        primary_carc=primary_carc,
        category_amounts={key: value.quantize(Decimal("0.01")) for key, value in category_amounts.items()},
        adjustments=classified,
    )


def _primary_category(category_amounts: dict[str, Decimal]) -> str | None:
    if not category_amounts:
        return None
    ranked = sorted(
        category_amounts.items(),
        key=lambda item: (-abs(item[1]), CATEGORY_PRIORITY.get(item[0], 99)),
    )
    return ranked[0][0]


def _primary_carc(adjustments: list[ClassifiedAdjustment], category: str | None) -> str | None:
    candidates = [item for item in adjustments if item.is_denial and (category is None or item.category == category)]
    if not candidates:
        candidates = [item for item in adjustments if item.is_denial]
    if not candidates:
        return None
    candidates.sort(key=lambda item: abs(item.amount), reverse=True)
    return candidates[0].reason_code


def has_bundled_adjustment(adjustments: list[tuple[str, str, Decimal]]) -> bool:
    return any(reason in BUNDLED_CODES for _, reason, _ in adjustments)
