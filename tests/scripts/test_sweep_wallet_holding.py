from __future__ import annotations

import pytest

from scripts import sweep_wallet_holding as sweep
from scripts.run_wallet_reverse_backtest import WalletReverseBacktestConfig


def _backtest_result(
    *,
    n_trades: int,
    sharpe: float,
    trade_level_ir: float,
) -> dict[str, object]:
    return {
        "portfolio_stats": {
            "n_trades": n_trades,
            "sharpe": sharpe,
            "daily_sharpe": sharpe / 2.0,
            "trade_level_ir": trade_level_ir,
            "sortino": sharpe - 0.5,
            "max_dd": -0.10,
            "total_return": 0.05,
            "win_rate": 0.55,
        }
    }


def test_four_holding_hour_combos_run_without_crash(mocker, tmp_path):
    calls: list[float] = []

    def run_backtest(config: WalletReverseBacktestConfig) -> dict[str, object]:
        calls.append(config.holding_hours)
        return _backtest_result(
            n_trades=100 + len(calls),
            sharpe=float(len(calls)),
            trade_level_ir=float(len(calls)) + 0.25,
        )

    mocker.patch.object(sweep, "run_wallet_reverse_backtest", side_effect=run_backtest)

    result = sweep.run_sweep(WalletReverseBacktestConfig(report=tmp_path / "sweep.md"))

    assert calls == [1.0, 4.0, 12.0, 24.0]
    assert result["total_combinations"] == 4
    assert len(result["rows"]) == 4
    assert all("trade_level_ir" in row for row in result["rows"])
    report = (tmp_path / "sweep.md").read_text()
    assert "| holding | n_trades | trade_level_ir |" in report


def test_sweep_ranking_keeps_eligible_rows_before_ineligible_high_sharpe(mocker):
    by_holding = {
        1.0: _backtest_result(n_trades=50, sharpe=99.0, trade_level_ir=99.0),
        4.0: _backtest_result(n_trades=100, sharpe=1.0, trade_level_ir=1.0),
        12.0: _backtest_result(n_trades=120, sharpe=0.5, trade_level_ir=0.5),
        24.0: _backtest_result(n_trades=80, sharpe=120.0, trade_level_ir=120.0),
    }

    mocker.patch.object(
        sweep,
        "run_wallet_reverse_backtest",
        side_effect=lambda config: by_holding[config.holding_hours],
    )

    result = sweep.run_sweep(WalletReverseBacktestConfig(report=None))

    assert result["rows"][0]["holding"] == 4.0
    assert result["rows"][0]["eligible"] is True
    assert result["rows"][1]["holding"] == 12.0
    assert result["rows"][1]["eligible"] is True
    assert result["rows"][2]["eligible"] is False
    assert result["rows"][3]["eligible"] is False


def test_cli_flag_validation_rejects_negative_init_cash(mocker, capsys):
    mocker.patch("sys.argv", ["sweep_wallet_holding.py", "--init-cash", "-1"])

    with pytest.raises(SystemExit):
        sweep._parse_args()

    assert "--init-cash must be greater than 0" in capsys.readouterr().err
