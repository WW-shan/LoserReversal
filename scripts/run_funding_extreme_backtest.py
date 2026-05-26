"""Run a single funding-extreme contrarian backtest configuration."""

from __future__ import annotations

import argparse
import logging
import math
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from infra.backtest.engine import periods_per_year
from infra.backtest.risk import max_drawdown, sharpe_ratio
from infra.storage import PARQUET_DIR, read_candles, read_funding
from signals.funding_extreme_v1 import funding_extreme_signal


DEFAULT_FUNDING_DIR = PARQUET_DIR / "funding"
DEFAULT_CANDLES_DIR = PARQUET_DIR / "candles"
DEFAULT_OUT = PARQUET_DIR / "funding_extreme_backtest.parquet"
DEFAULT_PRICE_INTERVAL = "1h"
SUPPORTED_PRICE_INTERVALS = ("1h", "4h")
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
    price_interval: str = DEFAULT_PRICE_INTERVAL


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


@dataclass(frozen=True)
class SingleConfigResult:
    frame: pd.DataFrame
    skipped_tokens: list[str] = field(default_factory=list)


def run_single_config(config: BacktestConfig) -> pd.DataFrame:
    return run_single_config_with_coverage(config).frame


def run_single_config_with_coverage(config: BacktestConfig) -> SingleConfigResult:
    funding_history = load_funding_history(config.funding_dir)
    prices = load_prices(config.candles_dir, price_interval=config.price_interval)
    return execute_backtest(funding_history, prices, config)


def execute_backtest(
    funding_history: dict[str, pd.DataFrame],
    prices: dict[str, pd.Series],
    config: BacktestConfig,
) -> SingleConfigResult:
    """Run a single config over pre-loaded data. Used by walk-forward."""
    token_results: list[TokenBacktest] = []
    rows: list[dict[str, object]] = []
    skipped: list[str] = []

    for token in sorted(funding_history):
        funding = funding_history[token]
        price = prices.get(token)
        if price is None:
            logger.warning("skipping %s: missing %s candles", token, config.price_interval)
            skipped.append(token)
            continue
        if not _has_sufficient_history(funding, config.lookback_days):
            logger.warning("skipping %s: insufficient funding history", token)
            skipped.append(token)
            continue

        result = _run_token_backtest(token, funding, price, config)
        token_results.append(result)
        rows.append(_metrics_row(token, result.equity, result.trades, config))

    aggregate_equity = _aggregate_equity([result.equity for result in token_results])
    aggregate_trades = [trade for result in token_results for trade in result.trades]
    portfolio_equity = _portfolio_equity_curve([result.equity for result in token_results])
    aggregate_sharpe = _portfolio_sharpe_from_equity(portfolio_equity, len(aggregate_trades))
    aggregate_annualized = _annualized_return(portfolio_equity, len(aggregate_trades))
    aggregate_max_dd = max_drawdown(portfolio_equity) if not portfolio_equity.empty else 0.0
    rows.append(
        _metrics_row(
            "AGGREGATE",
            aggregate_equity,
            aggregate_trades,
            config,
            override_sharpe=aggregate_sharpe,
            override_annualized=aggregate_annualized,
            override_max_dd=aggregate_max_dd,
        )
    )
    frame = pd.DataFrame(rows, columns=OUTPUT_COLUMNS)
    return SingleConfigResult(frame=frame, skipped_tokens=skipped)


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


def load_prices(
    candles_dir: Path,
    *,
    price_interval: str = DEFAULT_PRICE_INTERVAL,
) -> dict[str, pd.Series]:
    """Load close-price series for every token whose candles match `price_interval`.

    Globs `*_{price_interval}.parquet`. The `_sharpe` daily-resample downstream is
    interval-agnostic because it operates on `equity.resample("1D").last()` (no per-bar
    pct_change), so the only change a different interval introduces is fewer rows and a
    coarser intra-trade mark-to-market — not a re-derivation of the Sharpe formula.
    """
    if price_interval not in SUPPORTED_PRICE_INTERVALS:
        raise ValueError(
            f"unsupported price_interval {price_interval!r}; "
            f"expected one of {SUPPORTED_PRICE_INTERVALS}"
        )
    suffix = f"_{price_interval}.parquet"
    prices: dict[str, pd.Series] = {}
    for path in sorted(candles_dir.glob(f"*{suffix}")):
        token = path.name.removesuffix(suffix)
        try:
            frame = read_candles(token, price_interval, path=path)
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
    equity = _equity_curve(price, trades)
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


def _equity_curve(price: pd.Series, trades: list[TradeRecord]) -> pd.Series:
    """Mark-to-market equity curve.

    Outside an open position the equity is flat at last realized capital.
    Inside an open position the equity floats with `direction * (price_t / entry_price - 1)`
    on top of the capital at entry; at exit the realized `trade_return` (which already
    includes fees, slippage, and funding) snaps the curve.
    """
    index = _coerce_utc_index(price.index)
    close = pd.Series(
        pd.to_numeric(price.values, errors="coerce"), index=index, dtype="float64"
    )
    equity = pd.Series(BASE_CAPITAL, index=index, dtype="float64")
    capital = BASE_CAPITAL
    last_filled = -1

    for trade in sorted(trades, key=lambda item: item.entry_time):
        if not math.isfinite(trade.trade_return):
            continue
        try:
            entry_pos = index.get_indexer([trade.entry_time])[0]
            exit_pos = index.get_indexer([trade.exit_time])[0]
        except KeyError:
            continue
        if entry_pos < 0 or exit_pos < 0 or exit_pos <= entry_pos:
            continue
        # Flat between last filled and entry
        if last_filled + 1 <= entry_pos:
            equity.iloc[last_filled + 1 : entry_pos + 1] = capital
        entry_price = float(close.iloc[entry_pos])
        if not math.isfinite(entry_price) or entry_price <= 0:
            equity.iloc[entry_pos : exit_pos + 1] = capital
            last_filled = exit_pos
            continue
        # Mark-to-market intra-trade (gross PnL only; fees realize at exit)
        for i in range(entry_pos + 1, exit_pos):
            price_t = float(close.iloc[i])
            if not math.isfinite(price_t) or price_t <= 0:
                equity.iloc[i] = equity.iloc[i - 1]
                continue
            mtm = trade.direction * (price_t / entry_price - 1.0)
            equity.iloc[i] = capital * (1.0 + mtm)
        capital *= 1.0 + trade.trade_return
        equity.iloc[exit_pos] = capital
        last_filled = exit_pos

    if last_filled + 1 < len(index):
        equity.iloc[last_filled + 1 :] = capital
    return equity


def _aggregate_equity(equities: list[pd.Series]) -> pd.Series:
    """Sum per-token mark-to-market equities.

    Each token contributes 0 before its first observation (not BASE_CAPITAL — would
    inflate denominator for late-listed tokens) and forward-fill from the first valid
    bar onward. Aggregate NAV grows as tokens come online.
    """
    if not equities:
        return pd.Series(dtype="float64", name="equity")

    union_index = _coerce_utc_index(equities[0].index)
    for equity in equities[1:]:
        union_index = union_index.union(_coerce_utc_index(equity.index))

    aligned: list[pd.Series] = []
    for equity in equities:
        reindexed = equity.astype("float64").reindex(union_index)
        first_valid = reindexed.first_valid_index()
        if first_valid is None:
            aligned.append(pd.Series(0.0, index=union_index, dtype="float64"))
            continue
        filled = reindexed.ffill()
        filled.loc[filled.index < first_valid] = 0.0
        aligned.append(filled)
    return pd.concat(aligned, axis=1).sum(axis=1).rename("equity")


def _metrics_row(
    token: str,
    equity: pd.Series,
    trades: list[TradeRecord],
    config: BacktestConfig,
    *,
    override_sharpe: float | None = None,
    override_annualized: float | None = None,
    override_max_dd: float | None = None,
) -> dict[str, object]:
    n_trades = len(trades)
    trade_returns = pd.Series([trade.trade_return for trade in trades], dtype="float64")
    hold_hours = pd.Series([trade.hold_hours for trade in trades], dtype="float64")
    n_long = sum(1 for trade in trades if trade.direction == 1)
    n_short = sum(1 for trade in trades if trade.direction == -1)
    wins = int((trade_returns > 0).sum()) if n_trades else 0

    sharpe_value = override_sharpe if override_sharpe is not None else _sharpe(equity, n_trades)
    annualized_value = (
        override_annualized
        if override_annualized is not None
        else _annualized_return(equity, n_trades)
    )
    max_dd_value = (
        override_max_dd
        if override_max_dd is not None
        else (max_drawdown(equity) if not equity.empty else 0.0)
    )
    return {
        "token": token,
        "z_threshold": float(config.z_threshold),
        "hold_hours": int(config.hold_hours),
        "lookback_days": int(config.lookback_days),
        "n_trades": int(n_trades),
        "n_long": int(n_long),
        "n_short": int(n_short),
        "sharpe": sharpe_value,
        "annualized_return": annualized_value,
        "max_dd": max_dd_value,
        "win_rate": float(wins / n_trades) if n_trades else 0.0,
        "avg_trade_return": float(trade_returns.mean()) if n_trades else 0.0,
        "avg_hold_hours": float(hold_hours.mean()) if n_trades else 0.0,
        "total_funding_paid": float(sum(trade.funding_paid for trade in trades)),
    }


def _sharpe(equity: pd.Series, n_trades: int) -> float:
    """Sharpe annualized off daily-resampled equity returns.

    Previous implementation annualized hourly pct_change by sqrt(8760) on a step-function
    equity (constant between trade exits) — that inflates the ratio because std is
    dominated by zeros. Daily resampling smooths the step jumps and matches the
    granularity used by the unlock walk-forward report.
    """
    if n_trades < 5 or equity.empty:
        return math.nan
    daily = equity.resample("1D").last().dropna()
    if len(daily) < 2:
        return math.nan
    returns = daily.pct_change().dropna()
    if returns.empty:
        return math.nan
    return sharpe_ratio(returns, periods_per_year("1D"))


def _aggregate_sharpe(equities: list[pd.Series], n_trades: int) -> float:
    """Aggregate Sharpe from equal-weight portfolio of per-token daily returns.

    Each token contributes daily returns starting from its first valid bar; the
    portfolio return at day t is the mean across active tokens. This avoids the
    onboarding-spike artifact a token getting first $10k allocation would create
    when summing raw equities across heterogeneous listing dates.
    """
    portfolio = _portfolio_equity_curve(equities)
    return _portfolio_sharpe_from_equity(portfolio, n_trades)


def _portfolio_equity_curve(equities: list[pd.Series]) -> pd.Series:
    """Equal-weight portfolio cumulative equity rebased to BASE_CAPITAL.

    Daily portfolio return = mean of per-token daily returns across tokens
    active that day. Cumulative product starts at BASE_CAPITAL one day before
    the first return so `pct_change` reproduces the portfolio return series.
    """
    if not equities:
        return pd.Series(dtype="float64")
    per_token: list[pd.Series] = []
    for equity in equities:
        clean = equity.astype("float64").dropna()
        if clean.empty:
            continue
        daily = clean.resample("1D").last().dropna()
        if len(daily) < 2:
            continue
        returns = daily.pct_change().dropna()
        if not returns.empty:
            per_token.append(returns)
    if not per_token:
        return pd.Series(dtype="float64")
    joined = pd.concat(per_token, axis=1)
    portfolio_returns = joined.mean(axis=1, skipna=True).dropna()
    if portfolio_returns.empty:
        return pd.Series(dtype="float64")
    cumulative = (1.0 + portfolio_returns).cumprod() * BASE_CAPITAL
    seed_index = portfolio_returns.index[0] - pd.Timedelta(days=1)
    seed = pd.Series(
        [BASE_CAPITAL],
        index=pd.DatetimeIndex([seed_index], tz=cumulative.index.tz or "UTC"),
    )
    return pd.concat([seed, cumulative]).sort_index()


def _portfolio_sharpe_from_equity(portfolio_equity: pd.Series, n_trades: int) -> float:
    if n_trades < 5 or portfolio_equity.empty or len(portfolio_equity) < 2:
        return math.nan
    returns = portfolio_equity.pct_change().dropna()
    if returns.empty:
        return math.nan
    return sharpe_ratio(returns, periods_per_year("1D"))


def _annualized_return(equity: pd.Series, n_trades: int) -> float:
    if n_trades < 5 or len(equity) < 2:
        return math.nan

    nonzero = equity[equity > 0]
    if nonzero.empty:
        return math.nan
    start = float(nonzero.iloc[0])
    end = float(nonzero.iloc[-1])
    if start <= 0 or end <= 0:
        return math.nan

    elapsed = nonzero.index[-1] - nonzero.index[0]
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
    parser.add_argument(
        "--price-interval",
        choices=SUPPORTED_PRICE_INTERVALS,
        default=DEFAULT_PRICE_INTERVAL,
        help="candle interval to load (default 1h; 4h matches Phase 3 4h refactor)",
    )
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
            price_interval=args.price_interval,
        )
    )
    write_results(frame, args.out)
    print(f"wrote parquet: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
