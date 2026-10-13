from datetime import date
from decimal import Decimal

import pytest

from app.denials.catalog import DEFAULT_CODE_MAPPINGS
from app.denials.engine import MappingRule, assess_denial
from app.edi.parser import EDIParseError, parse_835
from app.edi.reconciliation import reconcile_file, rollup_status
from app.payments.engine import ContractRule, SubmissionAnchor, calculate_delay, calculate_underpayment
from app.synthetic.corpus import monthly_history, required_scenarios


def rules() -> dict[tuple[str, str], MappingRule]:
    return {
        (code_type, code): MappingRule(category, is_denial)
        for code, code_type, category, is_denial, _label in DEFAULT_CODE_MAPPINGS
    }


def test_required_fixtures_parse_and_balance() -> None:
    files = required_scenarios()
    assert set(files) >= {
        "successful_payment.835",
        "full_denial.835",
        "partial_denial.835",
        "multiple_claims.835",
        "multiple_service_lines.835",
        "authorization_denial.835",
        "coding_denial.835",
        "provider_level_adjustment.835",
        "reversal.835",
        "duplicate_file.835",
        "malformed.835",
    }
    with pytest.raises(EDIParseError):
        parse_835(files["malformed.835"])
    for name, text in files.items():
        if name == "malformed.835":
            continue
        parsed = parse_835(text)
        checks = reconcile_file(parsed)
        assert rollup_status(checks) == "balanced", name
        assert files["duplicate_file.835"] == files["successful_payment.835"]


def test_monthly_history_balances() -> None:
    for name, text in monthly_history().items():
        assert rollup_status(reconcile_file(parse_835(text))) == "balanced", name


def test_contractual_adjustment_is_not_a_denial() -> None:
    result = assess_denial(
        status_code="1",
        charge_amount=Decimal("200.00"),
        paid_amount=Decimal("150.00"),
        patient_responsibility=Decimal("25.00"),
        adjustments=[("CO", "45", Decimal("25.00")), ("PR", "2", Decimal("25.00"))],
        mappings=rules(),
    )
    assert result.is_denied is False
    assert result.denied_amount == Decimal("0.00")


def test_authorization_and_partial_coding_denials() -> None:
    full = assess_denial(
        status_code="4",
        charge_amount=Decimal("180.00"),
        paid_amount=Decimal("0.00"),
        patient_responsibility=Decimal("0.00"),
        adjustments=[("CO", "197", Decimal("180.00"))],
        mappings=rules(),
    )
    partial = assess_denial(
        status_code="1",
        charge_amount=Decimal("300.00"),
        paid_amount=Decimal("100.00"),
        patient_responsibility=Decimal("0.00"),
        adjustments=[("CO", "45", Decimal("50.00")), ("CO", "4", Decimal("150.00"))],
        mappings=rules(),
    )
    assert full.is_denied and full.scope == "full" and full.primary_category == "authorization"
    assert full.denied_amount == Decimal("180.00")
    assert partial.is_denied and partial.scope == "partial" and partial.primary_category == "coding"
    assert partial.denied_amount == Decimal("150.00")


def test_delay_is_unavailable_without_a_submission_date() -> None:
    result = calculate_delay(payment_date=date(2025, 12, 15), anchors=[], threshold_days=30, allow_synthetic=True)
    assert result.status == "insufficient_data"
    assert result.delay_days is None


def test_delay_uses_only_approved_dates_unless_demo_is_allowed() -> None:
    synthetic = SubmissionAnchor(date(2025, 11, 1), None, "synthetic_demo", False)
    hidden = calculate_delay(
        payment_date=date(2025, 12, 15),
        anchors=[synthetic],
        threshold_days=30,
        allow_synthetic=False,
    )
    shown = calculate_delay(
        payment_date=date(2025, 12, 15),
        anchors=[synthetic],
        threshold_days=30,
        allow_synthetic=True,
    )
    approved = calculate_delay(
        payment_date=date(2025, 12, 15),
        anchors=[SubmissionAnchor(date(2025, 11, 1), None, "clearinghouse", True)],
        threshold_days=30,
        allow_synthetic=False,
    )
    assert hidden.status == "insufficient_data"
    assert shown.status == "calculated" and shown.metric_basis == "synthetic_demo" and shown.delayed is True
    assert approved.metric_basis == "approved" and approved.delay_days == 44


def test_underpayment_requires_an_approved_rule() -> None:
    missing = calculate_underpayment(
        status_code="1",
        billed_amount=Decimal("150.00"),
        paid_amount=Decimal("80.00"),
        allowed_amount=Decimal("80.00"),
        line_adjustments=[("CO", "45", Decimal("70.00"))],
        procedure_code="90837",
        service_date=date(2025, 12, 1),
        modifier=None,
        rules=[],
        tolerance=Decimal("0.01"),
        allow_synthetic=False,
    )
    synthetic_rule = ContractRule(
        "90837",
        Decimal("120.00"),
        None,
        date(2025, 1, 1),
        None,
        "synthetic_demo",
        False,
    )
    blocked = calculate_underpayment(
        status_code="1",
        billed_amount=Decimal("150.00"),
        paid_amount=Decimal("80.00"),
        allowed_amount=Decimal("80.00"),
        line_adjustments=[("CO", "45", Decimal("70.00"))],
        procedure_code="90837",
        service_date=date(2025, 12, 1),
        modifier=None,
        rules=[synthetic_rule],
        tolerance=Decimal("0.01"),
        allow_synthetic=False,
    )
    demo = calculate_underpayment(
        status_code="1",
        billed_amount=Decimal("150.00"),
        paid_amount=Decimal("80.00"),
        allowed_amount=Decimal("80.00"),
        line_adjustments=[("CO", "45", Decimal("70.00"))],
        procedure_code="90837",
        service_date=date(2025, 12, 1),
        modifier=None,
        rules=[synthetic_rule],
        tolerance=Decimal("0.01"),
        allow_synthetic=True,
    )
    approved = calculate_underpayment(
        status_code="1",
        billed_amount=Decimal("150.00"),
        paid_amount=Decimal("80.00"),
        allowed_amount=Decimal("80.00"),
        line_adjustments=[("CO", "45", Decimal("70.00"))],
        procedure_code="90837",
        service_date=date(2025, 12, 1),
        modifier=None,
        rules=[ContractRule("90837", Decimal("120.00"), None, date(2025, 1, 1), None, "approved_contract", True)],
        tolerance=Decimal("0.01"),
        allow_synthetic=False,
    )
    assert missing.status == "insufficient_data"
    assert blocked.status == "insufficient_data"
    assert demo.metric_basis == "synthetic_demo" and demo.variance == Decimal("40.00") and demo.underpaid is True
    assert approved.metric_basis == "approved" and approved.variance == Decimal("40.00")
    assert any("expected" in line.lower() for line in approved.trace)
