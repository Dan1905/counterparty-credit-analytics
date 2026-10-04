"""Synthetic counterparty, trade and financial-statement data.

All names are fictional. Generation is seeded, so the same seed and the same
market snapshot always reproduce the same dataset.
"""

from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
import pandas as pd

from ccr.exposure import PRODUCT_RISK_FACTOR

logger = logging.getLogger(__name__)

MILLION = 1_000_000.0

# Static counterparty terms (amounts in INR millions).
_COUNTERPARTIES = [
    # id, name, sector, country, rating, limit, warning, collateral, threshold, MTA
    ("CP001", "Meridian Infotech Ltd", "Technology", "India", "AA", 100.0, 0.80, 24.0, 10.0, 1.0),
    ("CP002", "Suryodaya Steel & Power Ltd", "Metals & Mining", "India", "BBB", 55.0, 0.80, 25.5, 5.0, 1.0),
    ("CP003", "Blue Harbour Shipping Pte Ltd", "Shipping", "Singapore", "BB+", 50.0, 0.75, 24.0, 5.0, 0.5),
    ("CP004", "Northwind Energy Plc", "Energy", "United Kingdom", "A-", 150.0, 0.80, 0.0, 10.0, 1.0),
    ("CP005", "Kaveri Pharma Exports Ltd", "Pharmaceuticals", "India", "A", 60.0, 0.80, 4.0, 7.5, 0.5),
]

# Synthetic financial statements (INR millions):
# revenue, ebitda, net income, total assets, total debt, cash, current assets,
# current liabilities, previous-year revenue
_FINANCIALS = {
    "CP001": (48_500, 11_640, 7_760, 61_000, 9_300, 12_400, 27_500, 12_800, 43_100),
    "CP002": (72_000, 10_100, 2_450, 118_000, 46_500, 4_100, 31_000, 27_600, 70_300),
    "CP003": (21_400, 3_050, -320, 54_000, 31_800, 1_250, 6_900, 8_200, 24_100),
    "CP004": (95_000, 21_800, 8_900, 164_000, 49_000, 9_800, 38_500, 29_000, 88_400),
    "CP005": (33_600, 7_050, 4_200, 41_500, 8_900, 5_300, 18_200, 9_100, 29_800),
}

_TRADES_PER_COUNTERPARTY = 5
_PRODUCT_MIX = {
    "CP001": ["Equity Option", "Equity Option", "FX Forward", "FX Forward", "Interest Rate Swap"],
    "CP002": ["Interest Rate Swap", "Interest Rate Swap", "FX Forward", "Equity Option", "FX Forward"],
    "CP003": ["FX Forward", "FX Forward", "FX Forward", "Interest Rate Swap", "Equity Option"],
    "CP004": ["Interest Rate Swap", "Interest Rate Swap", "FX Forward", "Equity Option", "Equity Option"],
    "CP005": ["FX Forward", "FX Forward", "Equity Option", "Interest Rate Swap", "Equity Option"],
}


def generate_counterparties() -> pd.DataFrame:
    """Five fictional counterparties with limits and collateral terms (INR)."""
    columns = [
        "counterparty_id", "name", "sector", "country", "credit_rating", "credit_limit",
        "warning_threshold", "collateral", "collateral_threshold", "minimum_transfer_amount",
    ]
    frame = pd.DataFrame(_COUNTERPARTIES, columns=columns)
    for column in ("credit_limit", "collateral", "collateral_threshold", "minimum_transfer_amount"):
        frame[column] = frame[column] * MILLION
    return frame


def generate_financials() -> pd.DataFrame:
    """Synthetic latest-year financial statements for each counterparty (INR)."""
    columns = [
        "revenue", "ebitda", "net_income", "total_assets", "total_debt", "cash",
        "current_assets", "current_liabilities", "previous_revenue",
    ]
    frame = pd.DataFrame.from_dict(_FINANCIALS, orient="index", columns=columns) * MILLION
    frame.index.name = "counterparty_id"
    frame = frame.reset_index()
    frame.insert(1, "fiscal_year", "FY2026")
    return frame


def _equity_option(rng: np.random.Generator) -> dict[str, object]:
    option_type = rng.choice(["Call", "Put"])
    position = rng.choice(["Long", "Short"], p=[0.65, 0.35])
    delta = rng.uniform(0.30, 0.70) * (1 if option_type == "Call" else -1)
    sign = 1 if position == "Long" else -1
    notional = float(rng.choice([150, 200, 250, 300, 400, 500])) * MILLION
    # Long options carry positive value (premium paid), short options negative.
    mtm = sign * rng.uniform(0.02, 0.06) * notional
    return {
        "underlying": f"NIFTY 50 {position} {option_type}",
        "notional": notional,
        "currency": "INR",
        "current_mtm": mtm,
        "sensitivity": round(sign * delta, 3),
        "volatility": round(rng.uniform(0.12, 0.19), 4),
        "tenor_years": float(rng.choice([0.25, 0.5, 0.75, 1.0])),
    }


def _fx_forward(rng: np.random.Generator, usdinr: float) -> dict[str, object]:
    direction = rng.choice([1, -1])  # +1 = bank buys USD forward
    notional_usd = float(rng.choice([2, 3, 4, 5, 6, 8])) * MILLION
    mtm = rng.uniform(-0.02, 0.03) * notional_usd * usdinr
    return {
        "underlying": f"USD/INR {'Buy' if direction > 0 else 'Sell'} USD Forward",
        "notional": notional_usd,
        "currency": "USD",
        "current_mtm": mtm,
        "sensitivity": float(direction),
        "volatility": round(rng.uniform(0.04, 0.07), 4),
        "tenor_years": float(rng.choice([0.25, 0.5, 1.0, 1.5])),
    }


def _interest_rate_swap(rng: np.random.Generator) -> dict[str, object]:
    direction = rng.choice([1, -1])  # +1 = pay fixed (gains when rates rise)
    tenor = float(rng.choice([2, 3, 5, 7, 10]))
    duration = round(0.88 * tenor, 2)
    notional = float(rng.choice([300, 500, 750, 1000])) * MILLION
    mtm = rng.uniform(-0.010, 0.014) * notional
    return {
        "underlying": f"INR {tenor:g}Y IRS {'Pay' if direction > 0 else 'Receive'} Fixed",
        "notional": notional,
        "currency": "INR",
        "current_mtm": mtm,
        "sensitivity": float(direction * duration),
        "volatility": round(rng.uniform(0.008, 0.012), 4),
        "tenor_years": tenor,
    }


def generate_trades(seed: int, as_of: pd.Timestamp, usdinr: float) -> pd.DataFrame:
    """Twenty-five OTC derivative trades across the five counterparties.

    * ``notional`` is in the trade currency; ``current_mtm`` is in INR.
    * ``sensitivity`` is the signed PnL per unit notional per unit shock:
      option delta, +/-1 for FX forwards, +/- modified duration for swaps.
    * ``volatility`` is the annualised volatility quoted for the trade.
    """
    rng = np.random.default_rng(seed)
    rows: list[dict[str, object]] = []
    trade_number = 1
    for counterparty_id, products in _PRODUCT_MIX.items():
        for product in products[:_TRADES_PER_COUNTERPARTY]:
            if product == "Equity Option":
                details = _equity_option(rng)
            elif product == "FX Forward":
                details = _fx_forward(rng, usdinr)
            else:
                details = _interest_rate_swap(rng)
            tenor = details.pop("tenor_years")
            maturity = (as_of + pd.Timedelta(days=round(365.25 * tenor))).strftime("%Y-%m-%d")
            rows.append(
                {
                    "trade_id": f"T{trade_number:03d}",
                    "counterparty_id": counterparty_id,
                    "product_type": product,
                    "risk_factor": PRODUCT_RISK_FACTOR[product],
                    "maturity": maturity,
                    **details,
                    "current_mtm": round(float(details["current_mtm"]), 2),
                }
            )
            trade_number += 1
    columns = [
        "trade_id", "counterparty_id", "product_type", "underlying", "risk_factor", "notional",
        "currency", "maturity", "current_mtm", "sensitivity", "volatility",
    ]
    return pd.DataFrame(rows)[columns]


def write_dataset(
    counterparties_path: Path,
    trades_path: Path,
    financials_path: Path,
    seed: int,
    as_of: pd.Timestamp,
    usdinr: float,
) -> None:
    """Generate the synthetic dataset and write it as CSV files."""
    for path in (counterparties_path, trades_path, financials_path):
        path.parent.mkdir(parents=True, exist_ok=True)
    generate_counterparties().to_csv(counterparties_path, index=False)
    generate_trades(seed, as_of, usdinr).to_csv(trades_path, index=False)
    generate_financials().to_csv(financials_path, index=False)
    logger.info("Synthetic dataset written (seed=%d, as of %s)", seed, as_of.date())
