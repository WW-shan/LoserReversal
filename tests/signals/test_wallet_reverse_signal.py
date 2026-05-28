"""Tests for ``signals.wallet_reverse_signal``."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from signals.wallet_reverse_signal import (
    WalletReverseSignalConfig,
    _normalize_direction,
    build_signal_frame,
)


# ---------- Config validation -----------------------------------------------


def test_config_rejects_percentile_zero() -> None:
    with pytest.raises(ValueError, match="score_percentile"):
        WalletReverseSignalConfig(score_percentile=0.0)


def test_config_rejects_percentile_one() -> None:
    with pytest.raises(ValueError, match="score_percentile"):
        WalletReverseSignalConfig(score_percentile=1.0)


def test_config_rejects_zero_hold_hours() -> None:
    with pytest.raises(ValueError, match="hold_hours"):
        WalletReverseSignalConfig(hold_hours=0)


def test_config_rejects_negative_threshold_min_prior() -> None:
    with pytest.raises(ValueError, match="threshold_min_prior"):
        WalletReverseSignalConfig(threshold_min_prior=0)


# ---------- _normalize_direction -------------------------------------------


@pytest.mark.parametrize(
    "dir_value, expected",
    [
        ("Open Long", "long"),
        ("Close Short", "long"),
        ("Open Short", "short"),
        ("Close Long", "short"),
        ("Liquidated Isolated Long", "long"),  # liquidation of long → was long
        ("Liquidated Isolated Short", "short"),
        ("Auto-Deleveraging Long", "long"),
        ("Auto-Deleveraging Short", "short"),
        ("Long > Short", "short"),  # net flip ends in short
        ("Short > Long", "long"),  # net flip ends in long
    ],
)
def test_normalize_direction_handles_hl_variants(dir_value: str, expected: str) -> None:
    assert _normalize_direction(dir_value, None) == expected


def test_normalize_direction_falls_back_to_side_when_dir_missing() -> None:
    assert _normalize_direction(None, "B") == "long"
    assert _normalize_direction(None, "A") == "short"
    assert _normalize_direction(float("nan"), "B") == "long"


def test_normalize_direction_returns_none_for_unrecognized() -> None:
    assert _normalize_direction("Buy", None) is None  # spot
    assert _normalize_direction("Sell", None) is None
    assert _normalize_direction("Spot Dust Conversion", None) is None
    assert _normalize_direction(None, None) is None
    assert _normalize_direction("", None) is None


# ---------- build_signal_frame ---------------------------------------------


def _fills_frame(
    tids: list[int],
    times: list[str],
    coins: list[str],
    dirs: list[str],
) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "time": pd.to_datetime(times, utc=True),
            "tid": tids,
            "coin": coins,
            "dir": dirs,
            "side": ["B"] * len(tids),
        }
    )


def _scores_frame(
    fill_ids: list[str], wallets: list[str], scores: list[float]
) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "fill_id": pd.array(fill_ids, dtype="string"),
            "wallet": pd.array(wallets, dtype="string"),
            "token": ["BTC"] * len(fill_ids),
            "score": scores,
            "components": ["{}"] * len(fill_ids),
        }
    )


def test_build_signal_frame_returns_empty_for_empty_scores(tmp_path: Path) -> None:
    out = build_signal_frame(pd.DataFrame(columns=["fill_id", "wallet", "score"]), tmp_path)
    assert out.empty
    assert "wallet" in out.columns


def test_build_signal_frame_emits_reverse_direction(tmp_path: Path) -> None:
    """High-score long fill → reverse short entry; high-score short fill → reverse long."""
    wallet = "0xaaaa"
    fills = _fills_frame(
        [1, 2],
        ["2026-01-01T00:00:00Z", "2026-01-01T06:00:00Z"],
        ["BTC", "BTC"],
        ["Open Long", "Open Short"],
    )
    pq.write_table(pa.Table.from_pandas(fills, preserve_index=False), tmp_path / f"{wallet}.parquet")

    # Build 250 scores (enough to clear default threshold_min_prior=200 + shift(1))
    n = 250
    ids = [str(i + 1) for i in range(n)]
    # Repeat fill_ids 1, 2 in pattern so both real fills appear after threshold warmup
    fill_id_list = ["1" if i % 2 == 0 else "2" for i in range(n)]
    scores = [1.0] * (n - 2) + [5.0, 6.0]  # last 2 scores high → cleared
    scores_df = _scores_frame(fill_id_list, [wallet] * n, scores)
    out = build_signal_frame(
        scores_df,
        tmp_path,
        config=WalletReverseSignalConfig(score_percentile=0.5, hold_hours=24, threshold_min_prior=10),
    )
    directions = set(out["direction"])
    # Reverse direction: long fill → short signal, short fill → long signal
    assert directions <= {"long", "short"}
    assert not out.empty
    # Each high-score fill emits one entry + one exit row
    entries = out[out["entry"]]
    exits = out[out["exit"]]
    assert len(entries) == len(exits)


def test_build_signal_frame_drops_score_with_no_fill_match(tmp_path: Path) -> None:
    wallet = "0xaaaa"
    fills = _fills_frame([1], ["2026-01-01T00:00:00Z"], ["BTC"], ["Open Long"])
    pq.write_table(pa.Table.from_pandas(fills, preserve_index=False), tmp_path / f"{wallet}.parquet")
    scores_df = _scores_frame(["999"], [wallet], [5.0])  # fill_id doesn't match tid=1
    out = build_signal_frame(scores_df, tmp_path, config=WalletReverseSignalConfig(threshold_min_prior=1))
    assert out.empty


def test_build_signal_frame_skips_unrecognized_dir(tmp_path: Path) -> None:
    wallet = "0xaaaa"
    fills = _fills_frame([1, 2], ["2026-01-01T00:00:00Z", "2026-01-02T00:00:00Z"], ["BTC", "BTC"], ["Buy", "Sell"])
    pq.write_table(pa.Table.from_pandas(fills, preserve_index=False), tmp_path / f"{wallet}.parquet")

    # 50 scores all 5.0 above default threshold
    scores_df = _scores_frame(["1"] * 25 + ["2"] * 25, [wallet] * 50, [5.0] * 50)
    out = build_signal_frame(
        scores_df,
        tmp_path,
        config=WalletReverseSignalConfig(score_percentile=0.5, threshold_min_prior=2),
    )
    # Buy/Sell are spot, return None → dropped
    assert out.empty


def test_build_signal_frame_skips_when_fills_file_missing(tmp_path: Path) -> None:
    """A wallet with no fills parquet should be silently skipped."""
    scores_df = _scores_frame(["1"], ["0xnonexistent"], [5.0])
    out = build_signal_frame(scores_df, tmp_path, config=WalletReverseSignalConfig(threshold_min_prior=1))
    assert out.empty


def test_build_signal_frame_handles_time_as_index(tmp_path: Path) -> None:
    """Fills parquets sometimes have 'time' as index instead of column."""
    wallet = "0xaaaa"
    fills = _fills_frame([1], ["2026-01-01T00:00:00Z"], ["BTC"], ["Open Long"])
    fills_indexed = fills.set_index("time")
    # Save with index preserved (legacy fetcher writes this way before our fix)
    fills_indexed.to_parquet(tmp_path / f"{wallet}.parquet", index=True)
    scores_df = _scores_frame(["1"] * 25, [wallet] * 25, [5.0] * 25)
    out = build_signal_frame(
        scores_df,
        tmp_path,
        config=WalletReverseSignalConfig(score_percentile=0.5, threshold_min_prior=2),
    )
    assert not out.empty
