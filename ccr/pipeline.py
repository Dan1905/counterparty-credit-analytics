"""End-to-end risk run: data -> scenarios -> exposure -> collateral -> IM -> limits -> reporting."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

import pandas as pd

from ccr import collateral as collateral_module
from ccr import credit_analysis, exposure, limits, margin, market_data
from ccr.commentary import CommentaryItem, generate_commentary
from ccr.config import Config, load_config
from ccr.data_generation import write_dataset

logger = logging.getLogger(__name__)


class PipelineError(RuntimeError):
    """Raised when the risk run cannot be completed."""


@dataclass
class RiskSnapshot:
    """All risk results for a single valuation date."""

    as_of: pd.Timestamp
    trades: pd.DataFrame                 # trades with notional_base and MTM as of this date
    scenarios: pd.DataFrame              # scenario x risk factor shocks
    scenario_mtm: pd.DataFrame           # scenario x trade MTM
    exposure_distribution: pd.DataFrame  # scenario x counterparty exposure
    exposure: pd.DataFrame               # counterparty exposure summary (EE, PFE, ...)
    portfolio: dict[str, float]
    collateral: pd.DataFrame
    margin_trades: pd.DataFrame
    margin_factors: pd.DataFrame
    margin_counterparties: pd.DataFrame
    margin_contributions: pd.DataFrame
    limits: pd.DataFrame
    factor_volatility: pd.Series
    fx_rates: dict[str, float]

    @property
    def total_initial_margin(self) -> float:
        return float(self.margin_counterparties["initial_margin"].sum())

    @property
    def breach_count(self) -> int:
        return int((self.limits["status"] == limits.STATUS_BREACH).sum())

    @property
    def warning_count(self) -> int:
        return int((self.limits["status"] == limits.STATUS_WARNING).sum())


@dataclass
class RiskResults:
    """Everything the dashboard, database and Excel report need."""

    config: Config
    counterparties: pd.DataFrame
    trades: pd.DataFrame
    financials: pd.DataFrame
    market_levels: pd.DataFrame
    market_returns: pd.DataFrame
    market_statistics: pd.DataFrame
    market_metadata: dict[str, object]
    today: RiskSnapshot
    previous: RiskSnapshot | None
    credit: pd.DataFrame
    consolidated: pd.DataFrame
    highlights: dict[str, dict[str, object]]
    commentary: list[CommentaryItem] = field(default_factory=list)


# --------------------------------------------------------------------------- #
# Loading
# --------------------------------------------------------------------------- #
def ensure_dataset(config: Config) -> None:
    """Create the market-data file and synthetic portfolio if they do not exist yet."""
    paths = config.paths
    if not paths.market_data.exists():
        try:
            levels, source = market_data.fetch_market_data(), "Yahoo Finance"
        except market_data.MarketDataError as exc:
            logger.warning("Market-data download failed (%s); using synthetic history", exc)
            levels = market_data.generate_synthetic_market_data(seed=config.random_seed)
            source = "synthetic"
        market_data.save_market_data(levels, paths.market_data, source)
    if not all(p.exists() for p in (paths.counterparties, paths.trades, paths.financials)):
        levels = market_data.load_market_data(paths.market_data)
        write_dataset(
            paths.counterparties,
            paths.trades,
            paths.financials,
            seed=config.random_seed,
            as_of=levels.index[-1],
            usdinr=float(levels["USDINR"].iloc[-1]),
        )


def load_portfolio(config: Config) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Load counterparties, trades and financials from CSV and validate references."""
    try:
        counterparties = pd.read_csv(config.paths.counterparties)
        trades = pd.read_csv(config.paths.trades)
        financials = pd.read_csv(config.paths.financials)
    except FileNotFoundError as exc:
        raise PipelineError(f"Portfolio file missing: {exc.filename}") from exc

    if counterparties["counterparty_id"].duplicated().any():
        raise PipelineError("Counterparty IDs must be unique")
    counterparties["warning_threshold"] = counterparties["warning_threshold"].fillna(
        config.limits.warning_threshold
    )
    counterparties["collateral_threshold"] = counterparties["collateral_threshold"].fillna(
        config.collateral.default_threshold
    )
    counterparties["minimum_transfer_amount"] = counterparties["minimum_transfer_amount"].fillna(
        config.collateral.default_minimum_transfer_amount
    )
    counterparties["collateral"] = counterparties["collateral"].fillna(0.0)

    known = set(counterparties["counterparty_id"])
    orphans = set(trades["counterparty_id"]) - known
    if orphans:
        raise PipelineError(f"Trades reference unknown counterparties: {sorted(orphans)}")
    no_financials = known - set(financials["counterparty_id"])
    if no_financials:
        raise PipelineError(f"No financials for counterparties: {sorted(no_financials)}")
    return counterparties, trades, financials


# --------------------------------------------------------------------------- #
# Calculation
# --------------------------------------------------------------------------- #
def fx_rates_as_of(levels: pd.DataFrame, as_of: pd.Timestamp, base_currency: str) -> dict[str, float]:
    """Units of base currency per unit of each trade currency on ``as_of``."""
    return {base_currency: 1.0, "USD": float(levels.loc[as_of, "USDINR"])}


def roll_back_mtm(trades: pd.DataFrame, levels: pd.DataFrame, as_of: pd.Timestamp) -> pd.DataFrame:
    """Previous-day trade MTMs implied by the latest observed one-day market move.

    MTM(T-1) = MTM(T) - Sensitivity x Shock(T) x Notional, i.e. the same
    sensitivity model as the scenario engine, run backwards over one day.
    """
    last_move = market_data.compute_daily_returns(levels.loc[:as_of]).iloc[-1]
    previous = trades.copy()
    shocks = previous["risk_factor"].map(last_move).to_numpy()
    previous["current_mtm"] = previous["current_mtm"] - exposure.pnl_change(
        previous["sensitivity"].to_numpy(), shocks, previous["notional_base"].to_numpy()
    )
    return previous


def compute_snapshot(
    config: Config,
    counterparties: pd.DataFrame,
    trades: pd.DataFrame,
    levels: pd.DataFrame,
    as_of: pd.Timestamp,
) -> RiskSnapshot:
    """Run every risk calculation for one valuation date."""
    exposure.validate_trades(trades, list(levels.columns))
    fx_rates = fx_rates_as_of(levels, as_of, config.base_currency)
    trades = trades.copy()
    trades["notional_base"] = exposure.base_notional(trades, fx_rates)

    scenarios = market_data.build_scenarios(
        levels, config.exposure.scenario_horizon_days, config.market_data.lookback_days, as_of
    )
    scenario_mtm = exposure.scenario_mtm_matrix(trades, scenarios)
    distribution = exposure.counterparty_exposure_distribution(
        scenario_mtm, trades, config.exposure.aggregation
    )
    held = counterparties.set_index("counterparty_id")["collateral"]
    levels_cfg = config.exposure.pfe_confidence_levels
    summary = exposure.exposure_summary(trades, distribution, held, levels_cfg)
    portfolio = exposure.portfolio_summary(summary, distribution, levels_cfg)

    collateral = collateral_module.collateral_summary(summary, counterparties)

    daily_returns = market_data.compute_daily_returns(levels.loc[:as_of])
    factor_vol = market_data.historical_volatility(daily_returns, config.market_data.lookback_days)
    trading_days = config.market_data.trading_days_per_year
    margin_trades = margin.trade_initial_margin(
        trades, factor_vol, config.initial_margin, trading_days
    )
    margin_factors = margin.counterparty_factor_margin(margin_trades, config.initial_margin)
    margin_counterparties = margin.counterparty_margin(margin_factors)

    limit_table = limits.limit_monitoring(
        summary, counterparties, config.limits, exposure.pfe_column(max(levels_cfg))
    )
    return RiskSnapshot(
        as_of=as_of,
        trades=trades,
        scenarios=scenarios,
        scenario_mtm=scenario_mtm,
        exposure_distribution=distribution,
        exposure=summary,
        portfolio=portfolio,
        collateral=collateral,
        margin_trades=margin_trades,
        margin_factors=margin_factors,
        margin_counterparties=margin_counterparties,
        margin_contributions=margin.margin_contributions(margin_factors),
        limits=limit_table,
        factor_volatility=factor_vol,
        fx_rates=fx_rates,
    )


def consolidated_view(
    counterparties: pd.DataFrame, financials: pd.DataFrame, credit: pd.DataFrame, snapshot: RiskSnapshot
) -> pd.DataFrame:
    """One row per counterparty combining credit, financial, exposure, margin and limit data."""
    view = counterparties[
        ["counterparty_id", "name", "sector", "country", "credit_rating", "credit_limit"]
    ].merge(credit, on="counterparty_id")
    view = view.merge(financials[["counterparty_id", "revenue", "ebitda"]], on="counterparty_id")
    view = view.merge(snapshot.exposure, on="counterparty_id")
    view = view.merge(
        snapshot.margin_counterparties[["counterparty_id", "initial_margin"]], on="counterparty_id"
    )
    view = view.merge(
        snapshot.limits[
            ["counterparty_id", "exposure_utilisation", "pfe_utilisation", "utilisation", "status"]
        ],
        on="counterparty_id",
    )
    return view


def run_analysis(config: Config | None = None, as_of: str | pd.Timestamp | None = None) -> RiskResults:
    """Load the data and compute today's and the previous day's risk results."""
    config = config or load_config()
    ensure_dataset(config)
    counterparties, trades, financials = load_portfolio(config)
    levels = market_data.load_market_data(config.paths.market_data)

    as_of_ts = pd.Timestamp(as_of) if as_of is not None else levels.index[-1]
    if as_of_ts not in levels.index:
        raise PipelineError(f"No market data for valuation date {as_of_ts.date()}")
    position = levels.index.get_loc(as_of_ts)
    logger.info("Running risk analysis as of %s (%d trades)", as_of_ts.date(), len(trades))

    today = compute_snapshot(config, counterparties, trades, levels, as_of_ts)

    previous: RiskSnapshot | None = None
    if position > config.exposure.scenario_horizon_days + 30:
        previous_date = levels.index[position - 1]
        previous_trades = roll_back_mtm(today.trades, levels, as_of_ts).drop(columns="notional_base")
        previous = compute_snapshot(config, counterparties, previous_trades, levels, previous_date)

    ratios = credit_analysis.financial_ratios(financials)
    credit = credit_analysis.credit_scores(ratios, config.credit_score)
    consolidated = consolidated_view(counterparties, financials, credit, today)
    highlights = limits.key_risk_highlights(
        today.limits, today.exposure, previous.exposure if previous else None
    )

    returns = market_data.compute_daily_returns(levels.loc[:as_of_ts])
    results = RiskResults(
        config=config,
        counterparties=counterparties,
        trades=trades,
        financials=financials,
        market_levels=levels.loc[:as_of_ts],
        market_returns=returns,
        market_statistics=market_data.return_statistics(
            returns,
            config.market_data.return_percentiles,
            config.market_data.trading_days_per_year,
        ),
        market_metadata=market_data.load_market_metadata(config.paths.market_data),
        today=today,
        previous=previous,
        credit=credit,
        consolidated=consolidated,
        highlights=highlights,
    )
    results.commentary = generate_commentary(results)
    logger.info(
        "Analysis complete: PFE99 %.1fM, IM %.1fM, %d breach(es), %d warning(s)",
        today.portfolio[exposure.pfe_column(max(config.exposure.pfe_confidence_levels))] / 1e6,
        today.total_initial_margin / 1e6,
        today.breach_count,
        today.warning_count,
    )
    return results


def run_pipeline(config: Config | None = None, as_of: str | None = None) -> RiskResults:
    """Full workflow: analysis, SQLite persistence, CSV extracts and the Excel report."""
    from ccr import database, reporting  # local import keeps the calculation core light

    config = config or load_config()
    results = run_analysis(config, as_of)
    database.save_results(results)
    reporting.write_report_csvs(results)
    reporting.write_excel_report(results)
    return results
