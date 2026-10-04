"""Typed access to ``config/config.toml``.

All model parameters are read once into frozen dataclasses so that every
calculation receives its inputs explicitly rather than reading globals.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config" / "config.toml"

CREDIT_METRICS: tuple[str, ...] = (
    "debt_to_ebitda",
    "current_ratio",
    "net_margin",
    "debt_to_assets",
    "revenue_growth",
)


class ConfigError(ValueError):
    """Raised when the configuration file is missing or holds invalid values."""


@dataclass(frozen=True)
class PathsConfig:
    counterparties: Path
    trades: Path
    financials: Path
    market_data: Path
    database: Path
    excel_report: Path
    report_csv_dir: Path
    log_file: Path


@dataclass(frozen=True)
class MarketDataConfig:
    lookback_days: int = 500
    volatility_window: int = 60
    return_percentiles: tuple[float, ...] = (0.01, 0.05, 0.25, 0.50, 0.75, 0.95, 0.99)
    trading_days_per_year: int = 252


@dataclass(frozen=True)
class ExposureConfig:
    scenario_horizon_days: int = 10
    pfe_confidence_levels: tuple[float, ...] = (0.95, 0.99)
    aggregation: str = "gross"


@dataclass(frozen=True)
class InitialMarginConfig:
    confidence_level: float = 0.99
    margin_period_days: int = 10
    volatility_source: str = "historical"
    net_within_risk_factor: bool = True
    volatility_overrides: dict[str, float] = field(default_factory=dict)


@dataclass(frozen=True)
class LimitsConfig:
    warning_threshold: float = 0.80
    breach_threshold: float = 1.00


@dataclass(frozen=True)
class CollateralConfig:
    default_threshold: float = 5_000_000.0
    default_minimum_transfer_amount: float = 500_000.0


@dataclass(frozen=True)
class MetricBounds:
    """Ratio values that map to 0 (``best``) and 100 (``worst``) risk points."""

    best: float
    worst: float


@dataclass(frozen=True)
class CreditScoreConfig:
    weights: dict[str, float]
    bounds: dict[str, MetricBounds]
    categories: dict[str, float]


@dataclass(frozen=True)
class CommentaryConfig:
    exposure_change_pct: float = 0.02
    margin_change_pct: float = 0.01
    high_exposure_utilisation: float = 0.50
    revenue_decline_flag: float = -0.05
    leverage_flag: float = 4.0


@dataclass(frozen=True)
class Config:
    base_currency: str
    random_seed: int
    paths: PathsConfig
    market_data: MarketDataConfig
    exposure: ExposureConfig
    initial_margin: InitialMarginConfig
    limits: LimitsConfig
    collateral: CollateralConfig
    credit_score: CreditScoreConfig
    commentary: CommentaryConfig


def _validate(cfg: Config) -> None:
    for level in cfg.exposure.pfe_confidence_levels:
        if not 0.0 < level < 1.0:
            raise ConfigError(f"PFE confidence level must be in (0, 1), got {level}")
    if not 0.5 < cfg.initial_margin.confidence_level < 1.0:
        raise ConfigError("initial_margin.confidence_level must be in (0.5, 1)")
    if cfg.initial_margin.margin_period_days <= 0:
        raise ConfigError("initial_margin.margin_period_days must be positive")
    if cfg.initial_margin.volatility_source not in ("historical", "trade"):
        raise ConfigError("initial_margin.volatility_source must be 'historical' or 'trade'")
    if cfg.exposure.aggregation not in ("gross", "netted"):
        raise ConfigError("exposure.aggregation must be 'gross' or 'netted'")
    if cfg.exposure.scenario_horizon_days <= 0 or cfg.market_data.lookback_days <= 1:
        raise ConfigError("scenario horizon and lookback must be positive")
    if not 0.0 < cfg.limits.warning_threshold <= cfg.limits.breach_threshold:
        raise ConfigError("limits: need 0 < warning_threshold <= breach_threshold")
    missing = set(CREDIT_METRICS) - set(cfg.credit_score.weights)
    if missing:
        raise ConfigError(f"credit_score.weights missing metrics: {sorted(missing)}")
    if sum(cfg.credit_score.weights.values()) <= 0:
        raise ConfigError("credit_score.weights must sum to a positive number")
    missing = set(CREDIT_METRICS) - set(cfg.credit_score.bounds)
    if missing:
        raise ConfigError(f"credit_score.bounds missing metrics: {sorted(missing)}")
    for name, bounds in cfg.credit_score.bounds.items():
        if bounds.best == bounds.worst:
            raise ConfigError(f"credit_score.bounds.{name}: best and worst must differ")


def load_config(path: Path | str | None = None) -> Config:
    """Load and validate the TOML configuration file."""
    config_path = Path(path) if path else DEFAULT_CONFIG_PATH
    if not config_path.exists():
        raise ConfigError(f"Configuration file not found: {config_path}")
    with config_path.open("rb") as handle:
        raw: dict[str, Any] = tomllib.load(handle)

    try:
        general = raw.get("general", {})
        paths = {key: PROJECT_ROOT / value for key, value in raw["paths"].items()}
        market = raw.get("market_data", {})
        exposure = raw.get("exposure", {})
        margin = dict(raw.get("initial_margin", {}))
        overrides = {k: float(v) for k, v in margin.pop("volatility_overrides", {}).items()}
        score = raw["credit_score"]
        cfg = Config(
            base_currency=general.get("base_currency", "INR"),
            random_seed=int(general.get("random_seed", 42)),
            paths=PathsConfig(**paths),
            market_data=MarketDataConfig(
                **{
                    **market,
                    "return_percentiles": tuple(
                        market.get("return_percentiles", MarketDataConfig.return_percentiles)
                    ),
                }
            ),
            exposure=ExposureConfig(
                **{
                    **exposure,
                    "pfe_confidence_levels": tuple(
                        sorted(exposure.get("pfe_confidence_levels", (0.95, 0.99)))
                    ),
                }
            ),
            initial_margin=InitialMarginConfig(**margin, volatility_overrides=overrides),
            limits=LimitsConfig(**raw.get("limits", {})),
            collateral=CollateralConfig(**raw.get("collateral", {})),
            credit_score=CreditScoreConfig(
                weights={k: float(v) for k, v in score["weights"].items()},
                bounds={k: MetricBounds(**v) for k, v in score["bounds"].items()},
                categories={k: float(v) for k, v in score["categories"].items()},
            ),
            commentary=CommentaryConfig(**raw.get("commentary", {})),
        )
    except (KeyError, TypeError) as exc:
        raise ConfigError(f"Invalid configuration in {config_path}: {exc}") from exc

    _validate(cfg)
    return cfg
