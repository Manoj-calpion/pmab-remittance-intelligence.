"""Deterministic payment-delay and underpayment calculations.

Missing submission dates and missing approved contract rules produce an
insufficient-data result. This module does not invent dates or expected amounts.
"""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from app.denials.engine import has_bundled_adjustment

SECONDARY_STATUS = {"2", "3", "20", "21"}


@dataclass(frozen=True)
class SubmissionAnchor:
    submitted_at: date | None
    accepted_at: date | None
    source: str
    is_approved_source: bool

    @property
    def anchor_date(self) -> date | None:
        return self.accepted_at or self.submitted_at


@dataclass(frozen=True)
class ContractRule:
    procedure_code: str
    expected_amount: Decimal | None
    percent_of_billed: Decimal | None
    effective_from: date
    effective_to: date | None
    source_label: str
    is_approved: bool
    version: int = 1
    modifier: str | None = None


@dataclass
class DelayResult:
    status: str
    metric_basis: str
    delay_days: int | None
    delayed: bool | None
    threshold_days: int
    payment_date: date | None
    anchor_date: date | None
    reason: str


@dataclass
class UnderpaymentResult:
    status: str
    metric_basis: str
    expected_amount: Decimal | None
    actual_amount: Decimal | None
    variance: Decimal | None
    underpaid: bool | None
    trace: list[str]


def calculate_delay(
    *,
    payment_date: date | None,
    anchors: list[SubmissionAnchor],
    threshold_days: int,
    allow_synthetic: bool,
) -> DelayResult:
    if payment_date is None:
        return DelayResult(
            "insufficient_data",
            "unavailable",
            None,
            None,
            threshold_days,
            None,
            None,
            "Payment date is not present on the remittance.",
        )
    approved = [item for item in anchors if item.is_approved_source and item.anchor_date is not None]
    synthetic = [
        item
        for item in anchors
        if item.source == "synthetic_demo" and not item.is_approved_source and item.anchor_date is not None
    ]
    chosen: SubmissionAnchor | None = None
    basis = "unavailable"
    if approved:
        chosen = sorted(approved, key=lambda item: item.anchor_date or date.min)[0]
        basis = "approved"
    elif allow_synthetic and synthetic:
        chosen = sorted(synthetic, key=lambda item: item.anchor_date or date.min)[0]
        basis = "synthetic_demo"
    if chosen is None or chosen.anchor_date is None:
        return DelayResult(
            "insufficient_data",
            "unavailable",
            None,
            None,
            threshold_days,
            payment_date,
            None,
            "No approved claim submission or acceptance date is on file.",
        )
    delay_days = (payment_date - chosen.anchor_date).days
    return DelayResult(
        status="calculated",
        metric_basis=basis,
        delay_days=delay_days,
        delayed=delay_days > threshold_days,
        threshold_days=threshold_days,
        payment_date=payment_date,
        anchor_date=chosen.anchor_date,
        reason=f"Delay uses {('acceptance' if chosen.accepted_at else 'submission')} date {chosen.anchor_date.isoformat()} and payment date {payment_date.isoformat()}.",
    )


def _select_rule(rules: list[ContractRule], *, procedure_code: str, service_date: date | None, modifier: str | None, allow_synthetic: bool) -> ContractRule | None:
    matching = []
    for rule in rules:
        if rule.procedure_code != procedure_code:
            continue
        if rule.modifier and rule.modifier != modifier:
            continue
        if service_date is not None:
            if service_date < rule.effective_from:
                continue
            if rule.effective_to is not None and service_date > rule.effective_to:
                continue
        if rule.is_approved:
            matching.append(rule)
        elif allow_synthetic and rule.source_label == "synthetic_demo":
            matching.append(rule)
    approved = [rule for rule in matching if rule.is_approved]
    pool = approved or matching
    if not pool:
        return None
    pool.sort(key=lambda rule: (rule.version, rule.effective_from))
    return pool[-1]


def calculate_underpayment(
    *,
    status_code: str,
    billed_amount: Decimal,
    paid_amount: Decimal,
    allowed_amount: Decimal | None,
    line_adjustments: list[tuple[str, str, Decimal]],
    procedure_code: str | None,
    service_date: date | None,
    modifier: str | None,
    rules: list[ContractRule],
    tolerance: Decimal,
    allow_synthetic: bool,
    denial_on_line: bool = False,
) -> UnderpaymentResult:
    trace = [
        f"Claim status {status_code}.",
        f"Billed {billed_amount}, paid {paid_amount}.",
    ]
    if status_code == "22" or paid_amount < 0:
        trace.append("Reversals and negative payments are excluded from underpayment variance.")
        return UnderpaymentResult("reversal_excluded", "unavailable", None, None, None, None, trace)
    if status_code == "4" or denial_on_line:
        trace.append("Denied claims and denied service lines stay in the denial engine and are not also counted as underpayments.")
        return UnderpaymentResult("denial_excluded", "unavailable", None, None, None, None, trace)
    if status_code in SECONDARY_STATUS:
        trace.append("Secondary or tertiary adjudication needs an approved coordination-of-benefits rule, which is not configured.")
        return UnderpaymentResult("insufficient_data", "unavailable", None, None, None, None, trace)
    if has_bundled_adjustment(line_adjustments):
        trace.append("CARC 97 indicates a bundled allowance. Variance is not calculated as an underpayment.")
        return UnderpaymentResult("bundled_excluded", "unavailable", None, None, None, None, trace)
    if not procedure_code:
        trace.append("Procedure code is missing.")
        return UnderpaymentResult("insufficient_data", "unavailable", None, None, None, None, trace)
    if service_date is None:
        trace.append("Service date is missing, so contract effective dates cannot be applied.")
        return UnderpaymentResult("insufficient_data", "unavailable", None, None, None, None, trace)
    rule = _select_rule(
        rules,
        procedure_code=procedure_code,
        service_date=service_date,
        modifier=modifier,
        allow_synthetic=allow_synthetic,
    )
    if rule is None:
        trace.append("No approved reimbursement rule matched this payer, procedure, and service date.")
        return UnderpaymentResult("insufficient_data", "unavailable", None, None, None, None, trace)
    if rule.expected_amount is not None:
        expected = rule.expected_amount
        trace.append(f"Expected allowed amount {expected} comes from contract rule version {rule.version} ({rule.source_label}).")
    elif rule.percent_of_billed is not None:
        expected = (billed_amount * rule.percent_of_billed).quantize(Decimal("0.01"))
        trace.append(f"Expected amount is {rule.percent_of_billed} of billed charges from rule version {rule.version}.")
    else:
        trace.append("The matched rule has no expected amount.")
        return UnderpaymentResult("insufficient_data", "unavailable", None, None, None, None, trace)
    if allowed_amount is not None:
        actual = allowed_amount
        trace.append(f"Actual comparable amount is the allowed amount {actual}.")
    else:
        patient_responsibility = sum((amount for group, _, amount in line_adjustments if group == "PR"), Decimal("0.00"))
        actual = (paid_amount + patient_responsibility).quantize(Decimal("0.01"))
        trace.append(
            "Allowed amount was not on the service line. Actual comparable amount is line payment plus patient-responsibility adjustments."
        )
    variance = (expected - actual).quantize(Decimal("0.01"))
    basis = "approved" if rule.is_approved else "synthetic_demo"
    trace.append(f"Variance {variance} equals expected {expected} minus actual {actual}. Tolerance is {tolerance}.")
    return UnderpaymentResult(
        status="calculated",
        metric_basis=basis,
        expected_amount=expected.quantize(Decimal("0.01")),
        actual_amount=actual.quantize(Decimal("0.01")),
        variance=variance,
        underpaid=variance > tolerance,
        trace=trace,
    )
