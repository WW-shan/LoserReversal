"""Bot-cluster reverse signal generation."""

from __future__ import annotations

import math
import warnings
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any, Mapping

import pandas as pd


@dataclass(frozen=True)
class BotClusterConfig:
    n_bots_min: int = 3
    window_minutes: int = 30
    bot_score_threshold: float = 0.7
    hold_hours: int = 24

    def __post_init__(self) -> None:
        if type(self.n_bots_min) is not int or self.n_bots_min < 2:
            raise ValueError(f"n_bots_min must be an int >= 2; got {self.n_bots_min!r}")
        if type(self.window_minutes) is not int or self.window_minutes <= 0:
            raise ValueError(
                f"window_minutes must be an int > 0; got {self.window_minutes!r}"
            )
        if isinstance(self.bot_score_threshold, bool):
            raise ValueError(
                "bot_score_threshold must be a finite float-like value in "
                f"(0.0, 1.0]; got {self.bot_score_threshold!r}"
            )
        try:
            bot_score_threshold = float(self.bot_score_threshold)
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError(
                "bot_score_threshold must be a finite float-like value in "
                f"(0.0, 1.0]; got {self.bot_score_threshold!r}"
            ) from exc
        if not math.isfinite(bot_score_threshold) or not 0.0 < bot_score_threshold <= 1.0:
            raise ValueError(
                "bot_score_threshold must be a finite float-like value in "
                f"(0.0, 1.0]; got {self.bot_score_threshold!r}"
            )
        object.__setattr__(self, "bot_score_threshold", bot_score_threshold)
        if type(self.hold_hours) is not int or self.hold_hours <= 0:
            raise ValueError(f"hold_hours must be an int > 0; got {self.hold_hours!r}")


def cluster_bot_signal(
    fills_by_wallet: Mapping[str, pd.DataFrame],
    bot_scores: Mapping[str, float],
    prices: Mapping[str, pd.Series],
    *,
    config: BotClusterConfig,
) -> dict[str, tuple[pd.DataFrame, pd.DataFrame]]:
    """Return reverse entries/exits from bot-wallet fill clusters.

    ``fills_by_wallet`` maps wallet addresses to fill frames with ``coin``, ``dir``,
    and optional ``time`` columns. ``bot_scores`` maps wallet addresses to numeric
    bot-likelihood scores; NaN scores fail closed and are excluded. ``prices`` maps
    coins to close-price series whose index defines the output signal bars.

    The returned dict maps coin to ``(entries, exits)`` boolean frames with
    ``long`` and ``short`` columns. Bot ``Open Long`` clusters create reverse
    ``short`` signals; bot ``Open Short`` clusters create reverse ``long`` signals.
    Cluster windows are inclusive on both sides, ``[T-window_minutes, T]``, at the
    event-detection timestamp and do not look ahead beyond ``T``.
    """
    _validate_config(config)
    price_indexes = _price_indexes(prices)
    signals = {
        coin: (_empty_signal(index), _empty_signal(index)) for coin, index in price_indexes.items()
    }
    if not fills_by_wallet or not price_indexes:
        return signals

    bot_wallets = {
        str(wallet).lower()
        for wallet, score in bot_scores.items()
        if _coerce_float(score) >= config.bot_score_threshold
    }
    if not bot_wallets:
        return signals

    fills = _cluster_input_frame(fills_by_wallet, bot_wallets, price_indexes.keys())
    if fills.empty:
        return signals

    for coin, coin_fills in fills.groupby("coin", sort=False):
        entries, exits = signals[str(coin)]
        candidates = _cluster_candidates(
            coin_fills,
            n_bots_min=config.n_bots_min,
            window_minutes=config.window_minutes,
        )
        _apply_candidates(
            candidates,
            entries,
            exits,
            hold_hours=config.hold_hours,
        )
    return signals


def _empty_signal(index: pd.Index) -> pd.DataFrame:
    signal_index = pd.DatetimeIndex(pd.to_datetime(index, utc=True), name=getattr(index, "name", None))
    return pd.DataFrame(False, index=signal_index, columns=["long", "short"])


def _validate_config(config: BotClusterConfig) -> None:
    config.__post_init__()


def _price_indexes(prices: Mapping[str, pd.Series]) -> dict[str, pd.DatetimeIndex]:
    indexes: dict[str, pd.DatetimeIndex] = {}
    for coin, price in prices.items():
        index = pd.DatetimeIndex(pd.to_datetime(price.index, utc=True), name=getattr(price.index, "name", None))
        indexes[str(coin)] = index.sort_values()
    return indexes


def _cluster_input_frame(
    fills_by_wallet: Mapping[str, pd.DataFrame],
    bot_wallets: set[str],
    coin_filter: Iterable[str],
) -> pd.DataFrame:
    frames = [
        _wallet_events(wallet, fills)
        for wallet, fills in fills_by_wallet.items()
        if str(wallet).lower() in bot_wallets
    ]
    if not frames:
        return _empty_events()

    frame = pd.concat(frames, ignore_index=True)
    if frame.empty:
        return _empty_events()

    coins = {str(coin) for coin in coin_filter}
    frame = frame.loc[frame["coin"].isin(coins)].copy()
    if frame.empty:
        return _empty_events()
    return frame.sort_values(["coin", "bot_dir", "time", "wallet"]).reset_index(drop=True)


def _wallet_events(wallet: str, fills: pd.DataFrame) -> pd.DataFrame:
    if fills.empty or "coin" not in fills.columns or "dir" not in fills.columns:
        return _empty_events()

    columns = ["coin", "dir"]
    if "time" in fills.columns:
        columns.append("time")
    frame = fills.loc[:, columns].copy()
    if "time" in fills.columns:
        frame["time"] = pd.to_datetime(frame["time"], utc=True, errors="coerce")
    else:
        frame["time"] = pd.to_datetime(fills.index, utc=True, errors="coerce")

    frame["wallet"] = str(wallet).lower()
    frame["coin"] = frame["coin"].astype("string")
    frame["bot_dir"] = frame["dir"].astype("string")
    frame["reverse_dir"] = frame["bot_dir"].map(
        {
            "Open Long": "short",
            "Open Short": "long",
        }
    )
    mask = frame["time"].notna()
    mask &= frame["coin"].notna()
    mask &= frame["reverse_dir"].notna()
    return frame.loc[mask, ["wallet", "coin", "time", "bot_dir", "reverse_dir"]].reset_index(
        drop=True
    )


def _cluster_candidates(
    fills: pd.DataFrame,
    *,
    n_bots_min: int,
    window_minutes: int,
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    window = pd.Timedelta(minutes=window_minutes)
    for bot_dir, direction_fills in fills.groupby("bot_dir", sort=False):
        sorted_fills = direction_fills.sort_values(["time", "wallet"]).reset_index(drop=True)
        reverse_dir = str(sorted_fills["reverse_dir"].iloc[0])
        for current_time in sorted_fills["time"]:
            window_start = current_time - window
            in_window = sorted_fills.loc[
                (sorted_fills["time"] >= window_start) & (sorted_fills["time"] <= current_time)
            ]
            bot_count = int(in_window["wallet"].nunique())
            if bot_count < n_bots_min:
                continue
            rows.append(
                {
                    "time": pd.Timestamp(current_time),
                    "bot_dir": str(bot_dir),
                    "reverse_dir": reverse_dir,
                    "bot_count": bot_count,
                }
            )

    if not rows:
        return pd.DataFrame(
            {
                "time": pd.Series(dtype="datetime64[ns, UTC]"),
                "bot_dir": pd.Series(dtype="string"),
                "reverse_dir": pd.Series(dtype="string"),
                "bot_count": pd.Series(dtype="int64"),
            }
        )
    return pd.DataFrame(rows).sort_values(["time", "reverse_dir"]).reset_index(drop=True)


def _apply_candidates(
    candidates: pd.DataFrame,
    entries: pd.DataFrame,
    exits: pd.DataFrame,
    *,
    hold_hours: int,
) -> None:
    active_dir: str | None = None
    hold_exit_at: pd.Timestamp | None = None
    hold_delta = pd.Timedelta(hours=hold_hours)

    for row in candidates.itertuples(index=False):
        candidate_time = pd.Timestamp(row.time)
        reverse_dir = str(row.reverse_dir)
        if hold_exit_at is not None and hold_exit_at <= candidate_time:
            expired_dir = active_dir
            exit_bar = _align_to_price_index(entries.index, hold_exit_at)
            if exit_bar is not None and expired_dir is not None:
                exits.at[exit_bar, expired_dir] = True
            defer_same_direction = (
                expired_dir is not None
                and reverse_dir == expired_dir
                and candidate_time == hold_exit_at
            )
            active_dir = None
            hold_exit_at = None
            if defer_same_direction:
                next_bar = _next_price_bar_after(
                    entries.index,
                    exit_bar if exit_bar is not None else candidate_time,
                )
                if next_bar is None:
                    continue
                candidate_time = next_bar

        entry_bar = _align_to_price_index(entries.index, candidate_time)
        if entry_bar is None:
            continue
        if active_dir is None:
            entries.at[entry_bar, reverse_dir] = True
            active_dir = reverse_dir
            hold_exit_at = entry_bar + hold_delta
        elif reverse_dir != active_dir:
            exits.at[entry_bar, active_dir] = True
            entries.at[entry_bar, reverse_dir] = True
            active_dir = reverse_dir
            hold_exit_at = entry_bar + hold_delta

    if hold_exit_at is not None and active_dir is not None:
        exit_bar = _align_to_price_index(entries.index, hold_exit_at)
        if exit_bar is not None:
            exits.at[exit_bar, active_dir] = True
        else:
            warnings.warn(
                f"trailing position at {hold_exit_at} has hold_exit_at past end of price index",
                RuntimeWarning,
                stacklevel=2,
            )


def _align_to_price_index(index: pd.DatetimeIndex, timestamp: pd.Timestamp) -> pd.Timestamp | None:
    if index.empty:
        return None
    ts = pd.Timestamp(timestamp)
    if ts.tzinfo is None:
        ts = ts.tz_localize("UTC")
    else:
        ts = ts.tz_convert("UTC")
    position = index.searchsorted(ts, side="left")
    if position >= len(index):
        return None
    return pd.Timestamp(index[position])


def _next_price_bar_after(index: pd.DatetimeIndex, timestamp: pd.Timestamp) -> pd.Timestamp | None:
    if index.empty:
        return None
    ts = pd.Timestamp(timestamp)
    if ts.tzinfo is None:
        ts = ts.tz_localize("UTC")
    else:
        ts = ts.tz_convert("UTC")
    position = index.searchsorted(ts, side="right")
    if position >= len(index):
        return None
    return pd.Timestamp(index[position])


def _empty_events() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "wallet": pd.Series(dtype="string"),
            "coin": pd.Series(dtype="string"),
            "time": pd.Series(dtype="datetime64[ns, UTC]"),
            "bot_dir": pd.Series(dtype="string"),
            "reverse_dir": pd.Series(dtype="string"),
        }
    )


def _coerce_float(value: object) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float("nan")
