from __future__ import annotations

import pandas as pd
import pytest

from scripts import run_unlock_walkforward_v15 as runner


def test_config_default_fix_cohort_is_none():
    config = runner.WalkForwardV15Config()

    assert config.fix_cohort is None


def test_cli_parses_fix_cohort_team_and_forwards_to_runner(monkeypatch, tmp_path):
    captured_configs: list[runner.WalkForwardV15Config] = []

    def fake_run_walkforward(config):
        captured_configs.append(config)
        return {}

    monkeypatch.setattr(runner, "run_walkforward", fake_run_walkforward)

    exit_code = runner.main(["--fix-cohort", "team"])

    assert exit_code == 0
    assert len(captured_configs) == 1
    assert captured_configs[0].fix_cohort == "team"


@pytest.mark.parametrize("cohort_value", ["team", "team+investor", "all"])
def test_cli_accepts_cohort_choices(monkeypatch, cohort_value):
    captured_configs: list[runner.WalkForwardV15Config] = []
    monkeypatch.setattr(
        runner,
        "run_walkforward",
        lambda config: captured_configs.append(config) or {},
    )

    exit_code = runner.main(["--fix-cohort", cohort_value])

    assert exit_code == 0
    assert captured_configs[0].fix_cohort == cohort_value


def test_cli_fix_cohort_none_keeps_default_search(monkeypatch):
    captured_configs: list[runner.WalkForwardV15Config] = []
    monkeypatch.setattr(
        runner,
        "run_walkforward",
        lambda config: captured_configs.append(config) or {},
    )

    exit_code = runner.main(["--fix-cohort", "none"])

    assert exit_code == 0
    assert captured_configs[0].fix_cohort is None


def test_cli_rejects_unknown_fix_cohort_value(monkeypatch, capsys):
    monkeypatch.setattr(runner, "run_walkforward", lambda config: {})

    with pytest.raises(SystemExit) as exc:
        runner.main(["--fix-cohort", "whales"])

    assert exc.value.code != 0
    err = capsys.readouterr().err
    assert "fix-cohort" in err or "--fix-cohort" in err


def test_run_walkforward_forwards_fix_cohort_to_per_signal_runner(monkeypatch, tmp_path):
    split = _split("2026-01-01", "2026-07-01", "2026-07-01", "2026-10-01")
    captured_kwargs: list[dict[str, object]] = []

    def fake_run_per_signal_walkforward(*args, **kwargs):
        captured_kwargs.append(kwargs)
        return _per_signal_frame()

    monkeypatch.setattr(runner, "read_unlocks", lambda path=None: _events(), raising=False)
    monkeypatch.setattr(runner, "load_coverage", lambda path: _coverage(), raising=False)
    monkeypatch.setattr(runner, "load_prices", lambda events, candles_dir: {"ARB": _prices()})
    monkeypatch.setattr(runner, "walk_forward_splits", lambda *args, **kwargs: [split])
    monkeypatch.setattr(runner, "run_per_signal_walkforward", fake_run_per_signal_walkforward)
    monkeypatch.setattr(runner, "compose_portfolio", lambda *args, **kwargs: _portfolio_frame())

    config = runner.WalkForwardV15Config(
        n_splits=1,
        min_train_days=180,
        test_days=90,
        out=tmp_path / "out.parquet",
        report=tmp_path / "report.md",
        fix_cohort="team",
    )
    runner.run_walkforward(config)

    assert captured_kwargs[0]["fix_cohort"] == "team"


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
        _row("per_signal", "v2", 0, 5, 0.7, 0.60, cohort="team"),
        _row("per_signal", "v2", -1, 5, 0.7, 0.60, cohort="team"),
    ]
    return pd.DataFrame(rows)


def _portfolio_frame() -> pd.DataFrame:
    return pd.DataFrame(
        [
            _row("portfolio", "top_1_equal_weight", 0, 5, 0.7, 0.60, cohort="team"),
            _row("portfolio", "top_1_equal_weight", -1, 5, 0.7, 0.60, cohort="team"),
        ]
    )


def _row(
    kind: str,
    signal: str,
    split_idx: int,
    n_trades: int,
    sharpe: float,
    win_rate: float,
    *,
    cohort: str,
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
        "selected_cohort": cohort if split_idx >= 0 else "aggregate",
        "n_trades": n_trades,
        "sharpe": sharpe,
        "sortino": sharpe + 0.2,
        "win_rate": win_rate,
        "max_dd": -0.02,
        "total_return": 0.03,
        "fallback_used": False,
    }
