"""Walk-forward validation for the funding-extreme contrarian signal."""

from __future__ import annotations

import math
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from typing import Any

import pandas as pd

try:
    from scripts.run_funding_extreme_backtest import BacktestConfig, execute_backtest
except ModuleNotFoundError:
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
    from run_funding_extreme_backtest import BacktestConfig, execute_backtest  # type: ignore[no-redef]


Z_THRESHOLDS = (1.5, 2.0, 2.5, 3.0)
HOLD_HOURS = (8, 24, 72, 168)
LOOKBACK_DAYS = (14, 30, 90)
DEFAULT_TRAIN_DAYS = 270
DEFAULT_TEST_DAYS = 180
DEFAULT_N_SPLITS = 5
DEFAULT_MIN_IS_TRADES = 5
DEFAULT_TAKER_FEE = 0.0005
DEFAULT_SLIPPAGE = 0.0002

WALKFORWARD_COLUMNS = [
    "split_idx",
    "is_start",
    "is_end",
    "oos_start",
    "oos_end",
    "z_threshold",
    "hold_hours",
    "lookback_days",
    "is_n_trades",
    "is_sharpe",
    "oos_n_trades",
    "oos_sharpe",
    "oos_annualized",
    "oos_max_dd",
    "oos_win_rate",
    "is_oos_decay",
]


@dataclass(frozen=True)
class Split:
    train_start: pd.Timestamp
    train_end: pd.Timestamp
    test_start: pd.Timestamp
    test_end: pd.Timestamp


@dataclass(frozen=True)
class GridCell:
    z_threshold: float
    hold_hours: int
    lookback_days: int


@dataclass(frozen=True)
class SplitOutcome:
    split_idx: int
    cell: GridCell | None
    is_sharpe: float
    is_n_trades: int
    oos_sharpe: float
    oos_n_trades: int
    oos_annualized: float
    oos_max_dd: float
    oos_win_rate: float


def iter_grid() -> Iterator[GridCell]:
    for z_threshold in Z_THRESHOLDS:
        for hold_hours in HOLD_HOURS:
            for lookback_days in LOOKBACK_DAYS:
                yield GridCell(
                    z_threshold=z_threshold,
                    hold_hours=hold_hours,
                    lookback_days=lookback_days,
                )


def build_expanding_splits(
    history_start: pd.Timestamp,
    history_end: pd.Timestamp,
    *,
    n_splits: int = DEFAULT_N_SPLITS,
    train_days: int = DEFAULT_TRAIN_DAYS,
    test_days: int = DEFAULT_TEST_DAYS,
) -> list[Split]:
    """Generate expanding-window splits over [history_start, history_end].

    Split k uses train [history_start, history_start + train_days + k*test_days)
    and test [train_end, train_end + test_days).
    """
    start = _utc_timestamp(history_start)
    end = _utc_timestamp(history_end)
    if end <= start:
        return []
    splits: list[Split] = []
    for k in range(n_splits):
        train_start = start
        train_end = start + pd.Timedelta(days=train_days + k * test_days)
        test_start = train_end
        test_end = test_start + pd.Timedelta(days=test_days)
        if test_end > end + pd.Timedelta(days=1):
            break
        splits.append(
            Split(
                train_start=train_start,
                train_end=train_end,
                test_start=test_start,
                test_end=test_end,
            )
        )
    return splits


def select_best_cell(
    funding_history: dict[str, pd.DataFrame],
    prices: dict[str, pd.Series],
    *,
    min_n_trades: int = DEFAULT_MIN_IS_TRADES,
    taker_fee: float = DEFAULT_TAKER_FEE,
    slippage: float = DEFAULT_SLIPPAGE,
) -> tuple[GridCell | None, float, int]:
    """Return (best_cell, sharpe, n_trades) over the loaded history.

    Falls back to the highest-trade-count cell when no cell hits min_n_trades.
    """
    best_cell: GridCell | None = None
    best_sharpe = float("-inf")
    best_trades = 0
    fallback_cell: GridCell | None = None
    fallback_trades = 0

    for cell in iter_grid():
        config = BacktestConfig(
            z_threshold=cell.z_threshold,
            hold_hours=cell.hold_hours,
            lookback_days=cell.lookback_days,
            taker_fee=taker_fee,
            slippage=slippage,
        )
        result = execute_backtest(funding_history, prices, config)
        agg = _aggregate_row(result.frame)
        if agg is None:
            continue
        n_trades = int(agg["n_trades"])
        sharpe = _finite(agg["sharpe"])
        if n_trades > fallback_trades:
            fallback_cell = cell
            fallback_trades = n_trades
        if n_trades >= min_n_trades and math.isfinite(sharpe) and sharpe > best_sharpe:
            best_cell = cell
            best_sharpe = sharpe
            best_trades = n_trades

    if best_cell is None:
        return fallback_cell, float("nan"), fallback_trades
    return best_cell, best_sharpe, best_trades


def run_oos(
    funding_history: dict[str, pd.DataFrame],
    prices: dict[str, pd.Series],
    cell: GridCell,
    *,
    taker_fee: float = DEFAULT_TAKER_FEE,
    slippage: float = DEFAULT_SLIPPAGE,
) -> dict[str, float | int]:
    config = BacktestConfig(
        z_threshold=cell.z_threshold,
        hold_hours=cell.hold_hours,
        lookback_days=cell.lookback_days,
        taker_fee=taker_fee,
        slippage=slippage,
    )
    result = execute_backtest(funding_history, prices, config)
    agg = _aggregate_row(result.frame)
    if agg is None:
        return {
            "n_trades": 0,
            "sharpe": float("nan"),
            "annualized_return": float("nan"),
            "max_dd": 0.0,
            "win_rate": 0.0,
        }
    return {
        "n_trades": int(agg["n_trades"]),
        "sharpe": _finite(agg["sharpe"]),
        "annualized_return": _finite(agg["annualized_return"]),
        "max_dd": float(agg["max_dd"]),
        "win_rate": float(agg["win_rate"]),
    }


def run_walkforward(
    funding_history: dict[str, pd.DataFrame],
    prices: dict[str, pd.Series],
    splits: Sequence[Split],
    *,
    min_n_trades: int = DEFAULT_MIN_IS_TRADES,
    taker_fee: float = DEFAULT_TAKER_FEE,
    slippage: float = DEFAULT_SLIPPAGE,
) -> pd.DataFrame:
    """Run an IS->OOS walk-forward and return per-split + AGGREGATE rows."""
    rows: list[dict[str, Any]] = []
    outcomes: list[SplitOutcome] = []

    for split_idx, split in enumerate(splits):
        train_funding, train_prices = _filter_window(
            funding_history, prices, split.train_start, split.train_end
        )
        test_funding, test_prices = _filter_window(
            funding_history, prices, split.test_start, split.test_end
        )

        best_cell, is_sharpe, is_n_trades = select_best_cell(
            train_funding,
            train_prices,
            min_n_trades=min_n_trades,
            taker_fee=taker_fee,
            slippage=slippage,
        )
        if best_cell is None:
            row = _empty_row(split_idx, split, None)
            rows.append(row)
            outcomes.append(
                SplitOutcome(
                    split_idx=split_idx,
                    cell=None,
                    is_sharpe=float("nan"),
                    is_n_trades=0,
                    oos_sharpe=float("nan"),
                    oos_n_trades=0,
                    oos_annualized=float("nan"),
                    oos_max_dd=0.0,
                    oos_win_rate=0.0,
                )
            )
            continue

        oos = run_oos(
            test_funding,
            test_prices,
            best_cell,
            taker_fee=taker_fee,
            slippage=slippage,
        )
        decay = _decay(is_sharpe, oos["sharpe"])

        rows.append(
            {
                "split_idx": split_idx,
                "is_start": split.train_start,
                "is_end": split.train_end,
                "oos_start": split.test_start,
                "oos_end": split.test_end,
                "z_threshold": float(best_cell.z_threshold),
                "hold_hours": int(best_cell.hold_hours),
                "lookback_days": int(best_cell.lookback_days),
                "is_n_trades": int(is_n_trades),
                "is_sharpe": float(is_sharpe),
                "oos_n_trades": int(oos["n_trades"]),
                "oos_sharpe": float(oos["sharpe"]),
                "oos_annualized": float(oos["annualized_return"]),
                "oos_max_dd": float(oos["max_dd"]),
                "oos_win_rate": float(oos["win_rate"]),
                "is_oos_decay": decay,
            }
        )
        outcomes.append(
            SplitOutcome(
                split_idx=split_idx,
                cell=best_cell,
                is_sharpe=float(is_sharpe),
                is_n_trades=int(is_n_trades),
                oos_sharpe=float(oos["sharpe"]),
                oos_n_trades=int(oos["n_trades"]),
                oos_annualized=float(oos["annualized_return"]),
                oos_max_dd=float(oos["max_dd"]),
                oos_win_rate=float(oos["win_rate"]),
            )
        )

    rows.append(_aggregate_summary(outcomes))
    return pd.DataFrame(rows, columns=WALKFORWARD_COLUMNS)


def verdict_from_aggregate(aggregate_row: pd.Series | dict) -> str:
    """Phase 3 reframed verdict per `blocker.md`.

    Returns INCONCLUSIVE when OOS trade count is below the minimum needed
    for the Sharpe estimate to mean anything (matches Phase 1.5's n_trades
    >= 30 threshold). This prevents misreading a data-gap RED as a strategy
    failure (which was what happened to Phase 1 v1).
    """
    n_trades = _finite(aggregate_row.get("oos_n_trades", 0))
    sharpe = _finite(aggregate_row.get("oos_sharpe", float("nan")))
    annualized = _finite(aggregate_row.get("oos_annualized", float("nan")))
    if n_trades < 30:
        return "INCONCLUSIVE"
    if not math.isfinite(sharpe) or not math.isfinite(annualized):
        return "RED"
    if sharpe >= 1.2 and annualized >= 0.20:
        return "GREEN"
    if sharpe >= 0.5 and annualized >= 0.10:
        return "YELLOW"
    return "RED"


def _filter_window(
    funding_history: dict[str, pd.DataFrame],
    prices: dict[str, pd.Series],
    start: pd.Timestamp,
    end: pd.Timestamp,
) -> tuple[dict[str, pd.DataFrame], dict[str, pd.Series]]:
    start_ts = _utc_timestamp(start)
    end_ts = _utc_timestamp(end)

    funding_out: dict[str, pd.DataFrame] = {}
    for token, frame in funding_history.items():
        sliced = frame.loc[(frame.index >= start_ts) & (frame.index < end_ts)]
        if not sliced.empty:
            funding_out[token] = sliced

    prices_out: dict[str, pd.Series] = {}
    for token, series in prices.items():
        sliced = series.loc[(series.index >= start_ts) & (series.index < end_ts)]
        if not sliced.empty:
            prices_out[token] = sliced

    return funding_out, prices_out


def _aggregate_row(frame: pd.DataFrame) -> pd.Series | None:
    if frame.empty:
        return None
    matches = frame.loc[frame["token"] == "AGGREGATE"]
    if matches.empty:
        return None
    return matches.iloc[0]


def _aggregate_summary(outcomes: Sequence[SplitOutcome]) -> dict[str, Any]:
    if not outcomes:
        return _empty_row(-1, None, None)

    valid = [outcome for outcome in outcomes if math.isfinite(outcome.oos_sharpe)]
    is_starts = [pd.NaT, pd.NaT]
    oos_starts = [pd.NaT, pd.NaT]
    total_is_trades = sum(outcome.is_n_trades for outcome in outcomes)
    total_oos_trades = sum(outcome.oos_n_trades for outcome in outcomes)

    if valid:
        oos_sharpe = float(
            sum(outcome.oos_sharpe for outcome in valid) / len(valid)
        )
        oos_ann = float(
            sum(outcome.oos_annualized for outcome in valid) / len(valid)
        )
        oos_max_dd = float(min(outcome.oos_max_dd for outcome in outcomes))
        is_sharpe_mean = float(
            sum(outcome.is_sharpe for outcome in valid) / len(valid)
        )
        win_rate = (
            sum(outcome.oos_win_rate * outcome.oos_n_trades for outcome in outcomes) /
            total_oos_trades
            if total_oos_trades
            else 0.0
        )
        decay = _decay(is_sharpe_mean, oos_sharpe)
    else:
        oos_sharpe = float("nan")
        oos_ann = float("nan")
        oos_max_dd = 0.0
        is_sharpe_mean = float("nan")
        win_rate = 0.0
        decay = float("nan")

    return {
        "split_idx": -1,
        "is_start": is_starts[0],
        "is_end": is_starts[1],
        "oos_start": oos_starts[0],
        "oos_end": oos_starts[1],
        "z_threshold": float("nan"),
        "hold_hours": -1,
        "lookback_days": -1,
        "is_n_trades": int(total_is_trades),
        "is_sharpe": is_sharpe_mean,
        "oos_n_trades": int(total_oos_trades),
        "oos_sharpe": oos_sharpe,
        "oos_annualized": oos_ann,
        "oos_max_dd": oos_max_dd,
        "oos_win_rate": float(win_rate),
        "is_oos_decay": decay,
    }


def _empty_row(split_idx: int, split: Split | None, _: Any) -> dict[str, Any]:
    return {
        "split_idx": split_idx,
        "is_start": split.train_start if split else pd.NaT,
        "is_end": split.train_end if split else pd.NaT,
        "oos_start": split.test_start if split else pd.NaT,
        "oos_end": split.test_end if split else pd.NaT,
        "z_threshold": float("nan"),
        "hold_hours": -1,
        "lookback_days": -1,
        "is_n_trades": 0,
        "is_sharpe": float("nan"),
        "oos_n_trades": 0,
        "oos_sharpe": float("nan"),
        "oos_annualized": float("nan"),
        "oos_max_dd": 0.0,
        "oos_win_rate": 0.0,
        "is_oos_decay": float("nan"),
    }


def _decay(is_sharpe: float, oos_sharpe: float) -> float:
    if not math.isfinite(is_sharpe) or not math.isfinite(oos_sharpe):
        return float("nan")
    if is_sharpe == 0:
        return float("nan")
    return float((is_sharpe - oos_sharpe) / abs(is_sharpe))


def _finite(value: Any) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return float("nan")
    if not math.isfinite(result):
        return float("nan")
    return result


def _utc_timestamp(value: pd.Timestamp | str) -> pd.Timestamp:
    ts = pd.Timestamp(value)
    if ts.tzinfo is None:
        return ts.tz_localize("UTC")
    return ts.tz_convert("UTC")
