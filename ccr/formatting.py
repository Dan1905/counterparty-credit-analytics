"""Number formatting shared by the commentary, dashboard and Excel report."""

from __future__ import annotations

import math

CURRENCY_SYMBOLS: dict[str, str] = {"INR": "₹", "USD": "$", "EUR": "€", "GBP": "£"}


def money(value: float, currency: str = "INR", decimals: int = 1) -> str:
    """Format an amount in millions, e.g. 57_000_000 -> '₹57.0M'."""
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return "n/a"
    symbol = CURRENCY_SYMBOLS.get(currency, f"{currency} ")
    sign = "-" if value < 0 else ""
    return f"{sign}{symbol}{abs(value) / 1e6:,.{decimals}f}M"


def percent(value: float, decimals: int = 0) -> str:
    """Format a ratio as a percentage, e.g. 1.14 -> '114%'."""
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return "n/a"
    return f"{value * 100:,.{decimals}f}%"


def multiple(value: float, decimals: int = 2) -> str:
    """Format a ratio as a multiple, e.g. 3.456 -> '3.46x'."""
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return "n/a"
    if math.isinf(value):
        return "n/m"
    return f"{value:,.{decimals}f}x"
