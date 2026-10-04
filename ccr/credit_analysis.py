"""Counterparty financial ratios and the internal credit risk score.

The score is an *internal analytical score*, not an external rating:

1. Each ratio is mapped linearly onto 0-100 risk points between a configured
   ``best`` value (0 points) and ``worst`` value (100 points), clipped at both ends.
2. Risk points are combined with configurable weights (normalised to sum to 1).
3. The weighted score (0 = lowest risk, 100 = highest risk) is bucketed into
   Low / Moderate / Elevated / High.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ccr.config import CREDIT_METRICS, CreditScoreConfig, MetricBounds

REQUIRED_FINANCIAL_COLUMNS: tuple[str, ...] = (
    "counterparty_id",
    "revenue",
    "ebitda",
    "net_income",
    "total_assets",
    "total_debt",
    "cash",
    "current_assets",
    "current_liabilities",
    "previous_revenue",
)

RISK_CATEGORIES: tuple[str, ...] = ("Low", "Moderate", "Elevated", "High")

METRIC_LABELS: dict[str, str] = {
    "debt_to_ebitda": "Debt / EBITDA",
    "current_ratio": "Current Ratio",
    "net_margin": "Net Margin",
    "debt_to_assets": "Debt / Assets",
    "revenue_growth": "Revenue Growth",
}


class CreditAnalysisError(ValueError):
    """Raised when financial inputs are missing or invalid."""


def _safe_divide(numerator: float, denominator: float) -> float:
    """Division that returns NaN instead of raising when the denominator is zero."""
    if denominator == 0 or pd.isna(denominator):
        return float("nan")
    return float(numerator) / float(denominator)


def debt_to_ebitda(total_debt: float, ebitda: float) -> float:
    """Debt / EBITDA. Non-positive EBITDA cannot service debt, so it maps to infinity."""
    if ebitda <= 0:
        return float("inf")
    return float(total_debt) / float(ebitda)


def current_ratio(current_assets: float, current_liabilities: float) -> float:
    """Current Ratio = Current Assets / Current Liabilities."""
    return _safe_divide(current_assets, current_liabilities)


def net_margin(net_income: float, revenue: float) -> float:
    """Net Margin = Net Income / Revenue."""
    return _safe_divide(net_income, revenue)


def debt_to_assets(total_debt: float, total_assets: float) -> float:
    """Debt / Assets = Total Debt / Total Assets."""
    return _safe_divide(total_debt, total_assets)


def revenue_growth(revenue: float, previous_revenue: float) -> float:
    """Revenue Growth = (Current Revenue - Previous Revenue) / Previous Revenue."""
    return _safe_divide(revenue - previous_revenue, previous_revenue)


def financial_ratios(financials: pd.DataFrame) -> pd.DataFrame:
    """Compute the five credit ratios for every counterparty."""
    missing = set(REQUIRED_FINANCIAL_COLUMNS) - set(financials.columns)
    if missing:
        raise CreditAnalysisError(f"Financials are missing columns: {sorted(missing)}")
    rows = []
    for row in financials.itertuples(index=False):
        rows.append(
            {
                "counterparty_id": row.counterparty_id,
                "debt_to_ebitda": debt_to_ebitda(row.total_debt, row.ebitda),
                "current_ratio": current_ratio(row.current_assets, row.current_liabilities),
                "net_margin": net_margin(row.net_income, row.revenue),
                "debt_to_assets": debt_to_assets(row.total_debt, row.total_assets),
                "revenue_growth": revenue_growth(row.revenue, row.previous_revenue),
            }
        )
    return pd.DataFrame(rows)


def metric_risk_points(value: float, bounds: MetricBounds) -> float:
    """Map a ratio onto 0 (at ``best``) to 100 (at ``worst``) risk points, clipped."""
    if pd.isna(value):
        return 100.0  # an unavailable ratio is treated conservatively
    position = (value - bounds.best) / (bounds.worst - bounds.best)
    return float(np.clip(position, 0.0, 1.0) * 100.0)


def risk_category(score: float, categories: dict[str, float]) -> str:
    """Bucket a 0-100 risk score into Low / Moderate / Elevated / High."""
    if score <= categories["low"]:
        return "Low"
    if score <= categories["moderate"]:
        return "Moderate"
    if score <= categories["elevated"]:
        return "Elevated"
    return "High"


def normalised_weights(config: CreditScoreConfig) -> dict[str, float]:
    """Metric weights rescaled to sum to exactly 1."""
    total = sum(config.weights[m] for m in CREDIT_METRICS)
    return {m: config.weights[m] / total for m in CREDIT_METRICS}


def credit_scores(ratios: pd.DataFrame, config: CreditScoreConfig) -> pd.DataFrame:
    """Internal credit risk score with a full per-metric breakdown.

    Output columns per metric ``m``: ``m`` (the ratio), ``m_points`` (0-100 risk
    points) and ``m_contribution`` (weight x points). The contributions sum to
    ``credit_score`` so every score can be reconciled by hand.
    """
    weights = normalised_weights(config)
    result = ratios.copy()
    score = np.zeros(len(result))
    for metric in CREDIT_METRICS:
        points = result[metric].apply(lambda v, m=metric: metric_risk_points(v, config.bounds[m]))
        result[f"{metric}_points"] = points
        result[f"{metric}_contribution"] = points * weights[metric]
        score += result[f"{metric}_contribution"].to_numpy()
    result["credit_score"] = score
    result["risk_category"] = [risk_category(s, config.categories) for s in score]
    return result


def score_breakdown(scores: pd.DataFrame, counterparty_id: str, config: CreditScoreConfig) -> pd.DataFrame:
    """Per-metric explanation of one counterparty's score (ratio, bounds, points, weight)."""
    row = scores.set_index("counterparty_id").loc[counterparty_id]
    weights = normalised_weights(config)
    return pd.DataFrame(
        [
            {
                "metric": METRIC_LABELS[m],
                "value": row[m],
                "best (0 pts)": config.bounds[m].best,
                "worst (100 pts)": config.bounds[m].worst,
                "risk_points": row[f"{m}_points"],
                "weight": weights[m],
                "contribution": row[f"{m}_contribution"],
            }
            for m in CREDIT_METRICS
        ]
    )
