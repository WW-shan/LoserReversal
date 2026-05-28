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

    def __post_init__(self) -> None:
        if not 0.0 < self.score_percentile < 1.0:
            raise ValueError(
                f"score_percentile must be in (0.0, 1.0); got {self.score_percentile!r}"
            )
        if type(self.hold_hours) is not int or self.hold_hours <= 0:
            raise ValueError(f"hold_hours must be a positive int; got {self.hold_hours!r}")


def build_signal_frame(
    scores_df: pd.DataFrame,
    fills_dir: Path,
    *,
    config: WalletReverseSignalConfig | None = None,
) -> pd.DataFrame:
    """Build (timestamp, coin, direction, entry, exit) frame from scores + fills.

    Joins scores by (wallet, fill_id) with the original fills parquets to recover
    timestamp and direction. Reverses direction (long → short, sell → long).
    """
    config = config or WalletReverseSignalConfig()
    if scores_df.empty:
        return _empty_signal_frame()

    threshold = float(scores_df["score"].quantile(config.score_percentile))
    high_score = scores_df[scores_df["score"] >= threshold].copy()
    if high_score.empty:
        return _empty_signal_frame()

    fills_by_wallet: dict[str, pd.DataFrame] = {}
    rows: list[dict[str, object]] = []

    for wallet, group in high_score.groupby("wallet", sort=False):
        wallet_str = str(wallet).lower()
        fills = fills_by_wallet.get(wallet_str)
        if fills is None:
            path = fills_dir / f"{wallet_str}.parquet"
            if not path.exists():
                continue
            fills = pd.read_parquet(path)
            # The user_fills fetcher saves 'time' as the index; older cached
            # files store it as a column. Normalize so it is always a column.
            if "time" not in fills.columns:
                if fills.index.name == "time":
                    fills = fills.reset_index()
                elif "timestamp" in fills.columns:
                    fills = fills.rename(columns={"timestamp": "time"})
                else:
                    continue
            # Normalize time column to UTC datetime regardless of dtype.
            time_series = fills["time"]
            if pd.api.types.is_integer_dtype(time_series):
                fills = fills.assign(
                    time=pd.to_datetime(time_series, unit="ms", utc=True)
                )
            else:
                fills = fills.assign(time=pd.to_datetime(time_series, utc=True))
            fills_by_wallet[wallet_str] = fills

        # Index by stringified tid so score.fill_id (str) joins cleanly.
        if "tid" not in fills.columns:
            continue
        fills_by_tid = fills.set_index(fills["tid"].astype(str), drop=False)
        for _, row in group.iterrows():
            fill_id = str(row["fill_id"])
            if fill_id not in fills_by_tid.index:
                continue
            match = fills_by_tid.loc[fill_id]
            if isinstance(match, pd.DataFrame):
                match = match.iloc[0]
            wallet_dir = _normalize_direction(match.get("dir"), match.get("side"))
            if wallet_dir is None:
                continue
            reverse_dir = "short" if wallet_dir == "long" else "long"
            entry_ts = pd.Timestamp(match["time"])
            if entry_ts.tzinfo is None:
                entry_ts = entry_ts.tz_localize("UTC")
            else:
                entry_ts = entry_ts.tz_convert("UTC")
            exit_ts = entry_ts + pd.Timedelta(hours=config.hold_hours)
            coin = str(match["coin"]).upper()
            rows.append(
                {
                    "timestamp": entry_ts,
                    "coin": coin,
                    "direction": reverse_dir,
                    "entry": True,
                    "exit": False,
                    "score": float(row["score"]),
                    "wallet": wallet_str,
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
                    "wallet": wallet_str,
                }
            )

    if not rows:
        return _empty_signal_frame()

    frame = pd.DataFrame(rows)
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True)
    return frame.sort_values("timestamp").reset_index(drop=True)


def _normalize_direction(dir_value: object, side_value: object) -> str | None:
    """Hyperliquid fill ``dir`` is 'Open Long' / 'Open Short' / 'Close Long' etc.

    Treat 'Open Long' / 'Close Short' as the wallet's effective long position;
    'Open Short' / 'Close Long' as effective short. Ignore other strings.
    """
    if dir_value is None or (isinstance(dir_value, float) and pd.isna(dir_value)):
        # Fall back to side (B/A)
        if isinstance(side_value, str):
            return "long" if side_value.upper() == "B" else "short" if side_value.upper() == "A" else None
        return None
    text = str(dir_value).strip().lower()
    if "open long" in text or "close short" in text:
        return "long"
    if "open short" in text or "close long" in text:
        return "short"
    return None


def _empty_signal_frame() -> pd.DataFrame:
    return pd.DataFrame(
        columns=["timestamp", "coin", "direction", "entry", "exit", "score", "wallet"]
    )
