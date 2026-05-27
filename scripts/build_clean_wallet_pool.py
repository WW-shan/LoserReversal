"""Phase 2.5 Slice 3 — build the bot-filtered retail anti-alpha wallet pool."""

from __future__ import annotations

import argparse
import sys
import time
from datetime import timedelta
from pathlib import Path
from typing import Any

import pandas as pd

from bot_reverse.bot_detector import compute_bot_features, score_bot_likelihood
from infra.fetchers.user_fills import fetch_user_fills
from wallet_pool.bot_exclusion import (
    BotExclusionConfig,
    exclude_bots_from_pool,
    exclude_funding_source_clusters,
    funding_source_graph,
)


DEFAULT_ACADEMIC_POOL = Path("data/parquet/academic_wallet_pool.parquet")
DEFAULT_CLEAN_OUT = Path("data/parquet/clean_retail_pool.parquet")
DEFAULT_EXCLUDED_OUT = Path("data/parquet/excluded_bot_pool.parquet")
DEFAULT_FUNDING_SOURCES = Path("data/parquet/wallet_funding_sources.parquet")
DEFAULT_THROTTLE_MS = 200
DEFAULT_MIN_TRADES = 10
LOOKBACK_DAYS = 90
EXCLUDED_COLUMNS = ["wallet", "bot_score", "reason"]


def build_clean_wallet_pool(
    academic_pool_path: Path = DEFAULT_ACADEMIC_POOL,
    clean_out: Path = DEFAULT_CLEAN_OUT,
    excluded_out: Path = DEFAULT_EXCLUDED_OUT,
    funding_sources_path: Path = DEFAULT_FUNDING_SOURCES,
    bot_score_threshold: float = 0.5,
    funding_source_graph_max_shared: int = 3,
    throttle_ms: int = DEFAULT_THROTTLE_MS,
    min_trades_for_scoring: int = DEFAULT_MIN_TRADES,
    fetch_attempts: int = 3,
    retry_backoff_seconds: float = 0.25,
    lookback_days: int = LOOKBACK_DAYS,
    as_of: pd.Timestamp | None = None,
) -> dict[str, Any]:
    started = time.perf_counter()
    as_of_ts = _coerce_as_of(as_of)
    pool = _read_academic_pool(academic_pool_path)
    bot_scores, fetched, failed_wallets = _score_wallets(
        pool,
        as_of=as_of_ts,
        lookback_days=lookback_days,
        throttle_ms=throttle_ms,
        min_trades_for_scoring=min_trades_for_scoring,
        fetch_attempts=fetch_attempts,
        retry_backoff_seconds=retry_backoff_seconds,
        started=started,
    )

    config = BotExclusionConfig(
        bot_score_threshold=bot_score_threshold,
        funding_source_graph_max_shared=funding_source_graph_max_shared,
    )
    score_clean_pool, score_excluded = exclude_bots_from_pool(
        pool,
        bot_scores,
        config=config,
    )
    fetch_failed_excluded = _fetch_failed_excluded(failed_wallets)
    score_clean_pool = _remove_wallets(score_clean_pool, fetch_failed_excluded["wallet"])

    funding_sources = _read_funding_sources(funding_sources_path)
    funding_graph = funding_source_graph(funding_sources, as_of=as_of_ts)
    cluster_excluded = exclude_funding_source_clusters(
        score_clean_pool,
        funding_graph,
        max_shared=config.funding_source_graph_max_shared,
    )
    clean_pool = _remove_wallets(score_clean_pool, cluster_excluded["wallet"])
    excluded_pool = _combine_excluded(
        score_excluded,
        cluster_excluded,
        fetch_failed_excluded,
        bot_scores,
    )

    _write_frame(clean_pool, clean_out)
    _write_frame(excluded_pool, excluded_out)

    runtime = time.perf_counter() - started
    funnel = {
        "academic_pool": int(len(pool)),
        "bot_scores_computed": int(len(bot_scores)),
        "bot_score_excluded": int(len(score_excluded)),
        "fetch_failed_excluded": int(len(fetch_failed_excluded)),
        "funding_source_excluded": int(len(cluster_excluded)),
        "clean_retail_pool": int(len(clean_pool)),
        "excluded_bot_pool": int(len(excluded_pool)),
    }
    return {
        "clean_out": clean_out,
        "excluded_out": excluded_out,
        "wallets_fetched": fetched,
        "wallets_failed": len(failed_wallets),
        "funnel": funnel,
        "runtime_seconds": runtime,
        "as_of": as_of_ts,
    }


def _read_academic_pool(path: Path) -> pd.DataFrame:
    frame = pd.read_parquet(path)
    if "wallet" in frame.columns:
        frame["wallet"] = frame["wallet"].astype("string").str.lower()
    if "eligible_at" in frame.columns:
        frame["eligible_at"] = pd.to_datetime(frame["eligible_at"], utc=True)
    return frame.reset_index(drop=True)


def _score_wallets(
    pool: pd.DataFrame,
    *,
    as_of: pd.Timestamp,
    lookback_days: int,
    throttle_ms: int,
    min_trades_for_scoring: int,
    fetch_attempts: int,
    retry_backoff_seconds: float,
    started: float,
) -> tuple[pd.DataFrame, int, list[str]]:
    rows: list[dict[str, Any]] = []
    fetched = 0
    failed_wallets: list[str] = []
    total = len(pool)
    lookback_start = (as_of - timedelta(days=lookback_days)).to_pydatetime()
    lookback_end = as_of.to_pydatetime()

    for position, record in enumerate(pool.itertuples(index=False), start=1):
        wallet = str(getattr(record, "wallet", "") or "").lower()
        if not wallet:
            continue
        wallet_started = time.perf_counter()
        fills, error = _fetch_with_retries(
            wallet,
            lookback_start,
            lookback_end,
            fetch_attempts=fetch_attempts,
            retry_backoff_seconds=retry_backoff_seconds,
        )
        if error is not None or fills is None:
            failed_wallets.append(wallet)
            _log(
                position,
                total,
                wallet,
                f"warning: fetch failed after {fetch_attempts} attempts: {error}",
                wallet_started,
                started,
            )
            _sleep(throttle_ms, position, total)
            continue

        fetched += 1
        features = compute_bot_features(fills)
        bot_score = score_bot_likelihood(
            features,
            min_trades_for_scoring=min_trades_for_scoring,
        )
        rows.append({"wallet": wallet, "bot_score": bot_score})
        _log(position, total, wallet, f"scored {bot_score:.3f}", wallet_started, started)
        _sleep(throttle_ms, position, total)

    return pd.DataFrame(rows, columns=["wallet", "bot_score"]), fetched, failed_wallets


def _fetch_with_retries(
    wallet: str,
    lookback_start: Any,
    lookback_end: Any,
    *,
    fetch_attempts: int,
    retry_backoff_seconds: float,
) -> tuple[pd.DataFrame | None, Exception | None]:
    last_error: Exception | None = None
    for attempt in range(1, fetch_attempts + 1):
        try:
            return fetch_user_fills(wallet, lookback_start, lookback_end), None
        except Exception as error:  # noqa: BLE001
            last_error = error
            if attempt < fetch_attempts and retry_backoff_seconds > 0:
                time.sleep(retry_backoff_seconds * (2 ** (attempt - 1)))
    return None, last_error


def _read_funding_sources(path: Path) -> pd.DataFrame:
    if not path.exists():
        print(
            f"warning: funding sources file not found at {path}; skipping clustering",
            file=sys.stderr,
        )
        return pd.DataFrame(
            {
                "wallet": pd.Series(dtype="string"),
                "from_address": pd.Series(dtype="string"),
            }
        )
    return pd.read_parquet(path)


def _remove_wallets(pool: pd.DataFrame, wallets: pd.Series) -> pd.DataFrame:
    if pool.empty or wallets.empty:
        return pool.reset_index(drop=True)
    excluded_wallets = set(wallets.astype("string").str.lower())
    mask = ~pool["wallet"].astype("string").str.lower().isin(excluded_wallets)
    return pool.loc[mask].reset_index(drop=True)


def _combine_excluded(
    score_excluded: pd.DataFrame,
    cluster_excluded: pd.DataFrame,
    fetch_failed_excluded: pd.DataFrame,
    bot_scores: pd.DataFrame,
) -> pd.DataFrame:
    score_rows = score_excluded.copy()
    score_rows = score_rows[EXCLUDED_COLUMNS] if not score_rows.empty else _empty_excluded()

    if cluster_excluded.empty:
        cluster_rows = _empty_excluded()
    else:
        score_map = bot_scores.set_index("wallet")["bot_score"].to_dict()
        cluster_rows = pd.DataFrame(
            {
                "wallet": cluster_excluded["wallet"].astype("string").str.lower(),
                "bot_score": cluster_excluded["wallet"].map(score_map).astype("float64"),
                "reason": cluster_excluded["reason"].astype("string"),
            },
            columns=EXCLUDED_COLUMNS,
        )

    excluded = pd.concat([score_rows, fetch_failed_excluded, cluster_rows], ignore_index=True)
    if excluded.empty:
        return _empty_excluded()
    excluded["wallet"] = excluded["wallet"].astype("string").str.lower()
    excluded["bot_score"] = pd.to_numeric(excluded["bot_score"], errors="coerce").astype("float64")
    excluded["reason"] = excluded["reason"].astype("string")
    return excluded[EXCLUDED_COLUMNS].reset_index(drop=True)


def _fetch_failed_excluded(wallets: list[str]) -> pd.DataFrame:
    if not wallets:
        return _empty_excluded()
    return pd.DataFrame(
        {
            "wallet": pd.Series(wallets, dtype="string").str.lower(),
            "bot_score": pd.Series([pd.NA] * len(wallets), dtype="Float64"),
            "reason": pd.Series(["fetch_failed"] * len(wallets), dtype="string"),
        },
        columns=EXCLUDED_COLUMNS,
    )


def _write_frame(frame: pd.DataFrame, out: Path) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(out, index=False)


def _empty_excluded() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "wallet": pd.Series(dtype="string"),
            "bot_score": pd.Series(dtype="float64"),
            "reason": pd.Series(dtype="string"),
        },
        columns=EXCLUDED_COLUMNS,
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
    print("clean wallet pool funnel:")
    print(f"  academic pool rows: {funnel['academic_pool']}")
    print(f"  bot scores computed: {funnel['bot_scores_computed']}")
    print(f"  bot score excluded: {funnel['bot_score_excluded']}")
    print(f"  fetch failed excluded: {funnel['fetch_failed_excluded']}")
    print(f"  funding source excluded: {funnel['funding_source_excluded']}")
    print(f"  clean retail pool rows: {funnel['clean_retail_pool']}")
    print(f"  excluded bot pool rows: {funnel['excluded_bot_pool']}")
    print(f"wallets fetched: {result['wallets_fetched']}")
    print(f"wallets failed: {result['wallets_failed']}")
    print(f"clean out: {result['clean_out']}")
    print(f"excluded out: {result['excluded_out']}")
    print(f"runtime seconds: {result['runtime_seconds']:.1f}")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build the Phase 2.5 clean retail wallet pool.")
    parser.add_argument("--academic-pool", type=Path, default=DEFAULT_ACADEMIC_POOL)
    parser.add_argument("--clean-out", type=Path, default=DEFAULT_CLEAN_OUT)
    parser.add_argument("--excluded-out", type=Path, default=DEFAULT_EXCLUDED_OUT)
    parser.add_argument("--funding-sources", type=Path, default=DEFAULT_FUNDING_SOURCES)
    parser.add_argument("--bot-score-threshold", type=float, default=0.5)
    parser.add_argument("--funding-source-max-shared", type=int, default=3)
    parser.add_argument("--throttle-ms", type=int, default=DEFAULT_THROTTLE_MS)
    parser.add_argument("--min-trades", type=int, default=DEFAULT_MIN_TRADES)
    parser.add_argument("--fetch-attempts", type=int, default=3)
    parser.add_argument("--retry-backoff-seconds", type=float, default=0.25)
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
    if not 0.0 < args.bot_score_threshold <= 1.0:
        parser.error("--bot-score-threshold must be greater than 0 and at most 1")
    if args.funding_source_max_shared <= 1:
        parser.error("--funding-source-max-shared must be greater than 1")
    if args.throttle_ms < 0:
        parser.error("--throttle-ms must be non-negative")
    if args.min_trades <= 0:
        parser.error("--min-trades must be greater than 0")
    if args.fetch_attempts <= 0:
        parser.error("--fetch-attempts must be greater than 0")
    if args.retry_backoff_seconds < 0:
        parser.error("--retry-backoff-seconds must be non-negative")
    if args.lookback_days <= 0:
        parser.error("--lookback-days must be greater than 0")


def main() -> int:
    args = _parse_args()
    result = build_clean_wallet_pool(
        academic_pool_path=args.academic_pool,
        clean_out=args.clean_out,
        excluded_out=args.excluded_out,
        funding_sources_path=args.funding_sources,
        bot_score_threshold=args.bot_score_threshold,
        funding_source_graph_max_shared=args.funding_source_max_shared,
        throttle_ms=args.throttle_ms,
        min_trades_for_scoring=args.min_trades,
        fetch_attempts=args.fetch_attempts,
        retry_backoff_seconds=args.retry_backoff_seconds,
        lookback_days=args.lookback_days,
        as_of=args.as_of,
    )
    _print_summary(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
