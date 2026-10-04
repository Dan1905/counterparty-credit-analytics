"""Command-line entry point: run the full risk workflow.

    python run_pipeline.py                 # latest market date
    python run_pipeline.py --as-of 2026-09-15
    python run_pipeline.py --query limit_breaches
    python run_pipeline.py --list-queries
"""

from __future__ import annotations

import argparse
import sys

from ccr import database
from ccr.config import ConfigError, load_config
from ccr.formatting import money, percent
from ccr.logging_setup import configure_logging
from ccr.pipeline import run_pipeline


def main() -> int:
    parser = argparse.ArgumentParser(description="Counterparty Credit Risk & Exposure Analytics")
    parser.add_argument("--as-of", help="valuation date (YYYY-MM-DD); default = latest market date")
    parser.add_argument("--query", help="run a named SQL query against the risk database and exit")
    parser.add_argument("--list-queries", action="store_true", help="list the named SQL queries")
    args = parser.parse_args()

    try:
        config = load_config()
    except ConfigError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 2
    configure_logging(config.paths.log_file)

    if args.list_queries:
        for query in database.load_named_queries().values():
            print(f"{query.key:32s} {query.title}")
        return 0
    if args.query:
        try:
            print(database.run_query(config, args.query).to_string(index=False))
        except database.DatabaseError as exc:
            print(exc, file=sys.stderr)
            return 1
        return 0

    try:
        results = run_pipeline(config, args.as_of)
    except Exception as exc:  # report any failure clearly at the top level
        print(f"Risk run failed: {exc}", file=sys.stderr)
        return 1

    today = results.today
    ccy = config.base_currency
    print(f"\nRisk run complete - as of {today.as_of:%d %b %Y}")
    print(f"  Total current exposure : {money(today.portfolio['current_exposure'], ccy)}")
    print(f"  Total EE               : {money(today.portfolio['expected_exposure'], ccy)}")
    print(f"  Portfolio PFE 99%      : {money(today.portfolio.get('pfe_99', float('nan')), ccy)}")
    print(f"  Total Initial Margin   : {money(today.total_initial_margin, ccy)}")
    print(f"  Limit breaches/warnings: {today.breach_count} / {today.warning_count}\n")
    table = today.limits[["counterparty_id", "credit_limit", "net_exposure", "pfe", "utilisation", "status"]].copy()
    for column in ("credit_limit", "net_exposure", "pfe"):
        table[column] = table[column].map(lambda v: money(v, ccy))
    table["utilisation"] = table["utilisation"].map(percent)
    print(table.to_string(index=False))
    print(f"\nDatabase : {config.paths.database}\nExcel    : {config.paths.excel_report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
