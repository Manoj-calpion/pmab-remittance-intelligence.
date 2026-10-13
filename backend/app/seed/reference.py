"""Reference data that is safe to load in every environment.

Denial labels are internal operational text. Demo contracts, submission events,
and knowledge documents are created only in demo mode and are marked synthetic.
"""

from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.denials.catalog import DEFAULT_CODE_MAPPINGS, MAPPING_EFFECTIVE_FROM, MAPPING_VERSION
from app.models import (
    ClaimSubmissionEvent,
    DenialCategoryMapping,
    DenialCodeCatalog,
    KnowledgeDocument,
    Payer,
    PayerContract,
    ReimbursementRule,
    Role,
    User,
)
from app.synthetic.corpus import synthetic_contract_rules, synthetic_delay_events


KNOWLEDGE_DOCS = [
    {
        "title": "Synthetic sample: authorization follow-up SOP",
        "document_type": "sop",
        "content": (
            "SYNTHETIC SAMPLE. This is not a payer policy. "
            "When CARC 15, 39, 197, or 198 clusters for one payer, analysts should confirm whether an authorization number "
            "was present on the remittance and whether an approved authorization record exists. "
            "Do not treat a statistical increase as a confirmed root cause."
        ),
    },
    {
        "title": "Synthetic sample: coding denial review",
        "document_type": "coding_guidance",
        "content": (
            "SYNTHETIC SAMPLE. This is not coding guidance from a payer. "
            "CARC 4, 5, 6, 9, and 11 are mapped to the coding category in the default platform mapping. "
            "A reviewer should compare the procedure code and modifiers on the service line with the billed claim. "
            "The platform does not calculate a corrected code."
        ),
    },
    {
        "title": "Synthetic sample: reimbursement evidence rule",
        "document_type": "reimbursement_documentation",
        "content": (
            "SYNTHETIC SAMPLE. Expected reimbursement must come from an approved contract rule. "
            "If no approved rule matches the payer, procedure, and service date, underpayment status is insufficient data. "
            "Demo contract amounts are not approved payer rates."
        ),
    },
]


def ensure_roles(db: Session) -> dict[str, Role]:
    roles: dict[str, Role] = {}
    for name, description in (
        ("admin", "Configure rules, users, and integrations"),
        ("analyst", "Analyze remittances, export reports, and run investigations"),
        ("reviewer", "Review alerts and investigations"),
        ("viewer", "Read dashboards without exports or patient identifiers"),
    ):
        role = db.scalar(select(Role).where(Role.name == name))
        if role is None:
            role = Role(name=name, description=description)
            db.add(role)
            db.flush()
        roles[name] = role
    return roles


def ensure_denial_mappings(db: Session) -> None:
    if db.scalar(select(DenialCategoryMapping.id).limit(1)) is not None:
        return
    for code, code_type, category, is_denial, label in DEFAULT_CODE_MAPPINGS:
        db.add(DenialCodeCatalog(code_type=code_type, code=code, label=label, is_active=True))
        db.add(
            DenialCategoryMapping(
                code_type=code_type,
                code=code,
                category=category,
                is_denial=is_denial,
                version=MAPPING_VERSION,
                effective_from=MAPPING_EFFECTIVE_FROM,
                notes="Platform default mapping. Confirm with the billing operation before production use.",
            )
        )
    db.flush()


def ensure_demo_users(db: Session, settings) -> None:
    from app.core.security import hash_password, verify_password

    roles = ensure_roles(db)
    accounts = (
        ("admin@pmab.demo", "Demo Administrator", "admin", settings.demo_admin_password),
        ("analyst@pmab.demo", "Demo Analyst", "analyst", settings.demo_analyst_password),
        ("viewer@pmab.demo", "Demo Viewer", "viewer", settings.demo_viewer_password),
    )
    for email, full_name, role_name, password in accounts:
        existing = db.scalar(select(User).where(User.email == email))
        if existing is None:
            db.add(
                User(
                    email=email,
                    full_name=full_name,
                    password_hash=hash_password(password),
                    role_id=roles[role_name].id,
                    is_active=True,
                )
            )
        elif not verify_password(password, existing.password_hash):
            existing.password_hash = hash_password(password)
            existing.is_active = True
    db.flush()


def ensure_synthetic_contracts(db: Session) -> None:
    for item in synthetic_contract_rules():
        payer = db.scalar(select(Payer).where(Payer.payer_identifier == item["payer_identifier"]))
        if payer is None:
            payer = Payer(payer_identifier=item["payer_identifier"], name=item["payer_identifier"])
            db.add(payer)
            db.flush()
        existing = db.scalar(
            select(PayerContract).where(
                PayerContract.payer_id == payer.id,
                PayerContract.source_label == "synthetic_demo",
            )
        )
        if existing is None:
            existing = PayerContract(
                payer_id=payer.id,
                name=f"Synthetic demo schedule {payer.payer_identifier}",
                effective_from=date(2025, 1, 1),
                version=1,
                source_label="synthetic_demo",
                is_approved=False,
            )
            db.add(existing)
            db.flush()
        rule = db.scalar(
            select(ReimbursementRule).where(
                ReimbursementRule.contract_id == existing.id,
                ReimbursementRule.procedure_code == item["procedure_code"],
            )
        )
        if rule is None:
            db.add(
                ReimbursementRule(
                    contract_id=existing.id,
                    procedure_code=item["procedure_code"],
                    expected_amount=Decimal(item["expected_amount"]),
                    effective_from=date(2025, 1, 1),
                    version=1,
                    notes="Synthetic demo amount. Not an approved payer contract.",
                )
            )
    db.flush()


def ensure_synthetic_submission_events(db: Session) -> None:
    for item in synthetic_delay_events():
        payer = db.scalar(select(Payer).where(Payer.payer_identifier == item["payer_identifier"]))
        exists = db.scalar(
            select(ClaimSubmissionEvent).where(
                ClaimSubmissionEvent.patient_control_number == item["patient_control_number"],
                ClaimSubmissionEvent.source == "synthetic_demo",
            )
        )
        if exists is None:
            db.add(
                ClaimSubmissionEvent(
                    patient_control_number=item["patient_control_number"],
                    payer_id=payer.id if payer else None,
                    submitted_at=item["submitted_at"],
                    accepted_at=None,
                    source="synthetic_demo",
                    is_approved_source=False,
                )
            )
    db.flush()


def ensure_knowledge(db: Session) -> None:
    for item in KNOWLEDGE_DOCS:
        existing = db.scalar(select(KnowledgeDocument).where(KnowledgeDocument.title == item["title"]))
        if existing is None:
            db.add(
                KnowledgeDocument(
                    title=item["title"],
                    document_type=item["document_type"],
                    version=1,
                    source_label="synthetic_sample",
                    is_approved=False,
                    is_active=True,
                    content_text=item["content"],
                )
            )
    db.flush()
