"""Synthetic, clearly fake remittances for the local demo and parser tests."""

from datetime import date, timedelta
from decimal import Decimal

from app.edi.builder import ClaimSpec, LineSpec, RemitSpec, render_remittance

ZERO = Decimal("0.00")
PROVIDER = "Synthetic Clinic One"
NPI = "1999999992"


def _money(value: Decimal) -> str:
    return f"{value.quantize(Decimal('0.01')):.2f}"


def _line(
    procedure: str,
    charge: str,
    paid: str,
    adjustments: list[tuple[str, str, str]],
    service_date: str,
    rarc: str | None = None,
    allowed: str | None = None,
) -> LineSpec:
    return LineSpec(
        procedure=procedure,
        charge=charge,
        paid=paid,
        adjustments=adjustments,
        service_date=service_date,
        rarc=rarc,
        allowed=allowed,
    )


def _claim(
    control: str,
    status: str,
    lines: list[LineSpec],
    payer_claim: str,
    last: str = "DOE",
    first: str = "JANE",
    member: str = "SYNTH0001",
    authorization_number: str | None = None,
) -> ClaimSpec:
    charge = sum((Decimal(line.charge) for line in lines), ZERO)
    paid = sum((Decimal(line.paid) for line in lines), ZERO)
    responsibility = ZERO
    for line in lines:
        for group, _reason, amount in line.adjustments:
            if group == "PR":
                responsibility += Decimal(amount)
    return ClaimSpec(
        patient_control=control,
        status=status,
        charge=_money(charge),
        paid=_money(paid),
        patient_responsibility=_money(responsibility),
        payer_claim_control=payer_claim,
        lines=lines,
        patient_last=last,
        patient_first=first,
        member_id=member,
        authorization_number=authorization_number,
    )


def _render(spec: RemitSpec) -> str:
    paid = sum((Decimal(claim.paid) for claim in spec.claims), ZERO)
    plb = sum((Decimal(amount) for _reason, _ref, amount in spec.plb), ZERO)
    spec.payment_amount = _money(paid - plb)
    return render_remittance(spec)


def _base(**kwargs) -> RemitSpec:
    defaults = dict(
        payment_amount="0.00",
        payment_date="20251215",
        trace="TRC-SYNTH",
        payer_name="Synthetic Payer North",
        payer_id="PAYERNORTH",
        provider_name=PROVIDER,
        provider_npi=NPI,
        claims=[],
    )
    defaults.update(kwargs)
    return RemitSpec(**defaults)


def required_scenarios() -> dict[str, str]:
    success = _claim(
        "CLM-SUCCESS",
        "1",
        [
            _line(
                "90837",
                "200.00",
                "150.00",
                [("CO", "45", "25.00"), ("PR", "2", "25.00")],
                "20251201",
                allowed="175.00",
            )
        ],
        "PCN-SUCCESS",
    )
    full = _claim(
        "CLM-FULLDENY",
        "4",
        [_line("97153", "180.00", "0.00", [("CO", "197", "180.00")], "20251202", rarc="M62")],
        "PCN-FULLDENY",
        authorization_number="AUTH-FULLDENY",
    )
    partial = _claim(
        "CLM-PARTIAL",
        "1",
        [_line("90834", "300.00", "100.00", [("CO", "45", "50.00"), ("CO", "4", "150.00")], "20251203")],
        "PCN-PARTIAL",
    )
    multi = [
        _claim("CLM-MULTI-1", "1", [_line("90837", "100.00", "100.00", [], "20251204")], "PCN-MULTI-1", member="SYNTH1001"),
        _claim(
            "CLM-MULTI-2",
            "1",
            [_line("90834", "80.00", "50.00", [("CO", "45", "30.00")], "20251204")],
            "PCN-MULTI-2",
            member="SYNTH1002",
        ),
    ]
    lines = _claim(
        "CLM-LINES",
        "1",
        [
            _line("97153", "100.00", "80.00", [("CO", "45", "20.00")], "20251205"),
            _line("97155", "100.00", "70.00", [("CO", "45", "10.00"), ("PR", "3", "20.00")], "20251205"),
        ],
        "PCN-LINES",
    )
    auth = _claim(
        "CLM-AUTH",
        "4",
        [_line("97153", "220.00", "0.00", [("CO", "197", "220.00")], "20251206", rarc="M62")],
        "PCN-AUTH",
        authorization_number="AUTH-97153",
        member="SYNTH2001",
    )
    coding = _claim(
        "CLM-CODE",
        "4",
        [_line("90837", "160.00", "0.00", [("CO", "11", "160.00")], "20251206")],
        "PCN-CODE",
        member="SYNTH2002",
    )
    plb_claim = _claim("CLM-PLB", "1", [_line("90837", "100.00", "100.00", [], "20251207")], "PCN-PLB")
    reversal = _claim(
        "CLM-REVERSE",
        "22",
        [_line("90837", "-200.00", "-150.00", [("CO", "45", "-50.00")], "20251101")],
        "PCN-REVERSE",
    )
    success_text = _render(
        _base(trace="TRC-SUCCESS", interchange_control="000000101", claims=[success], payment_date="20251215")
    )
    return {
        "successful_payment.835": success_text,
        "full_denial.835": _render(
            _base(trace="TRC-FULL", interchange_control="000000102", claims=[full], payment_date="20251215")
        ),
        "partial_denial.835": _render(
            _base(trace="TRC-PARTIAL", interchange_control="000000103", claims=[partial], payment_date="20251215")
        ),
        "multiple_claims.835": _render(
            _base(
                trace="TRC-MULTI",
                interchange_control="000000104",
                claims=multi,
                payment_date="20251215",
                payer_name="Synthetic Payer Harbor",
                payer_id="PAYERHARBOR",
            )
        ),
        "multiple_service_lines.835": _render(
            _base(trace="TRC-LINES", interchange_control="000000105", claims=[lines], payment_date="20251215")
        ),
        "authorization_denial.835": _render(
            _base(trace="TRC-AUTH", interchange_control="000000106", claims=[auth], payment_date="20251215")
        ),
        "coding_denial.835": _render(
            _base(
                trace="TRC-CODE",
                interchange_control="000000107",
                claims=[coding],
                payment_date="20251215",
                payer_name="Synthetic Payer Harbor",
                payer_id="PAYERHARBOR",
            )
        ),
        "provider_level_adjustment.835": _render(
            _base(
                trace="TRC-PLB",
                interchange_control="000000108",
                claims=[plb_claim],
                plb=[("WO", "RECOUP1", "10.00")],
                payment_date="20251215",
                payer_name="Synthetic Payer Metro",
                payer_id="PAYERMETRO",
            )
        ),
        "reversal.835": _render(
            _base(trace="TRC-REV", interchange_control="000000109", claims=[reversal], payment_date="20251215")
        ),
        "duplicate_file.835": success_text,
        "malformed.835": "ISA*this is not a valid 835 envelope\n",
    }


def monthly_history() -> dict[str, str]:
    """Six months of labeled synthetic payer behavior, including a December denial spike."""
    payers = {
        "PAYERNORTH": "Synthetic Payer North",
        "PAYERHARBOR": "Synthetic Payer Harbor",
        "PAYERMETRO": "Synthetic Payer Metro",
    }
    months = ["202507", "202508", "202509", "202510", "202511", "202512"]
    files: dict[str, str] = {}
    sequence = 200
    for month in months:
        for payer_id, payer_name in payers.items():
            sequence += 1
            claims: list[ClaimSpec] = []
            if payer_id == "PAYERNORTH":
                denial_count = 4 if month == "202512" else 1
                denial_code = "197"
                procedure = "97153"
            elif payer_id == "PAYERHARBOR":
                denial_count = 2
                denial_code = "4"
                procedure = "90837"
            else:
                denial_count = 0
                denial_code = "45"
                procedure = "90834"
            for index in range(6):
                control = f"{payer_id}-{month}-{index + 1}"
                service_date = f"{month}{index + 1:02d}"
                if index < denial_count:
                    claims.append(
                        _claim(
                            control,
                            "4",
                            [_line(procedure, "150.00", "0.00", [("CO", denial_code, "150.00")], service_date, rarc="M62" if denial_code == "197" else None)],
                            f"PCN-{control}",
                            member=f"SYNTH{sequence}{index}",
                            authorization_number=f"AUTH-{control}" if denial_code == "197" else None,
                        )
                    )
                elif payer_id == "PAYERMETRO" and index == 5:
                    claims.append(
                        _claim(
                            control,
                            "1",
                            [_line("90837", "150.00", "80.00", [("CO", "45", "70.00")], service_date, allowed="80.00")],
                            f"PCN-{control}",
                            member=f"SYNTH{sequence}{index}",
                        )
                    )
                else:
                    claims.append(
                        _claim(
                            control,
                            "1",
                            [_line("90834", "150.00", "120.00", [("CO", "45", "30.00")], service_date, allowed="120.00")],
                            f"PCN-{control}",
                            member=f"SYNTH{sequence}{index}",
                        )
                    )
            spec = _base(
                trace=f"TRC-{payer_id}-{month}",
                interchange_control=f"{sequence:09d}",
                group_control=str(sequence),
                transaction_control=f"{sequence:04d}"[-4:],
                claims=claims,
                payment_date=f"{month}15",
                payer_name=payer_name,
                payer_id=payer_id,
            )
            files[f"history_{payer_id.lower()}_{month}.835"] = _render(spec)
    return files


def synthetic_delay_events() -> list[dict]:
    """Submission dates that exist only as labeled demo records, not as 835 dates."""
    events = []
    for month in ["202507", "202508", "202509", "202510", "202511", "202512"]:
        payment = date(int(month[:4]), int(month[4:6]), 15)
        delayed_control = f"PAYERNORTH-{month}-6"
        timely_control = f"PAYERMETRO-{month}-1"
        events.append(
            {
                "patient_control_number": delayed_control,
                "payer_identifier": "PAYERNORTH",
                "submitted_at": payment - timedelta(days=45),
                "source": "synthetic_demo",
            }
        )
        events.append(
            {
                "patient_control_number": timely_control,
                "payer_identifier": "PAYERMETRO",
                "submitted_at": payment.replace(day=10) if payment.day > 10 else payment,
                "source": "synthetic_demo",
            }
        )
    return events


def synthetic_contract_rules() -> list[dict]:
    return [
        {"payer_identifier": "PAYERNORTH", "procedure_code": "90837", "expected_amount": "120.00"},
        {"payer_identifier": "PAYERHARBOR", "procedure_code": "90837", "expected_amount": "120.00"},
        {"payer_identifier": "PAYERMETRO", "procedure_code": "90837", "expected_amount": "120.00"},
        {"payer_identifier": "PAYERMETRO", "procedure_code": "90834", "expected_amount": "120.00"},
        {"payer_identifier": "PAYERNORTH", "procedure_code": "90834", "expected_amount": "120.00"},
        {"payer_identifier": "PAYERHARBOR", "procedure_code": "90834", "expected_amount": "120.00"},
    ]
