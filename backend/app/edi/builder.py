"""Build valid synthetic X12 835 text for tests and the labeled demo corpus."""

from dataclasses import dataclass, field


@dataclass
class LineSpec:
    procedure: str
    charge: str
    paid: str
    units: str = "1"
    adjustments: list[tuple[str, str, str]] = field(default_factory=list)
    service_date: str = "20250101"
    rarc: str | None = None
    modifiers: list[str] = field(default_factory=list)
    allowed: str | None = None


@dataclass
class ClaimSpec:
    patient_control: str
    status: str
    charge: str
    paid: str
    patient_responsibility: str | None
    payer_claim_control: str
    lines: list[LineSpec]
    filing_indicator: str = "CI"
    facility: str = "11"
    frequency: str = "1"
    patient_last: str = "DOE"
    patient_first: str = "JANE"
    member_id: str = "SYNTH0001"
    authorization_number: str | None = None
    claim_adjustments: list[tuple[str, str, str]] = field(default_factory=list)


@dataclass
class RemitSpec:
    payment_amount: str
    payment_date: str
    trace: str
    payer_name: str
    payer_id: str
    provider_name: str
    provider_npi: str
    claims: list[ClaimSpec]
    plb: list[tuple[str, str, str]] = field(default_factory=list)
    interchange_control: str = "000000001"
    group_control: str = "1"
    transaction_control: str = "0001"
    element_separator: str = "*"
    component_separator: str = ":"
    segment_terminator: str = "~"
    repetition_separator: str = "^"


def build_isa(spec: RemitSpec) -> str:
    element = spec.element_separator
    sender = spec.payer_id.ljust(15)[:15]
    receiver = spec.provider_npi.ljust(15)[:15]
    date = spec.payment_date[2:8]
    parts = [
        "ISA",
        "00",
        "".ljust(10),
        "00",
        "".ljust(10),
        "ZZ",
        sender,
        "ZZ",
        receiver,
        date,
        "1200",
        spec.repetition_separator,
        "00501",
        spec.interchange_control.zfill(9)[:9],
        "0",
        "T",
        spec.component_separator,
    ]
    isa = element.join(parts) + spec.segment_terminator
    if len(isa) != 106:
        raise RuntimeError(f"ISA length {len(isa)} is not 106")
    return isa


def render_remittance(spec: RemitSpec) -> str:
    element = spec.element_separator
    segments: list[list[str]] = []

    def add(parts: list[str]) -> None:
        segments.append(parts)

    add(
        [
            "GS",
            "HP",
            spec.payer_id,
            spec.provider_npi,
            spec.payment_date,
            "1200",
            spec.group_control,
            "X",
            "005010X221A1",
        ]
    )
    st_index = len(segments)
    add(["ST", "835", spec.transaction_control])
    add(
        [
            "BPR",
            "I",
            spec.payment_amount,
            "C",
            "ACH",
            "CCP",
            "01",
            "111111111",
            "DA",
            "222222222",
            spec.payer_id[:10],
            "",
            "01",
            "333333333",
            "DA",
            "444444444",
            spec.payment_date,
        ]
    )
    add(["TRN", "1", spec.trace, spec.payer_id])
    add(["DTM", "405", spec.payment_date])
    add(["N1", "PR", spec.payer_name, "PI", spec.payer_id])
    add(["N1", "PE", spec.provider_name, "XX", spec.provider_npi])
    add(["LX", "1"])
    for claim in spec.claims:
        add(
            [
                "CLP",
                claim.patient_control,
                claim.status,
                claim.charge,
                claim.paid,
                claim.patient_responsibility or "",
                claim.filing_indicator,
                claim.payer_claim_control,
                claim.facility,
                claim.frequency,
            ]
        )
        for group, reason, amount in claim.claim_adjustments:
            add(["CAS", group, reason, amount])
        add(["NM1", "QC", "1", claim.patient_last, claim.patient_first, "", "", "", "MI", claim.member_id])
        if claim.authorization_number:
            add(["REF", "G1", claim.authorization_number])
        for line in claim.lines:
            composite = "HC" + spec.component_separator + line.procedure
            if line.modifiers:
                composite += spec.component_separator + spec.component_separator.join(line.modifiers)
            service = ["SVC", composite, line.charge, line.paid, "", line.units]
            add(service)
            if line.service_date:
                add(["DTM", "472", line.service_date])
            for group, reason, amount in line.adjustments:
                add(["CAS", group, reason, amount])
            if line.allowed is not None:
                add(["AMT", "B6", line.allowed])
            if line.rarc:
                add(["LQ", "HE", line.rarc])
            add(["REF", "6R", f"{claim.patient_control}-{line.procedure}"])
    if spec.plb:
        plb = ["PLB", spec.provider_npi, spec.payment_date]
        for reason, reference, amount in spec.plb:
            composite = reason if not reference else f"{reason}{spec.component_separator}{reference}"
            plb.extend([composite, amount])
        add(plb)
    segment_count = len(segments) - st_index + 1
    add(["SE", str(segment_count), spec.transaction_control])
    add(["GE", "1", spec.group_control])
    add(["IEA", "1", spec.interchange_control.zfill(9)[:9]])
    body = "".join(element.join(parts) + spec.segment_terminator for parts in segments)
    return build_isa(spec) + body
