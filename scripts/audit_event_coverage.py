"""CLI: audit unlock event candle coverage."""

from __future__ import annotations

import argparse
from pathlib import Path

from infra.data_audit import COVERAGE_STATUSES, compute_event_candle_coverage
from infra.storage import PARQUET_DIR


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_UNLOCKS_PATH = PARQUET_DIR / "unlocks.parquet"
DEFAULT_CANDLES_DIR = PARQUET_DIR / "candles"
DEFAULT_OUTPUT_PATH = PARQUET_DIR / "event_coverage.parquet"


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    coverage = compute_event_candle_coverage(args.unlocks, args.candles_dir)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    coverage.to_parquet(args.output, index=False)

    summary = coverage["coverage_status"].value_counts().reindex(COVERAGE_STATUSES, fill_value=0)
    print("event coverage summary")
    print(summary.to_string())
    print(f"wrote: {args.output}")
    return 0


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--unlocks", type=Path, default=DEFAULT_UNLOCKS_PATH)
    parser.add_argument("--candles-dir", type=Path, default=DEFAULT_CANDLES_DIR)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH)
    return parser.parse_args(argv)


if __name__ == "__main__":
    raise SystemExit(main())
