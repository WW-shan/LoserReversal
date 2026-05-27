from __future__ import annotations

import pandas as pd
import pytest

from scripts import run_unlock_walkforward_v15 as runner


def test_config_default_stop_loss_is_none():
    config = runner.WalkForwardV15Config()

    assert config.stop_loss is None


def test_cli_parses_stop_loss_flag_and_forwards_to_runner(monkeypatch):
    captured_configs: list[runner.WalkForwardV15Config] = []

    def fake_run_walkforward(config: runner.WalkForwardV15Config) -> dict:
        captured_configs.append(config)
        return {}

    monkeypatch.setattr(runner, "run_walkforward", fake_run_walkforward)

    exit_code = runner.main(["--stop-loss", "0.10"])

    assert exit_code == 0
    assert len(captured_configs) == 1
    assert captured_configs[0].stop_loss == pytest.approx(0.10)


def test_cli_rejects_negative_stop_loss(monkeypatch, capsys):
    monkeypatch.setattr(runner, "run_walkforward", lambda config: {})

    with pytest.raises(SystemExit) as exc:
        runner.main(["--stop-loss", "-0.05"])

    assert exc.value.code != 0
    err = capsys.readouterr().err
    assert "stop-loss" in err or "--stop-loss" in err


def test_cli_rejects_stop_loss_greater_than_one(monkeypatch, capsys):
    monkeypatch.setattr(runner, "run_walkforward", lambda config: {})

    with pytest.raises(SystemExit) as exc:
        runner.main(["--stop-loss", "1.5"])

    assert exc.value.code != 0
    err = capsys.readouterr().err
    assert "stop-loss" in err or "--stop-loss" in err


def test_cli_rejects_stop_loss_scalar_with_atr_mode(monkeypatch, capsys):
    monkeypatch.setattr(runner, "run_walkforward", lambda config: {})

    with pytest.raises(SystemExit) as exc:
        runner.main(["--stop-loss", "0.10", "--stop-loss-mode", "atr"])

    assert exc.value.code != 0
    err = capsys.readouterr().err
    assert "incompatible" in err
    assert "stop-loss-mode atr" in err


def test_cli_without_stop_loss_keeps_none(monkeypatch):
    captured_configs: list[runner.WalkForwardV15Config] = []
    monkeypatch.setattr(
        runner,
        "run_walkforward",
        lambda config: captured_configs.append(config) or {},
    )

    exit_code = runner.main([])

    assert exit_code == 0
    assert captured_configs[0].stop_loss is None


def test_run_walkforward_forwards_stop_loss_to_per_signal_runner(monkeypatch, tmp_path):
    split = _split("2026-01-01", "2026-07-01", "2026-07-01", "2026-10-01")
    captured_per_signal: list[dict[str, object]] = []
    captured_portfolio: list[dict[str, object]] = []

    def fake_run_per_signal_walkforward(*args, **kwargs):
        captured_per_signal.append(kwargs)
        return _per_signal_frame()

    def fake_compose_portfolio(*args, **kwargs):
        captured_portfolio.append(kwargs)
        return _portfolio_frame()

    monkeypatch.setattr(runner, "read_unlocks", lambda path=None: _events(), raising=False)
    monkeypatch.setattr(runner, "load_coverage", lambda path: _coverage(), raising=False)
    monkeypatch.setattr(runner, "load_prices", lambda events, candles_dir: {"ARB": _prices()})
    monkeypatch.setattr(runner, "walk_forward_splits", lambda *args, **kwargs: [split])
    monkeypatch.setattr(runner, "run_per_signal_walkforward", fake_run_per_signal_walkforward)
    monkeypatch.setattr(runner, "compose_portfolio", fake_compose_portfolio)

    config = runner.WalkForwardV15Config(
        n_splits=1,
        min_train_days=180,
        test_days=90,
        out=tmp_path / "out.parquet",
        report=tmp_path / "report.md",
        stop_loss=0.10,
    )
    runner.run_walkforward(config)

    assert captured_per_signal[0]["stop_loss"] == pytest.approx(0.10)
    assert captured_portfolio[0]["stop_loss"] == pytest.approx(0.10)


def _events() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "token": "ARB",
                "coingecko_id": "arb",
                "unlock_date": pd.Timestamp("2026-01-05T00:00:00Z"),
                "unlock_pct": 0.05,
                "category": "insiders",
                "has_hl_perp": True,
                "vesting_type": "cliff",
            },
            {
                "token": "ARB",
                "coingecko_id": "arb",
                "unlock_date": pd.Timestamp("2026-10-01T00:00:00Z"),
                "unlock_pct": 0.05,
                "category": "insiders",
                "has_hl_perp": True,
                "vesting_type": "cliff",
            },
        ]
    )


def _coverage() -> pd.DataFrame:
    return pd.DataFrame(
        [{"token": "ARB", "unlock_date": "2026-01-05", "coverage_status": "ok"}]
    )


def _prices() -> pd.Series:
    index = pd.date_range("2026-01-01", periods=300, freq="1D", tz="UTC")
    return pd.Series(range(300), index=index, name="close", dtype="float64")


def _split(
    train_start: str,
    train_end: str,
    test_start: str,
    test_end: str,
) -> tuple[tuple[pd.Timestamp, pd.Timestamp], tuple[pd.Timestamp, pd.Timestamp]]:
    return (
        (pd.Timestamp(train_start, tz="UTC"), pd.Timestamp(train_end, tz="UTC")),
        (pd.Timestamp(test_start, tz="UTC"), pd.Timestamp(test_end, tz="UTC")),
    )


def _per_signal_frame() -> pd.DataFrame:
    rows = [
        _row("per_signal", "v2", 0, 5, 0.7, 0.60),
        _row("per_signal", "v2", -1, 5, 0.7, 0.60),
    ]
    return pd.DataFrame(rows)


def _portfolio_frame() -> pd.DataFrame:
    return pd.DataFrame(
        [
            _row("portfolio", "top_1_equal_weight", 0, 5, 0.7, 0.60),
            _row("portfolio", "top_1_equal_weight", -1, 5, 0.7, 0.60),
        ]
    )


def _row(
    kind: str,
    signal: str,
    split_idx: int,
    n_trades: int,
    sharpe: float,
    win_rate: float,
) -> dict[str, object]:
    split = _split("2026-01-01", "2026-07-01", "2026-07-01", "2026-10-01")
    return {
        "kind": kind,
        "signal": signal,
        "split_idx": split_idx,
        "train_start": split[0][0] if split_idx >= 0 else pd.NaT,
        "train_end": split[0][1] if split_idx >= 0 else pd.NaT,
        "test_start": split[1][0] if split_idx >= 0 else pd.NaT,
        "test_end": split[1][1] if split_idx >= 0 else pd.NaT,
        "selected_min_pct": 0.02 if split_idx >= 0 else float("nan"),
        "selected_cohort": "team" if split_idx >= 0 else "aggregate",
        "n_trades": n_trades,
        "sharpe": sharpe,
        "sortino": sharpe + 0.2,
        "win_rate": win_rate,
        "max_dd": -0.02,
        "total_return": 0.03,
        "fallback_used": False,
    }
