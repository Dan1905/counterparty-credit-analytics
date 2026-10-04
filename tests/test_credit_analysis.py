"""Financial ratios and the internal credit risk score."""

from __future__ import annotations

import math

import pandas as pd
import pytest

from ccr import credit_analysis as ca
from ccr.config import CREDIT_METRICS, MetricBounds


def _financials(**overrides) -> pd.DataFrame:
    row = dict(counterparty_id="X", revenue=1000.0, ebitda=200.0, net_income=100.0, total_assets=2000.0,
               total_debt=600.0, cash=50.0, current_assets=450.0, current_liabilities=300.0,
               previous_revenue=800.0)
    row.update(overrides)
    return pd.DataFrame([row])


def test_individual_ratios():
    assert ca.debt_to_ebitda(600.0, 200.0) == pytest.approx(3.0)
    assert ca.current_ratio(450.0, 300.0) == pytest.approx(1.5)
    assert ca.net_margin(100.0, 1000.0) == pytest.approx(0.10)
    assert ca.debt_to_assets(600.0, 2000.0) == pytest.approx(0.30)
    assert ca.revenue_growth(1000.0, 800.0) == pytest.approx(0.25)


def test_ratio_edge_cases():
    assert math.isinf(ca.debt_to_ebitda(600.0, 0.0))
    assert math.isinf(ca.debt_to_ebitda(600.0, -50.0))
    assert math.isnan(ca.current_ratio(100.0, 0.0))
    assert ca.revenue_growth(900.0, 1000.0) == pytest.approx(-0.10)


def test_financial_ratios_table():
    ratios = ca.financial_ratios(_financials()).iloc[0]
    assert ratios["debt_to_ebitda"] == pytest.approx(3.0)
    assert ratios["revenue_growth"] == pytest.approx(0.25)
    with pytest.raises(ca.CreditAnalysisError):
        ca.financial_ratios(_financials().drop(columns="ebitda"))


def test_metric_risk_points_linear_and_clipped():
    lower_is_better = MetricBounds(best=1.0, worst=6.0)
    assert ca.metric_risk_points(1.0, lower_is_better) == 0.0
    assert ca.metric_risk_points(3.5, lower_is_better) == pytest.approx(50.0)
    assert ca.metric_risk_points(9.0, lower_is_better) == 100.0
    assert ca.metric_risk_points(float("inf"), lower_is_better) == 100.0
    higher_is_better = MetricBounds(best=2.0, worst=0.8)
    assert ca.metric_risk_points(2.5, higher_is_better) == 0.0
    assert ca.metric_risk_points(1.4, higher_is_better) == pytest.approx(50.0)
    assert ca.metric_risk_points(float("nan"), higher_is_better) == 100.0


def test_score_is_weighted_sum_of_points(config):
    scores = ca.credit_scores(ca.financial_ratios(_financials()), config.credit_score).iloc[0]
    weights = ca.normalised_weights(config.credit_score)
    assert sum(weights.values()) == pytest.approx(1.0)
    expected = sum(weights[m] * scores[f"{m}_points"] for m in CREDIT_METRICS)
    assert scores["credit_score"] == pytest.approx(expected)
    assert scores["credit_score"] == pytest.approx(sum(scores[f"{m}_contribution"] for m in CREDIT_METRICS))
    assert 0.0 <= scores["credit_score"] <= 100.0


def test_score_bounds_and_categories(config):
    strong = _financials(ebitda=900.0, net_income=300.0, total_debt=100.0, current_assets=900.0, previous_revenue=700.0)
    weak = _financials(ebitda=50.0, net_income=-100.0, total_debt=1800.0, current_assets=150.0, previous_revenue=1300.0)
    strong_score = ca.credit_scores(ca.financial_ratios(strong), config.credit_score).iloc[0]
    weak_score = ca.credit_scores(ca.financial_ratios(weak), config.credit_score).iloc[0]
    assert strong_score["credit_score"] == pytest.approx(0.0)
    assert strong_score["risk_category"] == "Low"
    assert weak_score["credit_score"] == pytest.approx(100.0)
    assert weak_score["risk_category"] == "High"


def test_more_leverage_means_higher_risk_score(config):
    base = ca.credit_scores(ca.financial_ratios(_financials()), config.credit_score).iloc[0]["credit_score"]
    levered = ca.credit_scores(ca.financial_ratios(_financials(total_debt=1000.0)), config.credit_score).iloc[0]["credit_score"]
    assert levered > base


def test_risk_category_boundaries(config):
    cats = config.credit_score.categories
    assert ca.risk_category(cats["low"], cats) == "Low"
    assert ca.risk_category(cats["low"] + 0.1, cats) == "Moderate"
    assert ca.risk_category(cats["moderate"] + 0.1, cats) == "Elevated"
    assert ca.risk_category(cats["elevated"] + 0.1, cats) == "High"


def test_score_breakdown_reconciles(config):
    scores = ca.credit_scores(ca.financial_ratios(_financials()), config.credit_score)
    breakdown = ca.score_breakdown(scores, "X", config.credit_score)
    assert len(breakdown) == 5
    assert breakdown["contribution"].sum() == pytest.approx(scores.iloc[0]["credit_score"])
