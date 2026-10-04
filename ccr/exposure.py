"""Exposure scenario engine: scenario MTM, counterparty exposure, EE and PFE.

The engine is sensitivity based and fully transparent::

    PnL change   = Sensitivity x Market Shock x Notional
    Scenario MTM = Current MTM + PnL change
    Exposure     = max(Scenario MTM, 0)
"""

from __future__ import annotations

import logging

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

PRODUCT_RISK_FACTOR: dict[str, str] = {
    "Equity Option": "NIFTY50",
    "FX Forward": "USDINR",
    "Interest Rate Swap": "RATE_10Y",
}

REQUIRED_TRADE_COLUMNS: tuple[str, ...] = (
    "trade_id",
    "counterparty_id",
    "product_type",
    "underlying",
    "risk_factor",
    "notional",
    "currency",
    "maturity",
    "current_mtm",
    "sensitivity",
    "volatility",
)


class ExposureError(ValueError):
    """Raised when trade or scenario inputs are inconsistent."""


def validate_trades(trades: pd.DataFrame, risk_factors: list[str]) -> None:
    """Check that the trade table is complete and references known risk factors."""
    missing = set(REQUIRED_TRADE_COLUMNS) - set(trades.columns)
    if missing:
        raise ExposureError(f"Trades are missing columns: {sorted(missing)}")
    if trades["trade_id"].duplicated().any():
        raise ExposureError("Trade IDs must be unique")
    unknown = set(trades["risk_factor"]) - set(risk_factors)
    if unknown:
        raise ExposureError(f"Trades reference unknown risk factors: {sorted(unknown)}")
    numeric = trades[["notional", "current_mtm", "sensitivity", "volatility"]]
    if numeric.isna().any().any():
        raise ExposureError("Trades contain missing numeric values")
    if (trades["notional"] <= 0).any():
        raise ExposureError("Trade notionals must be positive")


def base_notional(trades: pd.DataFrame, fx_rates: dict[str, float]) -> pd.Series:
    """Convert each trade notional into the base currency.

    ``fx_rates`` maps a currency code to units of base currency per unit of
    that currency (the base currency itself maps to 1).
    """
    unknown = set(trades["currency"]) - set(fx_rates)
    if unknown:
        raise ExposureError(f"No FX rate for currencies: {sorted(unknown)}")
    return trades["notional"] * trades["currency"].map(fx_rates)


def pnl_change(
    sensitivity: np.ndarray | float, shock: np.ndarray | float, notional: np.ndarray | float
) -> np.ndarray:
    """PnL change = Sensitivity x Market Shock x Notional."""
    return np.asarray(sensitivity) * np.asarray(shock) * np.asarray(notional)


def positive_exposure(mtm: np.ndarray | pd.DataFrame | pd.Series | float):
    """Exposure = max(MTM, 0): only positive MTM is at risk if the counterparty defaults."""
    if isinstance(mtm, (pd.DataFrame, pd.Series)):
        return mtm.clip(lower=0.0)
    return np.maximum(mtm, 0.0)


def scenario_mtm_matrix(trades: pd.DataFrame, scenarios: pd.DataFrame) -> pd.DataFrame:
    """Scenario MTM for every (scenario, trade) pair.

    ``trades`` must carry ``notional_base``. Returns a frame indexed by scenario
    date with one column per trade ID.
    """
    if "notional_base" not in trades.columns:
        raise ExposureError("trades must contain 'notional_base' (see base_notional)")
    missing = set(trades["risk_factor"]) - set(scenarios.columns)
    if missing:
        raise ExposureError(f"Scenarios are missing risk factors: {sorted(missing)}")
    shocks = scenarios[trades["risk_factor"].tolist()].to_numpy()  # (S, N)
    pnl = pnl_change(
        trades["sensitivity"].to_numpy(), shocks, trades["notional_base"].to_numpy()
    )
    mtm = trades["current_mtm"].to_numpy() + pnl
    return pd.DataFrame(mtm, index=scenarios.index, columns=trades["trade_id"].tolist())


def aggregate_exposure(mtm: pd.DataFrame, groups: pd.Series, aggregation: str) -> pd.DataFrame:
    """Aggregate trade MTMs (columns) into counterparty exposure.

    ``gross``  : sum of positive trade exposures (no netting benefit).
    ``netted`` : max(sum of trade MTMs, 0) (single netting set per counterparty).
    """
    if aggregation == "gross":
        values = positive_exposure(mtm).T.groupby(groups.to_numpy()).sum().T
    elif aggregation == "netted":
        values = positive_exposure(mtm.T.groupby(groups.to_numpy()).sum().T)
    else:
        raise ExposureError(f"Unknown aggregation '{aggregation}'")
    values.columns.name = "counterparty_id"
    return values


def counterparty_exposure_distribution(
    scenario_mtm: pd.DataFrame, trades: pd.DataFrame, aggregation: str = "gross"
) -> pd.DataFrame:
    """Exposure of each counterparty in every historical scenario (scenarios x counterparties)."""
    groups = trades.set_index("trade_id")["counterparty_id"].loc[scenario_mtm.columns]
    return aggregate_exposure(scenario_mtm, groups, aggregation)


def expected_exposure(exposures: np.ndarray | pd.Series) -> float:
    """EE = mean of the positive scenario exposures."""
    values = np.maximum(np.asarray(exposures, dtype=float), 0.0)
    if values.size == 0:
        raise ExposureError("Cannot compute EE from an empty exposure distribution")
    return float(values.mean())


def potential_future_exposure(exposures: np.ndarray | pd.Series, confidence: float) -> float:
    """PFE = ``confidence`` percentile of the scenario exposure distribution."""
    if not 0.0 < confidence < 1.0:
        raise ExposureError(f"PFE confidence must be in (0, 1), got {confidence}")
    values = np.maximum(np.asarray(exposures, dtype=float), 0.0)
    if values.size == 0:
        raise ExposureError("Cannot compute PFE from an empty exposure distribution")
    return float(np.quantile(values, confidence))


def pfe_column(confidence: float) -> str:
    """Column name for a PFE confidence level, e.g. 0.99 -> ``pfe_99``."""
    return f"pfe_{confidence * 100:g}".replace(".", "_")


def current_exposures(trades: pd.DataFrame) -> pd.DataFrame:
    """Current (netted) and gross exposure per counterparty from today's MTMs.

    * current exposure = max(sum of trade MTMs, 0)
    * gross exposure   = sum of max(trade MTM, 0)
    """
    grouped = trades.groupby("counterparty_id")["current_mtm"]
    return pd.DataFrame(
        {
            "net_mtm": grouped.sum(),
            "current_exposure": grouped.sum().clip(lower=0.0),
            "gross_exposure": grouped.apply(lambda s: s.clip(lower=0.0).sum()),
            "trade_count": grouped.size(),
        }
    )


def exposure_summary(
    trades: pd.DataFrame,
    distribution: pd.DataFrame,
    collateral: pd.Series,
    confidence_levels: tuple[float, ...],
) -> pd.DataFrame:
    """Counterparty-level exposure table: current, gross, collateral, net, EE and PFE."""
    summary = current_exposures(trades)
    summary["collateral"] = collateral.reindex(summary.index).fillna(0.0)
    summary["net_exposure"] = (summary["gross_exposure"] - summary["collateral"]).clip(lower=0.0)
    summary["expected_exposure"] = [
        expected_exposure(distribution[cp]) for cp in summary.index
    ]
    for level in confidence_levels:
        summary[pfe_column(level)] = [
            potential_future_exposure(distribution[cp], level) for cp in summary.index
        ]
    summary["max_scenario_exposure"] = distribution.max().reindex(summary.index)
    return summary.reset_index()


def portfolio_summary(
    summary: pd.DataFrame, distribution: pd.DataFrame, confidence_levels: tuple[float, ...]
) -> dict[str, float]:
    """Portfolio-level totals.

    Portfolio EE and PFE come from the portfolio distribution (the sum of
    counterparty exposures in each scenario), so the PFE reflects the fact
    that counterparties do not all hit their worst scenario together.
    """
    total = distribution.sum(axis=1)
    result = {
        "current_exposure": float(summary["current_exposure"].sum()),
        "gross_exposure": float(summary["gross_exposure"].sum()),
        "collateral": float(summary["collateral"].sum()),
        "net_exposure": float(summary["net_exposure"].sum()),
        "expected_exposure": expected_exposure(total),
    }
    for level in confidence_levels:
        column = pfe_column(level)
        result[column] = potential_future_exposure(total, level)
        result[f"{column}_sum_of_counterparties"] = float(summary[column].sum())
    return result
