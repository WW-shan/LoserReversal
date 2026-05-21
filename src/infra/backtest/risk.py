"""Pure risk primitives for backtest metrics and sizing."""

from __future__ import annotations

import numpy as np
import pandas as pd


def max_drawdown(equity: pd.Series) -> float:
    """Return max peak-to-trough drawdown as a negative decimal."""
    clean = equity.astype("float64").dropna()
    if clean.empty:
        return 0.0

    peaks = clean.cummax()
    drawdowns = clean / peaks - 1.0
    return float(drawdowns.min())


def sharpe_ratio(returns: pd.Series, periods_per_year: int = 365, rf: float = 0.0) -> float:
    """Return annualized Sharpe ratio."""
    excess = _excess_returns(returns, periods_per_year, rf)
    if excess.empty:
        return 0.0

    volatility = excess.std(ddof=0)
    mean_return = excess.mean()
    if volatility == 0:
        return _zero_volatility_ratio(mean_return)

    return float(mean_return / volatility * np.sqrt(periods_per_year))


def sortino_ratio(returns: pd.Series, periods_per_year: int = 365, rf: float = 0.0) -> float:
    """Return annualized Sortino ratio using downside-only volatility."""
    excess = _excess_returns(returns, periods_per_year, rf)
    if excess.empty:
        return 0.0

    downside = np.minimum(excess.to_numpy(dtype="float64"), 0.0)
    downside_deviation = np.sqrt(np.mean(np.square(downside)))
    mean_return = excess.mean()
    if downside_deviation == 0:
        return _zero_volatility_ratio(mean_return)

    return float(mean_return / downside_deviation * np.sqrt(periods_per_year))


def kelly_fraction(win_rate: float, avg_win: float, avg_loss: float) -> float:
    """Return optimal Kelly fraction, or zero for non-positive EV."""
    if avg_win <= 0 or avg_loss <= 0:
        return 0.0

    loss_rate = 1.0 - win_rate
    expected_value = win_rate * avg_win - loss_rate * avg_loss
    if expected_value <= 0:
        return 0.0

    win_loss_ratio = avg_win / avg_loss
    return float((win_loss_ratio * win_rate - loss_rate) / win_loss_ratio)


def fixed_fractional_size(equity: float, risk_per_trade: float, stop_distance_pct: float) -> float:
    """Return USD position size for fixed-fractional risk sizing."""
    if stop_distance_pct <= 0:
        raise ValueError("stop_distance_pct must be positive")
    if risk_per_trade < 0:
        raise ValueError("risk_per_trade must be non-negative")

    return float(equity * risk_per_trade / stop_distance_pct)


def _excess_returns(returns: pd.Series, periods_per_year: int, rf: float) -> pd.Series:
    return returns.astype("float64").dropna() - rf / periods_per_year


def _zero_volatility_ratio(mean_return: float) -> float:
    if mean_return > 0:
        return float("inf")
    if mean_return < 0:
        return float("-inf")
    return 0.0
