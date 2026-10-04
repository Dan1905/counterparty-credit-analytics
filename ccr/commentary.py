"""Automated daily risk commentary generated from the calculated metrics.

Nothing here is hard-coded text about a particular counterparty: every
sentence is assembled from today's and the previous day's risk results.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import pandas as pd

from ccr.formatting import money, multiple, percent
from ccr.limits import STATUS_BREACH, STATUS_NORMAL, STATUS_WARNING
from ccr.market_data import RISK_FACTORS

if TYPE_CHECKING:  # pragma: no cover
    from ccr.pipeline import RiskResults

SEVERITY_ORDER = {"Breach": 0, "Warning": 1, "Info": 2}


@dataclass(frozen=True)
class CommentaryItem:
    """One paragraph of commentary."""

    scope: str      # "Portfolio", "Market" or a counterparty ID
    severity: str   # "Breach", "Warning" or "Info"
    text: str


def _direction(change: float) -> str:
    return "increased" if change > 0 else "decreased"


def _moved(label: str, old: float, new: float, currency: str) -> str:
    """'<label> increased from ₹52.0M to ₹57.0M' (or 'was unchanged at ...')."""
    if abs(new - old) < 50_000:  # less than ₹0.05M does not show at one decimal
        return f"{label} was unchanged at {money(new, currency)}"
    return f"{label} {_direction(new - old)} from {money(old, currency)} to {money(new, currency)}"


def _relative_change(old: float, new: float) -> float:
    if old == 0:
        return float("inf") if new != 0 else 0.0
    return (new - old) / abs(old)


def market_commentary(results: "RiskResults") -> CommentaryItem:
    """Describe the latest one-day market move in each risk factor."""
    last = results.market_returns.iloc[-1]
    parts = []
    for name, move in last.items():
        factor = RISK_FACTORS[name]
        level = results.market_levels[name].iloc[-1]
        if factor.shock_type == "relative":
            parts.append(f"{factor.label} {'rose' if move >= 0 else 'fell'} {abs(move) * 100:.2f}% to {level:,.2f}")
        else:
            parts.append(
                f"the {factor.label} {'rose' if move >= 0 else 'fell'} {abs(move) * 1e4:.1f}bp to {level:.3f}%"
            )
    text = f"Market moves on {results.today.as_of:%d %b %Y}: " + "; ".join(parts) + "."
    return CommentaryItem("Market", "Info", text)


def portfolio_commentary(results: "RiskResults", pfe_col: str) -> CommentaryItem:
    """Portfolio-level totals and their day-on-day change."""
    today, previous = results.today, results.previous
    ccy = results.config.base_currency
    pfe_label = f"{pfe_col.split('_')[1]}% PFE"
    if previous is None:
        text = (
            f"Portfolio current exposure is {money(today.portfolio['current_exposure'], ccy)}, "
            f"{pfe_label} is {money(today.portfolio[pfe_col], ccy)} and total Initial Margin is "
            f"{money(today.total_initial_margin, ccy)}."
        )
    else:
        text = (
            _moved("Portfolio current exposure", previous.portfolio["current_exposure"],
                   today.portfolio["current_exposure"], ccy)
            + "; "
            + _moved(f"portfolio {pfe_label}", previous.portfolio[pfe_col], today.portfolio[pfe_col], ccy)
            + "; "
            + _moved("total Initial Margin", previous.total_initial_margin,
                     today.total_initial_margin, ccy)
            + "."
        )
    breaches = today.limits.loc[today.limits["status"] == STATUS_BREACH, "counterparty_id"].tolist()
    warnings = today.limits.loc[today.limits["status"] == STATUS_WARNING, "counterparty_id"].tolist()
    if breaches:
        text += f" {len(breaches)} counterparty limit breach(es): {', '.join(breaches)}."
    if warnings:
        text += f" {len(warnings)} counterparty(ies) above the warning threshold: {', '.join(warnings)}."
    if not breaches and not warnings:
        text += " All counterparties are within their credit limits."
    severity = "Breach" if breaches else "Warning" if warnings else "Info"
    return CommentaryItem("Portfolio", severity, text)


def counterparty_commentary(results: "RiskResults", counterparty_id: str, pfe_col: str) -> CommentaryItem:
    """Exposure, PFE, limit, collateral, margin and financial commentary for one counterparty."""
    cfg = results.config
    ccy = cfg.base_currency
    today, previous = results.today, results.previous
    pfe_label = f"{pfe_col.split('_')[1]}% PFE"

    def row(frame: pd.DataFrame) -> pd.Series:
        return frame.set_index("counterparty_id").loc[counterparty_id]

    exp, lim, col, im = row(today.exposure), row(today.limits), row(today.collateral), row(
        today.margin_counterparties
    )
    credit = row(results.credit)
    sentences: list[str] = []

    # --- exposure and PFE ---------------------------------------------------
    if previous is not None:
        prev_exp, prev_lim = row(previous.exposure), row(previous.limits)
        pfe_change = exp[pfe_col] - prev_exp[pfe_col]
        cause = ""
        if abs(_relative_change(prev_exp[pfe_col], exp[pfe_col])) >= cfg.commentary.exposure_change_pct:
            cause = (
                " following adverse market movements" if pfe_change > 0
                else " following favourable market movements"
            )
        sentences.append(
            _moved(f"{counterparty_id}'s {pfe_label}", prev_exp[pfe_col], exp[pfe_col], ccy) + cause + "."
        )
        if abs(_relative_change(prev_exp["current_exposure"], exp["current_exposure"])) >= (
            cfg.commentary.exposure_change_pct
        ):
            sentences.append(
                _moved("Current exposure", prev_exp["current_exposure"], exp["current_exposure"], ccy) + "."
            )
    else:
        prev_lim = None
        sentences.append(
            f"{counterparty_id}'s {pfe_label} is {money(exp[pfe_col], ccy)} against current exposure of "
            f"{money(exp['current_exposure'], ccy)}."
        )

    # --- limit status -------------------------------------------------------
    limit_text = money(lim["credit_limit"], ccy, 0)
    measure = pfe_label if lim["driver"] == "PFE" else "Net exposure"
    status_changed = prev_lim is not None and prev_lim["status"] != lim["status"]
    if lim["status"] == STATUS_BREACH:
        outcome = "resulting in a limit breach" if status_changed else "so the limit breach continues"
        sentences.append(
            f"{measure} {'now ' if status_changed else ''}exceeds the {limit_text} credit limit "
            f"({percent(lim['utilisation'])} utilisation), {outcome}."
        )
    elif lim["status"] == STATUS_WARNING:
        sentences.append(
            f"Utilisation of the {limit_text} credit limit is {percent(lim['utilisation'])}, above the "
            f"{percent(lim['warning_threshold'])} warning threshold; headroom is {money(lim['headroom'], ccy)}."
        )
        if status_changed and prev_lim["status"] == STATUS_BREACH:
            sentences.append("The previous day's limit breach has cleared.")
    else:
        text = f"Utilisation of the {limit_text} credit limit is {percent(lim['utilisation'])} (Normal)."
        if status_changed:
            text += f" Status improved from {prev_lim['status']}."
        sentences.append(text)

    # --- collateral ---------------------------------------------------------
    collateral_text = (
        f"Net exposure after {money(col['collateral_held'], ccy)} of collateral is "
        f"{money(col['net_exposure'], ccy)}"
    )
    if col["action"] == "Call":
        collateral_text += f"; a collateral call of {money(col['transfer_amount'], ccy)} is due"
    elif col["action"] == "Return":
        collateral_text += f"; {money(-col['transfer_amount'], ccy)} of excess collateral is returnable"
    elif abs(col["shortfall"]) > 0:
        collateral_text += (
            f"; the {money(abs(col['shortfall']), ccy, 2)} difference to the requirement is below the "
            f"{money(col['minimum_transfer_amount'], ccy, 2)} minimum transfer amount, so no transfer is made"
        )
    if previous is not None:
        prev_col = row(previous.collateral)
        change = col["collateral_requirement"] - prev_col["collateral_requirement"]
        if abs(change) >= 50_000:
            collateral_text += (
                f". The collateral requirement {_direction(change)} by {money(abs(change), ccy)} to "
                f"{money(col['collateral_requirement'], ccy)}"
            )
    sentences.append(collateral_text + ".")

    # --- initial margin -----------------------------------------------------
    if previous is not None:
        prev_im = row(previous.margin_counterparties)["initial_margin"]
        change = im["initial_margin"] - prev_im
        if abs(_relative_change(prev_im, im["initial_margin"])) >= cfg.commentary.margin_change_pct:
            sentences.append(
                f"Initial Margin {_direction(change)} by {money(abs(change), ccy, 2)} to "
                f"{money(im['initial_margin'], ccy)}."
            )
        else:
            sentences.append(f"Initial Margin is broadly unchanged at {money(im['initial_margin'], ccy)}.")
    else:
        sentences.append(f"Initial Margin is {money(im['initial_margin'], ccy)}.")

    # --- financial risk metrics ----------------------------------------------
    flags = []
    if credit["revenue_growth"] <= cfg.commentary.revenue_decline_flag:
        flags.append(f"revenue fell {percent(abs(credit['revenue_growth']), 1)} year on year")
    if credit["debt_to_ebitda"] >= cfg.commentary.leverage_flag:
        flags.append(f"leverage is high at {multiple(credit['debt_to_ebitda'], 1)} Debt/EBITDA")
    if credit["net_margin"] < 0:
        flags.append(f"the net margin is negative ({percent(credit['net_margin'], 1)})")
    if credit["current_ratio"] < 1.0:
        flags.append(f"the current ratio is below 1.0 ({multiple(credit['current_ratio'])})")
    if flags or credit["risk_category"] in ("Elevated", "High"):
        text = (
            f"Internal credit score is {credit['credit_score']:.0f}/100 ({credit['risk_category']} risk)"
        )
        if flags:
            text += ": " + ", ".join(flags)
        sentences.append(text + ".")

    severity = lim["status"] if lim["status"] != STATUS_NORMAL else "Info"
    return CommentaryItem(counterparty_id, severity, " ".join(sentences))


def generate_commentary(results: "RiskResults") -> list[CommentaryItem]:
    """Full daily commentary: market, portfolio, then counterparties (worst status first)."""
    pfe_col = f"pfe_{max(results.config.exposure.pfe_confidence_levels) * 100:g}".replace(".", "_")
    items = [portfolio_commentary(results, pfe_col), market_commentary(results)]

    highlights = results.highlights
    increase = highlights.get("largest_exposure_increase")
    if increase and increase["value"] > 0:
        items.append(
            CommentaryItem(
                "Portfolio",
                "Info",
                f"Largest increase in current exposure: {increase['counterparty_id']} "
                f"(+{money(increase['value'], results.config.base_currency)}). Highest utilisation: "
                f"{highlights['highest_utilisation']['counterparty_id']} at "
                f"{percent(highlights['highest_utilisation']['value'])}.",
            )
        )

    counterparty_items = [
        counterparty_commentary(results, cp, pfe_col)
        for cp in results.today.limits["counterparty_id"]
    ]
    counterparty_items.sort(key=lambda item: SEVERITY_ORDER[item.severity])
    return items + counterparty_items
