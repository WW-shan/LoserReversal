"""Compose active strategy signals into a Phase 5 portfolio."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from portfolio.composer import PortfolioComposer
from portfolio.signal_loader import LoadedSignal, load_active_signals


DEFAULT_SIGNALS = ("strategies/active/*.json",)
DEFAULT_METHOD = "risk_parity"
METHOD_CHOICES = ("risk_parity", "mean_variance", "equal_weight")
DEFAULT_TARGET_VOL = 0.15
DEFAULT_OUT = Path("data/parquet/portfolio_composition.parquet")
DEFAULT_REPORT = Path("reports/portfolio_composition.md")
RISK_PER_TRADE_LIMIT = 0.01
SINGLE_ASSET_LIMIT = 0.15
TOTAL_LEVERAGE_LIMIT = 5.0
MONTHLY_MAX_DD_LIMIT = 0.08


@dataclass(frozen=True)
class PortfolioComposerConfig:
    signals: tuple[str, ...] = DEFAULT_SIGNALS
    method: str = DEFAULT_METHOD
    target_vol: float = DEFAULT_TARGET_VOL
    out: Path = DEFAULT_OUT
    report: Path = DEFAULT_REPORT


def run_portfolio_composer(config: PortfolioComposerConfig) -> dict[str, Any]:
    if config.method not in METHOD_CHOICES:
        raise RuntimeError(f"unsupported method={config.method!r}; expected one of {METHOD_CHOICES}")
    signals = load_active_signals(config.signals)
    if not signals:
        raise RuntimeError(f"no active signal configs matched: {', '.join(config.signals)}")

    composer = PortfolioComposer()
    for signal in signals:
        composer.add_signal(
            signal.name,
            signal.returns,
            signal.bayesian_ci,
            signal.sharpe_lower,
            signal.weight_max,
        )

    weights = _select_weights(composer, signals, config)
    portfolio_returns = composer.portfolio_returns(weights)
    combined = composer.combined_metrics(weights)
    correlation = composer.correlation_matrix()
    composition = composer.weights_frame(weights)
    composition.insert(0, "method", config.method)
    composition.insert(1, "target_vol", float(config.target_vol))

    risk_checks = _risk_checks(signals, weights, portfolio_returns)
    _write_parquet(composition, config.out)
    _write_report(
        config.report,
        config=config,
        composition=composition,
        correlation=correlation,
        combined=combined,
        risk_checks=risk_checks,
        signals=signals,
    )
    print(f"wrote parquet: {config.out}")
    print(f"wrote report: {config.report}")
    return {
        "signals": signals,
        "weights": weights,
        "composition": composition,
        "correlation": correlation,
        "combined": combined,
        "risk_checks": risk_checks,
    }


def _select_weights(
    composer: PortfolioComposer,
    signals: Sequence[LoadedSignal],
    config: PortfolioComposerConfig,
) -> dict[str, float]:
    if config.method == "risk_parity":
        return composer.risk_parity_weights(target_vol=config.target_vol)
    if config.method == "mean_variance":
        return composer.mean_variance_weights(target_vol=config.target_vol)
    return _equal_weight(signals, composer=composer, target_vol=config.target_vol)


def _equal_weight(
    signals: Sequence[LoadedSignal],
    *,
    composer: PortfolioComposer,
    target_vol: float,
) -> dict[str, float]:
    if not signals:
        return {}
    if len(signals) == 1:
        return {signals[0].name: float(signals[0].weight_max)}

    caps = np.array([signal.weight_max for signal in signals], dtype="float64")
    raw = np.minimum(np.full(len(signals), 1.0 / len(signals), dtype="float64"), caps)
    frame = pd.concat([signal.returns.rename(signal.name) for signal in signals], axis=1).fillna(0.0)
    portfolio_returns = frame.to_numpy(dtype="float64") @ raw
    vol = float(pd.Series(portfolio_returns).std(ddof=0) * np.sqrt(composer.trades_per_year))
    if vol > 0.0:
        raw *= min(1.0, target_vol / vol)
    return {signal.name: float(weight) for signal, weight in zip(signals, raw, strict=True)}


def _risk_checks(
    signals: Sequence[LoadedSignal],
    weights: Mapping[str, float],
    portfolio_returns: pd.Series,
) -> list[dict[str, object]]:
    max_single_trade_risk = max(
        (
            float(weights.get(signal.name, 0.0))
            * float(signal.raw_config.get("stop_loss", signal.raw_config.get("stop_loss_pct", 0.0)))
            for signal in signals
        ),
        default=0.0,
    )
    max_single_asset = max((abs(float(weight)) for weight in weights.values()), default=0.0)
    total_leverage = sum(abs(float(weight)) for weight in weights.values())
    max_dd = _portfolio_max_drawdown(portfolio_returns)
    return [
        {
            "check": "single_trade_risk <= 1%",
            "value": max_single_trade_risk,
            "limit": RISK_PER_TRADE_LIMIT,
            "pass": max_single_trade_risk <= RISK_PER_TRADE_LIMIT + 1e-12,
        },
        {
            "check": "single_asset_exposure <= 15%",
            "value": max_single_asset,
            "limit": SINGLE_ASSET_LIMIT,
            "pass": max_single_asset <= SINGLE_ASSET_LIMIT + 1e-12,
        },
        {
            "check": "total_leverage <= 5x",
            "value": total_leverage,
            "limit": TOTAL_LEVERAGE_LIMIT,
            "pass": total_leverage <= TOTAL_LEVERAGE_LIMIT + 1e-12,
        },
        {
            "check": "monthly_max_drawdown <= 8%",
            "value": max_dd,
            "limit": MONTHLY_MAX_DD_LIMIT,
            "pass": max_dd <= MONTHLY_MAX_DD_LIMIT + 1e-12,
        },
    ]


def _portfolio_max_drawdown(returns: pd.Series) -> float:
    clean = returns.astype("float64").dropna()
    if clean.empty:
        return 0.0
    equity = (1.0 + clean).cumprod()
    drawdown = equity / equity.cummax() - 1.0
    return abs(float(drawdown.min()))


def _write_parquet(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(path, index=False)


def _write_report(
    path: Path,
    *,
    config: PortfolioComposerConfig,
    composition: pd.DataFrame,
    correlation: pd.DataFrame,
    combined: Mapping[str, float | int],
    risk_checks: list[dict[str, object]],
    signals: Sequence[LoadedSignal],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    generated = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines = [
        "# Phase 5 Portfolio Composition",
        "",
        f"_Generated {generated}_",
        "",
        "## Config",
        "",
        "| key | value |",
        "| --- | --- |",
        f"| signals | {', '.join(config.signals)} |",
        f"| method | {config.method} |",
        f"| target_vol | {config.target_vol:.4f} |",
        f"| out | {config.out} |",
        "",
        "## Correlation Matrix",
        "",
        *_markdown_table(correlation.reset_index(names="signal")),
        "",
        "## Per-Signal Stats",
        "",
        *_markdown_table(_stats_report_frame(composition)),
        "",
        "## Kelly Sizing",
        "",
        *_markdown_table(_kelly_report_frame(composition)),
        "",
        "## Combined Stats",
        "",
        "| metric | value |",
        "| --- | ---: |",
        f"| sharpe | {_fmt_float(float(combined['sharpe']))} |",
        f"| max_dd | {_fmt_pct(float(combined['max_dd']))} |",
        f"| n_trades | {int(combined['n_trades'])} |",
        f"| win_rate | {_fmt_pct(float(combined['win_rate']))} |",
        "",
        "## Risk Checks",
        "",
        *_markdown_table(pd.DataFrame(risk_checks)),
        "",
        "## Sources",
        "",
        *[f"- `{signal.config_path}` -> `{signal.raw_config['source_parquet']}`" for signal in signals],
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


def _stats_report_frame(composition: pd.DataFrame) -> pd.DataFrame:
    columns = [
        "signal",
        "weight",
        "weight_max",
        "n_trades",
        "win_rate",
        "sharpe",
        "max_dd",
        "sharpe_lower",
    ]
    return composition.loc[:, columns].copy()


def _kelly_report_frame(composition: pd.DataFrame) -> pd.DataFrame:
    columns = [
        "signal",
        "ci_lower",
        "ci_median",
        "ci_upper",
        "kelly_fraction",
        "kelly_weight",
        "weight",
    ]
    return composition.loc[:, columns].copy()


def _markdown_table(frame: pd.DataFrame) -> list[str]:
    if frame.empty:
        return ["_No rows._"]
    rendered = frame.copy()
    for column in rendered.columns:
        if pd.api.types.is_float_dtype(rendered[column]):
            rendered[column] = rendered[column].map(_fmt_float)
        elif pd.api.types.is_bool_dtype(rendered[column]):
            rendered[column] = rendered[column].map(lambda value: "PASS" if value else "FAIL")
    headers = [str(column) for column in rendered.columns]
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for row in rendered.itertuples(index=False, name=None):
        lines.append("| " + " | ".join(str(value) for value in row) + " |")
    return lines


def _fmt_float(value: float) -> str:
    if not np.isfinite(value):
        return str(value)
    return f"{value:.4f}"


def _fmt_pct(value: float) -> str:
    if not np.isfinite(value):
        return str(value)
    return f"{value:.2%}"


def parse_args(argv: Sequence[str] | None = None) -> PortfolioComposerConfig:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--signals", nargs="+", default=list(DEFAULT_SIGNALS))
    parser.add_argument("--method", choices=METHOD_CHOICES, default=DEFAULT_METHOD)
    parser.add_argument("--target-vol", type=float, default=DEFAULT_TARGET_VOL)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    args = parser.parse_args(argv)
    return PortfolioComposerConfig(
        signals=tuple(args.signals),
        method=args.method,
        target_vol=float(args.target_vol),
        out=args.out,
        report=args.report,
    )


def main(argv: Sequence[str] | None = None) -> int:
    try:
        run_portfolio_composer(parse_args(argv))
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
