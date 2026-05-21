"""Tests for Hyperliquid funding fetching."""

from datetime import datetime, timezone

import pandas as pd

from infra.fetchers.funding import fetch_funding


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
