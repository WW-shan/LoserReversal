"""CLI: backfill Hyperliquid funding history for top-volume perps."""

from __future__ import annotations

import argparse
import logging
import re
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from infra.fetchers.funding import fetch_funding
from infra.hyperliquid_client import HyperliquidClient
from infra.storage import PARQUET_DIR, write_funding


FUNDING_DIR = PARQUET_DIR / "funding"
DEFAULT_START = "2023-05-01"
_VALID_SYMBOL = re.compile(r"^[A-Za-z0-9:_-]{1,32}$")

logger = logging.getLogger(__name__)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    start = _coerce_utc_timestamp(args.start)
    end = _coerce_utc_timestamp(args.end)
    symbols = _requested_symbols(args.tokens)
    if symbols is None:
        symbols = _top_volume_tokens(args.top_n)

    ok = 0
    skipped = 0
    failed = 0
    empty = 0
    stale = 0
    ranges: dict[str, tuple[pd.Timestamp, pd.Timestamp]] = {}

    for symbol in symbols:
        try:
            target = _target_path(symbol)
        except ValueError:
            if args.tokens is not None:
                raise
            skipped += 1
            logger.warning("skipping invalid symbol from universe: %s", symbol)
            continue

        if args.missing_only and _existing_covers_start(target, start):
            skipped += 1
            continue

        try:
            frame = fetch_funding(symbol, start.to_pydatetime(), end.to_pydatetime())
            if frame.empty:
                empty += 1
                logger.warning("empty funding response for %s", symbol)
                continue
            write_funding(frame, symbol, path=target)
        except Exception as exc:
            failed += 1
            logger.warning("failed to backfill %s: %s", symbol, exc)
            continue

        index = pd.DatetimeIndex(pd.to_datetime(frame.index, utc=True))
        ranges[symbol] = (index.min(), index.max())
        if index.max() < end - pd.Timedelta(days=30):
            stale += 1
            logger.warning("stale funding response for %s: latest=%s end=%s", symbol, index.max(), end)
            continue

        ok += 1

    _print_summary(len(symbols), ok, skipped, failed, empty, stale, ranges)
    return 0


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", default=DEFAULT_START)
    parser.add_argument("--end", default="now")
    parser.add_argument("--top-n", type=int, default=30)
    parser.add_argument("--tokens")
    parser.add_argument("--missing-only", action="store_true")
    args = parser.parse_args(argv)
    if args.top_n <= 0:
        parser.error("--top-n must be greater than 0")
    return args


def _coerce_utc_timestamp(value: str) -> pd.Timestamp:
    if value.lower() == "now":
        return pd.Timestamp(datetime.now(timezone.utc))
    ts = pd.Timestamp(value)
    if ts.tz is None:
        return ts.tz_localize("UTC")
    return ts.tz_convert("UTC")


def _requested_symbols(raw: str | None) -> list[str] | None:
    if raw is None:
        return None
    return _stable_unique(symbol.strip() for symbol in raw.split(",") if symbol.strip())


def _top_volume_tokens(top_n: int, client: HyperliquidClient | None = None) -> list[str]:
    volumes = (client or HyperliquidClient()).universe_with_volumes()
    ranked = sorted(volumes.items(), key=lambda item: (-item[1], item[0]))
    return [symbol for symbol, _ in ranked[:top_n]]


def _stable_unique(values) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        if value not in seen:
            out.append(value)
            seen.add(value)
    return out


def _validate_symbol(symbol: str) -> str:
    if not _VALID_SYMBOL.match(symbol):
        raise ValueError(f"invalid symbol: {symbol}")
    return symbol


def _target_path(symbol: str) -> Path:
    safe_symbol = _validate_symbol(symbol)
    target = FUNDING_DIR / f"{safe_symbol}.parquet"
    if not target.resolve().is_relative_to(FUNDING_DIR.resolve()):
        raise ValueError(f"target path outside funding dir: {target}")
    return target


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
    empty: int,
    stale: int,
    ranges: dict[str, tuple[pd.Timestamp, pd.Timestamp]],
) -> None:
    covered = "n/a"
    if ranges:
        covered = f"{min(start for start, _ in ranges.values()).isoformat()} -> "
        covered += f"{max(end for _, end in ranges.values()).isoformat()}"

    print("backfill_funding summary")
    print(f"total tokens: {total}")
    print(f"tokens fetched OK: {ok}")
    print(f"tokens skipped: {skipped}")
    print(f"tokens failed: {failed}")
    print(f"tokens empty: {empty}")
    print(f"tokens stale: {stale}")
    print(f"range covered: {covered}")
    for symbol, (start, end) in sorted(ranges.items()):
        print(f"{symbol}: {start.isoformat()} -> {end.isoformat()}")


if __name__ == "__main__":
    raise SystemExit(main())
