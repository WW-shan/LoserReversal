"""End-to-end demo: fetch BTC daily, run SMA(10,30), output report.

Usage:
    uv run python -m scripts.run_btc_sma_e2e [--days 180]
"""

import argparse
from datetime import datetime, timedelta, timezone
from pathlib import Path

from infra.backtest.engine import INTERVAL_TABLE, BacktestConfig
from infra.backtest.toy import sma_crossover_signals
from infra.pipeline import PipelineConfig, run_pipeline
from infra.report import write_backtest_report


REPO_ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", default="BTC")
    parser.add_argument("--days", type=int, default=180)
    parser.add_argument("--fast", type=int, default=10)
    parser.add_argument("--slow", type=int, default=30)
    args = parser.parse_args()
    _validate_args(parser, args)

    end = _last_completed_candle_end("1d", datetime.now(tz=timezone.utc))
    start = end - timedelta(days=args.days)

    config = PipelineConfig(
        symbol=args.symbol,
        interval="1d",
        start=start,
        end=end,
        backtest_config=BacktestConfig(),
    )
    result = run_pipeline(
        config,
        lambda prices: sma_crossover_signals(prices, fast=args.fast, slow=args.slow),
    )

    out = REPO_ROOT / "reports" / f"backtest_{args.symbol.lower()}_sma{args.fast}-{args.slow}.md"
    write_backtest_report(
        out,
        title=f"{args.symbol} SMA({args.fast},{args.slow}) - {args.days}d",
        config_summary={
            "symbol": args.symbol,
            "interval": "1d",
            "days": args.days,
            "fast": args.fast,
            "slow": args.slow,
        },
        result=result,
    )
    print(
        f"verdict: Sharpe={result.stats['sharpe']:.2f}  "
        f"MaxDD={result.stats['max_dd']:.2%}  "
        f"n_trades={result.stats['n_trades']}  -> {out}"
    )
    return 0


def _validate_args(parser: argparse.ArgumentParser, args: argparse.Namespace) -> None:
    if args.days <= 0:
        parser.error("--days must be greater than 0")
    if args.fast <= 0:
        parser.error("--fast must be greater than 0")
    if args.slow <= 0:
        parser.error("--slow must be greater than 0")
    if args.fast >= args.slow:
        parser.error("--fast must be less than --slow")
    if "/" in args.symbol or "\\" in args.symbol or ".." in args.symbol:
        parser.error("--symbol must not contain path separators or '..'")


def _last_completed_candle_end(interval: str, now: datetime) -> datetime:
    delta = _fixed_interval_delta(interval)
    aware_now = now if now.tzinfo is not None else now.replace(tzinfo=timezone.utc)
    aware_now = aware_now.astimezone(timezone.utc)
    epoch = datetime(1970, 1, 1, tzinfo=timezone.utc)
    completed = (aware_now - epoch) // delta
    return epoch + completed * delta


def _fixed_interval_delta(interval: str) -> timedelta:
    unit = interval[-1]
    if interval in INTERVAL_TABLE and unit in {"m", "h", "d", "D"}:
        return INTERVAL_TABLE[interval][1].to_pytimedelta()

    try:
        amount = int(interval[:-1])
    except ValueError as error:
        raise ValueError(f"Unsupported fixed interval: {interval}") from error

    if unit == "m":
        return timedelta(minutes=amount)
    if unit == "h":
        return timedelta(hours=amount)
    if unit in {"d", "D"}:
        return timedelta(days=amount)
    raise ValueError(f"Unsupported fixed interval: {interval}")


if __name__ == "__main__":
    raise SystemExit(main())
