"""Phase 2.5 Slice 1 — build the academic anti-alpha wallet pool parquet.

Pulls the Hyperliquid public leaderboard, iterates per-wallet 90-day fills
via ``userFillsByTime``, computes the 5 academic metrics, applies the
inclusive thresholds, and writes the qualifying pool to
``data/parquet/academic_wallet_pool.parquet``.

Replaces the Phase 2 v1 ``scripts/build_wallet_pool.py`` selection logic
(``vlm DESC`` whale cohort) with the literature-review.md Part B criteria
(``account_value`` band + persistent loss + leverage + activity + size CV).
"""

from __future__ import annotations

import argparse
import re
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import requests
import tenacity

from infra.fetchers.leaderboard import fetch_leaderboard
from infra.fetchers.user_fills import fetch_user_fills
from wallet_pool.academic_pool import (
    LOOKBACK_DAYS,
    MAX_ACCOUNT_VALUE,
    MIN_ACCOUNT_VALUE,
    POOL_COLUMNS,
    REQUIRED_FILL_COLUMNS,
    build_academic_pool_with_funnel,
)


DEFAULT_OUT = Path("data/parquet/academic_wallet_pool.parquet")
DEFAULT_REPORT = Path("reports/phase_2_5_slice_1_wallet_pool.md")
DEFAULT_TOP_N = 2000  # Targets ROADMAP 200-500 final pool; assumes ~30-50%
# of worst-PnL top-2000 land in $1k-$100k band per Phase 1 v1 funnel.
DEFAULT_THROTTLE_MS = 200
CACHE_DIR = Path("data/cache/user_fills")
HEX40_RE = re.compile(r"^0x[0-9a-f]{40}$")

POOL_SCHEMA = pa.schema(
    [
        ("wallet", pa.string()),
        ("account_value", pa.float64()),
        ("realized_loss_rate_90d", pa.float64()),
        ("leverage_avg_90d", pa.float64()),
        ("n_trades_90d", pa.int64()),
        ("size_cv_90d", pa.float64()),
        ("eligible_at", pa.timestamp("us", tz="UTC")),
    ]
)


def build_academic_wallet_pool(
    out: Path = DEFAULT_OUT,
    report: Path | None = None,
    top_n: int | None = DEFAULT_TOP_N,
    throttle_ms: int = DEFAULT_THROTTLE_MS,
    lookback_days: int = LOOKBACK_DAYS,
    as_of: pd.Timestamp | None = None,
    leaderboard: pd.DataFrame | None = None,
    rebuild_cache: bool = False,
) -> dict[str, Any]:
    """Run the full pipeline and write the resulting pool parquet.

    The leaderboard is pre-filtered to the academic account-value band before
    applying ``top_n``. The default ``DEFAULT_TOP_N`` is 2000 to sample enough
    in-band wallets from a worst-PnL ordered leaderboard.
    """

    started = time.perf_counter()
    as_of_ts = _coerce_as_of(as_of)
    lookback_start = (as_of_ts - timedelta(days=lookback_days)).to_pydatetime()
    lookback_end = as_of_ts.to_pydatetime()

    source = leaderboard if leaderboard is not None else fetch_leaderboard()
    leaderboard_pre_filter = int(len(source))
    source = source.copy()
    source["eth_address"] = source["eth_address"].astype("string").str.strip().str.lower()
    source = source.drop_duplicates(subset="eth_address", keep="first")
    source["account_value"] = pd.to_numeric(source["account_value"], errors="coerce")
    in_band = source.loc[
        (source["account_value"] >= MIN_ACCOUNT_VALUE)
        & (source["account_value"] <= MAX_ACCOUNT_VALUE)
    ].copy()
    pre_filtered_band = int(len(in_band))
    selected = in_band.head(top_n).copy() if top_n is not None else in_band.copy()

    fills_by_wallet: dict[str, pd.DataFrame] = {}
    fetched = 0
    failed = 0
    total = len(selected)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)

    for position, record in enumerate(selected.itertuples(index=False), start=1):
        raw_address = getattr(record, "eth_address", None)
        if raw_address is None or pd.isna(raw_address):
            continue
        wallet = str(raw_address).strip().lower()
        if not wallet:
            continue

        wallet_started = time.perf_counter()
        try:
            cache_path = _cache_path(wallet, lookback_start, lookback_end)
            fills = None
            if cache_path is not None and cache_path.exists() and not rebuild_cache:
                fills = _read_cached_fills(cache_path)
            if fills is None:
                fills = fetch_user_fills(wallet, lookback_start, lookback_end)
                if cache_path is not None and not fills.empty:
                    _write_cached_fills(cache_path, fills)
                source_label = "fetched"
            else:
                source_label = "cache"
        except (
            requests.HTTPError,
            requests.ConnectionError,
            requests.Timeout,
            tenacity.RetryError,
        ) as error:
            failed += 1
            _log(
                position,
                total,
                wallet,
                f"warning: fetch failed: {error}",
                wallet_started,
                started,
            )
            _sleep(throttle_ms, position, total)
            continue

        fills_by_wallet[wallet] = fills
        fetched += 1
        _log(
            position,
            total,
            wallet,
            f"{source_label} {int(len(fills))} fills",
            wallet_started,
            started,
        )
        _sleep(throttle_ms, position, total)

    pool, funnel = build_academic_pool_with_funnel(
        selected,
        fills_by_wallet,
        as_of=as_of_ts,
        lookback_days=lookback_days,
    )
    funnel = {
        "leaderboard_pre_filter": leaderboard_pre_filter,
        "pre_filtered_band": pre_filtered_band,
        **funnel,
    }

    _write_pool(pool, out)

    runtime = time.perf_counter() - started
    result = {
        "out": out,
        "report": report,
        "written_count": int(len(pool)),
        "wallets_fetched": fetched,
        "wallets_failed": failed,
        "funnel": funnel,
        "runtime_seconds": runtime,
        "as_of": as_of_ts,
    }
    if report is not None:
        _write_report(report, result)
    return result


def _write_pool(pool: pd.DataFrame, out: Path) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    frame = pool.copy()[POOL_COLUMNS]
    frame["wallet"] = frame["wallet"].astype("string").str.lower()
    frame["eligible_at"] = pd.to_datetime(frame["eligible_at"], utc=True)
    for column in (
        "account_value",
        "realized_loss_rate_90d",
        "leverage_avg_90d",
        "size_cv_90d",
    ):
        frame[column] = pd.to_numeric(frame[column], errors="coerce").astype("float64")
    frame["n_trades_90d"] = pd.to_numeric(frame["n_trades_90d"], errors="coerce").astype("int64")

    table = pa.Table.from_pandas(frame, schema=POOL_SCHEMA, preserve_index=False)
    pq.write_table(table, out, compression=None, use_dictionary=False, row_group_size=64)


def _cache_path(
    wallet: str,
    lookback_start: datetime,
    lookback_end: datetime,
) -> Path | None:
    """Return cache path for wallet+window, or None if wallet is malformed.

    Default ``as_of`` uses current time, so cross-minute CLI reruns create new
    entries; pass ``--as-of`` explicitly for reproducible cache reuse.
    """

    if not HEX40_RE.fullmatch(wallet):
        return None
    key = (
        f"{wallet}_"
        f"{lookback_start.strftime('%Y%m%dT%H%M')}_"
        f"{lookback_end.strftime('%Y%m%dT%H%M')}"
    )
    return CACHE_DIR / f"{key}.parquet"


def _read_cached_fills(cache_path: Path) -> pd.DataFrame | None:
    try:
        cached = pd.read_parquet(cache_path)
    except (OSError, pa.lib.ArrowInvalid, pa.lib.ArrowIOError) as error:
        print(
            f"warning: cached fills at {cache_path} unreadable ({error}); refetching",
            file=sys.stderr,
        )
        cache_path.unlink(missing_ok=True)
        return None
    missing = REQUIRED_FILL_COLUMNS - set(cached.columns)
    if missing:
        print(
            f"warning: cached fills at {cache_path} missing columns "
            f"{sorted(missing)}; refetching",
            file=sys.stderr,
        )
        cache_path.unlink(missing_ok=True)
        return None
    if "time" not in cached.columns and not isinstance(cached.index, pd.DatetimeIndex):
        print(
            f"warning: cached fills at {cache_path} missing time axis; refetching",
            file=sys.stderr,
        )
        cache_path.unlink(missing_ok=True)
        return None
    if "time" in cached.columns:
        cached["time"] = pd.to_datetime(cached["time"], utc=True, errors="coerce")
    return cached


def _write_cached_fills(cache_path: Path, fills: pd.DataFrame) -> None:
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    frame = fills.reset_index() if "time" not in fills.columns else fills.copy()
    frame.to_parquet(cache_path, index=False)


def _write_report(report: Path, result: dict[str, Any]) -> None:
    funnel = result["funnel"]
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(
        "\n".join(
            [
                "# Phase 2.5 Slice 1 Academic Wallet Pool",
                "",
                "## Summary",
                f"- As of: {result['as_of'].isoformat()}",
                f"- Leaderboard rows before script pre-filter: {funnel['leaderboard_pre_filter']}",
                f"- After script account-value band pre-filter: {funnel['pre_filtered_band']}",
                f"- Leaderboard rows fetched: {funnel['leaderboard']}",
                f"- After valid address filter: {funnel['valid_address']}",
                f"- After positive account value filter: {funnel['positive_account_value']}",
                f"- After fills available filter: {funnel['fills_available']}",
                f"- After account_value filter: {funnel['account_value']}",
                f"- After realized_loss_rate filter: {funnel['realized_loss_rate']}",
                f"- After leverage filter: {funnel['leverage']}",
                f"- After n_trades filter: {funnel['n_trades']}",
                f"- After size_cv filter: {funnel['size_cv']}",
                f"- Final pool size: {funnel['final']}",
                f"- Wallets fetched: {result['wallets_fetched']}",
                f"- Wallets failed: {result['wallets_failed']}",
                f"- Output: `{result['out']}`",
                f"- Runtime seconds: {result['runtime_seconds']:.2f}",
                "",
            ]
        ),
        encoding="utf-8",
    )


def _coerce_as_of(as_of: pd.Timestamp | None) -> pd.Timestamp:
    if as_of is None:
        return pd.Timestamp.now(tz="UTC")
    if as_of.tzinfo is None:
        return as_of.tz_localize("UTC")
    return as_of.tz_convert("UTC")


def _log(
    position: int,
    total: int,
    wallet: str,
    message: str,
    wallet_started: float,
    started: float,
) -> None:
    elapsed = time.perf_counter() - wallet_started
    total_elapsed = time.perf_counter() - started
    print(
        f"[{position}/{total}] {wallet} {message} "
        f"({elapsed:.1f}s, total runtime {total_elapsed:.1f}s)",
        file=sys.stderr,
    )


def _sleep(throttle_ms: int, position: int, total: int) -> None:
    if throttle_ms > 0 and position < total:
        time.sleep(throttle_ms / 1000)


def _print_summary(result: dict[str, Any]) -> None:
    funnel = result["funnel"]
    print("academic pool funnel:")
    print(f"  leaderboard rows before script pre-filter: {funnel['leaderboard_pre_filter']}")
    print(f"  after script account-value band pre-filter: {funnel['pre_filtered_band']}")
    print(f"  leaderboard rows fetched: {funnel['leaderboard']}")
    print(f"  after valid address filter: {funnel['valid_address']}")
    print(f"  after positive account value filter: {funnel['positive_account_value']}")
    print(f"  after fills available filter: {funnel['fills_available']}")
    print(f"  after account_value filter: {funnel['account_value']}")
    print(f"  after realized_loss_rate filter: {funnel['realized_loss_rate']}")
    print(f"  after leverage filter: {funnel['leverage']}")
    print(f"  after n_trades filter: {funnel['n_trades']}")
    print(f"  after size_cv filter: {funnel['size_cv']}")
    print(f"  final pool size: {funnel['final']}")
    print(f"wallets fetched: {result['wallets_fetched']}")
    print(f"wallets failed: {result['wallets_failed']}")
    print(f"written rows: {result['written_count']}")
    print(f"wrote: {result['out']}")
    if result["report"] is not None:
        print(f"report: {result['report']}")
    print(f"runtime seconds: {result['runtime_seconds']:.1f}")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build the Phase 2.5 academic wallet pool.")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--report", type=Path, default=None)
    parser.add_argument("--top-n", type=int, default=DEFAULT_TOP_N)
    parser.add_argument("--throttle-ms", type=int, default=DEFAULT_THROTTLE_MS)
    parser.add_argument("--lookback-days", type=int, default=LOOKBACK_DAYS)
    parser.add_argument("--as-of", type=_parse_timestamp, default=None)
    parser.add_argument("--rebuild-cache", action="store_true")
    args = parser.parse_args()
    _validate_args(parser, args)
    return args


def _parse_timestamp(value: str) -> pd.Timestamp:
    ts = pd.Timestamp(value)
    if ts.tzinfo is None:
        ts = ts.tz_localize("UTC")
    return ts.tz_convert("UTC")


def _validate_args(parser: argparse.ArgumentParser, args: argparse.Namespace) -> None:
    if args.top_n <= 0:
        parser.error("--top-n must be greater than 0")
    if args.throttle_ms < 0:
        parser.error("--throttle-ms must be non-negative")
    if args.lookback_days <= 0:
        parser.error("--lookback-days must be greater than 0")


def main() -> int:
    args = _parse_args()
    result = build_academic_wallet_pool(
        out=args.out,
        report=args.report,
        top_n=args.top_n,
        throttle_ms=args.throttle_ms,
        lookback_days=args.lookback_days,
        as_of=args.as_of,
        rebuild_cache=args.rebuild_cache,
    )
    _print_summary(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
