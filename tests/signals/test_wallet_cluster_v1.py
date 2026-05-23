from __future__ import annotations

import pandas as pd

from signals.wallet_cluster_v1 import cluster_signal


def _pool(rows: list[dict[str, object]]) -> dict[str, pd.DataFrame]:
    by_wallet: dict[str, list[dict[str, object]]] = {}
    for row in rows:
        wallet = str(row["wallet"])
        by_wallet.setdefault(wallet, []).append(row)

    return {wallet: _fills(wallet_rows) for wallet, wallet_rows in by_wallet.items()}


def _fills(rows: list[dict[str, object]]) -> pd.DataFrame:
    defaults = {
        "coin": "BTC",
        "side": "B",
        "dir": "Open Long",
        "px": 100.0,
        "sz": 20.0,
        "start_position": 0.0,
        "closed_pnl": 0.0,
        "fee": 1.0,
        "oid": 1,
        "tid": 1,
        "hash": "0x1",
        "crossed": False,
        "liquidation": False,
    }
    frame = pd.DataFrame([{**defaults, **row} for row in rows])
    frame["time"] = pd.to_datetime(frame.pop("time"), utc=True)
    frame = frame.drop(columns=["wallet"])
    return frame.set_index("time")


def test_three_wallets_opening_long_within_window_emits_reverse_short_cluster():
    events = cluster_signal(
        _pool(
            [
                {"wallet": "0x1", "time": "2026-01-01T00:00:00Z"},
                {"wallet": "0x2", "time": "2026-01-01T00:10:00Z"},
                {"wallet": "0x3", "time": "2026-01-01T00:29:00Z"},
            ]
        ),
        min_wallets=3,
        window_minutes=30,
        holding_hours=4,
    )

    btc = events["BTC"]
    assert len(btc) == 1
    assert btc.iloc[0].to_dict() == {
        "entry_time": pd.Timestamp("2026-01-01T00:29:00Z"),
        "exit_time": pd.Timestamp("2026-01-01T04:29:00Z"),
        "side": "short",
        "cluster_size": 3,
        "confidence_score": 1.0,
    }


def test_two_wallets_only_do_not_emit_cluster():
    events = cluster_signal(
        _pool(
            [
                {"wallet": "0x1", "time": "2026-01-01T00:00:00Z"},
                {"wallet": "0x2", "time": "2026-01-01T00:10:00Z"},
            ]
        ),
        min_wallets=3,
        window_minutes=30,
    )

    assert events == {}


def test_mixed_long_short_openings_form_independent_direction_clusters():
    events = cluster_signal(
        _pool(
            [
                {"wallet": "0x1", "time": "2026-01-01T00:00:00Z", "dir": "Open Long"},
                {"wallet": "0x2", "time": "2026-01-01T00:01:00Z", "dir": "Open Long"},
                {"wallet": "0x3", "time": "2026-01-01T00:02:00Z", "dir": "Open Long"},
                {"wallet": "0x4", "time": "2026-01-01T00:00:00Z", "dir": "Open Short"},
                {"wallet": "0x5", "time": "2026-01-01T00:01:00Z", "dir": "Open Short"},
                {"wallet": "0x6", "time": "2026-01-01T00:02:00Z", "dir": "Open Short"},
            ]
        ),
        min_wallets=3,
        window_minutes=30,
    )

    btc = events["BTC"].sort_values("side").reset_index(drop=True)
    assert list(btc["side"]) == ["long", "short"]
    assert list(btc["cluster_size"]) == [3, 3]


def test_same_wallet_opening_same_direction_multiple_times_counts_once():
    events = cluster_signal(
        _pool(
            [
                {"wallet": "0x1", "time": "2026-01-01T00:00:00Z", "tid": 1},
                {"wallet": "0x1", "time": "2026-01-01T00:05:00Z", "tid": 2},
                {"wallet": "0x2", "time": "2026-01-01T00:06:00Z", "tid": 3},
                {"wallet": "0x3", "time": "2026-01-01T00:07:00Z", "tid": 4},
            ]
        ),
        min_wallets=3,
        window_minutes=30,
    )

    btc = events["BTC"]
    assert len(btc) == 1
    assert btc.iloc[0]["entry_time"] == pd.Timestamp("2026-01-01T00:07:00Z")
    assert btc.iloc[0]["cluster_size"] == 3


def test_cluster_cooldown_suppresses_overlapping_same_coin_clusters():
    events = cluster_signal(
        _pool(
            [
                {"wallet": "0x1", "time": "2026-01-01T00:00:00Z"},
                {"wallet": "0x2", "time": "2026-01-01T00:10:00Z"},
                {"wallet": "0x3", "time": "2026-01-01T00:20:00Z"},
                {"wallet": "0x4", "time": "2026-01-01T01:00:00Z"},
                {"wallet": "0x5", "time": "2026-01-01T01:10:00Z"},
                {"wallet": "0x6", "time": "2026-01-01T01:20:00Z"},
            ]
        ),
        min_wallets=3,
        window_minutes=30,
        holding_hours=4,
    )

    assert len(events["BTC"]) == 1
    assert events["BTC"].iloc[0]["entry_time"] == pd.Timestamp("2026-01-01T00:20:00Z")


def test_window_boundary_is_inclusive_at_exact_window_minutes():
    events = cluster_signal(
        _pool(
            [
                {"wallet": "0x1", "time": "2026-01-01T00:00:00Z"},
                {"wallet": "0x2", "time": "2026-01-01T00:15:00Z"},
                {"wallet": "0x3", "time": "2026-01-01T00:30:00Z"},
            ]
        ),
        min_wallets=3,
        window_minutes=30,
    )

    assert len(events["BTC"]) == 1
    assert events["BTC"].iloc[0]["entry_time"] == pd.Timestamp("2026-01-01T00:30:00Z")
