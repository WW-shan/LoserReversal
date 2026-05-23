from __future__ import annotations

import argparse
import math
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from infra.backtest.engine import periods_per_year
from infra.backtest.risk import max_drawdown, sharpe_ratio, sortino_ratio
from infra.hyperliquid_client import HyperliquidClient
from infra.pipeline import interval_timedelta
from infra.storage import read_fills, read_wallets
from signals.wallet_cluster_v1 import cluster_signal

if __package__:
    from scripts.run_wallet_reverse_backtest import (
        CACHE_ERRORS,
        backtest_freq,
        coerce_utc_timestamp,
        daily_sharpe,
        filter_fills_by_end,
        filter_fills_by_start,
        load_or_fetch_candles,
        run_path_backtest,
        summed_equity,
        trade_level_ir,
    )
else:
    from run_wallet_reverse_backtest import (
        CACHE_ERRORS,
        backtest_freq,
        coerce_utc_timestamp,
        daily_sharpe,
        filter_fills_by_end,
        filter_fills_by_start,
        load_or_fetch_candles,
        run_path_backtest,
        summed_equity,
        trade_level_ir,
    )


MIN_WALLETS_GRID = (3, 5, 7, 10)
WINDOW_MINUTES_GRID = (15, 30, 60)
HOLDING_HOURS_GRID = (1.0, 4.0, 12.0, 24.0)


@dataclass(frozen=True)
class WalletClusterBacktestConfig:
    min_wallets: int = 3
    window_minutes: int = 30
    holding_hours: float = 4.0
    top_wallet_n: int = 50
    candle_interval: str = "1h"
    init_cash: float = 10_000.0
    fees: float = 0.0005
    slippage: float = 0.0002
    date_start: datetime | None = None
    date_end: datetime | None = None
    report: Path | None = Path("reports/wallet_cluster_v1_backtest.md")


def run_wallet_cluster_backtest(config: WalletClusterBacktestConfig) -> dict[str, Any]:
    started = time.perf_counter()
    freq = backtest_freq(config.candle_interval)
    wallets = read_wallets().head(config.top_wallet_n).copy()
    pool_fills: dict[str, pd.DataFrame] = {}
    funnel = {
        "fills": 0,
        "date_start_fills": 0,
        "date_end_fills": 0,
        "wallets_with_fills": 0,
        "cluster_events": 0,
        "with_candle": 0,
        "trades": 0,
    }
    failed_wallets: list[str] = []

    for row in wallets.itertuples(index=False):
        address = str(row.eth_address).lower()
        try:
            fills = read_fills(address)
        except CACHE_ERRORS as error:
            failed_wallets.append(address)
            _log(f"warning: skipping {address} fills: {error}")
            continue

        funnel["fills"] += int(len(fills))
        fills = filter_fills_by_start(fills, config.date_start)
        funnel["date_start_fills"] += int(len(fills))
        fills = filter_fills_by_end(fills, config.date_end)
        funnel["date_end_fills"] += int(len(fills))
        if fills.empty:
            continue
        pool_fills[address] = fills

    funnel["wallets_with_fills"] = len(pool_fills)
    events_by_coin = cluster_signal(
        pool_fills,
        min_wallets=config.min_wallets,
        window_minutes=config.window_minutes,
        holding_hours=config.holding_hours,
    )
    funnel["cluster_events"] = sum(int(len(events)) for events in events_by_coin.values())

    backtest = backtest_cluster_events(events_by_coin, config, freq)
    funnel["with_candle"] = int(backtest["events_with_candles"])
    funnel["trades"] = int(backtest["portfolio_stats"]["n_trades"])
    result = {
        "config": config,
        "backtest_freq": freq,
        "n_candidate_wallets": int(len(wallets)),
        "n_failed_wallets": len(failed_wallets),
        "failed_wallets": failed_wallets,
        "n_cluster_events": int(funnel["cluster_events"]),
        "n_backtested_coins": int(backtest["n_backtested_coins"]),
        "funnel": funnel,
        "portfolio_stats": backtest["portfolio_stats"],
        "per_coin_stats": backtest["per_coin_stats"],
        "portfolio_equity": backtest["portfolio_equity"],
        "runtime_seconds": time.perf_counter() - started,
        "report_path": config.report,
    }
    if config.report is not None:
        _write_report(config.report, result)
    return result


def backtest_cluster_events(
    events_by_coin: dict[str, pd.DataFrame],
    config: WalletClusterBacktestConfig,
    freq: str,
) -> dict[str, Any]:
    if not events_by_coin:
        return _empty_backtest_result(config, freq)

    client = HyperliquidClient()
    coin_inputs: list[tuple[str, pd.Series, pd.DataFrame]] = []
    events_with_candles = 0
    for coin, events in events_by_coin.items():
        start = events["entry_time"].min()
        end = events["exit_time"].max() + interval_timedelta(config.candle_interval)
        try:
            candles, cached = load_or_fetch_candles(coin, config.candle_interval, start, end, client)
        except (FileNotFoundError, OSError, ValueError, ConnectionError) as error:
            _log(f"warning: skipping {coin} candles: {error}")
            continue

        close = candles["close"].astype("float64").dropna()
        if close.empty:
            _log(f"warning: skipping {coin}: no close prices")
            continue
        source = "cache" if cached else "HL"
        _log(f"{coin} candles from {source}: {len(close)} rows")
        events_with_candles += int(len(events))
        coin_inputs.append((coin, close, events.copy()))

    if not coin_inputs:
        return _empty_backtest_result(config, freq)

    per_coin_cash = config.init_cash / len(coin_inputs)
    coin_results = []
    for coin, prices, events in coin_inputs:
        result = run_path_backtest(
            prices=prices,
            events=events,
            init_cash=per_coin_cash,
            fees=config.fees,
            slippage=config.slippage,
            freq=freq,
        )
        coin_results.append((coin, result))

    equities = [result["equity"].rename(coin) for coin, result in coin_results]
    trades = [trade for _, result in coin_results for trade in result["trades"]]
    portfolio_equity = summed_equity(equities, per_coin_cash)
    per_coin_stats = [_coin_stats(coin, result, per_coin_cash) for coin, result in coin_results]
    portfolio_stats = _portfolio_stats(portfolio_equity, trades, config, freq)
    return {
        "n_backtested_coins": len(coin_inputs),
        "events_with_candles": events_with_candles,
        "portfolio_stats": portfolio_stats,
        "per_coin_stats": sorted(per_coin_stats, key=_sort_ir, reverse=True),
        "portfolio_equity": portfolio_equity,
    }


_backtest_cluster_events = backtest_cluster_events


def _empty_backtest_result(config: WalletClusterBacktestConfig, freq: str) -> dict[str, Any]:
    equity = pd.Series(dtype="float64", name="equity")
    return {
        "n_backtested_coins": 0,
        "events_with_candles": 0,
        "portfolio_stats": _portfolio_stats(equity, [], config, freq),
        "per_coin_stats": [],
        "portfolio_equity": equity,
    }


def _coin_stats(coin: str, result: dict[str, Any], init_cash: float) -> dict[str, Any]:
    stats = result["stats"]
    equity = result["equity"]
    equity_final = float(equity.iloc[-1]) if not equity.empty else 0.0
    return {
        "coin": coin,
        "sharpe": float(stats["sharpe"]),
        "daily_sharpe": daily_sharpe(equity),
        "trade_level_ir": trade_level_ir(result["trades"]),
        "sortino": float(stats["sortino"]),
        "max_dd": float(stats["max_dd"]),
        "n_trades": int(stats["n_trades"]),
        "win_rate": float(stats["win_rate"]),
        "total_return": equity_final / init_cash - 1.0 if init_cash else 0.0,
        "equity_final": equity_final,
    }


def _portfolio_stats(
    equity: pd.Series,
    trades: list[dict[str, Any]],
    config: WalletClusterBacktestConfig,
    freq: str,
) -> dict[str, Any]:
    returns = equity.pct_change().dropna()
    equity_final = float(equity.iloc[-1]) if not equity.empty else 0.0
    equity_first = float(equity.iloc[0]) if not equity.empty else 0.0
    n_trades = len(trades)
    trades_won = sum(1 for trade in trades if float(trade["return"]) > 0)
    return {
        "sharpe": sharpe_ratio(returns, periods_per_year(freq)),
        "daily_sharpe": daily_sharpe(equity),
        "trade_level_ir": trade_level_ir(trades),
        "sortino": sortino_ratio(returns, periods_per_year(freq)),
        "max_dd": max_drawdown(equity),
        "n_trades": n_trades,
        "win_rate": trades_won / n_trades if n_trades else 0.0,
        "total_return": equity_final / equity_first - 1.0 if equity_first else 0.0,
        "equity_final": equity_final,
        "capital": config.init_cash,
    }


def _write_report(path: Path, result: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_format_report(result), encoding="utf-8")


def _format_report(result: dict[str, Any]) -> str:
    generated = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    config: WalletClusterBacktestConfig = result["config"]
    stats = result["portfolio_stats"]
    funnel = result["funnel"]
    lines = [
        "# Wallet Cluster V1 Backtest",
        "",
        f"_Generated {generated}_",
        "",
        "## Config",
        "",
        "| Key | Value |",
        "| --- | --- |",
        f"| min_wallets | {config.min_wallets} |",
        f"| window_minutes | {config.window_minutes} |",
        f"| holding_hours | {config.holding_hours:.2f} |",
        f"| top_wallet_n | {config.top_wallet_n} |",
        f"| candle_interval | {config.candle_interval} |",
        f"| date_start | {_fmt_optional_date(config.date_start)} |",
        f"| date_end | {_fmt_optional_date(config.date_end)} |",
        "",
        "## Funnel",
        "",
        "| step | count |",
        "| --- | ---: |",
        f"| fills | {funnel['fills']} |",
        f"| date_start_fills | {funnel['date_start_fills']} |",
        f"| date_end_fills | {funnel['date_end_fills']} |",
        f"| wallets_with_fills | {funnel['wallets_with_fills']} |",
        f"| cluster_events | {funnel['cluster_events']} |",
        f"| with_candle | {funnel['with_candle']} |",
        f"| trades | {funnel['trades']} |",
        "",
        "## Portfolio Stats",
        "",
        "| Metric | Value |",
        "| --- | ---: |",
        f"| Trade-level IR | {_fmt_num(stats['trade_level_ir'], 2)} |",
        f"| Daily Sharpe | {_fmt_num(stats['daily_sharpe'], 2)} |",
        f"| Hourly Sharpe | {_fmt_num(stats['sharpe'], 2)} |",
        f"| Sortino | {_fmt_num(stats['sortino'], 2)} |",
        f"| Max DD | {_fmt_pct(stats['max_dd'])} |",
        f"| n_trades | {stats['n_trades']} |",
        f"| win_rate | {_fmt_pct(stats['win_rate'])} |",
        f"| total_return | {_fmt_pct(stats['total_return'])} |",
        f"| final equity | {_fmt_money(stats['equity_final'])} |",
        "",
        "## Per-Coin Stats",
        "",
        "| coin | trade_level_ir | daily_sharpe | max_dd | n_trades | total_return |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
        *_coin_rows(result["per_coin_stats"]),
    ]
    return "\n".join(lines) + "\n"


def _coin_rows(rows: list[dict[str, Any]]) -> list[str]:
    if not rows:
        return ["| - | - | - | - | - | - |"]
    return [
        f"| {row['coin']} | {_fmt_num(row['trade_level_ir'], 2)} | "
        f"{_fmt_num(row['daily_sharpe'], 2)} | {_fmt_pct(row['max_dd'])} | "
        f"{row['n_trades']} | {_fmt_pct(row['total_return'])} |"
        for row in rows
    ]


def _fmt_optional_date(value: datetime | None) -> str:
    if value is None:
        return "disabled"
    return coerce_utc_timestamp(value).strftime("%Y-%m-%d")


def _fmt_num(value: Any, decimals: int) -> str:
    number = float(value)
    if not math.isfinite(number):
        return "n/a"
    return f"{number:.{decimals}f}"


def _fmt_pct(value: Any) -> str:
    number = float(value)
    if not math.isfinite(number):
        return "n/a"
    return f"{number * 100:.2f}%"


def _fmt_money(value: Any) -> str:
    return f"${float(value):,.2f}"


def _sort_ir(row: dict[str, Any]) -> float:
    value = float(row["trade_level_ir"])
    return value if math.isfinite(value) else float("-inf")


def _parse_datetime_arg(value: str) -> datetime:
    try:
        return coerce_utc_timestamp(value).to_pydatetime()
    except (TypeError, ValueError) as error:
        raise argparse.ArgumentTypeError(f"invalid datetime {value!r}") from error


def _log(message: str) -> None:
    print(message, file=sys.stderr)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run wallet cluster backtest.")
    parser.add_argument("--min-wallets", type=int, default=3)
    parser.add_argument("--window-minutes", type=int, default=30)
    parser.add_argument("--holding-hours", type=float, default=4.0)
    parser.add_argument("--top-wallet-n", type=int, default=50)
    parser.add_argument("--candle-interval", default="1h")
    parser.add_argument("--init-cash", type=float, default=10_000.0)
    parser.add_argument("--fees", type=float, default=0.0005)
    parser.add_argument("--slippage", type=float, default=0.0002)
    parser.add_argument("--date-start", type=_parse_datetime_arg, default=None)
    parser.add_argument("--date-end", type=_parse_datetime_arg, default=None)
    parser.add_argument("--report", type=Path, default=Path("reports/wallet_cluster_v1_backtest.md"))
    args = parser.parse_args()
    _validate_args(parser, args)
    return args


def _validate_args(parser: argparse.ArgumentParser, args: argparse.Namespace) -> None:
    if args.min_wallets < 1:
        parser.error("--min-wallets must be at least 1")
    if args.window_minutes <= 0:
        parser.error("--window-minutes must be greater than 0")
    if args.holding_hours <= 0:
        parser.error("--holding-hours must be greater than 0")
    if args.top_wallet_n <= 0:
        parser.error("--top-wallet-n must be greater than 0")
    if args.init_cash <= 0:
        parser.error("--init-cash must be greater than 0")
    if args.fees < 0:
        parser.error("--fees must be non-negative")
    if args.slippage < 0:
        parser.error("--slippage must be non-negative")
    if not args.candle_interval:
        parser.error("--candle-interval must not be empty")
    if args.date_start is not None and args.date_end is not None and args.date_start >= args.date_end:
        parser.error("--date-start must be earlier than --date-end")
    try:
        interval_timedelta(args.candle_interval)
    except ValueError as error:
        parser.error(str(error))


def main() -> int:
    args = _parse_args()
    result = run_wallet_cluster_backtest(
        WalletClusterBacktestConfig(
            min_wallets=args.min_wallets,
            window_minutes=args.window_minutes,
            holding_hours=args.holding_hours,
            top_wallet_n=args.top_wallet_n,
            candle_interval=args.candle_interval,
            init_cash=args.init_cash,
            fees=args.fees,
            slippage=args.slippage,
            date_start=args.date_start,
            date_end=args.date_end,
            report=args.report,
        )
    )
    print(f"wrote report: {result['report_path']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
