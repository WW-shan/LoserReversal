"""Run the unlock-short strategy over real Hyperliquid candle data."""

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

from infra.backtest.engine import BacktestConfig, BacktestResult, periods_per_year, run_backtest
from infra.backtest.risk import max_drawdown, sharpe_ratio, sortino_ratio
from infra.fetchers.candles import fetch_candles
from infra.hyperliquid_client import HyperliquidClient
from infra.pipeline import PipelineConfig, candles_cover_range, interval_timedelta
from infra.storage import read_candles, read_unlocks, write_candles
from signals.unlock_v1 import unlock_short_signal


CACHE_ERRORS = (FileNotFoundError, OSError, duckdb.Error)


@dataclass(frozen=True)
class UnlockBacktestConfig:
    pre_window_days: int = 7
    min_unlock_pct: float = 0.02
    interval: str = "1d"
    init_cash: float = 10_000.0
    fees: float = 0.0005
    slippage: float = 0.0002
    date_start: datetime | None = None
    date_end: datetime | None = None
    report: Path | None = Path("reports/unlock_v1_backtest.md")
    skip_tokens: set[str] | None = None


def run_unlock_backtest(config: UnlockBacktestConfig) -> dict[str, Any]:
    started = time.perf_counter()
    freq = _backtest_freq(config.interval)
    skip_tokens = set(config.skip_tokens or ())
    failed_tokens: set[str] = set()
    events = read_unlocks()
    funnel = {
        "total_events": int(len(events)),
        "has_hl_perp_events": 0,
        "pct_threshold_events": 0,
        "date_start_events": 0,
        "date_end_events": 0,
        "candle_ok_events": 0,
        "in_range_events": 0,
        "non_overlap_events": 0,
    }
    events = events.loc[_coerce_bool_series(events["has_hl_perp"])].copy()
    funnel["has_hl_perp_events"] = int(len(events))
    events["token"] = events["token"].astype("string")
    events["unlock_date"] = pd.to_datetime(events["unlock_date"], utc=True, errors="coerce")
    events = events.dropna(subset=["token", "unlock_date"])
    events["unlock_pct"] = pd.to_numeric(events["unlock_pct"], errors="coerce")
    events = events.dropna(subset=["unlock_pct"])
    events = events.loc[events["unlock_pct"] >= config.min_unlock_pct].copy()
    funnel["pct_threshold_events"] = int(len(events))
    if config.date_start is not None:
        events = events.loc[events["unlock_date"] >= config.date_start].copy()
    funnel["date_start_events"] = int(len(events))
    if config.date_end is not None:
        events = events.loc[events["unlock_date"] <= config.date_end].copy()
    funnel["date_end_events"] = int(len(events))

    if events.empty:
        result = _empty_result(config, started, funnel, freq)
        if config.report is not None:
            _write_report(config.report, config, result)
        return result

    start = events["unlock_date"].min() - pd.Timedelta(days=30)
    end = events["unlock_date"].max() + pd.Timedelta(days=7)
    tokens = list(events["token"].dropna().unique())
    n_candidate_tokens = len(tokens)
    prices: dict[str, pd.Series] = {}
    token_positions = {token: index for index, token in enumerate(tokens, start=1)}
    client = HyperliquidClient()

    for token in tokens:
        if token in skip_tokens:
            failed_tokens.add(token)
            continue

        index = token_positions[token]
        token_started = time.perf_counter()
        cached = True
        try:
            candles, cached = _load_or_fetch_candles(token, config.interval, start, end, client)
        except (FileNotFoundError, OSError, duckdb.Error, ValueError, ConnectionError) as error:
            failed_tokens.add(token)
            elapsed = time.perf_counter() - token_started
            _log(
                f"[{index}/{len(tokens)}] warning: skipping {token} candles: "
                f"{error} ({elapsed:.1f}s)"
            )
            continue

        elapsed = time.perf_counter() - token_started
        source = "from cache" if cached else "from HL"
        verb = "loading" if cached else "fetching"
        _log(
            f"[{index}/{len(tokens)}] {verb} {token} candles {source}... "
            f"cached={cached} ({elapsed:.1f}s)"
        )

        close = candles["close"].astype("float64").dropna()
        if close.empty:
            failed_tokens.add(token)
            _log(f"[{index}/{len(tokens)}] warning: skipping {token}: no candle data")
            continue
        prices[token] = close

    funnel["candle_ok_events"] = int(events.loc[events["token"].isin(prices)].shape[0])
    funnel["in_range_events"] = _count_in_range_events(events, prices, config.pre_window_days)

    signals = unlock_short_signal(
        events,
        prices,
        pre_window_days=config.pre_window_days,
        min_unlock_pct=config.min_unlock_pct,
        require_hl_perp=True,
    )

    backtest_config = BacktestConfig(
        direction="shortonly",
        init_cash=config.init_cash,
        fees=config.fees,
        slippage=config.slippage,
        freq=freq,
    )
    token_stats: list[dict[str, Any]] = []
    equities: list[pd.Series] = []

    for token in tokens:
        if token not in prices:
            continue

        index = token_positions[token]
        token_signal = signals.get(token)
        signal_trades = int(token_signal[0].sum()) if token_signal is not None else 0
        _log(f"[{index}/{len(tokens)}] signal generated: {signal_trades} trades")
        if token_signal is None:
            entries = pd.Series(False, index=prices[token].index, dtype=bool)
            exits = pd.Series(False, index=prices[token].index, dtype=bool)
        else:
            entries, exits = token_signal
        result = run_backtest(prices[token], entries, exits, backtest_config)
        stats = _token_stats(token, result)
        token_stats.append(stats)
        equities.append(result.equity.rename(token))
        _log(
            f"[{index}/{len(tokens)}] backtest: Sharpe={stats['sharpe']:.2f} "
            f"MaxDD={stats['max_dd']:.1%}"
        )

    portfolio_equity = _summed_equity(equities, config.init_cash)
    funnel["non_overlap_events"] = int(sum(int(entries.sum()) for entries, _ in signals.values()))
    portfolio_stats = _portfolio_stats(portfolio_equity, token_stats, config, freq)
    n_backtested_tokens = len(token_stats)
    output = {
        "config": config,
        "backtest_freq": freq,
        "n_candidate_tokens": n_candidate_tokens,
        "n_backtested_tokens": n_backtested_tokens,
        "n_events_with_signal": funnel["non_overlap_events"],
        "funnel": funnel,
        "portfolio_stats": portfolio_stats,
        "per_token_stats": sorted(token_stats, key=_sort_sharpe, reverse=True),
        "portfolio_equity": portfolio_equity,
        "runtime_seconds": time.perf_counter() - started,
        "report_path": config.report,
        "failed_tokens": sorted(failed_tokens),
    }

    if config.report is not None:
        _write_report(config.report, config, output)
    return output


def _backtest_freq(interval: str) -> str:
    if interval.lower() == "1d":
        return "1D"
    return interval


def _load_or_fetch_candles(
    token: str,
    interval: str,
    start: pd.Timestamp,
    end: pd.Timestamp,
    client: HyperliquidClient,
) -> tuple[pd.DataFrame, bool]:
    pipeline_config = PipelineConfig(symbol=token, interval=interval, start=start, end=end)
    try:
        candles = read_candles(token, interval, start=start, end=end)
    except CACHE_ERRORS:
        return _fetch_store_load_candles(token, interval, start, end, client), False

    if not candles_cover_range(candles, pipeline_config):
        return _fetch_store_load_candles(token, interval, start, end, client), False
    return candles, True


def _fetch_store_load_candles(
    token: str,
    interval: str,
    start: pd.Timestamp,
    end: pd.Timestamp,
    client: HyperliquidClient,
) -> pd.DataFrame:
    candles = fetch_candles(token, interval, start, end, client=client)
    if candles.empty:
        raise ValueError("HL returned no candles")

    write_candles(candles, token, interval)
    loaded = read_candles(token, interval, start=start, end=end)
    if loaded.empty:
        raise ValueError("cached candles are empty after reload")
    return loaded


def _token_stats(token: str, result: BacktestResult) -> dict[str, Any]:
    n_trades = int(result.stats.get("n_trades", 0))
    win_rate = float(result.stats.get("win_rate", 0.0))
    equity_final = float(result.equity.iloc[-1]) if not result.equity.empty else 0.0
    return {
        "token": token,
        "sharpe": float(result.stats.get("sharpe", 0.0)),
        "sortino": float(result.stats.get("sortino", 0.0)),
        "max_dd": float(result.stats.get("max_dd", 0.0)),
        "n_trades": n_trades,
        "total_return": float(result.stats.get("total_return", 0.0)),
        "win_rate": win_rate,
        "equity_final": equity_final,
        "trades_won": win_rate * n_trades,
    }


def _summed_equity(equities: list[pd.Series], init_cash: float) -> pd.Series:
    """Per-token equity reindexed to union date range, leading gaps filled with init_cash
    (holding cash), trailing gaps ffilled (position held)."""
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


def _count_in_range_events(
    events: pd.DataFrame,
    prices: dict[str, pd.Series],
    pre_window_days: int,
) -> int:
    if events.empty or not prices:
        return 0

    count = 0
    for token, token_events in events.groupby("token", sort=False):
        token_name = str(token)
        series = prices.get(token_name)
        if series is None:
            continue

        price_index = pd.DatetimeIndex(series.index)
        if price_index.tz is None:
            close_index = pd.DatetimeIndex(price_index, tz="UTC")
        else:
            close_index = price_index.tz_convert("UTC")
        if close_index.empty:
            continue

        for unlock_ts in token_events["unlock_date"]:
            entry_ts = unlock_ts - pd.Timedelta(days=pre_window_days)
            if entry_ts in close_index and unlock_ts in close_index:
                count += 1

    return count


def _portfolio_stats(
    equity: pd.Series,
    token_stats: list[dict[str, Any]],
    config: UnlockBacktestConfig,
    freq: str,
) -> dict[str, Any]:
    n_trades = sum(int(row["n_trades"]) for row in token_stats)
    trades_won = sum(float(row["trades_won"]) for row in token_stats)
    returns = equity.pct_change().dropna()
    equity_final = float(equity.iloc[-1]) if not equity.empty else 0.0
    equity_first = float(equity.iloc[0]) if not equity.empty else 0.0
    return {
        "sharpe": sharpe_ratio(returns, periods_per_year(freq)),
        "sortino": sortino_ratio(returns, periods_per_year(freq)),
        "max_dd": max_drawdown(equity),
        "n_trades": n_trades,
        "win_rate": trades_won / n_trades if n_trades else 0.0,
        "total_return": equity_final / equity_first - 1.0 if equity_first else 0.0,
        "equity_final": equity_final,
        "capital_per_token": config.init_cash,
    }


def _empty_result(
    config: UnlockBacktestConfig,
    started: float,
    funnel: dict[str, int],
    freq: str,
) -> dict[str, Any]:
    equity = pd.Series(dtype="float64", name="equity")
    return {
        "config": config,
        "backtest_freq": freq,
        "n_candidate_tokens": 0,
        "n_backtested_tokens": 0,
        "n_events_with_signal": 0,
        "funnel": funnel,
        "portfolio_stats": _portfolio_stats(equity, [], config, freq),
        "per_token_stats": [],
        "portfolio_equity": equity,
        "runtime_seconds": time.perf_counter() - started,
        "report_path": config.report,
        "failed_tokens": [],
    }


def _write_report(path: Path, config: UnlockBacktestConfig, result: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    generated = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    stats = result["portfolio_stats"]
    equity = result["portfolio_equity"]
    per_token_stats = result["per_token_stats"]
    funnel = result["funnel"]
    freq = result["backtest_freq"]
    n_candidate_tokens = int(result["n_candidate_tokens"])
    n_backtested_tokens = int(result["n_backtested_tokens"])
    n_failed_tokens = n_candidate_tokens - n_backtested_tokens

    lines = [
        "# Unlock Short V1 Backtest",
        "",
        f"_Generated {generated}_",
        "",
        "## Config",
        "",
        "| Key | Value |",
        "| --- | --- |",
        f"| pre_window_days | {config.pre_window_days} |",
        f"| min_unlock_pct | {config.min_unlock_pct:.4f} |",
        f"| fees | {config.fees:.6f} |",
        f"| slippage | {config.slippage:.6f} |",
        f"| freq | {freq} |",
        f"| n_candidate_tokens | {n_candidate_tokens} |",
        f"| n_backtested_tokens | {n_backtested_tokens} |",
        f"| n_failed_tokens | {n_failed_tokens} |",
        f"| failed_tokens | {result['failed_tokens']!r} |",
        f"| n_events_with_signal | {result['n_events_with_signal']} |",
        "| portfolio_model | Per-token init_cash assumed for **backtested** tokens only; "
        "leading gaps = init_cash (cash held); trailing gaps = last equity (position held); "
        "portfolio = sum across backtested tokens. Failed-fetch tokens are NOT included "
        "in the portfolio capital base. |",
        "",
    ]

    if stats["n_trades"] < 30:
        lines.extend(
            [
                "> [WARN] INSUFFICIENT SAMPLE: only "
                f"{stats['n_trades']} trades. Sharpe is NOT decision-quality. "
                "Do not use this report for Pass/Kill.",
                "",
            ]
        )

    lines.extend(
        [
            "## Decision Gate Check",
            "",
            "| Check | Threshold | Value | Status |",
            "| --- | --- | --- | --- |",
            f"| n_backtested_tokens | > 0 | {n_backtested_tokens} | "
            f"{'**PASS**' if n_backtested_tokens > 0 else '**FAIL**'} |",
            f"| n_trades | >= 30 | {stats['n_trades']} | "
            f"{'**PASS**' if stats['n_trades'] >= 30 else '**FAIL**'} |",
            f"| Sharpe | >= 1.0 | {_fmt_num(stats['sharpe'], 2)} | "
            f"{'**PASS**' if float(stats['sharpe']) >= 1.0 else '**FAIL**'} |",
            f"| Max DD | >= -25% | {_fmt_pct(stats['max_dd'])} | "
            f"{'**PASS**' if float(stats['max_dd']) >= -0.25 else '**FAIL**'} |",
            "",
            "## Event Funnel",
            "",
            "| step | events | filter |",
            "| --- | ---: | --- |",
            *_event_funnel_rows(funnel, config),
            "",
            "## Portfolio Stats",
            "",
            "| Metric | Value |",
            "| --- | --- |",
            f"| Sharpe | {_fmt_num(stats['sharpe'], 2)} |",
            f"| Sortino | {_fmt_num(stats['sortino'], 2)} |",
            f"| Max DD | {_fmt_pct(stats['max_dd'])} |",
            f"| n_trades | {stats['n_trades']} |",
            f"| win_rate | {_fmt_pct(stats['win_rate'])} |",
            f"| total_return | {_fmt_pct(stats['total_return'])} |",
            f"| final equity | {_fmt_money(stats['equity_final'])} |",
            "",
            "## Per-Token Stats",
            "",
            "| token | sharpe | sortino | max_dd | n_trades | total_return | win_rate | equity_final |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
            *_per_token_rows(per_token_stats),
            "",
            "## Equity Curve",
            "",
            "| date | summed_equity |",
            "| --- | ---: |",
            *_equity_rows(equity),
        ]
    )
    path.write_text("\n".join(lines) + "\n")


def _per_token_rows(rows: list[dict[str, Any]]) -> list[str]:
    if not rows:
        return ["| - | - | - | - | - | - | - | - |"]

    return [
        "| {token} | {sharpe} | {sortino} | {max_dd} | {n_trades} | {total_return} | "
        "{win_rate} | {equity_final} |".format(
            token=row["token"],
            sharpe=_fmt_num(row["sharpe"], 2),
            sortino=_fmt_num(row["sortino"], 2),
            max_dd=_fmt_pct(row["max_dd"]),
            n_trades=row["n_trades"],
            total_return=_fmt_pct(row["total_return"]),
            win_rate=_fmt_pct(row["win_rate"]),
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
        return [f"| {equity.dropna().index[-1].strftime('%Y-%m-%d')} | {_fmt_money(last)} |"]
    return [f"| {index.strftime('%Y-%m-%d')} | {_fmt_money(value)} |" for index, value in monthly.items()]


def _event_funnel_rows(funnel: dict[str, int], config: UnlockBacktestConfig) -> list[str]:
    return [
        f"| total_events | {funnel['total_events']} | input rows |",
        f"| has_hl_perp_events | {funnel['has_hl_perp_events']} | has_hl_perp == True |",
        f"| pct_threshold_events | {funnel['pct_threshold_events']} | unlock_pct >= {config.min_unlock_pct:.4f} |",
        f"| date_start_events | {funnel['date_start_events']} | {_date_start_filter(config)} |",
        f"| date_end_events | {funnel['date_end_events']} | {_date_end_filter(config)} |",
        f"| candle_ok_events | {funnel['candle_ok_events']} | candles loaded successfully |",
        f"| in_range_events | {funnel['in_range_events']} | entry + unlock dates in candle index |",
        f"| non_overlap_events | {funnel['non_overlap_events']} | non-overlapping entries fired |",
    ]


def _date_start_filter(config: UnlockBacktestConfig) -> str:
    if config.date_start is None:
        return "date_start disabled"
    return f"unlock_date >= {config.date_start:%Y-%m-%d}"


def _date_end_filter(config: UnlockBacktestConfig) -> str:
    if config.date_end is None:
        return "date_end disabled"
    return f"unlock_date <= {config.date_end:%Y-%m-%d}"


def _coerce_bool_series(series: pd.Series) -> pd.Series:
    if pd.api.types.is_bool_dtype(series):
        return series.astype("bool")
    return series.astype("string").str.lower().isin({"true", "1", "yes", "y"})


def _fmt_pct(value: Any) -> str:
    return f"{float(value) * 100:.2f}%"


def _fmt_num(value: Any, decimals: int) -> str:
    number = float(value)
    if not math.isfinite(number):
        return "n/a"
    return f"{number:.{decimals}f}"


def _fmt_money(value: Any) -> str:
    return f"${float(value):,.2f}"


def _log(message: str) -> None:
    print(message, file=sys.stderr)


def _sort_sharpe(row: dict[str, Any]) -> float:
    value = float(row["sharpe"])
    return value if math.isfinite(value) else float("-inf")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run unlock-short backtest on HL candle data.")
    parser.add_argument("--pre-window-days", type=int, default=7)
    parser.add_argument("--min-unlock-pct", type=float, default=0.02)
    parser.add_argument("--interval", default="1d")
    parser.add_argument("--init-cash", type=float, default=10_000.0)
    parser.add_argument("--fees", type=float, default=0.0005)
    parser.add_argument("--slippage", type=float, default=0.0002)
    parser.add_argument("--report", type=Path, default=Path("reports/unlock_v1_backtest.md"))
    args = parser.parse_args()
    _validate_args(parser, args)
    return args


def _validate_args(parser: argparse.ArgumentParser, args: argparse.Namespace) -> None:
    if args.pre_window_days < 1:
        parser.error("--pre-window-days must be at least 1")
    if args.min_unlock_pct < 0:
        parser.error("--min-unlock-pct must be non-negative")
    if args.init_cash <= 0:
        parser.error("--init-cash must be greater than 0")
    if args.fees < 0:
        parser.error("--fees must be non-negative")
    if args.slippage < 0:
        parser.error("--slippage must be non-negative")
    if not args.interval:
        parser.error("--interval must not be empty")
    try:
        interval_timedelta(args.interval)
    except ValueError as error:
        parser.error(str(error))


def main() -> int:
    args = _parse_args()
    config = UnlockBacktestConfig(
        pre_window_days=args.pre_window_days,
        min_unlock_pct=args.min_unlock_pct,
        interval=args.interval,
        init_cash=args.init_cash,
        fees=args.fees,
        slippage=args.slippage,
        report=args.report,
    )
    result = run_unlock_backtest(config)
    print(f"wrote report: {result['report_path']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
