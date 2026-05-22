"""Tests for Hyperliquid funding fetching."""

from datetime import datetime, timezone

import pandas as pd

from infra.fetchers.funding import fetch_funding


def _response(mocker, rows):
    response = mocker.Mock()
    response.json.return_value = rows
    response.raise_for_status = lambda: None
    return response


def _funding_row(time_ms: int) -> dict:
    return {
        "coin": "BTC",
        "fundingRate": "0.0001",
        "premium": "0.0002",
        "time": time_ms,
    }


def test_fetch_funding_returns_rate_and_premium_frame(mocker):
    mock_post = mocker.patch("infra.hyperliquid_client.requests.post")
    mock_post.return_value.json.return_value = [
        {
            "coin": "BTC",
            "fundingRate": "0.0001",
            "premium": "0.0002",
            "time": 1767225600000,
        }
    ]
    mock_post.return_value.raise_for_status = lambda: None

    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    end = datetime(2026, 1, 1, 1, tzinfo=timezone.utc)
    df = fetch_funding("BTC", start, end)

    assert list(df.columns) == ["funding_rate", "premium"]
    assert df.index.name == "timestamp"
    assert pd.Timestamp("2026-01-01T00:00:00Z") in df.index
    assert df.loc[pd.Timestamp("2026-01-01T00:00:00Z"), "funding_rate"] == 0.0001
    assert df.loc[pd.Timestamp("2026-01-01T00:00:00Z"), "premium"] == 0.0002
    assert all(dtype.kind == "f" for dtype in df.dtypes)


def test_fetch_funding_posts_funding_history_request(mocker):
    mock_post = mocker.patch("infra.hyperliquid_client.requests.post")
    mock_post.return_value.json.return_value = []
    mock_post.return_value.raise_for_status = lambda: None
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    end = datetime(2026, 1, 2, tzinfo=timezone.utc)

    fetch_funding("ETH", start, end)

    mock_post.assert_called_once_with(
        "https://api.hyperliquid.xyz/info",
        json={
            "type": "fundingHistory",
            "coin": "ETH",
            "startTime": int(start.timestamp() * 1000),
            "endTime": int(end.timestamp() * 1000),
        },
        timeout=20,
    )


def test_fetch_funding_accepts_string_times(mocker):
    mock_post = mocker.patch("infra.hyperliquid_client.requests.post")
    mock_post.return_value.json.return_value = []
    mock_post.return_value.raise_for_status = lambda: None

    df = fetch_funding("SOL", "2026-01-01T00:00:00Z", "2026-01-01T01:00:00Z")

    assert isinstance(df.index, pd.DatetimeIndex)
    assert df.index.name == "timestamp"
    assert list(df.columns) == ["funding_rate", "premium"]
    assert df.empty
    assert all(dtype.kind == "f" for dtype in df.dtypes)


def test_fetch_funding_paginates_when_history_hits_cap(mocker):
    mock_post = mocker.patch("infra.hyperliquid_client.requests.post")
    base_ms = int(pd.Timestamp("2026-01-01T00:00:00Z").timestamp() * 1000)
    first_chunk = [_funding_row(base_ms + i * 3_600_000) for i in range(500)]
    second_chunk = [
        first_chunk[-1],
        _funding_row(base_ms + 500 * 3_600_000),
        _funding_row(base_ms + 501 * 3_600_000),
    ]
    mock_post.side_effect = [
        _response(mocker, first_chunk),
        _response(mocker, second_chunk),
    ]

    df = fetch_funding("BTC", "2026-01-01T00:00:00Z", "2026-02-01T00:00:00Z")

    assert len(df) == 502
    assert df.index.is_unique
    assert mock_post.call_count == 2
    assert mock_post.call_args_list[1].kwargs["json"]["startTime"] == first_chunk[-1]["time"] + 1
