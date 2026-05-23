from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Any

import pandas as pd

from infra.backtest.engine import BacktestConfig, periods_per_year, run_backtest
from infra.backtest.risk import max_drawdown, sharpe_ratio, sortino_ratio
from signals.unlock_v1 import unlock_short_signal
from signals.unlock_v2 import unlock_short_30d
from signals.unlock_v3 import unlock_short_tactical
from signals.unlock_v4 import unlock_short_72h
from signals.unlock_v5 import unlock_reversal_long


SignalFn = Callable[..., dict[str, tuple[pd.Series, pd.Series]]]


@dataclass(frozen=True)
class SignalSpec:
    signal_fn: SignalFn
    direction: str
    default_kwargs: dict[str, object]


@dataclass(frozen=True)
class GridCell:
    code: str
    min_unlock_pct: float
    cohort_name: str
    signal_fn: SignalFn
    direction: str
    category_filter: set[str] | None


@dataclass(frozen=True)
class PortfolioStats:
    n_trades: int
    win_rate: float
    sharpe: float
    sortino: float
    max_dd: float
    total_return: float
    mean_pnl: float
    median_pnl: float


SIGNAL_REGISTRY: dict[str, SignalSpec] = {
    "v1": SignalSpec(unlock_short_signal, "short", {}),
    "v2": SignalSpec(unlock_short_30d, "short", {}),
    "v3": SignalSpec(unlock_short_tactical, "short", {}),
    "v4": SignalSpec(unlock_short_72h, "short", {}),
    "v5": SignalSpec(unlock_reversal_long, "long", {}),
}
CATEGORY_COHORTS: dict[str, set[str] | None] = {
    "team": {"insiders"},
    "team+investor": {"insiders", "privateSale"},
    "all": None,
}
SIZE_THRESHOLDS: tuple[float, ...] = (0.01, 0.02, 0.05, 0.10)


def apply_category_filter(events: pd.DataFrame, category_filter: set[str] | None) -> pd.DataFrame:
    if category_filter is None:
        return events.copy()
    if events.empty or "category" not in events.columns:
        return events.iloc[0:0].copy()
    return events.loc[events["category"].isin(category_filter)].copy()


def iter_grid() -> Iterator[GridCell]:
    for code, spec in SIGNAL_REGISTRY.items():
        for min_unlock_pct in SIZE_THRESHOLDS:
            for cohort_name, category_filter in CATEGORY_COHORTS.items():
                yield GridCell(
                    code=code,
                    min_unlock_pct=min_unlock_pct,
                    cohort_name=cohort_name,
                    signal_fn=spec.signal_fn,
                    direction=spec.direction,
                    category_filter=category_filter,
                )


def run_cell(
    events: pd.DataFrame,
    prices: dict[str, pd.Series],
    coverage: pd.DataFrame,
    cell: GridCell,
    *,
    init_cash: float,
    fees: float,
    slippage: float,
) -> dict[str, Any]:
    filtered = apply_category_filter(events, cell.category_filter)
    signal_result = cell.signal_fn(
        filtered,
        prices,
        min_unlock_pct=cell.min_unlock_pct,
        coverage=coverage,
    )
    portfolio_stats = backtest_signals(
        prices,
        signal_result,
        cell.direction,
        init_cash=init_cash,
        fees=fees,
        slippage=slippage,
    )
    return {
        "signal": cell.code,
        "min_unlock_pct": cell.min_unlock_pct,
        "cohort": cell.cohort_name,
        "n_trades": portfolio_stats.n_trades,
        "win_rate": portfolio_stats.win_rate,
        "sharpe": portfolio_stats.sharpe,
        "sortino": portfolio_stats.sortino,
        "max_dd": portfolio_stats.max_dd,
        "total_return": portfolio_stats.total_return,
        "mean_pnl": portfolio_stats.mean_pnl,
        "median_pnl": portfolio_stats.median_pnl,
    }


def backtest_signals(
    prices: dict[str, pd.Series],
    signal_result: dict[str, tuple[pd.Series, pd.Series]],
    direction: str,
    *,
    init_cash: float,
    fees: float,
    slippage: float,
) -> PortfolioStats:
    config = BacktestConfig(
        init_cash=init_cash,
        fees=fees,
        slippage=slippage,
        freq="1D",
        direction=_vectorbt_direction(direction),
    )
    equities: list[pd.Series] = []
    pnl_values: list[float] = []
    n_trades = 0
    trades_won = 0.0

    for token, (entries, exits) in signal_result.items():
        close = prices.get(token)
        if close is None:
            continue

        result = run_backtest(close, entries, exits, config)
        token_trades = int(result.stats.get("n_trades", 0))
        token_win_rate = float(result.stats.get("win_rate", 0.0))
        n_trades += token_trades
        trades_won += token_win_rate * token_trades
        equities.append(result.equity.rename(token))
        pnl_values.extend(_trade_pnls(result.portfolio))

    equity = _summed_equity(equities, init_cash)
    pnl = pd.Series(pnl_values, dtype="float64")
    returns = equity.pct_change().dropna()
    equity_first = float(equity.iloc[0]) if not equity.empty else 0.0
    equity_final = float(equity.iloc[-1]) if not equity.empty else 0.0
    return PortfolioStats(
        n_trades=n_trades,
        win_rate=trades_won / n_trades if n_trades else 0.0,
        sharpe=sharpe_ratio(returns, periods_per_year("1D")),
        sortino=sortino_ratio(returns, periods_per_year("1D")),
        max_dd=max_drawdown(equity),
        total_return=equity_final / equity_first - 1.0 if equity_first else 0.0,
        mean_pnl=float(pnl.mean()) if not pnl.empty else 0.0,
        median_pnl=float(pnl.median()) if not pnl.empty else 0.0,
    )


def _vectorbt_direction(direction: str) -> str:
    if direction == "long":
        return "longonly"
    if direction == "short":
        return "shortonly"
    raise ValueError(f"unsupported direction: {direction}")


def _summed_equity(equities: list[pd.Series], init_cash: float) -> pd.Series:
    if not equities:
        return pd.Series(dtype="float64", name="equity")

    union_index = equities[0].index
    for equity in equities[1:]:
        union_index = union_index.union(equity.index)

    aligned = pd.concat(
        [equity.reindex(union_index).ffill().fillna(init_cash) for equity in equities],
        axis=1,
        sort=True,
    ).sort_index()
    return aligned.sum(axis=1).rename("equity")


def _trade_pnls(portfolio: object) -> list[float]:
    trades = getattr(portfolio, "trades", None)
    records = getattr(trades, "records_readable", pd.DataFrame())
    if not isinstance(records, pd.DataFrame) or "PnL" not in records.columns:
        return []
    return pd.to_numeric(records["PnL"], errors="coerce").dropna().astype("float64").tolist()
