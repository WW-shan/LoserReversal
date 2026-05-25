from __future__ import annotations

import pandas as pd

from scripts import run_unlock_walkforward_v15 as runner


TRADE_COLUMNS = [
    "signal",
    "split_idx",
    "token",
    "entry_ts",
    "exit_ts",
    "direction",
    "return",
    "hold_days",
    "win",
]


def test_cli_record_trades_flag_writes_parquet(monkeypatch, tmp_path):
    out = tmp_path / "phase1_5_walkforward.parquet"
    report = tmp_path / "phase1_5_walkforward.md"
    trades_out = tmp_path / "phase1_5_walkforward_trades.parquet"
    split = _split("2026-01-01", "2026-07-01", "2026-07-01", "2026-10-01")
    captured_record_trades: list[bool] = []

    def fake_run_per_signal_walkforward(*args, **kwargs):
        captured_record_trades.append(kwargs["record_trades"])
        return _per_signal_frame(), _trades_frame()

    monkeypatch.setattr(runner, "read_unlocks", lambda path=None: _events(), raising=False)
    monkeypatch.setattr(runner, "load_coverage", lambda path: _coverage(), raising=False)
    monkeypatch.setattr(runner, "load_prices", lambda events, candles_dir: {"ARB": _prices()})
    monkeypatch.setattr(runner, "walk_forward_splits", lambda *args, **kwargs: [split])
    monkeypatch.setattr(runner, "run_per_signal_walkforward", fake_run_per_signal_walkforward)
    monkeypatch.setattr(runner, "compose_portfolio", lambda *args, **kwargs: _portfolio_frame())

    exit_code = runner.main(
        [
            "--out",
            str(out),
            "--report",
            str(report),
            "--record-trades",
            "--trades-out",
            str(trades_out),
        ]
    )

    assert exit_code == 0
    assert captured_record_trades == [True]
    assert trades_out.exists()
    frame = pd.read_parquet(trades_out)
    assert frame.columns.tolist() == TRADE_COLUMNS
    assert frame.iloc[0]["signal"] == "v2"
    assert frame.iloc[0]["direction"] == -1
    assert str(frame["entry_ts"].dt.tz) == "UTC"


def _events() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "token": "ARB",
                "coingecko_id": "arb",
                "unlock_date": pd.Timestamp("2026-10-01T00:00:00Z"),
                "unlock_pct": 0.05,
                "category": "insiders",
                "has_hl_perp": True,
                "vesting_type": "cliff",
            }
        ]
    )


def _coverage() -> pd.DataFrame:
    return pd.DataFrame(
        [{"token": "ARB", "unlock_date": "2026-10-01", "coverage_status": "ok"}]
    )


def _prices() -> pd.Series:
    index = pd.date_range("2026-01-01", periods=365, freq="1D", tz="UTC")
    return pd.Series(range(365), index=index, name="close", dtype="float64")


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
    return pd.DataFrame(
        [
            _row("per_signal", "v2", 0, 1, 0.6, 1.0),
            _row("per_signal", "v2", -1, 1, 0.6, 1.0),
        ]
    )


def _portfolio_frame() -> pd.DataFrame:
    return pd.DataFrame([_row("portfolio", "top_1_equal_weight", 0, 1, 0.6, 1.0)])


def _trades_frame() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "signal": "v2",
                "split_idx": 0,
                "token": "ARB",
                "entry_ts": pd.Timestamp("2026-08-01T00:00:00Z"),
                "exit_ts": pd.Timestamp("2026-08-31T00:00:00Z"),
                "direction": -1,
                "return": 0.03,
                "hold_days": 30.0,
                "win": True,
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
        "selected_cohort": "all" if split_idx >= 0 else "aggregate",
        "n_trades": n_trades,
        "sharpe": sharpe,
        "sortino": sharpe + 0.2,
        "win_rate": win_rate,
        "max_dd": -0.02,
        "total_return": 0.03,
        "fallback_used": False,
    }
