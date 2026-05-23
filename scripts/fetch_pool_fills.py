from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from infra.fetchers.user_fills import fetch_user_fills
from infra.storage import read_wallets, write_fills_parquet


DEFAULT_OUT_DIR = Path("data/parquet/fills")


def fetch_pool_fills(
    top_n: int = 50,
    lookback_days: int = 180,
    throttle_ms: int = 200,
    out_dir: Path = DEFAULT_OUT_DIR,
    skip_existing: bool = True,
    now: datetime | None = None,
) -> dict[str, Any]:
    started = time.perf_counter()
    end = now or datetime.now(tz=timezone.utc)
    start = end - timedelta(days=lookback_days)
    out_dir.mkdir(parents=True, exist_ok=True)

    wallets = read_wallets()
    selected = wallets.head(min(top_n, len(wallets))).copy()
    total = len(selected)
    summary = {
        "wallets_total": total,
        "wallets_fetched": 0,
        "wallets_skipped": 0,
        "wallets_failed": 0,
        "total_fills": 0,
        "disk_size_bytes": 0,
        "runtime_seconds": 0.0,
    }

    for position, row in enumerate(selected.itertuples(index=False), start=1):
        wallet_started = time.perf_counter()
        address = str(row.eth_address).lower()
        path = out_dir / f"{address}.parquet"

        if skip_existing and _cached_parquet_has_rows(path):
            summary["wallets_skipped"] += 1
            _log_progress(position, total, address, "skipped cached fills", wallet_started, started)
            _sleep_if_needed(throttle_ms, position, total)
            continue

        try:
            fills = fetch_user_fills(address, start, end)
            write_fills_parquet(fills, address, path=path)
        except Exception as error:  # noqa: BLE001
            summary["wallets_failed"] += 1
            _log_progress(
                position,
                total,
                address,
                f"warning: fetch failed: {error}",
                wallet_started,
                started,
            )
            _sleep_if_needed(throttle_ms, position, total)
            continue

        n_fills = int(len(fills))
        summary["wallets_fetched"] += 1
        summary["total_fills"] += n_fills
        _log_progress(position, total, address, f"fetched {n_fills} fills", wallet_started, started)
        _sleep_if_needed(throttle_ms, position, total)

    summary["disk_size_bytes"] = _directory_size_bytes(out_dir)
    summary["runtime_seconds"] = time.perf_counter() - started
    return summary


def _cached_parquet_has_rows(path: Path) -> bool:
    if not path.exists():
        return False
    try:
        return not pd.read_parquet(path).empty
    except (OSError, ValueError):
        return False


def _directory_size_bytes(path: Path) -> int:
    return sum(file.stat().st_size for file in path.glob("*.parquet") if file.is_file())


def _log_progress(
    position: int,
    total: int,
    address: str,
    message: str,
    wallet_started: float,
    started: float,
) -> None:
    wallet_elapsed = time.perf_counter() - wallet_started
    total_elapsed = time.perf_counter() - started
    print(
        f"[{position}/{total}] {address} {message} "
        f"({wallet_elapsed:.1f}s, total runtime {total_elapsed:.1f}s)",
        file=sys.stderr,
    )


def _sleep_if_needed(throttle_ms: int, position: int, total: int) -> None:
    if throttle_ms > 0 and position < total:
        time.sleep(throttle_ms / 1000)


def _print_summary(summary: dict[str, Any]) -> None:
    print(f"wallets fetched: {summary['wallets_fetched']}")
    print(f"wallets skipped: {summary['wallets_skipped']}")
    print(f"wallets failed: {summary['wallets_failed']}")
    print(f"total fills: {summary['total_fills']}")
    print(f"disk size bytes: {summary['disk_size_bytes']}")
    print(f"runtime seconds: {summary['runtime_seconds']:.1f}")


def _parse_bool(value: str) -> bool:
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "y"}:
        return True
    if normalized in {"0", "false", "no", "n"}:
        return False
    raise argparse.ArgumentTypeError("expected a boolean value")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Batch fetch Hyperliquid fills for wallet pool.")
    parser.add_argument("--top-n", type=int, default=50)
    parser.add_argument("--lookback-days", type=int, default=180)
    parser.add_argument("--throttle-ms", type=int, default=200)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--skip-existing", type=_parse_bool, default=True)
    args = parser.parse_args()
    _validate_args(parser, args)
    return args


def _validate_args(parser: argparse.ArgumentParser, args: argparse.Namespace) -> None:
    if args.top_n <= 0:
        parser.error("--top-n must be greater than 0")
    if args.lookback_days <= 0:
        parser.error("--lookback-days must be greater than 0")
    if args.throttle_ms < 0:
        parser.error("--throttle-ms must be non-negative")


def main() -> int:
    args = _parse_args()
    summary = fetch_pool_fills(
        top_n=args.top_n,
        lookback_days=args.lookback_days,
        throttle_ms=args.throttle_ms,
        out_dir=args.out_dir,
        skip_existing=args.skip_existing,
    )
    _print_summary(summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
