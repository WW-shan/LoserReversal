"""Convert reverse_alpha_scores per-fill scores into a (timestamp, coin, direction, entry, exit)
signal frame compatible with ``signals.bot_walkforward``.

Each high-score fill becomes a contrarian entry: if the academic wallet opened
LONG, the reverse signal opens SHORT (and vice versa). The exit is emitted
``hold_hours`` after entry. Entries below the score percentile threshold are
discarded.

Per spec rule "Multi-feature score product needs smooth normalization":
score thresholding uses percentile-of-cohort, not absolute thresholds (since
the score scale depends on the cohort).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd


@dataclass(frozen=True)
class WalletReverseSignalConfig:
    score_percentile: float = 0.75
    hold_hours: int = 24
    threshold_min_prior: int = 200

    def __post_init__(self) -> None:
        if not 0.0 < self.score_percentile < 1.0:
            raise ValueError(
                f"score_percentile must be in (0.0, 1.0); got {self.score_percentile!r}"
            )
        if type(self.hold_hours) is not int or self.hold_hours <= 0:
            raise ValueError(f"hold_hours must be a positive int; got {self.hold_hours!r}")
        if type(self.threshold_min_prior) is not int or self.threshold_min_prior < 1:
            raise ValueError(
                f"threshold_min_prior must be a positive int; got {self.threshold_min_prior!r}"
            )


def build_signal_frame(
    scores_df: pd.DataFrame,
    fills_dir: Path,
    *,
    config: WalletReverseSignalConfig | None = None,
) -> pd.DataFrame:
    """Build (timestamp, coin, direction, entry, exit) frame from scores + fills.

    Joins scores by (wallet, fill_id) with the original fills parquets to recover
    timestamp and direction. Reverses direction (long → short, sell → long).

    The score percentile threshold is computed with an EXPANDING PRIOR-window
    over fill timestamps: at each fill F with timestamp T, the gate threshold
    uses only the score distribution of fills with timestamp strictly before T.
    This is point-in-time correct (spec rule "Time-series boundary slicing
    must be strict-less-than").
    """
    config = config or WalletReverseSignalConfig()
    if scores_df.empty:
        return _empty_signal_frame()

    fills_by_wallet: dict[str, pd.DataFrame] = {}
    score_with_time = _attach_timestamps(scores_df, fills_dir, fills_by_wallet)
    if score_with_time.empty:
        return _empty_signal_frame()

    # Sort by time; the threshold at fill F with time T uses the score
    # distribution of all fills with time strictly less than T (NOT row-order
    # less-than — same-timestamp fills must not see each other's scores).
    score_with_time = score_with_time.sort_values("time").reset_index(drop=True)

    # For each row, find the last row index with time strictly less than its
    # own time. searchsorted(side="left") on the sorted time series gives
    # the count of rows with time < current_time, which is exactly the cutoff.
    times = score_with_time["time"].to_numpy()
    sorted_times = pd.DatetimeIndex(times)
    prior_counts = sorted_times.searchsorted(times, side="left")

    scores_values = score_with_time["score"].to_numpy()
    n_rows = len(score_with_time)
    keep_flags = [False] * n_rows
    for i in range(n_rows):
        n_prior = int(prior_counts[i])
        if n_prior < config.threshold_min_prior:
            continue
        prior_scores = scores_values[:n_prior]
        threshold = float(pd.Series(prior_scores).quantile(config.score_percentile))
        keep_flags[i] = bool(scores_values[i] >= threshold)

    high_score = score_with_time.loc[keep_flags].copy()
    if high_score.empty:
        return _empty_signal_frame()

    rows: list[dict[str, object]] = []
    for _, row in high_score.iterrows():
        wallet_dir = _normalize_direction(row.get("dir"), row.get("side"))
        if wallet_dir is None:
            continue
        reverse_dir = "short" if wallet_dir == "long" else "long"
        entry_ts = pd.Timestamp(row["time"])
        if entry_ts.tzinfo is None:
            entry_ts = entry_ts.tz_localize("UTC")
        else:
            entry_ts = entry_ts.tz_convert("UTC")
        exit_ts = entry_ts + pd.Timedelta(hours=config.hold_hours)
        coin = str(row["coin"]).upper()
        rows.append(
            {
                "timestamp": entry_ts,
                "coin": coin,
                "direction": reverse_dir,
                "entry": True,
                "exit": False,
                "score": float(row["score"]),
                "wallet": str(row["wallet"]).lower(),
            }
        )
        rows.append(
            {
                "timestamp": exit_ts,
                "coin": coin,
                "direction": reverse_dir,
                "entry": False,
                "exit": True,
                "score": float(row["score"]),
                "wallet": str(row["wallet"]).lower(),
            }
        )

    if not rows:
        return _empty_signal_frame()

    frame = pd.DataFrame(rows)
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True)
    return frame.sort_values("timestamp").reset_index(drop=True)


def _attach_timestamps(
    scores_df: pd.DataFrame,
    fills_dir: Path,
    fills_cache: dict[str, pd.DataFrame],
) -> pd.DataFrame:
    """Attach fill `time`, `dir`, `side`, `coin` to scores via per-wallet fills.

    Drops score rows whose fill_id has no matching tid in the wallet's fills.
    """
    enriched: list[pd.DataFrame] = []
    for wallet, group in scores_df.groupby("wallet", sort=False):
        wallet_str = str(wallet).lower()
        fills = fills_cache.get(wallet_str)
        if fills is None:
            path = fills_dir / f"{wallet_str}.parquet"
            if not path.exists():
                continue
            fills = pd.read_parquet(path)
            if "time" not in fills.columns:
                if fills.index.name == "time":
                    fills = fills.reset_index()
                elif "timestamp" in fills.columns:
                    fills = fills.rename(columns={"timestamp": "time"})
                else:
                    continue
            time_series = fills["time"]
            if pd.api.types.is_integer_dtype(time_series):
                fills = fills.assign(
                    time=pd.to_datetime(time_series, unit="ms", utc=True)
                )
            else:
                fills = fills.assign(time=pd.to_datetime(time_series, utc=True))
            fills_cache[wallet_str] = fills

        if "tid" not in fills.columns:
            continue
        fills_subset = fills[["tid", "time", "coin", "dir", "side"]].copy()
        fills_subset["tid"] = fills_subset["tid"].astype(str)
        group_local = group.copy()
        group_local["fill_id"] = group_local["fill_id"].astype(str)
        joined = group_local.merge(
            fills_subset, left_on="fill_id", right_on="tid", how="inner",
            suffixes=("", "_fill"),
        )
        enriched.append(joined)

    if not enriched:
        return pd.DataFrame()
    out = pd.concat(enriched, ignore_index=True)
    return out


def _normalize_direction(dir_value: object, side_value: object) -> str | None:
    """Hyperliquid fill ``dir`` is 'Open Long' / 'Open Short' / 'Close Long' etc.

    Treat 'Open Long' / 'Close Short' as the wallet's effective long position;
    'Open Short' / 'Close Long' as effective short. Also handle liquidation
    and auto-deleveraging variants (which carry the same Long/Short suffix)
    and ``A > B`` net-flip notation (the wallet ends up in direction B).

    Per R1 finding: explicitly handle high-information events (liquidations,
    ADL, flips) rather than silently dropping them.
    """
    if dir_value is None or (isinstance(dir_value, float) and pd.isna(dir_value)):
        # Fall back to side (B/A)
        if isinstance(side_value, str):
            up = side_value.upper()
            return "long" if up == "B" else "short" if up == "A" else None
        return None
    text = str(dir_value).strip().lower()
    if not text:
        return None
    # Handle net-flip notation 'A > B' — wallet ends in direction B.
    if " > " in text:
        # 'long > short' → short; 'short > long' → long
        right = text.split(" > ", 1)[1].strip()
        if "long" in right:
            return "long"
        if "short" in right:
            return "short"
        return None
    # Tokens that semantically mean the wallet was in a LONG position:
    if "open long" in text or "close short" in text:
        return "long"
    if "open short" in text or "close long" in text:
        return "short"
    # Liquidation / ADL preserve the position direction: "Liquidated ... Long"
    # is a forced close of a long → was long. ADL same.
    if "liquidat" in text or "deleverag" in text or "adl" in text:
        if "long" in text:
            return "long"
        if "short" in text:
            return "short"
    return None


def _empty_signal_frame() -> pd.DataFrame:
    return pd.DataFrame(
        columns=["timestamp", "coin", "direction", "entry", "exit", "score", "wallet"]
    )
