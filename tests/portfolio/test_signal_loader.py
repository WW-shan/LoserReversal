from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from portfolio.signal_loader import LoadedSignal, load_active_signals


def test_load_active_signals_reads_config_and_filters_signal_returns(tmp_path: Path) -> None:
    trades = tmp_path / "trades.parquet"
    pd.DataFrame(
        {
            "signal": ["v1", "v2", "v1"],
            "entry_ts": pd.to_datetime(
                ["2026-01-01", "2026-01-02", "2026-01-03"],
                utc=True,
            ),
            "return": [0.10, -0.50, 0.04],
        }
    ).to_parquet(trades, index=False)
    config = _write_config(tmp_path / "unlock_v1_stop.json", source_parquet=trades)

    signals = load_active_signals([str(config)])

    assert signals == [
        LoadedSignal(
            name="v1+D",
            returns=pd.Series(
                [0.10, 0.04],
                index=pd.to_datetime(["2026-01-01", "2026-01-03"], utc=True),
                dtype="float64",
                name="v1+D",
            ),
            bayesian_ci=(0.5035, 1.8812, 3.3224),
            sharpe_lower=0.5035,
            weight_max=0.10,
            config_path=config,
            raw_config={
                "name": "v1+D",
                "signal": "v1",
                "portfolio_weight_max": 0.10,
                "sharpe_lower_ci_2_5": 0.5035,
                "sharpe_median_50": 1.8812,
                "sharpe_upper_ci_97_5": 3.3224,
                "source_parquet": str(trades),
            },
        )
    ]


def test_load_active_signals_accepts_glob_patterns_in_sorted_order(tmp_path: Path) -> None:
    first_trades = _write_returns(tmp_path / "first.parquet", [0.01])
    second_trades = _write_returns(tmp_path / "second.parquet", [0.02])
    _write_config(tmp_path / "b.json", name="b", signal="b", source_parquet=second_trades)
    _write_config(tmp_path / "a.json", name="a", signal="a", source_parquet=first_trades)

    signals = load_active_signals([str(tmp_path / "*.json")])

    assert [signal.name for signal in signals] == ["a", "b"]


def test_load_active_signals_returns_empty_for_unmatched_glob(tmp_path: Path) -> None:
    assert load_active_signals([str(tmp_path / "*.json")]) == []


def test_load_active_signals_filters_optional_phase_column(tmp_path: Path) -> None:
    trades = tmp_path / "trades.parquet"
    pd.DataFrame(
        {
            "signal": ["v1", "v1", "v1"],
            "phase": ["IS", "OOS", "OOS"],
            "return": [0.50, 0.03, 0.05],
        }
    ).to_parquet(trades, index=False)
    config = _write_config(tmp_path / "unlock_v1_stop.json", source_parquet=trades, phase="OOS")

    signals = load_active_signals([str(config)])

    assert signals[0].returns.tolist() == [0.03, 0.05]


def test_load_active_signals_raises_for_missing_required_config_key(tmp_path: Path) -> None:
    config = tmp_path / "broken.json"
    config.write_text(json.dumps({"name": "broken"}), encoding="utf-8")

    with pytest.raises(ValueError, match="missing required key"):
        load_active_signals([str(config)])


def test_load_active_signals_raises_when_no_returns_match(tmp_path: Path) -> None:
    trades = _write_returns(tmp_path / "trades.parquet", [0.10], signal="v2")
    config = _write_config(tmp_path / "unlock_v1_stop.json", source_parquet=trades)

    with pytest.raises(ValueError, match="no OOS returns"):
        load_active_signals([str(config)])


def _write_config(
    path: Path,
    *,
    name: str = "v1+D",
    signal: str = "v1",
    source_parquet: Path,
    phase: str | None = None,
) -> Path:
    payload: dict[str, object] = {
        "name": name,
        "signal": signal,
        "portfolio_weight_max": 0.10,
        "sharpe_lower_ci_2_5": 0.5035,
        "sharpe_median_50": 1.8812,
        "sharpe_upper_ci_97_5": 3.3224,
        "source_parquet": str(source_parquet),
    }
    if phase is not None:
        payload["phase"] = phase
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _write_returns(path: Path, returns: list[float], *, signal: str | None = None) -> Path:
    payload: dict[str, object] = {"return": returns}
    if signal is not None:
        payload["signal"] = [signal] * len(returns)
    pd.DataFrame(payload).to_parquet(path, index=False)
    return path
