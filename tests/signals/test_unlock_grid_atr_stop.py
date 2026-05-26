"""ATR-adaptive stop_loss threading from run_cell -> BacktestConfig."""

from __future__ import annotations

import pandas as pd

from signals.unlock_grid import GridCell, run_cell


def test_run_cell_forwards_atr_mode_to_backtest_config(monkeypatch):
    """run_cell must thread stop_loss_mode + ATR knobs into BacktestConfig."""
    captured_configs: list[object] = []

    monkeypatch.setattr(
        "signals.unlock_grid.run_backtest",
        lambda close, entries, exits, config: _record_and_fake(captured_configs, config, close),
    )

    cell = GridCell(
        code="v2",
        min_unlock_pct=0.02,
        cohort_name="team",
        signal_fn=_fake_signal,
        direction="short",
        category_filter={"insiders"},
    )

    run_cell(
        _events(),
        {"ARB": _prices()},
        _coverage(),
        cell,
        init_cash=10_000.0,
        fees=0.0,
        slippage=0.0,
        stop_loss_mode="atr",
        stop_loss_atr_period=21,
        stop_loss_atr_multiplier=3.0,
        stop_loss_floor=0.05,
        stop_loss_cap=0.30,
    )

    assert len(captured_configs) == 1
    config = captured_configs[0]
    assert config.stop_loss_mode == "atr"
    assert config.stop_loss_atr_period == 21
    assert config.stop_loss_atr_multiplier == 3.0
    assert config.stop_loss_floor == 0.05
    assert config.stop_loss_cap == 0.30


def test_run_cell_defaults_to_fixed_mode_when_no_atr_kwargs(monkeypatch):
    """Without ATR kwargs, run_cell keeps the legacy fixed-mode contract.

    Callers that pass only ``stop_loss`` continue to receive the prior
    BacktestConfig with mode='fixed' and the scalar stop_loss carried through.
    """
    captured_configs: list[object] = []

    monkeypatch.setattr(
        "signals.unlock_grid.run_backtest",
        lambda close, entries, exits, config: _record_and_fake(captured_configs, config, close),
    )

    cell = GridCell(
        code="v2",
        min_unlock_pct=0.02,
        cohort_name="team",
        signal_fn=_fake_signal,
        direction="short",
        category_filter={"insiders"},
    )

    run_cell(
        _events(),
        {"ARB": _prices()},
        _coverage(),
        cell,
        init_cash=10_000.0,
        fees=0.0,
        slippage=0.0,
        stop_loss=0.10,
    )

    assert captured_configs[0].stop_loss_mode == "fixed"
    assert captured_configs[0].stop_loss == 0.10


def _events() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "token": "ARB",
                "coingecko_id": "arb",
                "unlock_date": "2026-01-05",
                "unlock_pct": 0.05,
                "category": "insiders",
                "has_hl_perp": True,
                "vesting_type": "cliff",
            }
        ]
    )


def _coverage() -> pd.DataFrame:
    return pd.DataFrame(
        [{"token": "ARB", "unlock_date": "2026-01-05", "coverage_status": "ok"}]
    )


def _prices() -> pd.Series:
    index = pd.date_range("2026-01-01", periods=10, freq="1D", tz="UTC")
    return pd.Series(
        [100.0 + i for i in range(10)], index=index, name="close", dtype="float64"
    )


def _fake_signal(events, prices, min_unlock_pct, coverage):
    assert min_unlock_pct == 0.02
    assert coverage is not None
    index = prices["ARB"].index
    entries = pd.Series(False, index=index, dtype=bool)
    exits = pd.Series(False, index=index, dtype=bool)
    entries.iloc[0] = True
    exits.iloc[-1] = True
    return {"ARB": (entries, exits)}


def _record_and_fake(captured_configs: list[object], config: object, close: pd.Series) -> object:
    captured_configs.append(config)

    class FakeTrades:
        records_readable = pd.DataFrame({"PnL": [12.5]})

        @staticmethod
        def count() -> int:
            return 1

        @staticmethod
        def win_rate() -> float:
            return 1.0

    class FakePortfolio:
        trades = FakeTrades()

    equity = pd.Series([10_000.0, 10_125.0], index=close.index[:2], name="equity")
    return type(
        "FakeBacktestResult",
        (),
        {
            "portfolio": FakePortfolio(),
            "stats": {
                "n_trades": 1,
                "win_rate": 1.0,
                "sharpe": 1.5,
                "sortino": 2.0,
                "max_dd": -0.01,
                "total_return": 0.0125,
            },
            "equity": equity,
        },
    )()
