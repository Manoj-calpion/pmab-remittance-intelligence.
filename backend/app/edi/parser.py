"""Standards-aware X12 835 parser.

Evaluated libraries before writing this parser:

- pyx12 maps generic X12 toward XML and does not enforce 835 balancing or Decimal money.
- edi-835-parser is 835-specific but owns its own models and does not quarantine,
  reconcile provider-level adjustments, or guarantee Decimal arithmetic.
- A focused parser keeps delimiters, money, reconciliation, and source keys under test.

Structural failures raise EDIParseError. Financial imbalances are reported by the
reconciliation module and are still persisted.
"""

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

CLAIM_STATUS_LABELS = {
    "1": "Processed as primary",
    "2": "Processed as secondary",
    "3": "Processed as tertiary",
    "4": "Denied",
    "19": "Processed as primary, forwarded",
    "20": "Processed as secondary, forwarded",
    "21": "Processed as tertiary, forwarded",
    "22": "Reversal of previous payment",
    "23": "Not our claim, forwarded",
    "25": "Predetermination pricing only",
}

TWOPLACES = Decimal("0.01")


class EDIParseError(Exception):
    def __init__(self, message: str, segment: str | None = None) -> None:
        self.segment = segment
        detail = message if segment is None else f"{message} (segment {segment})"
        super().__init__(detail)


@dataclass
class Delimiters:
    element: str
    component: str
    segment: str
    repetition: str


@dataclass
class ParsedAdjustment:
    group_code: str
    reason_code: str
    amount: Decimal
    quantity: Decimal | None = None


@dataclass
class ParsedServiceLine:
    procedure_qualifier: str | None
    procedure_code: str | None
    modifiers: list[str]
    charge_amount: Decimal
    paid_amount: Decimal
    units: Decimal | None = None
    revenue_code: str | None = None
    service_date: date | None = None
    adjustments: list[ParsedAdjustment] = field(default_factory=list)
    rarc_codes: list[str] = field(default_factory=list)
    allowed_amount: Decimal | None = None
    references: dict[str, str] = field(default_factory=dict)


@dataclass
class ParsedClaim:
    patient_control_number: str
    status_code: str
    charge_amount: Decimal
    paid_amount: Decimal
    patient_responsibility: Decimal | None
    filing_indicator: str | None
    payer_claim_control_number: str | None
    facility_type: str | None
    frequency_code: str | None
    patient_last_name: str | None = None
    patient_first_name: str | None = None
    member_id: str | None = None
    adjustments: list[ParsedAdjustment] = field(default_factory=list)
    service_lines: list[ParsedServiceLine] = field(default_factory=list)
    service_date_from: date | None = None
    service_date_to: date | None = None
    received_date: date | None = None
    references: dict[str, str] = field(default_factory=dict)
    remark_codes: list[str] = field(default_factory=list)

    @property
    def status_label(self) -> str:
        return CLAIM_STATUS_LABELS.get(self.status_code, f"Status {self.status_code}")

    @property
    def is_reversal(self) -> bool:
        return self.status_code == "22"


@dataclass
class ParsedProviderAdjustment:
    provider_identifier: str
    fiscal_period: date | None
    reason_code: str
    reference_id: str | None
    amount: Decimal


@dataclass
class ParsedTransaction:
    transaction_control_number: str
    payment_amount: Decimal
    payment_method: str | None
    payment_date: date | None
    credit_debit: str | None
    trace_number: str | None = None
    trace_originator: str | None = None
    payer_name: str | None = None
    payer_identifier: str | None = None
    payee_name: str | None = None
    payee_npi: str | None = None
    payee_tax_id: str | None = None
    production_date: date | None = None
    group_control_number: str | None = None
    claims: list[ParsedClaim] = field(default_factory=list)
    provider_adjustments: list[ParsedProviderAdjustment] = field(default_factory=list)
    segment_count_reported: int | None = None
    segment_count_actual: int | None = None


@dataclass
class ParsedFile:
    interchange_control_number: str
    sender_id: str
    receiver_id: str
    interchange_date: str | None
    usage_indicator: str | None
    transactions: list[ParsedTransaction] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def money(value: str, *, segment: str) -> Decimal:
    text = (value or "").strip()
    if text == "":
        raise EDIParseError("Missing monetary amount", segment)
    try:
        amount = Decimal(text)
    except InvalidOperation as exc:
        raise EDIParseError(f"Invalid monetary amount '{value}'", segment) from exc
    return amount.quantize(TWOPLACES, rounding=ROUND_HALF_UP)


def optional_money(value: str | None, *, segment: str) -> Decimal | None:
    if value is None or value.strip() == "":
        return None
    return money(value, segment=segment)


def optional_decimal(value: str | None) -> Decimal | None:
    if value is None or value.strip() == "":
        return None
    return Decimal(value.strip())


def parse_x12_date(value: str, *, segment: str) -> date:
    text = value.strip()
    if len(text) != 8 or not text.isdigit():
        raise EDIParseError(f"Invalid date '{value}'", segment)
    try:
        return date(int(text[0:4]), int(text[4:6]), int(text[6:8]))
    except ValueError as exc:
        raise EDIParseError(f"Invalid date '{value}'", segment) from exc


def parse_delimiters(text: str) -> tuple[Delimiters, dict[str, str], str]:
    if text.startswith("\ufeff"):
        text = text[1:]
    if not text.startswith("ISA"):
        raise EDIParseError("Interchange does not start with ISA")
    if len(text) < 106:
        raise EDIParseError("ISA segment is shorter than the 106-character X12 envelope")
    element = text[3]
    separator_indexes = (6, 17, 20, 31, 34, 50, 53, 69, 76, 81, 83, 89, 99, 101, 103)
    if any(text[index] != element for index in separator_indexes):
        raise EDIParseError("ISA envelope is not a fixed 106-character segment")
    component = text[104]
    segment = text[105]
    repetition = text[82]
    if len({element, component, segment, repetition}) < 4:
        raise EDIParseError("EDI delimiters must be distinct")
    header = {
        "sender_id": text[35:50].strip(),
        "receiver_id": text[54:69].strip(),
        "interchange_date": text[70:76].strip(),
        "interchange_time": text[77:81].strip(),
        "control_number": text[90:99].strip(),
        "usage_indicator": text[102],
        "version": text[84:89],
    }
    return Delimiters(element, component, segment, repetition), header, text[106:]


def split_segments(payload: str, terminator: str) -> list[str]:
    segments: list[str] = []
    for part in payload.split(terminator):
        segment = part.strip()
        if segment:
            segments.append(segment)
    return segments


def parse_cas(elements: list[str]) -> list[ParsedAdjustment]:
    if len(elements) < 4:
        raise EDIParseError("CAS segment is missing a reason code and amount", "CAS")
    group = elements[1].strip()
    if not group:
        raise EDIParseError("CAS segment is missing a group code", "CAS")
    rest = elements[2:]
    parsed: list[ParsedAdjustment] = []
    index = 0
    while index < len(rest):
        reason = rest[index].strip() if index < len(rest) else ""
        amount_text = rest[index + 1].strip() if index + 1 < len(rest) else ""
        quantity_text = rest[index + 2].strip() if index + 2 < len(rest) else ""
        if reason == "" and amount_text == "":
            break
        if reason == "" or amount_text == "":
            raise EDIParseError("CAS triplet is incomplete", "CAS")
        parsed.append(
            ParsedAdjustment(
                group_code=group,
                reason_code=reason,
                amount=money(amount_text, segment="CAS"),
                quantity=optional_decimal(quantity_text),
            )
        )
        index += 3
    if not parsed:
        raise EDIParseError("CAS segment did not contain an adjustment", "CAS")
    return parsed


def parse_procedure(composite: str, component: str) -> tuple[str | None, str | None, list[str]]:
    parts = [part for part in composite.split(component)]
    if not parts or parts == [""]:
        return None, None, []
    qualifier = parts[0] or None
    code = parts[1] if len(parts) > 1 and parts[1] else None
    modifiers = [part for part in parts[2:] if part]
    return qualifier, code, modifiers


def _element(elements: list[str], index: int) -> str:
    if index >= len(elements):
        return ""
    return elements[index].strip()


def parse_835(content: str) -> ParsedFile:
    delimiters, header, payload = parse_delimiters(content)
    segments = split_segments(payload, delimiters.segment)
    parsed = ParsedFile(
        interchange_control_number=header["control_number"],
        sender_id=header["sender_id"],
        receiver_id=header["receiver_id"],
        interchange_date=header["interchange_date"] or None,
        usage_indicator=header["usage_indicator"],
    )
    group_control: str | None = None
    functional_groups = 0
    transactions_in_group = 0
    transactions_expected: int | None = None
    current: ParsedTransaction | None = None
    claim: ParsedClaim | None = None
    line: ParsedServiceLine | None = None
    segments_in_tx = 0
    seen_iea = False

    def close_claim() -> None:
        nonlocal claim, line
        if claim is not None and current is not None:
            current.claims.append(claim)
        claim = None
        line = None

    for raw in segments:
        elements = raw.split(delimiters.element)
        tag = elements[0].strip()
        if tag == "GS":
            functional_groups += 1
            transactions_in_group = 0
            group_control = _element(elements, 6)
            continue
        if tag == "ST":
            if _element(elements, 1) != "835":
                raise EDIParseError("Only 835 transaction sets are accepted", "ST")
            close_claim()
            if current is not None:
                raise EDIParseError("ST encountered before the previous transaction closed", "ST")
            current = ParsedTransaction(
                transaction_control_number=_element(elements, 2),
                payment_amount=Decimal("0.00"),
                payment_method=None,
                payment_date=None,
                credit_debit=None,
                group_control_number=group_control,
            )
            segments_in_tx = 1
            transactions_in_group += 1
            continue
        if current is None and tag not in {"GE", "IEA"}:
            if tag == "GE":
                pass
            else:
                raise EDIParseError(f"Segment {tag} appeared outside a transaction set", tag)
        if tag not in {"GE", "IEA"} and current is not None:
            segments_in_tx += 1
        if tag == "BPR":
            if current is None:
                raise EDIParseError("BPR outside a transaction set", "BPR")
            current.payment_amount = money(_element(elements, 2), segment="BPR")
            current.credit_debit = _element(elements, 3) or None
            current.payment_method = _element(elements, 4) or None
            payment_date = _element(elements, 16)
            current.payment_date = parse_x12_date(payment_date, segment="BPR") if payment_date else None
        elif tag == "TRN":
            if current is None:
                raise EDIParseError("TRN outside a transaction set", "TRN")
            current.trace_number = _element(elements, 2) or None
            current.trace_originator = _element(elements, 3) or None
        elif tag == "DTM":
            qualifier = _element(elements, 1)
            raw_date = _element(elements, 2)
            parsed_date = parse_x12_date(raw_date, segment="DTM") if raw_date else None
            if line is not None and qualifier == "472":
                line.service_date = parsed_date
            elif claim is not None and qualifier == "232":
                claim.service_date_from = parsed_date
            elif claim is not None and qualifier == "233":
                claim.service_date_to = parsed_date
            elif claim is not None and qualifier == "050":
                claim.received_date = parsed_date
            elif claim is None and current is not None and qualifier == "405":
                current.production_date = parsed_date
        elif tag == "N1":
            entity = _element(elements, 1)
            name = _element(elements, 2) or None
            qualifier = _element(elements, 3)
            identifier = _element(elements, 4) or None
            if claim is not None or current is None:
                continue
            if entity == "PR":
                current.payer_name = name
                if qualifier in {"PI", "XV", "FI"}:
                    current.payer_identifier = identifier
            elif entity == "PE":
                current.payee_name = name
                if qualifier == "XX":
                    current.payee_npi = identifier
                elif qualifier == "FI":
                    current.payee_tax_id = identifier
        elif tag == "NM1":
            entity = _element(elements, 1)
            if claim is None:
                continue
            if entity == "QC":
                claim.patient_last_name = _element(elements, 3) or None
                claim.patient_first_name = _element(elements, 4) or None
                if _element(elements, 8) == "MI":
                    claim.member_id = _element(elements, 9) or None
        elif tag == "CLP":
            if current is None:
                raise EDIParseError("CLP outside a transaction set", "CLP")
            close_claim()
            if len(elements) < 5:
                raise EDIParseError("CLP segment is missing required amounts", "CLP")
            claim = ParsedClaim(
                patient_control_number=_element(elements, 1),
                status_code=_element(elements, 2),
                charge_amount=money(_element(elements, 3), segment="CLP"),
                paid_amount=money(_element(elements, 4), segment="CLP"),
                patient_responsibility=optional_money(_element(elements, 5), segment="CLP"),
                filing_indicator=_element(elements, 6) or None,
                payer_claim_control_number=_element(elements, 7) or None,
                facility_type=_element(elements, 8) or None,
                frequency_code=_element(elements, 9) or None,
            )
            if not claim.patient_control_number or not claim.status_code:
                raise EDIParseError("CLP segment is missing claim identifiers", "CLP")
            line = None
        elif tag == "CAS":
            adjustments = parse_cas(elements)
            if line is not None:
                line.adjustments.extend(adjustments)
            elif claim is not None:
                claim.adjustments.extend(adjustments)
            else:
                raise EDIParseError("CAS segment is not attached to a claim or service line", "CAS")
        elif tag == "SVC":
            if claim is None:
                raise EDIParseError("SVC segment is not attached to a claim", "SVC")
            qualifier, code, modifiers = parse_procedure(_element(elements, 1), delimiters.component)
            line = ParsedServiceLine(
                procedure_qualifier=qualifier,
                procedure_code=code,
                modifiers=modifiers,
                charge_amount=money(_element(elements, 2), segment="SVC"),
                paid_amount=money(_element(elements, 3), segment="SVC"),
                revenue_code=_element(elements, 4) or None,
                units=optional_decimal(_element(elements, 5)),
            )
            claim.service_lines.append(line)
        elif tag == "AMT":
            qualifier = _element(elements, 1)
            if qualifier == "B6" and line is not None:
                line.allowed_amount = money(_element(elements, 2), segment="AMT")
        elif tag == "REF":
            qualifier = _element(elements, 1)
            reference = _element(elements, 2)
            if not qualifier or not reference:
                continue
            claim_level_qualifiers = {"G1", "BB", "EA", "F8", "1K", "CE"}
            if claim is not None and (qualifier in claim_level_qualifiers or line is None):
                claim.references[qualifier] = reference
            elif line is not None:
                line.references[qualifier] = reference
        elif tag == "LQ":
            if _element(elements, 1) == "HE" and _element(elements, 2):
                code = _element(elements, 2)
                if line is not None:
                    line.rarc_codes.append(code)
                elif claim is not None:
                    claim.remark_codes.append(code)
        elif tag == "PLB":
            if current is None:
                raise EDIParseError("PLB outside a transaction set", "PLB")
            close_claim()
            provider_id = _element(elements, 1)
            fiscal = _element(elements, 2)
            fiscal_date = parse_x12_date(fiscal, segment="PLB") if fiscal else None
            rest = elements[3:]
            pair = 0
            while pair < len(rest):
                composite = rest[pair].strip() if pair < len(rest) else ""
                amount_text = rest[pair + 1].strip() if pair + 1 < len(rest) else ""
                if composite == "" and amount_text == "":
                    break
                reason, _, reference = composite.partition(delimiters.component)
                if not reason or amount_text == "":
                    raise EDIParseError("PLB adjustment pair is incomplete", "PLB")
                current.provider_adjustments.append(
                    ParsedProviderAdjustment(
                        provider_identifier=provider_id,
                        fiscal_period=fiscal_date,
                        reason_code=reason,
                        reference_id=reference or None,
                        amount=money(amount_text, segment="PLB"),
                    )
                )
                pair += 2
        elif tag == "SE":
            if current is None:
                raise EDIParseError("SE without a transaction set", "SE")
            close_claim()
            reported = int(_element(elements, 1) or "0")
            control = _element(elements, 2)
            current.segment_count_reported = reported
            current.segment_count_actual = segments_in_tx
            if reported != segments_in_tx:
                raise EDIParseError(
                    f"SE01 count {reported} does not match actual segment count {segments_in_tx}",
                    "SE",
                )
            if control and control != current.transaction_control_number:
                raise EDIParseError("SE control number does not match ST", "SE")
            if current.trace_number is None:
                parsed.warnings.append(
                    f"Transaction {current.transaction_control_number} has no TRN trace number"
                )
            parsed.transactions.append(current)
            current = None
            claim = None
            line = None
        elif tag == "GE":
            transactions_expected = int(_element(elements, 1) or "0")
            if transactions_expected != transactions_in_group:
                raise EDIParseError(
                    f"GE01 count {transactions_expected} does not match {transactions_in_group} transaction sets",
                    "GE",
                )
            ge_control = _element(elements, 2)
            if group_control and ge_control and ge_control != group_control:
                raise EDIParseError("GE control number does not match GS", "GE")
        elif tag == "IEA":
            seen_iea = True
            group_count = int(_element(elements, 1) or "0")
            iea_control = _element(elements, 2)
            if group_count != functional_groups:
                raise EDIParseError(
                    f"IEA01 count {group_count} does not match {functional_groups} functional groups",
                    "IEA",
                )
            if iea_control.lstrip("0") != header["control_number"].lstrip("0"):
                raise EDIParseError("IEA control number does not match ISA", "IEA")
        elif tag in {"PER", "N3", "N4", "LX", "TS3", "TS2", "CUR", "RDM"}:
            continue
        else:
            parsed.warnings.append(f"Ignored unrecognized segment {tag}")

    if current is not None:
        raise EDIParseError("Transaction set was not closed with SE")
    if not seen_iea:
        raise EDIParseError("Interchange was not closed with IEA")
    if not parsed.transactions:
        raise EDIParseError("No 835 transaction sets were found")
    return parsed
