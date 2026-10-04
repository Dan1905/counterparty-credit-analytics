"""Download historical market data (NIFTY 50, USD/INR, 10Y yield) to ``data/market``.

Usage::

    python scripts/fetch_market_data.py            # download from Yahoo Finance
    python scripts/fetch_market_data.py --synthetic  # offline: simulated history

If the download fails the script falls back to simulated data and says so; the
source is recorded in ``market_data.meta.json`` and shown in the dashboard.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ccr.config import load_config  # noqa: E402
from ccr.logging_setup import configure_logging  # noqa: E402
from ccr.market_data import (  # noqa: E402
    MarketDataError,
    fetch_market_data,
    generate_synthetic_market_data,
    save_market_data,
)

logger = logging.getLogger("fetch_market_data")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--synthetic", action="store_true", help="skip the download")
    parser.add_argument("--years", type=int, default=5, help="years of history to request")
    args = parser.parse_args()

    cfg = load_config()
    configure_logging(cfg.paths.log_file)

    if args.synthetic:
        levels, source = generate_synthetic_market_data(seed=cfg.random_seed), "synthetic"
    else:
        try:
            levels, source = fetch_market_data(args.years), "Yahoo Finance"
        except MarketDataError as exc:
            logger.warning("Download failed (%s); falling back to synthetic data", exc)
            levels, source = generate_synthetic_market_data(seed=cfg.random_seed), "synthetic"

    save_market_data(levels, cfg.paths.market_data, source)
    print(f"{len(levels)} observations from {source}: "
          f"{levels.index.min().date()} to {levels.index.max().date()}")
    print(levels.tail(3).round(4).to_string())


if __name__ == "__main__":
    main()
