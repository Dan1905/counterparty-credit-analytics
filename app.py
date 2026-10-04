"""Streamlit dashboard: Counterparty Credit Risk & Exposure Analytics.

Run with:  streamlit run app.py
"""

from __future__ import annotations

from datetime import datetime
from typing import Callable

import streamlit as st

from ccr import database, reporting
from ccr.config import ConfigError, load_config
from ccr.logging_setup import configure_logging
from ccr.pipeline import RiskResults, run_analysis
from dashboard import components as ui
from dashboard import views
from dashboard.theme import CSS, active_nav_css

st.set_page_config(page_title="Counterparty Credit Analytics", layout="wide")

# url path -> (label, icon, renderer). This is the application's only navigation:
# Streamlit's page router, drawn in the sidebar as one link per page.
PAGES: dict[str, tuple[str, str, Callable[[RiskResults, ui.Context], None]]] = {
    "overview": ("Overview", ":material/dashboard:", views.render_overview),
    "counterparty": ("Counterparty Risk", ":material/account_balance:", views.render_counterparty),
    "exposure": ("Exposure Analysis", ":material/bar_chart:", views.render_exposure),
    "limits": ("Limit Monitoring", ":material/speed:", views.render_limits),
    "credit": ("Credit Analysis", ":material/fact_check:", views.render_credit),
    "margin": ("Margin & Collateral", ":material/shield:", views.render_margin_collateral),
    "market": ("Market Data", ":material/show_chart:", views.render_market),
    "reports": ("Reports", ":material/description:", views.render_reports),
}
AS_OF_CHOICES = 10  # most recent valuation dates offered in the sidebar


@st.cache_resource(show_spinner="Running exposure analysis...")
def load_results(as_of: str | None) -> tuple[RiskResults, datetime]:
    """Run the analysis for a valuation date (``None`` = latest) and time-stamp the run."""
    config = load_config()
    configure_logging(config.paths.log_file)
    results = run_analysis(config, as_of)
    if as_of is None and not config.paths.database.exists():
        database.save_results(results)
    return results, datetime.now()


def _page(key: str, shared: dict[str, object]) -> st.Page:  # type: ignore[valid-type]
    """Router entry for one page; the renderer receives the results loaded in ``main``."""
    label, icon, renderer = PAGES[key]

    def run() -> None:
        renderer(shared["results"], shared["context"])  # type: ignore[arg-type]

    run.__name__ = f"page_{key}"
    return st.Page(run, title=label, icon=icon, url_path=key, default=key == ui.HOME_PAGE)


def _format_date(value: str) -> str:
    return f"{datetime.strptime(value, '%Y-%m-%d'):%d %b %Y}"


def main() -> None:
    shared: dict[str, object] = {}
    pages = [_page(key, shared) for key in PAGES]
    current = st.navigation(pages, position="hidden")
    st.html(CSS + active_nav_css(current.url_path))

    with st.sidebar:
        ui.brand("COUNTERPARTY CREDIT ANALYTICS", "Exposure · Margin · Limits")
        for page in pages:
            ui.nav_item(page)

    try:
        latest, _ = load_results(None)
        dates = [f"{d:%Y-%m-%d}" for d in latest.market_levels.index[-AS_OF_CHOICES:]][::-1]
        # A valuation date arriving in the URL (from a table link) seeds the selector once.
        linked = st.query_params.get("asof")
        if linked in dates and "as_of" not in st.session_state:
            st.session_state["as_of"] = linked
        if st.session_state.get("as_of") not in dates:
            st.session_state["as_of"] = dates[0]

        with st.sidebar:
            ui.side_label("Valuation date")
            selected = st.selectbox("Valuation date", dates, key="as_of", format_func=_format_date,
                                    label_visibility="collapsed")
            rerun = st.button("Re-run analysis", icon=":material/refresh:", width="stretch",
                              help="Reload config, portfolio and market data, recompute, and update SQLite and Excel.")
        as_of = None if selected == dates[0] else selected
        st.session_state["as_of_param"] = as_of

        if rerun:
            load_results.clear()
        results, run_time = load_results(as_of)
        if rerun:
            database.save_results(results)
            reporting.write_report_csvs(results)
            reporting.write_excel_report(results)
            st.toast("Analysis complete. Database and Excel report updated.")
    except ConfigError as exc:
        st.error(f"Configuration error: {exc}")
        st.stop()
    except Exception as exc:  # surface any data / calculation failure instead of a stack trace
        st.error(f"The risk run failed: {exc}")
        st.stop()

    retrieved = str(results.market_metadata.get("retrieved_at", ""))
    try:
        data_time = f"{datetime.fromisoformat(retrieved):%d %b %Y %H:%M}"
    except ValueError:
        data_time = "unknown"
    config = results.config
    with st.sidebar:
        ui.side_label("System status")
        ui.system_status([
            ("Data updated", data_time),
            ("Analysis run", f"{run_time:%d %b %Y %H:%M}"),
            ("Market data", str(results.market_metadata.get("source", "unknown"))),
            ("Book", f"{len(results.counterparties)} cpties · {len(results.trades)} trades"),
            ("Scenarios", f"{len(results.today.scenarios)} × {config.exposure.scenario_horizon_days}-day"),
        ])

    shared["results"] = results
    shared["context"] = ui.Context(run_time=run_time, data_time=data_time)
    current.run()


main()
