from __future__ import annotations

import pytest
import pandas as pd

from infra.backtest.engine import periods_per_year
from infra.backtest.risk import sharpe_ratio
from signals.unlock_grid import GridCell
from signals.unlock_v2 import unlock_short_30d
from signals.unlock_walkforward import run_per_signal_walkforward


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


def test_record_trades_disabled_by_default_no_change_in_aggregate_output(monkeypatch):
    splits = [_split("2026-01-01", "2026-02-01", "2026-02-01", "2026-03-01")]

    monkeypatch.setattr(
        "signals.unlock_walkforward.select_best_config",
        lambda *args, **kwargs: _cell("v1"),
    )
    monkeypatch.setattr(
        "signals.unlock_walkforward.run_cell",
        lambda events, prices, coverage, cell, **kwargs: _stats(cell, n_trades=2, sharpe=1.2),
    )

    default_result = run_per_signal_walkforward(
        _events(),
        {"ARB": _prices()},
        _coverage(),
        splits,
        ["v1"],
        grid_df=_grid_df("v1"),
    )
    explicit_result = run_per_signal_walkforward(
        _events(),
        {"ARB": _prices()},
        _coverage(),
        splits,
        ["v1"],
        grid_df=_grid_df("v1"),
        record_trades=False,
    )

    assert isinstance(default_result, pd.DataFrame)
    pd.testing.assert_frame_equal(default_result, explicit_result)


def test_record_trades_enabled_returns_trades_dataframe(monkeypatch):
    splits = [_split("2026-01-01", "2026-02-01", "2026-02-01", "2026-03-01")]
    trades = [_trade("2026-02-05", "2026-02-10", -0.04)]

    monkeypatch.setattr(
        "signals.unlock_walkforward.select_best_config",
        lambda *args, **kwargs: _cell("v2"),
    )
    monkeypatch.setattr(
        "signals.unlock_walkforward.run_cell",
        lambda events, prices, coverage, cell, **kwargs: _stats(
            cell,
            n_trades=1,
            sharpe=0.5,
            trades=trades,
        ),
    )

    summary, trade_frame = run_per_signal_walkforward(
        _events(),
        {"ARB": _prices()},
        _coverage(),
        splits,
        ["v2"],
        grid_df=_grid_df("v2"),
        record_trades=True,
    )

    assert isinstance(summary, pd.DataFrame)
    assert isinstance(trade_frame, pd.DataFrame)
    assert trade_frame.columns.tolist() == TRADE_COLUMNS
    assert trade_frame.iloc[0]["signal"] == "v2"
    assert trade_frame.iloc[0]["split_idx"] == 0


def test_trades_row_count_matches_per_split_n_trades(monkeypatch):
    splits = [
        _split("2026-01-01", "2026-02-01", "2026-02-01", "2026-03-01"),
        _split("2026-01-01", "2026-03-01", "2026-03-01", "2026-04-01"),
    ]
    split_trades = [
        [_trade("2026-02-05", "2026-02-10", 0.04), _trade("2026-02-15", "2026-02-20", -0.01)],
        [_trade("2026-03-05", "2026-03-10", 0.02)],
    ]

    monkeypatch.setattr(
        "signals.unlock_walkforward.select_best_config",
        lambda *args, **kwargs: _cell("v2"),
    )

    def fake_run_cell(events, prices, coverage, cell, **kwargs):
        trades = split_trades.pop(0)
        return _stats(cell, n_trades=len(trades), sharpe=0.4, trades=trades)

    monkeypatch.setattr("signals.unlock_walkforward.run_cell", fake_run_cell)

    summary, trade_frame = run_per_signal_walkforward(
        _events(),
        {"ARB": _prices()},
        _coverage(),
        splits,
        ["v2"],
        grid_df=_grid_df("v2"),
        record_trades=True,
    )

    split_rows = summary.loc[summary["split_idx"].ge(0)]
    counts = trade_frame.groupby(["signal", "split_idx"], sort=False).size()
    for row in split_rows.to_dict("records"):
        assert counts[(row["signal"], row["split_idx"])] == row["n_trades"]


def test_trades_sharpe_reconstruction_matches_aggregate(monkeypatch):
    split_returns = [[0.04, -0.01, 0.03], [0.02, -0.02, 0.01]]
    splits = [
        _split("2026-01-01", "2026-02-01", "2026-02-01", "2026-03-01"),
        _split("2026-01-01", "2026-03-01", "2026-03-01", "2026-04-01"),
    ]

    monkeypatch.setattr(
        "signals.unlock_walkforward.select_best_config",
        lambda *args, **kwargs: _cell("v2"),
    )

    def fake_run_cell(events, prices, coverage, cell, **kwargs):
        returns = split_returns.pop(0)
        trades = [
            _trade(f"2026-02-{idx + 2:02d}", f"2026-02-{idx + 3:02d}", value)
            for idx, value in enumerate(returns)
        ]
        sharpe = sharpe_ratio(pd.Series(returns), periods_per_year("1D"))
        return _stats(cell, n_trades=len(trades), sharpe=sharpe, trades=trades)

    monkeypatch.setattr("signals.unlock_walkforward.run_cell", fake_run_cell)

    summary, trade_frame = run_per_signal_walkforward(
        _events(),
        {"ARB": _prices()},
        _coverage(),
        splits,
        ["v2"],
        grid_df=_grid_df("v2"),
        record_trades=True,
    )

    reconstructed = (
        trade_frame.groupby(["signal", "split_idx"], sort=False)["return"]
        .apply(lambda values: sharpe_ratio(values, periods_per_year("1D")))
        .mean()
    )
    aggregate = summary.loc[summary["split_idx"].eq(-1), "sharpe"].iloc[0]
    assert reconstructed == pytest.approx(aggregate, abs=1e-4)


def test_trades_directions_consistent_with_signal_type(monkeypatch):
    summary, trade_frame = _run_actual_v2_trade(monkeypatch)

    assert summary.loc[summary["split_idx"].eq(0), "n_trades"].iloc[0] == 1
    assert trade_frame["direction"].tolist() == [-1]


def test_trades_entry_exit_timestamps_within_split_window(monkeypatch):
    summary, trade_frame = _run_actual_v2_trade(monkeypatch)
    split_row = summary.loc[summary["split_idx"].eq(0)].iloc[0]
    trade = trade_frame.iloc[0]

    assert split_row["test_start"] <= trade["entry_ts"] < split_row["test_end"]
    assert split_row["test_start"] <= trade["exit_ts"] < split_row["test_end"]


def test_trades_hold_days_positive(monkeypatch):
    _, trade_frame = _run_actual_v2_trade(monkeypatch)

    assert trade_frame["hold_days"].gt(0).all()


def test_trades_parquet_roundtrip(tmp_path):
    trade_frame = pd.DataFrame(
        [
            {
                "signal": "v2",
                "split_idx": 0,
                "token": "ARB",
                "entry_ts": pd.Timestamp("2026-02-05T00:00:00Z"),
                "exit_ts": pd.Timestamp("2026-02-10T00:00:00Z"),
                "direction": -1,
                "return": 0.03,
                "hold_days": 5.0,
                "win": True,
            }
        ]
    )
    path = tmp_path / "trades.parquet"

    trade_frame.to_parquet(path)
    result = pd.read_parquet(path)

    assert result.columns.tolist() == TRADE_COLUMNS
    assert str(result["entry_ts"].dt.tz) == "UTC"
    assert result["direction"].dtype == "int64"
    assert result["win"].dtype == "bool"


def _run_actual_v2_trade(monkeypatch) -> tuple[pd.DataFrame, pd.DataFrame]:
    splits = [_split("2026-01-01", "2026-02-01", "2026-02-01", "2026-04-01")]
    cell = GridCell(
        code="v2",
        min_unlock_pct=0.02,
        cohort_name="all",
        signal_fn=unlock_short_30d,
        direction="short",
        category_filter=None,
    )

    monkeypatch.setattr(
        "signals.unlock_walkforward.select_best_config",
        lambda *args, **kwargs: cell,
    )

    return run_per_signal_walkforward(
        _events(unlock_date="2026-03-10"),
        {"ARB": _prices(start="2026-01-01", periods=120)},
        _coverage(unlock_date="2026-03-10"),
        splits,
        ["v2"],
        grid_df=_grid_df("v2"),
        record_trades=True,
    )


def _events(unlock_date: str = "2026-02-15") -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "token": "ARB",
                "coingecko_id": "arb",
                "unlock_date": pd.Timestamp(unlock_date, tz="UTC"),
                "unlock_pct": 0.05,
                "category": "insiders",
                "has_hl_perp": True,
                "vesting_type": "cliff",
            }
        ]
    )


def _coverage(unlock_date: str = "2026-02-15") -> pd.DataFrame:
    return pd.DataFrame(
        [{"token": "ARB", "unlock_date": unlock_date, "coverage_status": "ok"}]
    )


def _prices(start: str = "2026-01-01", periods: int = 120) -> pd.Series:
    index = pd.date_range(start, periods=periods, freq="1D", tz="UTC")
    values = [100.0 + idx for idx in range(periods)]
    return pd.Series(values, index=index, name="close", dtype="float64")


def _grid_df(signal: str) -> pd.DataFrame:
    return pd.DataFrame([{"signal": signal, "min_unlock_pct": 0.02, "cohort": "all"}])


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


def _cell(signal: str) -> GridCell:
    return GridCell(
        code=signal,
        min_unlock_pct=0.02,
        cohort_name="all",
        signal_fn=lambda *args, **kwargs: {},
        direction="short",
        category_filter=None,
    )


def _stats(
    cell: GridCell,
    *,
    n_trades: int,
    sharpe: float,
    trades: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    row: dict[str, object] = {
        "signal": cell.code,
        "min_unlock_pct": cell.min_unlock_pct,
        "cohort": cell.cohort_name,
        "n_trades": n_trades,
        "win_rate": 0.5,
        "sharpe": sharpe,
        "sortino": sharpe + 0.2,
        "max_dd": -0.02,
        "total_return": 0.03,
        "mean_pnl": 1.0,
        "median_pnl": 1.0,
    }
    if trades is not None:
        row["_trades"] = trades
    return row


def _trade(entry_ts: str, exit_ts: str, trade_return: float) -> dict[str, object]:
    entry = pd.Timestamp(entry_ts, tz="UTC")
    exit_ = pd.Timestamp(exit_ts, tz="UTC")
    return {
        "token": "ARB",
        "entry_ts": entry,
        "exit_ts": exit_,
        "direction": -1,
        "return": trade_return,
        "hold_days": (exit_ - entry).total_seconds() / 86400.0,
        "win": trade_return > 0,
    }
