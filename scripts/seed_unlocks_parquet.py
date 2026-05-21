"""CLI: seed data/parquet/unlocks.parquet from the curated CSV.

Usage:
    uv run python -m scripts.seed_unlocks_parquet
"""

from pathlib import Path

from infra.storage import write_unlocks_csv_to_parquet


REPO_ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    csv = REPO_ROOT / "data" / "seed" / "unlocks_curated.csv"
    out = write_unlocks_csv_to_parquet(csv)
    print(f"wrote {out} ({out.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
