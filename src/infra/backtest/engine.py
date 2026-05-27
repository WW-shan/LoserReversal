"""Thin vectorbt portfolio wrapper for generated strategy signals."""

from __future__ import annotations

import warnings
from dataclasses import dataclass

import numpy as np
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


STOP_LOSS_MODES: tuple[str, ...] = ("fixed", "atr")


@dataclass
class BacktestConfig:
    init_cash: float = 10_000.0
    fees: float = 0.0005
    slippage: float = 0.0002
    freq: str = "1D"
    direction: str = "longonly"
    stop_loss: float | None = None
    stop_loss_mode: str = "fixed"
    stop_loss_atr_period: int = 14
    stop_loss_atr_multiplier: float = 2.0
    stop_loss_floor: float = 0.08
    stop_loss_cap: float = 0.25
    high: pd.Series | None = None
    low: pd.Series | None = None


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
    if config.stop_loss_mode not in STOP_LOSS_MODES:
        raise ValueError(
            f"unsupported stop_loss_mode={config.stop_loss_mode!r}; "
            f"expected one of {STOP_LOSS_MODES}"
        )
    close = prices.astype("float64").sort_index()
    entry_signals = _align_bool_signals(entries, close.index)
    exit_signals = _align_bool_signals(exits, close.index)

    portfolio_kwargs: dict[str, object] = {
        "close": close,
        "entries": entry_signals,
        "exits": exit_signals,
        "init_cash": config.init_cash,
        "fees": config.fees,
        "slippage": config.slippage,
        "freq": config.freq,
        "direction": config.direction,
    }
    stop_array_or_scalar = _build_stop_loss(close, config)
    if stop_array_or_scalar is not None:
        portfolio_kwargs["sl_stop"] = stop_array_or_scalar

    portfolio = vbt.Portfolio.from_signals(**portfolio_kwargs)
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


def _build_stop_loss(close: pd.Series, config: BacktestConfig) -> float | pd.Series | None:
    """Materialise the stop-loss argument passed to vbt.

    Returns a scalar (legacy fixed mode) or a per-bar Series (ATR mode), or
    ``None`` when no stop should apply. ATR mode uses OHLC true range when
    high/low series are available, otherwise it falls back to a close-only
    proxy. The resulting per-bar sl_stop is clipped to
    ``[stop_loss_floor, stop_loss_cap]``.
    """
    if config.stop_loss_mode == "fixed":
        if config.stop_loss is None:
            return None
        return float(config.stop_loss)

    # ATR mode: build a per-bar fraction-of-close stop array.
    sl_stop = _atr_stop_series(
        close,
        high=config.high,
        low=config.low,
        period=int(config.stop_loss_atr_period),
        multiplier=float(config.stop_loss_atr_multiplier),
        floor=float(config.stop_loss_floor),
        cap=float(config.stop_loss_cap),
    )
    return sl_stop


def _atr_stop_series(
    close: pd.Series,
    *,
    high: pd.Series | None = None,
    low: pd.Series | None = None,
    period: int,
    multiplier: float,
    floor: float,
    cap: float,
) -> pd.Series:
    """Compute the per-bar ATR-fraction stop loss series.

    True Range uses high/low/previous-close when high and low series are
    provided. If OHLC is unavailable, a close-only ``|close.diff()|`` proxy is
    used. ATR is Wilder's RMA in both paths.
    """
    if period < 1:
        raise ValueError(f"stop_loss_atr_period must be >= 1, got {period}")
    if multiplier <= 0:
        raise ValueError(f"stop_loss_atr_multiplier must be > 0, got {multiplier}")
    if floor < 0:
        raise ValueError(f"stop_loss_floor must be >= 0, got {floor}")
    if cap <= 0 or cap < floor:
        raise ValueError(
            f"stop_loss_cap must be > 0 and >= floor (got cap={cap}, floor={floor})"
        )

    close_arr = close.astype("float64").to_numpy()
    if close_arr.size == 0:
        return pd.Series(dtype="float64", index=close.index, name="sl_stop")

    high_arr: np.ndarray | None = None
    low_arr: np.ndarray | None = None
    if high is not None and low is not None:
        high_aligned = high.astype("float64").reindex(close.index)
        low_aligned = low.astype("float64").reindex(close.index)
        if not high_aligned.isna().any() and not low_aligned.isna().any():
            high_arr = high_aligned.to_numpy()
            low_arr = low_aligned.to_numpy()

    atr = pd.Series(
        _compute_atr(close_arr, period, high=high_arr, low=low_arr),
        index=close.index,
        dtype="float64",
    )
    # fraction-of-close stop; guard against zero close before division.
    safe_close = pd.Series(close_arr, index=close.index, dtype="float64").replace(0.0, np.nan)
    fraction = (multiplier * atr / safe_close).bfill().ffill().fillna(floor)
    clipped = fraction.clip(lower=floor, upper=cap)
    return clipped.rename("sl_stop")


def _compute_atr(
    close: np.ndarray,
    period: int,
    *,
    high: np.ndarray | None = None,
    low: np.ndarray | None = None,
) -> np.ndarray:
    if period < 1:
        raise ValueError(f"period must be >= 1, got {period}")
    close_arr = np.asarray(close, dtype="float64")
    if close_arr.size == 0:
        return np.array([], dtype="float64")
    if high is not None and low is not None and len(high) == len(close_arr) == len(low):
        high_arr = np.asarray(high, dtype="float64")
        low_arr = np.asarray(low, dtype="float64")
        prev_close = np.concatenate(([close_arr[0]], close_arr[:-1]))
        true_range = np.maximum.reduce(
            [
                high_arr - low_arr,
                np.abs(high_arr - prev_close),
                np.abs(low_arr - prev_close),
            ]
        )
        return (
            pd.Series(true_range, dtype="float64")
            .ewm(alpha=1.0 / period, adjust=False)
            .mean()
            .to_numpy()
        )

    warnings.warn(
        "ATR using close-only proxy (no high/low provided); systematic underestimate of true range",
        UserWarning,
        stacklevel=2,
    )
    true_range = np.abs(np.diff(close_arr, prepend=close_arr[0]))
    return (
        pd.Series(true_range, dtype="float64")
        .ewm(alpha=1.0 / period, adjust=False)
        .mean()
        .to_numpy()
    )


def _align_bool_signals(signals: pd.Series, index: pd.Index) -> pd.Series:
    return signals.reindex(index).fillna(False).astype(bool)


def periods_per_year(freq: str) -> int:
    if freq in INTERVAL_TABLE:
        return INTERVAL_TABLE[freq][0]

    offset = pd.tseries.frequencies.to_offset(freq)
    one_year = pd.Timedelta(days=365)
    return max(int(one_year / pd.Timedelta(offset.nanos, unit="ns")), 1)
