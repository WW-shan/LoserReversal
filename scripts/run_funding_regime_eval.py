"""Post-hoc evaluate funding-rate regime filter against existing walkforward trades.

Loads Phase 1.5 walkforward trades (with stop-loss applied), computes funding
regime at each trade's entry timestamp, and recomputes aggregate stats on the
subset of trades surviving the regime filter. Compares pre/post filter
Sharpe / MaxDD / win rate / total return per signal.

Use case (P5 from 2026-05-27 smart-search): the existing BTC<200d SMA regime
filter ran into a data-shortage issue (1d candles only 91 days). Funding
history is 3 years for BTC/ETH on HL, so funding-rate regime is the available
substitute.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd

from signals.regime_filter import compute_funding_regime


DEFAULT_TRADES = Path("data/parquet/phase1_5_walkforward_stop_trades.parquet")
DEFAULT_FUNDING_DIR = Path("data/parquet/funding")
DEFAULT_REPORT = Path("reports/phase-1-5-ablation-c-funding-regime.md")
DEFAULT_OUT = Path("data/parquet/phase1_5_funding_regime_eval.parquet")
DEFAULT_MAJORS: tuple[str, ...] = ("BTC", "ETH")
DEFAULT_WINDOW_DAYS = 7

# Phase 1.5 signal registry: short signals expect bear regime, long signal v5 expects bull.
SIGNAL_DIRECTION: dict[str, str] = {
    "v1": "short",
    "v2": "short",
    "v3": "short",
    "v4": "short",
    "v5": "long",
}


def main() -> int:
    args = _parse_args()
    trades = pd.read_parquet(args.trades)
    if "signal" not in trades.columns or "entry_ts" not in trades.columns:
        raise SystemExit(
            f"trades parquet {args.trades} missing required 'signal' / 'entry_ts' columns"
        )

    funding = _load_funding(args.funding_dir, args.majors)
    regime = compute_funding_regime(
        funding, majors=tuple(args.majors), window_days=args.window_days
    )
    if regime.empty:
        raise SystemExit("no funding data — cannot compute regime")

    pre_summary = _summarize_per_signal(trades, label="pre_filter")
    filtered = _apply_funding_regime_to_trades(trades, regime)
    post_summary = _summarize_per_signal(filtered, label="post_filter")
    combined = pd.merge(
        pre_summary,
        post_summary,
        on="signal",
        suffixes=("_pre", "_post"),
        how="outer",
    )

    args.out.parent.mkdir(parents=True, exist_ok=True)
    combined.to_parquet(args.out, index=False)
    print(f"wrote: {args.out}")

    args.report.parent.mkdir(parents=True, exist_ok=True)
    _write_report(args.report, combined, args, regime)
    print(f"wrote: {args.report}")

    print("\nPre vs post regime filter:")
    print(combined.to_string(index=False))
    return 0


def _load_funding(
    funding_dir: Path, majors: Iterable[str]
) -> dict[str, pd.DataFrame]:
    out: dict[str, pd.DataFrame] = {}
    for token in majors:
        path = funding_dir / f"{token}.parquet"
        if not path.exists():
            continue
        out[token] = pd.read_parquet(path)
    return out


def _apply_funding_regime_to_trades(
    trades: pd.DataFrame, regime: pd.Series
) -> pd.DataFrame:
    """Filter trades by funding regime at each trade's entry timestamp.

    Per spec rule "Per-signal entry-date semantics in regime/event filters",
    the regime is queried at each trade's actual entry_ts (already
    signal-offset-adjusted).
    """
    if trades.empty:
        return trades.copy()
    regime_sorted = regime.dropna().sort_index()

    keep: list[bool] = []
    for _, row in trades.iterrows():
        signal = str(row["signal"])
        target_dir = SIGNAL_DIRECTION.get(signal)
        if target_dir is None:
            keep.append(False)
            continue
        entry_ts = pd.Timestamp(row["entry_ts"])
        if entry_ts.tzinfo is None:
            entry_ts = entry_ts.tz_localize("UTC")
        else:
            entry_ts = entry_ts.tz_convert("UTC")
        # Strict-less-than slicing (spec rule: "Time-series boundary slicing
        # must be strict-less-than for point-in-time queries"). The regime
        # series is daily-resampled; for an entry at day D we want the regime
        # label keyed on data through day D-1 only. Compare to normalized
        # entry_ts so an entry at D 00:00:00 is excluded along with later D
        # observations.
        entry_day = entry_ts.normalize()
        eligible = regime_sorted.loc[regime_sorted.index < entry_day]
        if eligible.empty:
            keep.append(False)
            continue
        is_bear = bool(eligible.iloc[-1])
        # short signals require bear=True, long signals require bear=False
        target_is_bear = target_dir == "short"
        keep.append(is_bear == target_is_bear)

    return trades.loc[keep].copy().reset_index(drop=True)


def _summarize_per_signal(
    trades: pd.DataFrame, *, label: str
) -> pd.DataFrame:
    if trades.empty:
        return pd.DataFrame(
            columns=["signal", f"n_{label}", f"sharpe_{label}", f"win_{label}", f"maxdd_{label}", f"ret_{label}"]
        )
    rows: list[dict[str, object]] = []
    for signal, group in trades.groupby("signal"):
        # Annualize using THIS signal's own trade cadence (per smart-search
        # 2026-05-27 R1 finding: overall-density was 6.7× canonical for v1).
        # tpy_signal = n_signal_trades / span_signal_days * 365
        if len(group) >= 2:
            span_days = (
                pd.Timestamp(group["entry_ts"].max())
                - pd.Timestamp(group["entry_ts"].min())
            ).total_seconds() / 86400.0
            span_days = max(span_days, 1.0)
            tpy_signal = float(len(group) * 365.0 / span_days)
        else:
            tpy_signal = 12.0  # fallback for n<2
        returns = group["return"].to_numpy()
        n = len(returns)
        if n == 0:
            sharpe = float("nan")
        else:
            mean = float(np.mean(returns))
            std = float(np.std(returns, ddof=0))
            sharpe = (
                float(mean / std * np.sqrt(tpy_signal)) if std > 0 else float("nan")
            )
        win_rate = float((returns > 0).mean()) if n else float("nan")
        equity = np.cumprod(1.0 + returns) if n else np.array([])
        if equity.size:
            peak = np.maximum.accumulate(equity)
            dd = (equity - peak) / peak
            max_dd = float(np.min(dd))
            total_ret = float(equity[-1] - 1.0)
        else:
            max_dd = float("nan")
            total_ret = float("nan")
        rows.append(
            {
                "signal": signal,
                f"n_{label}": int(n),
                f"sharpe_{label}": round(sharpe, 3) if not np.isnan(sharpe) else float("nan"),
                f"win_{label}": round(win_rate, 3) if not np.isnan(win_rate) else float("nan"),
                f"maxdd_{label}": round(max_dd, 3) if not np.isnan(max_dd) else float("nan"),
                f"ret_{label}": round(total_ret, 3) if not np.isnan(total_ret) else float("nan"),
            }
        )
    return pd.DataFrame(rows)


def _write_report(path: Path, summary: pd.DataFrame, args: argparse.Namespace, regime: pd.Series) -> None:
    bear_pct = float(regime.dropna().mean()) if not regime.dropna().empty else float("nan")
    span_start = regime.dropna().index.min() if not regime.dropna().empty else None
    span_end = regime.dropna().index.max() if not regime.dropna().empty else None
    lines = [
        "# Phase 1.5 Ablation C — Funding-Regime Filter (replaces BTC<200d SMA)",
        "",
        "_Generated 2026-05-28 UTC_",
        "",
        "## Motivation",
        "",
        "BTC<200d SMA filter rejected by Ablation C in 2026-05-26: BTC 1d candle",
        "only 91 days, can't compute 200d SMA. Per smart-search 2026-05-27 finding,",
        "funding-rate regime is a perp-native alternative with 3y data on HL.",
        "",
        "## Config",
        "",
        "| key | value |",
        "| --- | --- |",
        f"| trades input | {args.trades} |",
        f"| funding dir | {args.funding_dir} |",
        f"| majors | {','.join(args.majors)} |",
        f"| window_days | {args.window_days} |",
        f"| regime span | {span_start} → {span_end} |",
        f"| % days in bear regime | {bear_pct * 100:.1f}% |",
        "",
        "## Pre vs Post Filter (per signal)",
        "",
        "| signal | n_pre | sharpe_pre | win_pre | n_post | sharpe_post | win_post | Δ_sharpe |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for _, row in summary.iterrows():
        n_pre_raw = row.get("n_pre_filter")
        n_post_raw = row.get("n_post_filter")
        n_pre = int(n_pre_raw) if not pd.isna(n_pre_raw) else 0
        n_post = int(n_post_raw) if not pd.isna(n_post_raw) else 0
        sp = row.get("sharpe_pre_filter", float("nan"))
        sp_post = row.get("sharpe_post_filter", float("nan"))
        delta = (
            sp_post - sp
            if not (np.isnan(sp) or np.isnan(sp_post))
            else float("nan")
        )
        lines.append(
            f"| {row['signal']} | {n_pre} | {sp} | {row.get('win_pre_filter', 'n/a')} | "
            f"{n_post} | {sp_post} | {row.get('win_post_filter', 'n/a')} | "
            f"{delta:+.3f} |" if not np.isnan(delta) else
            f"| {row['signal']} | {n_pre} | {sp} | {row.get('win_pre_filter', 'n/a')} | "
            f"{n_post} | {sp_post} | {row.get('win_post_filter', 'n/a')} | n/a |"
        )
    lines += [
        "",
        "## Interpretation",
        "",
        "- **Positive Δ_sharpe**: funding regime filter helps (drops trades that would have lost).",
        "- **Negative Δ_sharpe**: filter drops winning trades → counterproductive.",
        "- **n_post = 0**: filter rejects all trades (regime never matched) → likely warmup issue.",
        "",
        "## Reproducibility",
        "",
        "```bash",
        "uv run python scripts/run_funding_regime_eval.py \\",
        f"  --trades {args.trades} \\",
        f"  --funding-dir {args.funding_dir} \\",
        f"  --majors {' '.join(args.majors)} \\",
        f"  --window-days {args.window_days}",
        "```",
        "",
    ]
    path.write_text("\n".join(lines))


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Evaluate funding-rate regime filter on existing walkforward trades."
    )
    parser.add_argument("--trades", type=Path, default=DEFAULT_TRADES)
    parser.add_argument("--funding-dir", type=Path, default=DEFAULT_FUNDING_DIR)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument(
        "--majors",
        nargs="+",
        default=list(DEFAULT_MAJORS),
        help="Major tokens used for funding regime aggregation",
    )
    parser.add_argument(
        "--window-days", type=int, default=DEFAULT_WINDOW_DAYS,
        help="Rolling N-day mean window for regime detection",
    )
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(main())
