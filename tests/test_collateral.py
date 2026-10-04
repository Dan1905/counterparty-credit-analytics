"""Collateral adjustment, requirement and minimum transfer amount."""

from __future__ import annotations

import pandas as pd
import pytest

from ccr import collateral


def test_net_exposure_is_gross_less_collateral_floored_at_zero():
    assert collateral.net_exposure(30.0, 20.0) == 10.0
    assert collateral.net_exposure(30.0, 45.0) == 0.0


def test_higher_collateral_gives_lower_net_exposure():
    values = [collateral.net_exposure(50.0, c) for c in (0.0, 10.0, 25.0, 50.0, 80.0)]
    assert values == sorted(values, reverse=True)
    assert values[0] > values[-1]


def test_collateral_requirement_is_exposure_above_threshold():
    assert collateral.collateral_requirement(30.0, 5.0) == 25.0
    assert collateral.collateral_requirement(3.0, 5.0) == 0.0


def test_transfer_respects_minimum_transfer_amount():
    assert collateral.collateral_transfer(25.0, 20.0, 1.0) == 5.0      # call
    assert collateral.collateral_transfer(20.4, 20.0, 1.0) == 0.0      # below MTA
    assert collateral.collateral_transfer(10.0, 20.0, 1.0) == -10.0    # return excess
    assert collateral.collateral_transfer(21.0, 20.0, 1.0) == 1.0      # exactly the MTA transfers


def test_collateral_summary(counterparties):
    exposure = pd.DataFrame({"counterparty_id": ["CP_A", "CP_B"], "gross_exposure": [16.0, 1.5]})
    table = collateral.collateral_summary(exposure, counterparties).set_index("counterparty_id")
    # CP_A: requirement = 16 - 2 = 14, held 5 -> call 9
    assert table.loc["CP_A", "collateral_requirement"] == pytest.approx(14.0)
    assert table.loc["CP_A", "transfer_amount"] == pytest.approx(9.0)
    assert table.loc["CP_A", "action"] == "Call"
    assert table.loc["CP_A", "net_exposure"] == pytest.approx(11.0)
    assert table.loc["CP_A", "net_exposure_after_transfer"] == pytest.approx(2.0)
    # CP_B: requirement = 0.5, held 0 -> shortfall below the MTA of 1 -> no transfer
    assert table.loc["CP_B", "collateral_requirement"] == pytest.approx(0.5)
    assert table.loc["CP_B", "transfer_amount"] == 0.0
    assert table.loc["CP_B", "action"] == "No transfer"
