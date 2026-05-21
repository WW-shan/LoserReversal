"""Tests for the Hyperliquid info API client."""

from infra.hyperliquid_client import HyperliquidClient


def test_universe_returns_ticker_list(mocker):
    mock_post = mocker.patch("infra.hyperliquid_client.requests.post")
    mock_post.return_value.status_code = 200
    mock_post.return_value.json.return_value = {
        "universe": [{"name": "BTC"}, {"name": "ETH"}]
    }
    mock_post.return_value.raise_for_status = lambda: None

    client = HyperliquidClient()

    assert client.universe() == ["BTC", "ETH"]


def test_universe_posts_meta_request_to_info_endpoint(mocker):
    mock_post = mocker.patch("infra.hyperliquid_client.requests.post")
    mock_post.return_value.json.return_value = {"universe": []}
    mock_post.return_value.raise_for_status = lambda: None
    client = HyperliquidClient(base_url="https://example.com/")

    client.universe()

    mock_post.assert_called_once_with(
        "https://example.com/info",
        json={"type": "meta"},
        timeout=20,
    )


def test_universe_with_volumes_returns_ticker_to_24h_notional_volume(mocker):
    mock_post = mocker.patch("infra.hyperliquid_client.requests.post")
    mock_post.return_value.json.return_value = [
        {"universe": [{"name": "BTC"}, {"name": "ETH"}]},
        [{"dayNtlVlm": "1250000.5"}, {"dayNtlVlm": "250000.25"}],
    ]
    mock_post.return_value.raise_for_status = lambda: None

    client = HyperliquidClient()

    assert client.universe_with_volumes() == {"BTC": 1250000.5, "ETH": 250000.25}
    mock_post.assert_called_once_with(
        "https://api.hyperliquid.xyz/info",
        json={"type": "metaAndAssetCtxs"},
        timeout=20,
    )
