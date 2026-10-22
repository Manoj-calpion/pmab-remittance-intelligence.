"""Idempotent 835 ingestion, persistence, and reconciliation."""

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.denials.engine import DenialAssessment, MappingRule, assess_denial
from app.edi.parser import EDIParseError, ParsedClaim, ParsedFile, ParsedTransaction, parse_835
from app.edi.reconciliation import ReconciliationCheck, reconcile_file, rollup_status
from app.integrations.storage import build_stored_filename, get_storage, sha256_digest
from app.models import (
    AuthorizationReference,
    Claim,
    ClaimAdjustment,
    ClaimServiceLine,
    DenialCategoryMapping,
    EdiTransaction,
    EraRecord,
    IngestionCheckpoint,
    Payer,
    ProcessingError,
    Provider,
    ProviderLevelAdjustment,
    ReconciliationResult,
    RemittanceFile,
    RemittancePayment,
    ServiceLineAdjustment,
)


@dataclass
class IngestResult:
    status: str
    file_id: str | None
    sha256: str
    message: str
    claim_count: int = 0
    reconciliation_status: str | None = None


def lifecycle_label(status: str, reconciliation_status: str | None = None) -> str:
    """Map stored file status onto the operator-facing lifecycle.

    Stored statuses stay stable for existing calculations and tests.
    """
    if status == "duplicate":
        return "DUPLICATE"
    if status == "quarantined":
        return "QUARANTINED"
    if status == "failed":
        return "FAILED"
    if status == "parsed_out_of_balance" or reconciliation_status == "out_of_balance":
        return "REQUIRES_REVIEW"
    if status == "parsed":
        return "COMPLETED"
    return "RECEIVED"


def _trace(stages: list[tuple[str, datetime]]) -> list[dict]:
    return [{"stage": name, "at": moment.isoformat()} for name, moment in stages]


def load_mapping_rules(db: Session) -> dict[tuple[str, str], MappingRule]:
    rows = db.scalars(select(DenialCategoryMapping)).all()
    best: dict[tuple[str, str], DenialCategoryMapping] = {}
    for row in rows:
        key = (row.code_type, row.code)
        current = best.get(key)
        if current is None or row.version > current.version:
            best[key] = row
    return {
        key: MappingRule(row.category, row.is_denial, row.version, row.effective_from, row.effective_to)
        for key, row in best.items()
    }


def _get_or_create_payer(db: Session, identifier: str | None, name: str | None) -> Payer | None:
    if not identifier and not name:
        return None
    ident = identifier or f"NAME::{name}"
    row = db.scalar(select(Payer).where(Payer.payer_identifier == ident))
    if row is None:
        row = Payer(payer_identifier=ident, name=name or ident)
        db.add(row)
        db.flush()
    elif name and row.name != name:
        row.name = name
    return row


def _get_or_create_provider(db: Session, name: str | None, npi: str | None, tax_id: str | None) -> Provider | None:
    if npi:
        row = db.scalar(select(Provider).where(Provider.npi == npi))
        if row is None:
            row = Provider(name=name or npi, npi=npi, tax_id=tax_id)
            db.add(row)
            db.flush()
        return row
    return None


def _claim_adjustments(claim: ParsedClaim) -> list[tuple[str, str, Decimal]]:
    items = [(item.group_code, item.reason_code, item.amount) for item in claim.adjustments]
    for line in claim.service_lines:
        items.extend((item.group_code, item.reason_code, item.amount) for item in line.adjustments)
    return items


def _apply_assessment(target, assessment: DenialAssessment) -> None:
    target.is_denied = assessment.is_denied
    target.denial_scope = assessment.scope
    target.denied_amount = assessment.denied_amount
    target.primary_denial_category = assessment.primary_category
    target.primary_carc = assessment.primary_carc


def ingest_content(
    db: Session,
    content: bytes,
    filename: str,
    *,
    source_system: str,
    source_record_id: str | None,
    settings: Settings | None = None,
    job_id=None,
) -> IngestResult:
    active = settings or get_settings()
    digest = sha256_digest(content)
    existing = db.scalar(select(RemittanceFile).where(RemittanceFile.sha256 == digest))
    if existing is not None:
        if source_record_id:
            era_exists = db.scalar(
                select(EraRecord).where(
                    EraRecord.source_system == source_system,
                    EraRecord.source_record_id == source_record_id,
                )
            )
            if era_exists is None:
                db.add(
                    EraRecord(
                        source_system=source_system,
                        source_record_id=source_record_id,
                        status="duplicate",
                        watermark_value=source_record_id,
                        attributes={"duplicate_of_file_id": str(existing.id), "sha256": digest, "original_filename": filename},
                    )
                )
                db.commit()
        return IngestResult(
            status="duplicate",
            file_id=str(existing.id),
            sha256=digest,
            message="File hash already exists. Claims were not inserted again.",
            claim_count=0,
            reconciliation_status=existing.reconciliation_status,
        )

    received_at = datetime.now(UTC)
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError:
        text = None
    parsed: ParsedFile | None = None
    parse_error: str | None = None
    if text is None:
        parse_error = "File is not valid UTF-8 text. Raw EDI was not written to the error log."
    else:
        try:
            parsed = parse_835(text)
        except EDIParseError as exc:
            parse_error = str(exc)[:500]
    validated_at = datetime.now(UTC)

    payment_date = parsed.transactions[0].payment_date if parsed and parsed.transactions else None
    control_number = parsed.interchange_control_number if parsed else None
    stored_name = build_stored_filename(
        active.stored_filename_pattern,
        original_filename=filename,
        payment_date=payment_date,
        control_number=control_number,
        digest=digest,
    )
    storage = get_storage(active)
    uri = storage.put(stored_name, content)
    payer = None
    provider = None
    if parsed and parsed.transactions:
        first = parsed.transactions[0]
        payer = _get_or_create_payer(db, first.payer_identifier or parsed.sender_id, first.payer_name)
        provider = _get_or_create_provider(db, first.payee_name, first.payee_npi, first.payee_tax_id)

    era = EraRecord(
        source_system=source_system,
        source_record_id=source_record_id or digest[:16],
        payer_id=payer.id if payer else None,
        payment_date=payment_date,
        payment_amount=parsed.transactions[0].payment_amount if parsed and parsed.transactions else None,
        trace_number=parsed.transactions[0].trace_number if parsed and parsed.transactions else None,
        status="quarantined" if parse_error else "parsed",
        watermark_value=source_record_id,
        attributes={"original_filename": filename, "sha256": digest, "lifecycle": "VALIDATING"},
    )
    db.add(era)
    db.flush()
    file_row = RemittanceFile(
        era_record_id=era.id,
        original_filename=filename,
        stored_filename=stored_name,
        storage_uri=uri,
        sha256=digest,
        file_size=len(content),
        status="quarantined" if parse_error else "received",
        source_system=source_system,
        source_record_id=source_record_id,
        received_at=received_at,
    )
    db.add(file_row)
    db.flush()
    if parse_error or parsed is None:
        finished = datetime.now(UTC)
        era.attributes = {
            **(era.attributes or {}),
            "lifecycle": "QUARANTINED",
            "duration_ms": int((finished - received_at).total_seconds() * 1000),
            "record_counts": {"claims": 0, "transactions": 0},
            "failure_reason": parse_error or "Unknown parse failure",
            "stages": _trace(
                [
                    ("RECEIVED", received_at),
                    ("VALIDATING", received_at),
                    ("PARSING", validated_at),
                    ("QUARANTINED", finished),
                ]
            ),
        }
        db.add(
            ProcessingError(
                job_id=job_id,
                remittance_file_id=file_row.id,
                stage="parse",
                message=parse_error or "Unknown parse failure",
                detail={"filename": filename},
            )
        )
        db.commit()
        return IngestResult("quarantined", str(file_row.id), digest, parse_error or "Quarantined", 0, "quarantined")

    from app.seed.reference import ensure_denial_mappings

    ensure_denial_mappings(db)
    checks = reconcile_file(parsed, active.reconciliation_tolerance)
    status = rollup_status(checks)
    mappings = load_mapping_rules(db)
    claim_ids: dict[tuple[str, str], object] = {}
    claim_count = 0
    for transaction in parsed.transactions:
        tx_row = _persist_transaction(db, file_row, parsed, transaction, payer, provider)
        for claim in transaction.claims:
            claim_row = _persist_claim(db, tx_row, claim, mappings, active, filename, digest, parsed)
            claim_ids[(transaction.transaction_control_number, claim.patient_control_number)] = claim_row.id
            claim_count += 1
            if "G1" in claim.references:
                db.add(
                    AuthorizationReference(
                        patient_control_number=claim.patient_control_number,
                        authorization_number=claim.references["G1"],
                        payer_id=tx_row.payer_id,
                        status="present_on_remittance",
                        source="remittance_ref",
                    )
                )
        _persist_checks(db, file_row.id, tx_row.id, checks, transaction, claim_ids)

    file_row.status = "parsed" if status == "balanced" else "parsed_out_of_balance"
    file_row.reconciliation_status = status
    finished = datetime.now(UTC)
    file_row.parsed_at = finished
    era.status = file_row.status
    lifecycle = lifecycle_label(file_row.status, status)
    era.attributes = {
        **(era.attributes or {}),
        "lifecycle": lifecycle,
        "duration_ms": int((finished - received_at).total_seconds() * 1000),
        "record_counts": {"claims": claim_count, "transactions": len(parsed.transactions)},
        "stages": _trace(
            [
                ("RECEIVED", received_at),
                ("VALIDATING", received_at),
                ("PARSING", validated_at),
                ("NORMALIZING", validated_at),
                ("ANALYZING", finished),
                (lifecycle, finished),
            ]
        ),
    }
    db.commit()
    return IngestResult("parsed", str(file_row.id), digest, "Parsed and stored", claim_count, status)


def _persist_transaction(db, file_row, parsed: ParsedFile, transaction: ParsedTransaction, payer, provider) -> EdiTransaction:
    if transaction.payer_identifier or transaction.payer_name:
        payer = _get_or_create_payer(db, transaction.payer_identifier or parsed.sender_id, transaction.payer_name)
    if transaction.payee_npi:
        provider = _get_or_create_provider(db, transaction.payee_name, transaction.payee_npi, transaction.payee_tax_id)
    row = EdiTransaction(
        remittance_file_id=file_row.id,
        interchange_control_number=parsed.interchange_control_number,
        group_control_number=transaction.group_control_number,
        transaction_control_number=transaction.transaction_control_number,
        payment_method=transaction.payment_method,
        payment_amount=transaction.payment_amount,
        payment_date=transaction.payment_date,
        credit_debit=transaction.credit_debit,
        trace_number=transaction.trace_number,
        payer_id=payer.id if payer else None,
        provider_id=provider.id if provider else None,
        production_date=transaction.production_date,
    )
    db.add(row)
    db.flush()
    db.add(
        RemittancePayment(
            edi_transaction_id=row.id,
            payment_method=transaction.payment_method,
            amount=transaction.payment_amount,
            payment_date=transaction.payment_date,
            trace_number=transaction.trace_number,
            originator_id=transaction.trace_originator,
            credit_debit_flag=transaction.credit_debit,
        )
    )
    for item in transaction.provider_adjustments:
        db.add(
            ProviderLevelAdjustment(
                edi_transaction_id=row.id,
                provider_identifier=item.provider_identifier,
                fiscal_period=item.fiscal_period,
                reason_code=item.reason_code,
                reference_id=item.reference_id,
                amount=item.amount,
            )
        )
    return row


def _persist_claim(db, tx_row, claim: ParsedClaim, mappings, settings: Settings, filename: str, digest: str, parsed: ParsedFile) -> Claim:
    assessment = assess_denial(
        status_code=claim.status_code,
        charge_amount=claim.charge_amount,
        paid_amount=claim.paid_amount,
        patient_responsibility=claim.patient_responsibility,
        adjustments=_claim_adjustments(claim),
        mappings=mappings,
        count_partial=settings.count_partial_denials,
        as_of=claim.service_date_from,
    )
    row = Claim(
        edi_transaction_id=tx_row.id,
        patient_control_number=claim.patient_control_number,
        payer_claim_control_number=claim.payer_claim_control_number,
        claim_status_code=claim.status_code,
        claim_status_label=claim.status_label,
        total_charge=claim.charge_amount,
        payment_amount=claim.paid_amount,
        patient_responsibility=claim.patient_responsibility,
        claim_filing_indicator=claim.filing_indicator,
        facility_type=claim.facility_type,
        frequency_code=claim.frequency_code,
        patient_last_name=claim.patient_last_name,
        patient_first_name=claim.patient_first_name,
        member_id=claim.member_id,
        service_date_from=claim.service_date_from or (claim.service_lines[0].service_date if claim.service_lines else None),
        service_date_to=claim.service_date_to,
        received_date=claim.received_date,
        is_reversal=claim.is_reversal,
        source_references={
            "original_filename": filename,
            "sha256": digest,
            "interchange_control_number": parsed.interchange_control_number,
            "transaction_control_number": tx_row.transaction_control_number,
            "trace_number": tx_row.trace_number,
            "reference_qualifiers": sorted(claim.references.keys()),
        },
    )
    _apply_assessment(row, assessment)
    db.add(row)
    db.flush()
    for sequence, item in enumerate(assessment.adjustments, start=1):
        if any(adj.reason_code == item.reason_code and adj.amount == item.amount for adj in claim.adjustments):
            db.add(
                ClaimAdjustment(
                    claim_id=row.id,
                    group_code=item.group_code,
                    reason_code=item.reason_code,
                    amount=item.amount,
                    sequence=sequence,
                    category=item.category,
                    is_denial=item.is_denial,
                )
            )
    line_adjustments = {id(line): [] for line in claim.service_lines}
    classified_lines = []
    for line in claim.service_lines:
        pairs = [(item.group_code, item.reason_code, item.amount) for item in line.adjustments]
        line_assessment = assess_denial(
            status_code=claim.status_code,
            charge_amount=line.charge_amount,
            paid_amount=line.paid_amount,
            patient_responsibility=None,
            adjustments=pairs,
            mappings=mappings,
            count_partial=settings.count_partial_denials,
            as_of=line.service_date,
        )
        classified_lines.append((line, line_assessment))
    for index, (line, line_assessment) in enumerate(classified_lines, start=1):
        line_row = ClaimServiceLine(
            claim_id=row.id,
            line_number=index,
            procedure_code=line.procedure_code,
            modifiers=":".join(line.modifiers) if line.modifiers else None,
            revenue_code=line.revenue_code,
            charge_amount=line.charge_amount,
            paid_amount=line.paid_amount,
            units=line.units,
            service_date=line.service_date,
            allowed_amount=line.allowed_amount,
            remark_codes=line.rarc_codes,
        )
        _apply_assessment(line_row, line_assessment)
        db.add(line_row)
        db.flush()
        for item in line_assessment.adjustments:
            db.add(
                ServiceLineAdjustment(
                    service_line_id=line_row.id,
                    group_code=item.group_code,
                    reason_code=item.reason_code,
                    amount=item.amount,
                    category=item.category,
                    is_denial=item.is_denial,
                )
            )
        line_adjustments[id(line)].append(line_row.id)
    return row


def _persist_checks(db, file_id, transaction_id, checks: list[ReconciliationCheck], transaction: ParsedTransaction, claim_ids) -> None:
    relevant = [
        check
        for check in checks
        if check.entity_key == transaction.transaction_control_number
        or check.entity_key in {claim.patient_control_number for claim in transaction.claims}
        or any(check.entity_key.startswith(f"{claim.patient_control_number}:") for claim in transaction.claims)
    ]
    for check in relevant:
        claim_id = None
        control = check.entity_key.split(":", 1)[0]
        claim_id = claim_ids.get((transaction.transaction_control_number, control))
        db.add(
            ReconciliationResult(
                remittance_file_id=file_id,
                edi_transaction_id=transaction_id,
                claim_id=claim_id,
                scope=check.scope,
                status=check.status,
                expected_amount=check.expected_amount,
                actual_amount=check.actual_amount,
                difference=check.difference,
                detail=check.detail,
            )
        )


def retry_quarantined(db: Session, file_id, settings: Settings | None = None) -> IngestResult:
    """Re-read a quarantined original and parse it again.

    Parsed files are left untouched so a retry cannot duplicate claims.
    The stored bytes are deleted from the database only after they have been
    read back. A still-malformed file is quarantined again.
    """
    row = db.get(RemittanceFile, file_id)
    if row is None:
        raise LookupError("Remittance file was not found.")
    if row.status != "quarantined":
        return IngestResult(
            status="not_retryable",
            file_id=str(row.id),
            sha256=row.sha256,
            message="Only quarantined files can be retried. Parsed claims were not inserted again.",
            reconciliation_status=row.reconciliation_status,
        )
    active = settings or get_settings()
    content = get_storage(active).get(row.storage_uri)
    filename = row.original_filename
    source_system = row.source_system
    source_record_id = row.source_record_id
    era_id = row.era_record_id
    db.execute(delete(ProcessingError).where(ProcessingError.remittance_file_id == row.id))
    db.delete(row)
    db.flush()
    if era_id is not None:
        era = db.get(EraRecord, era_id)
        if era is not None:
            db.delete(era)
    db.commit()
    return ingest_content(
        db,
        content,
        filename,
        source_system=source_system,
        source_record_id=source_record_id,
        settings=active,
    )


def known_source_ids(db: Session, source_system: str) -> set[str]:
    file_ids = db.scalars(select(RemittanceFile.source_record_id).where(RemittanceFile.source_system == source_system)).all()
    era_ids = db.scalars(select(EraRecord.source_record_id).where(EraRecord.source_system == source_system)).all()
    return {row for row in [*file_ids, *era_ids] if row}


def update_checkpoint(db: Session, source_system: str, watermark: str) -> None:
    row = db.scalar(
        select(IngestionCheckpoint).where(
            IngestionCheckpoint.source_system == source_system,
            IngestionCheckpoint.checkpoint_name == "era_watermark",
        )
    )
    if row is None:
        db.add(IngestionCheckpoint(source_system=source_system, checkpoint_name="era_watermark", watermark_value=watermark))
    elif watermark > row.watermark_value:
        row.watermark_value = watermark


def ingest_directory(db: Session, directory: Path, source_system: str, job_id=None) -> dict:
    from app.integrations.connectors import LocalFileConnector, MockCentralReachConnector

    if source_system == "mock_central_reach":
        connector = MockCentralReachConnector(directory)
    else:
        connector = LocalFileConnector(directory)
    from app.integrations.connectors import ALLOWED_SUFFIXES

    known = known_source_ids(db, connector.source_system)
    records = connector.list_records(known)
    skipped_known = 0
    if directory.is_dir():
        skipped_known = sum(
            1
            for path in directory.iterdir()
            if path.is_file() and path.suffix.lower() in ALLOWED_SUFFIXES and path.name in known
        )
    stats = {
        "discovered": len(records),
        "parsed": 0,
        "quarantined": 0,
        "duplicates": 0,
        "failed": 0,
        "skipped_known": skipped_known,
    }
    for record in records:
        try:
            result = ingest_content(
                db,
                record.content,
                record.filename,
                source_system=connector.source_system,
                source_record_id=record.source_record_id,
                job_id=job_id,
            )
        except Exception as exc:
            db.rollback()
            stats["failed"] += 1
            db.add(ProcessingError(job_id=job_id, stage="ingest", message=str(exc)[:500], detail={"filename": record.filename}))
            db.commit()
            continue
        if result.status == "parsed":
            stats["parsed"] += 1
        elif result.status == "quarantined":
            stats["quarantined"] += 1
        elif result.status == "duplicate":
            stats["duplicates"] += 1
        else:
            stats["failed"] += 1
        update_checkpoint(db, connector.source_system, record.watermark)
        db.commit()
    return stats
