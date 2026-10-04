"""Dashboard pages. Each ``render_*`` function draws one page from a ``RiskResults`` object.

Pages only present numbers: every figure comes from ``ccr`` result frames.
"""

from __future__ import annotations

from datetime import datetime
from html import escape

import pandas as pd
import streamlit as st

from ccr import database, market_data, reporting
from ccr.credit_analysis import METRIC_LABELS, score_breakdown
from ccr.exposure import pfe_column
from ccr.limits import STATUS_BREACH, STATUS_NORMAL, STATUS_ORDER, STATUS_WARNING
from ccr.margin import confidence_multiplier
from ccr.market_data import RISK_FACTORS
from ccr.pipeline import RiskResults
from dashboard import charts
from dashboard import components as ui
from dashboard.components import Context, Kpi, money, pct, ratio, score
from dashboard.theme import BLUE_RAMP, NEUTRAL, TEXT_SECONDARY

L, R, C = "l", "r", "c"


# --------------------------------------------------------------------------- #
# Shared helpers
# --------------------------------------------------------------------------- #
def _pfe_columns(results: RiskResults) -> dict[str, str]:
    """Label -> column for the configured PFE levels, lowest first."""
    return {f"PFE {lvl:.0%}": pfe_column(lvl) for lvl in sorted(results.config.exposure.pfe_confidence_levels)}


def _top_pfe(results: RiskResults) -> tuple[str, str]:
    """(label, column) of the highest configured PFE level - the one limits are monitored on."""
    return list(_pfe_columns(results).items())[-1]


def _previous_value(results: RiskResults, frame_name: str, counterparty_id: str, column: str) -> float | None:
    if results.previous is None:
        return None
    frame = getattr(results.previous, frame_name)
    row = frame.loc[frame["counterparty_id"] == counterparty_id, column]
    return float(row.iloc[0]) if len(row) else None


def _status_counts(limits: pd.DataFrame) -> dict[str, list[str]]:
    return {status: limits.loc[limits["status"] == status, "counterparty_id"].tolist() for status in STATUS_ORDER}


def _ratio_tone(points: float) -> str:
    """Conditional-formatting tone from a ratio's risk points (0 = strong, 100 = weak)."""
    if points < 25:
        return "good"
    if points >= 85:
        return "bad"
    if points >= 60:
        return "warn"
    return ""


def _ratio_cells(row: pd.Series) -> dict[str, str]:
    formatters = {
        "debt_to_ebitda": ratio, "current_ratio": ratio,
        "net_margin": pct, "debt_to_assets": pct, "revenue_growth": lambda v: pct(v, signed=True),
    }
    return {
        metric: ui.tone_text(formatters[metric](row[metric]), _ratio_tone(row[f"{metric}_points"]))
        for metric in METRIC_LABELS
    }


def _attention(results: RiskResults, limits: pd.DataFrame) -> None:
    """Breach and warning rows; the first thing an analyst should read."""
    ccy = results.config.base_currency
    flagged = limits[limits["status"] != STATUS_NORMAL]
    if flagged.empty:
        ui.banner("CLEAR", "good", "All counterparties are within their approved credit limits.")
        return
    for row in flagged.itertuples():
        heading = f"{ui.counterparty_link(row.counterparty_id)}<small>{escape(row.name)}</small>"
        measure = "PFE" if row.driver == "PFE" else "Net exposure"
        if row.status == STATUS_BREACH:
            message = f"{measure} exceeds the {money(row.credit_limit, ccy)} credit limit by {money(-row.headroom, ccy)}"
            ui.banner("CRITICAL", "bad", message, heading, pct(row.utilisation), "utilisation")
        else:
            message = (
                f"{measure} utilisation is above the {row.warning_threshold:.0%} warning threshold; "
                f"{money(row.headroom, ccy)} remaining headroom"
            )
            ui.banner("WARNING", "warn", message, heading, pct(row.utilisation), "utilisation")


# --------------------------------------------------------------------------- #
# Overview
# --------------------------------------------------------------------------- #
def render_overview(results: RiskResults, context: Context) -> None:
    today, previous, ccy = results.today, results.previous, results.config.base_currency
    portfolio = today.portfolio
    before = previous.portfolio if previous else {}
    pfe_label, pfe_col = _top_pfe(results)
    counts = _status_counts(today.limits)
    breaches, warnings = len(counts[STATUS_BREACH]), len(counts[STATUS_WARNING])

    ui.page_header("Portfolio Risk Overview", "Portfolio-wide credit exposure and counterparty health",
                   today.as_of, context)

    previous_breaches = previous.breach_count if previous else None
    breach_trend = ""
    if previous_breaches is not None:
        change = breaches - previous_breaches
        breach_trend = "unchanged vs prev" if change == 0 else f"{'▲' if change > 0 else '▼'} {abs(change)} vs prev"
    ui.kpi_row([
        Kpi("Total Exposure", money(portfolio["current_exposure"], ccy), "exposure",
            f"Gross {money(portfolio['gross_exposure'], ccy)}",
            ui.trend_text(portfolio["current_exposure"], before.get("current_exposure"), ccy)),
        Kpi("Expected Exposure", money(portfolio["expected_exposure"], ccy), "expected",
            f"{len(today.scenarios)} scenarios",
            ui.trend_text(portfolio["expected_exposure"], before.get("expected_exposure"), ccy)),
        Kpi(pfe_label, money(portfolio[pfe_col], ccy), "pfe",
            f"Sum of cpties {money(portfolio[f'{pfe_col}_sum_of_counterparties'], ccy)}",
            ui.trend_text(portfolio[pfe_col], before.get(pfe_col), ccy)),
        Kpi("Initial Margin", money(today.total_initial_margin, ccy), "margin",
            f"{results.config.initial_margin.confidence_level:.0%} · {results.config.initial_margin.margin_period_days}d MPOR",
            ui.trend_text(today.total_initial_margin, previous.total_initial_margin if previous else None, ccy)),
        Kpi("Collateral", money(portfolio["collateral"], ccy), "collateral",
            f"Net exposure {money(portfolio['net_exposure'], ccy)}"),
        Kpi("Limit Breaches", str(breaches), "alert",
            f"{warnings} warning{'s' if warnings != 1 else ''}", breach_trend,
            tone="bad" if breaches else ("warn" if warnings else "good")),
    ])

    view = results.consolidated.sort_values("counterparty_id")
    left, right = st.columns([2.25, 1], gap="large")
    with left:
        ui.section("Exposure Profile")
        ui.chart(
            charts.exposure_profile(view, _pfe_columns(results)),
            "Current exposure, EE and PFE by counterparty",
            f"{results.config.exposure.scenario_horizon_days}-day historical scenarios · horizontal marker = approved credit limit",
        )
    with right:
        ui.section("Risk Status")
        ui.status_rows([
            (status, len(counts[status]),
             ", ".join(ui.counterparty_link(cp) for cp in counts[status]) or ui.DASH)
            for status in (STATUS_NORMAL, STATUS_WARNING, STATUS_BREACH)
        ])
        ui.section("Since Previous Run")
        if previous is None:
            ui.note("No previous risk run is available for comparison.")
        else:
            requirement = float(today.collateral["collateral_requirement"].sum())
            requirement_before = float(previous.collateral["collateral_requirement"].sum())
            rows = [
                ("Current exposure", money(portfolio["current_exposure"] - before["current_exposure"], ccy, signed=True)),
                (pfe_label, money(portfolio[pfe_col] - before[pfe_col], ccy, signed=True)),
                ("Initial Margin", money(today.total_initial_margin - previous.total_initial_margin, ccy, signed=True)),
                ("Collateral requirement", money(requirement - requirement_before, ccy, signed=True)),
            ]
            increase = results.highlights.get("largest_exposure_increase")
            if increase and increase["value"] > 0:
                rows.append((
                    "Largest exposure increase",
                    f'{ui.counterparty_link(str(increase["counterparty_id"]))} {money(float(increase["value"]), ccy, signed=True)}',
                ))
            ui.metric_rows(rows)

    ui.section("Requiring Attention")
    _attention(results, today.limits)

    head, sorter = st.columns([3, 1], vertical_alignment="bottom", gap="medium")
    with head:
        ui.section("Counterparty Risk", "Select a counterparty to open its risk profile. Risk score: 0 = lowest risk, 100 = highest.")
    sort_options = {
        "Highest utilisation": "utilisation", f"Highest {pfe_label}": pfe_col,
        "Largest exposure": "current_exposure", "Highest risk score": "credit_score",
        "Largest Initial Margin": "initial_margin",
    }
    with sorter:
        sort_by = st.selectbox("Sort by", list(sort_options), key="overview_sort")
    ordered = results.consolidated.sort_values(sort_options[sort_by], ascending=False)
    ui.table(
        [("Counterparty", L), ("Rating", C), ("Risk score", R), ("Exposure", R), ("EE", R),
         (pfe_label, R), ("Limit", R), ("Utilisation", R), ("IM", R), ("Status", L)],
        [
            [
                ui.entity(row.counterparty_id, f"{row.name} · {row.sector}"),
                escape(row.credit_rating),
                ui.tone_text(score(row.credit_score), {"High": "bad", "Elevated": "warn"}.get(row.risk_category, "")),
                money(row.current_exposure, ccy), money(row.expected_exposure, ccy),
                money(getattr(row, pfe_col), ccy), money(row.credit_limit, ccy),
                ui.utilisation_cell(row.utilisation, row.status), money(row.initial_margin, ccy),
                ui.badge(row.status),
            ]
            for row in ordered.itertuples()
        ],
        footer=[
            "Portfolio", "", "", money(portfolio["current_exposure"], ccy),
            money(ordered["expected_exposure"].sum(), ccy), money(ordered[pfe_col].sum(), ccy),
            money(ordered["credit_limit"].sum(), ccy), "", money(today.total_initial_margin, ccy), "",
        ],
    )
    ui.note(
        f"Footer EE and {pfe_label} are sums of the counterparty figures. Portfolio EE and {pfe_label} in the cards "
        "come from the portfolio scenario distribution, so they reflect that counterparties do not peak together."
    )


# --------------------------------------------------------------------------- #
# Counterparty risk profile
# --------------------------------------------------------------------------- #
def render_counterparty(results: RiskResults, context: Context) -> None:
    today, ccy, config = results.today, results.config.base_currency, results.config
    view = results.consolidated.set_index("counterparty_id")
    ids = view.index.tolist()
    names = view["name"].to_dict()

    ui.page_header("Counterparty Risk", "Credit profile, exposure, collateral and limit position of a single counterparty",
                   today.as_of, context)

    # The selection follows a ?cp= link once, then belongs to the selectbox.
    requested = st.query_params.get("cp")
    if requested in ids and st.session_state.get("cp_synced") != requested:
        st.session_state["cp_select"] = requested
    if st.session_state.get("cp_select") not in ids:
        st.session_state["cp_select"] = str(today.limits.iloc[0]["counterparty_id"])
    picker, _ = st.columns([2, 3])
    with picker:
        cp = st.selectbox("Counterparty", ids, key="cp_select", format_func=lambda c: f"{c} · {names[c]}")
    st.query_params["cp"] = cp
    st.session_state["cp_synced"] = cp

    row = view.loc[cp]
    limit = today.limits.set_index("counterparty_id").loc[cp]
    collateral = today.collateral.set_index("counterparty_id").loc[cp]
    financials = results.financials.set_index("counterparty_id").loc[cp]
    pfe_columns = _pfe_columns(results)
    pfe_label, pfe_col = _top_pfe(results)

    ui.counterparty_header({**row.to_dict(), "counterparty_id": cp})

    # 1. Credit profile -------------------------------------------------------
    ui.section("1 · Credit Profile", "Internal analytical score: 0 = lowest risk, 100 = highest. Not an agency rating.")
    cells = _ratio_cells(row)
    left, right = st.columns(2, gap="large")
    with left:
        ui.metric_rows([
            ("Internal risk score", f'{score(row["credit_score"])} / 100'),
            ("Risk classification", ui.badge(row["risk_category"])),
            ("External rating", escape(row["credit_rating"])),
            ("Sector", escape(row["sector"])),
            (f"Revenue ({financials['fiscal_year']})", money(financials["revenue"], ccy)),
            ("EBITDA", money(financials["ebitda"], ccy)),
        ])
    with right:
        ui.metric_rows([(METRIC_LABELS[metric], cells[metric]) for metric in METRIC_LABELS]
                       + [("Net income", money(financials["net_income"], ccy))])

    # 2. Exposure profile -----------------------------------------------------
    ui.section("2 · Exposure Profile")
    cards = [
        Kpi("Current Exposure", money(row["current_exposure"], ccy), "exposure",
            f"Net MTM {money(row['net_mtm'], ccy)}",
            ui.trend_text(row["current_exposure"], _previous_value(results, "exposure", cp, "current_exposure"), ccy)),
        Kpi("EE", money(row["expected_exposure"], ccy), "expected", "Mean scenario exposure",
            ui.trend_text(row["expected_exposure"], _previous_value(results, "exposure", cp, "expected_exposure"), ccy)),
    ]
    for label, column in pfe_columns.items():
        cards.append(Kpi(label, money(row[column], ccy), "pfe", "",
                         ui.trend_text(row[column], _previous_value(results, "exposure", cp, column), ccy)))
    cards.append(Kpi("Net Exposure", money(row["net_exposure"], ccy), "collateral", "After collateral"))
    ui.kpi_row(cards)

    distribution = today.exposure_distribution[cp]
    markers = [("Mean (EE)", float(row["expected_exposure"]), TEXT_SECONDARY, "dot")]
    markers += [(label, float(row[column]), colour, "solid")
                for (label, column), colour in zip(pfe_columns.items(), BLUE_RAMP[1:])]
    markers.append(("Limit", float(row["credit_limit"]), NEUTRAL, "dash"))
    worst = distribution.idxmax()
    ui.chart(
        charts.exposure_distribution(distribution, markers),
        "Exposure distribution",
        f"{len(distribution)} historical {config.exposure.scenario_horizon_days}-day scenarios applied to today's trades · "
        f"worst scenario {money(float(distribution.max()), ccy)} (move ending {worst:%d %b %Y})",
    )

    # 3. Collateral & margin --------------------------------------------------
    ui.section("3 · Collateral & Margin")
    transfer = float(collateral["transfer_amount"])
    action = str(collateral["action"])
    action_text = ui.badge(action) + (f" &nbsp;{money(abs(transfer), ccy)}" if transfer else "")
    left, right = st.columns([1, 1.25], gap="large")
    with left:
        ui.metric_rows([
            ("Gross exposure", money(collateral["gross_exposure"], ccy)),
            ("Collateral held", money(collateral["collateral_held"], ccy)),
            ("Net exposure", money(collateral["net_exposure"], ccy)),
            ("Initial Margin", money(row["initial_margin"], ccy)),
            ("Collateral requirement", money(collateral["collateral_requirement"], ccy)),
            ("Threshold / MTA",
             f'{money(collateral["collateral_threshold"], ccy)} / {money(collateral["minimum_transfer_amount"], ccy)}'),
            ("Collateral action", action_text),
        ])
    with right:
        gross, net = float(collateral["gross_exposure"]), float(collateral["net_exposure"])
        ui.chart(charts.collateral_waterfall(gross, gross - net, net), "Gross exposure − collateral = net exposure",
                 "Collateral is applied up to the gross exposure; net exposure is floored at zero")

    # 4. Credit limit ---------------------------------------------------------
    ui.section("4 · Credit Limit", f"Limit is monitored on the larger of net exposure and {pfe_label}.")
    measure_label = pfe_label if limit["driver"] == "PFE" else "Net exposure"
    measure_value = float(limit["pfe"]) if limit["driver"] == "PFE" else float(limit["net_exposure"])
    ui.limit_utilisation(
        float(limit["credit_limit"]), measure_label, measure_value, float(limit["utilisation"]),
        float(limit["warning_threshold"]), config.limits.breach_threshold, str(limit["status"]),
        float(limit["headroom"]), ccy,
    )
    ui.metric_rows([
        ("Exposure utilisation (net exposure / limit)", pct(limit["exposure_utilisation"])),
        (f"PFE utilisation ({pfe_label} / limit)", pct(limit["pfe_utilisation"])),
    ])

    # Detail ------------------------------------------------------------------
    ui.section("Detail", "Trade list and score derivation")
    with st.expander(f"Trades ({int(row['trade_count'])})"):
        trades = today.trades[today.trades["counterparty_id"] == cp].merge(
            today.margin_trades[["trade_id", "initial_margin"]], on="trade_id")
        ui.table(
            [("Trade", L), ("Product", L), ("Underlying", L), ("Notional", R), ("Maturity", L),
             ("MTM", R), ("Sensitivity", R), ("Volatility", R), ("IM", R)],
            [[t.trade_id, escape(t.product_type), f'<span class="dim">{escape(t.underlying)}</span>',
              f"{t.currency} {t.notional / 1e6:,.1f}M", str(t.maturity)[:10], money(t.current_mtm, ccy),
              f"{t.sensitivity:+.2f}", pct(t.volatility), money(t.initial_margin, ccy)]
             for t in trades.itertuples()],
        )
    with st.expander("Credit score breakdown"):
        breakdown = score_breakdown(results.credit, cp, config.credit_score)
        ui.table(
            [("Metric", L), ("Value", R), ("Best (0 pts)", R), ("Worst (100 pts)", R), ("Risk points", R),
             ("Weight", R), ("Contribution", R)],
            [[escape(str(b[0])), f"{b[1]:,.2f}", f"{b[2]:,.2f}", f"{b[3]:,.2f}", f"{b[4]:.1f}", pct(b[5], 0), f"{b[6]:.1f}"]
             for b in breakdown.itertuples(index=False)],
            footer=["Internal risk score", "", "", "", "", "", f'{row["credit_score"]:.1f}'],
        )

    # 5. Commentary -----------------------------------------------------------
    ui.section("5 · Risk Commentary")
    notes = [item.text for item in results.commentary if item.scope == cp]
    if notes:
        ui.commentary([(f"{cp} · {today.as_of:%d %b %Y}", ui.paragraphs(notes))])
    else:
        ui.empty_state("No commentary", "Nothing material to report for this counterparty today.")


# --------------------------------------------------------------------------- #
# Exposure analysis
# --------------------------------------------------------------------------- #
def render_exposure(results: RiskResults, context: Context) -> None:
    today, ccy, config = results.today, results.config.base_currency, results.config
    pfe_columns = _pfe_columns(results)
    pfe_label, pfe_col = _top_pfe(results)
    names = results.counterparties.set_index("counterparty_id")["name"].to_dict()

    ui.page_header("Exposure Analysis", "Scenario exposure distribution, EE and PFE for the portfolio and each counterparty",
                   today.as_of, context)

    picker, _ = st.columns([2, 5])
    with picker:
        scope = st.selectbox("Scope", ["Portfolio", *today.exposure_distribution.columns],
                             format_func=lambda c: c if c == "Portfolio" else f"{c} · {names[c]}")
    if scope == "Portfolio":
        distribution = today.exposure_distribution.sum(axis=1)
        figures = {"expected_exposure": today.portfolio["expected_exposure"],
                   **{column: today.portfolio[column] for column in pfe_columns.values()}}
        extra = Kpi("Diversification", money(today.portfolio[f"{pfe_col}_sum_of_counterparties"] - today.portfolio[pfe_col], ccy),
                    "limit", f"Sum of cpty {pfe_label} less portfolio")
    else:
        distribution = today.exposure_distribution[scope]
        row = today.exposure.set_index("counterparty_id").loc[scope]
        figures = {"expected_exposure": float(row["expected_exposure"]),
                   **{column: float(row[column]) for column in pfe_columns.values()}}
        extra = Kpi("Current Exposure", money(float(row["current_exposure"]), ccy), "exposure",
                    f"Gross {money(float(row['gross_exposure']), ccy)}")

    worst = distribution.idxmax()
    ui.kpi_row([
        Kpi("Expected Exposure", money(figures["expected_exposure"], ccy), "expected", "Mean of scenario exposures"),
        *[Kpi(label, money(figures[column], ccy), "pfe", f"{label[4:]} percentile") for label, column in pfe_columns.items()],
        Kpi("Worst Scenario", money(float(distribution.max()), ccy), "alert", f"Move ending {worst:%d %b %Y}"),
        extra,
    ])

    markers = [("Mean (EE)", figures["expected_exposure"], TEXT_SECONDARY, "dot")]
    markers += [(label, figures[column], colour, "solid")
                for (label, column), colour in zip(pfe_columns.items(), BLUE_RAMP[1:])]
    left, right = st.columns(2, gap="large")
    with left:
        ui.section("Exposure Distribution")
        ui.chart(charts.exposure_distribution(distribution, markers), f"{scope}: distribution of scenario exposure",
                 f"{len(distribution)} scenarios · {config.exposure.scenario_horizon_days}-day moves · {config.exposure.aggregation} aggregation")
    with right:
        ui.section("Exposure by Scenario")
        ui.chart(
            charts.exposure_by_scenario(distribution, [(pfe_label, figures[pfe_col], TEXT_SECONDARY)]),
            f"{scope}: exposure under each historical market move",
            "Each point applies one observed market move to today's trades",
        )

    trade_exposure = today.scenario_mtm.clip(lower=0.0)
    trades = today.trades.set_index("trade_id")
    per_trade = pd.DataFrame({
        "counterparty_id": trades["counterparty_id"], "product_type": trades["product_type"],
        "underlying": trades["underlying"], "current_mtm": trades["current_mtm"],
        "gross_exposure": trades["current_mtm"].clip(lower=0.0),
        "expected_exposure": trade_exposure.mean(), pfe_col: trade_exposure.quantile(max(config.exposure.pfe_confidence_levels)),
    })
    if scope != "Portfolio":
        per_trade = per_trade[per_trade["counterparty_id"] == scope]

    left, right = st.columns(2, gap="large")
    with left:
        ui.section("Exposure by Product")
        by_product = per_trade.groupby("product_type")[["gross_exposure", "expected_exposure"]].sum().reset_index()
        ui.chart(charts.product_exposure(by_product), f"{scope}: gross current exposure and EE by product",
                 "Sum of trade-level positive exposures (no netting across trades)")
    with right:
        ui.section("Worst Scenarios")
        top = distribution.nlargest(8)
        shocks = today.scenarios.loc[top.index]

        def shock(name: str, value: float) -> str:
            scale, unit = charts.factor_unit(name)
            return f"{value * scale:+.2f}{unit}" if unit == "%" else f"{value * scale:+.0f}{unit}"

        ui.table(
            [("Move ending", L), ("Exposure", R), *[(RISK_FACTORS[name].label.split(" (")[0], R) for name in shocks.columns]],
            [[f"{date:%d %b %Y}", money(float(value), ccy), *[shock(name, shocks.at[date, name]) for name in shocks.columns]]
             for date, value in top.items()],
        )

    ui.section("Trade-Level Exposure", "EE and PFE of each trade on a stand-alone basis. Click a column header to sort.")
    display = per_trade.reset_index().rename(columns={"index": "trade_id"})
    for column in ("current_mtm", "gross_exposure", "expected_exposure", pfe_col):
        display[column] = display[column] / 1e6
    st.dataframe(
        display, hide_index=True, width="stretch", height=min(38 * len(display) + 40, 420),
        column_config={
            "trade_id": "Trade", "counterparty_id": "Counterparty", "product_type": "Product", "underlying": "Underlying",
            "current_mtm": st.column_config.NumberColumn("MTM (₹M)", format="%.1f"),
            "gross_exposure": st.column_config.NumberColumn("Exposure (₹M)", format="%.1f"),
            "expected_exposure": st.column_config.NumberColumn("EE (₹M)", format="%.1f"),
            pfe_col: st.column_config.NumberColumn(f"{pfe_label} (₹M)", format="%.1f"),
        },
    )


# --------------------------------------------------------------------------- #
# Limit monitoring
# --------------------------------------------------------------------------- #
def render_limits(results: RiskResults, context: Context) -> None:
    today, ccy = results.today, results.config.base_currency
    pfe_label, _ = _top_pfe(results)
    limits = today.limits.merge(results.counterparties[["counterparty_id", "credit_rating"]], on="counterparty_id")
    counts = _status_counts(limits)
    top = limits.loc[limits["utilisation"].idxmax()]

    ui.page_header("Limit Monitoring", "Monitor counterparties approaching or exceeding approved credit limits",
                   today.as_of, context)
    ui.kpi_row([
        Kpi("Total Limits", money(limits["credit_limit"].sum(), ccy), "limit", f"{len(limits)} counterparties"),
        Kpi("Warning", str(len(counts[STATUS_WARNING])), "alert", ", ".join(counts[STATUS_WARNING]) or "None",
            tone="warn" if counts[STATUS_WARNING] else ""),
        Kpi("Breaches", str(len(counts[STATUS_BREACH])), "alert", ", ".join(counts[STATUS_BREACH]) or "None",
            tone="bad" if counts[STATUS_BREACH] else "good"),
        Kpi("Highest Utilisation", pct(top["utilisation"]), "pfe", f"{top['counterparty_id']} · driven by {top['driver']}",
            tone={"Breach": "bad", "Warning": "warn"}.get(top["status"], "")),
    ])

    ui.section("Breaches Requiring Attention")
    _attention(results, limits)

    ui.section("All Limits", f"Utilisation = max(net exposure, {pfe_label}) / credit limit")
    f1, f2, f3, f4, f5 = st.columns(5, gap="small")
    statuses = f1.multiselect("Status", [STATUS_BREACH, STATUS_WARNING, STATUS_NORMAL], placeholder="All")
    sectors = f2.multiselect("Sector", sorted(limits["sector"].unique()), placeholder="All")
    ratings = f3.multiselect("Rating", sorted(limits["credit_rating"].unique()), placeholder="All")
    selected = f4.multiselect("Counterparty", limits["counterparty_id"].tolist(), placeholder="All")
    sort_options = {"Highest utilisation": "utilisation", f"Highest {pfe_label}": "pfe", "Largest exposure": "current_exposure"}
    sort_by = f5.selectbox("Sort by", list(sort_options))

    shown = limits
    for column, chosen in (("status", statuses), ("sector", sectors), ("credit_rating", ratings), ("counterparty_id", selected)):
        if chosen:
            shown = shown[shown[column].isin(chosen)]
    shown = shown.sort_values(sort_options[sort_by], ascending=False)

    ui.table(
        [("Counterparty", L), ("Rating", C), ("Limit", R), ("Exposure", R), ("Net exposure", R),
         (pfe_label, R), ("Utilisation", R), ("Headroom", R), ("Status", L)],
        [
            [
                ui.entity(row.counterparty_id, f"{row.name} · {row.sector}"), escape(row.credit_rating),
                money(row.credit_limit, ccy), money(row.current_exposure, ccy), money(row.net_exposure, ccy),
                money(row.pfe, ccy), ui.utilisation_cell(row.utilisation, row.status),
                ui.tone_text(money(row.headroom, ccy), "bad" if row.headroom < 0 else ""), ui.badge(row.status),
            ]
            for row in shown.itertuples()
        ],
        empty="No counterparties match the selected filters.",
    )
    if len(shown):
        ui.chart(charts.limit_utilisation(shown, results.config.limits.breach_threshold),
                 "Credit limit utilisation", "Bars are labelled with utilisation and status; dashed line = approved limit")

    highlights = results.highlights
    ui.section("Key Risk Indicators")
    rows = [
        ("Largest current exposure", f'{ui.counterparty_link(str(highlights["largest_exposure"]["counterparty_id"]))} &nbsp;{money(float(highlights["largest_exposure"]["value"]), ccy)}'),
        (f"Highest {pfe_label}", f'{ui.counterparty_link(str(highlights["highest_pfe"]["counterparty_id"]))} &nbsp;{money(float(highlights["highest_pfe"]["value"]), ccy)}'),
        ("Highest utilisation", f'{ui.counterparty_link(str(highlights["highest_utilisation"]["counterparty_id"]))} &nbsp;{pct(float(highlights["highest_utilisation"]["value"]))}'),
    ]
    increase = highlights.get("largest_exposure_increase")
    if increase:
        rows.append(("Largest increase in exposure vs previous run",
                     f'{ui.counterparty_link(str(increase["counterparty_id"]))} &nbsp;{money(float(increase["value"]), ccy, signed=True)}'))
    ui.metric_rows(rows)


# --------------------------------------------------------------------------- #
# Credit analysis
# --------------------------------------------------------------------------- #
def render_credit(results: RiskResults, context: Context) -> None:
    today, ccy, config = results.today, results.config.base_currency, results.config.credit_score
    credit = results.consolidated

    ui.page_header("Credit Analysis", "Counterparty financial strength and internal credit risk scores", today.as_of, context)

    picker, _ = st.columns([2, 5])
    sectors = picker.multiselect("Sector", sorted(credit["sector"].unique()), placeholder="All sectors")
    if sectors:
        credit = credit[credit["sector"].isin(sectors)]
    if credit.empty:
        ui.empty_state("No counterparties", "No counterparties in the selected sectors.")
        return

    ui.section("Counterparty Credit Overview", "Internal analytical score: 0 = lowest risk, 100 = highest. Not an agency rating.")
    elevated = credit[credit["risk_category"].isin(["Elevated", "High"])]
    weakest = credit.loc[credit["current_ratio"].idxmin()]
    ui.kpi_row([
        Kpi("Average Risk Score", f"{credit['credit_score'].mean():.0f}", "score", f"{len(credit)} counterparties"),
        Kpi("High Risk Counterparties", str(len(elevated)), "alert",
            ", ".join(elevated["counterparty_id"]) or "None", tone="bad" if len(elevated) else "good"),
        Kpi("Average Debt / EBITDA", ratio(credit["debt_to_ebitda"].mean()), "exposure",
            f"Max {ratio(credit['debt_to_ebitda'].max())}"),
        Kpi("Weakest Liquidity", ratio(weakest["current_ratio"]), "collateral",
            f"{weakest['counterparty_id']} current ratio", tone="warn" if weakest["current_ratio"] < 1 else ""),
    ])

    ui.section("Credit Score Comparison")
    ui.chart(charts.score_comparison(credit), "Internal credit risk score by counterparty",
             f"Low ≤ {config.categories['low']:.0f} · Moderate ≤ {config.categories['moderate']:.0f} · "
             f"Elevated ≤ {config.categories['elevated']:.0f} · High above")

    ui.section("Financial Ratio Analysis", "Green = strong, amber = weak, red = very weak relative to the scoring bounds.")
    ordered = credit.sort_values("credit_score", ascending=False)
    rows = []
    for _, row in ordered.iterrows():
        cells = _ratio_cells(row)
        rows.append([
            ui.entity(row["counterparty_id"], f'{row["name"]} · {row["sector"]}'), escape(row["credit_rating"]),
            *[cells[metric] for metric in METRIC_LABELS], score(row["credit_score"]), ui.badge(row["risk_category"]),
        ])
    ui.table(
        [("Counterparty", L), ("Rating", C), *[(METRIC_LABELS[m], R) for m in METRIC_LABELS],
         ("Risk score", R), ("Risk category", L)],
        rows,
    )

    ui.section("Financials")
    fin = results.financials.merge(ordered[["counterparty_id"]], on="counterparty_id")
    ui.table(
        [("Counterparty", L), ("Fiscal year", L), ("Revenue", R), ("EBITDA", R), ("Net income", R),
         ("Total assets", R), ("Total debt", R), ("Cash", R)],
        [[ui.counterparty_link(f.counterparty_id), str(f.fiscal_year), money(f.revenue, ccy), money(f.ebitda, ccy),
          ui.tone_text(money(f.net_income, ccy), "bad" if f.net_income < 0 else ""), money(f.total_assets, ccy),
          money(f.total_debt, ccy), money(f.cash, ccy)] for f in fin.itertuples()],
    )

    with st.expander("Scoring methodology"):
        total = sum(config.weights.values())
        ui.table(
            [("Metric", L), ("Weight", R), ("Best (0 risk points)", R), ("Worst (100 risk points)", R)],
            [[METRIC_LABELS[m], pct(config.weights[m] / total, 0), f"{config.bounds[m].best:,.2f}",
              f"{config.bounds[m].worst:,.2f}"] for m in METRIC_LABELS],
        )
        ui.note("Each ratio is mapped linearly between its best and worst bound (clipped to 0–100 risk points); "
                "the score is the weighted sum. Weights, bounds and category cut-offs are set in config/config.toml.")


# --------------------------------------------------------------------------- #
# Margin & collateral
# --------------------------------------------------------------------------- #
def render_margin_collateral(results: RiskResults, context: Context) -> None:
    today, previous, ccy = results.today, results.previous, results.config.base_currency
    im_config = results.config.initial_margin
    margin = today.margin_counterparties
    largest = margin.loc[margin["initial_margin"].idxmax()]
    calls = today.collateral[today.collateral["transfer_amount"] > 0]

    ui.page_header("Margin & Collateral", "Initial Margin requirements and collateral position by counterparty",
                   today.as_of, context)
    ui.kpi_row([
        Kpi("Total Initial Margin", money(today.total_initial_margin, ccy), "margin",
            f"Netting benefit {money(margin['netting_benefit'].sum(), ccy)}",
            ui.trend_text(today.total_initial_margin, previous.total_initial_margin if previous else None, ccy)),
        Kpi("Total Collateral", money(today.portfolio["collateral"], ccy), "collateral",
            f"Requirement {money(today.collateral['collateral_requirement'].sum(), ccy)}"),
        Kpi("Average IM", money(margin["initial_margin"].mean(), ccy), "expected", "Per counterparty"),
        Kpi("Largest Margin Requirement", money(largest["initial_margin"], ccy), "pfe", str(largest["counterparty_id"])),
        Kpi("Collateral Calls", str(len(calls)), "alert",
            f"{money(calls['transfer_amount'].sum(), ccy)} to call" if len(calls) else "None due",
            tone="warn" if len(calls) else ""),
    ])

    view = results.consolidated.sort_values("counterparty_id")
    left, right = st.columns(2, gap="large")
    with left:
        ui.section("Initial Margin")
        ui.chart(charts.margin_by_counterparty(today.margin_factors), "Initial Margin by counterparty",
                 "Stacked by product / risk factor")
    with right:
        ui.section("Collateral Coverage")
        ui.chart(charts.exposure_components(view), "Gross exposure vs collateral vs net exposure",
                 "Net exposure = max(gross exposure − collateral, 0)")

    ui.section("Margin & Collateral by Counterparty")
    table = today.collateral.merge(margin[["counterparty_id", "initial_margin"]], on="counterparty_id")
    ui.table(
        [("Counterparty", L), ("Gross exposure", R), ("Collateral", R), ("Net exposure", R), ("Initial Margin", R),
         ("Collateral requirement", R), ("Threshold", R), ("MTA", R), ("Transfer", R), ("Action", L)],
        [[ui.counterparty_link(c.counterparty_id), money(c.gross_exposure, ccy), money(c.collateral_held, ccy),
          money(c.net_exposure, ccy), money(c.initial_margin, ccy), money(c.collateral_requirement, ccy),
          money(c.collateral_threshold, ccy), money(c.minimum_transfer_amount, ccy),
          money(c.transfer_amount, ccy, signed=True) if c.transfer_amount else ui.DASH, ui.badge(c.action)]
         for c in table.itertuples()],
        footer=["Portfolio", money(table["gross_exposure"].sum(), ccy), money(table["collateral_held"].sum(), ccy),
                money(table["net_exposure"].sum(), ccy), money(table["initial_margin"].sum(), ccy),
                money(table["collateral_requirement"].sum(), ccy), "", "", "", ""],
    )

    left, right = st.columns(2, gap="large")
    with left:
        ui.section("Initial Margin by Product")
        ui.metric_rows(
            [(f"{c.product_type} ({RISK_FACTORS[c.risk_factor].label.split(' (')[0]})",
              f'{money(c.initial_margin, ccy)} <span style="color:{TEXT_SECONDARY}">&nbsp;{pct(c.share)}</span>')
             for c in today.margin_contributions.itertuples()]
            + [("Portfolio", money(today.total_initial_margin, ccy))],
            total_last=True,
        )
    with right:
        ui.section("Model Parameters")
        z = confidence_multiplier(im_config.confidence_level)
        ui.metric_rows([
            ("Formula", "IM = Z × Volatility × Exposure × √T"),
            ("Confidence level / Z", f"{im_config.confidence_level:.0%} / {z:.3f}"),
            ("Margin period (T)", f"{im_config.margin_period_days} days"),
            ("Volatility source", escape(im_config.volatility_source)),
            *[(f"Daily volatility · {RISK_FACTORS[name].label.split(' (')[0]}",
               f"{value * charts.factor_unit(name)[0]:.2f}{charts.factor_unit(name)[1]}")
              for name, value in today.factor_volatility.items()],
        ])

    with st.expander("Trade-level Initial Margin"):
        ui.table(
            [("Trade", L), ("Counterparty", L), ("Product", L), ("Delta exposure", R), ("Daily volatility", R), ("Initial Margin", R)],
            [[m.trade_id, m.counterparty_id, escape(m.product_type), money(m.delta_exposure, ccy),
              f"{m.daily_volatility * charts.factor_unit(m.risk_factor)[0]:.2f}{charts.factor_unit(m.risk_factor)[1]}",
              money(m.initial_margin, ccy)] for m in today.margin_trades.itertuples()],
        )
        ui.note("Trade margins are stand-alone. Counterparty margin offsets long and short positions in the same "
                "risk factor and adds across risk factors without diversification benefit.")


# --------------------------------------------------------------------------- #
# Market data
# --------------------------------------------------------------------------- #
def render_market(results: RiskResults, context: Context) -> None:
    config = results.config.market_data
    ui.page_header("Market Data", "Historical behaviour of the risk factors that drive the exposure scenarios",
                   results.today.as_of, context)

    factors = list(results.market_levels.columns)
    labels = {name: RISK_FACTORS[name].label.split(" (")[0] for name in factors}
    windows = {"1Y": 252, "2Y": 504, "3Y": 756, "All": None}
    left, right, _ = st.columns([2.2, 1.6, 3], vertical_alignment="bottom")
    name = left.segmented_control("Risk factor", factors, default=factors[0], format_func=lambda n: labels[n]) or factors[0]
    window = right.segmented_control("History", list(windows), default="All") or "All"

    levels = results.market_levels[name]
    returns = results.market_returns[name]
    if windows[window]:
        levels, returns = levels.tail(windows[window]), returns.tail(windows[window])
    stats = market_data.return_statistics(returns.to_frame(), config.return_percentiles, config.trading_days_per_year).loc[name]
    scale, unit = charts.factor_unit(name)
    is_yield = unit == "bp"
    last_move = float(returns.iloc[-1]) * scale

    def move(value: float) -> str:
        return f"{value * scale:+.2f}{unit}" if not is_yield else f"{value * scale:+.1f}{unit}"

    ui.kpi_row([
        Kpi("Current Value", f"{levels.iloc[-1]:,.2f}{'%' if is_yield else ''}", "market",
            RISK_FACTORS[name].unit, f"{'▲' if last_move >= 0 else '▼'} {abs(last_move):.2f}{unit} 1d"),
        Kpi("Historical Volatility", f"{stats['annualised_volatility'] * scale:.2f}{unit}", "pfe",
            f"Annualised · daily {stats['daily_volatility'] * scale:.2f}{unit}"),
        Kpi("Mean Return", f"{stats['mean_return'] * scale:+.3f}{unit}", "expected", "Per day"),
        Kpi("Worst Day", move(stats["min_return"]), "alert", f"{returns.idxmin():%d %b %Y}"),
        Kpi("Best Day", move(stats["max_return"]), "exposure", f"{returns.idxmax():%d %b %Y}"),
    ])

    source = results.market_metadata.get("source", "unknown")
    ui.section("Historical Price")
    ui.chart(charts.price_history(levels, name), f"{labels[name]}: historical level",
             f"{len(levels):,} observations · {levels.index[0]:%d %b %Y} to {levels.index[-1]:%d %b %Y} · source: {source}")

    move_name = "yield changes" if is_yield else "returns"
    left, right = st.columns(2, gap="large")
    with left:
        ui.section("Daily Returns")
        ui.chart(charts.daily_returns(returns, name), f"{labels[name]}: daily {move_name}")
    with right:
        ui.section("Return Distribution")
        ui.chart(charts.return_distribution(returns, name), f"{labels[name]}: distribution of daily {move_name}",
                 "Dashed lines mark the 1st and 99th percentiles")

    left, right = st.columns(2, gap="large")
    with left:
        ui.section("Historical Volatility")
        rolling = market_data.rolling_volatility(
            results.market_returns[[name]], config.volatility_window, config.trading_days_per_year)[name]
        ui.chart(charts.rolling_volatility(rolling.loc[levels.index[0]:], name),
                 f"{labels[name]}: {config.volatility_window}-day rolling volatility", "Annualised")
    with right:
        ui.section("Return Percentiles")
        ui.metric_rows([
            ("Minimum", move(stats["min_return"])),
            *[(f"{p:.0%} percentile", move(stats[f"p{p * 100:g}"])) for p in config.return_percentiles],
            ("Maximum", move(stats["max_return"])),
        ])
    if is_yield:
        ui.note("The interest-rate factor is the US 10-year Treasury yield, used as a proxy for INR rates. "
                "Moves are absolute yield changes in basis points.")
    ui.note(f"The exposure engine uses the most recent {config.lookback_days} "
            f"{results.config.exposure.scenario_horizon_days}-day moves of these factors as its scenarios.")


# --------------------------------------------------------------------------- #
# Reports
# --------------------------------------------------------------------------- #
def _key_developments(results: RiskResults) -> list[str]:
    """Bullet points derived from today's and the previous run's results."""
    today, previous, ccy = results.today, results.previous, results.config.base_currency
    pfe_label, pfe_col = _top_pfe(results)
    before = previous.limits.set_index("counterparty_id")["status"].to_dict() if previous else {}
    bullets = []
    for row in today.limits.itertuples():
        was = before.get(row.counterparty_id)
        if row.status == STATUS_BREACH:
            verb = "remains in breach of" if was == STATUS_BREACH else "breached"
            bullets.append(f"{row.counterparty_id} {verb} its {money(row.credit_limit, ccy)} credit limit "
                           f"({row.driver} utilisation {pct(row.utilisation)}).")
        elif row.status == STATUS_WARNING:
            verb = "remains above" if was == STATUS_WARNING else "moved above"
            bullets.append(f"{row.counterparty_id} {verb} the {row.warning_threshold:.0%} warning threshold "
                           f"({pct(row.utilisation)} utilised, {money(row.headroom, ccy)} headroom).")
        elif was in (STATUS_BREACH, STATUS_WARNING):
            bullets.append(f"{row.counterparty_id} returned to Normal from {was} ({pct(row.utilisation)} utilised).")
    if previous:
        def changed(label: str, new: float, old: float) -> str:
            if abs(new - old) < 50_000:
                return f"{label} was unchanged at {money(new, ccy)}."
            return f"{label} {'increased' if new > old else 'decreased'} by {money(abs(new - old), ccy)} to {money(new, ccy)}."

        bullets.append(changed(f"Portfolio {pfe_label}", today.portfolio[pfe_col], previous.portfolio[pfe_col]))
        bullets.append(changed("Portfolio collateral requirement", float(today.collateral["collateral_requirement"].sum()),
                               float(previous.collateral["collateral_requirement"].sum())))
        bullets.append(changed("Initial Margin", today.total_initial_margin, previous.total_initial_margin))
    calls = today.collateral[today.collateral["transfer_amount"] > 0]
    if len(calls):
        bullets.append(f"Collateral calls due from {', '.join(calls['counterparty_id'])} "
                       f"totalling {money(calls['transfer_amount'].sum(), ccy)}.")
    return bullets


def render_reports(results: RiskResults, context: Context) -> None:
    today, config = results.today, results.config
    ui.page_header("Reports", "Generate the daily risk pack and export risk data", today.as_of, context)

    report = config.paths.excel_report
    generated = f"{datetime.fromtimestamp(report.stat().st_mtime):%d %b %Y · %H:%M}" if report.exists() else "not yet generated"
    ui.section("Daily Risk Report", f"Last generated: {generated} · {report.name} · 9 sheets")

    names = results.counterparties[["counterparty_id", "name", "sector"]]
    exposure_csv = names.merge(today.exposure, on="counterparty_id").to_csv(index=False).encode("utf-8-sig")
    flagged = today.limits[today.limits["status"] != STATUS_NORMAL]
    breach_csv = flagged.to_csv(index=False).encode("utf-8-sig")
    stamp = f"{today.as_of:%Y%m%d}"

    b1, b2, b3, b4 = st.columns(4, gap="small")
    if b1.button("Generate Risk Report", type="primary", width="stretch", icon=":material/play_arrow:"):
        try:
            database.save_results(results)
            reporting.write_report_csvs(results)
            reporting.write_excel_report(results)
            st.toast("Risk report generated. Database, CSV extracts and Excel report updated.")
            st.rerun()
        except Exception as exc:  # report the failure in the page instead of a stack trace
            st.error(f"Report generation failed: {exc}")
    b2.download_button(
        "Export Excel", report.read_bytes() if report.exists() else b"", file_name=report.name, width="stretch",
        disabled=not report.exists(), icon=":material/download:",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    b3.download_button("Export Exposure Data", exposure_csv, file_name=f"exposure_{stamp}.csv", mime="text/csv",
                       width="stretch", icon=":material/download:")
    b4.download_button("Export Breach Report", breach_csv, file_name=f"limit_breaches_{stamp}.csv", mime="text/csv",
                       width="stretch", icon=":material/download:", disabled=flagged.empty,
                       help="Counterparties in Warning or Breach" if not flagged.empty else "No warnings or breaches to export")

    ui.section("Daily Risk Commentary", f"Generated from the risk results for {today.as_of:%d %b %Y}"
               + (f" against {results.previous.as_of:%d %b %Y}" if results.previous else ""))
    by_scope = {"Portfolio": [], "Market": []}
    counterparty_items = []
    for item in results.commentary:
        if item.scope in by_scope:
            by_scope[item.scope].append(item.text)
        else:
            counterparty_items.append(item)

    names_by_id = results.counterparties.set_index("counterparty_id")["name"].to_dict()
    notes = []
    for item in counterparty_items:
        status = {"Breach": STATUS_BREACH, "Warning": STATUS_WARNING}.get(item.severity, STATUS_NORMAL)
        notes.append(
            f'<div class="cpn">{ui.counterparty_link(item.scope)}<small>{escape(str(names_by_id.get(item.scope, "")))}</small>'
            f"{ui.badge(status)}</div><p>{escape(item.text)}</p>"
        )
    ui.commentary([
        ("Portfolio Summary", ui.paragraphs(by_scope["Portfolio"])),
        ("Key Developments", ui.bullets(_key_developments(results))),
        ("Market", ui.paragraphs(by_scope["Market"])),
        ("Counterparties", "".join(notes)),
    ])

    text = "\n\n".join(f"[{item.severity}] {item.scope}: {item.text}" for item in results.commentary)
    st.download_button("Download commentary (.txt)", text, file_name=f"risk_commentary_{stamp}.txt",
                       icon=":material/download:")

    ui.section("Risk Database", "Read-only SQL over the SQLite risk database")
    with st.expander("Saved and custom queries"):
        if not config.paths.database.exists():
            ui.empty_state("No database yet", "Use Generate Risk Report above to create it.")
            return
        queries = database.load_named_queries()
        key = st.selectbox("Saved query", list(queries), format_func=lambda k: queries[k].title)
        st.code(queries[key].sql, language="sql")
        try:
            st.dataframe(database.run_query(config, key), hide_index=True, width="stretch")
        except database.DatabaseError as exc:
            st.error(str(exc))
        custom = st.text_area(
            "Custom SELECT statement",
            "SELECT counterparty_id, run_date, pfe_99 / 1e6 AS pfe_99_m\nFROM exposure_results\nORDER BY run_date, pfe_99 DESC",
            height=110,
        )
        if st.button("Run query"):
            try:
                st.dataframe(database.run_sql(config.paths.database, custom), hide_index=True, width="stretch")
            except database.DatabaseError as exc:
                st.error(str(exc))
