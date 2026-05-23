from __future__ import annotations

import pandas as pd

from scripts import run_unlock_walkforward_v15 as runner


def test_config_defaults_traverse_full_data_span():
    config = runner.WalkForwardV15Config()

    assert config.n_splits == 5
    assert config.min_train_days == 270
    assert config.test_days == 180
    assert config.min_train_days + config.n_splits * config.test_days == 1170


def test_cli_defaults_match_calibrated_walkforward_params(monkeypatch):
    captured_configs: list[runner.WalkForwardV15Config] = []

    def fake_run_walkforward(config):
        captured_configs.append(config)
        return {}

    monkeypatch.setattr(runner, "run_walkforward", fake_run_walkforward)

    exit_code = runner.main([])

    assert exit_code == 0
    assert len(captured_configs) == 1
    config = captured_configs[0]
    assert config.n_splits == 5
    assert config.min_train_days == 270
    assert config.test_days == 180


def test_cli_smoke(monkeypatch, tmp_path, capsys):
    out = tmp_path / "phase1_5_walkforward.parquet"
    report = tmp_path / "phase1_5_walkforward.md"
    split = _split("2026-01-01", "2026-07-01", "2026-07-01", "2026-10-01")

    monkeypatch.setattr(runner, "read_unlocks", lambda path=None: _events(), raising=False)
    monkeypatch.setattr(runner, "load_coverage", lambda path: _coverage(), raising=False)
    monkeypatch.setattr(runner, "load_prices", lambda events, candles_dir: {"ARB": _prices()})
    monkeypatch.setattr(
        runner,
        "walk_forward_splits",
        lambda *args, **kwargs: [split],
    )
    monkeypatch.setattr(
        runner,
        "run_per_signal_walkforward",
        lambda *args, **kwargs: _per_signal_frame(),
    )
    monkeypatch.setattr(
        runner,
        "compose_portfolio",
        lambda *args, **kwargs: _portfolio_frame(),
    )

    exit_code = runner.main(
        [
            "--out",
            str(out),
            "--report",
            str(report),
            "--n-splits",
            "1",
            "--min-train-days",
            "180",
            "--test-days",
            "90",
            "--top-k",
            "2",
            "--fees",
            "0",
            "--slippage",
            "0",
        ]
    )

    assert exit_code == 0
    frame = pd.read_parquet(out)
    assert set(frame["kind"]) == {"per_signal", "portfolio"}
    text = report.read_text(encoding="utf-8")
    assert "## Methodology" in text
    assert "## Per-Signal Walk-Forward" in text
    assert "## Portfolio Walk-Forward" in text
    assert "## Verdict-Ready Summary" in text
    assert "## Best-Signal Snapshot" in text
    assert "wrote parquet" in capsys.readouterr().out


def test_report_contains_verdict_ready_summary(tmp_path):
    report = tmp_path / "phase1_5_walkforward.md"

    runner._write_report(
        report,
        pd.concat([_per_signal_frame(), _portfolio_frame()], ignore_index=True),
        _grid_df(),
        runner.WalkForwardV15Config(report=report),
        effective_test_days=180,
        fallback_used=False,
    )

    text = report.read_text(encoding="utf-8")
    assert "## Verdict-Ready Summary" in text
    assert "Best signal by OOS Sharpe: v1, sharpe=1.20, n_trades=10" in text
    assert "No-train-signal splits: 0" in text
    assert "If n_trades ≥ 50 AND sharpe ≥ 1.0 → GREEN" in text
    assert "If n_trades ≥ 30 AND sharpe ∈ [0.3, 1.0) → YELLOW" in text
    assert "Else → RED" in text
    assert "Actual classification: RED" in text


def test_verdict_ready_summary_counts_no_train_signal_rows():
    frame = pd.concat([_per_signal_frame(), _portfolio_frame()], ignore_index=True)
    mask = frame["kind"].eq("per_signal") & frame["split_idx"].eq(0) & frame["signal"].eq("v2")
    frame.loc[mask, "selected_min_pct"] = float("nan")
    frame.loc[mask, "selected_cohort"] = "no_train_signal"
    frame.loc[mask, "n_trades"] = 0
    frame.loc[mask, "sharpe"] = 0.0

    lines = runner._verdict_ready_summary(frame)

    assert "No-train-signal splits: 1" in lines


def test_verdict_classification_thresholds():
    assert runner._classify_verdict(n_trades=50, sharpe=1.0) == "GREEN"
    assert runner._classify_verdict(n_trades=30, sharpe=0.3) == "YELLOW"
    assert runner._classify_verdict(n_trades=8, sharpe=0.57) == "RED"
    assert runner._classify_verdict(n_trades=49, sharpe=1.2) == "RED"


def test_run_walkforward_logs_span_coverage(monkeypatch, tmp_path, capsys):
    _patch_run_walkforward_dependencies(monkeypatch, tmp_path)
    config = _config(tmp_path)

    runner.run_walkforward(config)

    assert (
        "walk-forward span: train_days=270 + n_splits×test_days = 1170 days; "
        "data span = 1232 days; coverage = 95.0%"
    ) in capsys.readouterr().err


def test_run_walkforward_warns_when_span_coverage_below_80(monkeypatch, tmp_path, capsys):
    _patch_run_walkforward_dependencies(monkeypatch, tmp_path)
    config = _config(tmp_path, n_splits=1, min_train_days=180, test_days=90)

    runner.run_walkforward(config)

    err = capsys.readouterr().err
    assert "coverage = 21.9%" in err
    assert (
        "[WARNING] walk-forward coverage below 80%; recommended params: "
        "--n-splits 5 --min-train-days 270 --test-days 180"
    ) in err


def test_cli_falls_back_to_shorter_test_days_when_range_too_short(
    monkeypatch,
    tmp_path,
    capsys,
):
    out = tmp_path / "phase1_5_walkforward.parquet"
    report = tmp_path / "phase1_5_walkforward.md"
    calls: list[int] = []
    captured_fallback: list[bool] = []
    split = _split("2026-01-01", "2026-07-01", "2026-07-01", "2026-09-01")

    def fake_walk_forward_splits(*args, **kwargs):
        calls.append(kwargs["test_days"])
        if kwargs["test_days"] == 90:
            raise ValueError("time range too short for requested splits")
        return [split]

    def fake_run_per_signal_walkforward(*args, **kwargs):
        captured_fallback.append(kwargs["fallback_used"])
        return _per_signal_frame(fallback_used=kwargs["fallback_used"])

    monkeypatch.setattr(runner, "read_unlocks", lambda path=None: _events(), raising=False)
    monkeypatch.setattr(runner, "load_coverage", lambda path: _coverage(), raising=False)
    monkeypatch.setattr(runner, "load_prices", lambda events, candles_dir: {"ARB": _prices()})
    monkeypatch.setattr(runner, "walk_forward_splits", fake_walk_forward_splits)
    monkeypatch.setattr(runner, "run_per_signal_walkforward", fake_run_per_signal_walkforward)
    monkeypatch.setattr(runner, "compose_portfolio", lambda *args, **kwargs: _portfolio_frame(True))

    exit_code = runner.main(
        [
            "--out",
            str(out),
            "--report",
            str(report),
            "--n-splits",
            "1",
            "--min-train-days",
            "180",
            "--test-days",
            "90",
        ]
    )

    assert exit_code == 0
    assert calls == [90, 60]
    assert captured_fallback == [True]
    assert pd.read_parquet(out)["fallback_used"].all()
    assert "using test_days=60" in capsys.readouterr().err


def _patch_run_walkforward_dependencies(monkeypatch, tmp_path) -> None:
    split = _split("2025-01-01", "2025-10-01", "2025-10-01", "2026-04-01")

    monkeypatch.setattr(runner, "read_unlocks", lambda path=None: _span_events(), raising=False)
    monkeypatch.setattr(runner, "load_coverage", lambda path: _coverage(), raising=False)
    monkeypatch.setattr(runner, "load_prices", lambda events, candles_dir: {"ARB": _prices()})
    monkeypatch.setattr(runner, "walk_forward_splits", lambda *args, **kwargs: [split])
    monkeypatch.setattr(runner, "run_per_signal_walkforward", lambda *args, **kwargs: _per_signal_frame())
    monkeypatch.setattr(runner, "compose_portfolio", lambda *args, **kwargs: _portfolio_frame())
    _grid_df().to_parquet(tmp_path / "grid.parquet")


def _config(tmp_path, **overrides) -> runner.WalkForwardV15Config:
    values = {
        "out": tmp_path / "phase1_5_walkforward.parquet",
        "report": tmp_path / "phase1_5_walkforward.md",
        "grid_path": tmp_path / "grid.parquet",
    }
    values.update(overrides)
    return runner.WalkForwardV15Config(**values)


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


def _span_events() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "token": "ARB",
                "coingecko_id": "arb",
                "unlock_date": pd.Timestamp("2023-01-07T00:00:00Z"),
                "unlock_pct": 0.05,
                "category": "insiders",
                "has_hl_perp": True,
                "vesting_type": "cliff",
            },
            {
                "token": "ARB",
                "coingecko_id": "arb",
                "unlock_date": pd.Timestamp("2026-05-23T00:00:00Z"),
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


def _per_signal_frame(fallback_used: bool = False) -> pd.DataFrame:
    rows = [
        _row("per_signal", "v1", 0, 10, 1.2, 0.60, fallback_used),
        _row("per_signal", "v2", 0, 8, 0.8, 0.50, fallback_used),
        _row("per_signal", "v1", -1, 10, 1.2, 0.60, fallback_used),
        _row("per_signal", "v2", -1, 8, 0.8, 0.50, fallback_used),
    ]
    return pd.DataFrame(rows)


def _portfolio_frame(fallback_used: bool = False) -> pd.DataFrame:
    return pd.DataFrame(
        [
            _row("portfolio", "top_2_equal_weight", 0, 18, 1.0, 0.55, fallback_used),
            _row("portfolio", "top_2_equal_weight", -1, 18, 1.0, 0.55, fallback_used),
        ]
    )


def _grid_df() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "signal": "v1",
                "min_unlock_pct": 0.02,
                "cohort": "team",
                "n_trades": 30,
                "sharpe": 1.1,
            }
        ]
    )


def _row(
    kind: str,
    signal: str,
    split_idx: int,
    n_trades: int,
    sharpe: float,
    win_rate: float,
    fallback_used: bool,
) -> dict:
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
        "fallback_used": fallback_used,
    }
