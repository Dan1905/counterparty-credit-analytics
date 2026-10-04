"""Market data: returns, statistics and scenario construction."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from ccr import market_data as md


@pytest.fixture
def levels() -> pd.DataFrame:
    return md.generate_synthetic_market_data(n_days=300, seed=1, end="2026-06-30")


def test_synthetic_data_is_reproducible():
    a = md.generate_synthetic_market_data(n_days=50, seed=3, end="2026-06-30")
    b = md.generate_synthetic_market_data(n_days=50, seed=3, end="2026-06-30")
    pd.testing.assert_frame_equal(a, b)


def test_daily_returns_relative_and_absolute():
    frame = pd.DataFrame(
        {"NIFTY50": [100.0, 110.0], "USDINR": [80.0, 76.0], "RATE_10Y": [5.00, 5.25]},
        index=pd.to_datetime(["2026-01-01", "2026-01-02"]),
    )
    returns = md.compute_daily_returns(frame).iloc[0]
    assert returns["NIFTY50"] == pytest.approx(0.10)
    assert returns["USDINR"] == pytest.approx(-0.05)
    assert returns["RATE_10Y"] == pytest.approx(0.0025)   # 25bp as a decimal


def test_return_statistics(levels):
    returns = md.compute_daily_returns(levels)
    stats = md.return_statistics(returns, (0.01, 0.99))
    row = stats.loc["NIFTY50"]
    assert row["daily_volatility"] == pytest.approx(returns["NIFTY50"].std(ddof=1))
    assert row["annualised_volatility"] == pytest.approx(row["daily_volatility"] * np.sqrt(252))
    assert row["min_return"] <= row["p1"] <= row["mean_return"] <= row["p99"] <= row["max_return"]


def test_build_scenarios_respects_lookback_horizon_and_as_of(levels):
    as_of = levels.index[-20]
    scenarios = md.build_scenarios(levels, horizon=10, lookback=100, as_of=as_of)
    assert len(scenarios) == 100
    assert scenarios.index.max() == as_of                     # no look-ahead
    expected = levels["NIFTY50"].loc[as_of] / levels["NIFTY50"].shift(10).loc[as_of] - 1
    assert scenarios["NIFTY50"].iloc[-1] == pytest.approx(expected)


def test_too_little_history_raises(levels):
    with pytest.raises(md.MarketDataError):
        md.build_scenarios(levels.head(20), horizon=10, lookback=100)


def test_clean_levels_requires_all_factors(levels):
    with pytest.raises(md.MarketDataError):
        md.clean_levels(levels.drop(columns="USDINR"))


def test_save_and_load_round_trip(levels, tmp_path):
    path = tmp_path / "market.csv"
    md.save_market_data(levels, path, "synthetic")
    loaded = md.load_market_data(path)
    np.testing.assert_allclose(loaded.to_numpy(), levels.to_numpy())
    assert md.load_market_metadata(path)["source"] == "synthetic"
