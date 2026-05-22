"""Tests for Hyperliquid candle fetching."""

from datetime import datetime, timezone

import pandas as pd

from infra.fetchers.candles import fetch_candles


def _response(mocker, rows):
    response = mocker.Mock()
    response.json.return_value = rows
    response.raise_for_status = lambda: None
    return response


def _candle_row(open_time_ms: int) -> dict:
    return {
        "t": open_time_ms,
        "T": open_time_ms + 59_999,
        "s": "BTC",
        "i": "1m",
        "o": "43000.1",
        "h": "43100.2",
        "l": "42900.3",
        "c": "43050.4",
        "v": "12.5",
        "n": 25,
    }


def test_fetch_candles_returns_float_ohlcv_frame(mocker):
    mock_post = mocker.patch("infra.hyperliquid_client.requests.post")
    mock_post.return_value.json.return_value = [
        {
            "t": 1767225600000,
            "T": 1767229200000,
            "s": "BTC",
            "i": "1h",
            "o": "43000.1",
            "h": "43100.2",
            "l": "42900.3",
            "c": "43050.4",
            "v": "12.5",
            "n": 25,
        }
    ]
    mock_post.return_value.raise_for_status = lambda: None

    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    end = datetime(2026, 1, 1, 1, tzinfo=timezone.utc)
    df = fetch_candles("BTC", "1h", start, end)

    assert list(df.columns) == ["open", "high", "low", "close", "volume"]
    assert df.index.name == "timestamp"
    assert pd.Timestamp("2026-01-01T00:00:00Z") in df.index
    assert df.loc[pd.Timestamp("2026-01-01T00:00:00Z"), "open"] == 43000.1
    assert df.loc[pd.Timestamp("2026-01-01T00:00:00Z"), "volume"] == 12.5
    assert all(dtype.kind == "f" for dtype in df.dtypes)


def test_fetch_candles_posts_candle_snapshot_request(mocker):
    mock_post = mocker.patch("infra.hyperliquid_client.requests.post")
    mock_post.return_value.json.return_value = []
    mock_post.return_value.raise_for_status = lambda: None
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    end = datetime(2026, 1, 2, tzinfo=timezone.utc)

    fetch_candles("ETH", "1d", start, end)

    mock_post.assert_called_once_with(
        "https://api.hyperliquid.xyz/info",
        json={
            "type": "candleSnapshot",
            "req": {
                "coin": "ETH",
                "interval": "1d",
                "startTime": int(start.timestamp() * 1000),
                "endTime": int(end.timestamp() * 1000),
            },
        },
        timeout=20,
    )


def test_fetch_candles_accepts_string_times(mocker):
    mock_post = mocker.patch("infra.hyperliquid_client.requests.post")
    mock_post.return_value.json.return_value = []
    mock_post.return_value.raise_for_status = lambda: None

    df = fetch_candles("SOL", "5m", "2026-01-01T00:00:00Z", "2026-01-01T00:05:00Z")

    assert isinstance(df.index, pd.DatetimeIndex)
    assert df.index.name == "timestamp"
    assert list(df.columns) == ["open", "high", "low", "close", "volume"]
    assert df.empty
    assert all(dtype.kind == "f" for dtype in df.dtypes)


def test_fetch_candles_paginates_when_snapshot_hits_cap(mocker):
    mock_post = mocker.patch("infra.hyperliquid_client.requests.post")
    base_ms = int(pd.Timestamp("2026-01-01T00:00:00Z").timestamp() * 1000)
    first_chunk = [_candle_row(base_ms + i * 60_000) for i in range(5000)]
    second_chunk = [first_chunk[-1], _candle_row(base_ms + 5000 * 60_000), _candle_row(base_ms + 5001 * 60_000)]
    mock_post.side_effect = [
        _response(mocker, first_chunk),
        _response(mocker, second_chunk),
    ]

    df = fetch_candles("BTC", "1m", "2026-01-01T00:00:00Z", "2026-01-08T00:00:00Z")

    assert len(df) == 5002
    assert df.index.is_unique
    assert mock_post.call_count == 2
    assert mock_post.call_args_list[1].kwargs["json"]["req"]["startTime"] == first_chunk[-1]["T"] + 1
