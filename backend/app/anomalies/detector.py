"""Statistical anomaly detection.

An anomaly is a departure from a historical baseline. It is not a confirmed
financial error. Isolation Forest runs only when the configured sample size is met.
"""

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

import numpy as np
from scipy.stats import median_abs_deviation
from sklearn.ensemble import IsolationForest


@dataclass(frozen=True)
class SeriesPoint:
    entity_type: str
    entity_id: str
    entity_label: str
    period_start: date
    period_end: date
    value: Decimal
    sample_size: int


@dataclass
class DetectedAnomaly:
    metric: str
    entity_type: str
    entity_id: str
    entity_label: str
    period_start: date
    period_end: date
    baseline: Decimal
    observed: Decimal
    severity: str
    method: str
    explanation: str
    evidence: dict = field(default_factory=dict)
    is_financial_error: bool = False


def _modified_z(history: list[float], observed: float) -> tuple[float, float, float]:
    baseline = float(np.median(history))
    mad = float(median_abs_deviation(history, scale=1))
    if mad == 0:
        score = 0.0 if observed == baseline else float("inf")
    else:
        score = 0.6745 * (observed - baseline) / mad
    return score, baseline, mad


def _severity(abs_z: float, abs_pct: float | None, z_threshold: float, pct_threshold: float) -> str | None:
    z_hit = abs_z >= z_threshold
    pct_hit = abs_pct is not None and abs_pct >= pct_threshold
    if not z_hit and not pct_hit:
        return None
    if abs_z >= z_threshold + 2 or (abs_pct is not None and abs_pct >= max(pct_threshold * 3, 1.5)):
        return "critical"
    if abs_z >= z_threshold + 1 or (abs_pct is not None and abs_pct >= max(pct_threshold * 2, 1.0)):
        return "high"
    return "medium"


def detect_series_anomalies(
    points: list[SeriesPoint],
    *,
    metric: str,
    min_periods: int,
    min_sample_size: int,
    z_threshold: float,
    pct_threshold: float,
) -> list[DetectedAnomaly]:
    grouped: dict[tuple[str, str], list[SeriesPoint]] = defaultdict(list)
    for point in points:
        grouped[(point.entity_type, point.entity_id)].append(point)
    anomalies: list[DetectedAnomaly] = []
    for group in grouped.values():
        ordered = sorted(group, key=lambda item: item.period_start)
        if len(ordered) < min_periods + 1:
            continue
        observed = ordered[-1]
        history = [item for item in ordered[:-1] if item.sample_size >= min_sample_size]
        if observed.sample_size < min_sample_size or len(history) < min_periods:
            continue
        history_values = [float(item.value) for item in history]
        observed_value = float(observed.value)
        score, baseline, mad = _modified_z(history_values, observed_value)
        mean_baseline = sum(history_values) / len(history_values)
        pct = None if mean_baseline == 0 else (observed_value - mean_baseline) / abs(mean_baseline)
        severity = _severity(abs(score), None if pct is None else abs(pct), z_threshold, pct_threshold)
        if severity is None:
            continue
        baseline_decimal = Decimal(str(round(baseline, 6)))
        observed_decimal = Decimal(str(round(observed_value, 6)))
        pct_text = "not calculated because the baseline average is zero" if pct is None else f"{pct:.2%}"
        z_text = "infinite" if score == float("inf") else f"{score:.2f}"
        explanation = (
            f"Statistical anomaly for {metric} on {observed.entity_label} during "
            f"{observed.period_start.isoformat()} to {observed.period_end.isoformat()}. "
            f"Baseline median {baseline_decimal}, observed {observed_decimal}, "
            f"robust z-score {z_text}, change versus the prior average {pct_text}. "
            f"Method: median absolute deviation with a minimum of {min_periods} prior periods "
            f"and {min_sample_size} observations in the current period. "
            "This is a statistical anomaly, not a confirmed financial error."
        )
        anomalies.append(
            DetectedAnomaly(
                metric=metric,
                entity_type=observed.entity_type,
                entity_id=observed.entity_id,
                entity_label=observed.entity_label,
                period_start=observed.period_start,
                period_end=observed.period_end,
                baseline=baseline_decimal,
                observed=observed_decimal,
                severity=severity,
                method="modified_z_score_mad",
                explanation=explanation,
                evidence={
                    "robust_z": None if score == float("inf") else round(score, 4),
                    "median_absolute_deviation": mad,
                    "percentage_change": None if pct is None else round(pct, 4),
                    "history": [str(item.value) for item in history],
                    "sample_size": observed.sample_size,
                    "minimum_periods": min_periods,
                    "minimum_sample_size": min_sample_size,
                    "is_financial_error": False,
                },
            )
        )
    return anomalies


def isolation_forest_outliers(
    rows: list[dict],
    *,
    feature_names: list[str],
    min_observations: int,
    metric: str,
) -> list[DetectedAnomaly]:
    """Run Isolation Forest only when every row has the requested features."""
    if len(rows) < min_observations:
        return []
    complete = [row for row in rows if all(row.get(name) is not None for name in feature_names)]
    if len(complete) < min_observations:
        return []
    matrix = np.array([[float(row[name]) for name in feature_names] for row in complete], dtype=float)
    if np.allclose(matrix, matrix[0]):
        return []
    model = IsolationForest(random_state=42, contamination=0.05, n_estimators=100)
    predictions = model.fit_predict(matrix)
    anomalies: list[DetectedAnomaly] = []
    for row, prediction in zip(complete, predictions, strict=True):
        if prediction != -1:
            continue
        observed = Decimal(str(row[feature_names[0]]))
        anomalies.append(
            DetectedAnomaly(
                metric=metric,
                entity_type=row.get("entity_type", "observation"),
                entity_id=str(row.get("entity_id", "")),
                entity_label=str(row.get("entity_label", "observation")),
                period_start=row["period_start"],
                period_end=row["period_end"],
                baseline=Decimal("0"),
                observed=observed,
                severity="medium",
                method="isolation_forest",
                explanation=(
                    f"Isolation Forest flagged {row.get('entity_label', 'an observation')} on {metric} "
                    f"for {row['period_start'].isoformat()} to {row['period_end'].isoformat()} "
                    f"using features {', '.join(feature_names)}. Observed {feature_names[0]} is {observed}. "
                    "No separate median baseline is implied by this method. "
                    "This is a statistical anomaly, not a confirmed financial error."
                ),
                evidence={
                    "features": feature_names,
                    "values": {name: row[name] for name in feature_names},
                    "observation_count": len(complete),
                    "is_financial_error": False,
                },
            )
        )
    return anomalies
