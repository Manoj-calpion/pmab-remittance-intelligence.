"""Read-only financial analytics. Monetary totals stay in Decimal."""

from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID

import polars as pl
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.anomalies.detector import SeriesPoint, detect_series_anomalies, isolation_forest_outliers
from app.core.config import Settings, get_settings
from app.models import (
    Claim,
    ClaimServiceLine,
    ClaimSubmissionEvent,
    EdiTransaction,
    Payer,
    PayerContract,
    ReimbursementRule,
    ServiceLineAdjustment,
)
from app.payments.engine import ContractRule, SubmissionAnchor, calculate_delay, calculate_underpayment

ZERO = Decimal("0.00")
RATE_QUANTUM = Decimal("0.000001")


@dataclass
class AnalyticsFilter:
    date_from: date | None = None
    date_to: date | None = None
    payer_id: UUID | None = None
    provider_id: UUID | None = None
    procedure_code: str | None = None
    denial_category: str | None = None
    location_id: UUID | None = None


def money(value: Decimal | None) -> str | None:
    if value is None:
        return None
    return f"{value.quantize(Decimal('0.01')):.2f}"


def rate(numerator: int, denominator: int) -> str | None:
    if denominator == 0:
        return None
    return f"{(Decimal(numerator) / Decimal(denominator)).quantize(RATE_QUANTUM):.6f}"


def basis_notice(basis: str) -> str:
    notices = {
        "approved": "Calculated from approved dates or approved contract rules.",
        "synthetic_demo": "Synthetic demo basis. These figures are not approved payer contract or submission data.",
        "mixed": "Results mix approved inputs and labeled synthetic demo inputs.",
        "insufficient_data": "Insufficient approved data. Dates and expected reimbursement were not invented.",
    }
    return notices.get(basis, notices["insufficient_data"])


def _rollup_basis(bases: set[str]) -> str:
    if not bases:
        return "insufficient_data"
    if bases == {"approved"}:
        return "approved"
    if bases == {"synthetic_demo"}:
        return "synthetic_demo"
    if "approved" in bases and "synthetic_demo" in bases:
        return "mixed"
    return next(iter(bases))


def _claim_rows(db: Session, filters: AnalyticsFilter, settings: Settings):
    statement = (
        select(Claim, EdiTransaction, Payer)
        .join(EdiTransaction, Claim.edi_transaction_id == EdiTransaction.id)
        .outerjoin(Payer, EdiTransaction.payer_id == Payer.id)
    )
    if settings.exclude_reversals_from_denial_rate:
        statement = statement.where(Claim.is_reversal.is_(False))
    if filters.date_from is not None:
        statement = statement.where(EdiTransaction.payment_date >= filters.date_from)
    if filters.date_to is not None:
        statement = statement.where(EdiTransaction.payment_date <= filters.date_to)
    if filters.payer_id is not None:
        statement = statement.where(EdiTransaction.payer_id == filters.payer_id)
    if filters.provider_id is not None:
        statement = statement.where(EdiTransaction.provider_id == filters.provider_id)
    if filters.location_id is not None:
        statement = statement.where(Claim.location_id == filters.location_id)
    if filters.denial_category is not None:
        statement = statement.where(Claim.primary_denial_category == filters.denial_category)
    if filters.procedure_code is not None:
        statement = statement.where(
            Claim.id.in_(
                select(ClaimServiceLine.claim_id).where(ClaimServiceLine.procedure_code == filters.procedure_code)
            )
        )
    return db.execute(statement).all()


def _group_counts(rows, key_fn) -> list[dict]:
    buckets: dict[str, dict] = {}
    for claim, transaction, payer in rows:
        key, label, extra = key_fn(claim, transaction, payer)
        bucket = buckets.setdefault(key, {"key": key, "label": label, "claims": 0, "denied_claims": 0, "denied_amount": ZERO, **extra})
        bucket["claims"] += 1
        if claim.is_denied:
            bucket["denied_claims"] += 1
            bucket["denied_amount"] += claim.denied_amount
    results = []
    for bucket in buckets.values():
        results.append(
            {
                "key": bucket["key"],
                "label": bucket["label"],
                "claims": bucket["claims"],
                "denied_claims": bucket["denied_claims"],
                "denial_rate": rate(bucket["denied_claims"], bucket["claims"]),
                "denied_amount": money(bucket["denied_amount"]),
                **{name: bucket[name] for name in bucket if name not in {"key", "label", "claims", "denied_claims", "denied_amount"}},
            }
        )
    results.sort(key=lambda item: Decimal(item["denied_amount"] or "0"), reverse=True)
    return results


def denial_analytics(db: Session, filters: AnalyticsFilter, settings: Settings | None = None) -> dict:
    active = settings or get_settings()
    rows = _claim_rows(db, filters, active)
    denied_rows = [row for row in rows if row[0].is_denied]
    denied_amount = sum((row[0].denied_amount for row in denied_rows), ZERO)
    trend_rows = []
    amount_by_month: dict[tuple[str, str], Decimal] = defaultdict(lambda: ZERO)
    for claim, transaction, payer in rows:
        if transaction.payment_date is None:
            continue
        month = transaction.payment_date.strftime("%Y-%m")
        payer_name = payer.name if payer else "Unknown payer"
        trend_rows.append({"month": month, "payer": payer_name, "is_denied": 1 if claim.is_denied else 0})
        if claim.is_denied:
            amount_by_month[(month, payer_name)] += claim.denied_amount
    trend = []
    if trend_rows:
        frame = pl.DataFrame(trend_rows)
        grouped = (
            frame.group_by(["month", "payer"])
            .agg(pl.len().alias("claims"), pl.col("is_denied").sum().alias("denied_claims"))
            .sort(["month", "payer"])
        )
        for record in grouped.iter_rows(named=True):
            trend.append(
                {
                    "month": record["month"],
                    "payer": record["payer"],
                    "claims": int(record["claims"]),
                    "denied_claims": int(record["denied_claims"]),
                    "denial_rate": rate(int(record["denied_claims"]), int(record["claims"])),
                    "denied_amount": money(amount_by_month[(record["month"], record["payer"])]),
                }
            )
    line_rows = _service_line_rows(db, filters, active)
    line_denied = [row for row in line_rows if row[0].is_denied]
    return {
        "definition": "Denied amount is the sum of adjustments mapped as denials. Contractual write-offs and patient responsibility are excluded. Reversals are excluded from the rate.",
        "claim_level": {
            "claims": len(rows),
            "denied_claims": len(denied_rows),
            "denial_rate": rate(len(denied_rows), len(rows)),
            "denied_amount": money(denied_amount),
        },
        "service_line_level": {
            "service_lines": len(line_rows),
            "denied_lines": len(line_denied),
            "denial_rate": rate(len(line_denied), len(line_rows)),
            "denied_amount": money(sum((row[0].denied_amount for row in line_denied), ZERO)),
        },
        "by_category": _group_counts(
            denied_rows,
            lambda claim, _tx, _payer: (claim.primary_denial_category or "unclassified", claim.primary_denial_category or "unclassified", {}),
        ),
        "by_carc": _group_counts(
            [row for row in denied_rows if row[0].primary_carc],
            lambda claim, _tx, _payer: (claim.primary_carc, claim.primary_carc, {}),
        ),
        "by_payer": _group_counts(
            rows,
            lambda _claim, _tx, payer: (
                str(payer.id) if payer else "unknown",
                payer.name if payer else "Unknown payer",
                {},
            ),
        ),
        "by_procedure": _procedure_denials(line_rows),
        "trend": trend,
    }


def _service_line_rows(db: Session, filters: AnalyticsFilter, settings: Settings):
    statement = (
        select(ClaimServiceLine, Claim, EdiTransaction, Payer)
        .join(Claim, ClaimServiceLine.claim_id == Claim.id)
        .join(EdiTransaction, Claim.edi_transaction_id == EdiTransaction.id)
        .outerjoin(Payer, EdiTransaction.payer_id == Payer.id)
    )
    if settings.exclude_reversals_from_denial_rate:
        statement = statement.where(Claim.is_reversal.is_(False))
    if filters.date_from is not None:
        statement = statement.where(EdiTransaction.payment_date >= filters.date_from)
    if filters.date_to is not None:
        statement = statement.where(EdiTransaction.payment_date <= filters.date_to)
    if filters.payer_id is not None:
        statement = statement.where(EdiTransaction.payer_id == filters.payer_id)
    if filters.provider_id is not None:
        statement = statement.where(EdiTransaction.provider_id == filters.provider_id)
    if filters.procedure_code is not None:
        statement = statement.where(ClaimServiceLine.procedure_code == filters.procedure_code)
    if filters.denial_category is not None:
        statement = statement.where(ClaimServiceLine.primary_denial_category == filters.denial_category)
    return db.execute(statement).all()


def _procedure_denials(line_rows) -> list[dict]:
    buckets: dict[str, dict] = {}
    for line, _claim, _tx, payer in line_rows:
        code = line.procedure_code or "unknown"
        bucket = buckets.setdefault(
            code,
            {"procedure_code": code, "lines": 0, "denied_lines": 0, "denied_amount": ZERO, "payers": set()},
        )
        bucket["lines"] += 1
        if payer is not None:
            bucket["payers"].add(payer.name)
        if line.is_denied:
            bucket["denied_lines"] += 1
            bucket["denied_amount"] += line.denied_amount
    results = []
    for bucket in buckets.values():
        results.append(
            {
                "procedure_code": bucket["procedure_code"],
                "lines": bucket["lines"],
                "denied_lines": bucket["denied_lines"],
                "denial_rate": rate(bucket["denied_lines"], bucket["lines"]),
                "denied_amount": money(bucket["denied_amount"]),
                "payers": sorted(bucket["payers"]),
            }
        )
    results.sort(key=lambda item: Decimal(item["denied_amount"] or "0"), reverse=True)
    return results


def _anchors_for(db: Session) -> dict[tuple[UUID | None, str], list[SubmissionAnchor]]:
    grouped: dict[tuple[UUID | None, str], list[SubmissionAnchor]] = defaultdict(list)
    for event in db.scalars(select(ClaimSubmissionEvent)).all():
        grouped[(event.payer_id, event.patient_control_number)].append(
            SubmissionAnchor(event.submitted_at, event.accepted_at, event.source, event.is_approved_source)
        )
    return grouped


def _rules_for(db: Session) -> dict[UUID, list[ContractRule]]:
    grouped: dict[UUID, list[ContractRule]] = defaultdict(list)
    rows = db.execute(select(ReimbursementRule, PayerContract).join(PayerContract, ReimbursementRule.contract_id == PayerContract.id)).all()
    for rule, contract in rows:
        grouped[contract.payer_id].append(
            ContractRule(
                procedure_code=rule.procedure_code,
                expected_amount=rule.expected_amount,
                percent_of_billed=rule.percent_of_billed,
                effective_from=rule.effective_from,
                effective_to=rule.effective_to,
                source_label=contract.source_label,
                is_approved=contract.is_approved,
                version=rule.version,
                modifier=rule.modifier,
            )
        )
    return grouped


def payment_delay_analytics(db: Session, filters: AnalyticsFilter, settings: Settings | None = None) -> dict:
    active = settings or get_settings()
    rows = _claim_rows(db, filters, active)
    anchors = _anchors_for(db)
    items = []
    bases: set[str] = set()
    delayed = 0
    unavailable = 0
    for claim, transaction, payer in rows:
        choices = list(anchors.get((transaction.payer_id, claim.patient_control_number), []))
        choices.extend(anchors.get((None, claim.patient_control_number), []))
        result = calculate_delay(
            payment_date=transaction.payment_date,
            anchors=choices,
            threshold_days=active.payment_delay_threshold_days,
            allow_synthetic=active.demo_mode,
        )
        if result.status != "calculated":
            unavailable += 1
        else:
            bases.add(result.metric_basis)
            if result.delayed:
                delayed += 1
        if result.status == "calculated":
            items.append(
                {
                    "patient_control_number": claim.patient_control_number,
                    "payer": payer.name if payer else None,
                    "payer_id": str(payer.id) if payer else None,
                    "payment_date": result.payment_date.isoformat() if result.payment_date else None,
                    "anchor_date": result.anchor_date.isoformat() if result.anchor_date else None,
                    "delay_days": result.delay_days,
                    "delayed": result.delayed,
                    "metric_basis": result.metric_basis,
                    "reason": result.reason,
                }
            )
    basis = _rollup_basis(bases)
    return {
        "metric_basis": basis,
        "notice": basis_notice(basis),
        "threshold_days": active.payment_delay_threshold_days,
        "claims_considered": len(rows),
        "calculated_count": len(items),
        "insufficient_data_count": unavailable,
        "delayed_count": delayed if basis != "insufficient_data" else None,
        "items": items,
    }


def _line_adjustments(db: Session, line_id: UUID) -> list[tuple[str, str, Decimal]]:
    rows = db.scalars(select(ServiceLineAdjustment).where(ServiceLineAdjustment.service_line_id == line_id)).all()
    return [(row.group_code, row.reason_code, row.amount) for row in rows]


def underpayment_analytics(db: Session, filters: AnalyticsFilter, settings: Settings | None = None) -> dict:
    active = settings or get_settings()
    rules = _rules_for(db)
    items = []
    bases: set[str] = set()
    insufficient = 0
    excluded = 0
    variance_total = ZERO
    for line, claim, transaction, payer in _service_line_rows(db, filters, active):
        result = calculate_underpayment(
            status_code=claim.claim_status_code,
            billed_amount=line.charge_amount,
            paid_amount=line.paid_amount,
            allowed_amount=line.allowed_amount,
            line_adjustments=_line_adjustments(db, line.id),
            procedure_code=line.procedure_code,
            service_date=line.service_date or claim.service_date_from,
            modifier=(line.modifiers.split(":")[0] if line.modifiers else None),
            rules=rules.get(transaction.payer_id, []) if transaction.payer_id else [],
            tolerance=active.underpayment_tolerance,
            allow_synthetic=active.demo_mode,
            denial_on_line=line.is_denied,
        )
        if result.status == "calculated" and result.underpaid:
            bases.add(result.metric_basis)
            variance_total += result.variance or ZERO
            items.append(
                {
                    "patient_control_number": claim.patient_control_number,
                    "payer": payer.name if payer else None,
                    "payer_id": str(payer.id) if payer else None,
                    "procedure_code": line.procedure_code,
                    "service_date": (line.service_date or claim.service_date_from).isoformat()
                    if (line.service_date or claim.service_date_from)
                    else None,
                    "expected_amount": money(result.expected_amount),
                    "actual_amount": money(result.actual_amount),
                    "variance": money(result.variance),
                    "metric_basis": result.metric_basis,
                    "trace": result.trace,
                }
            )
        elif result.status == "calculated":
            bases.add(result.metric_basis)
        elif result.status == "insufficient_data":
            insufficient += 1
        else:
            excluded += 1
    basis = _rollup_basis(bases) if items or bases else "insufficient_data"
    if not items and insufficient:
        basis = "insufficient_data"
    return {
        "metric_basis": basis,
        "notice": basis_notice(basis),
        "underpaid_count": len(items) if basis != "insufficient_data" else 0,
        "underpaid_amount": money(variance_total) if basis != "insufficient_data" else None,
        "insufficient_data_count": insufficient,
        "excluded_count": excluded,
        "items": sorted(items, key=lambda item: Decimal(item["variance"] or "0"), reverse=True),
    }


def _monthly_denial_points(rows) -> list[SeriesPoint]:
    buckets: dict[tuple[str, str, str], dict] = {}
    for claim, transaction, payer in rows:
        if transaction.payment_date is None or payer is None:
            continue
        month_start = transaction.payment_date.replace(day=1)
        key = (str(payer.id), payer.name, month_start.isoformat())
        bucket = buckets.setdefault(
            key,
            {"payer_id": str(payer.id), "payer": payer.name, "start": month_start, "claims": 0, "denied": 0},
        )
        bucket["claims"] += 1
        if claim.is_denied:
            bucket["denied"] += 1
    points = []
    for bucket in buckets.values():
        if bucket["claims"] == 0:
            continue
        value = (Decimal(bucket["denied"]) / Decimal(bucket["claims"])).quantize(RATE_QUANTUM)
        end = bucket["start"]
        points.append(
            SeriesPoint(
                "payer",
                bucket["payer_id"],
                bucket["payer"],
                bucket["start"],
                end,
                value,
                bucket["claims"],
            )
        )
    return points


def anomaly_analytics(db: Session, filters: AnalyticsFilter, settings: Settings | None = None) -> dict:
    active = settings or get_settings()
    rows = _claim_rows(db, filters, active)
    points = _monthly_denial_points(rows)
    found = detect_series_anomalies(
        points,
        metric="denial_rate",
        min_periods=active.anomaly_min_periods,
        min_sample_size=active.anomaly_min_claims,
        z_threshold=active.anomaly_z_threshold,
        pct_threshold=active.anomaly_pct_change_threshold,
    )
    forest_rows = [
        {
            "entity_type": point.entity_type,
            "entity_id": point.entity_id,
            "entity_label": point.entity_label,
            "period_start": point.period_start,
            "period_end": point.period_end,
            "denial_rate": float(point.value),
        }
        for point in points
    ]
    forest = isolation_forest_outliers(
        forest_rows,
        feature_names=["denial_rate"],
        min_observations=active.isolation_forest_min_observations,
        metric="denial_rate",
    )
    items = []
    for anomaly in [*found, *forest]:
        items.append(
            {
                "metric": anomaly.metric,
                "entity_type": anomaly.entity_type,
                "entity_id": anomaly.entity_id,
                "entity_label": anomaly.entity_label,
                "period_start": anomaly.period_start.isoformat() if anomaly.period_start else None,
                "period_end": anomaly.period_end.isoformat() if anomaly.period_end else None,
                "baseline": str(anomaly.baseline),
                "observed": str(anomaly.observed),
                "severity": anomaly.severity,
                "method": anomaly.method,
                "explanation": anomaly.explanation,
                "evidence": anomaly.evidence,
                "is_financial_error": False,
            }
        )
    return {
        "notice": "Statistical anomalies are not confirmed financial errors.",
        "count": len(items),
        "isolation_forest_ran": any(item["method"] == "isolation_forest" for item in items),
        "isolation_forest_minimum": active.isolation_forest_min_observations,
        "items": items,
    }


def payer_analytics(db: Session, filters: AnalyticsFilter, settings: Settings | None = None) -> dict:
    active = settings or get_settings()
    denials = denial_analytics(db, filters, active)
    delays = payment_delay_analytics(db, filters, active)
    underpayments = underpayment_analytics(db, filters, active)
    delay_by_payer: dict[str, int] = defaultdict(int)
    for item in delays["items"]:
        if item["delayed"] and item["payer_id"]:
            delay_by_payer[item["payer_id"]] += 1
    underpay_by_payer: dict[str, Decimal] = defaultdict(lambda: ZERO)
    for item in underpayments["items"]:
        if item["payer_id"] and item["variance"]:
            underpay_by_payer[item["payer_id"]] += Decimal(item["variance"])
    payers = []
    for row in denials["by_payer"]:
        payers.append(
            {
                **row,
                "low_volume": row["claims"] < active.anomaly_min_claims,
                "delayed_payments": delay_by_payer.get(row["key"], 0) if delays["metric_basis"] != "insufficient_data" else None,
                "underpayment_amount": money(underpay_by_payer.get(row["key"], ZERO))
                if underpayments["metric_basis"] != "insufficient_data"
                else None,
            }
        )
    return {
        "payers": payers,
        "delay_basis": delays["metric_basis"],
        "underpayment_basis": underpayments["metric_basis"],
        "trend": denials["trend"],
        "movement": _payer_movement(denials["trend"]),
        "low_volume_minimum_claims": active.anomaly_min_claims,
    }


def _payer_movement(trend: list[dict]) -> list[dict]:
    grouped: dict[str, list[dict]] = defaultdict(list)
    for row in trend:
        grouped[row["payer"]].append(row)
    movement = []
    for payer, rows in grouped.items():
        ordered = sorted(rows, key=lambda item: item["month"])
        current = ordered[-1]
        previous = ordered[-2] if len(ordered) > 1 else None
        change = None
        if previous and current.get("denial_rate") and previous.get("denial_rate"):
            change = f"{(Decimal(current['denial_rate']) - Decimal(previous['denial_rate'])):.6f}"
        movement.append(
            {
                "payer": payer,
                "month": current["month"],
                "previous_month": previous["month"] if previous else None,
                "denial_rate": current.get("denial_rate"),
                "previous_denial_rate": previous.get("denial_rate") if previous else None,
                "denial_rate_change": change,
                "claims": current.get("claims"),
                "note": "Month-over-month denial rate from payment dates." if previous else "Only one month is available for this payer.",
            }
        )
    movement.sort(key=lambda item: item["payer"])
    return movement


def category_slice(db: Session, filters: AnalyticsFilter, category: str, settings: Settings | None = None) -> dict:
    active = settings or get_settings()
    scoped = AnalyticsFilter(
        date_from=filters.date_from,
        date_to=filters.date_to,
        payer_id=filters.payer_id,
        provider_id=filters.provider_id,
        procedure_code=filters.procedure_code,
        denial_category=category,
        location_id=filters.location_id,
    )
    denials = denial_analytics(db, scoped, active)
    return {
        "category": category,
        "claim_level": denials["claim_level"],
        "by_payer": denials["by_payer"],
        "by_procedure": denials["by_procedure"],
        "by_carc": denials["by_carc"],
        "trend": denials["trend"],
    }


def overview(db: Session, filters: AnalyticsFilter, settings: Settings | None = None) -> dict:
    active = settings or get_settings()
    denials = denial_analytics(db, filters, active)
    delays = payment_delay_analytics(db, filters, active)
    underpayments = underpayment_analytics(db, filters, active)
    anomalies = anomaly_analytics(db, filters, active)
    from app.models import AiInsight, Alert, RemittanceFile

    remittances = db.query(RemittanceFile).count()
    high_alerts = db.query(Alert).filter(Alert.status == "open", Alert.severity.in_(["high", "critical"])).count()
    insights = db.scalars(select(AiInsight).order_by(AiInsight.created_at.desc()).limit(5)).all()
    claim_rows = _claim_rows(db, filters, active)
    paid = sum((row[0].payment_amount for row in claim_rows), ZERO)
    paid_by_month: dict[str, Decimal] = defaultdict(lambda: ZERO)
    denied_by_month: dict[str, Decimal] = defaultdict(lambda: ZERO)
    claims_by_month: dict[str, int] = defaultdict(int)
    for claim, transaction, _payer in claim_rows:
        if transaction.payment_date is None:
            continue
        month = transaction.payment_date.strftime("%Y-%m")
        paid_by_month[month] += claim.payment_amount
        claims_by_month[month] += 1
        if claim.is_denied:
            denied_by_month[month] += claim.denied_amount
    payment_trend = [
        {
            "month": month,
            "paid_amount": money(paid_by_month[month]),
            "denied_amount": money(denied_by_month[month]),
            "claims": claims_by_month[month],
        }
        for month in sorted(claims_by_month)
    ]
    return {
        "demo_mode": active.demo_mode,
        "as_of": datetime.now(UTC).isoformat(),
        "total_remittances": remittances,
        "claims_analyzed": denials["claim_level"]["claims"],
        "total_paid": money(paid) if claim_rows else None,
        "payers_analyzed": len(denials["by_payer"]),
        "denial_rate": denials["claim_level"]["denial_rate"],
        "denied_amount": denials["claim_level"]["denied_amount"],
        "payment_trend": payment_trend,
        "potential_underpayments": underpayments["underpaid_amount"],
        "underpayment_basis": underpayments["metric_basis"],
        "underpayment_notice": underpayments["notice"],
        "delayed_payments": delays["delayed_count"],
        "delay_basis": delays["metric_basis"],
        "delay_notice": delays["notice"],
        "high_priority_alerts": high_alerts,
        "anomaly_count": anomalies["count"],
        "ai_insights": [
            {
                "id": str(item.id),
                "agent_name": item.agent_name,
                "summary": item.summary,
                "provider_name": item.provider_name,
                "insufficient_evidence": item.insufficient_evidence,
            }
            for item in insights
        ],
    }
