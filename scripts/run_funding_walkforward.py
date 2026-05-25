"""Walk-forward CLI for the funding-extreme contrarian signal."""

from __future__ import annotations

import argparse
import math
from collections.abc import Sequence
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from infra.storage import PARQUET_DIR
from signals.funding_walkforward import (
    DEFAULT_MIN_IS_TRADES,
    DEFAULT_N_SPLITS,
    DEFAULT_SLIPPAGE,
    DEFAULT_TAKER_FEE,
    DEFAULT_TEST_DAYS,
    DEFAULT_TRAIN_DAYS,
    build_expanding_splits,
    run_walkforward,
    verdict_from_aggregate,
)

try:
    from scripts.run_funding_extreme_backtest import load_funding_history, load_prices
except ModuleNotFoundError:
    from run_funding_extreme_backtest import load_funding_history, load_prices


DEFAULT_FUNDING_DIR = PARQUET_DIR / "funding"
DEFAULT_CANDLES_DIR = PARQUET_DIR / "candles"
DEFAULT_OUT = PARQUET_DIR / "funding_walkforward.parquet"
DEFAULT_REPORT = Path("reports/funding_walkforward.md")


def run(
    funding_dir: Path,
    candles_dir: Path,
    out: Path,
    report: Path,
    *,
    n_splits: int = DEFAULT_N_SPLITS,
    train_days: int = DEFAULT_TRAIN_DAYS,
    test_days: int = DEFAULT_TEST_DAYS,
    min_is_trades: int = DEFAULT_MIN_IS_TRADES,
    taker_fee: float = DEFAULT_TAKER_FEE,
    slippage: float = DEFAULT_SLIPPAGE,
) -> dict[str, object]:
    funding_history = load_funding_history(funding_dir)
    prices = load_prices(candles_dir)
    if not funding_history:
        raise RuntimeError(f"no funding history found in {funding_dir}")

    history_start, history_end = _history_span(funding_history, prices)
    splits = build_expanding_splits(
        history_start,
        history_end,
        n_splits=n_splits,
        train_days=train_days,
        test_days=test_days,
    )
    if not splits:
        raise RuntimeError(
            f"history too short for requested splits "
            f"(effective span {(history_end - history_start).days}d, "
            f"need >= {train_days + test_days}d)"
        )

    frame = run_walkforward(
        funding_history,
        prices,
        splits,
        min_n_trades=min_is_trades,
        taker_fee=taker_fee,
        slippage=slippage,
    )

    out.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(out, index=False)

    aggregate = frame.loc[frame["split_idx"] == -1].iloc[0] if not frame.empty else None
    verdict = verdict_from_aggregate(aggregate.to_dict()) if aggregate is not None else "RED"

    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(
        _format_report(
            frame,
            verdict,
            history_start=history_start,
            history_end=history_end,
            n_splits=len(splits),
            train_days=train_days,
            test_days=test_days,
            taker_fee=taker_fee,
            slippage=slippage,
        ),
        encoding="utf-8",
    )

    print(f"verdict: {verdict}")
    print(f"wrote parquet: {out}")
    print(f"wrote report: {report}")
    return {"frame": frame, "verdict": verdict, "out": out, "report": report}


def _history_span(
    funding_history: dict[str, pd.DataFrame],
    prices: dict[str, pd.Series] | None = None,
) -> tuple[pd.Timestamp, pd.Timestamp]:
    """Effective walk-forward span requires BOTH funding AND price data.

    If `prices` is supplied, the span is restricted to where at least one
    token has overlapping coverage. Phase 3 1h candle backfill currently
    only covers ~90 days while funding extends 3 years; honouring the
    intersection prevents the walkforward from picking train/test windows
    with no price data.
    """
    candidates_start: list[pd.Timestamp] = []
    candidates_end: list[pd.Timestamp] = []
    for token, frame in funding_history.items():
        if frame.empty:
            continue
        funding_start = pd.Timestamp(frame.index.min()).tz_convert("UTC")
        funding_end = pd.Timestamp(frame.index.max()).tz_convert("UTC")
        if prices is not None and token in prices:
            price = prices[token]
            if price.empty:
                continue
            price_start = pd.Timestamp(price.index.min()).tz_convert("UTC")
            price_end = pd.Timestamp(price.index.max()).tz_convert("UTC")
            candidates_start.append(max(funding_start, price_start))
            candidates_end.append(min(funding_end, price_end))
        elif prices is None:
            candidates_start.append(funding_start)
            candidates_end.append(funding_end)
    if not candidates_start or not candidates_end:
        raise RuntimeError("no funding/price overlap available")
    return min(candidates_start), max(candidates_end)


def _format_report(
    frame: pd.DataFrame,
    verdict: str,
    *,
    history_start: pd.Timestamp,
    history_end: pd.Timestamp,
    n_splits: int,
    train_days: int,
    test_days: int,
    taker_fee: float,
    slippage: float,
) -> str:
    generated = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    per_split = frame.loc[frame["split_idx"] >= 0].sort_values("split_idx")
    aggregate = frame.loc[frame["split_idx"] == -1]

    lines = [
        "# Phase 3 Funding Extreme Contrarian Walk-Forward",
        "",
        f"_Generated {generated}_",
        "",
        f"## Verdict: {verdict}",
        "",
        _verdict_blurb(verdict),
        "",
        "## Methodology",
        "",
        "- Expanding-window walk-forward: 5 splits, train 270d, test 180d per Phase 3 plan.",
        "- IS step: sweep the same 48-cell grid as `sweep_funding_extreme_grid.py` over "
        "the train window; pick top-1 by aggregate Sharpe with n_trades >= 5.",
        "- OOS step: apply the selected (z, hold, lookback) to the test window only; "
        "record aggregate Sharpe / annualized / MaxDD / win_rate / n_trades.",
        "- Aggregate row averages OOS Sharpe and annualized over splits, takes worst MaxDD, "
        "and pools win_rate by trade count.",
        "- Funding/price slicing uses `(index >= window_start) & (index < window_end)` so "
        "splits do not overlap a single hourly bar.",
        "",
        "## Config",
        "",
        "| key | value |",
        "| --- | --- |",
        f"| history_start | {history_start.isoformat()} |",
        f"| history_end | {history_end.isoformat()} |",
        f"| n_splits | {n_splits} |",
        f"| train_days | {train_days} |",
        f"| test_days | {test_days} |",
        f"| taker_fee | {taker_fee:.6f} |",
        f"| slippage | {slippage:.6f} |",
        "",
        "## Per-Split Results",
        "",
        _per_split_table(per_split),
        "",
        "## Aggregate",
        "",
        _aggregate_table(aggregate),
        "",
        "## Verdict thresholds (reframed Phase 3 per blocker.md)",
        "",
        "- GREEN: OOS Sharpe >= 1.2 AND annualized >= 20%",
        "- YELLOW: OOS Sharpe in [0.5, 1.2) AND annualized >= 10%",
        "- RED: OOS Sharpe < 0.5 OR negative annualized",
    ]
    return "\n".join(lines) + "\n"


def _verdict_blurb(verdict: str) -> str:
    return {
        "GREEN": (
            "Walk-forward OOS aggregate clears Sharpe >= 1.2 AND annualized >= 20%. "
            "Funding extreme contrarian is deployment-eligible (alongside Phase 1.5 "
            "unlock short) as a low-weight portfolio component."
        ),
        "YELLOW": (
            "Walk-forward OOS Sharpe falls in [0.5, 1.2) with annualized >= 10%. "
            "Tradeable as a low-conviction sleeve; needs cross-thesis diversification "
            "(Phase 2.5 wallet, Phase 5 portfolio) before live deployment."
        ),
        "RED": (
            "OOS Sharpe < 0.5 or negative annualized. The IS edge does not survive "
            "out-of-sample selection. Kill funding-extreme as a standalone signal."
        ),
    }.get(verdict, "Unknown verdict.")


def _per_split_table(per_split: pd.DataFrame) -> str:
    header = (
        "| split | is_start | is_end | oos_start | oos_end | z | hold | lookback | "
        "is_n | is_sharpe | oos_n | oos_sharpe | oos_ann | oos_max_dd | oos_win_rate | decay |"
    )
    divider = "| ---: | --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |"
    lines = [header, divider]
    if per_split.empty:
        lines.append("| - | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - |")
        return "\n".join(lines)
    for row in per_split.to_dict("records"):
        lines.append(
            "| {idx} | {is_s} | {is_e} | {oos_s} | {oos_e} | {z} | {hold} | {lb} | "
            "{is_n} | {is_sh} | {oos_n} | {oos_sh} | {oos_ann} | {oos_dd} | {wr} | {dc} |".format(
                idx=int(row["split_idx"]),
                is_s=_iso_date(row["is_start"]),
                is_e=_iso_date(row["is_end"]),
                oos_s=_iso_date(row["oos_start"]),
                oos_e=_iso_date(row["oos_end"]),
                z=_num(row["z_threshold"], 1),
                hold=_int(row["hold_hours"]),
                lb=_int(row["lookback_days"]),
                is_n=_int(row["is_n_trades"]),
                is_sh=_num(row["is_sharpe"], 2),
                oos_n=_int(row["oos_n_trades"]),
                oos_sh=_num(row["oos_sharpe"], 2),
                oos_ann=_pct(row["oos_annualized"]),
                oos_dd=_pct(row["oos_max_dd"]),
                wr=_pct(row["oos_win_rate"]),
                dc=_num(row["is_oos_decay"], 2),
            )
        )
    return "\n".join(lines)


def _aggregate_table(aggregate: pd.DataFrame) -> str:
    if aggregate.empty:
        return "| Metric | Value |\n| --- | --- |\n| n_splits | 0 |"
    row = aggregate.iloc[0]
    return (
        "| Metric | Value |\n"
        "| --- | --- |\n"
        f"| OOS Sharpe (mean) | {_num(row['oos_sharpe'], 2)} |\n"
        f"| OOS annualized (mean) | {_pct(row['oos_annualized'])} |\n"
        f"| OOS MaxDD (worst) | {_pct(row['oos_max_dd'])} |\n"
        f"| OOS n_trades (sum) | {_int(row['oos_n_trades'])} |\n"
        f"| OOS win_rate (pooled) | {_pct(row['oos_win_rate'])} |\n"
        f"| IS Sharpe (mean) | {_num(row['is_sharpe'], 2)} |\n"
        f"| IS->OOS decay | {_num(row['is_oos_decay'], 2)} |"
    )


def _iso_date(value: object) -> str:
    if value is None or pd.isna(value):
        return "n/a"
    return pd.Timestamp(value).strftime("%Y-%m-%d")


def _int(value: object) -> str:
    try:
        return str(int(value))
    except (TypeError, ValueError):
        return "n/a"


def _num(value: object, decimals: int) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "n/a"
    if not math.isfinite(number):
        return "n/a"
    return f"{number:.{decimals}f}"


def _pct(value: object) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "n/a"
    if not math.isfinite(number):
        return "n/a"
    return f"{number * 100:.2f}%"


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--funding-dir", type=Path, default=DEFAULT_FUNDING_DIR)
    parser.add_argument("--candles-dir", type=Path, default=DEFAULT_CANDLES_DIR)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--n-splits", type=int, default=DEFAULT_N_SPLITS)
    parser.add_argument("--train-days", type=int, default=DEFAULT_TRAIN_DAYS)
    parser.add_argument("--test-days", type=int, default=DEFAULT_TEST_DAYS)
    parser.add_argument("--min-is-trades", type=int, default=DEFAULT_MIN_IS_TRADES)
    parser.add_argument("--taker-fee", type=float, default=DEFAULT_TAKER_FEE)
    parser.add_argument("--slippage", type=float, default=DEFAULT_SLIPPAGE)
    args = parser.parse_args(argv)
    if args.n_splits <= 0:
        parser.error("--n-splits must be > 0")
    if args.train_days <= 0:
        parser.error("--train-days must be > 0")
    if args.test_days <= 0:
        parser.error("--test-days must be > 0")
    if args.min_is_trades < 0:
        parser.error("--min-is-trades must be >= 0")
    if args.taker_fee < 0:
        parser.error("--taker-fee must be >= 0")
    if args.slippage < 0:
        parser.error("--slippage must be >= 0")
    return args


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    run(
        funding_dir=args.funding_dir,
        candles_dir=args.candles_dir,
        out=args.out,
        report=args.report,
        n_splits=args.n_splits,
        train_days=args.train_days,
        test_days=args.test_days,
        min_is_trades=args.min_is_trades,
        taker_fee=args.taker_fee,
        slippage=args.slippage,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
