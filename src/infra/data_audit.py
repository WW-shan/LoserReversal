"""Data audit helpers for unlock research inputs."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from infra.storage import read_unlocks


COVERAGE_STATUSES = ("ok", "listing_after", "insufficient_pre_days", "no_candle_file")


def compute_event_candle_coverage(unlocks_path: Path, candles_dir: Path) -> pd.DataFrame:
    unlocks = read_unlocks(unlocks_path)
    if pd.api.types.is_bool_dtype(unlocks["has_hl_perp"]):
        mask = unlocks["has_hl_perp"]
    else:
        mask = unlocks["has_hl_perp"].astype("string").str.lower().eq("true")

    rows: list[dict[str, object]] = []
    for event in unlocks.loc[mask].itertuples(index=False):
        token = str(event.token)
        unlock_date = _coerce_utc_midnight(event.unlock_date)
        candle_path = candles_dir / f"{token}_1d.parquet"
        candle_earliest = _read_candle_earliest(candle_path)

        pre_event_days: int | pd.NA = pd.NA
        if candle_earliest is None:
            status = "no_candle_file"
        elif candle_earliest > unlock_date:
            status = "listing_after"
        else:
            pre_event_days = int((unlock_date - candle_earliest).days)
            status = "ok" if pre_event_days >= 60 else "insufficient_pre_days"

        rows.append(
            {
                "token": token,
                "unlock_date": unlock_date.date(),
                "candle_earliest": candle_earliest,
                "pre_event_days": pre_event_days,
                "coverage_status": status,
            }
        )

    frame = pd.DataFrame(
        rows,
        columns=[
            "token",
            "unlock_date",
            "candle_earliest",
            "pre_event_days",
            "coverage_status",
        ],
    )
    if not frame.empty:
        frame["pre_event_days"] = frame["pre_event_days"].astype("Int64")
    return frame


def _coerce_utc_midnight(value: object) -> pd.Timestamp:
    ts = pd.Timestamp(value)
    if ts.tz is None:
        ts = ts.tz_localize("UTC")
    else:
        ts = ts.tz_convert("UTC")
    return ts.normalize()


def _read_candle_earliest(path: Path) -> pd.Timestamp | None:
    if not path.exists():
        return None
    try:
        frame = pd.read_parquet(path, columns=["timestamp"])
    except Exception:
        return None
    if frame.empty or "timestamp" not in frame:
        return None
    timestamps = pd.to_datetime(frame["timestamp"], utc=True)
    return pd.Timestamp(timestamps.min()).normalize()
