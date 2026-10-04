"""Plotly figure builders. Each function takes result frames and returns a styled figure.

Colour is assigned by job: blue ramp for exposure measures, grey for reference
data, a fixed categorical order for products, and the reserved status colours
(always paired with a text label) for limit status and risk category.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go

from ccr.market_data import RISK_FACTORS
from dashboard.theme import (
    ACCENT,
    BG,
    BLUE_RAMP,
    BORDER,
    CATEGORY_COLOURS,
    GRID,
    MILLION,
    NEUTRAL,
    PRODUCT_COLOURS,
    STATUS_COLOURS,
    TEXT_MUTED,
    TEXT_PRIMARY,
    TEXT_SECONDARY,
    style_figure,
)

_MONEY_HOVER = "<b>%{x}</b><br>%{fullData.name}: ₹%{y:,.1f}M<extra></extra>"


def _reference_line(fig: go.Figure, x: float, label: str, colour: str = TEXT_MUTED, dash: str = "dot") -> None:
    fig.add_vline(x=x, line=dict(color=colour, width=1, dash=dash))
    fig.add_annotation(
        x=x, y=1.0, yref="paper", yanchor="bottom", showarrow=False, text=label,
        font=dict(color=TEXT_SECONDARY, size=11),
    )


# --------------------------------------------------------------------------- #
# Exposure
# --------------------------------------------------------------------------- #
def exposure_profile(view: pd.DataFrame, pfe_columns: dict[str, str]) -> go.Figure:
    """Current exposure, EE and PFE per counterparty with the credit limit as a marker."""
    fig = go.Figure()
    fig.add_bar(
        x=view["counterparty_id"], y=view["current_exposure"] / MILLION, name="Current exposure",
        marker_color=NEUTRAL, hovertemplate=_MONEY_HOVER,
    )
    measures = [("expected_exposure", "EE"), *[(column, label) for label, column in pfe_columns.items()]]
    for (column, label), colour in zip(measures, BLUE_RAMP):
        fig.add_bar(
            x=view["counterparty_id"], y=view[column] / MILLION, name=label,
            marker_color=colour, hovertemplate=_MONEY_HOVER,
        )
    fig.add_scatter(
        x=view["counterparty_id"], y=view["credit_limit"] / MILLION, name="Credit limit", mode="markers",
        marker=dict(symbol="line-ew", size=46, line=dict(width=1.5, color=TEXT_PRIMARY)),
        hovertemplate="<b>%{x}</b><br>Credit limit: ₹%{y:,.1f}M<extra></extra>",
    )
    fig.update_layout(barmode="group", bargap=0.26, bargroupgap=0.12)
    return style_figure(fig, height=372, money_axis="y")


def exposure_components(view: pd.DataFrame) -> go.Figure:
    """Gross exposure, collateral held and net exposure per counterparty."""
    fig = go.Figure()
    series = [
        ("gross_exposure", "Gross exposure", ACCENT),
        ("collateral", "Collateral", NEUTRAL),
        ("net_exposure", "Net exposure", BLUE_RAMP[2]),
    ]
    for column, label, colour in series:
        fig.add_bar(
            x=view["counterparty_id"], y=view[column] / MILLION, name=label,
            marker_color=colour, hovertemplate=_MONEY_HOVER,
        )
    fig.update_layout(barmode="group", bargap=0.3)
    return style_figure(fig, money_axis="y")


def exposure_distribution(exposures: pd.Series, markers: list[tuple[str, float, str, str]]) -> go.Figure:
    """Histogram of scenario exposures. ``markers`` is ``[(label, value, colour, dash)]``."""
    fig = go.Figure(
        go.Histogram(
            x=exposures / MILLION, nbinsx=44, marker_color=BLUE_RAMP[0],
            marker_line=dict(color=BG, width=1), name="Scenarios",
            hovertemplate="Exposure ₹%{x}M<br>%{y} scenarios<extra></extra>",
        )
    )
    values = [value for _, value, _, _ in markers]
    low = min(float(exposures.min()), *values)
    high = max(float(exposures.max()), *values)
    span = (high - low) or 1.0
    pad = span * 0.04
    for index, (label, value, colour, dash) in enumerate(sorted(markers, key=lambda m: m[1])):
        on_right = (value - low) / span > 0.6  # label sits left of the line near the right edge
        fig.add_vline(x=value / MILLION, line=dict(color=colour, width=1.5, dash=dash))
        fig.add_annotation(
            x=value / MILLION, y=1.0 - 0.1 * index, yref="paper", yanchor="top",
            xanchor="right" if on_right else "left",
            text=f"{label} ₹{value / MILLION:,.1f}M " if on_right else f" {label} ₹{value / MILLION:,.1f}M", showarrow=False,
            font=dict(color=TEXT_PRIMARY, size=11), bgcolor="rgba(13,15,19,0.85)",
        )
    fig = style_figure(fig, height=360)
    fig.update_layout(showlegend=False, bargap=0.04, barcornerradius=0, margin=dict(t=8))
    fig.update_xaxes(title_text="Scenario exposure", tickprefix="₹", ticksuffix="M",
                     range=[(low - pad) / MILLION, (high + pad) / MILLION])
    fig.update_yaxes(title_text="Scenarios")
    return fig


def exposure_by_scenario(exposures: pd.Series, references: list[tuple[str, float, str]]) -> go.Figure:
    """Exposure under each historical scenario, ordered by the date the market move ended."""
    fig = go.Figure(
        go.Scatter(
            x=exposures.index, y=exposures / MILLION, mode="lines", name="Scenario exposure",
            line=dict(color=ACCENT, width=1.5),
            hovertemplate="Move ending %{x|%d %b %Y}<br>Exposure: ₹%{y:,.1f}M<extra></extra>",
        )
    )
    for label, value, colour in references:
        fig.add_hline(y=value / MILLION, line=dict(color=colour, width=1, dash="dash"))
        fig.add_annotation(
            x=1.0, xref="paper", xanchor="right", y=value / MILLION, yanchor="bottom", showarrow=False,
            text=f"{label} ₹{value / MILLION:,.1f}M", font=dict(color=TEXT_PRIMARY, size=11),
            bgcolor="rgba(13,15,19,0.85)",
        )
    fig = style_figure(fig, height=360, money_axis="y")
    fig.update_layout(showlegend=False, margin=dict(t=8))
    fig.update_xaxes(title_text="Scenario (end date of market move)")
    return fig


def product_exposure(frame: pd.DataFrame) -> go.Figure:
    """Gross current exposure and expected exposure by product."""
    ordered = frame.sort_values("expected_exposure")
    fig = go.Figure()
    for column, label, colour in (
        ("gross_exposure", "Gross current exposure", NEUTRAL),
        ("expected_exposure", "EE", BLUE_RAMP[1]),
    ):
        fig.add_bar(
            y=ordered["product_type"], x=ordered[column] / MILLION, name=label, orientation="h",
            marker_color=colour, hovertemplate="<b>%{y}</b><br>%{fullData.name}: ₹%{x:,.1f}M<extra></extra>",
        )
    fig.update_layout(barmode="group", bargap=0.34)
    fig = style_figure(fig, height=300, money_axis="x")
    fig.update_yaxes(ticksuffix="  ")
    return fig


def collateral_waterfall(gross: float, collateral_applied: float, net: float) -> go.Figure:
    """Gross Exposure - Collateral = Net Exposure."""
    fig = go.Figure(
        go.Waterfall(
            x=["Gross exposure", "Collateral", "Net exposure"],
            measure=["absolute", "relative", "total"],
            y=[gross / MILLION, -collateral_applied / MILLION, net / MILLION],
            text=[f"₹{gross / MILLION:,.1f}M", f"−₹{collateral_applied / MILLION:,.1f}M", f"₹{net / MILLION:,.1f}M"],
            textposition=["outside", "inside", "outside"], textfont=dict(color=TEXT_PRIMARY, size=12),
            insidetextanchor="middle", cliponaxis=False,
            connector=dict(line=dict(color=BORDER, width=1)),
            increasing=dict(marker=dict(color=ACCENT)),
            decreasing=dict(marker=dict(color=NEUTRAL)),
            totals=dict(marker=dict(color=BLUE_RAMP[2])),
            hovertemplate="<b>%{x}</b><br>%{text}<extra></extra>",
        )
    )
    fig = style_figure(fig, height=300, money_axis="y")
    fig.update_layout(showlegend=False, waterfallgap=0.5)
    fig.update_yaxes(rangemode="tozero")
    return fig


# --------------------------------------------------------------------------- #
# Limits and credit
# --------------------------------------------------------------------------- #
def limit_utilisation(limits: pd.DataFrame, breach_threshold: float = 1.0) -> go.Figure:
    """Utilisation bars coloured by status and labelled with value and status."""
    ordered = limits.sort_values("utilisation")
    fig = go.Figure(
        go.Bar(
            x=ordered["utilisation"], y=ordered["counterparty_id"], orientation="h",
            marker_color=[STATUS_COLOURS[s] for s in ordered["status"]],
            text=[f"{u:.1%}  {s.upper()}" for u, s in zip(ordered["utilisation"], ordered["status"])],
            textposition="outside", textfont=dict(color=TEXT_PRIMARY, size=11), cliponaxis=False,
            customdata=np.stack(
                [ordered["pfe"] / MILLION, ordered["net_exposure"] / MILLION,
                 ordered["credit_limit"] / MILLION, ordered["driver"]], axis=-1),
            hovertemplate=(
                "<b>%{y}</b><br>Utilisation: %{x:.1%} (driver: %{customdata[3]})<br>PFE 99%: ₹%{customdata[0]:,.1f}M"
                "<br>Net exposure: ₹%{customdata[1]:,.1f}M<br>Limit: ₹%{customdata[2]:,.1f}M<extra></extra>"
            ),
        )
    )
    _reference_line(fig, breach_threshold, "Limit", TEXT_SECONDARY, "dash")
    fig = style_figure(fig, height=max(220, 52 * len(ordered) + 70))
    upper = max(1.5, float(ordered["utilisation"].max()) * 1.45) if len(ordered) else 1.5
    fig.update_xaxes(range=[0, upper], tickformat=".0%", showgrid=True, gridcolor=GRID)
    fig.update_yaxes(showgrid=False, ticksuffix="  ")
    fig.update_layout(showlegend=False, bargap=0.5)
    return fig


def score_comparison(credit: pd.DataFrame) -> go.Figure:
    """Internal credit risk score per counterparty (0 = lowest risk, 100 = highest)."""
    ordered = credit.sort_values("credit_score")
    fig = go.Figure(
        go.Bar(
            x=ordered["credit_score"], y=ordered["counterparty_id"], orientation="h",
            marker_color=[CATEGORY_COLOURS[c] for c in ordered["risk_category"]],
            text=[f"{s:.0f}  {c.upper()}" for s, c in zip(ordered["credit_score"], ordered["risk_category"])],
            textposition="outside", textfont=dict(color=TEXT_PRIMARY, size=11), cliponaxis=False,
            customdata=ordered["name"],
            hovertemplate="<b>%{y}</b> %{customdata}<br>Risk score: %{x:.1f} / 100<extra></extra>",
        )
    )
    fig = style_figure(fig, height=max(220, 48 * len(ordered) + 70))
    fig.update_xaxes(range=[0, 135], showgrid=True, gridcolor=GRID, tickvals=[0, 25, 50, 75, 100],
                     title_text="Internal risk score (0 = lowest risk, 100 = highest)")
    fig.update_yaxes(showgrid=False, ticksuffix="  ")
    fig.update_layout(showlegend=False, bargap=0.5, margin=dict(t=8))
    return fig


# --------------------------------------------------------------------------- #
# Margin
# --------------------------------------------------------------------------- #
def margin_by_counterparty(factor_margin: pd.DataFrame) -> go.Figure:
    """Initial Margin per counterparty stacked by product."""
    fig = go.Figure()
    pivot = factor_margin.pivot_table(
        index="counterparty_id", columns="product_type", values="initial_margin", aggfunc="sum"
    ).fillna(0.0)
    for product, colour in PRODUCT_COLOURS.items():
        if product in pivot.columns:
            fig.add_bar(
                x=pivot.index, y=pivot[product] / MILLION, name=product, marker_color=colour,
                marker_line=dict(color=BG, width=2), hovertemplate=_MONEY_HOVER,
            )
    fig.update_layout(barmode="stack", bargap=0.5)
    fig = style_figure(fig, money_axis="y")
    fig.update_layout(barcornerradius=0)
    return fig


# --------------------------------------------------------------------------- #
# Market data
# --------------------------------------------------------------------------- #
def factor_unit(name: str) -> tuple[float, str]:
    """Scale and unit for displaying a factor's moves (% for prices, bp for yields)."""
    return (100.0, "%") if RISK_FACTORS[name].shock_type == "relative" else (10_000.0, "bp")


def price_history(levels: pd.Series, name: str) -> go.Figure:
    suffix = "%" if RISK_FACTORS[name].shock_type == "absolute" else ""
    fig = go.Figure(
        go.Scatter(
            x=levels.index, y=levels, mode="lines", line=dict(color=ACCENT, width=1.6),
            hovertemplate="%{x|%d %b %Y}<br>%{y:,.2f}" + suffix + "<extra></extra>",
        )
    )
    fig = style_figure(fig, height=300)
    fig.update_layout(showlegend=False, hovermode="x", margin=dict(t=8))
    fig.update_yaxes(tickformat=",.2f" if levels.max() < 1000 else ",.0f", ticksuffix=suffix,
                     title_text=RISK_FACTORS[name].unit.capitalize())
    return fig


def daily_returns(returns: pd.Series, name: str) -> go.Figure:
    scale, unit = factor_unit(name)
    fig = go.Figure(
        go.Bar(
            x=returns.index, y=returns * scale, marker_color=ACCENT, marker_line_width=0,
            hovertemplate="%{x|%d %b %Y}<br>%{y:+.2f}" + unit + "<extra></extra>",
        )
    )
    fig = style_figure(fig, height=290)
    fig.update_layout(showlegend=False, bargap=0, barcornerradius=0, margin=dict(t=8))
    fig.update_yaxes(ticksuffix=unit, title_text="Daily move")
    return fig


def rolling_volatility(volatility: pd.Series, name: str) -> go.Figure:
    scale, unit = factor_unit(name)
    fig = go.Figure(
        go.Scatter(
            x=volatility.index, y=volatility * scale, mode="lines", line=dict(color=ACCENT, width=1.6),
            hovertemplate="%{x|%d %b %Y}<br>%{y:.2f}" + unit + "<extra></extra>",
        )
    )
    fig = style_figure(fig, height=290)
    fig.update_layout(showlegend=False, margin=dict(t=8))
    fig.update_yaxes(ticksuffix=unit, rangemode="tozero", title_text="Annualised volatility")
    return fig


def return_distribution(returns: pd.Series, name: str, percentiles: tuple[float, float] = (0.01, 0.99)) -> go.Figure:
    scale, unit = factor_unit(name)
    fig = go.Figure(
        go.Histogram(
            x=returns * scale, nbinsx=60, marker_color=BLUE_RAMP[0], marker_line=dict(color=BG, width=1),
            hovertemplate="%{x}" + unit + "<br>%{y} days<extra></extra>",
        )
    )
    for p in percentiles:
        value = float(returns.quantile(p)) * scale
        _reference_line(fig, value, f"{p:.0%}: {value:+.2f}{unit}", TEXT_SECONDARY, "dash")
    fig = style_figure(fig, height=290)
    fig.update_layout(showlegend=False, bargap=0.04, barcornerradius=0)
    fig.update_xaxes(ticksuffix=unit, title_text="Daily move")
    fig.update_yaxes(title_text="Days")
    return fig
