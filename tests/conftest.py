"""Shared fixtures: a small hand-built portfolio whose numbers can be checked by hand."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ccr.config import Config, load_config  # noqa: E402


@pytest.fixture(scope="session")
def config() -> Config:
    return load_config()


@pytest.fixture
def trades() -> pd.DataFrame:
    """Three trades for CP_A (two positive, one negative MTM) and one for CP_B."""
    return pd.DataFrame(
        {
            "trade_id": ["T1", "T2", "T3", "T4"],
            "counterparty_id": ["CP_A", "CP_A", "CP_A", "CP_B"],
            "product_type": ["Equity Option", "FX Forward", "Interest Rate Swap", "FX Forward"],
            "underlying": ["NIFTY 50", "USD/INR", "INR 5Y IRS", "USD/INR"],
            "risk_factor": ["NIFTY50", "USDINR", "RATE_10Y", "USDINR"],
            "notional": [100.0, 2.0, 500.0, 1.0],
            "currency": ["INR", "USD", "INR", "USD"],
            "maturity": ["2027-01-01"] * 4,
            "current_mtm": [10.0, -4.0, 6.0, -5.0],
            "sensitivity": [0.5, 1.0, -4.0, -1.0],
            "volatility": [0.15, 0.05, 0.01, 0.05],
        }
    )


@pytest.fixture
def trades_base(trades: pd.DataFrame) -> pd.DataFrame:
    """Trades with ``notional_base`` at USD/INR = 100."""
    result = trades.copy()
    result["notional_base"] = [100.0, 200.0, 500.0, 100.0]
    return result


@pytest.fixture
def scenarios() -> pd.DataFrame:
    """Three scenarios: equity up, FX up, rates up."""
    return pd.DataFrame(
        {
            "NIFTY50": [0.10, 0.0, 0.0],
            "USDINR": [0.0, 0.05, 0.0],
            "RATE_10Y": [0.0, 0.0, 0.01],
        },
        index=pd.to_datetime(["2026-01-01", "2026-01-02", "2026-01-05"]),
    )


@pytest.fixture
def counterparties() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "counterparty_id": ["CP_A", "CP_B"],
            "name": ["Alpha Ltd", "Beta Ltd"],
            "sector": ["Technology", "Energy"],
            "country": ["India", "India"],
            "credit_rating": ["A", "BBB"],
            "credit_limit": [20.0, 10.0],
            "warning_threshold": [0.8, 0.8],
            "collateral": [5.0, 0.0],
            "collateral_threshold": [2.0, 1.0],
            "minimum_transfer_amount": [1.0, 1.0],
        }
    )


@pytest.fixture
def rng() -> np.random.Generator:
    return np.random.default_rng(7)
