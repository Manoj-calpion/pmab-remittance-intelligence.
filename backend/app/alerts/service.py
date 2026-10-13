"""Operational alerts derived from deterministic analytics."""

from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.analytics.service import AnalyticsFilter, anomaly_analytics, denial_analytics
from app.core.config import Settings, get_settings
from app.models import Alert, AnomalyResult


def sync_alerts(db: Session, settings: Settings | None = None) -> int:
    active = settings or get_settings()
    denials = denial_analytics(db, AnalyticsFilter(), active)
    created = 0
    threshold = active.denial_rate_alert_threshold
    for payer in denials["by_payer"]:
        if payer["claims"] < active.anomaly_min_claims or payer["denial_rate"] is None:
            continue
        if Decimal(payer["denial_rate"]) < threshold:
            continue
        created += _upsert_alert(
            db,
            source_type="denial_rate",
            source_id=payer["key"],
            title=f"High denial rate for {payer['label']}",
            category="denial",
            severity="high" if Decimal(payer["denial_rate"]) < Decimal("0.50") else "critical",
            financial_impact=Decimal(payer["denied_amount"]),
            detail={
                "denial_rate": payer["denial_rate"],
                "denied_claims": payer["denied_claims"],
                "claims": payer["claims"],
                "is_financial_error": False,
            },
        )
    anomalies = anomaly_analytics(db, AnalyticsFilter(), active)
    db.query(AnomalyResult).delete()
    for item in anomalies["items"]:
        db.add(
            AnomalyResult(
                metric=item["metric"],
                entity_type=item["entity_type"],
                entity_id=item["entity_id"],
                entity_label=item["entity_label"],
                period_start=None,
                period_end=None,
                baseline=_decimal_or_none(item["baseline"]),
                observed=_decimal_or_none(item["observed"]),
                severity=item["severity"],
                method=item["method"],
                explanation=item["explanation"],
                evidence=item["evidence"],
                is_financial_error=False,
            )
        )
        created += _upsert_alert(
            db,
            source_type="anomaly",
            source_id=f"{item['entity_id']}:{item['metric']}:{item['method']}",
            title=f"{item['severity'].title()} {item['metric']} anomaly for {item['entity_label']}",
            category="anomaly",
            severity=item["severity"],
            financial_impact=None,
            detail={"explanation": item["explanation"], "is_financial_error": False},
        )
    db.commit()
    return created


def _decimal_or_none(value: str | None) -> Decimal | None:
    if value in (None, "", "None"):
        return None
    try:
        return Decimal(value)
    except Exception:
        return None


def _upsert_alert(db: Session, **fields) -> int:
    existing = db.scalar(
        select(Alert).where(Alert.source_type == fields["source_type"], Alert.source_id == fields["source_id"])
    )
    if existing is not None:
        if existing.status == "open":
            existing.title = fields["title"]
            existing.severity = fields["severity"]
            existing.financial_impact = fields["financial_impact"]
            existing.detail = fields["detail"]
        return 0
    db.add(Alert(status="open", assigned_to=None, **fields))
    return 1
