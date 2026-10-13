"""Relational model for remittance, analytics, and audit data."""

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import JSON, MONEY, RATE, Base, PortableVector, TimestampMixin, pk, utcnow


class Role(Base, TimestampMixin):
    __tablename__ = "roles"

    id: Mapped[uuid.UUID] = pk()
    name: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    description: Mapped[str] = mapped_column(String(255), default="")
    users: Mapped[list["User"]] = relationship(back_populates="role")


class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = pk()
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("roles.id"), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    role: Mapped[Role] = relationship(back_populates="users")


class Payer(Base, TimestampMixin):
    __tablename__ = "payers"

    id: Mapped[uuid.UUID] = pk()
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    payer_identifier: Mapped[str] = mapped_column(String(80), unique=True, nullable=False, index=True)


class Provider(Base, TimestampMixin):
    __tablename__ = "providers"

    id: Mapped[uuid.UUID] = pk()
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    npi: Mapped[str | None] = mapped_column(String(20), unique=True)
    tax_id: Mapped[str | None] = mapped_column(String(20))


class Location(Base, TimestampMixin):
    __tablename__ = "locations"

    id: Mapped[uuid.UUID] = pk()
    provider_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), ForeignKey("providers.id"))
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    city: Mapped[str | None] = mapped_column(String(120))
    state: Mapped[str | None] = mapped_column(String(2))
    postal_code: Mapped[str | None] = mapped_column(String(15))


class EraRecord(Base, TimestampMixin):
    __tablename__ = "era_records"
    __table_args__ = (UniqueConstraint("source_system", "source_record_id", name="uq_era_source_record"),)

    id: Mapped[uuid.UUID] = pk()
    source_system: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    source_record_id: Mapped[str] = mapped_column(String(128), nullable=False)
    payer_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), ForeignKey("payers.id"))
    payment_date: Mapped[date | None] = mapped_column(Date)
    payment_amount: Mapped[Decimal | None] = mapped_column(MONEY)
    trace_number: Mapped[str | None] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="discovered")
    watermark_value: Mapped[str | None] = mapped_column(String(255))
    discovered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    attributes: Mapped[dict] = mapped_column(JSON, default=dict)


class RemittanceFile(Base, TimestampMixin):
    __tablename__ = "remittance_files"

    id: Mapped[uuid.UUID] = pk()
    era_record_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), ForeignKey("era_records.id"))
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    stored_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    storage_uri: Mapped[str] = mapped_column(String(512), nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    file_size: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    duplicate_of_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), ForeignKey("remittance_files.id"))
    source_system: Mapped[str] = mapped_column(String(64), nullable=False)
    source_record_id: Mapped[str | None] = mapped_column(String(128))
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    parsed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reconciliation_status: Mapped[str | None] = mapped_column(String(40))


class EdiTransaction(Base, TimestampMixin):
    __tablename__ = "edi_transactions"

    id: Mapped[uuid.UUID] = pk()
    remittance_file_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("remittance_files.id"), nullable=False, index=True
    )
    interchange_control_number: Mapped[str] = mapped_column(String(20), nullable=False)
    group_control_number: Mapped[str | None] = mapped_column(String(20))
    transaction_control_number: Mapped[str] = mapped_column(String(20), nullable=False)
    payment_method: Mapped[str | None] = mapped_column(String(10))
    payment_amount: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    payment_date: Mapped[date | None] = mapped_column(Date, index=True)
    credit_debit: Mapped[str | None] = mapped_column(String(1))
    trace_number: Mapped[str | None] = mapped_column(String(80), index=True)
    payer_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), ForeignKey("payers.id"), index=True)
    provider_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), ForeignKey("providers.id"))
    production_date: Mapped[date | None] = mapped_column(Date)
    payer: Mapped[Payer | None] = relationship()
    provider: Mapped[Provider | None] = relationship()


class Claim(Base, TimestampMixin):
    __tablename__ = "claims"
    __table_args__ = (
        Index("ix_claims_status_payer_control", "claim_status_code", "patient_control_number"),
    )

    id: Mapped[uuid.UUID] = pk()
    edi_transaction_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("edi_transactions.id"), nullable=False, index=True
    )
    patient_control_number: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    payer_claim_control_number: Mapped[str | None] = mapped_column(String(64), index=True)
    claim_status_code: Mapped[str] = mapped_column(String(4), nullable=False, index=True)
    claim_status_label: Mapped[str] = mapped_column(String(80), nullable=False)
    total_charge: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    payment_amount: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    patient_responsibility: Mapped[Decimal | None] = mapped_column(MONEY)
    claim_filing_indicator: Mapped[str | None] = mapped_column(String(4))
    facility_type: Mapped[str | None] = mapped_column(String(4))
    frequency_code: Mapped[str | None] = mapped_column(String(4))
    patient_last_name: Mapped[str | None] = mapped_column(String(80))
    patient_first_name: Mapped[str | None] = mapped_column(String(80))
    member_id: Mapped[str | None] = mapped_column(String(80))
    service_date_from: Mapped[date | None] = mapped_column(Date)
    service_date_to: Mapped[date | None] = mapped_column(Date)
    received_date: Mapped[date | None] = mapped_column(Date)
    is_reversal: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_denied: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    denial_scope: Mapped[str] = mapped_column(String(16), default="none", nullable=False)
    denied_amount: Mapped[Decimal] = mapped_column(MONEY, nullable=False, default=Decimal("0.00"))
    primary_denial_category: Mapped[str | None] = mapped_column(String(40), index=True)
    primary_carc: Mapped[str | None] = mapped_column(String(8))
    location_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), ForeignKey("locations.id"))
    source_references: Mapped[dict] = mapped_column(JSON, default=dict)
    transaction: Mapped[EdiTransaction] = relationship()


class ClaimServiceLine(Base, TimestampMixin):
    __tablename__ = "claim_service_lines"

    id: Mapped[uuid.UUID] = pk()
    claim_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("claims.id"), nullable=False, index=True)
    line_number: Mapped[int] = mapped_column(Integer, nullable=False)
    procedure_code: Mapped[str | None] = mapped_column(String(16), index=True)
    modifiers: Mapped[str | None] = mapped_column(String(32))
    revenue_code: Mapped[str | None] = mapped_column(String(16))
    charge_amount: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    paid_amount: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    units: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    service_date: Mapped[date | None] = mapped_column(Date)
    allowed_amount: Mapped[Decimal | None] = mapped_column(MONEY)
    is_denied: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    denial_scope: Mapped[str] = mapped_column(String(16), default="none", nullable=False)
    denied_amount: Mapped[Decimal] = mapped_column(MONEY, nullable=False, default=Decimal("0.00"))
    primary_denial_category: Mapped[str | None] = mapped_column(String(40))
    primary_carc: Mapped[str | None] = mapped_column(String(8))
    remark_codes: Mapped[list] = mapped_column(JSON, default=list)


class ClaimAdjustment(Base):
    __tablename__ = "claim_adjustments"

    id: Mapped[uuid.UUID] = pk()
    claim_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("claims.id"), nullable=False, index=True)
    group_code: Mapped[str] = mapped_column(String(4), nullable=False)
    reason_code: Mapped[str] = mapped_column(String(8), nullable=False, index=True)
    amount: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    quantity: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    sequence: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    category: Mapped[str] = mapped_column(String(40), nullable=False, default="unclassified")
    is_denial: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ServiceLineAdjustment(Base):
    __tablename__ = "service_line_adjustments"

    id: Mapped[uuid.UUID] = pk()
    service_line_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("claim_service_lines.id"), nullable=False, index=True
    )
    group_code: Mapped[str] = mapped_column(String(4), nullable=False)
    reason_code: Mapped[str] = mapped_column(String(8), nullable=False, index=True)
    amount: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    quantity: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    category: Mapped[str] = mapped_column(String(40), nullable=False, default="unclassified")
    is_denial: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ProviderLevelAdjustment(Base):
    __tablename__ = "provider_level_adjustments"

    id: Mapped[uuid.UUID] = pk()
    edi_transaction_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("edi_transactions.id"), nullable=False, index=True
    )
    provider_identifier: Mapped[str] = mapped_column(String(32), nullable=False)
    fiscal_period: Mapped[date | None] = mapped_column(Date)
    reason_code: Mapped[str] = mapped_column(String(8), nullable=False)
    reference_id: Mapped[str | None] = mapped_column(String(64))
    amount: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class RemittancePayment(Base):
    __tablename__ = "remittance_payments"

    id: Mapped[uuid.UUID] = pk()
    edi_transaction_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("edi_transactions.id"), nullable=False, index=True
    )
    payment_method: Mapped[str | None] = mapped_column(String(10))
    amount: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    payment_date: Mapped[date | None] = mapped_column(Date)
    trace_number: Mapped[str | None] = mapped_column(String(80))
    originator_id: Mapped[str | None] = mapped_column(String(80))
    credit_debit_flag: Mapped[str | None] = mapped_column(String(1))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class DenialCodeCatalog(Base):
    __tablename__ = "denial_code_catalog"
    __table_args__ = (UniqueConstraint("code_type", "code", name="uq_denial_code"),)

    id: Mapped[uuid.UUID] = pk()
    code_type: Mapped[str] = mapped_column(String(8), nullable=False)
    code: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    label: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class DenialCategoryMapping(Base, TimestampMixin):
    __tablename__ = "denial_category_mappings"
    __table_args__ = (UniqueConstraint("code_type", "code", "version", name="uq_denial_mapping_version"),)

    id: Mapped[uuid.UUID] = pk()
    code_type: Mapped[str] = mapped_column(String(8), nullable=False)
    code: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    category: Mapped[str] = mapped_column(String(40), nullable=False)
    is_denial: Mapped[bool] = mapped_column(Boolean, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    effective_from: Mapped[date] = mapped_column(Date, nullable=False)
    effective_to: Mapped[date | None] = mapped_column(Date)
    notes: Mapped[str] = mapped_column(String(400), default="")


class PayerContract(Base, TimestampMixin):
    __tablename__ = "payer_contracts"

    id: Mapped[uuid.UUID] = pk()
    payer_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("payers.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    effective_from: Mapped[date] = mapped_column(Date, nullable=False)
    effective_to: Mapped[date | None] = mapped_column(Date)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    source_label: Mapped[str] = mapped_column(String(40), nullable=False)
    is_approved: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class ReimbursementRule(Base, TimestampMixin):
    __tablename__ = "reimbursement_rules"

    id: Mapped[uuid.UUID] = pk()
    contract_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("payer_contracts.id"), nullable=False)
    procedure_code: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    expected_amount: Mapped[Decimal | None] = mapped_column(MONEY)
    percent_of_billed: Mapped[Decimal | None] = mapped_column(RATE)
    modifier: Mapped[str | None] = mapped_column(String(8))
    place_of_service: Mapped[str | None] = mapped_column(String(4))
    effective_from: Mapped[date] = mapped_column(Date, nullable=False)
    effective_to: Mapped[date | None] = mapped_column(Date)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    notes: Mapped[str] = mapped_column(String(400), default="")
    contract: Mapped[PayerContract] = relationship()


class ClaimSubmissionEvent(Base, TimestampMixin):
    __tablename__ = "claim_submission_events"

    id: Mapped[uuid.UUID] = pk()
    patient_control_number: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    payer_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), ForeignKey("payers.id"))
    submitted_at: Mapped[date | None] = mapped_column(Date)
    accepted_at: Mapped[date | None] = mapped_column(Date)
    source: Mapped[str] = mapped_column(String(40), nullable=False)
    is_approved_source: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class AuthorizationReference(Base, TimestampMixin):
    __tablename__ = "authorization_references"

    id: Mapped[uuid.UUID] = pk()
    patient_control_number: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    authorization_number: Mapped[str] = mapped_column(String(64), nullable=False)
    payer_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), ForeignKey("payers.id"))
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="unknown")
    effective_from: Mapped[date | None] = mapped_column(Date)
    effective_to: Mapped[date | None] = mapped_column(Date)
    source: Mapped[str] = mapped_column(String(40), nullable=False, default="remittance_ref")


class IngestionCheckpoint(Base, TimestampMixin):
    __tablename__ = "ingestion_checkpoints"
    __table_args__ = (UniqueConstraint("source_system", "checkpoint_name", name="uq_checkpoint"),)

    id: Mapped[uuid.UUID] = pk()
    source_system: Mapped[str] = mapped_column(String(64), nullable=False)
    checkpoint_name: Mapped[str] = mapped_column(String(64), nullable=False)
    watermark_value: Mapped[str] = mapped_column(String(255), nullable=False)


class ProcessingJob(Base):
    __tablename__ = "processing_jobs"

    id: Mapped[uuid.UUID] = pk()
    job_type: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    triggered_by: Mapped[str | None] = mapped_column(String(255))
    stats: Mapped[dict] = mapped_column(JSON, default=dict)
    error_summary: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ProcessingError(Base):
    __tablename__ = "processing_errors"

    id: Mapped[uuid.UUID] = pk()
    job_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), ForeignKey("processing_jobs.id"))
    remittance_file_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), ForeignKey("remittance_files.id"))
    stage: Mapped[str] = mapped_column(String(64), nullable=False)
    message: Mapped[str] = mapped_column(String(500), nullable=False)
    detail: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ReconciliationResult(Base):
    __tablename__ = "reconciliation_results"

    id: Mapped[uuid.UUID] = pk()
    remittance_file_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("remittance_files.id"), nullable=False, index=True
    )
    edi_transaction_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), ForeignKey("edi_transactions.id"))
    claim_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), ForeignKey("claims.id"))
    scope: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    expected_amount: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    actual_amount: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    difference: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    detail: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AnalyticalFinding(Base):
    __tablename__ = "analytical_findings"

    id: Mapped[uuid.UUID] = pk()
    finding_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    category: Mapped[str | None] = mapped_column(String(40))
    payer_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), ForeignKey("payers.id"))
    provider_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), ForeignKey("providers.id"))
    period_start: Mapped[date | None] = mapped_column(Date)
    period_end: Mapped[date | None] = mapped_column(Date)
    metric: Mapped[str] = mapped_column(String(64), nullable=False)
    value: Mapped[Decimal | None] = mapped_column(RATE)
    severity: Mapped[str] = mapped_column(String(16), nullable=False, default="info")
    evidence: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AnomalyResult(Base):
    __tablename__ = "anomaly_results"

    id: Mapped[uuid.UUID] = pk()
    metric: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    entity_type: Mapped[str] = mapped_column(String(32), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_label: Mapped[str] = mapped_column(String(255), nullable=False)
    period_start: Mapped[date | None] = mapped_column(Date)
    period_end: Mapped[date | None] = mapped_column(Date)
    baseline: Mapped[Decimal | None] = mapped_column(RATE)
    observed: Mapped[Decimal | None] = mapped_column(RATE)
    severity: Mapped[str] = mapped_column(String(16), nullable=False)
    method: Mapped[str] = mapped_column(String(64), nullable=False)
    explanation: Mapped[str] = mapped_column(Text, nullable=False)
    evidence: Mapped[dict] = mapped_column(JSON, default=dict)
    is_financial_error: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AiInvestigation(Base):
    __tablename__ = "ai_investigations"

    id: Mapped[uuid.UUID] = pk()
    question: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    requested_by: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), ForeignKey("users.id"))
    provider_name: Mapped[str] = mapped_column(String(32), nullable=False)
    model_id: Mapped[str] = mapped_column(String(128), default="")
    needs_human_review: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    result: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), ForeignKey("users.id"))


class AiInsight(Base):
    __tablename__ = "ai_insights"

    id: Mapped[uuid.UUID] = pk()
    investigation_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("ai_investigations.id"), nullable=False, index=True
    )
    agent_name: Mapped[str] = mapped_column(String(64), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    recommendations: Mapped[list] = mapped_column(JSON, default=list)
    evidence: Mapped[dict] = mapped_column(JSON, default=dict)
    insufficient_evidence: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    provider_name: Mapped[str] = mapped_column(String(32), nullable=False)
    model_id: Mapped[str] = mapped_column(String(128), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Alert(Base, TimestampMixin):
    __tablename__ = "alerts"

    id: Mapped[uuid.UUID] = pk()
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    category: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    severity: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    financial_impact: Mapped[Decimal | None] = mapped_column(MONEY)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="open", index=True)
    assigned_to: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), ForeignKey("users.id"))
    source_type: Mapped[str] = mapped_column(String(40), nullable=False)
    source_id: Mapped[str] = mapped_column(String(64), nullable=False)
    detail: Mapped[dict] = mapped_column(JSON, default=dict)


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[uuid.UUID] = pk()
    actor_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), ForeignKey("users.id"))
    action: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    resource_type: Mapped[str] = mapped_column(String(64), nullable=False)
    resource_id: Mapped[str | None] = mapped_column(String(64))
    ip_address: Mapped[str | None] = mapped_column(String(64))
    detail: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class KnowledgeDocument(Base, TimestampMixin):
    __tablename__ = "knowledge_documents"

    id: Mapped[uuid.UUID] = pk()
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    document_type: Mapped[str] = mapped_column(String(64), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    source_label: Mapped[str] = mapped_column(String(40), nullable=False)
    is_approved: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    content_text: Mapped[str] = mapped_column(Text, nullable=False)


class KnowledgeChunk(Base):
    __tablename__ = "knowledge_chunks"

    id: Mapped[uuid.UUID] = pk()
    document_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("knowledge_documents.id"), nullable=False, index=True
    )
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[list | None] = mapped_column(PortableVector(256))
    token_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    document: Mapped[KnowledgeDocument] = relationship()
