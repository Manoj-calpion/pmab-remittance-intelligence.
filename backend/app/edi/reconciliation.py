"""X12 835 financial reconciliation.

Checks, paraphrased from the 835 balancing practice and applied with Decimal:

- A service line charge equals the line payment plus that line's adjustments.
- A claim charge equals the claim payment plus claim-level and line-level adjustments.
- When patient responsibility is present, it equals the sum of PR adjustments.
- When service lines exist, their charges sum to the claim charge and their payments
  sum to the claim payment.
- The remittance payment equals the sum of claim payments minus provider-level
  adjustment amounts. A positive provider adjustment reduces the payment.

Out-of-balance results are returned. They are not silently corrected.
"""

from dataclasses import dataclass, field
from decimal import Decimal

from app.edi.parser import ParsedFile, ParsedTransaction

ZERO = Decimal("0.00")


@dataclass
class ReconciliationCheck:
    scope: str
    entity_key: str
    status: str
    expected_amount: Decimal
    actual_amount: Decimal
    difference: Decimal
    detail: dict = field(default_factory=dict)

    @property
    def balanced(self) -> bool:
        return self.status == "balanced"


def _status(expected: Decimal, actual: Decimal, tolerance: Decimal) -> str:
    if abs(expected - actual) <= tolerance:
        return "balanced"
    return "out_of_balance"


def _check(scope: str, key: str, expected: Decimal, actual: Decimal, tolerance: Decimal, detail: dict | None = None) -> ReconciliationCheck:
    return ReconciliationCheck(
        scope=scope,
        entity_key=key,
        status=_status(expected, actual, tolerance),
        expected_amount=expected,
        actual_amount=actual,
        difference=(expected - actual).quantize(Decimal("0.01")),
        detail=detail or {},
    )


def reconcile_transaction(transaction: ParsedTransaction, tolerance: Decimal = ZERO) -> list[ReconciliationCheck]:
    checks: list[ReconciliationCheck] = []
    claim_payments = ZERO
    provider_adjustments = sum((item.amount for item in transaction.provider_adjustments), ZERO)
    for claim in transaction.claims:
        claim_key = claim.patient_control_number
        claim_payments += claim.paid_amount
        claim_adjustment_total = sum((item.amount for item in claim.adjustments), ZERO)
        line_adjustment_total = ZERO
        line_charges = ZERO
        line_payments = ZERO
        pr_total = sum((item.amount for item in claim.adjustments if item.group_code == "PR"), ZERO)
        for index, line in enumerate(claim.service_lines, start=1):
            line_key = f"{claim_key}:{line.procedure_code or index}:{index}"
            line_adj = sum((item.amount for item in line.adjustments), ZERO)
            line_adjustment_total += line_adj
            line_charges += line.charge_amount
            line_payments += line.paid_amount
            pr_total += sum((item.amount for item in line.adjustments if item.group_code == "PR"), ZERO)
            checks.append(
                _check(
                    "service_line",
                    line_key,
                    line.charge_amount,
                    line.paid_amount + line_adj,
                    tolerance,
                    {"procedure_code": line.procedure_code, "adjustment_total": str(line_adj)},
                )
            )
        checks.append(
            _check(
                "claim",
                claim_key,
                claim.charge_amount,
                claim.paid_amount + claim_adjustment_total + line_adjustment_total,
                tolerance,
                {
                    "claim_adjustments": str(claim_adjustment_total),
                    "line_adjustments": str(line_adjustment_total),
                    "status_code": claim.status_code,
                },
            )
        )
        if claim.service_lines:
            checks.append(
                _check(
                    "claim_line_charges",
                    claim_key,
                    claim.charge_amount,
                    line_charges,
                    tolerance,
                )
            )
            checks.append(
                _check(
                    "claim_line_payments",
                    claim_key,
                    claim.paid_amount,
                    line_payments,
                    tolerance,
                )
            )
        if claim.patient_responsibility is not None:
            checks.append(
                _check(
                    "patient_responsibility",
                    claim_key,
                    claim.patient_responsibility,
                    pr_total,
                    tolerance,
                )
            )
    actual_payment = claim_payments - provider_adjustments
    checks.append(
        _check(
            "transaction",
            transaction.transaction_control_number,
            transaction.payment_amount,
            actual_payment,
            tolerance,
            {
                "claim_payment_total": str(claim_payments),
                "provider_adjustment_total": str(provider_adjustments),
                "formula": "sum(claim payments) - sum(provider-level adjustments)",
            },
        )
    )
    return checks


def reconcile_file(parsed: ParsedFile, tolerance: Decimal = ZERO) -> list[ReconciliationCheck]:
    checks: list[ReconciliationCheck] = []
    for transaction in parsed.transactions:
        checks.extend(reconcile_transaction(transaction, tolerance))
    return checks


def rollup_status(checks: list[ReconciliationCheck]) -> str:
    if not checks:
        return "not_checked"
    if all(check.balanced for check in checks):
        return "balanced"
    return "out_of_balance"
