"""Tests for Hyperliquid leaderboard fetching."""

import pandas as pd

from infra.fetchers.leaderboard import fetch_leaderboard


EXPECTED_COLUMNS = [
    "eth_address",
    "account_value",
    "display_name",
    "pnl_day",
    "pnl_week",
    "pnl_month",
    "pnl_alltime",
    "vlm_day",
    "vlm_week",
    "vlm_month",
    "vlm_alltime",
    "roi_day",
    "roi_week",
    "roi_month",
    "roi_alltime",
]


def _response(mocker, rows):
    response = mocker.Mock()
    response.json.return_value = {"leaderboardRows": rows}
    response.raise_for_status = lambda: None
    return response


def _leaderboard_row(address: str, alltime_pnl: str, alltime_vlm: str = "1000000"):
    return {
        "ethAddress": address,
        "accountValue": "1234.5",
        "displayName": "wallet",
        "windowPerformances": [
            ["day", {"pnl": "-1.1", "roi": "-0.01", "vlm": "100"}],
            ["week", {"pnl": "-2.2", "roi": "-0.02", "vlm": "200"}],
            ["month", {"pnl": "-3.3", "roi": "-0.03", "vlm": "300"}],
            ["allTime", {"pnl": alltime_pnl, "roi": "-0.04", "vlm": alltime_vlm}],
        ],
    }


def test_fetch_leaderboard_returns_expected_columns_and_sorts_worst_first(mocker):
    mock_get = mocker.patch("infra.fetchers.leaderboard.requests.get")
    mock_get.return_value = _response(
        mocker,
        [
            _leaderboard_row("0xBBB", "-1000"),
            _leaderboard_row("0xAAA", "-5000"),
            _leaderboard_row("0xCCC", "250"),
        ],
    )

    df = fetch_leaderboard()

    assert list(df.columns) == EXPECTED_COLUMNS
    assert df["eth_address"].tolist() == ["0xaaa", "0xbbb", "0xccc"]
    assert df["pnl_alltime"].tolist() == [-5000.0, -1000.0, 250.0]


def test_fetch_leaderboard_coerces_numeric_strings_to_float64(mocker):
    mock_get = mocker.patch("infra.fetchers.leaderboard.requests.get")
    mock_get.return_value = _response(mocker, [_leaderboard_row("0xAAA", "-5000.25")])

    df = fetch_leaderboard()

    numeric_columns = [column for column in EXPECTED_COLUMNS if column != "eth_address"]
    numeric_columns.remove("display_name")
    assert all(df[column].dtype == "float64" for column in numeric_columns)
    assert df.loc[0, "account_value"] == 1234.5
    assert df.loc[0, "pnl_alltime"] == -5000.25


def test_fetch_leaderboard_handles_non_finite_numeric_strings(mocker):
    mock_get = mocker.patch("infra.fetchers.leaderboard.requests.get")
    mock_get.return_value = _response(
        mocker,
        [
            {
                "ethAddress": "0xAAA",
                "accountValue": "NaN",
                "displayName": None,
                "windowPerformances": [
                    ["day", {"pnl": "Infinity", "roi": "-Infinity", "vlm": "bad"}],
                    ["week", {"pnl": "-2.2", "roi": "-0.02", "vlm": "200"}],
                    ["month", {"pnl": "-3.3", "roi": "-0.03", "vlm": "300"}],
                    ["allTime", {"pnl": "-5000", "roi": "NaN", "vlm": "1000000"}],
                ],
            }
        ],
    )

    df = fetch_leaderboard()

    assert pd.isna(df.loc[0, "account_value"])
    assert pd.isna(df.loc[0, "pnl_day"])
    assert pd.isna(df.loc[0, "roi_day"])
    assert pd.isna(df.loc[0, "vlm_day"])
    assert pd.isna(df.loc[0, "roi_alltime"])


def test_fetch_leaderboard_empty_response_returns_empty_frame(mocker):
    mock_get = mocker.patch("infra.fetchers.leaderboard.requests.get")
    mock_get.return_value = _response(mocker, [])

    df = fetch_leaderboard()

    assert list(df.columns) == EXPECTED_COLUMNS
    assert df.empty
    assert df.index.name is None
