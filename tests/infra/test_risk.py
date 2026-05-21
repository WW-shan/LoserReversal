"""Tests for backtest risk primitives."""

import numpy as np
import pandas as pd

from infra.backtest.risk import (
    fixed_fractional_size,
    kelly_fraction,
    max_drawdown,
    sharpe_ratio,
    sortino_ratio,
)


def test_max_drawdown_returns_peak_to_trough_loss():
    equity = pd.Series(
        [100.0, 120.0, 90.0, 110.0],
        index=pd.date_range("2026-01-01", periods=4, freq="1D", tz="UTC"),
    )

    assert max_drawdown(equity) == -0.25


def test_sharpe_ratio_preserves_return_sign():
    positive = pd.Series([0.01, 0.02, 0.015])
    negative = pd.Series([-0.01, -0.02, -0.015])

    assert sharpe_ratio(positive, periods_per_year=365) > 0
    assert sharpe_ratio(negative, periods_per_year=365) < 0


def test_sortino_ratio_uses_downside_volatility():
    returns = pd.Series([0.10, -0.04, 0.02, -0.02])
    downside = np.sqrt(np.mean(np.square([0.0, -0.04, 0.0, -0.02])))
    expected = returns.mean() / downside

    assert sortino_ratio(returns, periods_per_year=1) == expected


def test_kelly_fraction_returns_positive_for_positive_ev():
    assert kelly_fraction(win_rate=0.55, avg_win=0.04, avg_loss=0.02) > 0


def test_kelly_fraction_returns_zero_for_negative_ev():
    assert kelly_fraction(win_rate=0.40, avg_win=0.02, avg_loss=0.03) == 0.0


def test_fixed_fractional_size_returns_dollar_position_size():
    assert fixed_fractional_size(equity=10_000, risk_per_trade=0.01, stop_distance_pct=0.05) == 2000
