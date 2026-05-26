"""Run the Phase 4 bot reverse signal generator."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from bot_reverse.cluster_signal import BotClusterConfig, cluster_bot_signal


DEFAULT_BOT_POOL = Path("data/parquet/bot_wallets.parquet")
DEFAULT_FILLS_DIR = Path("data/parquet/fills")
DEFAULT_CANDLES_DIR = Path("data/parquet/candles")
DEFAULT_OUT = Path("data/parquet/bot_reverse_signal.parquet")
OUTPUT_COLUMNS = ["timestamp", "coin", "direction", "entry", "exit"]


@dataclass(frozen=True)
class BotReverseSignalConfig:
    bot_pool: Path = DEFAULT_BOT_POOL
    fills_dir: Path = DEFAULT_FILLS_DIR
    candles_dir: Path = DEFAULT_CANDLES_DIR
    out: Path = DEFAULT_OUT


def run_bot_reverse_signal(config: BotReverseSignalConfig) -> dict[str, Any]:
    bot_scores = load_bot_scores(config.bot_pool)
    fills_by_wallet = load_fills_by_wallet(config.fills_dir, bot_scores.keys())
    prices = load_prices(config.candles_dir)
    signals = cluster_bot_signal(
        fills_by_wallet,
        bot_scores,
        prices,
        config=BotClusterConfig(),
    )
    frame = signals_to_frame(signals)
    write_signal_frame(frame, config.out)
    return {
        "out": config.out,
        "bot_wallets": len(bot_scores),
        "fills_loaded": len(fills_by_wallet),
        "price_tokens": len(prices),
        "signal_rows": int(len(frame)),
        "entry_rows": int(frame["entry"].sum()) if not frame.empty else 0,
        "exit_rows": int(frame["exit"].sum()) if not frame.empty else 0,
    }


def load_bot_scores(path: Path) -> dict[str, float]:
    frame = pd.read_parquet(path)
    if frame.empty:
        return {}
    wallet_column = "wallet" if "wallet" in frame.columns else "eth_address"
    scores: dict[str, float] = {}
    for row in frame.itertuples(index=False):
        wallet = str(getattr(row, wallet_column, "") or "").lower()
        if not wallet:
            continue
        scores[wallet] = float(getattr(row, "bot_score", 0.0) or 0.0)
    return scores


def load_fills_by_wallet(fills_dir: Path, wallets: Any) -> dict[str, pd.DataFrame]:
    fills_by_wallet: dict[str, pd.DataFrame] = {}
    for wallet in sorted({str(wallet).lower() for wallet in wallets}):
        path = fills_dir / f"{wallet}.parquet"
        if not path.exists():
            continue
        frame = pd.read_parquet(path)
        if "time" in frame.columns:
            frame["time"] = pd.to_datetime(frame["time"], utc=True, errors="coerce")
        fills_by_wallet[wallet] = frame
    return fills_by_wallet


def load_prices(candles_dir: Path) -> dict[str, pd.Series]:
    prices: dict[str, pd.Series] = {}
    for path in sorted(candles_dir.glob("*.parquet")):
        coin = _coin_from_candle_path(path)
        close = _read_close(path)
        if close is None or close.empty:
            continue
        prices.setdefault(coin, close)
    return prices


def signals_to_frame(signals: dict[str, tuple[pd.DataFrame, pd.DataFrame]]) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for coin in sorted(signals):
        entries, exits = signals[coin]
        for timestamp in entries.index:
            for direction in ("long", "short"):
                has_entry = bool(entries.at[timestamp, direction])
                has_exit = bool(exits.at[timestamp, direction])
                if not has_entry and not has_exit:
                    continue
                rows.append(
                    {
                        "timestamp": pd.Timestamp(timestamp),
                        "coin": coin,
                        "direction": direction,
                        "entry": has_entry,
                        "exit": has_exit,
                    }
                )
    if not rows:
        return _empty_output_frame()
    frame = pd.DataFrame(rows, columns=OUTPUT_COLUMNS)
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True)
    frame["coin"] = frame["coin"].astype("string")
    frame["direction"] = frame["direction"].astype("string")
    frame["entry"] = frame["entry"].astype("bool")
    frame["exit"] = frame["exit"].astype("bool")
    return frame.sort_values(["coin", "timestamp", "direction"]).reset_index(drop=True)


def write_signal_frame(frame: pd.DataFrame, out: Path) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(out, index=False)


def _read_close(path: Path) -> pd.Series | None:
    frame = pd.read_parquet(path)
    if frame.empty or "close" not in frame.columns:
        return None
    if "timestamp" in frame.columns:
        index = pd.to_datetime(frame["timestamp"], utc=True, errors="coerce")
    elif "time" in frame.columns:
        index = pd.to_datetime(frame["time"], utc=True, errors="coerce")
    else:
        index = pd.to_datetime(frame.index, utc=True, errors="coerce")
    close = pd.to_numeric(frame["close"], errors="coerce")
    series = pd.Series(close.to_numpy(), index=pd.DatetimeIndex(index), name="close")
    series = series.dropna().sort_index()
    return series.astype("float64")


def _coin_from_candle_path(path: Path) -> str:
    stem = path.stem
    if "_" not in stem:
        return stem
    coin, suffix = stem.rsplit("_", 1)
    if suffix in {"1m", "5m", "15m", "1h", "4h", "1d"}:
        return coin
    return stem


def _empty_output_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "timestamp": pd.Series(dtype="datetime64[ns, UTC]"),
            "coin": pd.Series(dtype="string"),
            "direction": pd.Series(dtype="string"),
            "entry": pd.Series(dtype="bool"),
            "exit": pd.Series(dtype="bool"),
        },
        columns=OUTPUT_COLUMNS,
    )


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the Phase 4 bot reverse signal.")
    parser.add_argument("--bot-pool", type=Path, default=DEFAULT_BOT_POOL)
    parser.add_argument("--fills-dir", type=Path, default=DEFAULT_FILLS_DIR)
    parser.add_argument("--candles-dir", type=Path, default=DEFAULT_CANDLES_DIR)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    return parser.parse_args()


def _print_summary(result: dict[str, Any]) -> None:
    print("bot reverse signal:")
    print(f"  bot wallets: {result['bot_wallets']}")
    print(f"  fills loaded: {result['fills_loaded']}")
    print(f"  price tokens: {result['price_tokens']}")
    print(f"  signal rows: {result['signal_rows']}")
    print(f"  entries: {result['entry_rows']}")
    print(f"  exits: {result['exit_rows']}")
    print(f"  wrote: {result['out']}")


def main() -> int:
    args = _parse_args()
    result = run_bot_reverse_signal(
        BotReverseSignalConfig(
            bot_pool=args.bot_pool,
            fills_dir=args.fills_dir,
            candles_dir=args.candles_dir,
            out=args.out,
        )
    )
    _print_summary(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
