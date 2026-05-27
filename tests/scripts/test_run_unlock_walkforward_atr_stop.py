"""ATR-adaptive stop_loss flags on the run_unlock_walkforward_v15 CLI."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from infra.backtest import engine
from scripts import run_unlock_walkforward_v15 as runner


def test_config_default_stop_loss_mode_is_fixed():
    config = runner.WalkForwardV15Config()

    assert config.stop_loss_mode == "fixed"
    assert config.stop_loss_atr_period == 14
    assert config.stop_loss_atr_multiplier == 2.0
    assert config.stop_loss_atr_floor == 0.08
    assert config.stop_loss_atr_cap == 0.25


def test_cli_parses_atr_mode_with_defaults(monkeypatch):
    captured: list[runner.WalkForwardV15Config] = []

    monkeypatch.setattr(
        runner,
        "run_walkforward",
        lambda config: captured.append(config) or {},
    )

    exit_code = runner.main(["--stop-loss-mode", "atr"])

    assert exit_code == 0
    assert captured[0].stop_loss_mode == "atr"
    assert captured[0].stop_loss_atr_period == 14
    assert captured[0].stop_loss_atr_multiplier == 2.0
    assert captured[0].stop_loss_atr_floor == 0.08
    assert captured[0].stop_loss_atr_cap == 0.25


def test_cli_atr_mode_emits_best_is_per_variant_warning(monkeypatch, capsys):
    monkeypatch.setattr(runner, "run_walkforward", lambda config: {})

    exit_code = runner.main(["--stop-loss-mode", "atr"])

    assert exit_code == 0
    err = capsys.readouterr().err
    assert "best-IS-per-variant" in err
    assert "lock-is-cell" not in err


def test_cli_rejects_lock_is_cell_flag():
    with pytest.raises(SystemExit):
        runner._parse_args(["--lock-is-cell", "v2,0.02,team"])


def test_cli_parses_atr_mode_with_custom_knobs(monkeypatch):
    captured: list[runner.WalkForwardV15Config] = []

    monkeypatch.setattr(
        runner,
        "run_walkforward",
        lambda config: captured.append(config) or {},
    )

    exit_code = runner.main(
        [
            "--stop-loss-mode",
            "atr",
            "--stop-loss-atr-period",
            "21",
            "--stop-loss-atr-multiplier",
            "3.0",
            "--stop-loss-atr-floor",
            "0.05",
            "--stop-loss-atr-cap",
            "0.30",
        ]
    )

    assert exit_code == 0
    assert captured[0].stop_loss_mode == "atr"
    assert captured[0].stop_loss_atr_period == 21
    assert captured[0].stop_loss_atr_multiplier == pytest.approx(3.0)
    assert captured[0].stop_loss_atr_floor == pytest.approx(0.05)
    assert captured[0].stop_loss_atr_cap == pytest.approx(0.30)


def test_cli_rejects_unknown_stop_loss_mode(monkeypatch, capsys):
    monkeypatch.setattr(runner, "run_walkforward", lambda config: {})

    with pytest.raises(SystemExit) as exc:
        runner.main(["--stop-loss-mode", "trailing"])

    assert exc.value.code != 0
    err = capsys.readouterr().err
    assert "stop-loss-mode" in err or "trailing" in err


def test_cli_rejects_atr_multiplier_zero_or_negative(monkeypatch, capsys):
    monkeypatch.setattr(runner, "run_walkforward", lambda config: {})

    with pytest.raises(SystemExit) as exc:
        runner.main(["--stop-loss-mode", "atr", "--stop-loss-atr-multiplier", "0"])

    assert exc.value.code != 0
    err = capsys.readouterr().err
    assert "atr-multiplier" in err or "multiplier" in err


def test_cli_rejects_atr_floor_above_cap(monkeypatch, capsys):
    monkeypatch.setattr(runner, "run_walkforward", lambda config: {})

    with pytest.raises(SystemExit) as exc:
        runner.main(
            [
                "--stop-loss-mode",
                "atr",
                "--stop-loss-atr-floor",
                "0.30",
                "--stop-loss-atr-cap",
                "0.20",
            ]
        )

    assert exc.value.code != 0
    err = capsys.readouterr().err
    assert "floor" in err and "cap" in err


def test_run_walkforward_forwards_atr_kwargs(monkeypatch, tmp_path):
    split = _split("2026-01-01", "2026-07-01", "2026-07-01", "2026-10-01")
    captured_per_signal: list[dict[str, object]] = []
    captured_portfolio: list[dict[str, object]] = []

    monkeypatch.setattr(runner, "read_unlocks", lambda path=None: _events(), raising=False)
    monkeypatch.setattr(runner, "load_coverage", lambda path: _coverage(), raising=False)
    monkeypatch.setattr(runner, "load_prices", lambda events, candles_dir: {"ARB": _prices()})
    monkeypatch.setattr(
        runner,
        "_load_high_low_prices",
        lambda events, candles_dir: ({"ARB": _highs()}, {"ARB": _lows()}),
        raising=False,
    )
    monkeypatch.setattr(runner, "walk_forward_splits", lambda *args, **kwargs: [split])
    monkeypatch.setattr(
        runner,
        "run_per_signal_walkforward",
        lambda *args, **kwargs: (captured_per_signal.append(kwargs) or _per_signal_frame()),
    )
    monkeypatch.setattr(
        runner,
        "compose_portfolio",
        lambda *args, **kwargs: (captured_portfolio.append(kwargs) or _portfolio_frame()),
    )

    config = runner.WalkForwardV15Config(
        n_splits=1,
        min_train_days=180,
        test_days=90,
        out=tmp_path / "out.parquet",
        report=tmp_path / "report.md",
        stop_loss_mode="atr",
        stop_loss_atr_period=14,
        stop_loss_atr_multiplier=2.0,
        stop_loss_atr_floor=0.08,
        stop_loss_atr_cap=0.25,
    )
    runner.run_walkforward(config)

    assert captured_per_signal[0]["stop_loss_mode"] == "atr"
    assert captured_per_signal[0]["stop_loss_atr_period"] == 14
    assert captured_per_signal[0]["stop_loss_atr_multiplier"] == pytest.approx(2.0)
    assert captured_per_signal[0]["stop_loss_floor"] == pytest.approx(0.08)
    assert captured_per_signal[0]["stop_loss_cap"] == pytest.approx(0.25)
    assert captured_per_signal[0]["highs"]["ARB"].equals(_highs())
    assert captured_per_signal[0]["lows"]["ARB"].equals(_lows())
    assert captured_portfolio[0]["stop_loss_mode"] == "atr"
    assert captured_portfolio[0]["stop_loss_atr_period"] == 14
    assert captured_portfolio[0]["highs"]["ARB"].equals(_highs())
    assert captured_portfolio[0]["lows"]["ARB"].equals(_lows())


def test_report_methodology_describes_atr_mode(tmp_path):
    """Methodology line must describe ATR mode when active."""
    report = tmp_path / "phase1_5_walkforward.md"

    runner._write_report(
        report,
        pd.concat([_per_signal_frame(), _portfolio_frame()], ignore_index=True),
        _grid_df(),
        runner.WalkForwardV15Config(
            report=report,
            stop_loss_mode="atr",
            stop_loss_atr_period=14,
            stop_loss_atr_multiplier=2.0,
            stop_loss_atr_floor=0.08,
            stop_loss_atr_cap=0.25,
        ),
        effective_test_days=180,
        fallback_used=False,
    )

    text = report.read_text(encoding="utf-8")
    assert "atr" in text.lower() or "ATR" in text
    assert "multiplier" in text.lower() or "2.0" in text


def test_atr_with_high_low_uses_wilder_rma():
    close = np.array([10.0, 11.0, 10.0, 12.0], dtype="float64")
    high = np.array([12.0, 12.0, 11.0, 13.0], dtype="float64")
    low = np.array([9.0, 10.0, 9.0, 10.0], dtype="float64")

    atr = engine._compute_atr(close, 3, high=high, low=low)

    np.testing.assert_allclose(
        atr,
        np.array([3.0, 2.6666666667, 2.4444444444, 2.6296296296]),
        rtol=1e-9,
    )


def test_atr_close_only_emits_warning():
    close = np.array([10.0, 12.0, 11.0, 15.0], dtype="float64")

    with pytest.warns(UserWarning, match="close-only proxy"):
        atr = engine._compute_atr(close, 3)

    np.testing.assert_allclose(
        atr,
        np.array([0.0, 0.6666666667, 0.7777777778, 1.8518518519]),
        rtol=1e-9,
    )


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


def _highs() -> pd.Series:
    prices = _prices()
    return (prices + 2.0).rename("high")


def _lows() -> pd.Series:
    prices = _prices()
    return (prices - 2.0).rename("low")


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


def _grid_df() -> pd.DataFrame:
    return pd.DataFrame([{"signal": "v2", "min_unlock_pct": 0.02, "cohort": "team"}])


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
