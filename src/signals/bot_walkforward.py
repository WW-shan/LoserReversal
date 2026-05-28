"""Walk-forward backtest for Phase 4 bot cluster reverse signal.

Takes a signal frame (``timestamp``, ``coin``, ``direction``, ``entry``, ``exit``)
produced by ``bot_reverse.cluster_signal.cluster_bot_signal`` and replays the
entry/exit events against 1h candle data per coin. Each entry is paired with
the next exit in the same (coin, direction) channel; intervening events of the
same channel are ignored (state machine invariant from cluster_signal).

Returns per-trade returns + walkforward-fold Sharpe + aggregate verdict.

Walk-forward splits use the same expanding/rolling utility as Phase 1.5
(``infra.backtest.walkforward.walk_forward_splits``). With sparse signals
(common for bot cluster signal on small wallet pools), a fold may have
zero trades; aggregate Sharpe averages only folds with trades.

Pass / Kill thresholds (per ROADMAP §660 + 2026-05-27 smart-search):
- GREEN: aggregate OOS Sharpe >= 1.5 AND n_trades >= 100
- YELLOW: Sharpe in [0.5, 1.5) AND n_trades >= 50
- RED: Sharpe < 0.5 OR n_trades < 30
- INCONCLUSIVE: n_trades < 30 (CLT floor per smart-search 01-funding-sample-size)
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timezone

import numpy as np
import pandas as pd

from infra.backtest.walkforward import walk_forward_splits


REQUIRED_COLUMNS: tuple[str, ...] = (
    "timestamp",
    "coin",
    "direction",
    "entry",
    "exit",
)


@dataclass(frozen=True)
class BotBacktestConfig:
    fees: float = 0.0005
    slippage: float = 0.0002
    hold_hours: int = 24

    def __post_init__(self) -> None:
        if self.fees < 0:
            raise ValueError(f"fees must be non-negative; got {self.fees!r}")
        if self.slippage < 0:
            raise ValueError(f"slippage must be non-negative; got {self.slippage!r}")
        if type(self.hold_hours) is not int or self.hold_hours <= 0:
            raise ValueError(
                f"hold_hours must be a positive int; got {self.hold_hours!r}"
            )


@dataclass(frozen=True)
class BotWalkforwardConfig:
    n_splits: int = 3
    mode: str = "expanding"
    min_train_days: int = 30
    test_days: int = 15

    def __post_init__(self) -> None:
        if self.n_splits < 1:
            raise ValueError(f"n_splits must be >= 1; got {self.n_splits!r}")
        if self.mode not in {"expanding", "rolling"}:
            raise ValueError(f"mode must be expanding|rolling; got {self.mode!r}")
        if self.min_train_days < 1:
            raise ValueError(
                f"min_train_days must be >= 1; got {self.min_train_days!r}"
            )
        if self.test_days < 1:
            raise ValueError(f"test_days must be >= 1; got {self.test_days!r}")


def validate_signal_frame(signal_df: pd.DataFrame) -> None:
    """Verify the signal frame matches the cluster_bot_signal output schema."""
    missing = [c for c in REQUIRED_COLUMNS if c not in signal_df.columns]
    if missing:
        raise ValueError(
            f"signal_df missing required columns {missing!r}; expected {REQUIRED_COLUMNS!r}"
        )


def backtest_bot_signal(
    signal_df: pd.DataFrame,
    candles_by_coin: dict[str, pd.DataFrame],
    *,
    config: BotBacktestConfig | None = None,
) -> pd.DataFrame:
    """Return per-trade frame with entry/exit timestamps, prices, and return.

    Trades are formed by pairing entry=True with the next exit=True in the
    same (coin, direction) channel after the entry timestamp. Entries with no
    matching exit are dropped (incomplete trades). Returns are net of fees on
    both sides and per-side slippage.
    """
    validate_signal_frame(signal_df)
    config = config or BotBacktestConfig()

    if signal_df.empty:
        return _empty_trade_frame()

    trade_rows: list[dict[str, object]] = []
    for (coin, direction), group in signal_df.groupby(["coin", "direction"], sort=False):
        candles = candles_by_coin.get(coin)
        if candles is None or candles.empty:
            continue
        trade_rows.extend(
            _pair_trades_for_channel(
                group=group.sort_values("timestamp"),
                candles=candles,
                coin=str(coin),
                direction=str(direction),
                config=config,
            )
        )

    if not trade_rows:
        return _empty_trade_frame()

    frame = pd.DataFrame(trade_rows)
    frame["entry_timestamp"] = pd.to_datetime(frame["entry_timestamp"], utc=True)
    frame["exit_timestamp"] = pd.to_datetime(frame["exit_timestamp"], utc=True)
    return frame.sort_values("entry_timestamp").reset_index(drop=True)


def aggregate_trade_stats(trades: pd.DataFrame) -> dict[str, float | int]:
    """Aggregate stats over a trade frame: n_trades, mean_return, Sharpe, MaxDD, win_rate."""
    if trades.empty:
        return {
            "n_trades": 0,
            "mean_return": float("nan"),
            "sharpe": float("nan"),
            "max_drawdown": float("nan"),
            "win_rate": float("nan"),
            "total_return": float("nan"),
        }
    returns = trades["pct_return"].to_numpy()
    n = len(returns)
    mean = float(np.mean(returns))
    std = float(np.std(returns, ddof=0))
    sharpe = float(mean / std * np.sqrt(_trades_per_year(trades))) if std > 0 else float("nan")
    win_rate = float((returns > 0).mean())
    # equity curve from compounded returns
    equity = np.cumprod(1.0 + returns)
    peak = np.maximum.accumulate(equity)
    drawdown = (equity - peak) / peak
    max_dd = float(np.min(drawdown))
    total_ret = float(equity[-1] - 1.0)
    return {
        "n_trades": int(n),
        "mean_return": mean,
        "sharpe": sharpe,
        "max_drawdown": max_dd,
        "win_rate": win_rate,
        "total_return": total_ret,
    }


def run_walkforward(
    signal_df: pd.DataFrame,
    candles_by_coin: dict[str, pd.DataFrame],
    *,
    backtest_config: BotBacktestConfig | None = None,
    walkforward_config: BotWalkforwardConfig | None = None,
) -> dict[str, object]:
    """Run walk-forward over the signal frame, returning per-fold + aggregate stats."""
    validate_signal_frame(signal_df)
    walkforward_config = walkforward_config or BotWalkforwardConfig()
    trades = backtest_bot_signal(
        signal_df=signal_df,
        candles_by_coin=candles_by_coin,
        config=backtest_config,
    )
    if trades.empty:
        return {
            "fold_stats": [],
            "aggregate": aggregate_trade_stats(trades),
            "all_trades": trades,
            "oos_trades": trades,
            "verdict": "RED",
            "verdict_reason": "no trades formed from signal frame",
        }

    span_start = pd.Timestamp(trades["entry_timestamp"].min()).to_pydatetime()
    span_end = pd.Timestamp(trades["entry_timestamp"].max()).to_pydatetime()
    if span_end.tzinfo is None:
        span_end = span_end.replace(tzinfo=timezone.utc)
    if span_start.tzinfo is None:
        span_start = span_start.replace(tzinfo=timezone.utc)

    try:
        splits = walk_forward_splits(
            start=span_start,
            end=span_end + pd.Timedelta(hours=1),
            n_splits=walkforward_config.n_splits,
            mode=walkforward_config.mode,
            min_train_days=walkforward_config.min_train_days,
            test_days=walkforward_config.test_days,
        )
    except ValueError as exc:
        # Span too short for requested split count. There is no OOS window,
        # so the aggregate must reflect zero OOS trades (NOT all trades —
        # spec rule "OOS-only aggregate" applies even when no fold runs).
        empty = trades.iloc[0:0]
        return {
            "fold_stats": [],
            "aggregate": aggregate_trade_stats(empty),
            "all_trades": trades,
            "oos_trades": empty,
            "verdict": "INCONCLUSIVE",
            "verdict_reason": f"walk-forward span too short: {exc}",
        }

    fold_stats: list[dict[str, object]] = []
    fold_sharpes: list[float] = []
    oos_trade_indices: list[int] = []
    for idx, ((_, _), (test_start, test_end)) in enumerate(splits):
        test_start_ts = _coerce_utc(test_start)
        test_end_ts = _coerce_utc(test_end)
        mask = (
            (trades["entry_timestamp"] >= test_start_ts)
            & (trades["entry_timestamp"] < test_end_ts)
        )
        fold_trades = trades[mask]
        oos_trade_indices.extend(fold_trades.index.tolist())
        stats = aggregate_trade_stats(fold_trades)
        fold_stats.append(
            {
                "split_idx": idx,
                "test_start": test_start_ts,
                "test_end": test_end_ts,
                **stats,
            }
        )
        if not np.isnan(stats["sharpe"]) and stats["n_trades"] > 0:
            fold_sharpes.append(stats["sharpe"])

    # OOS-only aggregate (excludes train-window trades).
    oos_trades = trades.loc[sorted(set(oos_trade_indices))] if oos_trade_indices else trades.iloc[0:0]
    aggregate = aggregate_trade_stats(oos_trades)
    if fold_sharpes:
        aggregate = {**aggregate, "mean_fold_sharpe": float(np.mean(fold_sharpes))}
    else:
        aggregate = {**aggregate, "mean_fold_sharpe": float("nan")}

    verdict, reason = classify_verdict(aggregate)
    return {
        "fold_stats": fold_stats,
        "aggregate": aggregate,
        "all_trades": trades,
        "oos_trades": oos_trades,
        "verdict": verdict,
        "verdict_reason": reason,
    }


def classify_verdict(aggregate: dict[str, float | int]) -> tuple[str, str]:
    """Map aggregate stats to GREEN / YELLOW / RED / INCONCLUSIVE."""
    n = int(aggregate.get("n_trades", 0))
    sharpe = float(aggregate.get("sharpe", float("nan")))
    if n < 30:
        return "INCONCLUSIVE", f"n_trades={n} below CLT floor of 30"
    if np.isnan(sharpe):
        return "RED", "sharpe is undefined"
    if sharpe >= 1.5 and n >= 100:
        return "GREEN", f"sharpe={sharpe:.2f} >=1.5 and n={n} >=100"
    if 0.5 <= sharpe < 1.5 and n >= 50:
        return "YELLOW", f"sharpe={sharpe:.2f} in [0.5, 1.5) and n={n} >=50"
    if sharpe < 0.5:
        return "RED", f"sharpe={sharpe:.2f} < 0.5"
    return "RED", f"sharpe={sharpe:.2f} above 0.5 but n={n} below YELLOW floor 50"


def _pair_trades_for_channel(
    *,
    group: pd.DataFrame,
    candles: pd.DataFrame,
    coin: str,
    direction: str,
    config: BotBacktestConfig,
) -> list[dict[str, object]]:
    """Pair entry=True with next exit=True for a single (coin, direction) channel."""
    rows: list[dict[str, object]] = []
    active_entry_ts: pd.Timestamp | None = None
    for _, row in group.iterrows():
        entry_flag = _safe_bool(row["entry"])
        exit_flag = _safe_bool(row["exit"])
        if entry_flag and active_entry_ts is None:
            active_entry_ts = _coerce_utc(row["timestamp"])
        elif exit_flag and active_entry_ts is not None:
            exit_ts = _coerce_utc(row["timestamp"])
            entry_px = _price_at(candles, active_entry_ts)
            exit_px = _price_at(candles, exit_ts)
            if entry_px is None or exit_px is None:
                active_entry_ts = None
                continue
            pct_return = _trade_return(
                entry_px=entry_px,
                exit_px=exit_px,
                direction=direction,
                fees=config.fees,
                slippage=config.slippage,
            )
            rows.append(
                {
                    "coin": coin,
                    "direction": direction,
                    "entry_timestamp": active_entry_ts,
                    "exit_timestamp": exit_ts,
                    "entry_px": float(entry_px),
                    "exit_px": float(exit_px),
                    "pct_return": float(pct_return),
                    "hold_hours": float(
                        (exit_ts - active_entry_ts).total_seconds() / 3600.0
                    ),
                }
            )
            active_entry_ts = None
    return rows


def _price_at(
    candles: pd.DataFrame,
    ts: pd.Timestamp,
    *,
    max_gap_hours: float | None = 26.0,
) -> float | None:
    """Look up close price at or immediately after timestamp ts.

    Returns None when the next candle is more than ``max_gap_hours`` after
    ``ts``. This guards against the R1 wallet-walkforward finding where
    trades from February were priced against a May candle (88-day gap).
    Set ``max_gap_hours=None`` to disable the guard (legacy behavior).
    """
    if candles.empty:
        return None
    index = candles.index
    if not isinstance(index, pd.DatetimeIndex):
        # candles may carry a timestamp column instead
        if "timestamp" not in candles.columns:
            return None
        candles = candles.set_index(pd.DatetimeIndex(candles["timestamp"]))
        index = candles.index
    if index.tz is None:
        index = index.tz_localize("UTC")
        candles = candles.set_index(index)
    pos = index.searchsorted(ts, side="left")
    if pos >= len(index):
        return None
    bar_ts = index[pos]
    if max_gap_hours is not None:
        gap = (bar_ts - ts).total_seconds() / 3600.0
        if gap > max_gap_hours:
            return None
    close_col = "close" if "close" in candles.columns else candles.columns[0]
    return float(candles.iloc[pos][close_col])


def _trade_return(
    *,
    entry_px: float,
    exit_px: float,
    direction: str,
    fees: float,
    slippage: float,
) -> float:
    """Compute return net of round-trip fees and per-side slippage."""
    if direction == "long":
        # buy at entry (slip up), sell at exit (slip down)
        eff_entry = entry_px * (1.0 + slippage)
        eff_exit = exit_px * (1.0 - slippage)
        gross = (eff_exit - eff_entry) / eff_entry
    elif direction == "short":
        # sell at entry (slip down), buy at exit (slip up)
        eff_entry = entry_px * (1.0 - slippage)
        eff_exit = exit_px * (1.0 + slippage)
        gross = (eff_entry - eff_exit) / eff_entry
    else:
        raise ValueError(f"unknown direction {direction!r}; expected long|short")
    return gross - 2.0 * fees


def _empty_trade_frame() -> pd.DataFrame:
    return pd.DataFrame(
        columns=[
            "coin",
            "direction",
            "entry_timestamp",
            "exit_timestamp",
            "entry_px",
            "exit_px",
            "pct_return",
            "hold_hours",
        ]
    )


def _coerce_utc(value: object) -> pd.Timestamp:
    """Return a UTC-aware Timestamp regardless of input tz state."""
    ts = pd.Timestamp(value)
    if ts.tzinfo is None:
        return ts.tz_localize("UTC")
    return ts.tz_convert("UTC")


def _safe_bool(value: object) -> bool:
    """Coerce a value to bool, treating NaN/None/<NA> as False (fail closed).

    Per R1 finding (C1): ``bool(np.nan) is True`` would silently fire the
    state machine on NaN entries. Coerce via ``pd.notna`` first to avoid
    that landmine.
    """
    if value is None:
        return False
    try:
        if pd.isna(value):
            return False
    except (TypeError, ValueError):
        pass
    return bool(value)


def _trades_per_year(trades: pd.DataFrame) -> float:
    """Estimate trades-per-year from observed cadence, with fallback to 12.0."""
    if len(trades) < 2:
        return 12.0
    span = (trades["exit_timestamp"].max() - trades["entry_timestamp"].min())
    days = max(span.total_seconds() / 86400.0, 1.0)
    return float(len(trades) * 365.0 / days)
