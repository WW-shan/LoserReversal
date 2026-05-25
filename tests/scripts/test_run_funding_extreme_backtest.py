from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from infra.backtest.risk import sharpe_ratio
from scripts import run_funding_extreme_backtest as backtest


def test_runs_single_config_produces_per_token_and_aggregate_rows(mocker):
    funding_history, prices = _two_token_fixture()
    mocker.patch.object(backtest, "load_funding_history", return_value=funding_history)
    mocker.patch.object(backtest, "load_prices", return_value=prices)

    frame = backtest.run_single_config(
        backtest.BacktestConfig(
            z_threshold=2.0,
            hold_hours=4,
            lookback_days=2,
            taker_fee=0.0,
            slippage=0.0,
        )
    )

    assert set(frame["token"]) == {"BTC", "ETH", "AGGREGATE"}
    assert len(frame) == 3
    assert frame.loc[frame["token"] == "AGGREGATE", "n_trades"].item() == 6
    assert frame["z_threshold"].tolist() == [2.0, 2.0, 2.0]
    assert frame["hold_hours"].tolist() == [4, 4, 4]
    assert frame["lookback_days"].tolist() == [2, 2, 2]


def test_aggregate_sharpe_consistent_with_per_token_pnl(mocker):
    funding_history, prices = _two_token_fixture()
    mocker.patch.object(backtest, "load_funding_history", return_value=funding_history)
    mocker.patch.object(backtest, "load_prices", return_value=prices)

    frame = backtest.run_single_config(
        backtest.BacktestConfig(
            z_threshold=2.0,
            hold_hours=4,
            lookback_days=2,
            taker_fee=0.0,
            slippage=0.0,
        )
    )

    aggregate = frame.loc[frame["token"] == "AGGREGATE"].iloc[0]
    expected = _manual_aggregate_sharpe(
        funding_history["BTC"],
        prices["BTC"],
        entry_positions=[180, 196, 212],
        hold_hours=4,
    )

    assert aggregate["sharpe"] == pytest.approx(expected, rel=1e-9, abs=1e-9)


def test_no_trades_returns_nan_sharpe_not_crash(mocker):
    funding_history, prices = _flat_fixture()
    mocker.patch.object(backtest, "load_funding_history", return_value=funding_history)
    mocker.patch.object(backtest, "load_prices", return_value=prices)

    frame = backtest.run_single_config(
        backtest.BacktestConfig(
            z_threshold=3.0,
            hold_hours=4,
            lookback_days=2,
            taker_fee=0.0,
            slippage=0.0,
        )
    )

    assert frame["n_trades"].sum() == 0
    assert frame["sharpe"].isna().all()
    assert frame["annualized_return"].isna().all()
    assert frame.loc[frame["token"] == "AGGREGATE", "max_dd"].item() == 0.0


def test_fees_and_slippage_applied_correctly(mocker):
    funding_history, prices = _single_trade_fixture()
    mocker.patch.object(backtest, "load_funding_history", return_value=funding_history)
    mocker.patch.object(backtest, "load_prices", return_value=prices)

    zero_cost = backtest.run_single_config(
        backtest.BacktestConfig(
            z_threshold=2.0,
            hold_hours=4,
            lookback_days=2,
            taker_fee=0.0,
            slippage=0.0,
        )
    )
    costed = backtest.run_single_config(
        backtest.BacktestConfig(
            z_threshold=2.0,
            hold_hours=4,
            lookback_days=2,
            taker_fee=0.001,
            slippage=0.002,
        )
    )

    delta = zero_cost.loc[zero_cost["token"] == "BTC", "avg_trade_return"].item() - costed.loc[
        costed["token"] == "BTC", "avg_trade_return"
    ].item()
    assert delta == pytest.approx(0.006)


def test_funding_payment_aligned_to_hold_window(mocker):
    funding_history, prices = _single_trade_fixture(
        funding_rates=[0.0001] * 180 + [0.0010] * 5 + [0.0001] * 35
    )
    mocker.patch.object(backtest, "load_funding_history", return_value=funding_history)
    mocker.patch.object(backtest, "load_prices", return_value=prices)

    frame = backtest.run_single_config(
        backtest.BacktestConfig(
            z_threshold=2.0,
            hold_hours=4,
            lookback_days=2,
            taker_fee=0.0,
            slippage=0.0,
        )
    )

    token_row = frame.loc[frame["token"] == "BTC"].iloc[0]
    assert token_row["total_funding_paid"] == pytest.approx(-0.004)


def test_cli_writes_parquet_at_expected_path(mocker, tmp_path: Path):
    funding_history, prices = _single_trade_fixture()
    out = tmp_path / "funding_extreme_backtest.parquet"
    mocker.patch.object(backtest, "load_funding_history", return_value=funding_history)
    mocker.patch.object(backtest, "load_prices", return_value=prices)

    assert (
        backtest.main(
            [
                "--funding-dir",
                str(tmp_path / "funding"),
                "--candles-dir",
                str(tmp_path / "candles"),
                "--out",
                str(out),
                "--z-threshold",
                "2.0",
                "--hold-hours",
                "4",
                "--lookback-days",
                "2",
                "--taker-fee",
                "0",
                "--slippage",
                "0",
            ]
        )
        == 0
    )

    assert out.exists()
    frame = pd.read_parquet(out)
    assert set(frame["token"]) == {"BTC", "AGGREGATE"}


def test_cli_skips_tokens_with_insufficient_history(mocker, tmp_path: Path, caplog):
    funding_history, prices = _single_trade_fixture()
    funding_history["SHORT"] = funding_history["BTC"].iloc[:12].copy()
    prices["SHORT"] = prices["BTC"].iloc[:12].copy()
    mocker.patch.object(backtest, "load_funding_history", return_value=funding_history)
    mocker.patch.object(backtest, "load_prices", return_value=prices)
    out = tmp_path / "funding_extreme_backtest.parquet"

    assert (
        backtest.main(
            [
                "--funding-dir",
                str(tmp_path / "funding"),
                "--candles-dir",
                str(tmp_path / "candles"),
                "--out",
                str(out),
                "--z-threshold",
                "2.0",
                "--hold-hours",
                "4",
                "--lookback-days",
                "2",
            ]
        )
        == 0
    )

    assert "skipping SHORT" in caplog.text
    frame = pd.read_parquet(out)
    assert set(frame["token"]) == {"BTC", "AGGREGATE"}


def _two_token_fixture() -> tuple[dict[str, pd.DataFrame], dict[str, pd.Series]]:
    funding = _funding_frame(
        rates=[0.0001] * 180 + [0.0010] * 4 + [0.0001] * 12 + [0.0010] * 4 + [0.0001] * 12
        + [0.0010] * 4 + [0.0001] * 24,
    )
    prices = _price_frame()
    return {"BTC": funding, "ETH": funding.copy()}, {"BTC": prices, "ETH": prices.copy()}


def _flat_fixture() -> tuple[dict[str, pd.DataFrame], dict[str, pd.Series]]:
    funding = _funding_frame(rates=[0.0001] * 240)
    prices = _price_frame()
    return {"BTC": funding, "ETH": funding.copy()}, {"BTC": prices, "ETH": prices.copy()}


def _single_trade_fixture(
    *, funding_rates: list[float] | None = None
) -> tuple[dict[str, pd.DataFrame], dict[str, pd.Series]]:
    rates = funding_rates or ([0.0001] * 180 + [0.0010] * 5 + [0.0001] * 55)
    funding = _funding_frame(rates=rates)
    prices = _price_frame()
    return {"BTC": funding}, {"BTC": prices}


def _funding_frame(rates: list[float]) -> pd.DataFrame:
    index = pd.date_range("2026-01-01T00:00:00Z", periods=len(rates), freq="1h", tz="UTC")
    return pd.DataFrame(
        {"funding_rate": rates, "premium": np.linspace(0.0, 0.001, len(rates))},
        index=pd.DatetimeIndex(index, name="timestamp"),
    )


def _price_frame() -> pd.Series:
    index = pd.date_range("2026-01-01T00:00:00Z", periods=240, freq="1h", tz="UTC")
    base = 100.0 + np.arange(len(index), dtype="float64") * 0.2
    oscillation = np.sin(np.arange(len(index), dtype="float64") / 8.0) * 1.5
    return pd.Series(base + oscillation, index=index, dtype="float64", name="close")


def _manual_aggregate_sharpe(
    funding: pd.DataFrame,
    prices: pd.Series,
    *,
    entry_positions: list[int],
    hold_hours: int,
    taker_fee: float = 0.0,
    slippage: float = 0.0,
) -> float:
    index = prices.index
    trade_returns: list[tuple[pd.Timestamp, float]] = []
    for entry_position in entry_positions:
        entry_time = index[entry_position]
        exit_time = index[entry_position + hold_hours]
        price_return = prices.iloc[entry_position] / prices.iloc[entry_position + hold_hours] - 1.0
        funding_paid = float(funding.loc[(funding.index > entry_time) & (funding.index <= exit_time), "funding_rate"].sum())
        trade_returns.append(
            (
                exit_time,
                price_return - (2.0 * taker_fee) - (2.0 * slippage) - (-1 * funding_paid),
            )
        )

    equity = pd.Series(1.0, index=index, dtype="float64")
    for exit_time, trade_return in trade_returns:
        equity.loc[exit_time:] *= 1.0 + trade_return

    returns = equity.pct_change().dropna()
    return sharpe_ratio(returns, periods_per_year=8760)
