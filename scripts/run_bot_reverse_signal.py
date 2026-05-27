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
CANDLE_TIMEFRAMES = frozenset(
    {"1m", "5m", "15m", "30m", "1h", "2h", "4h", "8h", "12h", "1d", "1w"}
)
DEFAULT_CLUSTER_CONFIG = BotClusterConfig()


@dataclass(frozen=True)
class BotReverseSignalConfig:
    bot_pool: Path = DEFAULT_BOT_POOL
    fills_dir: Path = DEFAULT_FILLS_DIR
    candles_dir: Path = DEFAULT_CANDLES_DIR
    out: Path = DEFAULT_OUT
    n_bots_min: int = DEFAULT_CLUSTER_CONFIG.n_bots_min
    window_minutes: int = DEFAULT_CLUSTER_CONFIG.window_minutes
    bot_score_threshold: float = DEFAULT_CLUSTER_CONFIG.bot_score_threshold
    hold_hours: int = DEFAULT_CLUSTER_CONFIG.hold_hours


def run_bot_reverse_signal(config: BotReverseSignalConfig) -> dict[str, Any]:
    bot_scores = load_bot_scores(config.bot_pool)
    fills_by_wallet, missing_wallets = load_fills_by_wallet(config.fills_dir, bot_scores.keys())
    prices = load_prices(config.candles_dir)
    signals = cluster_bot_signal(
        fills_by_wallet,
        bot_scores,
        prices,
        config=BotClusterConfig(
            n_bots_min=config.n_bots_min,
            window_minutes=config.window_minutes,
            bot_score_threshold=config.bot_score_threshold,
            hold_hours=config.hold_hours,
        ),
    )
    frame = signals_to_frame(signals)
    write_signal_frame(frame, config.out)
    return {
        "out": config.out,
        "bot_wallets": len(bot_scores),
        "fills_loaded": len(fills_by_wallet),
        "fills_missing": len(missing_wallets),
        "fills_missing_sample": missing_wallets[:5],
        "price_tokens": len(prices),
        "signal_rows": int(len(frame)),
        "entry_rows": int(frame["entry"].sum()) if not frame.empty else 0,
        "exit_rows": int(frame["exit"].sum()) if not frame.empty else 0,
    }


def load_bot_scores(path: Path) -> dict[str, float]:
    frame = pd.read_parquet(path)
    if frame.empty:
        return {}
    if "wallet" in frame.columns:
        wallet_column = "wallet"
    elif "eth_address" in frame.columns:
        wallet_column = "eth_address"
    else:
        raise KeyError("bot pool parquet must contain a wallet or eth_address column")
    if "bot_score" not in frame.columns:
        raise KeyError("bot pool parquet must contain a bot_score column")
    frame = frame[[wallet_column, "bot_score"]].copy()
    frame["bot_score"] = pd.to_numeric(frame["bot_score"], errors="coerce")
    frame[wallet_column] = frame[wallet_column].astype("string").str.lower()
    frame = frame.dropna(subset=[wallet_column, "bot_score"])
    return dict(zip(frame[wallet_column].astype(str), frame["bot_score"].astype(float), strict=True))


def load_fills_by_wallet(fills_dir: Path, wallets: Any) -> tuple[dict[str, pd.DataFrame], list[str]]:
    fills_by_wallet: dict[str, pd.DataFrame] = {}
    missing_wallets: list[str] = []
    for wallet in sorted({str(wallet).lower() for wallet in wallets}):
        path = fills_dir / f"{wallet}.parquet"
        if not path.exists():
            missing_wallets.append(wallet)
            continue
        frame = pd.read_parquet(path)
        if "time" in frame.columns:
            frame["time"] = pd.to_datetime(frame["time"], utc=True, errors="coerce")
        fills_by_wallet[wallet] = frame
    return fills_by_wallet, missing_wallets


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
    frames: list[pd.DataFrame] = []
    field_map = pd.DataFrame(
        [
            {"field": "entry_long", "direction": "long", "kind": "entry"},
            {"field": "entry_short", "direction": "short", "kind": "entry"},
            {"field": "exit_long", "direction": "long", "kind": "exit"},
            {"field": "exit_short", "direction": "short", "kind": "exit"},
        ]
    )
    for coin in sorted(signals):
        entries, exits = signals[coin]
        entry_long = entries["long"].rename("entry_long")
        entry_short = entries["short"].rename("entry_short")
        exit_long = exits["long"].rename("exit_long")
        exit_short = exits["short"].rename("exit_short")
        combined = pd.concat([entry_long, entry_short, exit_long, exit_short], axis=1)
        if combined.empty:
            continue
        combined["coin"] = coin
        melted = combined.rename_axis("timestamp").reset_index().melt(
            id_vars=["timestamp", "coin"],
            value_vars=["entry_long", "entry_short", "exit_long", "exit_short"],
            var_name="field",
            value_name="value",
        )
        melted = melted.merge(field_map, on="field", how="inner")
        frame = (
            melted.pivot(
                index=["timestamp", "coin", "direction"],
                columns="kind",
                values="value",
            )
            .reset_index()
            .rename_axis(columns=None)
        )
        frame["entry"] = frame["entry"].fillna(False).astype(bool)
        frame["exit"] = frame["exit"].fillna(False).astype(bool)
        frame = frame.loc[frame["entry"] | frame["exit"], OUTPUT_COLUMNS]
        if not frame.empty:
            frames.append(frame)
    if not frames:
        return _empty_output_frame()
    frame = pd.concat(frames, ignore_index=True)
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
        raise ValueError(f"candle parquet stem must use '{{coin}}_{{tf}}' format; got {stem!r}")
    coin, suffix = stem.rsplit("_", 1)
    if suffix not in CANDLE_TIMEFRAMES:
        raise ValueError(
            f"unknown timeframe suffix {suffix!r} in {path.name}; "
            f"expected one of {sorted(CANDLE_TIMEFRAMES)}"
        )
    return coin


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
    parser.add_argument("--n-bots-min", type=int, default=DEFAULT_CLUSTER_CONFIG.n_bots_min)
    parser.add_argument("--window-minutes", type=int, default=DEFAULT_CLUSTER_CONFIG.window_minutes)
    parser.add_argument(
        "--bot-score-threshold",
        type=float,
        default=DEFAULT_CLUSTER_CONFIG.bot_score_threshold,
    )
    parser.add_argument("--hold-hours", type=int, default=DEFAULT_CLUSTER_CONFIG.hold_hours)
    return parser.parse_args()


def _print_summary(result: dict[str, Any]) -> None:
    print("bot reverse signal:")
    print(f"  bot wallets: {result['bot_wallets']}")
    print(f"  fills loaded: {result['fills_loaded']}")
    print(f"  fills missing: {result['fills_missing']}")
    print(f"  price tokens: {result['price_tokens']}")
    print(f"  signal rows: {result['signal_rows']}")
    if result["signal_rows"] == 0:
        print("  (no clusters detected)")
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
            n_bots_min=args.n_bots_min,
            window_minutes=args.window_minutes,
            bot_score_threshold=args.bot_score_threshold,
            hold_hours=args.hold_hours,
        )
    )
    _print_summary(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
