"""Reusable UI components shared by every page.

Navigation item, page header, section header, KPI card, status badge, risk table,
metric row, chart container, warning / breach banner, empty state and risk
commentary box. Each component renders one HTML block styled by a single class in
``dashboard.theme.CSS``, so spacing and typography are identical on every page.
HTML is emitted on one line because Markdown treats blank or indented lines as text.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from html import escape
from urllib.parse import urlencode

import plotly.graph_objects as go
import streamlit as st

from ccr.formatting import CURRENCY_SYMBOLS
from dashboard.theme import BAD, GOOD, STATUS_COLOURS, WARN

# --------------------------------------------------------------------------- #
# Number formatting (one convention for cards, tables, charts and tooltips)
# --------------------------------------------------------------------------- #
DASH = "–"
HOME_PAGE = "overview"


def _missing(value: object) -> bool:
    return value is None or (isinstance(value, float) and math.isnan(value))


def money(value: float, currency: str = "INR", signed: bool = False) -> str:
    """₹1,250,000 -> '₹1.3M'; ₹1,250,000,000 -> '₹1.25B'."""
    if _missing(value):
        return DASH
    symbol = CURRENCY_SYMBOLS.get(currency, f"{currency} ")
    sign = "-" if value < 0 else ("+" if signed and value > 0 else "")
    magnitude = abs(value)
    if magnitude >= 1e9:
        return f"{sign}{symbol}{magnitude / 1e9:,.2f}B"
    return f"{sign}{symbol}{magnitude / 1e6:,.1f}M"


def pct(value: float, decimals: int = 1, signed: bool = False) -> str:
    """0.843 -> '84.3%'."""
    if _missing(value):
        return DASH
    return f"{value * 100:{'+' if signed else ''},.{decimals}f}%"


def ratio(value: float) -> str:
    """3.2 -> '3.20x'."""
    if _missing(value):
        return DASH
    return "n/m" if math.isinf(value) else f"{value:,.2f}x"


def score(value: float) -> str:
    return DASH if _missing(value) else f"{value:.0f}"


# --------------------------------------------------------------------------- #
# Context, links and navigation
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Context:
    """Run metadata shared by every page."""

    run_time: datetime
    data_time: str


def render(html: str) -> None:
    st.markdown(html, unsafe_allow_html=True)


def page_url(page: str, **params: str) -> str:
    """Relative URL of a dashboard page, carrying the selected valuation date."""
    query = dict(params)
    as_of = st.session_state.get("as_of_param")
    if as_of:
        query["asof"] = as_of
    path = "./" if page == HOME_PAGE else f"./{page}"
    return path + (f"?{urlencode(query)}" if query else "")


def counterparty_link(counterparty_id: str, label: str | None = None) -> str:
    url = page_url("counterparty", cp=counterparty_id)
    return f'<a href="{url}" target="_self">{escape(label or counterparty_id)}</a>'


def brand(title: str, subtitle: str) -> None:
    render(f'<div class="brand"><div class="b1">{escape(title)}</div><div class="b2">{escape(subtitle)}</div></div>')


def nav_item(page: st.navigation) -> None:  # type: ignore[valid-type]
    """One sidebar navigation row; Streamlit marks the current page as active."""
    st.page_link(page, width="stretch")


def side_label(text: str) -> None:
    render(f'<div class="side-label">{escape(text)}</div>')


def system_status(rows: list[tuple[str, str]]) -> None:
    body = "".join(
        f'<div><span class="k">{escape(key)}</span><span class="v">{escape(value)}</span></div>' for key, value in rows
    )
    render(f'<div class="sys"><div class="ok"><span class="dot"></span>Operational</div>{body}</div>')


# --------------------------------------------------------------------------- #
# Headers, notes, empty state
# --------------------------------------------------------------------------- #
def page_header(title: str, description: str, as_of: datetime, context: Context) -> None:
    render(
        f'<div class="ph"><div class="tt"><h1>{escape(title)}</h1><div class="d">{escape(description)}</div></div>'
        f'<div class="m"><span>As of <b>{as_of:%d %b %Y}</b></span> · '
        f"<span>Latest risk run <b>{context.run_time:%d %b %Y %H:%M}</b></span></div></div>"
    )


def section(title: str, subtitle: str | None = None) -> None:
    sub = f'<div class="s">{escape(subtitle)}</div>' if subtitle else ""
    render(f'<div class="sh"><div class="t">{escape(title)}</div>{sub}</div>')


def note(text: str) -> None:
    render(f'<div class="note">{escape(text)}</div>')


def empty_state(title: str, message: str) -> None:
    render(f'<div class="empty"><b>{escape(title)}</b>{escape(message)}</div>')


# --------------------------------------------------------------------------- #
# Chart container
# --------------------------------------------------------------------------- #
def _legend_items(fig: go.Figure) -> list[tuple[str, str, bool]]:
    """(label, colour, is_line) for every named trace that should appear in the legend."""
    if fig.layout.showlegend is False:
        return []
    items = []
    for trace in fig.data:
        if not trace.name or trace.showlegend is False:
            continue
        marker = getattr(trace, "marker", None)
        line = getattr(trace, "line", None)
        if trace.type == "scatter":
            is_line = True
            colour = (marker.line.color if marker is not None and "line" in str(marker.symbol) else None) or (
                line.color if line is not None else None
            )
        else:
            is_line = False
            colour = marker.color if marker is not None and isinstance(marker.color, str) else None
        if colour:
            items.append((trace.name, colour, is_line))
    return items if len(items) > 1 else []


def chart(fig: go.Figure, title: str, subtitle: str | None = None) -> None:
    """Chart container: title, optional subtitle, a wrapping HTML legend, then the figure."""
    legend = "".join(
        f'<span><i class="{"ln" if is_line else ""}" style="background:{colour}"></i>{escape(label)}</span>'
        for label, colour, is_line in _legend_items(fig)
    )
    fig.update_layout(showlegend=False)
    sub = f'<div class="s">{escape(subtitle)}</div>' if subtitle else ""
    render(f'<div class="ch"><div class="t">{escape(title)}</div>{sub}'
           + (f'<div class="lg">{legend}</div>' if legend else "") + "</div>")
    st.plotly_chart(fig, width="stretch", theme=None, config={"displayModeBar": False, "responsive": True})


# --------------------------------------------------------------------------- #
# KPI cards
# --------------------------------------------------------------------------- #
_ICON_PATHS = {
    "exposure": "M4 20V11M10 20V4M16 20v-7M2 20h20",
    "expected": "M3 17l6-6 4 4 8-8",
    "pfe": "M3 20h18M5 15l5-5 4 3 6-8M16 5h4v4",
    "margin": "M12 3l8 3v6c0 4.5-3.4 8-8 9-4.6-1-8-4.5-8-9V6l8-3z",
    "collateral": "M6 11h12v9H6zM8.5 11V8a3.5 3.5 0 0 1 7 0v3",
    "alert": "M12 4l9 16H3L12 4zM12 10v4M12 17v.5",
    "limit": "M4 18a8 8 0 1 1 16 0M12 18l4-6",
    "score": "M5 4h14v16H5zM9 9h6M9 13h6M9 17h3",
    "market": "M3 12h4l3-7 4 14 3-7h4",
}


def icon(name: str) -> str:
    path = _ICON_PATHS.get(name, "")
    return (
        '<svg viewBox="0 0 24 24" fill="none" stroke-width="1.6" stroke-linecap="round" '
        f'stroke-linejoin="round"><path d="{path}"/></svg>'
    )


@dataclass(frozen=True)
class Kpi:
    """One KPI card: label, large value, optional change indicator and secondary metric.

    ``tone`` is 'bad' / 'warn' / 'good' only for a meaningful risk state.
    """

    label: str
    value: str
    icon: str = ""
    secondary: str = ""
    trend: str = ""
    tone: str = ""


def trend_text(today: float, previous: float | None, currency: str = "INR", suffix: str = "vs prev") -> str:
    """Small change indicator, e.g. '▲ ₹2.6M vs prev'."""
    if previous is None:
        return ""
    change = today - previous
    if abs(change) < 50_000:
        return f"Unchanged {suffix}"
    arrow = "▲" if change > 0 else "▼"
    return f"{arrow} {money(abs(change), currency)} {suffix}"


def kpi_row(cards: list[Kpi]) -> None:
    """A row of equal-height KPI cards that wraps onto further rows when space runs out."""
    cells = []
    for card in cards:
        first = card.trend or card.secondary
        second = card.secondary if card.trend else ""
        first_class = "x" if card.trend else "y"
        cells.append(
            f'<div class="kpi {card.tone}"><div class="l">{icon(card.icon) if card.icon else ""}'
            f'<span>{escape(card.label)}</span></div><div class="v">{escape(card.value)}</div>'
            + (f'<div class="{first_class}">{escape(first)}</div>' if first else "")
            + (f'<div class="y">{escape(second)}</div>' if second else "")
            + "</div>"
        )
    render(f'<div class="kpis">{"".join(cells)}</div>')


# --------------------------------------------------------------------------- #
# Badges and cell helpers
# --------------------------------------------------------------------------- #
_TONES = {
    "Normal": "good", "Warning": "warn", "Breach": "bad",
    "Low": "good", "Moderate": "neutral", "Elevated": "warn", "High": "bad",
    "No transfer": "neutral", "Call": "warn", "Return": "neutral",
    "Info": "neutral",
}


def tone_of(label: str) -> str:
    return _TONES.get(label, "neutral")


def badge(label: str, large: bool = False) -> str:
    """Small status badge: NORMAL / WARNING / BREACH (and risk categories)."""
    return f'<span class="bdg {tone_of(label)}{" lg" if large else ""}">{escape(str(label))}</span>'


def tone_text(text: str, tone: str) -> str:
    """Coloured text for conditional formatting ('good', 'warn', 'bad' or '')."""
    css = {"good": "tg", "warn": "ta", "bad": "tb"}.get(tone)
    return f'<span class="{css}">{text}</span>' if css else text


def utilisation_cell(value: float, status: str) -> str:
    """Utilisation percentage with a small inline bar."""
    width = max(0.0, min(value, 1.0)) * 100
    colour = STATUS_COLOURS.get(status, GOOD)
    return f'<span class="ubar"><i style="width:{width:.0f}%;background:{colour}"></i></span>{pct(value)}'


def entity(counterparty_id: str, name: str) -> str:
    """Two-line counterparty cell: clickable ID above the (wrapping) legal name."""
    return f'<span class="ent">{counterparty_link(counterparty_id)}<small>{escape(name)}</small></span>'


# --------------------------------------------------------------------------- #
# Tables and rows
# --------------------------------------------------------------------------- #
def table(
    headers: list[tuple[str, str]], rows: list[list[str]], footer: list[str] | None = None,
    empty: str = "Nothing to show.",
) -> None:
    """Risk table. ``headers`` is ``[(label, align)]``; align is 'l', 'r', 'c' or 'w' (wrapping text).

    Cells are HTML. Text is left-aligned, numbers right-aligned, and the table
    scrolls horizontally inside its own frame rather than overflowing the page.
    """
    aligns = [align for _, align in headers]

    def cells(values: list[str], tag: str) -> str:
        return "".join(
            f'<{tag} class="{align if align != "l" else ""}">{value}</{tag}>'
            for value, align in zip(values, aligns)
        )

    head = cells([escape(label) for label, _ in headers], "th")
    body = "".join(f"<tr>{cells(row, 'td')}</tr>" for row in rows)
    if not rows:
        body = f'<tr><td colspan="{len(headers)}" class="dim">{escape(empty)}</td></tr>'
    foot = f"<tfoot><tr>{cells(footer, 'td')}</tr></tfoot>" if footer and rows else ""
    render(
        f'<div class="tw"><table class="rt"><thead><tr>{head}</tr></thead>'
        f"<tbody>{body}</tbody>{foot}</table></div>"
    )


def metric_rows(items: list[tuple[str, str]], total_last: bool = False) -> None:
    """Compact label / value list. Labels are plain text, values are HTML."""
    rows = []
    for index, (label, value) in enumerate(items):
        css = "row total" if total_last and index == len(items) - 1 else "row"
        rows.append(f'<div class="{css}"><span class="k">{escape(label)}</span><span class="v">{value}</span></div>')
    render(f'<div class="mr">{"".join(rows)}</div>')


def status_rows(items: list[tuple[str, int, str]]) -> None:
    """Rows of ``(status, count, detail_html)``, e.g. '● 1 Breach   CP003'."""
    rows = "".join(
        f'<div class="row"><span class="k"><span class="dot" style="background:{STATUS_COLOURS[status]}"></span>'
        f'<span class="cnt">{count}</span>{status}</span><span class="v">{detail}</span></div>'
        for status, count, detail in items
    )
    render(f'<div class="mr">{rows}</div>')


# --------------------------------------------------------------------------- #
# Banner and commentary
# --------------------------------------------------------------------------- #
def banner(severity: str, tone: str, message: str, heading: str = "", figure: str = "", caption: str = "") -> None:
    """Warning / breach banner. ``heading`` is HTML (e.g. a counterparty link); the rest is plain text."""
    who = f'<div class="who">{heading}</div>' if heading else ""
    fig = f'<div class="fig">{escape(figure)}<small>{escape(caption)}</small></div>' if figure else "<div></div>"
    render(
        f'<div class="bn {tone}"><div class="sev">{escape(severity)}</div>'
        f'<div class="body">{who}{escape(message)}</div>{fig}</div>'
    )


def commentary(blocks: list[tuple[str, str]]) -> None:
    """Risk commentary box: ``[(heading, body_html)]`` rendered as a report."""
    body = "".join(f"<h4>{escape(heading)}</h4>{html}" for heading, html in blocks)
    render(f'<div class="rep">{body}</div>')


def paragraphs(texts: list[str]) -> str:
    return "".join(f"<p>{escape(text)}</p>" for text in texts)


def bullets(texts: list[str]) -> str:
    return "<ul>" + "".join(f"<li>{escape(text)}</li>" for text in texts) + "</ul>"


# --------------------------------------------------------------------------- #
# Counterparty header and limit utilisation
# --------------------------------------------------------------------------- #
def counterparty_header(row: dict[str, object]) -> None:
    render(
        f'<div class="cph"><div class="who"><div class="id">{escape(str(row["counterparty_id"]))}</div>'
        f'<div class="nm">{escape(str(row["name"]))}</div><div class="meta">'
        f'<span>Sector<b>{escape(str(row["sector"]))}</b></span>'
        f'<span>Country<b>{escape(str(row["country"]))}</b></span>'
        f'<span>External rating<b>{escape(str(row["credit_rating"]))}</b></span>'
        f'<span>Trades<b>{int(row["trade_count"])}</b></span></div></div>'
        f'<div class="st">Limit status<br>{badge(str(row["status"]), large=True)}</div></div>'
    )


def limit_utilisation(
    credit_limit: float, measure_label: str, measure_value: float, utilisation: float,
    warning_threshold: float, breach_threshold: float, status: str, headroom: float, currency: str,
) -> None:
    """Limit block with a horizontal utilisation bar marked at 0%, warning, limit and current."""
    scale = max(1.25, utilisation * 1.1)
    colour = {"Normal": GOOD, "Warning": WARN, "Breach": BAD}[status]

    def pos(value: float) -> float:
        return min(value / scale, 1.0) * 100

    marks = [(0.0, "0%"), (warning_threshold, f"{warning_threshold:.0%}"), (breach_threshold, f"{breach_threshold:.0%}")]
    ticks = "".join(f'<div class="tick" style="left:{pos(value):.2f}%"></div>' for value, _ in marks)
    labels = "".join(f'<span style="left:{pos(value):.2f}%">{label}</span>' for value, label in marks)
    headroom_text = (
        f"{money(headroom, currency)} headroom" if headroom >= 0 else f"{money(-headroom, currency)} over limit"
    )
    render(
        f'<div class="lim"><div class="top">'
        f'<div class="blk"><div class="k">Credit limit</div><div class="v">{money(credit_limit, currency)}</div></div>'
        f'<div class="blk"><div class="k">{escape(measure_label)}</div><div class="v">{money(measure_value, currency)}</div></div>'
        f'<div class="blk"><div class="k">Utilised</div><div class="v" style="color:{colour}">{pct(utilisation)}</div></div>'
        f'<div class="right"><div class="hd">{escape(headroom_text)}</div>{badge(status, large=True)}</div></div>'
        f'<div class="track"><div class="fill" style="width:{pos(utilisation):.2f}%;background:{colour}"></div>{ticks}'
        f'<div class="now" style="left:{pos(utilisation):.2f}%"></div></div>'
        f'<div class="scale">{labels}</div>'
        f'<div class="key"><span>Warning at <b>{warning_threshold:.0%}</b></span>'
        f"<span>Limit at <b>{breach_threshold:.0%}</b></span>"
        f"<span>Current utilisation <b>{pct(utilisation)}</b> (white marker)</span></div></div>"
    )
