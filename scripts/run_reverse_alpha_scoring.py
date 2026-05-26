"""Phase 2.5 Slice 2 CLI: score academic wallet fills with reverse alpha weights."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from wallet_pool.reverse_signal import ReverseScoreConfig, score_wallet_fills


DEFAULT_POOL = Path("data/parquet/academic_wallet_pool.parquet")
DEFAULT_FILLS_DIR = Path("data/parquet/fills")
DEFAULT_FUNDING_DIR = Path("data/parquet/funding")
DEFAULT_OUT = Path("data/parquet/reverse_alpha_scores.parquet")
DEFAULT_REPORT = Path("reports/phase_2_5_slice_2_reverse_scores.md")

OUTPUT_COLUMNS = ["fill_id", "wallet", "token", "score", "components"]
OUTPUT_SCHEMA = pa.schema(
    [
        ("fill_id", pa.string()),
        ("wallet", pa.string()),
        ("token", pa.string()),
        ("score", pa.float64()),
        ("components", pa.string()),
    ]
)


def run_reverse_alpha_scoring(
    pool_path: Path = DEFAULT_POOL,
    fills_dir: Path = DEFAULT_FILLS_DIR,
    funding_dir: Path = DEFAULT_FUNDING_DIR,
    out: Path = DEFAULT_OUT,
    report: Path | None = DEFAULT_REPORT,
    config: ReverseScoreConfig | None = None,
) -> dict[str, Any]:
    started = time.perf_counter()
    score_config = config or ReverseScoreConfig()
    pool = _read_pool(pool_path)

    frames: list[pd.DataFrame] = []
    funding_cache: dict[str, pd.DataFrame] = {}
    wallets_missing_fills = 0
    wallets_empty_fills = 0
    wallets_scored = 0

    for _, wallet_metrics in pool.iterrows():
        wallet = str(wallet_metrics.get("wallet", "") or "").lower()
        if not wallet:
            continue

        fills_path = fills_dir / f"{wallet}.parquet"
        if not fills_path.exists():
            wallets_missing_fills += 1
            continue

        fills = pd.read_parquet(fills_path)
        if fills.empty:
            wallets_empty_fills += 1
            continue

        tokens = _fill_tokens(fills)
        funding_history = _load_funding_history(funding_dir, tokens, funding_cache)
        scored = score_wallet_fills(
            fills,
            wallet_metrics.to_dict(),
            funding_history,
            config=score_config,
        )
        if scored.empty:
            wallets_empty_fills += 1
            continue

        scored["wallet"] = wallet
        scored["token"] = tokens[: len(scored)]
        scored["components"] = scored["components"].map(_components_json)
        frames.append(scored[OUTPUT_COLUMNS])
        wallets_scored += 1

    scores = pd.concat(frames, ignore_index=True) if frames else _empty_output_frame()
    _write_scores(scores, out)

    result = {
        "pool_path": pool_path,
        "fills_dir": fills_dir,
        "funding_dir": funding_dir,
        "out": out,
        "report": report,
        "wallets_total": int(len(pool)),
        "wallets_scored": wallets_scored,
        "wallets_missing_fills": wallets_missing_fills,
        "wallets_empty_fills": wallets_empty_fills,
        "funding_tokens_loaded": sum(1 for frame in funding_cache.values() if not frame.empty),
        "written_count": int(len(scores)),
        "runtime_seconds": time.perf_counter() - started,
    }
    if report is not None:
        _write_report(report, result)
    return result


def _read_pool(path: Path) -> pd.DataFrame:
    pool = pd.read_parquet(path)
    if "wallet" not in pool.columns:
        return pd.DataFrame(columns=["wallet"])
    pool = pool.copy()
    pool["wallet"] = pool["wallet"].astype("string").str.lower()
    return pool


def _fill_tokens(fills: pd.DataFrame) -> list[str]:
    if "coin" not in fills.columns:
        return [""] * len(fills)
    return fills["coin"].astype("string").fillna("").astype(str).tolist()


def _load_funding_history(
    funding_dir: Path,
    tokens: list[str],
    cache: dict[str, pd.DataFrame],
) -> dict[str, pd.DataFrame]:
    history: dict[str, pd.DataFrame] = {}
    for token in sorted({token for token in tokens if token}):
        if token not in cache:
            path = funding_dir / f"{token}.parquet"
            cache[token] = pd.read_parquet(path) if path.exists() else pd.DataFrame()
        if not cache[token].empty:
            history[token] = cache[token]
    return history


def _components_json(components: dict[str, Any]) -> str:
    return json.dumps(components, sort_keys=True, separators=(",", ":"))


def _write_scores(scores: pd.DataFrame, out: Path) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    frame = scores.copy()[OUTPUT_COLUMNS] if not scores.empty else _empty_output_frame()
    for column in ("fill_id", "wallet", "token", "components"):
        frame[column] = frame[column].astype("string")
    frame["score"] = pd.to_numeric(frame["score"], errors="coerce").astype("float64")

    table = pa.Table.from_pandas(frame, schema=OUTPUT_SCHEMA, preserve_index=False)
    pq.write_table(table, out, compression=None, use_dictionary=False, row_group_size=256)


def _write_report(report: Path, result: dict[str, Any]) -> None:
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(
        "\n".join(
            [
                "# Phase 2.5 Slice 2 Reverse Scores",
                "",
                "## Summary",
                f"- Pool wallets: {result['wallets_total']}",
                f"- Wallets scored: {result['wallets_scored']}",
                f"- Wallets missing fills: {result['wallets_missing_fills']}",
                f"- Wallets with empty fills: {result['wallets_empty_fills']}",
                f"- Funding tokens loaded: {result['funding_tokens_loaded']}",
                f"- Written rows: {result['written_count']}",
                f"- Output: `{result['out']}`",
                f"- Runtime seconds: {result['runtime_seconds']:.2f}",
                "",
            ]
        ),
        encoding="utf-8",
    )


def _empty_output_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "fill_id": pd.Series(dtype="string"),
            "wallet": pd.Series(dtype="string"),
            "token": pd.Series(dtype="string"),
            "score": pd.Series(dtype="float64"),
            "components": pd.Series(dtype="string"),
        },
        columns=OUTPUT_COLUMNS,
    )


def _print_summary(result: dict[str, Any]) -> None:
    print("reverse alpha scoring:")
    print(f"  pool wallets: {result['wallets_total']}")
    print(f"  wallets scored: {result['wallets_scored']}")
    print(f"  wallets missing fills: {result['wallets_missing_fills']}")
    print(f"  wallets with empty fills: {result['wallets_empty_fills']}")
    print(f"  funding tokens loaded: {result['funding_tokens_loaded']}")
    print(f"  written rows: {result['written_count']}")
    print(f"  wrote: {result['out']}")
    if result["report"] is not None:
        print(f"  report: {result['report']}")
    print(f"  runtime seconds: {result['runtime_seconds']:.2f}")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Score Phase 2.5 academic wallet fills.")
    parser.add_argument("--pool", type=Path, default=DEFAULT_POOL)
    parser.add_argument("--fills-dir", type=Path, default=DEFAULT_FILLS_DIR)
    parser.add_argument("--funding-dir", type=Path, default=DEFAULT_FUNDING_DIR)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    result = run_reverse_alpha_scoring(
        pool_path=args.pool,
        fills_dir=args.fills_dir,
        funding_dir=args.funding_dir,
        out=args.out,
        report=args.report,
    )
    _print_summary(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
