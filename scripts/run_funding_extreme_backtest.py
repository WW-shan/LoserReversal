"""Run a single funding-extreme contrarian backtest configuration."""

from __future__ import annotations

import argparse
import logging
import math
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from infra.backtest.engine import periods_per_year
from infra.backtest.risk import max_drawdown, sharpe_ratio
from infra.storage import PARQUET_DIR, read_candles, read_funding
from signals.funding_extreme_v1 import funding_extreme_signal


DEFAULT_FUNDING_DIR = PARQUET_DIR / "funding"
DEFAULT_CANDLES_DIR = PARQUET_DIR / "candles"
DEFAULT_OUT = PARQUET_DIR / "funding_extreme_backtest.parquet"
BASE_CAPITAL = 10_000.0
OUTPUT_COLUMNS = [
    "token",
    "z_threshold",
    "hold_hours",
    "lookback_days",
    "n_trades",
    "n_long",
    "n_short",
    "sharpe",
    "annualized_return",
    "max_dd",
    "win_rate",
    "avg_trade_return",
    "avg_hold_hours",
    "total_funding_paid",
]

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class BacktestConfig:
    funding_dir: Path = DEFAULT_FUNDING_DIR
    candles_dir: Path = DEFAULT_CANDLES_DIR
    out: Path = DEFAULT_OUT
    z_threshold: float = 2.0
    hold_hours: int = 24
    lookback_days: int = 30
    taker_fee: float = 0.0005
    slippage: float = 0.0002


@dataclass(frozen=True)
class TradeRecord:
    token: str
    entry_time: pd.Timestamp
    exit_time: pd.Timestamp
    direction: int
    trade_return: float
    hold_hours: float
    funding_paid: float


@dataclass(frozen=True)
class TokenBacktest:
    token: str
    equity: pd.Series
    trades: list[TradeRecord]


def run_single_config(config: BacktestConfig) -> pd.DataFrame:
    funding_history = load_funding_history(config.funding_dir)
    prices = load_prices(config.candles_dir)
    token_results: list[TokenBacktest] = []
    rows: list[dict[str, object]] = []

    for token in sorted(funding_history):
        funding = funding_history[token]
        price = prices.get(token)
        if price is None:
            logger.warning("skipping %s: missing 1h candles", token)
            continue
        if not _has_sufficient_history(funding, config.lookback_days):
            logger.warning("skipping %s: insufficient funding history", token)
            continue

        result = _run_token_backtest(token, funding, price, config)
        token_results.append(result)
        rows.append(_metrics_row(token, result.equity, result.trades, config))

    aggregate_equity = _aggregate_equity([result.equity for result in token_results])
    aggregate_trades = [trade for result in token_results for trade in result.trades]
    rows.append(_metrics_row("AGGREGATE", aggregate_equity, aggregate_trades, config))
    return pd.DataFrame(rows, columns=OUTPUT_COLUMNS)


def load_funding_history(funding_dir: Path) -> dict[str, pd.DataFrame]:
    history: dict[str, pd.DataFrame] = {}
    for path in sorted(funding_dir.glob("*.parquet")):
        token = path.stem
        try:
            frame = read_funding(token, path=path)
        except Exception as exc:
            logger.warning("skipping %s: failed to read funding parquet: %s", token, exc)
            continue
        if not frame.empty:
            history[token] = frame
    return history


def load_prices(candles_dir: Path) -> dict[str, pd.Series]:
    prices: dict[str, pd.Series] = {}
    for path in sorted(candles_dir.glob("*_1h.parquet")):
        token = path.name.removesuffix("_1h.parquet")
        try:
            frame = read_candles(token, "1h", path=path)
        except Exception as exc:
            logger.warning("skipping %s: failed to read candle parquet: %s", token, exc)
            continue
        if frame.empty or "close" not in frame:
            continue

        close = pd.to_numeric(frame["close"], errors="coerce").dropna().astype("float64")
        if close.empty:
            continue
        close.index = _coerce_utc_index(close.index)
        prices[token] = close.sort_index().rename("close")
    return prices


def write_results(frame: pd.DataFrame, out: Path) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(out, index=False)


def _run_token_backtest(
    token: str,
    funding: pd.DataFrame,
    price: pd.Series,
    config: BacktestConfig,
) -> TokenBacktest:
    signal = funding_extreme_signal(
        {token: funding},
        {token: price},
        z_threshold=config.z_threshold,
        lookback_days=config.lookback_days,
        hold_hours=config.hold_hours,
    ).get(token)
    if signal is None:
        equity = pd.Series(BASE_CAPITAL, index=_coerce_utc_index(price.index), dtype="float64")
        return TokenBacktest(token=token, equity=equity, trades=[])

    entries, exits, direction = signal
    trades = _extract_trades(
        token,
        price,
        funding,
        entries,
        exits,
        direction,
        taker_fee=config.taker_fee,
        slippage=config.slippage,
    )
    equity = _equity_curve(price.index, trades)
    return TokenBacktest(token=token, equity=equity, trades=trades)


def _extract_trades(
    token: str,
    price: pd.Series,
    funding: pd.DataFrame,
    entries: pd.Series,
    exits: pd.Series,
    direction: pd.Series,
    *,
    taker_fee: float,
    slippage: float,
) -> list[TradeRecord]:
    close = price.astype("float64").sort_index()
    close.index = _coerce_utc_index(close.index)
    entry_signals = entries.reindex(close.index).fillna(False).astype(bool)
    exit_signals = exits.reindex(close.index).fillna(False).astype(bool)
    directions = direction.reindex(close.index).fillna(0).astype("int64")

    active_entry: pd.Timestamp | None = None
    active_direction = 0
    trades: list[TradeRecord] = []

    for timestamp in close.index:
        if active_entry is None:
            if bool(entry_signals.loc[timestamp]):
                next_direction = int(directions.loc[timestamp])
                if next_direction in {-1, 1}:
                    active_entry = timestamp
                    active_direction = next_direction
            continue

        if not bool(exit_signals.loc[timestamp]):
            continue

        trade = _build_trade(
            token,
            close,
            funding,
            active_entry,
            timestamp,
            active_direction,
            taker_fee=taker_fee,
            slippage=slippage,
        )
        trades.append(trade)
        active_entry = None
        active_direction = 0

    return trades


def _build_trade(
    token: str,
    close: pd.Series,
    funding: pd.DataFrame,
    entry_time: pd.Timestamp,
    exit_time: pd.Timestamp,
    direction: int,
    *,
    taker_fee: float,
    slippage: float,
) -> TradeRecord:
    entry_price = float(close.loc[entry_time])
    exit_price = float(close.loc[exit_time])
    price_return = _price_return(entry_price, exit_price, direction)
    funding_paid = _funding_paid(funding, entry_time, exit_time, direction)
    trade_return = price_return - (2.0 * taker_fee) - (2.0 * slippage) - funding_paid
    hold_hours = (exit_time - entry_time) / pd.Timedelta(hours=1)
    return TradeRecord(
        token=token,
        entry_time=entry_time,
        exit_time=exit_time,
        direction=direction,
        trade_return=float(trade_return),
        hold_hours=float(hold_hours),
        funding_paid=float(funding_paid),
    )


def _price_return(entry_price: float, exit_price: float, direction: int) -> float:
    if entry_price <= 0 or exit_price <= 0:
        return math.nan
    if direction == 1:
        return exit_price / entry_price - 1.0
    if direction == -1:
        return entry_price / exit_price - 1.0
    raise ValueError(f"unsupported direction: {direction}")


def _funding_paid(
    funding: pd.DataFrame,
    entry_time: pd.Timestamp,
    exit_time: pd.Timestamp,
    direction: int,
) -> float:
    if funding.empty or "funding_rate" not in funding.columns:
        return 0.0

    frame = funding.copy()
    frame.index = _coerce_utc_index(frame.index)
    rates = pd.to_numeric(frame["funding_rate"], errors="coerce").dropna()
    mask = (rates.index > entry_time) & (rates.index <= exit_time)
    return float(rates.loc[mask].sum()) * direction


def _equity_curve(index: pd.Index, trades: list[TradeRecord]) -> pd.Series:
    equity_index = _coerce_utc_index(index)
    equity = pd.Series(BASE_CAPITAL, index=equity_index, dtype="float64")
    capital = BASE_CAPITAL
    for trade in sorted(trades, key=lambda item: item.exit_time):
        if not math.isfinite(trade.trade_return):
            continue
        capital *= 1.0 + trade.trade_return
        equity.loc[equity.index >= trade.exit_time] = capital
    return equity


def _aggregate_equity(equities: list[pd.Series]) -> pd.Series:
    if not equities:
        return pd.Series(dtype="float64", name="equity")

    union_index = _coerce_utc_index(equities[0].index)
    for equity in equities[1:]:
        union_index = union_index.union(_coerce_utc_index(equity.index))

    aligned = [
        equity.reindex(union_index).ffill().fillna(BASE_CAPITAL).astype("float64")
        for equity in equities
    ]
    return pd.concat(aligned, axis=1).sum(axis=1).rename("equity")


def _metrics_row(
    token: str,
    equity: pd.Series,
    trades: list[TradeRecord],
    config: BacktestConfig,
) -> dict[str, object]:
    n_trades = len(trades)
    trade_returns = pd.Series([trade.trade_return for trade in trades], dtype="float64")
    hold_hours = pd.Series([trade.hold_hours for trade in trades], dtype="float64")
    n_long = sum(1 for trade in trades if trade.direction == 1)
    n_short = sum(1 for trade in trades if trade.direction == -1)
    wins = int((trade_returns > 0).sum()) if n_trades else 0

    return {
        "token": token,
        "z_threshold": float(config.z_threshold),
        "hold_hours": int(config.hold_hours),
        "lookback_days": int(config.lookback_days),
        "n_trades": int(n_trades),
        "n_long": int(n_long),
        "n_short": int(n_short),
        "sharpe": _sharpe(equity, n_trades),
        "annualized_return": _annualized_return(equity, n_trades),
        "max_dd": max_drawdown(equity) if not equity.empty else 0.0,
        "win_rate": float(wins / n_trades) if n_trades else 0.0,
        "avg_trade_return": float(trade_returns.mean()) if n_trades else 0.0,
        "avg_hold_hours": float(hold_hours.mean()) if n_trades else 0.0,
        "total_funding_paid": float(sum(trade.funding_paid for trade in trades)),
    }


def _sharpe(equity: pd.Series, n_trades: int) -> float:
    if n_trades < 5 or equity.empty:
        return math.nan
    returns = equity.pct_change().dropna()
    return sharpe_ratio(returns, periods_per_year("1h"))


def _annualized_return(equity: pd.Series, n_trades: int) -> float:
    if n_trades < 5 or len(equity) < 2:
        return math.nan

    start = float(equity.iloc[0])
    end = float(equity.iloc[-1])
    if start <= 0 or end <= 0:
        return math.nan

    elapsed = equity.index[-1] - equity.index[0]
    years = elapsed / pd.Timedelta(days=365)
    if years <= 0:
        return math.nan
    return float((end / start) ** (1.0 / years) - 1.0)


def _has_sufficient_history(funding: pd.DataFrame, lookback_days: int) -> bool:
    if funding.empty:
        return False
    index = _coerce_utc_index(funding.index)
    if len(index) < 2:
        return False
    return bool(index.max() - index.min() >= pd.Timedelta(days=lookback_days))


def _coerce_utc_index(index: pd.Index) -> pd.DatetimeIndex:
    return pd.DatetimeIndex(pd.to_datetime(index, utc=True), name="timestamp")


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--funding-dir", type=Path, default=DEFAULT_FUNDING_DIR)
    parser.add_argument("--candles-dir", type=Path, default=DEFAULT_CANDLES_DIR)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--z-threshold", type=float, default=2.0)
    parser.add_argument("--hold-hours", type=int, default=24)
    parser.add_argument("--lookback-days", type=int, default=30)
    parser.add_argument("--taker-fee", type=float, default=0.0005)
    parser.add_argument("--slippage", type=float, default=0.0002)
    args = parser.parse_args(argv)
    _validate_args(parser, args)
    return args


def _validate_args(parser: argparse.ArgumentParser, args: argparse.Namespace) -> None:
    if args.z_threshold <= 0:
        parser.error("--z-threshold must be greater than 0")
    if args.hold_hours <= 0:
        parser.error("--hold-hours must be greater than 0")
    if args.lookback_days <= 0:
        parser.error("--lookback-days must be greater than 0")
    if args.taker_fee < 0:
        parser.error("--taker-fee must be non-negative")
    if args.slippage < 0:
        parser.error("--slippage must be non-negative")


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    frame = run_single_config(
        BacktestConfig(
            funding_dir=args.funding_dir,
            candles_dir=args.candles_dir,
            out=args.out,
            z_threshold=args.z_threshold,
            hold_hours=args.hold_hours,
            lookback_days=args.lookback_days,
            taker_fee=args.taker_fee,
            slippage=args.slippage,
        )
    )
    write_results(frame, args.out)
    print(f"wrote parquet: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
