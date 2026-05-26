from __future__ import annotations

import pandas as pd

from bot_reverse.cluster_signal import BotClusterConfig, cluster_bot_signal


def _fill(
    time: str,
    *,
    coin: str = "BTC",
    direction: str = "Open Long",
) -> dict[str, object]:
    return {
        "time": pd.Timestamp(time, tz="UTC"),
        "coin": coin,
        "side": "B" if direction == "Open Long" else "A",
        "dir": direction,
        "px": 100.0,
        "sz": 1.0,
        "start_position": 0.0,
        "closed_pnl": 0.0,
        "fee": 0.0,
        "oid": 1,
        "tid": 1,
        "hash": "0x1",
        "crossed": False,
        "liquidation": False,
    }


def _fills(rows: list[dict[str, object]]) -> pd.DataFrame:
    if not rows:
        frame = pd.DataFrame(columns=list(_fill("2026-01-01T00:00:00Z").keys()))
        frame["time"] = pd.to_datetime(frame["time"], utc=True)
        return frame.set_index("time")
    frame = pd.DataFrame(rows)
    frame["time"] = pd.to_datetime(frame["time"], utc=True)
    return frame.set_index("time").sort_index()


def _prices(*coins: str) -> dict[str, pd.Series]:
    index = pd.date_range("2026-01-01T00:00:00Z", periods=49, freq="1h")
    return {coin: pd.Series(100.0, index=index, name="close") for coin in coins}


def _high_scores(*wallets: str) -> dict[str, float]:
    return {wallet: 0.9 for wallet in wallets}


def test_three_bots_open_long_within_window_creates_reverse_short_entry() -> None:
    fills_by_wallet = {
        "0x1": _fills([_fill("2026-01-01T00:00:00Z")]),
        "0x2": _fills([_fill("2026-01-01T00:10:00Z")]),
        "0x3": _fills([_fill("2026-01-01T00:20:00Z")]),
    }

    entries, exits = cluster_bot_signal(
        fills_by_wallet,
        _high_scores("0x1", "0x2", "0x3"),
        _prices("BTC"),
        config=BotClusterConfig(),
    )["BTC"]

    assert entries.loc[pd.Timestamp("2026-01-01T01:00:00Z"), "short"]
    assert not entries["long"].any()
    assert not exits.loc[pd.Timestamp("2026-01-01T01:00:00Z"), "short"]


def test_less_than_minimum_bot_count_creates_no_signal() -> None:
    fills_by_wallet = {
        "0x1": _fills([_fill("2026-01-01T00:00:00Z")]),
        "0x2": _fills([_fill("2026-01-01T00:10:00Z")]),
    }

    entries, exits = cluster_bot_signal(
        fills_by_wallet,
        _high_scores("0x1", "0x2"),
        _prices("BTC"),
        config=BotClusterConfig(),
    )["BTC"]

    assert not entries.any().any()
    assert not exits.any().any()


def test_wallet_scores_below_threshold_are_ignored() -> None:
    fills_by_wallet = {
        "0x1": _fills([_fill("2026-01-01T00:00:00Z")]),
        "0x2": _fills([_fill("2026-01-01T00:10:00Z")]),
        "0x3": _fills([_fill("2026-01-01T00:20:00Z")]),
    }

    entries, exits = cluster_bot_signal(
        fills_by_wallet,
        {"0x1": 0.9, "0x2": 0.9, "0x3": 0.69},
        _prices("BTC"),
        config=BotClusterConfig(bot_score_threshold=0.7),
    )["BTC"]

    assert not entries.any().any()
    assert not exits.any().any()


def test_window_boundary_accepts_29_minutes_and_rejects_31_minutes() -> None:
    prices = _prices("BTC")
    scores = _high_scores("0x1", "0x2", "0x3")
    within_window = {
        "0x1": _fills([_fill("2026-01-01T00:00:00Z")]),
        "0x2": _fills([_fill("2026-01-01T00:14:00Z")]),
        "0x3": _fills([_fill("2026-01-01T00:29:00Z")]),
    }
    outside_window = {
        "0x1": _fills([_fill("2026-01-01T00:00:00Z")]),
        "0x2": _fills([_fill("2026-01-01T00:15:00Z")]),
        "0x3": _fills([_fill("2026-01-01T00:31:00Z")]),
    }

    within_entries, _ = cluster_bot_signal(
        within_window,
        scores,
        prices,
        config=BotClusterConfig(window_minutes=30),
    )["BTC"]
    outside_entries, outside_exits = cluster_bot_signal(
        outside_window,
        scores,
        prices,
        config=BotClusterConfig(window_minutes=30),
    )["BTC"]

    assert within_entries["short"].any()
    assert not outside_entries.any().any()
    assert not outside_exits.any().any()


def test_hold_hours_creates_exit_after_holding_period() -> None:
    fills_by_wallet = {
        "0x1": _fills([_fill("2026-01-01T00:00:00Z")]),
        "0x2": _fills([_fill("2026-01-01T00:10:00Z")]),
        "0x3": _fills([_fill("2026-01-01T00:20:00Z")]),
    }

    entries, exits = cluster_bot_signal(
        fills_by_wallet,
        _high_scores("0x1", "0x2", "0x3"),
        _prices("BTC"),
        config=BotClusterConfig(hold_hours=2),
    )["BTC"]

    assert entries.loc[pd.Timestamp("2026-01-01T01:00:00Z"), "short"]
    assert exits.loc[pd.Timestamp("2026-01-01T03:00:00Z"), "short"]


def test_opposite_cluster_exits_active_position_before_hold_timeout() -> None:
    fills_by_wallet = {
        "0x1": _fills(
            [
                _fill("2026-01-01T00:00:00Z", direction="Open Long"),
                _fill("2026-01-01T01:00:00Z", direction="Open Short"),
            ]
        ),
        "0x2": _fills(
            [
                _fill("2026-01-01T00:10:00Z", direction="Open Long"),
                _fill("2026-01-01T01:10:00Z", direction="Open Short"),
            ]
        ),
        "0x3": _fills(
            [
                _fill("2026-01-01T00:20:00Z", direction="Open Long"),
                _fill("2026-01-01T01:20:00Z", direction="Open Short"),
            ]
        ),
    }

    entries, exits = cluster_bot_signal(
        fills_by_wallet,
        _high_scores("0x1", "0x2", "0x3"),
        _prices("BTC"),
        config=BotClusterConfig(hold_hours=24),
    )["BTC"]

    assert entries.loc[pd.Timestamp("2026-01-01T01:00:00Z"), "short"]
    assert exits.loc[pd.Timestamp("2026-01-01T02:00:00Z"), "short"]
    assert entries.loc[pd.Timestamp("2026-01-01T02:00:00Z"), "long"]


def test_empty_fills_return_empty_price_aligned_frames_without_crashing() -> None:
    entries, exits = cluster_bot_signal(
        {},
        {},
        _prices("BTC"),
        config=BotClusterConfig(),
    )["BTC"]

    assert entries.index.equals(_prices("BTC")["BTC"].index)
    assert exits.index.equals(_prices("BTC")["BTC"].index)
    assert not entries.any().any()
    assert not exits.any().any()


def test_multiple_coins_are_signaled_independently() -> None:
    fills_by_wallet = {
        "0x1": _fills(
            [
                _fill("2026-01-01T00:00:00Z", coin="BTC", direction="Open Long"),
                _fill("2026-01-01T01:00:00Z", coin="ETH", direction="Open Short"),
            ]
        ),
        "0x2": _fills(
            [
                _fill("2026-01-01T00:10:00Z", coin="BTC", direction="Open Long"),
                _fill("2026-01-01T01:10:00Z", coin="ETH", direction="Open Short"),
            ]
        ),
        "0x3": _fills(
            [
                _fill("2026-01-01T00:20:00Z", coin="BTC", direction="Open Long"),
                _fill("2026-01-01T01:20:00Z", coin="ETH", direction="Open Short"),
            ]
        ),
    }

    signals = cluster_bot_signal(
        fills_by_wallet,
        _high_scores("0x1", "0x2", "0x3"),
        _prices("BTC", "ETH"),
        config=BotClusterConfig(hold_hours=2),
    )

    btc_entries, btc_exits = signals["BTC"]
    eth_entries, eth_exits = signals["ETH"]
    assert btc_entries.loc[pd.Timestamp("2026-01-01T01:00:00Z"), "short"]
    assert btc_exits.loc[pd.Timestamp("2026-01-01T03:00:00Z"), "short"]
    assert eth_entries.loc[pd.Timestamp("2026-01-01T02:00:00Z"), "long"]
    assert eth_exits.loc[pd.Timestamp("2026-01-01T04:00:00Z"), "long"]
