"""Phase 1.5 Ablation A: bootstrap CI on v2 OOS trade-level Sharpe.

Resamples 36 walk-forward trade returns (with replacement) 10,000 times to estimate
the distribution of trade-level Sharpe under the null of i.i.d. trade returns.
Reports the 2.5 / 50 / 97.5 percentiles and a robust / lucky-fold / inconclusive
decision based on whether the 95% CI crosses zero.

Two resampling methods are supported via ``--method``:

- ``percentile`` (default, back-compat): classic Efron bootstrap that resamples
  trade indices with replacement.
- ``bayesian`` (Rubin 1981): re-weights every observation with a Dirichlet(1,...,1)
  draw and computes weighted Sharpe. This is the preferred small-sample (n<30)
  variant and is required for the v1+stop=10% combo (n=29 OOS trades).
"""

from __future__ import annotations

import argparse
import math
import sys
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
DEFAULT_METHOD = "percentile"
METHOD_CHOICES = ("percentile", "bayesian")


@dataclass(frozen=True)
class BootstrapConfig:
    input: Path = DEFAULT_INPUT
    signal: str = DEFAULT_SIGNAL
    phase: str = DEFAULT_PHASE
    iterations: int = DEFAULT_ITERATIONS
    seed: int = DEFAULT_SEED
    trades_per_year: float = DEFAULT_TRADES_PER_YEAR
    report: Path = DEFAULT_REPORT
    method: str = DEFAULT_METHOD


def run_bootstrap(config: BootstrapConfig) -> dict[str, Any]:
    if config.method not in METHOD_CHOICES:
        raise RuntimeError(
            f"unknown bootstrap method {config.method!r}; expected one of {METHOD_CHOICES}"
        )

    returns = _load_returns(config)
    n_trades = int(returns.size)
    if n_trades == 0:
        raise RuntimeError(
            f"no trades match signal={config.signal!r} phase={config.phase!r} in {config.input}"
        )

    point_sharpe = _annualized_sharpe(returns, config.trades_per_year)
    rng = np.random.default_rng(config.seed)
    if config.method == "bayesian":
        samples = bayesian_bootstrap(
            returns,
            iterations=config.iterations,
            rng=rng,
            trades_per_year=config.trades_per_year,
        )
    else:
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
        "method": config.method,
        "n_trades": n_trades,
        "point_sharpe": point_sharpe,
        "mean": mean,
        "lower_2_5": lower,
        "median_50": median,
        "upper_97_5": upper,
        "decision": decision,
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
    else:
        print(
            f"[WARN] input {config.input} has no 'phase' column; using all rows",
            file=sys.stderr,
        )
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


def bayesian_bootstrap(
    returns: np.ndarray,
    *,
    iterations: int,
    rng: np.random.Generator,
    trades_per_year: float = DEFAULT_TRADES_PER_YEAR,
) -> np.ndarray:
    """Rubin (1981) Bayesian bootstrap for annualized trade-level Sharpe.

    For each of ``iterations`` draws we sample a weight vector
    ``w ~ Dirichlet(1, ..., 1)`` (i.e. uniform on the n-simplex) and compute
    the weighted Sharpe:

    .. code-block::

        mean_w  = sum(w * r)
        var_w   = sum(w * (r - mean_w) ** 2)
        sharpe  = mean_w / sqrt(var_w) * sqrt(trades_per_year)

    Compared with the standard percentile bootstrap, this avoids the
    discrete index-resampling distribution and yields better coverage on
    small samples (n<30), where Efron-Tibshirani's index resampling tends
    to over-cluster on extreme observations. We use Dirichlet weights that
    always sum to 1, so Sharpe is invariant to constant scaling of the
    weight vector.

    Returns a 1D float64 array of length ``iterations`` containing the
    weighted, annualized Sharpe samples. Constant ``returns`` (zero
    variance) collapse the Sharpe to 0 by definition.
    """
    if iterations < 1:
        raise ValueError("iterations must be at least 1")
    values = np.asarray(returns, dtype="float64")
    n = values.size
    if n == 0:
        return np.array([], dtype="float64")

    # Degenerate input: zero unweighted variance => weighted variance is also zero
    # under any positive weight vector. Short-circuit to 0 to avoid amplifying
    # float-precision noise into spurious Sharpe samples (e.g. constant return
    # round-tripped through parquet leaves std ~ 1e-17 instead of exact zero).
    sample_std = float(np.std(values, ddof=0))
    if sample_std <= np.finfo(np.float64).eps * max(1.0, float(np.max(np.abs(values)))):
        return np.zeros(iterations, dtype="float64")

    alpha = np.ones(n, dtype="float64")
    weights = rng.dirichlet(alpha, size=iterations).astype("float64")
    means = weights @ values
    centered = values[np.newaxis, :] - means[:, np.newaxis]
    variances = np.einsum("ij,ij->i", weights, centered * centered)
    stds = np.sqrt(np.clip(variances, a_min=0.0, a_max=None))
    factor = math.sqrt(trades_per_year)
    with np.errstate(divide="ignore", invalid="ignore"):
        sharpes = np.where(stds > 0.0, means / stds * factor, 0.0)
    return sharpes.astype("float64")


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
    method = str(result.get("method", DEFAULT_METHOD))
    title_suffix = "Bayesian" if method == "bayesian" else "Percentile"
    lines = [
        f"# Phase 1.5 Bootstrap CI ({title_suffix}) on {result['signal']} {result['phase']}",
        "",
        f"_Generated {generated}_",
        "",
        "## Methodology",
        "",
        f"- Input: `{result['input']}` filtered to signal=`{result['signal']}`"
        f" phase=`{result['phase']}` ({result['n_trades']} trades).",
        f"- Method: `{method}`.",
        *_method_description(method, result),
        f"- Iterations: {result['iterations']} (seed={result['seed']}).",
        f"- Sharpe per sample: `weighted_mean / weighted_std * sqrt({result['trades_per_year']:.2f})`"
        if method == "bayesian"
        else f"- Sharpe per sample: `mean / std(ddof=0) * sqrt({result['trades_per_year']:.2f})`.",
        "- Annualization assumes unlock cadence ~14.4 trades / year (36 trades / 2.5 years).",
        "",
        "## Config",
        "",
        "| key | value |",
        "| --- | --- |",
        f"| input | {result['input']} |",
        f"| signal | {result['signal']} |",
        f"| phase | {result['phase']} |",
        f"| method | {method} |",
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
        *_verdict_implications(result["decision"], result),
        "",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _method_description(method: str, result: dict[str, Any]) -> list[str]:
    if method == "bayesian":
        return [
            "- Bayesian bootstrap (Rubin 1981) draws Dirichlet(1,...,1) weights on the "
            f"n={result['n_trades']} trade returns and computes weighted Sharpe per draw.",
            "- Recommended over percentile bootstrap when n<30 (Efron-Tibshirani threshold); "
            "weights live on the n-simplex, so each draw is a soft re-weighting rather than "
            "a discrete index resample.",
        ]
    return [
        "- Resampled trade returns with replacement (classical Efron percentile bootstrap).",
    ]


def _verdict_implications(decision: str, result: dict[str, Any]) -> list[str]:
    signal = result.get("signal", "<signal>")
    method = result.get("method", DEFAULT_METHOD)
    if decision == "robust":
        return [
            "## Implications",
            "",
            f"- {signal} signal Sharpe is statistically distinguishable from zero at "
            f"95% confidence ({method} bootstrap).",
            f"- Phase 5 portfolio sizing should use the lower CI bound "
            f"({result['lower_2_5']:.4f}) with fractional Kelly.",
        ]
    if decision == "lucky-fold":
        return [
            "## Implications",
            "",
            "- Upper CI sits below zero — single-fold Sharpe likely a sampling artifact.",
            f"- Treat {signal} as RED and defer further tuning.",
        ]
    return [
        "## Implications",
        "",
        "- CI straddles zero — signal direction is ambiguous on bootstrap evidence.",
        f"- Treat {signal} as YELLOW upper-bound until cross-thesis diversification.",
    ]


def _summary_line(result: dict[str, Any]) -> str:
    method = str(result.get("method", DEFAULT_METHOD))
    return (
        f"bootstrap CI ({method}) for signal={result['signal']} phase={result['phase']}: "
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
    parser.add_argument(
        "--method",
        choices=list(METHOD_CHOICES),
        default=DEFAULT_METHOD,
        help=(
            "Bootstrap method. 'percentile' is the classical Efron resample (default); "
            "'bayesian' uses Rubin (1981) Dirichlet weights and is preferred when n<30."
        ),
    )
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
                method=args.method,
            )
        )
    except RuntimeError as error:
        print(f"error: {error}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
