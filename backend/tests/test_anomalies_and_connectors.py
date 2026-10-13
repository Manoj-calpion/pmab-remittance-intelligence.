from datetime import date
from decimal import Decimal

from app.anomalies.detector import SeriesPoint, detect_series_anomalies, isolation_forest_outliers
from app.integrations.connectors import CentralReachAPIConnector, IntegrationDisabledError
import pytest


def test_denial_rate_spike_is_a_statistical_anomaly_not_a_financial_error() -> None:
    points = []
    for index, value in enumerate(["0.10", "0.11", "0.09", "0.10", "0.12", "0.80"]):
        points.append(
            SeriesPoint(
                "payer",
                "payer-1",
                "Synthetic Payer North",
                date(2025, index + 1, 1),
                date(2025, index + 1, 28),
                Decimal(value),
                20,
            )
        )
    found = detect_series_anomalies(
        points,
        metric="denial_rate",
        min_periods=4,
        min_sample_size=5,
        z_threshold=3.5,
        pct_threshold=0.50,
    )
    assert len(found) == 1
    assert found[0].severity in {"high", "critical"}
    assert found[0].is_financial_error is False
    assert "not a confirmed financial error" in found[0].explanation
    assert "Synthetic Payer North" in found[0].explanation


def test_small_samples_are_not_flagged() -> None:
    points = [
        SeriesPoint("payer", "payer-1", "Payer", date(2025, 1, 1), date(2025, 1, 28), Decimal("0.10"), 2),
        SeriesPoint("payer", "payer-1", "Payer", date(2025, 2, 1), date(2025, 2, 28), Decimal("0.90"), 2),
    ]
    found = detect_series_anomalies(
        points,
        metric="denial_rate",
        min_periods=4,
        min_sample_size=5,
        z_threshold=3.5,
        pct_threshold=0.50,
    )
    assert found == []


def test_isolation_forest_requires_the_minimum_sample_and_does_not_confirm_errors() -> None:
    short = [
        {
            "entity_type": "payer",
            "entity_id": "p",
            "entity_label": "Payer",
            "period_start": date(2025, 1, 1),
            "period_end": date(2025, 1, 28),
            "denial_rate": 0.1,
        }
    ]
    assert isolation_forest_outliers(short, feature_names=["denial_rate"], min_observations=50, metric="denial_rate") == []
    rows = []
    for index in range(60):
        rows.append(
            {
                "entity_type": "payer",
                "entity_id": f"p{index}",
                "entity_label": f"Payer {index}",
                "period_start": date(2025, 1, 1),
                "period_end": date(2025, 1, 28),
                "denial_rate": 0.1 if index < 59 else 0.95,
            }
        )
    found = isolation_forest_outliers(rows, feature_names=["denial_rate"], min_observations=50, metric="denial_rate")
    assert all(item.is_financial_error is False for item in found)


def test_central_reach_connector_is_refused() -> None:
    connector = CentralReachAPIConnector(False)
    with pytest.raises(IntegrationDisabledError):
        connector.list_records()
    enabled = CentralReachAPIConnector(True)
    with pytest.raises(IntegrationDisabledError):
        enabled.list_records()
