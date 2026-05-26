"""Academic anti-alpha wallet pool — Phase 2.5 Slice 1.

Phase 2 v1 (archived) selected wallets by ``vlm_alltime`` DESC and ended up
copying an 86%-profitable whale cohort (IR=-4.83). Academic research summarised
in ``docs/research/literature-review.md`` Part B is unambiguous:

* HL retail loss distribution: < $1k = 85% loss, $1k-$10k = 85%+ loss,
  $100k-$1M = 26% profit, >$10M = 86% profit (whales win!).
* HL 124k whale trade simulation: "Trade size alone is a poor or negative
  predictor of success. Strategies copying larger trades underperformed.
  Account size mattered far more than single-trade size."

This module implements the academic per-wallet selection criteria:

* ``account_value`` cohort: $1k-$100k (85% loss bracket).
* ``realized_loss_rate_90d`` >= 50%: persistent loss in recent window.
* ``leverage_avg_90d`` >= 5x: retail dumb-money signal.
* ``n_trades_90d`` >= 50: active enough to matter.
* ``size_cv_90d`` >= 0.3: heterogeneous trade size (excludes market makers).
"""

from __future__ import annotations

import math
from typing import Any, Mapping

import pandas as pd


MIN_ACCOUNT_VALUE = 1_000.0
MAX_ACCOUNT_VALUE = 100_000.0
MIN_LOSS_RATE = 0.50
MIN_LEVERAGE = 5.0
MIN_N_TRADES = 50
MIN_SIZE_CV = 0.30
LOOKBACK_DAYS = 90

OPEN_DIRECTIONS = {"Open Long", "Open Short"}
CLOSE_DIRECTIONS = {"Close Long", "Close Short"}

POOL_COLUMNS = [
    "wallet",
    "account_value",
    "realized_loss_rate_90d",
    "leverage_avg_90d",
    "n_trades_90d",
    "size_cv_90d",
    "eligible_at",
]

FUNNEL_AXES = (
    "account_value",
    "realized_loss_rate",
    "leverage",
    "n_trades",
    "size_cv",
)


def compute_wallet_metrics(
    fills: pd.DataFrame,
    account_value: float,
    as_of: pd.Timestamp | None = None,
    lookback_days: int = LOOKBACK_DAYS,
) -> dict[str, float]:
    """Compute the 5 academic metrics over a wallet's 90-day fill history.

    ``fills`` is expected to be the parquet-style frame produced by
    ``infra.fetchers.user_fills.fetch_user_fills``: a DataFrame indexed by
    UTC ``time`` with columns ``coin, side, dir, px, sz, start_position,
    closed_pnl, fee, oid, tid, hash, crossed, liquidation``.
    """

    horizon = _window_start(as_of, lookback_days)
    window = _filter_window(fills, horizon)

    metrics: dict[str, float] = {
        "account_value": float(account_value),
        "n_trades_90d": 0,
        "realized_loss_rate_90d": 0.0,
        "leverage_avg_90d": 0.0,
        "size_cv_90d": 0.0,
    }

    if window.empty:
        return metrics

    open_mask = window["dir"].isin(OPEN_DIRECTIONS)
    close_mask = window["dir"].isin(CLOSE_DIRECTIONS)

    open_fills = window.loc[open_mask]
    metrics["n_trades_90d"] = int(len(open_fills))

    close_fills = window.loc[close_mask]
    if not close_fills.empty:
        losing = (close_fills["closed_pnl"].astype("float64") < 0).sum()
        metrics["realized_loss_rate_90d"] = float(losing) / float(len(close_fills))

    if not open_fills.empty:
        notional = open_fills["px"].astype("float64") * open_fills["sz"].astype("float64")
        if account_value > 0:
            metrics["leverage_avg_90d"] = float((notional / account_value).mean())

        mean_notional = float(notional.mean())
        if mean_notional > 0:
            std_notional = float(notional.std(ddof=0))
            metrics["size_cv_90d"] = std_notional / mean_notional

    return metrics


def is_academic_anti_alpha(metrics: Mapping[str, Any]) -> bool:
    """Predicate enforcing the 5 inclusive thresholds for the academic pool."""

    account_value = float(metrics["account_value"])
    if not MIN_ACCOUNT_VALUE <= account_value <= MAX_ACCOUNT_VALUE:
        return False
    if float(metrics["realized_loss_rate_90d"]) < MIN_LOSS_RATE:
        return False
    if float(metrics["leverage_avg_90d"]) < MIN_LEVERAGE:
        return False
    if int(metrics["n_trades_90d"]) < MIN_N_TRADES:
        return False
    if float(metrics["size_cv_90d"]) < MIN_SIZE_CV:
        return False
    return True


def build_academic_pool(
    leaderboard: pd.DataFrame,
    fills_by_wallet: Mapping[str, pd.DataFrame],
    as_of: pd.Timestamp | None = None,
    lookback_days: int = LOOKBACK_DAYS,
) -> pd.DataFrame:
    """Apply the academic metrics + predicate pipeline to a leaderboard slice.

    ``leaderboard`` is the dataframe produced by
    ``infra.fetchers.leaderboard.fetch_leaderboard`` (must contain
    ``eth_address`` and ``account_value`` columns). ``fills_by_wallet`` maps
    lowercase address → user fills dataframe (the parquet schema produced by
    ``infra.fetchers.user_fills.fetch_user_fills``). Returns a dataframe with
    ``POOL_COLUMNS`` containing only the wallets that pass all 5 filters.
    """

    pool, _ = build_academic_pool_with_funnel(
        leaderboard,
        fills_by_wallet,
        as_of=as_of,
        lookback_days=lookback_days,
    )
    return pool


def build_academic_pool_with_funnel(
    leaderboard: pd.DataFrame,
    fills_by_wallet: Mapping[str, pd.DataFrame],
    as_of: pd.Timestamp | None = None,
    lookback_days: int = LOOKBACK_DAYS,
) -> tuple[pd.DataFrame, dict[str, int]]:
    """Same as ``build_academic_pool`` but also returns the per-axis funnel."""

    eligible_at = _coerce_eligible_at(as_of)
    funnel: dict[str, int] = {"leaderboard": int(len(leaderboard))}
    for axis in FUNNEL_AXES:
        funnel[axis] = 0
    funnel["final"] = 0

    if leaderboard.empty or "eth_address" not in leaderboard.columns:
        return _empty_pool(), funnel

    rows: list[dict[str, Any]] = []
    for record in leaderboard.itertuples(index=False):
        raw_address = getattr(record, "eth_address", None)
        if raw_address is None:
            continue
        wallet = str(raw_address).lower()
        account_value = float(getattr(record, "account_value", 0.0) or 0.0)
        if account_value <= 0:
            continue

        fills = fills_by_wallet.get(wallet)
        if fills is None or fills.empty:
            continue

        metrics = compute_wallet_metrics(
            fills,
            account_value=account_value,
            as_of=eligible_at,
            lookback_days=lookback_days,
        )

        if not (MIN_ACCOUNT_VALUE <= account_value <= MAX_ACCOUNT_VALUE):
            continue
        funnel["account_value"] += 1

        if metrics["realized_loss_rate_90d"] < MIN_LOSS_RATE:
            continue
        funnel["realized_loss_rate"] += 1

        if metrics["leverage_avg_90d"] < MIN_LEVERAGE:
            continue
        funnel["leverage"] += 1

        if metrics["n_trades_90d"] < MIN_N_TRADES:
            continue
        funnel["n_trades"] += 1

        if metrics["size_cv_90d"] < MIN_SIZE_CV:
            continue
        funnel["size_cv"] += 1

        rows.append(
            {
                "wallet": wallet,
                "account_value": account_value,
                "realized_loss_rate_90d": metrics["realized_loss_rate_90d"],
                "leverage_avg_90d": metrics["leverage_avg_90d"],
                "n_trades_90d": int(metrics["n_trades_90d"]),
                "size_cv_90d": metrics["size_cv_90d"],
                "eligible_at": eligible_at,
            }
        )

    funnel["final"] = len(rows)
    if not rows:
        return _empty_pool(), funnel

    frame = pd.DataFrame(rows, columns=POOL_COLUMNS)
    frame["wallet"] = frame["wallet"].astype("string").str.lower()
    frame["eligible_at"] = pd.to_datetime(frame["eligible_at"], utc=True)
    return frame.reset_index(drop=True), funnel


def _window_start(as_of: pd.Timestamp | None, lookback_days: int) -> pd.Timestamp:
    if as_of is None:
        as_of = pd.Timestamp.now(tz="UTC")
    elif as_of.tzinfo is None:
        as_of = as_of.tz_localize("UTC")
    else:
        as_of = as_of.tz_convert("UTC")
    return as_of - pd.Timedelta(days=lookback_days)


def _coerce_eligible_at(as_of: pd.Timestamp | None) -> pd.Timestamp:
    if as_of is None:
        return pd.Timestamp.now(tz="UTC")
    if as_of.tzinfo is None:
        return as_of.tz_localize("UTC")
    return as_of.tz_convert("UTC")


def _empty_pool() -> pd.DataFrame:
    frame = pd.DataFrame(
        {
            "wallet": pd.Series(dtype="string"),
            "account_value": pd.Series(dtype="float64"),
            "realized_loss_rate_90d": pd.Series(dtype="float64"),
            "leverage_avg_90d": pd.Series(dtype="float64"),
            "n_trades_90d": pd.Series(dtype="int64"),
            "size_cv_90d": pd.Series(dtype="float64"),
            "eligible_at": pd.Series(dtype="datetime64[ns, UTC]"),
        },
        columns=POOL_COLUMNS,
    )
    return frame


def _filter_window(fills: pd.DataFrame, horizon: pd.Timestamp) -> pd.DataFrame:
    if fills.empty:
        return fills

    frame = fills.copy()
    if isinstance(frame.index, pd.DatetimeIndex):
        if frame.index.tz is None:
            frame.index = frame.index.tz_localize("UTC")
        else:
            frame.index = frame.index.tz_convert("UTC")
        mask = frame.index >= horizon
    elif "time" in frame.columns:
        times = pd.to_datetime(frame["time"], utc=True, errors="coerce")
        mask = times >= horizon
    else:
        return frame.iloc[0:0]

    filtered = frame.loc[mask].copy()
    filtered["px"] = pd.to_numeric(filtered.get("px"), errors="coerce")
    filtered["sz"] = pd.to_numeric(filtered.get("sz"), errors="coerce")
    filtered["closed_pnl"] = pd.to_numeric(filtered.get("closed_pnl"), errors="coerce").fillna(0.0)
    filtered["dir"] = filtered.get("dir").astype("string")

    finite_mask = filtered[["px", "sz"]].apply(lambda col: col.map(_is_finite_or_nan))
    keep = finite_mask.all(axis=1)
    return filtered.loc[keep]


def _is_finite_or_nan(value: Any) -> bool:
    if value is None:
        return False
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False
