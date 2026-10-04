"""Parametric Initial Margin.

    IM = Z x Volatility x Exposure x sqrt(T)

* ``Z``          one-sided normal quantile of the IM confidence level
* ``Volatility`` daily volatility of the trade's risk factor
* ``Exposure``   delta-equivalent exposure to that factor (Sensitivity x Notional)
* ``T``          margin period of risk in days
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.stats import norm

from ccr.config import InitialMarginConfig


class MarginError(ValueError):
    """Raised when Initial Margin inputs are invalid."""


def confidence_multiplier(confidence_level: float) -> float:
    """Z: the standard-normal quantile for ``confidence_level`` (0.99 -> 2.326)."""
    if not 0.5 < confidence_level < 1.0:
        raise MarginError("IM confidence level must be in (0.5, 1)")
    return float(norm.ppf(confidence_level))


def initial_margin(
    z: float, volatility: float, exposure: float, margin_period_days: float
) -> float:
    """IM = Z x Volatility x |Exposure| x sqrt(T)."""
    if volatility < 0:
        raise MarginError("Volatility cannot be negative")
    if margin_period_days <= 0:
        raise MarginError("Margin period must be positive")
    return float(z * volatility * abs(exposure) * np.sqrt(margin_period_days))


def trade_volatilities(
    trades: pd.DataFrame,
    factor_volatility: pd.Series,
    config: InitialMarginConfig,
    trading_days: int = 252,
) -> pd.Series:
    """Daily volatility applied to each trade according to the configured source."""
    if config.volatility_source == "trade":
        return trades["volatility"] / np.sqrt(trading_days)
    daily = factor_volatility.copy()
    for factor, override in config.volatility_overrides.items():
        daily[factor] = override
    missing = set(trades["risk_factor"]) - set(daily.index)
    if missing:
        raise MarginError(f"No volatility for risk factors: {sorted(missing)}")
    return trades["risk_factor"].map(daily)


def trade_initial_margin(
    trades: pd.DataFrame,
    factor_volatility: pd.Series,
    config: InitialMarginConfig,
    trading_days: int = 252,
) -> pd.DataFrame:
    """Stand-alone Initial Margin for every trade."""
    z = confidence_multiplier(config.confidence_level)
    result = trades[
        ["trade_id", "counterparty_id", "product_type", "risk_factor", "sensitivity",
         "notional_base"]
    ].copy()
    result["delta_exposure"] = result["sensitivity"] * result["notional_base"]
    result["daily_volatility"] = trade_volatilities(
        trades, factor_volatility, config, trading_days
    ).to_numpy()
    result["z"] = z
    result["margin_period_days"] = config.margin_period_days
    result["initial_margin"] = [
        initial_margin(z, vol, exposure, config.margin_period_days)
        for vol, exposure in zip(result["daily_volatility"], result["delta_exposure"])
    ]
    return result


def counterparty_factor_margin(
    trade_margin: pd.DataFrame, config: InitialMarginConfig
) -> pd.DataFrame:
    """Initial Margin per counterparty and risk factor / product.

    With ``net_within_risk_factor`` long and short sensitivities to the same
    factor offset: IM = Z x sqrt(T) x |sum(delta exposure x volatility)|.
    Without it the stand-alone trade margins are simply added.
    """
    frame = trade_margin.copy()
    frame["vol_weighted_exposure"] = frame["delta_exposure"] * frame["daily_volatility"]
    grouped = frame.groupby(["counterparty_id", "risk_factor", "product_type"], sort=True)
    result = grouped.agg(
        trade_count=("trade_id", "size"),
        net_delta_exposure=("delta_exposure", "sum"),
        gross_delta_exposure=("delta_exposure", lambda s: s.abs().sum()),
        net_vol_weighted_exposure=("vol_weighted_exposure", "sum"),
        standalone_margin=("initial_margin", "sum"),
    ).reset_index()
    if config.net_within_risk_factor:
        z = confidence_multiplier(config.confidence_level)
        result["initial_margin"] = (
            z * np.sqrt(config.margin_period_days) * result["net_vol_weighted_exposure"].abs()
        )
    else:
        result["initial_margin"] = result["standalone_margin"]
    result["netting_benefit"] = result["standalone_margin"] - result["initial_margin"]
    return result.drop(columns="net_vol_weighted_exposure")


def counterparty_margin(factor_margin: pd.DataFrame) -> pd.DataFrame:
    """Total Initial Margin per counterparty (sum across risk factors, no diversification)."""
    return (
        factor_margin.groupby("counterparty_id")
        .agg(
            initial_margin=("initial_margin", "sum"),
            standalone_margin=("standalone_margin", "sum"),
            netting_benefit=("netting_benefit", "sum"),
        )
        .reset_index()
    )


def margin_contributions(factor_margin: pd.DataFrame) -> pd.DataFrame:
    """Share of portfolio Initial Margin by risk factor / product."""
    result = (
        factor_margin.groupby(["risk_factor", "product_type"])["initial_margin"]
        .sum()
        .reset_index()
    )
    total = result["initial_margin"].sum()
    result["share"] = result["initial_margin"] / total if total else 0.0
    return result.sort_values("initial_margin", ascending=False, ignore_index=True)
