from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from scripts import run_unlock_walkforward_v15 as cli


def test_walkforward_config_has_regime_filter_fields():
    """Field plumbing — required for Ablation C wiring."""
    config = cli.WalkForwardV15Config(regime_filter="btc-200ma")
    assert config.regime_filter == "btc-200ma"
    assert config.btc_candles_path is None


def test_apply_btc_regime_filter_drops_bull_period_events(tmp_path: Path):
    """Events landing in BTC < 200d SMA (bear) are kept; bull-period dropped."""
    # 300 days of synthetic BTC: first 200 flat at 100 to warm SMA, then drop
    # to 80 (bear) for next 100. SMA stays around 100 → bear flag True after drop.
    days = pd.date_range("2024-01-01T00:00:00Z", periods=300, freq="1D", tz="UTC")
    closes = np.full(300, 100.0)
    closes[200:] = 80.0
    btc_path = tmp_path / "BTC_1d.parquet"
    pd.DataFrame(
        {
            "timestamp": days,
            "open": closes,
            "high": closes,
            "low": closes,
            "close": closes,
            "volume": [1.0] * 300,
        }
    ).to_parquet(btc_path, index=False)

    events = pd.DataFrame(
        {
            "token": ["bull1", "bear1", "bear2"],
            "unlock_date": pd.to_datetime(
                ["2024-04-01", "2024-09-15", "2024-10-01"], utc=True
            ),
            "unlock_pct": [0.05, 0.05, 0.05],
            "category": ["team", "team", "team"],
            "has_hl_perp": [True, True, True],
            "vesting_type": ["cliff", "cliff", "cliff"],
        }
    )
    config = cli.WalkForwardV15Config(
        regime_filter="btc-200ma",
        btc_candles_path=btc_path,
    )

    filtered = cli.apply_btc_regime_filter(events, config)

    assert set(filtered["token"]) == {"bear1", "bear2"}
    assert "bull1" not in set(filtered["token"])


def test_apply_btc_regime_filter_raises_when_btc_candles_missing(tmp_path: Path):
    """Helpful error directing user to backfill rather than silent pass-through."""
    config = cli.WalkForwardV15Config(
        regime_filter="btc-200ma",
        btc_candles_path=tmp_path / "missing.parquet",
    )
    with pytest.raises(RuntimeError, match="BTC 1d candles"):
        cli.apply_btc_regime_filter(pd.DataFrame(), config)


def test_apply_btc_regime_filter_raises_when_btc_close_column_missing(tmp_path: Path):
    btc_path = tmp_path / "BTC_1d.parquet"
    pd.DataFrame(
        {
            "timestamp": pd.date_range("2024-01-01T00:00:00Z", periods=3, freq="1D"),
            "open": [100.0, 101.0, 102.0],
        }
    ).to_parquet(btc_path, index=False)
    config = cli.WalkForwardV15Config(
        regime_filter="btc-200ma",
        btc_candles_path=btc_path,
    )

    with pytest.raises(RuntimeError, match="close"):
        cli.apply_btc_regime_filter(pd.DataFrame(), config)


def test_cli_parse_args_accepts_regime_filter_btc_200ma():
    args = cli._parse_args(["--regime-filter", "btc-200ma"])
    assert args.regime_filter == "btc-200ma"


def test_cli_parse_args_rejects_unknown_regime_filter():
    with pytest.raises(SystemExit):
        cli._parse_args(["--regime-filter", "sideways"])


def test_cli_parse_args_regime_filter_defaults_to_none():
    args = cli._parse_args([])
    assert args.regime_filter == "none"


def test_main_threads_regime_filter_to_config(monkeypatch):
    """main() converts argparse 'none' to None, anything else passes through."""
    captured: dict = {}

    def fake_run(config):
        captured["regime_filter"] = config.regime_filter
        return {}

    monkeypatch.setattr(cli, "run_walkforward", fake_run)

    cli.main(["--regime-filter", "btc-200ma"])
    assert captured["regime_filter"] == "btc-200ma"

    cli.main(["--regime-filter", "none"])
    assert captured["regime_filter"] is None
