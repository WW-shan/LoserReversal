"""Tests for Hyperliquid user fills fetching."""

from datetime import datetime, timezone

import pandas as pd
import pytest

from infra.fetchers.user_fills import fetch_user_fills


class FakeClient:
    def __init__(self, chunks):
        self.chunks = list(chunks)
        self.calls = []

    def _post_info(self, payload):
        self.calls.append(payload)
        if not self.chunks:
            return []
        return self.chunks.pop(0)


def _fill(time_ms: int, tid: int, liquidation=None) -> dict:
    return {
        "coin": "BTC",
        "px": "43000.5",
        "sz": "0.1",
        "side": "B",
        "time": time_ms,
        "startPosition": "0.0",
        "dir": "Open Long",
        "closedPnl": "-12.34",
        "hash": f"0x{tid:x}",
        "oid": 1000 + tid,
        "crossed": False,
        "fee": "0.12",
        "tid": tid,
        "liquidation": liquidation,
        "feeToken": "USDC",
        "twapId": None,
    }


def test_fetch_user_fills_single_page_returns_all_rows_without_extra_call():
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    end = datetime(2026, 1, 2, tzinfo=timezone.utc)
    client = FakeClient([[_fill(1767225600000, 1), _fill(1767225660000, 2)]])

    df = fetch_user_fills("0xABC", start, end, client=client)

    assert len(df) == 2
    assert len(client.calls) == 1
    assert client.calls[0] == {
        "type": "userFillsByTime",
        "user": "0xabc",
        "startTime": int(start.timestamp() * 1000),
        "endTime": int(end.timestamp() * 1000),
    }


def test_fetch_user_fills_paginates_when_response_hits_cap():
    base_ms = 1767225600000
    first = [_fill(base_ms + index, index) for index in range(2000)]
    second = [_fill(base_ms + 2000 + index, 2000 + index) for index in range(500)]
    client = FakeClient([first, second, []])

    df = fetch_user_fills("0xabc", base_ms, base_ms + 10_000, client=client)

    assert len(df) == 2500
    assert len(client.calls) == 2
    assert client.calls[1]["startTime"] == first[-1]["time"]


def test_fetch_user_fills_handles_repeated_final_timestamp_across_pages():
    base_ms = 1767225600000
    t1 = base_ms + 3000
    t2 = t1 + 1
    first = [_fill(base_ms + index, 1000 + index) for index in range(1995)]
    first.extend(_fill(t1, tid) for tid in range(1, 6))
    second = [_fill(t1, tid) for tid in range(3, 9)]
    second.append(_fill(t2, 9))
    client = FakeClient([first, second])

    df = fetch_user_fills("0xabc", base_ms, base_ms + 10_000, client=client)

    assert len(df) == 2004
    assert client.calls[1]["startTime"] == t1
    assert df["tid"].is_unique
    assert set(df.loc[pd.Timestamp(t1, unit="ms", tz="UTC"), "tid"]) == set(range(1, 9))


def test_fetch_user_fills_deduplicates_by_tid_across_pages():
    base_ms = 1767225600000
    first = [_fill(base_ms + index, index) for index in range(2000)]
    second = [_fill(base_ms + 2000, 1999), _fill(base_ms + 2001, 2000)]
    client = FakeClient([first, second])

    df = fetch_user_fills("0xabc", base_ms, base_ms + 10_000, client=client)

    assert len(df) == 2001
    assert df["tid"].is_unique


def test_fetch_user_fills_normalizes_address_in_request():
    client = FakeClient([[]])

    fetch_user_fills("0xAbCdEf", 1767225600000, 1767229200000, client=client)

    assert client.calls[0]["user"] == "0xabcdef"


def test_fetch_user_fills_marks_liquidation_when_field_is_present():
    client = FakeClient(
        [
            [
                _fill(1767225600000, 1, liquidation={"liquidatedUser": "0xaaa"}),
                _fill(1767225660000, 2, liquidation=None),
            ]
        ]
    )

    df = fetch_user_fills("0xabc", 1767225600000, 1767229200000, client=client)

    assert df["liquidation"].tolist() == [True, False]


def test_fetch_user_fills_warns_when_pagination_hard_cap_is_hit(mocker):
    mocker.patch("infra.fetchers.user_fills.MAX_PAGES", 2)
    base_ms = 1767225600000
    first = [_fill(base_ms + index, index) for index in range(2000)]
    second = [_fill(base_ms + 2000 + index, 2000 + index) for index in range(2000)]
    client = FakeClient([first, second])

    with pytest.warns(RuntimeWarning, match="pagination hard cap"):
        df = fetch_user_fills("0xabc", base_ms, base_ms + 100_000, client=client)

    assert len(df) == 4000


def test_fetch_user_fills_warns_when_cap_page_has_one_timestamp():
    base_ms = 1767225600000
    client = FakeClient([[_fill(base_ms, index) for index in range(2000)]])

    with pytest.warns(RuntimeWarning, match="single millisecond"):
        df = fetch_user_fills("0xabc", base_ms, base_ms + 10_000, client=client)

    assert len(df) == 2000
    assert len(client.calls) == 2
    assert client.calls[1]["startTime"] == base_ms + 1


def test_fetch_user_fills_rejects_unix_seconds_ints():
    client = FakeClient([[]])

    with pytest.raises(ValueError, match="unix milliseconds"):
        fetch_user_fills("0xabc", 1767225600, 1767229200, client=client)


def test_fetch_user_fills_uses_utc_tz_aware_time_index():
    client = FakeClient([[_fill(1767225600000, 1)]])

    df = fetch_user_fills("0xabc", 1767225600000, 1767229200000, client=client)

    assert df.index.name == "time"
    assert isinstance(df.index, pd.DatetimeIndex)
    assert df.index.tz is not None
    assert df.index[0] == pd.Timestamp("2026-01-01T00:00:00Z")


def test_fetch_user_fills_parses_closed_pnl_and_fee_as_float64():
    client = FakeClient([[_fill(1767225600000, 1)]])

    df = fetch_user_fills("0xabc", 1767225600000, 1767229200000, client=client)

    assert df["closed_pnl"].dtype == "float64"
    assert df["fee"].dtype == "float64"
    assert df.loc[pd.Timestamp("2026-01-01T00:00:00Z"), "closed_pnl"] == -12.34
    assert df.loc[pd.Timestamp("2026-01-01T00:00:00Z"), "fee"] == 0.12
