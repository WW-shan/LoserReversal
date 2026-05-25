"""Phase 1.5 Ablation A: bootstrap CI on v2 OOS trade-level Sharpe.

Resamples 36 walk-forward trade returns (with replacement) 10,000 times to estimate
the distribution of trade-level Sharpe under the null of i.i.d. trade returns.
Reports the 2.5 / 50 / 97.5 percentiles and a robust / lucky-fold / inconclusive
decision based on whether the 95% CI crosses zero.
"""

from __future__ import annotations

import argparse
import math
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


DEFAULT_INPUT = Path("data/parquet/phase1_5_walkforward_trades.parquet")
DEFAULT_REPORT = Path("reports/phase-1-5-bootstrap-ci.md")
DEFAULT_SIGNAL = "v2"
DEFAULT_PHASE = "OOS"
DEFAULT_ITERATIONS = 10_000
DEFAULT_SEED = 20260524
DEFAULT_TRADES_PER_YEAR = 14.4


@dataclass(frozen=True)
class BootstrapConfig:
    input: Path = DEFAULT_INPUT
    signal: str = DEFAULT_SIGNAL
    phase: str = DEFAULT_PHASE
    iterations: int = DEFAULT_ITERATIONS
    seed: int = DEFAULT_SEED
    trades_per_year: float = DEFAULT_TRADES_PER_YEAR
    report: Path = DEFAULT_REPORT


def run_bootstrap(config: BootstrapConfig) -> dict[str, Any]:
    returns = _load_returns(config)
    n_trades = int(returns.size)
    if n_trades == 0:
        raise RuntimeError(
            f"no trades match signal={config.signal!r} phase={config.phase!r} in {config.input}"
        )

    point_sharpe = _annualized_sharpe(returns, config.trades_per_year)
    samples = _bootstrap_sharpes(
        returns,
        iterations=config.iterations,
        seed=config.seed,
        trades_per_year=config.trades_per_year,
    )
    percentiles = np.percentile(samples, [2.5, 50.0, 97.5])
    lower, median, upper = (float(percentiles[0]), float(percentiles[1]), float(percentiles[2]))
    mean = float(np.mean(samples))
    decision = _decide(lower=lower, upper=upper)

    result: dict[str, Any] = {
        "input": str(config.input),
        "signal": config.signal,
        "phase": config.phase,
        "iterations": int(config.iterations),
        "seed": int(config.seed),
        "trades_per_year": float(config.trades_per_year),
        "n_trades": n_trades,
        "point_sharpe": point_sharpe,
        "mean": mean,
        "lower_2_5": lower,
        "median_50": median,
        "upper_97_5": upper,
        "decision": decision,
        "samples": samples,
    }

    _write_report(config.report, result)
    print(_summary_line(result))
    print(f"wrote report: {config.report}")
    return result


def _load_returns(config: BootstrapConfig) -> np.ndarray:
    if not config.input.exists():
        raise RuntimeError(f"input parquet not found: {config.input}")

    frame = pd.read_parquet(config.input)
    if frame.empty or "return" not in frame.columns:
        return np.array([], dtype="float64")

    mask = pd.Series(True, index=frame.index)
    if "signal" in frame.columns:
        mask &= frame["signal"].astype("string").eq(config.signal)
    if "phase" in frame.columns:
        mask &= frame["phase"].astype("string").eq(config.phase)
    selected = frame.loc[mask, "return"]
    values = pd.to_numeric(selected, errors="coerce").dropna().to_numpy(dtype="float64")
    return values


def _bootstrap_sharpes(
    returns: np.ndarray,
    *,
    iterations: int,
    seed: int,
    trades_per_year: float,
) -> np.ndarray:
    rng = np.random.default_rng(seed)
    n = returns.size
    indices = rng.integers(low=0, high=n, size=(iterations, n))
    samples = returns[indices]
    factor = math.sqrt(trades_per_year)
    means = samples.mean(axis=1)
    stds = samples.std(axis=1, ddof=0)
    with np.errstate(divide="ignore", invalid="ignore"):
        raw = np.where(stds > 0, means / stds * factor, 0.0)
    return raw.astype("float64")


def _annualized_sharpe(returns: np.ndarray, trades_per_year: float) -> float:
    if returns.size == 0:
        return float("nan")
    std = float(np.std(returns, ddof=0))
    mean = float(np.mean(returns))
    if std == 0.0:
        return float("nan")
    return mean / std * math.sqrt(trades_per_year)


def _decide(*, lower: float, upper: float) -> str:
    if lower > 0.0:
        return "robust"
    if upper < 0.0:
        return "lucky-fold"
    return "inconclusive"


def _write_report(path: Path, result: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    generated = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines = [
        "# Phase 1.5 Ablation A: Bootstrap CI on v2 OOS Sharpe",
        "",
        f"_Generated {generated}_",
        "",
        "## Methodology",
        "",
        f"- Input: `{result['input']}` filtered to signal=`{result['signal']}`"
        f" phase=`{result['phase']}` ({result['n_trades']} trades).",
        f"- Resampled trade returns with replacement {result['iterations']} times"
        f" (seed={result['seed']}).",
        f"- Sharpe per sample: `mean / std(ddof=0) * sqrt({result['trades_per_year']:.2f})`.",
        "- Annualization assumes unlock cadence ~14.4 trades / year (36 trades / 2.5 years).",
        "",
        "## Config",
        "",
        "| key | value |",
        "| --- | --- |",
        f"| input | {result['input']} |",
        f"| signal | {result['signal']} |",
        f"| phase | {result['phase']} |",
        f"| iterations | {result['iterations']} |",
        f"| seed | {result['seed']} |",
        f"| trades_per_year | {result['trades_per_year']:.4f} |",
        f"| n_trades | {result['n_trades']} |",
        "",
        "## Bootstrap CI",
        "",
        "| statistic | value |",
        "| --- | ---: |",
        f"| point Sharpe (annualized) | {_fmt(result['point_sharpe'])} |",
        f"| mean of bootstrap Sharpes | {_fmt(result['mean'])} |",
        f"| 2.5% percentile (lower CI) | {_fmt(result['lower_2_5'])} |",
        f"| 50% percentile (median) | {_fmt(result['median_50'])} |",
        f"| 97.5% percentile (upper CI) | {_fmt(result['upper_97_5'])} |",
        "",
        "## Decision",
        "",
        f"- Lower 2.5% CI = {_fmt(result['lower_2_5'])}, Upper 97.5% CI = {_fmt(result['upper_97_5'])}",
        "- Decision rule: lower > 0 = robust; upper < 0 = lucky-fold; else inconclusive.",
        f"- **Verdict: {result['decision']}**",
        "",
        *_verdict_implications(result["decision"]),
        "",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _verdict_implications(decision: str) -> list[str]:
    if decision == "robust":
        return [
            "## Implications",
            "",
            "- v2 signal Sharpe is statistically distinguishable from zero at 95% confidence.",
            "- Worth proceeding to Ablations B (fix cohort=team), C (BTC<200d filter),"
            " and D (-10% stop) to attempt GREEN.",
        ]
    if decision == "lucky-fold":
        return [
            "## Implications",
            "",
            "- Upper CI sits below zero — single-fold Sharpe likely a sampling artifact.",
            "- Recommend accepting YELLOW (or downgrading to RED) and deferring further tuning.",
        ]
    return [
        "## Implications",
        "",
        "- CI straddles zero — signal direction is ambiguous on bootstrap evidence.",
        "- Ablations B/C/D may still help, but expect modest gains; treat YELLOW as upper bound"
        " until cross-thesis diversification is available.",
    ]


def _summary_line(result: dict[str, Any]) -> str:
    return (
        f"bootstrap CI for signal={result['signal']} phase={result['phase']}: "
        f"lower={_fmt(result['lower_2_5'])} median={_fmt(result['median_50'])} "
        f"upper={_fmt(result['upper_97_5'])} decision={result['decision']}"
    )


def _fmt(value: float) -> str:
    number = float(value)
    if not math.isfinite(number):
        return "n/a"
    return f"{number:.4f}"


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--signal", type=str, default=DEFAULT_SIGNAL)
    parser.add_argument("--phase", type=str, default=DEFAULT_PHASE)
    parser.add_argument("--iterations", type=int, default=DEFAULT_ITERATIONS)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--trades-per-year", type=float, default=DEFAULT_TRADES_PER_YEAR)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    args = parser.parse_args(argv)
    _validate_args(parser, args)
    return args


def _validate_args(parser: argparse.ArgumentParser, args: argparse.Namespace) -> None:
    if args.iterations < 1:
        parser.error("--iterations must be at least 1")
    if args.trades_per_year <= 0:
        parser.error("--trades-per-year must be positive")


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        run_bootstrap(
            BootstrapConfig(
                input=args.input,
                signal=args.signal,
                phase=args.phase,
                iterations=args.iterations,
                seed=args.seed,
                trades_per_year=args.trades_per_year,
                report=args.report,
            )
        )
    except RuntimeError as error:
        print(f"error: {error}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
