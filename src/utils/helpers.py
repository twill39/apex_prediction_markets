"""General utility functions"""

from typing import Optional


def format_currency(amount: float, currency: str = "USD") -> str:
    """Format currency amount"""
    if currency == "USD":
        return f"${amount:,.2f}"
    return f"{amount:,.2f} {currency}"


def calculate_percentage(value: float, total: float) -> float:
    """Calculate percentage"""
    if total == 0:
        return 0.0
    return (value / total) * 100.0


def safe_divide(numerator: float, denominator: float, default: float = 0.0) -> float:
    """Safely divide two numbers, returning default if denominator is zero"""
    if denominator == 0:
        return default
    return numerator / denominator
