from __future__ import annotations

import argparse
import math
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd

from infra.backtest.engine import periods_per_year
from infra.backtest.risk import max_drawdown, sharpe_ratio, sortino_ratio
from infra.fetchers.candles import fetch_candles
from infra.hyperliquid_client import HyperliquidClient
from infra.pipeline import PipelineConfig, candles_cover_range, interval_timedelta
from infra.storage import read_candles, read_fills, read_wallets, write_candles
from signals.wallet_reverse_v1 import reverse_signal, reverse_signal_events


CACHE_ERRORS = (FileNotFoundError, OSError, duckdb.Error)


@dataclass(frozen=True)
class WalletReverseBacktestConfig:
    holding_hours: float = 4.0
    top_wallet_n: int = 50
    candle_interval: str = "1h"
    init_cash: float = 10_000.0
    fees: float = 0.0005
    slippage: float = 0.0002
    report: Path | None = Path("reports/wallet_reverse_v1_backtest.md")


def run_wallet_reverse_backtest(config: WalletReverseBacktestConfig) -> dict[str, Any]:
    started = time.perf_counter()
    freq = _backtest_freq(config.candle_interval)
    wallets = read_wallets().head(config.top_wallet_n).copy()
    client = HyperliquidClient()
    funnel = {
        "fills": 0,
        "in_size": 0,
        "with_candle": 0,
        "trades": 0,
    }
    failed_wallets: list[str] = []
    skipped_wallets: list[str] = []
    wallet_stats: list[dict[str, Any]] = []
    wallet_equities: list[pd.Series] = []
    portfolio_trades: list[dict[str, Any]] = []

    for position, row in enumerate(wallets.itertuples(index=False), start=1):
        wallet_started = time.perf_counter()
        address = str(row.eth_address).lower()
        try:
            fills = read_fills(address)
        except CACHE_ERRORS as error:
            failed_wallets.append(address)
            _log(f"[{position}/{len(wallets)}] warning: skipping {address} fills: {error}")
            continue

        funnel["fills"] += int(len(fills))
        events = reverse_signal_events(fills, config.holding_hours)
        signals = reverse_signal(fills, config.holding_hours)
        signal_count = sum(int(entries.sum()) for entries, _, _ in signals.values())
        funnel["in_size"] += int(len(events))
        if events.empty:
            skipped_wallets.append(address)
            _log(f"[{position}/{len(wallets)}] {address} no qualifying fills")
            continue

        wallet_result = _backtest_wallet(address, events, config, freq, client)
        if wallet_result["n_backtested_coins"] == 0:
            failed_wallets.append(address)
            _log(f"[{position}/{len(wallets)}] warning: {address} no coins backtested")
            continue

        stats = wallet_result["stats"]
        wallet_stats.append(stats)
        wallet_equities.append(wallet_result["equity"].rename(address))
        portfolio_trades.extend(wallet_result["trades"])
        funnel["with_candle"] += int(wallet_result["events_with_candles"])
        funnel["trades"] += int(stats["n_trades"])
        elapsed = time.perf_counter() - wallet_started
        _log(
            f"[{position}/{len(wallets)}] {address} signals={signal_count} "
            f"trades={stats['n_trades']} Sharpe={stats['sharpe']:.2f} ({elapsed:.1f}s)"
        )

    portfolio_equity = _summed_equity(wallet_equities, config.init_cash)
    portfolio_stats = _portfolio_stats(portfolio_equity, wallet_stats, portfolio_trades, config, freq)
    result = {
        "config": config,
        "backtest_freq": freq,
        "n_candidate_wallets": int(len(wallets)),
        "n_backtested_wallets": len(wallet_stats),
        "n_failed_wallets": len(failed_wallets),
        "n_skipped_wallets": len(skipped_wallets),
        "failed_wallets": failed_wallets,
        "skipped_wallets": skipped_wallets,
        "funnel": funnel,
        "portfolio_stats": portfolio_stats,
        "per_wallet_stats": sorted(wallet_stats, key=_sort_sharpe, reverse=True),
        "portfolio_equity": portfolio_equity,
        "runtime_seconds": time.perf_counter() - started,
        "report_path": config.report,
    }
    if config.report is not None:
        _write_report(config.report, result)
    return result


def _backtest_wallet(
    address: str,
    events: pd.DataFrame,
    config: WalletReverseBacktestConfig,
    freq: str,
    client: HyperliquidClient,
) -> dict[str, Any]:
    coin_inputs: list[tuple[str, pd.Series, pd.DataFrame]] = []
    events_with_candles = 0

    for coin, coin_events in events.groupby("coin", sort=False):
        coin_name = str(coin)
        start = coin_events["entry_time"].min()
        end = coin_events["exit_time"].max() + interval_timedelta(config.candle_interval)
        try:
            candles, cached = _load_or_fetch_candles(coin_name, config.candle_interval, start, end, client)
        except (FileNotFoundError, OSError, duckdb.Error, ValueError, ConnectionError) as error:
            _log(f"  warning: skipping {address} {coin_name} candles: {error}")
            continue

        close = candles["close"].astype("float64").dropna()
        if close.empty:
            _log(f"  warning: skipping {address} {coin_name}: no close prices")
            continue

        events_with_candles += int(len(coin_events))
        coin_inputs.append((coin_name, close, coin_events.copy()))
        source = "cache" if cached else "HL"
        _log(f"  {address} {coin_name} candles from {source}: {len(close)} rows")

    if not coin_inputs:
        return {
            "n_backtested_coins": 0,
            "events_with_candles": 0,
            "stats": _empty_wallet_stats(address),
            "equity": pd.Series(dtype="float64", name=address),
            "trades": [],
        }

    per_coin_cash = config.init_cash / len(coin_inputs)
    coin_results = [
        _run_path_backtest(
            prices=prices,
            events=coin_events,
            init_cash=per_coin_cash,
            fees=config.fees,
            slippage=config.slippage,
            freq=freq,
        )
        for _, prices, coin_events in coin_inputs
    ]
    coin_equities = [result["equity"] for result in coin_results]
    trades = [trade for result in coin_results for trade in result["trades"]]
    wallet_equity = _summed_equity(coin_equities, per_coin_cash)
    stats = _wallet_stats(address, wallet_equity, coin_results, config, freq)
    stats["n_coins"] = len(coin_inputs)
    return {
        "n_backtested_coins": len(coin_inputs),
        "events_with_candles": events_with_candles,
        "stats": stats,
        "equity": wallet_equity,
        "trades": trades,
    }


def _run_path_backtest(
    prices: pd.Series,
    events: pd.DataFrame,
    init_cash: float,
    fees: float,
    slippage: float,
    freq: str,
) -> dict[str, Any]:
    close = prices.astype("float64").dropna().sort_index()
    close.index = _coerce_utc_index(close.index)
    if close.empty:
        return _empty_coin_result(init_cash)

    deltas = pd.Series(0.0, index=close.index)
    costs = pd.Series(0.0, index=close.index)
    trades: list[dict[str, Any]] = []
    roundtrip_cost = 2.0 * (fees + slippage)

    for event in events.itertuples(index=False):
        entry_pos = _first_index_position_at_or_after(close.index, event.entry_time)
        exit_pos = _first_index_position_at_or_after(close.index, event.exit_time)
        if entry_pos is None or exit_pos is None or exit_pos <= entry_pos:
            continue

        direction = 1.0 if event.side == "long" else -1.0
        entry_price = float(close.iloc[entry_pos])
        exit_price = float(close.iloc[exit_pos])
        if entry_price <= 0 or exit_price <= 0:
            continue

        gross_return = direction * (exit_price / entry_price - 1.0)
        trades.append(
            {
                "entry_time": pd.Timestamp(event.entry_time),
                "exit_time": pd.Timestamp(event.exit_time),
                "return": gross_return - roundtrip_cost,
            }
        )
        deltas.iloc[entry_pos] += direction
        deltas.iloc[exit_pos] -= direction
        costs.iloc[entry_pos] += fees + slippage
        costs.iloc[exit_pos] += fees + slippage

    position = deltas.cumsum().clip(lower=-1.0, upper=1.0)
    price_returns = close.pct_change().fillna(0.0)
    strategy_returns = position.shift(1).fillna(0.0) * price_returns - costs
    equity = _equity_from_returns(init_cash, strategy_returns)
    returns = equity.pct_change().dropna()
    n_trades = len(trades)
    trades_won = sum(1 for trade in trades if float(trade["return"]) > 0)
    return {
        "equity": equity,
        "trades": trades,
        "stats": {
            "sharpe": sharpe_ratio(returns, periods_per_year(freq)),
            "sortino": sortino_ratio(returns, periods_per_year(freq)),
            "max_dd": max_drawdown(equity),
            "n_trades": n_trades,
            "win_rate": trades_won / n_trades if n_trades else 0.0,
            "total_return": float(equity.iloc[-1] / init_cash - 1.0) if not equity.empty else 0.0,
            "equity_final": float(equity.iloc[-1]) if not equity.empty else 0.0,
            "trades_won": trades_won,
        },
    }


def _equity_from_returns(init_cash: float, returns: pd.Series) -> pd.Series:
    current = init_cash
    values = []
    for value in returns:
        current = max(current * max(1.0 + float(value), 0.0), 0.0)
        values.append(current)
    return pd.Series(values, index=returns.index, dtype="float64", name="equity")


def _load_or_fetch_candles(
    coin: str,
    interval: str,
    start: pd.Timestamp,
    end: pd.Timestamp,
    client: HyperliquidClient,
) -> tuple[pd.DataFrame, bool]:
    pipeline_config = PipelineConfig(symbol=coin, interval=interval, start=start, end=end)
    try:
        candles = read_candles(coin, interval, start=start, end=end)
    except CACHE_ERRORS:
        return _fetch_store_load_candles(coin, interval, start, end, client), False

    if not candles_cover_range(candles, pipeline_config):
        return _fetch_store_load_candles(coin, interval, start, end, client), False
    return candles, True


def _fetch_store_load_candles(
    coin: str,
    interval: str,
    start: pd.Timestamp,
    end: pd.Timestamp,
    client: HyperliquidClient,
) -> pd.DataFrame:
    candles = fetch_candles(coin, interval, start, end, client=client)
    if candles.empty:
        raise ValueError("HL returned no candles")

    write_candles(candles, coin, interval)
    loaded = read_candles(coin, interval, start=start, end=end)
    if loaded.empty:
        raise ValueError("cached candles are empty after reload")
    return loaded


def _first_index_position_at_or_after(
    index: pd.DatetimeIndex,
    timestamp: pd.Timestamp,
) -> int | None:
    ts = pd.Timestamp(timestamp)
    if ts.tz is None:
        ts = ts.tz_localize("UTC")
    else:
        ts = ts.tz_convert("UTC")
    position = int(index.searchsorted(ts, side="left"))
    if position >= len(index):
        return None
    return position


def _wallet_stats(
    address: str,
    equity: pd.Series,
    coin_results: list[dict[str, Any]],
    config: WalletReverseBacktestConfig,
    freq: str,
) -> dict[str, Any]:
    n_trades = sum(int(result["stats"]["n_trades"]) for result in coin_results)
    trades_won = sum(int(result["stats"]["trades_won"]) for result in coin_results)
    trades = [trade for result in coin_results for trade in result["trades"]]
    returns = equity.pct_change().dropna()
    equity_final = float(equity.iloc[-1]) if not equity.empty else 0.0
    return {
        "wallet": address,
        "sharpe": sharpe_ratio(returns, periods_per_year(freq)),
        "daily_sharpe": _daily_sharpe(equity),
        "trade_level_ir": _trade_level_ir(trades),
        "sortino": sortino_ratio(returns, periods_per_year(freq)),
        "max_dd": max_drawdown(equity),
        "n_trades": n_trades,
        "win_rate": trades_won / n_trades if n_trades else 0.0,
        "total_return": equity_final / config.init_cash - 1.0 if config.init_cash else 0.0,
        "equity_final": equity_final,
        "trades_won": trades_won,
    }


def _portfolio_stats(
    equity: pd.Series,
    wallet_stats: list[dict[str, Any]],
    trades: list[dict[str, Any]],
    config: WalletReverseBacktestConfig,
    freq: str,
) -> dict[str, Any]:
    n_trades = sum(int(row["n_trades"]) for row in wallet_stats)
    trades_won = sum(float(row["trades_won"]) for row in wallet_stats)
    returns = equity.pct_change().dropna()
    equity_final = float(equity.iloc[-1]) if not equity.empty else 0.0
    equity_first = float(equity.iloc[0]) if not equity.empty else 0.0
    return {
        "sharpe": sharpe_ratio(returns, periods_per_year(freq)),
        "daily_sharpe": _daily_sharpe(equity),
        "trade_level_ir": _trade_level_ir(trades),
        "sortino": sortino_ratio(returns, periods_per_year(freq)),
        "max_dd": max_drawdown(equity),
        "n_trades": n_trades,
        "win_rate": trades_won / n_trades if n_trades else 0.0,
        "total_return": equity_final / equity_first - 1.0 if equity_first else 0.0,
        "equity_final": equity_final,
        "capital_per_wallet": config.init_cash,
    }


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


def _empty_coin_result(init_cash: float) -> dict[str, Any]:
    equity = pd.Series(dtype="float64", name="equity")
    return {
            "equity": equity,
            "trades": [],
            "stats": {
                "sharpe": 0.0,
                "daily_sharpe": 0.0,
                "trade_level_ir": 0.0,
                "sortino": 0.0,
                "max_dd": 0.0,
            "n_trades": 0,
            "win_rate": 0.0,
            "total_return": 0.0,
            "equity_final": init_cash,
            "trades_won": 0,
        },
    }


def _empty_wallet_stats(address: str) -> dict[str, Any]:
    return {
        "wallet": address,
        "sharpe": 0.0,
        "daily_sharpe": 0.0,
        "trade_level_ir": 0.0,
        "sortino": 0.0,
        "max_dd": 0.0,
        "n_trades": 0,
        "win_rate": 0.0,
        "total_return": 0.0,
        "equity_final": 0.0,
        "trades_won": 0,
        "n_coins": 0,
    }


def _write_report(path: Path, result: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    generated = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    config: WalletReverseBacktestConfig = result["config"]
    stats = result["portfolio_stats"]
    funnel = result["funnel"]
    equity = result["portfolio_equity"]
    lines = [
        "# Wallet Reverse V1 Backtest",
        "",
        f"_Generated {generated}_",
        "",
        "## Config",
        "",
        "| Key | Value |",
        "| --- | --- |",
        f"| holding_hours | {config.holding_hours:.2f} |",
        f"| candle_interval | {config.candle_interval} |",
        f"| fees | {config.fees:.6f} |",
        f"| slippage | {config.slippage:.6f} |",
        f"| n_candidate_wallets | {result['n_candidate_wallets']} |",
        f"| n_backtested_wallets | {result['n_backtested_wallets']} |",
        f"| n_failed_wallets | {result['n_failed_wallets']} |",
        f"| n_skipped_wallets | {result['n_skipped_wallets']} |",
        f"| failed_wallets | {result['failed_wallets']!r} |",
        "",
    ]
    if stats["n_trades"] < 100:
        lines.extend(
            [
                "> [WARN] INSUFFICIENT SAMPLE: fewer than 100 trades. "
                "Sharpe is not decision-quality.",
                "",
            ]
        )

    lines.extend(
        [
            "## Decision Gate Check",
            "",
            "| Check | Threshold | Value | Status |",
            "| --- | --- | --- | --- |",
            f"| n_backtested_wallets | > 0 | {result['n_backtested_wallets']} | "
            f"{'**PASS**' if result['n_backtested_wallets'] > 0 else '**FAIL**'} |",
            f"| n_trades | >= 100 | {stats['n_trades']} | "
            f"{'**PASS**' if stats['n_trades'] >= 100 else '**FAIL**'} |",
            f"| Sharpe | >= 1.2 | {_fmt_num(stats['sharpe'], 2)} | "
            f"{'**PASS**' if float(stats['sharpe']) >= 1.2 else '**FAIL**'} |",
            f"| Max DD | >= -25% | {_fmt_pct(stats['max_dd'])} | "
            f"{'**PASS**' if float(stats['max_dd']) >= -0.25 else '**FAIL**'} |",
            "",
            "## Funnel",
            "",
            "| step | count | filter |",
            "| --- | ---: | --- |",
            f"| fills | {funnel['fills']} | cached wallet fills loaded |",
            f"| in_size | {funnel['in_size']} | open fills with $1k-$200k notional |",
            f"| with_candle | {funnel['with_candle']} | signal fills whose coin candles loaded |",
            f"| trades | {funnel['trades']} | aligned entry/exit trades executed |",
            "",
            "## Portfolio Stats",
            "",
            "| Metric | Value |",
            "| --- | --- |",
            f"| Hourly Sharpe | {_fmt_num(stats['sharpe'], 2)} |",
            f"| Trade-level IR | {_fmt_num(stats['trade_level_ir'], 2)} |",
            f"| Daily Sharpe | {_fmt_num(stats['daily_sharpe'], 2)} |",
            f"| Sortino | {_fmt_num(stats['sortino'], 2)} |",
            f"| Max DD | {_fmt_pct(stats['max_dd'])} |",
            f"| n_trades | {stats['n_trades']} |",
            f"| win_rate | {_fmt_pct(stats['win_rate'])} |",
            f"| total_return | {_fmt_pct(stats['total_return'])} |",
            f"| final equity | {_fmt_money(stats['equity_final'])} |",
            "",
            "## Per-Wallet Stats",
            "",
            "| wallet | hourly_sharpe | trade_level_ir | daily_sharpe | sortino | max_dd | n_trades | win_rate | total_return | n_coins | equity_final |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
            *_wallet_rows(result["per_wallet_stats"]),
            "",
            "## Equity Curve",
            "",
            "| date | summed_equity |",
            "| --- | ---: |",
            *_equity_rows(equity),
        ]
    )
    path.write_text("\n".join(lines) + "\n")


def _wallet_rows(rows: list[dict[str, Any]]) -> list[str]:
    if not rows:
        return ["| - | - | - | - | - | - | - | - | - | - | - |"]
    return [
        "| {wallet} | {sharpe} | {trade_level_ir} | {daily_sharpe} | {sortino} | "
        "{max_dd} | {n_trades} | {win_rate} | {total_return} | {n_coins} | "
        "{equity_final} |".format(
            wallet=row["wallet"],
            sharpe=_fmt_num(row["sharpe"], 2),
            trade_level_ir=_fmt_num(row["trade_level_ir"], 2),
            daily_sharpe=_fmt_num(row["daily_sharpe"], 2),
            sortino=_fmt_num(row["sortino"], 2),
            max_dd=_fmt_pct(row["max_dd"]),
            n_trades=row["n_trades"],
            win_rate=_fmt_pct(row["win_rate"]),
            total_return=_fmt_pct(row["total_return"]),
            n_coins=row["n_coins"],
            equity_final=_fmt_money(row["equity_final"]),
        )
        for row in rows
    ]


def _equity_rows(equity: pd.Series) -> list[str]:
    if equity.empty:
        return ["| - | - |"]
    monthly = equity.resample("ME").last().dropna()
    if monthly.empty:
        last = equity.dropna().iloc[-1]
        return [f"| {equity.dropna().index[-1].strftime('%Y-%m-%d %H:%M')} | {_fmt_money(last)} |"]
    return [f"| {index.strftime('%Y-%m-%d')} | {_fmt_money(value)} |" for index, value in monthly.items()]


def _coerce_utc_index(index: pd.Index) -> pd.DatetimeIndex:
    ts_index = pd.DatetimeIndex(pd.to_datetime(index, utc=True), name="timestamp")
    return ts_index


def _coerce_utc_timestamp(value: Any) -> pd.Timestamp:
    ts = pd.Timestamp(value)
    if ts.tz is None:
        return ts.tz_localize("UTC")
    return ts.tz_convert("UTC")


def _daily_sharpe(equity: pd.Series) -> float:
    daily_equity = equity.resample("1D").last().dropna()
    returns = daily_equity.pct_change().dropna()
    return sharpe_ratio(returns, periods_per_year("1D"))


def _trade_level_ir(trades: list[dict[str, Any]]) -> float:
    if not trades:
        return 0.0

    returns = pd.Series([float(trade["return"]) for trade in trades], dtype="float64").dropna()
    if returns.empty:
        return 0.0

    entry_times = [_coerce_utc_timestamp(trade["entry_time"]) for trade in trades]
    exit_times = [_coerce_utc_timestamp(trade["exit_time"]) for trade in trades]
    total_days = (max(exit_times) - min(entry_times)).total_seconds() / 86_400.0
    if total_days <= 0:
        return 0.0

    annual_trade_freq = len(returns) / total_days * 365.0
    volatility = float(returns.std(ddof=0))
    mean_return = float(returns.mean())
    if volatility == 0:
        if mean_return > 0:
            return float("inf")
        if mean_return < 0:
            return float("-inf")
        return 0.0
    return mean_return / volatility * math.sqrt(annual_trade_freq)


def _backtest_freq(interval: str) -> str:
    if interval.lower() == "1d":
        return "1D"
    return interval


def _fmt_pct(value: Any) -> str:
    return f"{float(value) * 100:.2f}%"


def _fmt_num(value: Any, decimals: int) -> str:
    number = float(value)
    if not math.isfinite(number):
        return "n/a"
    return f"{number:.{decimals}f}"


def _fmt_money(value: Any) -> str:
    return f"${float(value):,.2f}"


def _sort_sharpe(row: dict[str, Any]) -> float:
    value = float(row["sharpe"])
    return value if math.isfinite(value) else float("-inf")


def _log(message: str) -> None:
    print(message, file=sys.stderr)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run wallet reverse backtest.")
    parser.add_argument("--holding-hours", type=float, default=4.0)
    parser.add_argument("--top-wallet-n", type=int, default=50)
    parser.add_argument("--candle-interval", default="1h")
    parser.add_argument("--init-cash", type=float, default=10_000.0)
    parser.add_argument("--fees", type=float, default=0.0005)
    parser.add_argument("--slippage", type=float, default=0.0002)
    parser.add_argument("--report", type=Path, default=Path("reports/wallet_reverse_v1_backtest.md"))
    args = parser.parse_args()
    _validate_args(parser, args)
    return args


def _validate_args(parser: argparse.ArgumentParser, args: argparse.Namespace) -> None:
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
    try:
        interval_timedelta(args.candle_interval)
    except ValueError as error:
        parser.error(str(error))


def main() -> int:
    args = _parse_args()
    result = run_wallet_reverse_backtest(
        WalletReverseBacktestConfig(
            holding_hours=args.holding_hours,
            top_wallet_n=args.top_wallet_n,
            candle_interval=args.candle_interval,
            init_cash=args.init_cash,
            fees=args.fees,
            slippage=args.slippage,
            report=args.report,
        )
    )
    print(f"wrote report: {result['report_path']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
