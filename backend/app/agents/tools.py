"""Read-only analytical tools. No SQL text is accepted from agents or users."""

from sqlalchemy.orm import Session

from app.analytics.service import (
    AnalyticsFilter,
    anomaly_analytics,
    category_slice,
    denial_analytics,
    payer_analytics,
    payment_delay_analytics,
    underpayment_analytics,
)
from app.core.config import Settings
from app.rag.knowledge import search_knowledge


class ReadOnlyTools:
    def __init__(self, db: Session, settings: Settings) -> None:
        self.db = db
        self.settings = settings
        self.filters = AnalyticsFilter()

    def denial_summary(self) -> dict:
        data = denial_analytics(self.db, self.filters, self.settings)
        return {
            "claim_level": data["claim_level"],
            "service_line_level": data["service_line_level"],
            "by_category": data["by_category"][:8],
            "by_carc": data["by_carc"][:8],
            "by_payer": data["by_payer"],
            "by_procedure": data["by_procedure"][:8],
            "definition": data["definition"],
        }

    def payment_summary(self) -> dict:
        delays = payment_delay_analytics(self.db, self.filters, self.settings)
        underpayments = underpayment_analytics(self.db, self.filters, self.settings)
        procedures: dict[str, str] = {}
        for item in underpayments["items"]:
            procedures.setdefault(item["procedure_code"] or "unknown", item["variance"])
        return {
            "delays": {
                "metric_basis": delays["metric_basis"],
                "notice": delays["notice"],
                "threshold_days": delays["threshold_days"],
                "delayed_count": delays["delayed_count"],
                "insufficient_data_count": delays["insufficient_data_count"],
                "calculated_count": delays["calculated_count"],
            },
            "underpayments": {
                "metric_basis": underpayments["metric_basis"],
                "notice": underpayments["notice"],
                "underpaid_count": underpayments["underpaid_count"],
                "underpaid_amount": underpayments["underpaid_amount"],
                "insufficient_data_count": underpayments["insufficient_data_count"],
                "top_procedure_variances": procedures,
            },
        }

    def payer_summary(self) -> dict:
        data = payer_analytics(self.db, self.filters, self.settings)
        return {
            "payers": data["payers"],
            "delay_basis": data["delay_basis"],
            "underpayment_basis": data["underpayment_basis"],
        }

    def anomaly_summary(self) -> dict:
        data = anomaly_analytics(self.db, self.filters, self.settings)
        return {
            "notice": data["notice"],
            "count": data["count"],
            "items": [
                {
                    "entity_label": item["entity_label"],
                    "metric": item["metric"],
                    "baseline": item["baseline"],
                    "observed": item["observed"],
                    "severity": item["severity"],
                    "method": item["method"],
                    "explanation": item["explanation"],
                    "is_financial_error": False,
                }
                for item in data["items"]
            ],
        }

    def category_summary(self, category: str) -> dict:
        return category_slice(self.db, self.filters, category, self.settings)

    def knowledge(self, query: str) -> dict:
        return search_knowledge(self.db, query, self.settings)
