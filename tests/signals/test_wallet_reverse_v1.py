from __future__ import annotations

import pandas as pd

from signals.wallet_reverse_v1 import reverse_signal


def _fills(rows: list[dict[str, object]]) -> pd.DataFrame:
    defaults = {
        "coin": "BTC",
        "side": "B",
        "dir": "Open Long",
        "px": 50_000.0,
        "sz": 0.1,
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
    frame["time"] = pd.to_datetime(frame["time"], utc=True)
    return frame.set_index("time")


def test_open_long_fill_emits_short_reverse_entry():
    fills = _fills([{"time": "2026-01-01T00:00:00Z", "dir": "Open Long"}])

    entries, exits, side = reverse_signal(fills, holding_hours=4)["BTC"]

    assert side == "short"
    assert bool(entries.loc["2026-01-01T00:00:00Z"])
    assert bool(exits.loc["2026-01-01T04:00:00Z"])
    assert entries.sum() == 1
    assert exits.sum() == 1


def test_open_short_fill_emits_long_reverse_entry():
    fills = _fills([{"time": "2026-01-01T00:00:00Z", "dir": "Open Short"}])

    entries, exits, side = reverse_signal(fills, holding_hours=4)["BTC"]

    assert side == "long"
    assert bool(entries.loc["2026-01-01T00:00:00Z"])
    assert bool(exits.loc["2026-01-01T04:00:00Z"])


def test_close_fills_are_ignored():
    fills = _fills(
        [
            {"time": "2026-01-01T00:00:00Z", "dir": "Close Long"},
            {"time": "2026-01-01T01:00:00Z", "dir": "Close Short"},
        ]
    )

    assert reverse_signal(fills, holding_hours=4) == {}


def test_fill_below_retail_size_is_ignored():
    fills = _fills([{"time": "2026-01-01T00:00:00Z", "px": 500.0, "sz": 1.0}])

    assert reverse_signal(fills, holding_hours=4) == {}


def test_fill_above_whale_size_is_ignored():
    fills = _fills([{"time": "2026-01-01T00:00:00Z", "px": 50_000.0, "sz": 5.0}])

    assert reverse_signal(fills, holding_hours=4) == {}


def test_holding_hours_controls_exit_timestamp():
    fills = _fills([{"time": "2026-01-01T02:30:00Z", "dir": "Open Short"}])

    _, exits, _ = reverse_signal(fills, holding_hours=1.5)["BTC"]

    assert bool(exits.loc["2026-01-01T04:00:00Z"])


def test_multiple_fills_same_coin_emit_multiple_pairs():
    fills = _fills(
        [
            {"time": "2026-01-01T00:00:00Z", "tid": 1, "dir": "Open Long"},
            {"time": "2026-01-01T06:00:00Z", "tid": 2, "dir": "Open Long"},
        ]
    )

    entries, exits, side = reverse_signal(fills, holding_hours=4)["BTC"]

    assert side == "short"
    assert bool(entries.loc["2026-01-01T00:00:00Z"])
    assert bool(exits.loc["2026-01-01T04:00:00Z"])
    assert bool(entries.loc["2026-01-01T06:00:00Z"])
    assert bool(exits.loc["2026-01-01T10:00:00Z"])
    assert entries.sum() == 2
    assert exits.sum() == 2


def test_coin_filter_limits_output():
    fills = _fills(
        [
            {"time": "2026-01-01T00:00:00Z", "coin": "BTC"},
            {"time": "2026-01-01T01:00:00Z", "coin": "ETH", "tid": 2},
        ]
    )

    assert set(reverse_signal(fills, holding_hours=4, coin_filter={"ETH"})) == {"ETH"}
