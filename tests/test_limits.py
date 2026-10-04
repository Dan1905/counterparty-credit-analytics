"""Credit-limit utilisation and breach detection."""

from __future__ import annotations

import pandas as pd
import pytest

from ccr import limits
from ccr.config import LimitsConfig


def test_utilisation():
    assert limits.utilisation(57.0, 50.0) == pytest.approx(1.14)
    assert limits.utilisation(0.0, 50.0) == 0.0
    with pytest.raises(limits.LimitError):
        limits.utilisation(10.0, 0.0)


@pytest.mark.parametrize(
    ("ratio", "expected"),
    [(0.0, "Normal"), (0.79, "Normal"), (0.80, "Warning"), (0.99, "Warning"), (1.0, "Warning"),
     (1.0001, "Breach"), (1.14, "Breach")],
)
def test_classify_status(ratio, expected):
    assert limits.classify_status(ratio, warning_threshold=0.80, breach_threshold=1.0) == expected


def _exposure(net: float, pfe: float, current: float = 0.0) -> pd.DataFrame:
    return pd.DataFrame(
        {"counterparty_id": ["CP_A", "CP_B"], "current_exposure": [current, 1.0],
         "net_exposure": [net, 1.0], "pfe_99": [pfe, 2.0]}
    )


def test_exposure_above_limit_is_a_breach(counterparties):
    table = limits.limit_monitoring(_exposure(net=25.0, pfe=10.0), counterparties, LimitsConfig())
    row = table.set_index("counterparty_id").loc["CP_A"]
    assert row["exposure_utilisation"] == pytest.approx(1.25)
    assert row["status"] == "Breach"
    assert row["driver"] == "Net exposure"
    assert row["headroom"] < 0


def test_pfe_above_limit_is_a_breach_like_spec_example(counterparties):
    cps = counterparties.copy()
    cps.loc[0, "credit_limit"] = 50.0
    table = limits.limit_monitoring(_exposure(net=27.0, pfe=57.0), cps, LimitsConfig())
    row = table.set_index("counterparty_id").loc["CP_A"]
    assert row["pfe_utilisation"] == pytest.approx(1.14)
    assert row["status"] == "Breach"
    assert row["driver"] == "PFE"


def test_warning_and_normal_and_ordering(counterparties):
    table = limits.limit_monitoring(_exposure(net=5.0, pfe=17.0), counterparties, LimitsConfig())
    by_cp = table.set_index("counterparty_id")
    assert by_cp.loc["CP_A", "status"] == "Warning"      # 17 / 20 = 85%
    assert by_cp.loc["CP_B", "status"] == "Normal"       # 2 / 10 = 20%
    assert table.iloc[0]["counterparty_id"] == "CP_A"    # worst status first
    flagged = limits.breaches_and_warnings(table)
    assert flagged["counterparty_id"].tolist() == ["CP_A"]


def test_counterparty_specific_warning_threshold(counterparties):
    cps = counterparties.copy()
    cps.loc[0, "warning_threshold"] = 0.90
    table = limits.limit_monitoring(_exposure(net=5.0, pfe=17.0), cps, LimitsConfig())
    assert table.set_index("counterparty_id").loc["CP_A", "status"] == "Normal"


def test_key_risk_highlights(counterparties):
    today = _exposure(net=5.0, pfe=17.0, current=9.0)
    previous = _exposure(net=4.0, pfe=15.0, current=6.0)
    table = limits.limit_monitoring(today, counterparties, LimitsConfig())
    highlights = limits.key_risk_highlights(table, today, previous)
    assert highlights["largest_exposure"]["counterparty_id"] == "CP_A"
    assert highlights["highest_pfe"]["value"] == pytest.approx(17.0)
    assert highlights["highest_utilisation"]["value"] == pytest.approx(0.85)
    assert highlights["largest_exposure_increase"] == {"counterparty_id": "CP_A", "value": pytest.approx(3.0)}
