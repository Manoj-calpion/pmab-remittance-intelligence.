"""HTTP API for remittance intelligence."""

import csv
import io
from datetime import date
from decimal import Decimal
from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, Depends, File, Query, Request, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.agents.graph import investigate
from app.agents.llm import BedrockApprovalError, LLMError
from app.alerts.service import sync_alerts
from app.analytics.service import (
    AnalyticsFilter,
    anomaly_analytics,
    category_slice,
    denial_analytics,
    overview,
    payer_analytics,
    payment_delay_analytics,
    underpayment_analytics,
)
from app.api.deps import get_current_user, require_permission
from app.api.errors import AppError
from app.core.config import get_settings
from app.core.database import get_db
from app.core.phi import mask_identifier, mask_name
from app.core.security import PERMISSIONS, authenticate
from app.ingestion.archive import ArchiveError, expand_upload
from app.ingestion.pipeline import ingest_content, ingest_directory, lifecycle_label, retry_quarantined
from app.integrations.connectors import CentralReachAPIConnector, IntegrationDisabledError
from app.models import (
    AiInsight,
    AiInvestigation,
    Alert,
    AuditLog,
    Claim,
    ClaimServiceLine,
    DenialCategoryMapping,
    EdiTransaction,
    EraRecord,
    Payer,
    PayerContract,
    ProcessingError,
    ProcessingJob,
    ReconciliationResult,
    ReimbursementRule,
    RemittanceFile,
    User,
)
from app.models.base import utcnow
from app.reporting.exports import build_report, to_csv, to_pdf, to_xlsx
from app.seed.reference import ensure_denial_mappings

router = APIRouter()
ALLOWED_UPLOADS = {".835", ".edi", ".txt", ".x12", ".zip"}
REPORTS = {
    "daily_remittance",
    "weekly_denial",
    "monthly_payer",
    "underpayment_exception",
    "authorization_denial",
    "coding_denial",
    "reconciliation",
}


class LoginRequest(BaseModel):
    email: str
    password: str


class QuestionRequest(BaseModel):
    question: str = Field(min_length=8, max_length=1000)


class AlertUpdate(BaseModel):
    status: str | None = None
    assigned_to: UUID | None = None


class ProcessRequest(BaseModel):
    source: str = "local_directory"
    path: str | None = None


class ContractRequest(BaseModel):
    payer_identifier: str
    payer_name: str
    procedure_code: str
    expected_amount: Decimal | None = None
    percent_of_billed: Decimal | None = None
    effective_from: date
    effective_to: date | None = None
    source_label: str
    is_approved: bool = False


class MappingUpdate(BaseModel):
    category: str
    is_denial: bool
    notes: str = ""


def filters(
    date_from: date | None = None,
    date_to: date | None = None,
    payer_id: UUID | None = None,
    provider_id: UUID | None = None,
    procedure_code: str | None = None,
    denial_category: str | None = None,
    location_id: UUID | None = None,
) -> AnalyticsFilter:
    return AnalyticsFilter(date_from, date_to, payer_id, provider_id, procedure_code, denial_category, location_id)


def _audit(db: Session, user: User | None, action: str, resource_type: str, resource_id: str | None, request: Request, detail: dict | None = None) -> None:
    db.add(
        AuditLog(
            actor_id=user.id if user else None,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            ip_address=request.client.host if request.client else None,
            detail=detail or {},
        )
    )


def _page(items: list, total: int, page: int, page_size: int) -> dict:
    return {"items": items, "total": total, "page": page, "page_size": page_size}


@router.get("/health")
def health(db: Session = Depends(get_db)) -> dict:
    from app.core.database import check_database

    check_database()
    settings = get_settings()
    return {
        "status": "ok",
        "environment": settings.environment,
        "demo_mode": settings.demo_mode,
        "database": "ok",
        "db_dialect": db.bind.dialect.name if db.bind is not None else "unknown",
    }


@router.get("/meta")
def meta() -> dict:
    settings = get_settings()
    central_reach = "disabled"
    try:
        CentralReachAPIConnector(settings.central_reach_api_enabled).list_records()
    except IntegrationDisabledError as exc:
        central_reach = str(exc)
    return {
        "demo_mode": settings.demo_mode,
        "llm_provider": settings.llm_provider,
        "bedrock_phi_approved": settings.bedrock_phi_approved,
        "storage_backend": settings.storage_backend,
        "central_reach_status": central_reach,
        "ingestion_mode": "downloaded_835_files",
        "ingestion_note": "Primary source is downloaded X12 835 files. Live Central Reach retrieval stays a separate client-managed connector.",
        "filename_pattern": settings.stored_filename_pattern,
        "filename_pattern_note": "The default PLUTUS pattern is a platform default. Confirm the organization's file naming convention before production.",
        **(
            {
                "demo_email": "analyst@pmab.demo",
                "demo_password": settings.demo_analyst_password,
            }
            if settings.demo_mode
            else {}
        ),
    }


@router.post("/auth/login")
def login(body: LoginRequest, request: Request, db: Session = Depends(get_db)) -> dict:
    result = authenticate(db, body.email, body.password)
    if result is None:
        _audit(db, None, "login_failed", "user", None, request, {"email": body.email.lower()})
        db.commit()
        settings = get_settings()
        message = "The email or password is incorrect."
        if settings.demo_mode:
            message = (
                "The email or password is incorrect. "
                f"Demo sign-in is analyst@pmab.demo with password {settings.demo_analyst_password}."
            )
        raise AppError(401, "unauthorized", message)
    token, user = result
    _audit(db, user, "login", "user", str(user.id), request)
    db.commit()
    return {"access_token": token, "token_type": "bearer", "role": user.role.name, "email": user.email}


@router.get("/auth/me")
def me(user: User = Depends(get_current_user)) -> dict:
    role_name = user.role.name if user.role else "viewer"
    return {"id": str(user.id), "email": user.email, "full_name": user.full_name, "role": role_name, "permissions": sorted(PERMISSIONS.get(role_name, set()))}


@router.get("/analytics/overview")
def analytics_overview(
    selected: AnalyticsFilter = Depends(filters),
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("analytics:read")),
) -> dict:
    return overview(db, selected)


@router.get("/analytics/denials")
def analytics_denials(selected: AnalyticsFilter = Depends(filters), db: Session = Depends(get_db), _: User = Depends(require_permission("analytics:read"))) -> dict:
    return denial_analytics(db, selected)


@router.get("/analytics/payers")
def analytics_payers(selected: AnalyticsFilter = Depends(filters), db: Session = Depends(get_db), _: User = Depends(require_permission("analytics:read"))) -> dict:
    return payer_analytics(db, selected)


@router.get("/analytics/payment-delays")
def analytics_delays(selected: AnalyticsFilter = Depends(filters), db: Session = Depends(get_db), _: User = Depends(require_permission("analytics:read"))) -> dict:
    return payment_delay_analytics(db, selected)


@router.get("/analytics/underpayments")
def analytics_underpayments(selected: AnalyticsFilter = Depends(filters), db: Session = Depends(get_db), _: User = Depends(require_permission("analytics:read"))) -> dict:
    return underpayment_analytics(db, selected)


@router.get("/analytics/anomalies")
def analytics_anomalies(selected: AnalyticsFilter = Depends(filters), db: Session = Depends(get_db), _: User = Depends(require_permission("analytics:read"))) -> dict:
    return anomaly_analytics(db, selected)


@router.get("/analytics/authorization")
def analytics_authorization(selected: AnalyticsFilter = Depends(filters), db: Session = Depends(get_db), _: User = Depends(require_permission("analytics:read"))) -> dict:
    return category_slice(db, selected, "authorization")


@router.get("/analytics/coding")
def analytics_coding(selected: AnalyticsFilter = Depends(filters), db: Session = Depends(get_db), _: User = Depends(require_permission("analytics:read"))) -> dict:
    return category_slice(db, selected, "coding")


@router.get("/remittances")
def list_remittances(
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    status: str | None = None,
    lifecycle: str | None = None,
    q: str | None = None,
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("remittances:read")),
) -> dict:
    statement = select(RemittanceFile)
    count_statement = select(func.count()).select_from(RemittanceFile)
    if lifecycle:
        mapped = _status_for_lifecycle(lifecycle)
        statement = statement.where(RemittanceFile.status == mapped)
        count_statement = count_statement.where(RemittanceFile.status == mapped)
    elif status:
        statement = statement.where(RemittanceFile.status == status)
        count_statement = count_statement.where(RemittanceFile.status == status)
    if q:
        statement = statement.where(RemittanceFile.original_filename.ilike(f"%{q.strip()}%"))
        count_statement = count_statement.where(RemittanceFile.original_filename.ilike(f"%{q.strip()}%"))
    total = db.scalar(count_statement) or 0
    rows = db.scalars(statement.order_by(RemittanceFile.received_at.desc()).offset((page - 1) * page_size).limit(page_size)).all()
    return _page(
        [
            {
                "id": str(row.id),
                "original_filename": row.original_filename,
                "stored_filename": row.stored_filename,
                "status": row.status,
                "reconciliation_status": row.reconciliation_status,
                "sha256": row.sha256,
                "source_system": row.source_system,
                "source_record_id": row.source_record_id,
                "file_size": row.file_size,
                "received_at": row.received_at.isoformat() if row.received_at else None,
                "parsed_at": row.parsed_at.isoformat() if row.parsed_at else None,
                "lifecycle": lifecycle_label(row.status, row.reconciliation_status),
            }
            for row in rows
        ],
        total,
        page,
        page_size,
    )


@router.get("/remittances/{file_id}")
def get_remittance(file_id: UUID, db: Session = Depends(get_db), _: User = Depends(require_permission("remittances:read"))) -> dict:
    row = db.get(RemittanceFile, file_id)
    if row is None:
        raise AppError(404, "not_found", "Remittance file was not found.")
    checks = db.scalars(select(ReconciliationResult).where(ReconciliationResult.remittance_file_id == row.id)).all()
    errors = db.scalars(select(ProcessingError).where(ProcessingError.remittance_file_id == row.id)).all()
    era = db.get(EraRecord, row.era_record_id) if row.era_record_id else None
    transactions = db.scalars(select(EdiTransaction).where(EdiTransaction.remittance_file_id == row.id)).all()
    claim_rows = db.execute(
        select(Claim, EdiTransaction, Payer)
        .join(EdiTransaction, Claim.edi_transaction_id == EdiTransaction.id)
        .outerjoin(Payer, EdiTransaction.payer_id == Payer.id)
        .where(EdiTransaction.remittance_file_id == row.id)
        .order_by(Claim.created_at.asc())
    ).all()
    trace = (era.attributes or {}).get("stages") if era and era.attributes else None
    return {
        "id": str(row.id),
        "original_filename": row.original_filename,
        "stored_filename": row.stored_filename,
        "status": row.status,
        "lifecycle": lifecycle_label(row.status, row.reconciliation_status),
        "reconciliation_status": row.reconciliation_status,
        "sha256": row.sha256,
        "source_system": row.source_system,
        "file_size": row.file_size,
        "received_at": row.received_at.isoformat() if row.received_at else None,
        "parsed_at": row.parsed_at.isoformat() if row.parsed_at else None,
        "duration_ms": (era.attributes or {}).get("duration_ms") if era and era.attributes else None,
        "record_counts": (era.attributes or {}).get("record_counts") if era and era.attributes else None,
        "stages": trace
        or [
            {"stage": "RECEIVED", "at": row.received_at.isoformat() if row.received_at else None},
            {"stage": lifecycle_label(row.status, row.reconciliation_status), "at": row.parsed_at.isoformat() if row.parsed_at else None},
        ],
        "payment_amount": f"{sum((item.payment_amount for item in transactions), Decimal('0.00')):.2f}" if transactions else None,
        "trace_numbers": [item.trace_number for item in transactions if item.trace_number],
        "claims": [_claim_payload(claim, transaction, payer, False) for claim, transaction, payer in claim_rows],
        "reconciliation": [
            {
                "scope": item.scope,
                "status": item.status,
                "expected_amount": f"{item.expected_amount:.2f}",
                "actual_amount": f"{item.actual_amount:.2f}",
                "difference": f"{item.difference:.2f}",
            }
            for item in checks
        ],
        "errors": [{"stage": item.stage, "message": item.message} for item in errors],
    }


@router.get("/claims")
def list_claims(
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    selected: AnalyticsFilter = Depends(filters),
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("claims:read")),
) -> dict:
    statement = select(Claim, EdiTransaction, Payer).join(EdiTransaction, Claim.edi_transaction_id == EdiTransaction.id).outerjoin(Payer, EdiTransaction.payer_id == Payer.id)
    if selected.payer_id:
        statement = statement.where(EdiTransaction.payer_id == selected.payer_id)
    if selected.denial_category:
        statement = statement.where(Claim.primary_denial_category == selected.denial_category)
    rows = db.execute(statement.order_by(Claim.created_at.desc())).all()
    start = (page - 1) * page_size
    can_view_phi = "phi:view" in PERMISSIONS.get(user.role.name if user.role else "", set())
    items = [_claim_payload(claim, transaction, payer, can_view_phi) for claim, transaction, payer in rows[start : start + page_size]]
    return _page(items, len(rows), page, page_size)


@router.get("/claims/{claim_id}")
def get_claim(claim_id: UUID, db: Session = Depends(get_db), user: User = Depends(require_permission("claims:read"))) -> dict:
    claim = db.get(Claim, claim_id)
    if claim is None:
        raise AppError(404, "not_found", "Claim was not found.")
    transaction = db.get(EdiTransaction, claim.edi_transaction_id)
    payer = db.get(Payer, transaction.payer_id) if transaction and transaction.payer_id else None
    can_view_phi = "phi:view" in PERMISSIONS.get(user.role.name if user.role else "", set())
    lines = db.scalars(select(ClaimServiceLine).where(ClaimServiceLine.claim_id == claim.id).order_by(ClaimServiceLine.line_number)).all()
    payload = _claim_payload(claim, transaction, payer, can_view_phi)
    payload["service_lines"] = [
        {
            "line_number": line.line_number,
            "procedure_code": line.procedure_code,
            "charge_amount": f"{line.charge_amount:.2f}",
            "paid_amount": f"{line.paid_amount:.2f}",
            "allowed_amount": f"{line.allowed_amount:.2f}" if line.allowed_amount is not None else None,
            "is_denied": line.is_denied,
            "denial_scope": line.denial_scope,
            "denied_amount": f"{line.denied_amount:.2f}",
            "primary_denial_category": line.primary_denial_category,
            "primary_carc": line.primary_carc,
            "remark_codes": line.remark_codes,
        }
        for line in lines
    ]
    return payload


def _claim_payload(claim: Claim, transaction: EdiTransaction | None, payer: Payer | None, can_view_phi: bool) -> dict:
    return {
        "id": str(claim.id),
        "patient_control_number": claim.patient_control_number,
        "payer_claim_control_number": claim.payer_claim_control_number,
        "claim_status_code": claim.claim_status_code,
        "claim_status_label": claim.claim_status_label,
        "total_charge": f"{claim.total_charge:.2f}",
        "payment_amount": f"{claim.payment_amount:.2f}",
        "patient_responsibility": f"{claim.patient_responsibility:.2f}" if claim.patient_responsibility is not None else None,
        "is_denied": claim.is_denied,
        "denial_scope": claim.denial_scope,
        "denied_amount": f"{claim.denied_amount:.2f}",
        "primary_denial_category": claim.primary_denial_category,
        "primary_carc": claim.primary_carc,
        "is_reversal": claim.is_reversal,
        "payer": payer.name if payer else None,
        "payment_date": transaction.payment_date.isoformat() if transaction and transaction.payment_date else None,
        "patient_display": f"{claim.patient_first_name or ''} {claim.patient_last_name or ''}".strip() if can_view_phi else mask_name(claim.patient_last_name, claim.patient_first_name),
        "member_id": claim.member_id if can_view_phi else mask_identifier(claim.member_id),
    }


@router.post("/remittances/upload")
async def upload_remittance(
    request: Request,
    upload: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("remittances:ingest")),
) -> dict:
    settings = get_settings()
    name = upload.filename or "upload.835"
    suffix = Path(name).suffix.lower()
    if suffix not in ALLOWED_UPLOADS:
        raise AppError(400, "invalid_upload", "Upload a .835, .edi, .txt, or .x12 file.")
    content = await upload.read()
    if len(content) > settings.max_upload_bytes:
        raise AppError(400, "invalid_upload", "The file exceeds the configured upload size.")
    if b"\x00" in content:
        raise AppError(400, "invalid_upload", "The file is not a text EDI interchange.")
    if suffix == ".zip":
        return await _accept_uploads(request, db, user, [(name, content)])
    result = ingest_content(db, content, name, source_system="upload", source_record_id=name)
    _audit(db, user, "upload_remittance", "remittance_file", result.file_id, request, {"status": result.status})
    db.commit()
    return {
        "status": result.status,
        "lifecycle": lifecycle_label(result.status, result.reconciliation_status),
        "file_id": result.file_id,
        "message": result.message,
        "reconciliation_status": result.reconciliation_status,
        "sha256": result.sha256,
    }


@router.post("/remittances/batch")
async def upload_batch(
    request: Request,
    files: list[UploadFile] = File(...),
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("remittances:ingest")),
) -> dict:
    settings = get_settings()
    if not files:
        raise AppError(400, "invalid_upload", "Choose at least one remittance file.")
    if len(files) > 40:
        raise AppError(400, "invalid_upload", "Upload 40 files or fewer at a time.")
    incoming: list[tuple[str, bytes]] = []
    for upload in files:
        name = upload.filename or "upload.835"
        suffix = Path(name).suffix.lower()
        if suffix not in ALLOWED_UPLOADS:
            raise AppError(400, "invalid_upload", f"{Path(name).name} is not a supported remittance or ZIP file.")
        content = await upload.read()
        if len(content) > settings.max_upload_bytes:
            raise AppError(400, "invalid_upload", f"{Path(name).name} exceeds the configured upload size.")
        if suffix != ".zip" and b"\x00" in content:
            raise AppError(400, "invalid_upload", f"{Path(name).name} is not a text EDI interchange.")
        incoming.append((name, content))
    return await _accept_uploads(request, db, user, incoming)


@router.post("/remittances/{file_id}/retry")
def retry_remittance(
    file_id: UUID,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("remittances:ingest")),
) -> dict:
    try:
        result = retry_quarantined(db, file_id)
    except LookupError as exc:
        raise AppError(404, "not_found", str(exc)) from exc
    except FileNotFoundError as exc:
        raise AppError(404, "not_found", "The stored remittance file could not be read.") from exc
    if result.status == "not_retryable":
        raise AppError(409, "not_retryable", result.message)
    _audit(db, user, "retry_remittance", "remittance_file", result.file_id, request, {"status": result.status})
    db.commit()
    return {
        "status": result.status,
        "lifecycle": lifecycle_label(result.status, result.reconciliation_status),
        "file_id": result.file_id,
        "message": result.message,
        "reconciliation_status": result.reconciliation_status,
    }


@router.get("/remittances/{file_id}/error-report")
def remittance_error_report(
    file_id: UUID,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("remittances:read")),
):
    row = db.get(RemittanceFile, file_id)
    if row is None:
        raise AppError(404, "not_found", "Remittance file was not found.")
    errors = db.scalars(select(ProcessingError).where(ProcessingError.remittance_file_id == row.id)).all()
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["filename", "sha256", "lifecycle", "stage", "message", "created_at"])
    if not errors:
        writer.writerow([row.original_filename, row.sha256, lifecycle_label(row.status, row.reconciliation_status), "", "No processing errors were recorded.", ""])
    for item in errors:
        writer.writerow(
            [
                row.original_filename,
                row.sha256,
                lifecycle_label(row.status, row.reconciliation_status),
                item.stage,
                item.message,
                item.created_at.isoformat() if item.created_at else "",
            ]
        )
    _audit(db, user, "export_error_report", "remittance_file", str(row.id), request)
    db.commit()
    return Response(
        content=buffer.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{Path(row.original_filename).stem}-errors.csv"'},
    )


def _status_for_lifecycle(lifecycle: str) -> str:
    mapping = {
        "COMPLETED": "parsed",
        "QUARANTINED": "quarantined",
        "REQUIRES_REVIEW": "parsed_out_of_balance",
        "RECEIVED": "received",
        "FAILED": "failed",
    }
    status = mapping.get(lifecycle.upper())
    if status is None:
        raise AppError(400, "invalid_lifecycle", "Lifecycle filter is not recognized.")
    return status


async def _accept_uploads(request: Request, db: Session, user: User, incoming: list[tuple[str, bytes]]) -> dict:
    settings = get_settings()
    job = ProcessingJob(job_type="upload_batch", status="running", started_at=utcnow(), triggered_by=user.email)
    db.add(job)
    db.commit()
    results = []
    try:
        members = []
        for name, content in incoming:
            members.extend(
                expand_upload(
                    name,
                    content,
                    max_member_bytes=settings.max_upload_bytes,
                    max_total_bytes=settings.max_upload_bytes * 8,
                )
            )
    except ArchiveError as exc:
        job.status = "failed"
        job.finished_at = utcnow()
        job.error_summary = str(exc)
        db.commit()
        raise AppError(400, "invalid_upload", str(exc)) from exc
    for member in members:
        if member.content is None:
            results.append(
                {
                    "filename": member.filename,
                    "status": "rejected",
                    "lifecycle": "FAILED",
                    "file_id": None,
                    "message": member.rejected_reason,
                    "sha256": None,
                    "reconciliation_status": None,
                }
            )
            continue
        if b"\x00" in member.content:
            results.append(
                {
                    "filename": member.filename,
                    "status": "rejected",
                    "lifecycle": "FAILED",
                    "file_id": None,
                    "message": "The file is not a text EDI interchange.",
                    "sha256": None,
                    "reconciliation_status": None,
                }
            )
            continue
        result = ingest_content(db, member.content, member.filename, source_system="upload", source_record_id=member.filename, job_id=job.id)
        results.append(
            {
                "filename": member.filename,
                "status": result.status,
                "lifecycle": lifecycle_label(result.status, result.reconciliation_status),
                "file_id": result.file_id,
                "message": result.message,
                "sha256": result.sha256,
                "reconciliation_status": result.reconciliation_status,
                "claim_count": result.claim_count,
            }
        )
    job.status = "completed"
    job.finished_at = utcnow()
    job.stats = {
        "files": len(results),
        "parsed": sum(1 for item in results if item["status"] == "parsed"),
        "quarantined": sum(1 for item in results if item["status"] == "quarantined"),
        "duplicates": sum(1 for item in results if item["status"] == "duplicate"),
        "rejected": sum(1 for item in results if item["status"] == "rejected"),
    }
    _audit(db, user, "upload_batch", "processing_job", str(job.id), request, job.stats)
    db.commit()
    return {"job_id": str(job.id), "stats": job.stats, "results": results}


@router.post("/processing/run")
def run_processing(
    body: ProcessRequest,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("jobs:run")),
) -> dict:
    settings = get_settings()
    if body.source == "synthetic_demo" and not settings.demo_mode:
        raise AppError(409, "demo_disabled", "Synthetic demo ingestion is available only when DEMO_MODE is true.")
    if body.source == "central_reach":
        try:
            CentralReachAPIConnector(settings.central_reach_api_enabled).list_records()
        except IntegrationDisabledError as exc:
            raise AppError(409, "integration_disabled", str(exc)) from exc
    directory = _resolve_ingest_path(body, settings)
    if settings.use_celery:
        try:
            from app.workers.celery_app import process_ingestion_task

            task = process_ingestion_task.delay(str(directory), _source_system(body.source))
        except Exception as exc:
            raise AppError(503, "queue_unavailable", "USE_CELERY is true and the queue did not accept the job. It was not run inline.") from exc
        return {"status": "queued", "task_id": task.id}
    job = ProcessingJob(job_type=body.source, status="running", started_at=utcnow(), triggered_by=user.email)
    db.add(job)
    db.commit()
    stats = ingest_directory(db, directory, _source_system(body.source), job.id)
    if body.source == "synthetic_demo":
        from app.seed.reference import ensure_knowledge, ensure_synthetic_contracts, ensure_synthetic_submission_events

        ensure_synthetic_contracts(db)
        ensure_synthetic_submission_events(db)
        ensure_knowledge(db)
        db.commit()
    alert_count = sync_alerts(db, settings)
    job.status = "completed"
    job.finished_at = utcnow()
    job.stats = {**stats, "alerts_created": alert_count}
    _audit(db, user, "processing_run", "processing_job", str(job.id), request, job.stats)
    db.commit()
    return {"status": job.status, "job_id": str(job.id), "stats": job.stats}


def _source_system(source: str) -> str:
    if source == "synthetic_demo":
        return "mock_central_reach"
    if source == "sftp":
        return "sftp"
    return "local_file"


def _resolve_ingest_path(body: ProcessRequest, settings) -> Path:
    root = Path(settings.ingest_root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    if body.source == "synthetic_demo":
        from app.synthetic.corpus import monthly_history, required_scenarios

        target = root / "synthetic_835"
        target.mkdir(parents=True, exist_ok=True)
        for name, text in {**required_scenarios(), **monthly_history()}.items():
            (target / name).write_text(text, encoding="utf-8")
        return target
    requested = Path(body.path) if body.path else root
    target = requested.resolve() if requested.is_absolute() else (root / requested).resolve()
    if not target.is_relative_to(root):
        raise AppError(400, "invalid_path", "The ingestion path must stay inside the configured ingest root.")
    if not target.exists():
        raise AppError(400, "invalid_path", "The ingestion directory does not exist.")
    return target


@router.get("/processing/jobs")
def list_jobs(
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("analytics:read")),
) -> dict:
    total = db.scalar(select(func.count()).select_from(ProcessingJob)) or 0
    rows = db.scalars(select(ProcessingJob).order_by(ProcessingJob.created_at.desc()).offset((page - 1) * page_size).limit(page_size)).all()
    return _page(
        [
            {
                "id": str(row.id),
                "job_type": row.job_type,
                "status": row.status,
                "stats": row.stats,
                "error_summary": row.error_summary,
                "started_at": row.started_at.isoformat() if row.started_at else None,
                "finished_at": row.finished_at.isoformat() if row.finished_at else None,
            }
            for row in rows
        ],
        total,
        page,
        page_size,
    )


@router.get("/alerts")
def list_alerts(
    status: str | None = None,
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("analytics:read")),
) -> dict:
    statement = select(Alert).order_by(Alert.created_at.desc())
    if status:
        statement = statement.where(Alert.status == status)
    rows = db.scalars(statement).all()
    return {
        "items": [
            {
                "id": str(row.id),
                "title": row.title,
                "category": row.category,
                "severity": row.severity,
                "financial_impact": f"{row.financial_impact:.2f}" if row.financial_impact is not None else None,
                "status": row.status,
                "assigned_to": str(row.assigned_to) if row.assigned_to else None,
                "source_type": row.source_type,
                "detail": row.detail,
            }
            for row in rows
        ]
    }


@router.patch("/alerts/{alert_id}")
def update_alert(
    alert_id: UUID,
    body: AlertUpdate,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("alerts:write")),
) -> dict:
    alert = db.get(Alert, alert_id)
    if alert is None:
        raise AppError(404, "not_found", "Alert was not found.")
    if body.status is not None:
        if body.status not in {"open", "acknowledged", "resolved", "dismissed"}:
            raise AppError(400, "invalid_status", "Alert status is not recognized.")
        alert.status = body.status
    if body.assigned_to is not None:
        alert.assigned_to = body.assigned_to
    _audit(db, user, "update_alert", "alert", str(alert.id), request, {"status": alert.status})
    db.commit()
    return {"id": str(alert.id), "status": alert.status}


@router.get("/ai/investigations")
def list_investigations(
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("ai:investigate")),
) -> dict:
    rows = db.scalars(select(AiInvestigation).order_by(AiInvestigation.created_at.desc()).limit(50)).all()
    return {
        "items": [
            {
                "id": str(row.id),
                "question": row.question,
                "status": row.status,
                "provider_name": row.provider_name,
                "model_id": row.model_id,
                "needs_human_review": row.needs_human_review,
                "summary": (row.result or {}).get("summary"),
                "created_at": row.created_at.isoformat() if row.created_at else None,
                "reviewed_at": row.reviewed_at.isoformat() if row.reviewed_at else None,
            }
            for row in rows
        ]
    }


@router.post("/ai/ask")
@router.post("/ai/investigate")
def ask(
    body: QuestionRequest,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("ai:investigate")),
) -> dict:
    settings = get_settings()
    try:
        result = investigate(db, settings, body.question)
    except BedrockApprovalError as exc:
        raise AppError(409, "bedrock_not_approved", str(exc)) from exc
    except LLMError as exc:
        raise AppError(502, "llm_error", str(exc)) from exc
    investigation = AiInvestigation(
        question=body.question,
        status=result["status"],
        requested_by=user.id,
        provider_name=result["provider_name"],
        model_id=result["model_id"],
        needs_human_review=result["needs_human_review"],
        result={key: result[key] for key in ("summary", "recommendations", "missing_evidence", "citations", "disclaimer", "errors", "plan", "llm_error")},
    )
    db.add(investigation)
    db.flush()
    db.add(
        AiInsight(
            investigation_id=investigation.id,
            agent_name="insight",
            summary=result["summary"],
            recommendations=result["recommendations"],
            evidence={"plan": result["plan"], "provider_name": result["provider_name"]},
            insufficient_evidence=result["insufficient_evidence"],
            provider_name=result["provider_name"],
            model_id=result["model_id"],
        )
    )
    _audit(db, user, "ai_investigate", "ai_investigation", str(investigation.id), request, {"provider": result["provider_name"]})
    db.commit()
    result["investigation_id"] = str(investigation.id)
    return result


@router.post("/ai/investigations/{investigation_id}/review")
def review_investigation(
    investigation_id: UUID,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("alerts:write")),
) -> dict:
    row = db.get(AiInvestigation, investigation_id)
    if row is None:
        raise AppError(404, "not_found", "Investigation was not found.")
    row.status = "reviewed"
    row.reviewed_at = utcnow()
    row.reviewed_by = user.id
    row.needs_human_review = False
    _audit(db, user, "review_investigation", "ai_investigation", str(row.id), request)
    db.commit()
    return {"id": str(row.id), "status": row.status}


@router.get("/reports/{report_name}")
def export_report(
    report_name: str,
    request: Request,
    export_format: str = Query("csv", alias="format"),
    selected: AnalyticsFilter = Depends(filters),
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("reports:export")),
):
    if report_name not in REPORTS:
        raise AppError(404, "not_found", "Report type was not found.")
    if export_format not in {"csv", "xlsx", "pdf"}:
        raise AppError(400, "invalid_format", "Format must be csv, xlsx, or pdf.")
    settings = get_settings()
    try:
        title, rows = build_report(db, report_name, selected, settings.demo_mode)
    except KeyError as exc:
        raise AppError(404, "not_found", "Report type was not found.") from exc
    _audit(db, user, "export_report", "report", report_name, request, {"format": export_format})
    db.commit()
    if export_format == "csv":
        return Response(content=to_csv(rows), media_type="text/csv", headers={"Content-Disposition": f'attachment; filename="{report_name}.csv"'})
    if export_format == "xlsx":
        return Response(
            content=to_xlsx(title, rows),
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f'attachment; filename="{report_name}.xlsx"'},
        )
    return Response(content=to_pdf(title, rows, settings.demo_mode), media_type="application/pdf", headers={"Content-Disposition": f'attachment; filename="{report_name}.pdf"'})


@router.get("/audit")
def list_audit(db: Session = Depends(get_db), _: User = Depends(require_permission("audit:read"))) -> dict:
    rows = db.scalars(select(AuditLog).order_by(AuditLog.created_at.desc()).limit(200)).all()
    return {
        "items": [
            {
                "id": str(row.id),
                "action": row.action,
                "resource_type": row.resource_type,
                "resource_id": row.resource_id,
                "created_at": row.created_at.isoformat() if row.created_at else None,
                "detail": row.detail,
            }
            for row in rows
        ]
    }


@router.get("/settings/denial-mappings")
def list_mappings(db: Session = Depends(get_db), _: User = Depends(require_permission("analytics:read"))) -> dict:
    ensure_denial_mappings(db)
    db.commit()
    rows = db.scalars(select(DenialCategoryMapping).order_by(DenialCategoryMapping.code_type, DenialCategoryMapping.code, DenialCategoryMapping.version)).all()
    return {
        "items": [
            {
                "code": row.code,
                "code_type": row.code_type,
                "category": row.category,
                "is_denial": row.is_denial,
                "version": row.version,
                "notes": row.notes,
            }
            for row in rows
        ]
    }


@router.put("/settings/denial-mappings/{code}")
def update_mapping(
    code: str,
    body: MappingUpdate,
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("settings:write")),
) -> dict:
    from app.denials.catalog import DENIAL_CATEGORIES

    if body.category not in DENIAL_CATEGORIES and body.category not in {"contractual", "patient_responsibility"}:
        raise AppError(400, "invalid_category", "Denial category is not recognized.")
    current = db.scalar(
        select(DenialCategoryMapping)
        .where(DenialCategoryMapping.code == code, DenialCategoryMapping.code_type == "CARC")
        .order_by(DenialCategoryMapping.version.desc())
    )
    version = 1 if current is None else current.version + 1
    if current is not None:
        current.effective_to = date.today()
    row = DenialCategoryMapping(
        code_type="CARC",
        code=code,
        category=body.category,
        is_denial=body.is_denial,
        version=version,
        effective_from=date.today(),
        notes=body.notes or "Updated through settings.",
    )
    db.add(row)
    db.commit()
    return {"code": code, "version": version, "category": body.category, "is_denial": body.is_denial}


@router.post("/settings/contracts")
def create_contract(
    body: ContractRequest,
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("settings:write")),
) -> dict:
    if body.is_approved and body.source_label == "synthetic_demo":
        raise AppError(400, "invalid_contract", "A synthetic demo contract cannot be marked approved.")
    if body.expected_amount is None and body.percent_of_billed is None:
        raise AppError(400, "invalid_contract", "A contract rule needs an expected amount or a percent of billed charges.")
    payer = db.scalar(select(Payer).where(Payer.payer_identifier == body.payer_identifier))
    if payer is None:
        payer = Payer(payer_identifier=body.payer_identifier, name=body.payer_name)
        db.add(payer)
        db.flush()
    contract = PayerContract(
        payer_id=payer.id,
        name=f"{body.source_label} {body.procedure_code}",
        effective_from=body.effective_from,
        effective_to=body.effective_to,
        version=1,
        source_label=body.source_label,
        is_approved=body.is_approved,
    )
    db.add(contract)
    db.flush()
    db.add(
        ReimbursementRule(
            contract_id=contract.id,
            procedure_code=body.procedure_code,
            expected_amount=body.expected_amount,
            percent_of_billed=body.percent_of_billed,
            effective_from=body.effective_from,
            effective_to=body.effective_to,
            version=1,
            notes="Loaded through the settings API.",
        )
    )
    db.commit()
    return {"contract_id": str(contract.id), "is_approved": contract.is_approved, "source_label": contract.source_label}


@router.get("/settings/integrations")
def integration_settings(_: User = Depends(require_permission("analytics:read"))) -> dict:
    return meta()


@router.get("/settings/thresholds")
def thresholds(_: User = Depends(require_permission("analytics:read"))) -> dict:
    settings = get_settings()
    return {
        "payment_delay_threshold_days": settings.payment_delay_threshold_days,
        "denial_rate_alert_threshold": str(settings.denial_rate_alert_threshold),
        "underpayment_tolerance": str(settings.underpayment_tolerance),
        "reconciliation_tolerance": str(settings.reconciliation_tolerance),
        "anomaly_min_periods": settings.anomaly_min_periods,
        "anomaly_min_claims": settings.anomaly_min_claims,
        "human_review_exposure_threshold": str(settings.human_review_exposure_threshold),
    }
