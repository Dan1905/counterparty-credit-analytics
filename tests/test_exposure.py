"""Exposure calculation, EE and PFE."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from ccr import exposure


def test_pnl_change_is_sensitivity_times_shock_times_notional():
    assert exposure.pnl_change(0.5, 0.10, 100.0) == pytest.approx(5.0)
    assert exposure.pnl_change(-4.0, 0.01, 500.0) == pytest.approx(-20.0)


def test_base_notional_converts_foreign_currency(trades):
    base = exposure.base_notional(trades, {"INR": 1.0, "USD": 100.0})
    assert base.tolist() == [100.0, 200.0, 500.0, 100.0]


def test_base_notional_rejects_unknown_currency(trades):
    with pytest.raises(exposure.ExposureError):
        exposure.base_notional(trades, {"INR": 1.0})


def test_positive_exposure_floors_at_zero():
    assert exposure.positive_exposure(np.array([-3.0, 0.0, 2.5])).tolist() == [0.0, 0.0, 2.5]


def test_scenario_mtm_matrix(trades_base, scenarios):
    mtm = exposure.scenario_mtm_matrix(trades_base, scenarios)
    assert mtm.shape == (3, 4)
    # Scenario 1 (equity +10%): T1 = 10 + 0.5 * 0.10 * 100 = 15; others unchanged
    assert mtm.iloc[0].tolist() == pytest.approx([15.0, -4.0, 6.0, -5.0])
    # Scenario 2 (FX +5%): T2 = -4 + 1 * 0.05 * 200 = 6; T4 = -5 - 1 * 0.05 * 100 = -10
    assert mtm.iloc[1].tolist() == pytest.approx([10.0, 6.0, 6.0, -10.0])
    # Scenario 3 (rates +100bp): T3 = 6 - 4 * 0.01 * 500 = -14
    assert mtm.iloc[2].tolist() == pytest.approx([10.0, -4.0, -14.0, -5.0])


def test_gross_counterparty_exposure_sums_positive_trades(trades_base, scenarios):
    mtm = exposure.scenario_mtm_matrix(trades_base, scenarios)
    dist = exposure.counterparty_exposure_distribution(mtm, trades_base, "gross")
    assert dist["CP_A"].tolist() == pytest.approx([21.0, 22.0, 10.0])
    assert dist["CP_B"].tolist() == pytest.approx([0.0, 0.0, 0.0])


def test_netted_counterparty_exposure_offsets_trades(trades_base, scenarios):
    mtm = exposure.scenario_mtm_matrix(trades_base, scenarios)
    dist = exposure.counterparty_exposure_distribution(mtm, trades_base, "netted")
    assert dist["CP_A"].tolist() == pytest.approx([17.0, 22.0, 0.0])
    gross = exposure.counterparty_exposure_distribution(mtm, trades_base, "gross")
    assert (dist <= gross + 1e-12).all().all()


def test_current_exposures(trades_base):
    current = exposure.current_exposures(trades_base)
    assert current.loc["CP_A", "current_exposure"] == pytest.approx(12.0)   # max(10 - 4 + 6, 0)
    assert current.loc["CP_A", "gross_exposure"] == pytest.approx(16.0)     # 10 + 6
    assert current.loc["CP_B", "current_exposure"] == 0.0
    assert current.loc["CP_B", "gross_exposure"] == 0.0


def test_expected_exposure_is_mean_of_positive_exposures():
    assert exposure.expected_exposure(np.array([10.0, 20.0, 30.0])) == pytest.approx(20.0)
    assert exposure.expected_exposure(np.array([-10.0, 10.0])) == pytest.approx(5.0)


def test_pfe_is_percentile_of_distribution():
    values = np.arange(1, 101, dtype=float)
    assert exposure.potential_future_exposure(values, 0.99) == pytest.approx(np.quantile(values, 0.99))
    assert exposure.potential_future_exposure(values, 0.95) == pytest.approx(95.05)


def test_pfe_99_at_least_pfe_95(rng):
    for _ in range(20):
        values = rng.normal(0, 10, size=400)
        assert exposure.potential_future_exposure(values, 0.99) >= exposure.potential_future_exposure(values, 0.95)


def test_pfe_at_least_expected_exposure_for_upper_tail(rng):
    values = np.maximum(rng.normal(5, 10, size=500), 0)
    assert exposure.potential_future_exposure(values, 0.95) >= exposure.expected_exposure(values)


@pytest.mark.parametrize("bad", [0.0, 1.0, 1.5, -0.1])
def test_pfe_rejects_invalid_confidence(bad):
    with pytest.raises(exposure.ExposureError):
        exposure.potential_future_exposure(np.array([1.0, 2.0]), bad)


def test_empty_distribution_raises():
    with pytest.raises(exposure.ExposureError):
        exposure.expected_exposure(np.array([]))


def test_exposure_summary_and_portfolio(trades_base, scenarios):
    mtm = exposure.scenario_mtm_matrix(trades_base, scenarios)
    dist = exposure.counterparty_exposure_distribution(mtm, trades_base, "gross")
    collateral = pd.Series({"CP_A": 5.0, "CP_B": 0.0})
    summary = exposure.exposure_summary(trades_base, dist, collateral, (0.95, 0.99)).set_index("counterparty_id")
    assert summary.loc["CP_A", "net_exposure"] == pytest.approx(11.0)       # max(16 - 5, 0)
    assert summary.loc["CP_A", "expected_exposure"] == pytest.approx((21 + 22 + 10) / 3)
    assert summary.loc["CP_A", "pfe_99"] >= summary.loc["CP_A", "pfe_95"]
    portfolio = exposure.portfolio_summary(summary.reset_index(), dist, (0.95, 0.99))
    assert portfolio["gross_exposure"] == pytest.approx(16.0)
    # diversified portfolio PFE can never exceed the sum of stand-alone PFEs
    assert portfolio["pfe_99"] <= portfolio["pfe_99_sum_of_counterparties"] + 1e-9


def test_validate_trades_rejects_duplicates_and_unknown_factors(trades):
    exposure.validate_trades(trades, ["NIFTY50", "USDINR", "RATE_10Y"])
    with pytest.raises(exposure.ExposureError):
        exposure.validate_trades(trades, ["NIFTY50"])
    duplicated = trades.copy()
    duplicated.loc[1, "trade_id"] = "T1"
    with pytest.raises(exposure.ExposureError):
        exposure.validate_trades(duplicated, ["NIFTY50", "USDINR", "RATE_10Y"])
