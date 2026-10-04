"""Regenerate the synthetic counterparties, trades and financials CSV files.

    python scripts/generate_data.py

Uses the seed in config/config.toml and the latest market date / USD/INR spot.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ccr.config import load_config  # noqa: E402
from ccr.data_generation import write_dataset  # noqa: E402
from ccr.market_data import load_market_data  # noqa: E402


def main() -> None:
    cfg = load_config()
    levels = load_market_data(cfg.paths.market_data)
    write_dataset(
        cfg.paths.counterparties, cfg.paths.trades, cfg.paths.financials,
        seed=cfg.random_seed, as_of=levels.index[-1], usdinr=float(levels["USDINR"].iloc[-1]),
    )
    print(f"Dataset written to {cfg.paths.trades.parent} (seed {cfg.random_seed}, as of {levels.index[-1].date()})")


if __name__ == "__main__":
    main()
