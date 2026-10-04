"""Credit-limit utilisation, status classification and breach monitoring."""

from __future__ import annotations

import pandas as pd

from ccr.config import LimitsConfig

STATUS_NORMAL = "Normal"
STATUS_WARNING = "Warning"
STATUS_BREACH = "Breach"
STATUS_ORDER: tuple[str, ...] = (STATUS_BREACH, STATUS_WARNING, STATUS_NORMAL)


class LimitError(ValueError):
    """Raised when a credit limit is missing or not positive."""


def utilisation(amount: float, credit_limit: float) -> float:
    """Utilisation = amount / credit limit."""
    if credit_limit <= 0:
        raise LimitError(f"Credit limit must be positive, got {credit_limit}")
    return float(amount) / float(credit_limit)


def classify_status(
    utilisation_ratio: float, warning_threshold: float, breach_threshold: float = 1.0
) -> str:
    """Normal below the warning threshold, Warning from there up to the limit, Breach above it."""
    if utilisation_ratio > breach_threshold:
        return STATUS_BREACH
    if utilisation_ratio >= warning_threshold:
        return STATUS_WARNING
    return STATUS_NORMAL


def limit_monitoring(
    exposure: pd.DataFrame,
    counterparties: pd.DataFrame,
    config: LimitsConfig,
    pfe_column: str = "pfe_99",
) -> pd.DataFrame:
    """Limit-monitoring table, one row per counterparty, worst status first.

    The governing utilisation is the larger of exposure utilisation
    (Net Exposure / Limit) and PFE utilisation (PFE / Limit).
    """
    terms = counterparties.set_index("counterparty_id")
    rows = []
    for record in exposure.to_dict("records"):
        cp = record["counterparty_id"]
        limit = float(terms.at[cp, "credit_limit"])
        warning = float(terms.at[cp, "warning_threshold"])
        if pd.isna(warning):
            warning = config.warning_threshold
        exposure_util = utilisation(record["net_exposure"], limit)
        pfe_util = utilisation(record[pfe_column], limit)
        governing = max(exposure_util, pfe_util)
        rows.append(
            {
                "counterparty_id": cp,
                "name": terms.at[cp, "name"],
                "sector": terms.at[cp, "sector"],
                "credit_limit": limit,
                "warning_threshold": warning,
                "current_exposure": float(record["current_exposure"]),
                "net_exposure": float(record["net_exposure"]),
                "pfe": float(record[pfe_column]),
                "exposure_utilisation": exposure_util,
                "pfe_utilisation": pfe_util,
                "utilisation": governing,
                "driver": "PFE" if pfe_util >= exposure_util else "Net exposure",
                "headroom": limit - max(record["net_exposure"], record[pfe_column]),
                "status": classify_status(governing, warning, config.breach_threshold),
            }
        )
    table = pd.DataFrame(rows)
    table["status"] = pd.Categorical(table["status"], categories=STATUS_ORDER, ordered=True)
    table = table.sort_values(["status", "utilisation"], ascending=[True, False])
    table["status"] = table["status"].astype(str)
    return table.reset_index(drop=True)


def breaches_and_warnings(limits: pd.DataFrame) -> pd.DataFrame:
    """Counterparties approaching (Warning) or exceeding (Breach) their limit."""
    return limits[limits["status"] != STATUS_NORMAL].reset_index(drop=True)


def key_risk_highlights(
    limits: pd.DataFrame, exposure: pd.DataFrame, previous_exposure: pd.DataFrame | None
) -> dict[str, dict[str, object]]:
    """Largest exposure, highest PFE, highest utilisation and largest exposure increase."""

    def top(frame: pd.DataFrame, column: str) -> dict[str, object]:
        row = frame.loc[frame[column].idxmax()]
        return {"counterparty_id": row["counterparty_id"], "value": float(row[column])}

    highlights = {
        "largest_exposure": top(limits, "current_exposure"),
        "highest_pfe": top(limits, "pfe"),
        "highest_utilisation": top(limits, "utilisation"),
    }
    if previous_exposure is not None and not previous_exposure.empty:
        merged = exposure.merge(
            previous_exposure[["counterparty_id", "current_exposure"]],
            on="counterparty_id",
            suffixes=("", "_previous"),
        )
        merged["change"] = merged["current_exposure"] - merged["current_exposure_previous"]
        highlights["largest_exposure_increase"] = top(merged, "change")
    return highlights
