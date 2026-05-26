"""Build the Phase 4 bot-wallet exclusion pool parquet."""

from __future__ import annotations

import argparse
import sys
import time
from datetime import timedelta
from pathlib import Path
from typing import Any

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from bot_reverse.bot_detector import compute_bot_features, score_bot_likelihood
from infra.fetchers.leaderboard import fetch_leaderboard
from infra.fetchers.user_fills import fetch_user_fills


DEFAULT_OUT = Path("data/parquet/bot_wallets.parquet")
DEFAULT_TOP_N = 500
DEFAULT_MAX_WALLETS = 500
DEFAULT_THROTTLE_MS = 200
DEFAULT_MIN_BOT_SCORE = 0.5
LOOKBACK_DAYS = 90

BOT_POOL_COLUMNS = [
    "wallet",
    "bot_score",
    "hour_entropy",
    "size_cv",
    "coin_diversity",
    "session_gap_min",
    "round_number_pct",
]

BOT_POOL_SCHEMA = pa.schema(
    [
        ("wallet", pa.string()),
        ("bot_score", pa.float64()),
        ("hour_entropy", pa.float64()),
        ("size_cv", pa.float64()),
        ("coin_diversity", pa.float64()),
        ("session_gap_min", pa.float64()),
        ("round_number_pct", pa.float64()),
    ]
)


def build_bot_pool(
    out: Path = DEFAULT_OUT,
    top_n: int | None = None,
    max_wallets: int = DEFAULT_MAX_WALLETS,
    min_bot_score: float = DEFAULT_MIN_BOT_SCORE,
    throttle_ms: int = DEFAULT_THROTTLE_MS,
    lookback_days: int = LOOKBACK_DAYS,
    as_of: pd.Timestamp | None = None,
    leaderboard: pd.DataFrame | None = None,
) -> dict[str, Any]:
    """Run the Phase 4 bot scoring pipeline and write the parquet."""

    started = time.perf_counter()
    as_of_ts = _coerce_as_of(as_of)
    lookback_start = (as_of_ts - timedelta(days=lookback_days)).to_pydatetime()
    lookback_end = as_of_ts.to_pydatetime()

    source = leaderboard if leaderboard is not None else fetch_leaderboard()
    selected = source.head(top_n).copy() if top_n is not None else source.copy()

    rows: list[dict[str, Any]] = []
    fetched = 0
    failed = 0
    human_excluded = 0
    total = len(selected)

    for position, record in enumerate(selected.itertuples(index=False), start=1):
        wallet = str(getattr(record, "eth_address", "") or "").lower()
        if not wallet:
            continue

        wallet_started = time.perf_counter()
        try:
            fills = fetch_user_fills(wallet, lookback_start, lookback_end)
        except Exception as error:  # noqa: BLE001
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

        fetched += 1
        features = compute_bot_features(fills, account_value=float(getattr(record, "account_value", 0.0) or 0.0))
        bot_score = score_bot_likelihood(features)
        if bot_score < min_bot_score:
            human_excluded += 1
        else:
            rows.append(
                {
                    "wallet": wallet,
                    "bot_score": bot_score,
                    "hour_entropy": features["tx_hour_entropy"],
                    "size_cv": features["size_uniformity_cv"],
                    "coin_diversity": features["coin_diversity"],
                    "session_gap_min": features["avg_session_gap_minutes"],
                    "round_number_pct": features["round_number_pct"],
                }
            )

        _log(
            position,
            total,
            wallet,
            f"scored {bot_score:.3f} from {int(len(fills))} fills",
            wallet_started,
            started,
        )
        _sleep(throttle_ms, position, total)

    rows = sorted(rows, key=lambda row: (-float(row["bot_score"]), row["wallet"]))
    if max_wallets > 0:
        rows = rows[:max_wallets]

    pool = pd.DataFrame(rows, columns=BOT_POOL_COLUMNS)
    _write_pool(pool, out)

    runtime = time.perf_counter() - started
    return {
        "out": out,
        "written_count": int(len(pool)),
        "leaderboard_count": int(len(selected)),
        "wallets_fetched": fetched,
        "wallets_failed": failed,
        "human_excluded_count": human_excluded,
        "runtime_seconds": runtime,
        "as_of": as_of_ts,
    }


def _write_pool(pool: pd.DataFrame, out: Path) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    frame = pool.copy()[BOT_POOL_COLUMNS]
    frame["wallet"] = frame["wallet"].astype("string").str.lower()
    for column in BOT_POOL_COLUMNS[1:]:
        frame[column] = pd.to_numeric(frame[column], errors="coerce").astype("float64")
    table = pa.Table.from_pandas(frame, schema=BOT_POOL_SCHEMA, preserve_index=False)
    pq.write_table(table, out, compression=None, use_dictionary=False, row_group_size=64)


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
    print("bot pool funnel:")
    print(f"  leaderboard rows fetched: {result['leaderboard_count']}")
    print(f"  wallets fetched: {result['wallets_fetched']}")
    print(f"  wallets failed: {result['wallets_failed']}")
    print(f"  human retail excluded: {result['human_excluded_count']}")
    print(f"  written rows: {result['written_count']}")
    print(f"  wrote: {result['out']}")
    print(f"  runtime seconds: {result['runtime_seconds']:.1f}")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build the Phase 4 bot wallet pool.")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--top-n", type=int, default=DEFAULT_TOP_N)
    parser.add_argument("--max-wallets", type=int, default=DEFAULT_MAX_WALLETS)
    parser.add_argument("--min-bot-score", type=float, default=DEFAULT_MIN_BOT_SCORE)
    parser.add_argument("--throttle-ms", type=int, default=DEFAULT_THROTTLE_MS)
    parser.add_argument("--lookback-days", type=int, default=LOOKBACK_DAYS)
    parser.add_argument("--as-of", type=_parse_timestamp, default=None)
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
    if args.max_wallets <= 0:
        parser.error("--max-wallets must be greater than 0")
    if not 0.0 <= args.min_bot_score <= 1.0:
        parser.error("--min-bot-score must be between 0 and 1")
    if args.throttle_ms < 0:
        parser.error("--throttle-ms must be non-negative")
    if args.lookback_days <= 0:
        parser.error("--lookback-days must be greater than 0")


def main() -> int:
    args = _parse_args()
    result = build_bot_pool(
        out=args.out,
        top_n=args.top_n,
        max_wallets=args.max_wallets,
        min_bot_score=args.min_bot_score,
        throttle_ms=args.throttle_ms,
        lookback_days=args.lookback_days,
        as_of=args.as_of,
    )
    _print_summary(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
