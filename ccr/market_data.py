"""Historical market data: loading, return statistics and scenario generation.

Three risk factors drive the portfolio:

* ``NIFTY50``  - equity index level (shock = relative return)
* ``USDINR``   - FX spot (shock = relative return)
* ``RATE_10Y`` - 10-year government yield in percent, used as the interest-rate
  proxy (shock = absolute yield change expressed as a decimal, i.e. 10bp = 0.001)
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


class MarketDataError(ValueError):
    """Raised when market data is missing, malformed or too short."""


@dataclass(frozen=True)
class RiskFactor:
    """Static description of a market risk factor."""

    name: str
    label: str
    ticker: str
    shock_type: str  # "relative" (price return) or "absolute" (yield change)
    unit: str


RISK_FACTORS: dict[str, RiskFactor] = {
    "NIFTY50": RiskFactor("NIFTY50", "NIFTY 50", "^NSEI", "relative", "index points"),
    "USDINR": RiskFactor("USDINR", "USD/INR", "INR=X", "relative", "INR per USD"),
    "RATE_10Y": RiskFactor(
        "RATE_10Y", "10Y yield (rate proxy)", "^TNX", "absolute", "percent"
    ),
}

YIELD_QUOTE_SCALE = 100.0  # yields are quoted in percent; shocks are decimals


# --------------------------------------------------------------------------- #
# Acquisition
# --------------------------------------------------------------------------- #
def fetch_yahoo_history(ticker: str, years: int = 5, timeout: float = 20.0) -> pd.Series:
    """Download daily closes for ``ticker`` from the Yahoo Finance chart API."""
    encoded = urllib.request.quote(ticker, safe="")
    url = (
        f"https://query1.finance.yahoo.com/v8/finance/chart/{encoded}"
        f"?range={years}y&interval=1d"
    )
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.load(response)
        result = payload["chart"]["result"][0]
        closes = result["indicators"]["quote"][0]["close"]
        dates = [
            datetime.fromtimestamp(ts, tz=timezone.utc).date() for ts in result["timestamp"]
        ]
    except (urllib.error.URLError, KeyError, IndexError, TypeError, ValueError) as exc:
        raise MarketDataError(f"Could not download {ticker}: {exc}") from exc

    series = pd.Series(closes, index=pd.to_datetime(dates), dtype=float).dropna()
    series = series[~series.index.duplicated(keep="last")].sort_index()
    if series.empty:
        raise MarketDataError(f"No observations returned for {ticker}")
    return series


def fetch_market_data(years: int = 5) -> pd.DataFrame:
    """Download all risk factors and align them on common business days."""
    columns = {name: fetch_yahoo_history(rf.ticker, years) for name, rf in RISK_FACTORS.items()}
    frame = pd.DataFrame(columns).sort_index().ffill(limit=3)
    # The NIFTY trading calendar is the master calendar: the portfolio is INR-based,
    # so days on which the Indian market was closed are not valuation dates.
    return clean_levels(frame.loc[columns["NIFTY50"].index])


def generate_synthetic_market_data(
    n_days: int = 1260, seed: int = 42, end: str | None = None
) -> pd.DataFrame:
    """Simulate plausible risk-factor histories (offline fallback only).

    Equity and FX follow correlated geometric random walks with fat tails
    (Student-t innovations); the yield follows a random walk in basis points.
    """
    rng = np.random.default_rng(seed)
    end_date = pd.Timestamp(end) if end else pd.Timestamp.today().normalize()
    dates = pd.bdate_range(end=end_date, periods=n_days)
    corr = np.array([[1.0, -0.35, -0.10], [-0.35, 1.0, 0.15], [-0.10, 0.15, 1.0]])
    chol = np.linalg.cholesky(corr)
    shocks = rng.standard_t(df=5, size=(n_days, 3)) / np.sqrt(5 / 3) @ chol.T
    daily_vol = np.array([0.0095, 0.0030, 0.055])  # equity, fx, yield (pct points)
    drift = np.array([0.0004, 0.0001, 0.0])
    moves = shocks * daily_vol + drift
    nifty = 17500.0 * np.exp(np.cumsum(moves[:, 0]))
    usdinr = 82.0 * np.exp(np.cumsum(moves[:, 1]))
    rate = np.clip(4.0 + np.cumsum(moves[:, 2]), 0.5, None)
    return pd.DataFrame({"NIFTY50": nifty, "USDINR": usdinr, "RATE_10Y": rate}, index=dates)


def clean_levels(levels: pd.DataFrame) -> pd.DataFrame:
    """Align risk factors on a common calendar and drop unusable rows."""
    missing = set(RISK_FACTORS) - set(levels.columns)
    if missing:
        raise MarketDataError(f"Market data is missing risk factors: {sorted(missing)}")
    cleaned = levels[list(RISK_FACTORS)].sort_index()
    cleaned = cleaned[cleaned.index.dayofweek < 5]
    # A factor that did not trade on a given day (local holiday) keeps its last level.
    cleaned = cleaned.ffill(limit=3).dropna()
    if (cleaned <= 0).any().any():
        raise MarketDataError("Market data contains non-positive levels")
    cleaned.index.name = "date"
    return cleaned


def save_market_data(levels: pd.DataFrame, path: Path, source: str) -> None:
    """Persist levels as a long CSV plus a small JSON file recording provenance."""
    path.parent.mkdir(parents=True, exist_ok=True)
    long = levels.rename_axis("date").reset_index().melt(
        id_vars="date", var_name="risk_factor", value_name="value"
    )
    long["date"] = long["date"].dt.strftime("%Y-%m-%d")
    long.to_csv(path, index=False)
    meta = {
        "source": source,
        "retrieved_at": datetime.now().isoformat(timespec="seconds"),
        "start": levels.index.min().strftime("%Y-%m-%d"),
        "end": levels.index.max().strftime("%Y-%m-%d"),
        "observations": int(len(levels)),
        "tickers": {name: rf.ticker for name, rf in RISK_FACTORS.items()},
    }
    path.with_suffix(".meta.json").write_text(json.dumps(meta, indent=2))
    logger.info("Saved %d market observations (%s) to %s", len(levels), source, path)


def load_market_data(path: Path) -> pd.DataFrame:
    """Read the long market-data CSV into a wide date-indexed frame of levels."""
    if not path.exists():
        raise MarketDataError(
            f"Market data file not found: {path}. Run `python scripts/fetch_market_data.py`."
        )
    long = pd.read_csv(path, parse_dates=["date"])
    required = {"date", "risk_factor", "value"}
    if not required.issubset(long.columns):
        raise MarketDataError(f"{path} must contain columns {sorted(required)}")
    wide = long.pivot(index="date", columns="risk_factor", values="value")
    wide.columns.name = None
    return clean_levels(wide)


def load_market_metadata(path: Path) -> dict[str, object]:
    """Return the provenance record written next to the market-data CSV."""
    meta_path = path.with_suffix(".meta.json")
    if not meta_path.exists():
        return {"source": "unknown"}
    return json.loads(meta_path.read_text())


# --------------------------------------------------------------------------- #
# Returns and statistics
# --------------------------------------------------------------------------- #
def compute_shocks(levels: pd.DataFrame, horizon: int = 1) -> pd.DataFrame:
    """Observed market moves over ``horizon`` business days.

    Relative factors: ``P_t / P_{t-h} - 1``.
    Absolute factors (yields in percent): ``(y_t - y_{t-h}) / 100``.
    """
    if horizon <= 0:
        raise MarketDataError("horizon must be a positive number of days")
    shocks = {}
    for name in levels.columns:
        series = levels[name]
        if RISK_FACTORS[name].shock_type == "relative":
            shocks[name] = series / series.shift(horizon) - 1.0
        else:
            shocks[name] = (series - series.shift(horizon)) / YIELD_QUOTE_SCALE
    return pd.DataFrame(shocks).dropna()


def compute_daily_returns(levels: pd.DataFrame) -> pd.DataFrame:
    """One-day market moves (see :func:`compute_shocks`)."""
    return compute_shocks(levels, horizon=1)


def historical_volatility(returns: pd.DataFrame, lookback: int | None = None) -> pd.Series:
    """Daily standard deviation of returns over the last ``lookback`` observations."""
    window = returns.tail(lookback) if lookback else returns
    if len(window) < 2:
        raise MarketDataError("Need at least two returns to compute volatility")
    return window.std(ddof=1)


def rolling_volatility(
    returns: pd.DataFrame, window: int = 60, trading_days: int = 252
) -> pd.DataFrame:
    """Annualised rolling volatility used for the market-data charts."""
    return returns.rolling(window).std(ddof=1).dropna() * np.sqrt(trading_days)


def return_statistics(
    returns: pd.DataFrame,
    percentiles: tuple[float, ...] = (0.01, 0.05, 0.95, 0.99),
    trading_days: int = 252,
) -> pd.DataFrame:
    """Summary statistics of daily returns, one row per risk factor."""
    stats = pd.DataFrame(
        {
            "observations": returns.count(),
            "mean_return": returns.mean(),
            "daily_volatility": returns.std(ddof=1),
            "annualised_volatility": returns.std(ddof=1) * np.sqrt(trading_days),
            "min_return": returns.min(),
            "max_return": returns.max(),
        }
    )
    for p in percentiles:
        stats[f"p{p * 100:g}"] = returns.quantile(p)
    stats.index.name = "risk_factor"
    return stats


def build_scenarios(
    levels: pd.DataFrame, horizon: int, lookback: int, as_of: pd.Timestamp | None = None
) -> pd.DataFrame:
    """Historical scenarios: the last ``lookback`` observed ``horizon``-day moves up to ``as_of``.

    Each row is one scenario (labelled by the date the move ended) and each
    column a risk-factor shock that can be applied to today's portfolio.
    """
    history = levels if as_of is None else levels.loc[:as_of]
    shocks = compute_shocks(history, horizon)
    if len(shocks) < lookback:
        logger.warning(
            "Only %d scenarios available (requested %d); using all of them",
            len(shocks),
            lookback,
        )
    scenarios = shocks.tail(lookback)
    if len(scenarios) < 30:
        raise MarketDataError(
            f"Only {len(scenarios)} scenarios available; at least 30 are required"
        )
    scenarios.index.name = "scenario_date"
    return scenarios
