"""Initial Margin: IM = Z x Volatility x Exposure x sqrt(T)."""

from __future__ import annotations

import dataclasses
import math

import pandas as pd
import pytest

from ccr import margin
from ccr.config import InitialMarginConfig

VOLS = pd.Series({"NIFTY50": 0.01, "USDINR": 0.004, "RATE_10Y": 0.0006})


def test_confidence_multiplier():
    assert margin.confidence_multiplier(0.99) == pytest.approx(2.3263, abs=1e-4)
    assert margin.confidence_multiplier(0.95) == pytest.approx(1.6449, abs=1e-4)
    with pytest.raises(margin.MarginError):
        margin.confidence_multiplier(1.0)


def test_initial_margin_formula():
    assert margin.initial_margin(2.0, 0.01, 1000.0, 9) == pytest.approx(2.0 * 0.01 * 1000.0 * 3.0)
    assert margin.initial_margin(2.0, 0.01, -1000.0, 9) == pytest.approx(60.0)  # sign of exposure is irrelevant


def test_higher_exposure_gives_higher_margin():
    low = margin.initial_margin(2.33, 0.01, 100.0, 10)
    high = margin.initial_margin(2.33, 0.01, 150.0, 10)
    assert high > low


def test_higher_volatility_gives_higher_margin():
    low = margin.initial_margin(2.33, 0.01, 100.0, 10)
    high = margin.initial_margin(2.33, 0.02, 100.0, 10)
    assert high > low
    assert high == pytest.approx(2 * low)


def test_longer_margin_period_and_higher_confidence_give_higher_margin():
    assert margin.initial_margin(2.33, 0.01, 100.0, 20) > margin.initial_margin(2.33, 0.01, 100.0, 10)
    z95, z99 = margin.confidence_multiplier(0.95), margin.confidence_multiplier(0.99)
    assert margin.initial_margin(z99, 0.01, 100.0, 10) > margin.initial_margin(z95, 0.01, 100.0, 10)


def test_invalid_inputs_raise():
    with pytest.raises(margin.MarginError):
        margin.initial_margin(2.33, -0.01, 100.0, 10)
    with pytest.raises(margin.MarginError):
        margin.initial_margin(2.33, 0.01, 100.0, 0)


def test_trade_level_margin(trades_base):
    cfg = InitialMarginConfig(confidence_level=0.99, margin_period_days=10)
    result = margin.trade_initial_margin(trades_base, VOLS, cfg).set_index("trade_id")
    z = margin.confidence_multiplier(0.99)
    # T1: |0.5 x 100| x 1% x z x sqrt(10)
    assert result.loc["T1", "initial_margin"] == pytest.approx(z * 0.01 * 50.0 * math.sqrt(10))
    assert result.loc["T3", "delta_exposure"] == pytest.approx(-2000.0)
    assert (result["initial_margin"] >= 0).all()


def test_counterparty_and_portfolio_levels_reconcile(trades_base):
    cfg = InitialMarginConfig(net_within_risk_factor=False)
    trade_level = margin.trade_initial_margin(trades_base, VOLS, cfg)
    factors = margin.counterparty_factor_margin(trade_level, cfg)
    counterparties = margin.counterparty_margin(factors)
    assert counterparties["initial_margin"].sum() == pytest.approx(trade_level["initial_margin"].sum())
    contributions = margin.margin_contributions(factors)
    assert contributions["share"].sum() == pytest.approx(1.0)
    assert contributions["initial_margin"].sum() == pytest.approx(counterparties["initial_margin"].sum())


def test_netting_within_risk_factor_never_increases_margin(trades_base):
    offsetting = pd.concat([trades_base, trades_base.iloc[[1]].assign(trade_id="T5", sensitivity=-1.0)])
    netted_cfg = InitialMarginConfig(net_within_risk_factor=True)
    trade_level = margin.trade_initial_margin(offsetting, VOLS, netted_cfg)
    netted = margin.counterparty_factor_margin(trade_level, netted_cfg)
    fx = netted[(netted["counterparty_id"] == "CP_A") & (netted["risk_factor"] == "USDINR")].iloc[0]
    assert fx["initial_margin"] == pytest.approx(0.0, abs=1e-9)   # +200 and -200 offset fully
    assert fx["netting_benefit"] > 0
    assert (netted["initial_margin"] <= netted["standalone_margin"] + 1e-9).all()


def test_volatility_source_and_overrides(trades_base):
    trade_cfg = InitialMarginConfig(volatility_source="trade")
    vols = margin.trade_volatilities(trades_base, VOLS, trade_cfg, trading_days=252)
    assert vols.iloc[0] == pytest.approx(0.15 / math.sqrt(252))
    override_cfg = dataclasses.replace(InitialMarginConfig(), volatility_overrides={"NIFTY50": 0.02})
    vols = margin.trade_volatilities(trades_base, VOLS, override_cfg)
    assert vols.iloc[0] == 0.02
