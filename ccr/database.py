"""SQLite persistence and the library of named risk queries."""

from __future__ import annotations

import logging
import re
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Iterator

import pandas as pd

from ccr.config import CREDIT_METRICS, PROJECT_ROOT, Config

if TYPE_CHECKING:  # pragma: no cover
    from ccr.pipeline import RiskResults, RiskSnapshot

logger = logging.getLogger(__name__)

SCHEMA_PATH = PROJECT_ROOT / "sql" / "schema.sql"
QUERIES_PATH = PROJECT_ROOT / "sql" / "queries.sql"

RESULT_TABLES: tuple[str, ...] = (
    "exposure_results",
    "exposure_scenarios",
    "margin_results",
    "collateral_results",
    "limit_breaches",
    "daily_commentary",
)


class DatabaseError(RuntimeError):
    """Raised when the database cannot be read or written."""


@dataclass(frozen=True)
class NamedQuery:
    key: str
    title: str
    sql: str


@contextmanager
def connect(path: Path) -> Iterator[sqlite3.Connection]:
    """Open a connection with foreign keys on; commit on success, roll back on error."""
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.execute("PRAGMA foreign_keys = ON")
    try:
        yield connection
        connection.commit()
    except sqlite3.Error as exc:
        connection.rollback()
        raise DatabaseError(f"Database operation failed: {exc}") from exc
    finally:
        connection.close()


def initialise(connection: sqlite3.Connection) -> None:
    """Create all tables if they do not exist."""
    connection.executescript(SCHEMA_PATH.read_text())


def _insert(connection: sqlite3.Connection, table: str, frame: pd.DataFrame) -> None:
    """Insert a frame using the table's own column list (extra frame columns are ignored)."""
    columns = [row[1] for row in connection.execute(f"PRAGMA table_info({table})")]
    usable = [c for c in columns if c in frame.columns]
    data = frame[usable].astype(object).where(frame[usable].notna(), None)
    placeholders = ", ".join("?" for _ in usable)
    connection.executemany(
        f"INSERT INTO {table} ({', '.join(usable)}) VALUES ({placeholders})",
        data.itertuples(index=False, name=None),
    )


def _snapshot_frames(snapshot: "RiskSnapshot", pfe_columns: list[str]) -> dict[str, pd.DataFrame]:
    run_date = snapshot.as_of.strftime("%Y-%m-%d")

    exposure = snapshot.exposure.copy()
    exposure = exposure.rename(columns=dict(zip(pfe_columns, ("pfe_95", "pfe_99"))))

    scenarios = snapshot.exposure_distribution.rename_axis("scenario_date").reset_index().melt(
        id_vars="scenario_date", var_name="counterparty_id", value_name="exposure"
    )
    scenarios["scenario_date"] = scenarios["scenario_date"].dt.strftime("%Y-%m-%d")

    trade_margin = snapshot.margin_trades.assign(level="trade")
    factor_margin = snapshot.margin_factors.assign(level="counterparty_factor").rename(
        columns={"net_delta_exposure": "delta_exposure"}
    )
    cp_margin = snapshot.margin_counterparties.assign(level="counterparty")
    portfolio_margin = pd.DataFrame(
        [{"level": "portfolio", "initial_margin": snapshot.total_initial_margin}]
    )
    margin = pd.concat([trade_margin, factor_margin, cp_margin, portfolio_margin], ignore_index=True)

    frames = {
        "exposure_results": exposure,
        "exposure_scenarios": scenarios,
        "margin_results": margin,
        "collateral_results": snapshot.collateral.copy(),
        "limit_breaches": snapshot.limits.copy(),
    }
    for frame in frames.values():
        frame["run_date"] = run_date
    return frames


def save_results(results: "RiskResults") -> Path:
    """Write reference data and the risk results for today (and the previous day) to SQLite.

    Reference tables are replaced; result tables are replaced per run date, so
    re-running a date is idempotent and history from other dates is kept.
    """
    path = results.config.paths.database
    levels = sorted(results.config.exposure.pfe_confidence_levels)
    pfe_columns = [f"pfe_{lvl * 100:g}".replace(".", "_") for lvl in (levels[0], levels[-1])]

    market = results.market_levels.rename_axis("date").reset_index().melt(
        id_vars="date", var_name="risk_factor", value_name="value"
    )
    returns = results.market_returns.rename_axis("date").reset_index().melt(
        id_vars="date", var_name="risk_factor", value_name="daily_return"
    )
    market = market.merge(returns, on=["date", "risk_factor"], how="left")
    market["date"] = market["date"].dt.strftime("%Y-%m-%d")

    with connect(path) as connection:
        initialise(connection)
        connection.execute("PRAGMA foreign_keys = OFF")
        for table in ("market_data", "credit_scores", "financials", "trades", "counterparties"):
            connection.execute(f"DELETE FROM {table}")
        connection.execute("PRAGMA foreign_keys = ON")
        _insert(connection, "counterparties", results.counterparties)
        _insert(connection, "trades", results.trades)
        _insert(connection, "financials", results.financials)
        _insert(connection, "credit_scores", results.credit[
            ["counterparty_id", *CREDIT_METRICS, "credit_score", "risk_category"]
        ].replace([float("inf")], [None]))
        _insert(connection, "market_data", market)

        snapshots = [s for s in (results.previous, results.today) if s is not None]
        for snapshot in snapshots:
            run_date = snapshot.as_of.strftime("%Y-%m-%d")
            for table in RESULT_TABLES:
                connection.execute(f"DELETE FROM {table} WHERE run_date = ?", (run_date,))
            for table, frame in _snapshot_frames(snapshot, pfe_columns).items():
                _insert(connection, table, frame)

        commentary = pd.DataFrame(
            [
                {
                    "run_date": results.today.as_of.strftime("%Y-%m-%d"),
                    "sequence": i,
                    "scope": item.scope,
                    "severity": item.severity,
                    "text": item.text,
                }
                for i, item in enumerate(results.commentary, start=1)
            ]
        )
        if not commentary.empty:
            _insert(connection, "daily_commentary", commentary)

    logger.info("Results saved to %s", path)
    return path


# --------------------------------------------------------------------------- #
# Queries
# --------------------------------------------------------------------------- #
def load_named_queries(path: Path = QUERIES_PATH) -> dict[str, NamedQuery]:
    """Parse ``sql/queries.sql`` into a dictionary of named queries."""
    queries: dict[str, NamedQuery] = {}
    blocks = re.split(r"^-- name:\s*", path.read_text(), flags=re.MULTILINE)[1:]
    for block in blocks:
        header, _, sql = block.partition("\n")
        key, _, title = header.partition("|")
        queries[key.strip()] = NamedQuery(key.strip(), title.strip() or key.strip(), sql.strip())
    return queries


def query_parameters(config: Config) -> dict[str, float]:
    """Values bound to the named-query parameters."""
    return {
        "elevated_score": config.credit_score.categories["moderate"],
        "high_utilisation": config.commentary.high_exposure_utilisation,
    }


def run_query(config: Config, key: str) -> pd.DataFrame:
    """Run one of the named queries against the risk database."""
    queries = load_named_queries()
    if key not in queries:
        raise DatabaseError(f"Unknown query '{key}'. Available: {sorted(queries)}")
    sql = queries[key].sql
    params = {k: v for k, v in query_parameters(config).items() if f":{k}" in sql}
    return run_sql(config.paths.database, sql, params)


def run_sql(path: Path, sql: str, params: dict[str, object] | None = None) -> pd.DataFrame:
    """Run a read-only SELECT statement and return the result as a DataFrame."""
    statement = sql.strip().rstrip(";")
    if not re.match(r"(?is)^\s*(select|with)\b", statement) or ";" in statement:
        raise DatabaseError("Only a single SELECT statement is allowed")
    if not path.exists():
        raise DatabaseError(f"Database not found: {path}. Run the pipeline first.")
    connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        return pd.read_sql_query(statement, connection, params=params or {})
    except (sqlite3.Error, pd.errors.DatabaseError) as exc:
        raise DatabaseError(f"Query failed: {exc}") from exc
    finally:
        connection.close()
