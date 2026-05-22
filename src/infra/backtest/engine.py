"""Thin vectorbt portfolio wrapper for generated strategy signals."""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd
import vectorbt as vbt

from infra.backtest.risk import max_drawdown, sharpe_ratio, sortino_ratio


INTERVAL_TABLE: dict[str, tuple[int, pd.Timedelta]] = {
    "1m": (525600, pd.Timedelta(minutes=1)),
    "5m": (105120, pd.Timedelta(minutes=5)),
    "1h": (8760, pd.Timedelta(hours=1)),
    "1d": (365, pd.Timedelta(days=1)),
    "1D": (365, pd.Timedelta(days=1)),
    "1w": (52, pd.Timedelta(weeks=1)),
    "1W": (52, pd.Timedelta(weeks=1)),
    "1M": (12, pd.Timedelta(days=365) / 12),
    "ME": (12, pd.Timedelta(days=365) / 12),
    "1Y": (1, pd.Timedelta(days=365)),
    "YE": (1, pd.Timedelta(days=365)),
}


@dataclass
class BacktestConfig:
    init_cash: float = 10_000.0
    fees: float = 0.0005
    slippage: float = 0.0002
    freq: str = "1D"
    direction: str = "longonly"


@dataclass
class BacktestResult:
    portfolio: object
    stats: dict
    equity: pd.Series


def run_backtest(
    prices: pd.Series,
    entries: pd.Series,
    exits: pd.Series,
    config: BacktestConfig | None = None,
) -> BacktestResult:
    """Run vectorbt portfolio simulation and compute local risk metrics."""
    config = config or BacktestConfig()
    close = prices.astype("float64").sort_index()
    entry_signals = _align_bool_signals(entries, close.index)
    exit_signals = _align_bool_signals(exits, close.index)

    portfolio = vbt.Portfolio.from_signals(
        close=close,
        entries=entry_signals,
        exits=exit_signals,
        init_cash=config.init_cash,
        fees=config.fees,
        slippage=config.slippage,
        freq=config.freq,
        direction=config.direction,
    )
    equity = portfolio.value().astype("float64")
    returns = equity.pct_change().dropna()
    n_trades = int(portfolio.trades.count())

    stats = {
        "sharpe": sharpe_ratio(returns, periods_per_year(config.freq)),
        "sortino": sortino_ratio(returns, periods_per_year(config.freq)),
        "max_dd": max_drawdown(equity),
        "total_return": float(equity.iloc[-1] / config.init_cash - 1.0) if not equity.empty else 0.0,
        "win_rate": float(portfolio.trades.win_rate()) if n_trades else 0.0,
        "n_trades": n_trades,
    }
    return BacktestResult(portfolio=portfolio, stats=stats, equity=equity)


def _align_bool_signals(signals: pd.Series, index: pd.Index) -> pd.Series:
    return signals.reindex(index).fillna(False).astype(bool)


def periods_per_year(freq: str) -> int:
    if freq in INTERVAL_TABLE:
        return INTERVAL_TABLE[freq][0]

    offset = pd.tseries.frequencies.to_offset(freq)
    one_year = pd.Timedelta(days=365)
    return max(int(one_year / pd.Timedelta(offset.nanos, unit="ns")), 1)
