"""Build the Phase 4 bot-wallet exclusion pool parquet."""

from __future__ import annotations

import argparse
import os
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
DEFAULT_MIN_TRADES = 10
CHECKPOINT_EVERY_WALLETS = 10
LOOKBACK_DAYS = 90

BOT_POOL_COLUMNS = [
    "wallet",
    "bot_score",
    "hour_entropy",
    "size_cv",
    "coin_diversity",
    "session_gap_median_min",
    "round_number_pct",
]

BOT_POOL_SCHEMA = pa.schema(
    [
        ("wallet", pa.string()),
        ("bot_score", pa.float64()),
        ("hour_entropy", pa.float64()),
        ("size_cv", pa.float64()),
        ("coin_diversity", pa.float64()),
        ("session_gap_median_min", pa.float64()),
        ("round_number_pct", pa.float64()),
    ]
)

CHECKPOINT_COLUMNS = [*BOT_POOL_COLUMNS, "status", "processed_at"]

CHECKPOINT_SCHEMA = pa.schema(
    [
        ("wallet", pa.string()),
        ("bot_score", pa.float64()),
        ("hour_entropy", pa.float64()),
        ("size_cv", pa.float64()),
        ("coin_diversity", pa.float64()),
        ("session_gap_median_min", pa.float64()),
        ("round_number_pct", pa.float64()),
        ("status", pa.string()),
        ("processed_at", pa.string()),
    ]
)


def build_bot_pool(
    out: Path = DEFAULT_OUT,
    top_n: int | None = None,
    max_wallets: int = DEFAULT_MAX_WALLETS,
    min_bot_score: float = DEFAULT_MIN_BOT_SCORE,
    min_trades_for_scoring: int = DEFAULT_MIN_TRADES,
    throttle_ms: int = DEFAULT_THROTTLE_MS,
    lookback_days: int = LOOKBACK_DAYS,
    as_of: pd.Timestamp | None = None,
    leaderboard: pd.DataFrame | None = None,
    resume: bool = False,
) -> dict[str, Any]:
    """Run the Phase 4 bot scoring pipeline and write the parquet."""

    started = time.perf_counter()
    as_of_ts = _coerce_as_of(as_of)
    lookback_start = (as_of_ts - timedelta(days=lookback_days)).to_pydatetime()
    lookback_end = as_of_ts.to_pydatetime()

    source = leaderboard if leaderboard is not None else fetch_leaderboard()
    selected = source.copy()
    selected["eth_address"] = selected["eth_address"].astype("string").str.lower()
    selected = selected.drop_duplicates(subset="eth_address", keep="first")
    if top_n is not None:
        selected = selected.head(top_n)
    selected = selected.copy()

    checkpoint_path = _checkpoint_path(out)
    processed_rows, seen_wallets = _load_checkpoint(checkpoint_path) if resume else ([], set())
    fetched = 0
    failed = 0
    human_excluded = 0
    checkpoint_skipped = 0
    total = len(selected)

    try:
        for position, record in enumerate(selected.itertuples(index=False), start=1):
            raw_wallet = getattr(record, "eth_address", None)
            if raw_wallet is None or pd.isna(raw_wallet):
                continue
            wallet = str(raw_wallet).lower()
            if not wallet or wallet == "<na>":
                continue
            if wallet in seen_wallets:
                checkpoint_skipped += 1
                continue

            wallet_started = time.perf_counter()
            try:
                fills = fetch_user_fills(wallet, lookback_start, lookback_end)
            except Exception as error:  # noqa: BLE001
                failed += 1
                processed_rows = [
                    row for row in processed_rows if str(row.get("wallet", "")).lower() != wallet
                ]
                processed_rows.append(_checkpoint_row(wallet, status="failed"))
                _log(
                    position,
                    total,
                    wallet,
                    f"warning: fetch failed: {error}",
                    wallet_started,
                    started,
                )
                _sleep(throttle_ms, position, total)
                _checkpoint_if_needed(processed_rows, checkpoint_path, resume, position)
                continue

            fetched += 1
            features = compute_bot_features(fills)
            bot_score = score_bot_likelihood(
                features,
                min_trades_for_scoring=min_trades_for_scoring,
            )
            if bot_score < min_bot_score:
                human_excluded += 1
                status = "human"
            else:
                status = "bot"
            processed_rows = [
                row for row in processed_rows if str(row.get("wallet", "")).lower() != wallet
            ]
            processed_rows.append(
                _checkpoint_row(
                    wallet,
                    status=status,
                    bot_score=bot_score,
                    features=features,
                )
            )
            seen_wallets.add(wallet)

            _log(
                position,
                total,
                wallet,
                f"scored {bot_score:.3f} from {int(len(fills))} fills",
                wallet_started,
                started,
            )
            _sleep(throttle_ms, position, total)
            _checkpoint_if_needed(processed_rows, checkpoint_path, resume, position)
    except KeyboardInterrupt:
        if resume:
            _save_checkpoint(processed_rows, checkpoint_path)
            print(f"interrupted; saved checkpoint to {checkpoint_path}", file=sys.stderr)
        raise

    rows = sorted(
        _bot_rows(processed_rows),
        key=lambda row: (-float(row["bot_score"]), row["wallet"]),
    )
    if max_wallets > 0:
        rows = rows[:max_wallets]

    pool = pd.DataFrame(rows, columns=BOT_POOL_COLUMNS)
    _write_pool(pool, out)
    checkpoint_path.unlink(missing_ok=True)

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
        "resumed_from_checkpoint": bool(resume),
        "checkpoint_skipped_count": checkpoint_skipped,
    }


def _write_pool(pool: pd.DataFrame, out: Path) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    frame = pool.copy()
    frame = frame.reindex(columns=BOT_POOL_COLUMNS)
    frame["wallet"] = frame["wallet"].astype("string").str.lower()
    for column in BOT_POOL_COLUMNS[1:]:
        frame[column] = pd.to_numeric(frame[column], errors="coerce").astype("float64")
    table = pa.Table.from_pandas(frame, schema=BOT_POOL_SCHEMA, preserve_index=False)
    pq.write_table(table, out, compression=None, use_dictionary=False, row_group_size=64)


def _checkpoint_path(out: Path) -> Path:
    return Path(f"{out}.tmp.parquet")


def _load_checkpoint(path: Path) -> tuple[list[dict[str, Any]], set[str]]:
    if not path.exists():
        return [], set()
    try:
        checkpoint = pd.read_parquet(path)
    except Exception as error:  # noqa: BLE001
        print(f"warning: checkpoint at {path} is unreadable ({error}); starting fresh", file=sys.stderr)
        return [], set()
    missing = set(CHECKPOINT_COLUMNS) - set(checkpoint.columns)
    if missing:
        print(
            f"warning: checkpoint at {path} missing columns {sorted(missing)}; starting fresh",
            file=sys.stderr,
        )
        return [], set()
    checkpoint = checkpoint.reindex(columns=CHECKPOINT_COLUMNS)
    checkpoint["wallet"] = checkpoint["wallet"].astype("string").str.lower()
    checkpoint["status"] = checkpoint["status"].astype("string").str.lower()
    checkpoint = checkpoint.dropna(subset=["wallet"])
    checkpoint = checkpoint.loc[checkpoint["wallet"].ne("")]
    for column in BOT_POOL_COLUMNS[1:]:
        checkpoint[column] = pd.to_numeric(checkpoint[column], errors="coerce")
    checkpoint = checkpoint.loc[checkpoint["bot_score"].notna() | checkpoint["status"].eq("failed")]
    wallets = set(
        checkpoint.loc[
            checkpoint["status"].astype("string").isin(["bot", "human"]),
            "wallet",
        ]
        .astype("string")
        .str.lower()
        .dropna()
    )
    return checkpoint.to_dict("records"), wallets


def _save_checkpoint(rows: list[dict[str, Any]], path: Path) -> None:
    partial = path.with_suffix(path.suffix + ".partial")
    try:
        _write_checkpoint(pd.DataFrame(rows, columns=CHECKPOINT_COLUMNS), partial)
        os.replace(partial, path)
    except Exception:
        partial.unlink(missing_ok=True)
        raise


def _write_checkpoint(rows: pd.DataFrame | list[dict[str, Any]], out: Path) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    frame = pd.DataFrame(rows, columns=CHECKPOINT_COLUMNS)
    frame["wallet"] = frame["wallet"].astype("string").str.lower()
    for column in BOT_POOL_COLUMNS[1:]:
        frame[column] = pd.to_numeric(frame[column], errors="coerce").astype("float64")
    frame["status"] = frame["status"].astype("string").str.lower()
    frame["processed_at"] = frame["processed_at"].astype("string")
    table = pa.Table.from_pandas(frame, schema=CHECKPOINT_SCHEMA, preserve_index=False)
    pq.write_table(table, out, compression=None, use_dictionary=False, row_group_size=64)


def _checkpoint_row(
    wallet: str,
    *,
    status: str,
    bot_score: float = float("nan"),
    features: dict[str, float] | None = None,
) -> dict[str, Any]:
    features = features or {}
    return {
        "wallet": wallet,
        "bot_score": bot_score,
        "hour_entropy": features.get("tx_hour_entropy", float("nan")),
        "size_cv": features.get("size_uniformity_cv", float("nan")),
        "coin_diversity": features.get("coin_diversity", float("nan")),
        "session_gap_median_min": features.get("median_session_gap_minutes", float("nan")),
        "round_number_pct": features.get("round_number_pct", float("nan")),
        "status": status,
        "processed_at": pd.Timestamp.now(tz="UTC").isoformat(),
    }


def _bot_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {column: row.get(column) for column in BOT_POOL_COLUMNS}
        for row in rows
        if str(row.get("status", "")).lower() == "bot"
    ]


def _checkpoint_if_needed(
    rows: list[dict[str, Any]],
    checkpoint_path: Path,
    resume: bool,
    position: int,
) -> None:
    if resume and position % CHECKPOINT_EVERY_WALLETS == 0:
        _save_checkpoint(rows, checkpoint_path)


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
        f"[{position}/{total}] {wallet} {message}"
        f" ({elapsed:.1f}s, total runtime {total_elapsed:.1f}s)",
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
    if result.get("resumed_from_checkpoint"):
        skipped = int(result.get("checkpoint_skipped_count", 0))
        print(f"  resumed: yes (skipped {skipped} previously-processed wallets)")
        print(
            "  metrics note: this run only; resume checkpoints track processed wallets "
            "during recovery, not cumulative metrics"
        )
    print(f"  wrote: {result['out']}")
    print(f"  runtime seconds: {result['runtime_seconds']:.1f}")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build the Phase 4 bot wallet pool.")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--top-n", type=int, default=DEFAULT_TOP_N)
    parser.add_argument("--max-wallets", type=int, default=DEFAULT_MAX_WALLETS)
    parser.add_argument("--min-bot-score", type=float, default=DEFAULT_MIN_BOT_SCORE)
    parser.add_argument("--min-trades", type=int, default=DEFAULT_MIN_TRADES)
    parser.add_argument("--throttle-ms", type=int, default=DEFAULT_THROTTLE_MS)
    parser.add_argument("--lookback-days", type=int, default=LOOKBACK_DAYS)
    parser.add_argument("--as-of", type=_parse_timestamp, default=None)
    parser.add_argument("--resume", action="store_true")
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
    if args.min_trades <= 0:
        parser.error("--min-trades must be greater than 0")
    if args.throttle_ms < 0:
        parser.error("--throttle-ms must be non-negative")
    if args.lookback_days <= 0:
        parser.error("--lookback-days must be greater than 0")


def main() -> int:
    args = _parse_args()
    try:
        result = build_bot_pool(
            out=args.out,
            top_n=args.top_n,
            max_wallets=args.max_wallets,
            min_bot_score=args.min_bot_score,
            min_trades_for_scoring=args.min_trades,
            throttle_ms=args.throttle_ms,
            lookback_days=args.lookback_days,
            as_of=args.as_of,
            resume=args.resume,
        )
    except KeyboardInterrupt:
        if not args.resume:
            print("interrupted; exiting without checkpoint because --resume is disabled", file=sys.stderr)
        return 130
    _print_summary(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
