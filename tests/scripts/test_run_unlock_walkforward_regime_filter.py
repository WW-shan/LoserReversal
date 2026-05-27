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
    btc_close = _btc_close_from_path(btc_path)

    filtered = cli.apply_btc_regime_filter(
        events,
        btc_close=btc_close,
        signal_offset_days=0,
        direction="short",
    )

    assert set(filtered["token"]) == {"bear1", "bear2"}
    assert "bull1" not in set(filtered["token"])


def test_apply_btc_regime_filter_uses_v2_offset_minus_30(tmp_path: Path):
    days = pd.date_range("2025-01-01T00:00:00Z", periods=305, freq="1D", tz="UTC")
    closes = np.full(305, 100.0)
    closes[243] = 80.0
    closes[244:] = 120.0
    btc_path = tmp_path / "BTC_1d.parquet"
    pd.DataFrame(
        {
            "timestamp": days,
            "open": closes,
            "high": closes,
            "low": closes,
            "close": closes,
            "volume": [1.0] * 305,
        }
    ).to_parquet(btc_path, index=False)
    events = pd.DataFrame(
        {
            "token": ["entry_bear_unlock_bull"],
            "unlock_date": pd.to_datetime(["2025-10-01"], utc=True),
            "unlock_pct": [0.05],
            "category": ["team"],
            "has_hl_perp": [True],
            "vesting_type": ["cliff"],
        }
    )
    btc_close = _btc_close_from_path(btc_path)

    filtered = cli.apply_btc_regime_filter(
        events,
        btc_close=btc_close,
        signal_offset_days=-30,
        direction="short",
    )

    assert filtered["token"].tolist() == ["entry_bear_unlock_bull"]


def test_apply_btc_regime_filter_uses_v1_offset_minus_7(tmp_path: Path):
    btc_path = _write_btc_fixture(
        tmp_path,
        days=pd.date_range("2025-01-01T00:00:00Z", periods=305, freq="1D", tz="UTC"),
        marks={
            pd.Timestamp("2025-09-24T00:00:00Z"): 80.0,
            pd.Timestamp("2025-10-01T00:00:00Z"): 120.0,
        },
    )
    events = _single_event("v1_entry_bear_unlock_bull", "2025-10-01")

    filtered = cli.apply_btc_regime_filter(
        events,
        btc_close=_btc_close_from_path(btc_path),
        signal_offset_days=-7,
        direction="short",
    )

    assert filtered["token"].tolist() == ["v1_entry_bear_unlock_bull"]


def test_apply_btc_regime_filter_uses_v3_offset_minus_2(tmp_path: Path):
    btc_path = _write_btc_fixture(
        tmp_path,
        days=pd.date_range("2025-01-01T00:00:00Z", periods=305, freq="1D", tz="UTC"),
        marks={
            pd.Timestamp("2025-09-29T00:00:00Z"): 80.0,
            pd.Timestamp("2025-10-01T00:00:00Z"): 120.0,
        },
    )
    events = _single_event("v3_entry_bear_unlock_bull", "2025-10-01")

    filtered = cli.apply_btc_regime_filter(
        events,
        btc_close=_btc_close_from_path(btc_path),
        signal_offset_days=-2,
        direction="short",
    )

    assert filtered["token"].tolist() == ["v3_entry_bear_unlock_bull"]


def test_apply_btc_regime_filter_uses_v4_offset_minus_3(tmp_path: Path):
    from signals.unlock_grid import SIGNAL_REGISTRY

    spec = SIGNAL_REGISTRY["v4"]
    assert spec.entry_offset_days == -3
    assert spec.direction == "short"
    btc_path = _write_btc_fixture(
        tmp_path,
        days=pd.date_range("2025-01-01T00:00:00Z", periods=305, freq="1D", tz="UTC"),
        marks={
            pd.Timestamp("2025-09-28T00:00:00Z"): 80.0,
            pd.Timestamp("2025-10-01T00:00:00Z"): 120.0,
        },
    )
    events = _single_event("v4_entry_bear_unlock_bull", "2025-10-01")

    filtered = cli.apply_btc_regime_filter(
        events,
        btc_close=_btc_close_from_path(btc_path),
        signal_offset_days=spec.entry_offset_days,
        direction=spec.direction,
    )

    assert filtered["token"].tolist() == ["v4_entry_bear_unlock_bull"]


def test_apply_btc_regime_filter_uses_v5_offset_plus_3(tmp_path: Path):
    btc_path = _write_btc_fixture(
        tmp_path,
        days=pd.date_range("2025-01-01T00:00:00Z", periods=310, freq="1D", tz="UTC"),
        marks={
            pd.Timestamp("2025-10-01T00:00:00Z"): 80.0,
            pd.Timestamp("2025-10-04T00:00:00Z"): 120.0,
        },
    )
    events = _single_event("v5_entry_bull", "2025-10-01")

    filtered = cli.apply_btc_regime_filter(
        events,
        btc_close=_btc_close_from_path(btc_path),
        signal_offset_days=3,
        direction="long",
    )

    assert filtered["token"].tolist() == ["v5_entry_bull"]


def test_apply_btc_regime_filter_raises_when_btc_candles_missing(tmp_path: Path):
    """Helpful error directing user to backfill rather than silent pass-through."""
    config = cli.WalkForwardV15Config(
        regime_filter="btc-200ma",
        btc_candles_path=tmp_path / "missing.parquet",
    )
    with pytest.raises(RuntimeError, match="BTC 1d candles"):
        cli._load_btc_close_for_regime(config)


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
        cli._load_btc_close_for_regime(config)


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


def test_run_walkforward_threads_regime_to_per_signal_without_global_filter(
    monkeypatch,
    tmp_path: Path,
):
    btc_path = _write_btc_fixture(
        tmp_path,
        days=pd.date_range("2025-01-01T00:00:00Z", periods=305, freq="1D", tz="UTC"),
        marks={
            pd.Timestamp("2025-09-24T00:00:00Z"): 80.0,
            pd.Timestamp("2025-10-01T00:00:00Z"): 120.0,
        },
    )
    captured: dict[str, object] = {}
    captured_portfolio: dict[str, object] = {}
    split = (
        (pd.Timestamp("2025-01-01T00:00:00Z"), pd.Timestamp("2025-09-01T00:00:00Z")),
        (pd.Timestamp("2025-09-01T00:00:00Z"), pd.Timestamp("2025-11-01T00:00:00Z")),
    )

    monkeypatch.setattr(
        cli,
        "read_unlocks",
        lambda path=None: _single_event("v1_entry_bear_unlock_bull", "2025-10-01"),
        raising=False,
    )
    monkeypatch.setattr(cli, "load_coverage", lambda path: _coverage(), raising=False)
    monkeypatch.setattr(cli, "load_prices", lambda events, candles_dir: {"ARB": _prices()})
    monkeypatch.setattr(cli, "walk_forward_splits", lambda *args, **kwargs: [split])
    monkeypatch.setattr(
        cli,
        "run_per_signal_walkforward",
        lambda events, *args, **kwargs: (
            captured.update({"events": events, **kwargs}) or _per_signal_frame()
        ),
    )
    monkeypatch.setattr(
        cli,
        "compose_portfolio",
        lambda *args, **kwargs: (captured_portfolio.update(kwargs) or _portfolio_frame()),
    )
    grid_path = tmp_path / "grid.parquet"
    _grid_df().to_parquet(grid_path, index=False)

    cli.run_walkforward(
        cli.WalkForwardV15Config(
            n_splits=1,
            min_train_days=30,
            test_days=30,
            out=tmp_path / "out.parquet",
            report=tmp_path / "report.md",
            grid_path=grid_path,
            regime_filter="btc-200ma",
            btc_candles_path=btc_path,
        )
    )

    assert captured["events"]["token"].tolist() == ["v1_entry_bear_unlock_bull"]
    assert isinstance(captured["regime_btc_close"], pd.Series)
    assert isinstance(captured_portfolio["regime_btc_close"], pd.Series)


def _btc_close_from_path(path: Path) -> pd.Series:
    frame = pd.read_parquet(path)
    return pd.Series(
        pd.to_numeric(frame["close"], errors="coerce").to_numpy(),
        index=pd.to_datetime(frame["timestamp"], utc=True),
        dtype="float64",
        name="close",
    ).dropna()


def _single_event(token: str, unlock_date: str) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "token": [token],
            "unlock_date": pd.to_datetime([unlock_date], utc=True),
            "unlock_pct": [0.05],
            "category": ["team"],
            "has_hl_perp": [True],
            "vesting_type": ["cliff"],
        }
    )


def _write_btc_fixture(
    tmp_path: Path,
    *,
    days: pd.DatetimeIndex,
    marks: dict[pd.Timestamp, float],
) -> Path:
    closes = np.full(len(days), 100.0)
    day_lookup = {day: idx for idx, day in enumerate(days)}
    for day, close in marks.items():
        closes[day_lookup[day]] = close
        next_idx = day_lookup[day] + 1
        if close > 100.0 and next_idx < len(closes):
            closes[next_idx:] = close
    btc_path = tmp_path / f"BTC_{len(marks)}_1d.parquet"
    pd.DataFrame(
        {
            "timestamp": days,
            "open": closes,
            "high": closes,
            "low": closes,
            "close": closes,
            "volume": [1.0] * len(days),
        }
    ).to_parquet(btc_path, index=False)
    return btc_path


def _coverage() -> pd.DataFrame:
    return pd.DataFrame(
        [{"token": "ARB", "unlock_date": "2025-10-01", "coverage_status": "ok"}]
    )


def _prices() -> pd.Series:
    index = pd.date_range("2025-01-01", periods=305, freq="1D", tz="UTC")
    return pd.Series(np.arange(305), index=index, name="close", dtype="float64")


def _per_signal_frame() -> pd.DataFrame:
    rows = [
        _row("per_signal", "v1", 0, 1, 0.7, 1.0),
        _row("per_signal", "v1", -1, 1, 0.7, 1.0),
    ]
    return pd.DataFrame(rows)


def _portfolio_frame() -> pd.DataFrame:
    return pd.DataFrame(
        [
            _row("portfolio", "top_1_equal_weight", 0, 1, 0.7, 1.0),
            _row("portfolio", "top_1_equal_weight", -1, 1, 0.7, 1.0),
        ]
    )


def _grid_df() -> pd.DataFrame:
    return pd.DataFrame([{"signal": "v1", "min_unlock_pct": 0.01, "cohort": "team"}])


def _row(
    kind: str,
    signal: str,
    split_idx: int,
    n_trades: int,
    sharpe: float,
    win_rate: float,
) -> dict[str, object]:
    split = (
        (pd.Timestamp("2025-01-01T00:00:00Z"), pd.Timestamp("2025-09-01T00:00:00Z")),
        (pd.Timestamp("2025-09-01T00:00:00Z"), pd.Timestamp("2025-11-01T00:00:00Z")),
    )
    return {
        "kind": kind,
        "signal": signal,
        "split_idx": split_idx,
        "train_start": split[0][0] if split_idx >= 0 else pd.NaT,
        "train_end": split[0][1] if split_idx >= 0 else pd.NaT,
        "test_start": split[1][0] if split_idx >= 0 else pd.NaT,
        "test_end": split[1][1] if split_idx >= 0 else pd.NaT,
        "selected_min_pct": 0.01 if split_idx >= 0 else float("nan"),
        "selected_cohort": "team" if split_idx >= 0 else "aggregate",
        "n_trades": n_trades,
        "sharpe": sharpe,
        "sortino": sharpe,
        "win_rate": win_rate,
        "max_dd": -0.02,
        "total_return": 0.03,
        "fallback_used": False,
    }
