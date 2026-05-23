from __future__ import annotations

import pandas as pd
import pytest

from scripts import build_wallet_pool as builder


def _wallet(
    address: str,
    *,
    pnl_alltime: float,
    vlm_alltime: float,
    roi_alltime: float,
    account_value: float = 1_000.0,
) -> dict[str, object]:
    return {
        "eth_address": address,
        "account_value": account_value,
        "pnl_alltime": pnl_alltime,
        "vlm_alltime": vlm_alltime,
        "roi_alltime": roi_alltime,
        "display_name": address,
        "pnl_month": 0.0,
        "vlm_month": 0.0,
    }


def test_build_wallet_pool_excludes_whales_and_high_roi_wallets(mocker, tmp_path):
    leaderboard = pd.DataFrame(
        [
            _wallet("0xretail", pnl_alltime=-50_000.0, vlm_alltime=500_000.0, roi_alltime=-0.10),
            _wallet(
                "0xwhale",
                pnl_alltime=-300_000.0,
                vlm_alltime=30_000_000_000.0,
                roi_alltime=-0.000001,
            ),
            _wallet("0xhighroi", pnl_alltime=-100_000.0, vlm_alltime=2_000_000.0, roi_alltime=-0.02),
        ]
    )
    mocker.patch.object(builder, "fetch_leaderboard", return_value=leaderboard)

    result = builder.build_wallet_pool(out=tmp_path / "wallets.parquet")

    pool = pd.read_parquet(result["path"])
    assert result["written_count"] == 1
    assert pool["eth_address"].tolist() == ["0xretail"]


def test_build_wallet_pool_sorts_by_alltime_volume_desc(mocker, tmp_path):
    leaderboard = pd.DataFrame(
        [
            _wallet("0xmid", pnl_alltime=-100_000.0, vlm_alltime=2_000_000.0, roi_alltime=-0.10),
            _wallet("0xlow", pnl_alltime=-100_000.0, vlm_alltime=1_000_000.0, roi_alltime=-0.10),
            _wallet("0xhigh", pnl_alltime=-100_000.0, vlm_alltime=3_000_000.0, roi_alltime=-0.10),
        ]
    )
    mocker.patch.object(builder, "fetch_leaderboard", return_value=leaderboard)

    result = builder.build_wallet_pool(out=tmp_path / "wallets.parquet")

    pool = pd.read_parquet(result["path"])
    assert pool["eth_address"].tolist() == ["0xhigh", "0xmid", "0xlow"]


def test_build_wallet_pool_rejects_positive_max_roi_cli_arg(mocker, capsys):
    mocker.patch("sys.argv", ["build_wallet_pool.py", "--max-roi", "0.1"])

    with pytest.raises(SystemExit):
        builder._parse_args()

    assert "--max-roi must be less than or equal to 0" in capsys.readouterr().err


def test_build_wallet_pool_rejects_positive_max_pnl_vlm_ratio_cli_arg(mocker, capsys):
    mocker.patch("sys.argv", ["build_wallet_pool.py", "--max-pnl-vlm-ratio", "0.1"])

    with pytest.raises(SystemExit):
        builder._parse_args()

    assert "--max-pnl-vlm-ratio must be less than or equal to 0" in capsys.readouterr().err
