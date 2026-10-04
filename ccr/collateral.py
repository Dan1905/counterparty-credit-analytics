"""Collateral: requirement, minimum transfer amount and net exposure."""

from __future__ import annotations

import numpy as np
import pandas as pd


def net_exposure(gross_exposure: float, collateral: float) -> float:
    """Net Exposure = max(Gross Exposure - Collateral, 0)."""
    return max(float(gross_exposure) - float(collateral), 0.0)


def collateral_requirement(exposure: float, threshold: float) -> float:
    """Collateral Requirement = max(Exposure - Threshold, 0)."""
    return max(float(exposure) - float(threshold), 0.0)


def collateral_transfer(requirement: float, held: float, minimum_transfer_amount: float) -> float:
    """Collateral to move after applying the Minimum Transfer Amount (MTA).

    Positive = call collateral from the counterparty, negative = return excess.
    A shortfall or excess smaller than the MTA results in no transfer.
    """
    difference = float(requirement) - float(held)
    if abs(difference) < float(minimum_transfer_amount):
        return 0.0
    return difference


def collateral_summary(exposure: pd.DataFrame, counterparties: pd.DataFrame) -> pd.DataFrame:
    """Collateral position per counterparty.

    ``exposure`` needs ``counterparty_id`` and ``gross_exposure``; ``counterparties``
    supplies collateral held, threshold and MTA.
    """
    terms = counterparties.set_index("counterparty_id")
    rows = []
    for record in exposure.itertuples(index=False):
        cp = record.counterparty_id
        held = float(terms.at[cp, "collateral"])
        threshold = float(terms.at[cp, "collateral_threshold"])
        mta = float(terms.at[cp, "minimum_transfer_amount"])
        requirement = collateral_requirement(record.gross_exposure, threshold)
        transfer = collateral_transfer(requirement, held, mta)
        if transfer > 0:
            action = "Call"
        elif transfer < 0:
            action = "Return"
        else:
            action = "No transfer"
        rows.append(
            {
                "counterparty_id": cp,
                "gross_exposure": float(record.gross_exposure),
                "collateral_held": held,
                "collateral_threshold": threshold,
                "minimum_transfer_amount": mta,
                "collateral_requirement": requirement,
                "shortfall": requirement - held,
                "transfer_amount": transfer,
                "action": action,
                "collateral_after_transfer": held + transfer,
                "net_exposure": net_exposure(record.gross_exposure, held),
                "net_exposure_after_transfer": net_exposure(
                    record.gross_exposure, held + transfer
                ),
            }
        )
    return pd.DataFrame(rows).replace({-0.0: 0.0}).astype({"transfer_amount": np.float64})
