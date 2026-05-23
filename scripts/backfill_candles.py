"""CLI: backfill Hyperliquid candles for unlock tokens."""

from __future__ import annotations

import argparse
import logging
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from infra.fetchers.candles import fetch_candles
from infra.storage import PARQUET_DIR, read_unlocks, write_candles


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_UNLOCKS_PATH = REPO_ROOT / "data" / "parquet" / "unlocks.parquet"
CANDLES_DIR = PARQUET_DIR / "candles"

logger = logging.getLogger(__name__)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    start = _coerce_utc_timestamp(args.start)
    end = _coerce_utc_timestamp(args.end)
    tokens = _requested_tokens(args.tokens)
    if tokens is None:
        tokens = _unlock_tokens(DEFAULT_UNLOCKS_PATH)

    ok = 0
    skipped = 0
    failed = 0
    ranges: dict[str, tuple[pd.Timestamp, pd.Timestamp]] = {}

    for token in tokens:
        target = CANDLES_DIR / f"{token}_{args.interval}.parquet"
        if args.missing_only and _existing_covers_start(target, start):
            skipped += 1
            continue

        try:
            frame = fetch_candles(token, args.interval, start.to_pydatetime(), end.to_pydatetime())
            write_candles(frame, token, args.interval, path=target)
        except Exception as exc:
            failed += 1
            logger.warning("failed to backfill %s: %s", token, exc)
            continue

        ok += 1
        if not frame.empty:
            index = pd.DatetimeIndex(pd.to_datetime(frame.index, utc=True))
            ranges[token] = (index.min(), index.max())

    _print_summary(len(tokens), ok, skipped, failed, ranges)
    return 0


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", default="2023-01-01")
    parser.add_argument("--end", default="now")
    parser.add_argument("--interval", default="1d")
    parser.add_argument("--tokens")
    parser.add_argument("--missing-only", action="store_true")
    return parser.parse_args(argv)


def _coerce_utc_timestamp(value: str) -> pd.Timestamp:
    if value.lower() == "now":
        return pd.Timestamp(datetime.now(timezone.utc))
    ts = pd.Timestamp(value)
    if ts.tz is None:
        return ts.tz_localize("UTC")
    return ts.tz_convert("UTC")


def _requested_tokens(raw: str | None) -> list[str] | None:
    if raw is None:
        return None
    return _stable_unique(token.strip().upper() for token in raw.split(",") if token.strip())


def _unlock_tokens(path: Path) -> list[str]:
    frame = read_unlocks(path)
    if pd.api.types.is_bool_dtype(frame["has_hl_perp"]):
        mask = frame["has_hl_perp"]
    else:
        mask = frame["has_hl_perp"].astype("string").str.lower().eq("true")
    return _stable_unique(frame.loc[mask, "token"].astype("string").str.upper())


def _stable_unique(values) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        if value not in seen:
            out.append(value)
            seen.add(value)
    return out


def _existing_covers_start(path: Path, start: pd.Timestamp) -> bool:
    if not path.exists():
        return False
    try:
        frame = pd.read_parquet(path, columns=["timestamp"])
    except Exception:
        return False
    if frame.empty or "timestamp" not in frame:
        return False
    timestamps = pd.to_datetime(frame["timestamp"], utc=True)
    return bool(timestamps.min() <= start)


def _print_summary(
    total: int,
    ok: int,
    skipped: int,
    failed: int,
    ranges: dict[str, tuple[pd.Timestamp, pd.Timestamp]],
) -> None:
    covered = "n/a"
    if ranges:
        covered = f"{min(start for start, _ in ranges.values()).isoformat()} -> "
        covered += f"{max(end for _, end in ranges.values()).isoformat()}"

    print("backfill_candles summary")
    print(f"total tokens: {total}")
    print(f"tokens fetched OK: {ok}")
    print(f"tokens skipped: {skipped}")
    print(f"tokens failed: {failed}")
    print(f"range covered: {covered}")
    for token, (start, end) in sorted(ranges.items()):
        print(f"{token}: {start.isoformat()} -> {end.isoformat()}")


if __name__ == "__main__":
    raise SystemExit(main())
