"""Build the anti-alpha wallet pool parquet from the Hyperliquid leaderboard."""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from infra.fetchers.leaderboard import fetch_leaderboard
from infra.storage import WALLET_COLUMNS, write_wallets_parquet


def build_wallet_pool(
    min_loss: float = -10_000.0,
    min_volume: float = 500_000.0,
    top_n: int = 500,
    out: Path = Path("data/parquet/anti_alpha_wallets.parquet"),
    limit: int | None = None,
) -> dict[str, object]:
    leaderboard = fetch_leaderboard()
    total_fetched = len(leaderboard)
    source = leaderboard.head(limit).copy() if limit is not None else leaderboard
    filtered = source.loc[
        (source["pnl_alltime"] <= min_loss)
        & (source["vlm_alltime"] >= min_volume)
        & ((source["account_value"] > 0) | (source["vlm_alltime"] >= 10_000_000))
    ].copy()
    pool = filtered.sort_values("vlm_alltime", ascending=False).head(top_n).copy()
    pool["added_at"] = pd.Timestamp.now(tz="UTC")
    pool = pool[WALLET_COLUMNS]

    written = write_wallets_parquet(pool, path=out)
    return {
        "path": written,
        "total_fetched": total_fetched,
        "source_count": len(source),
        "filtered_count": len(filtered),
        "written_count": len(pool),
        "sample": filtered.sort_values("pnl_alltime", ascending=True).head(5),
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build the Hyperliquid anti-alpha wallet pool.")
    parser.add_argument("--min-loss", type=float, default=-10_000.0)
    parser.add_argument("--min-volume", type=float, default=500_000.0)
    parser.add_argument("--top-n", type=int, default=500)
    parser.add_argument("--out", type=Path, default=Path("data/parquet/anti_alpha_wallets.parquet"))
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()
    _validate_args(parser, args)
    return args


def _validate_args(parser: argparse.ArgumentParser, args: argparse.Namespace) -> None:
    if args.top_n <= 0:
        parser.error("--top-n must be greater than 0")
    if args.min_volume < 0:
        parser.error("--min-volume must be non-negative")
    if args.limit is not None and args.limit <= 0:
        parser.error("--limit must be greater than 0 when provided")


def _print_summary(result: dict[str, object]) -> None:
    sample = result["sample"]
    print(f"total fetched: {result['total_fetched']}")
    if result["source_count"] != result["total_fetched"]:
        print(f"source after limit: {result['source_count']}")
    print(f"filtered count: {result['filtered_count']}")
    print(f"written wallets: {result['written_count']}")
    print(f"wrote: {result['path']}")
    print("top 5 worst PnL:")
    if isinstance(sample, pd.DataFrame) and not sample.empty:
        print(
            sample[
                ["eth_address", "pnl_alltime", "vlm_alltime", "account_value", "display_name"]
            ].to_string(index=False)
        )
    else:
        print("(none)")


def main() -> int:
    args = _parse_args()
    result = build_wallet_pool(
        min_loss=args.min_loss,
        min_volume=args.min_volume,
        top_n=args.top_n,
        out=args.out,
        limit=args.limit,
    )
    _print_summary(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
