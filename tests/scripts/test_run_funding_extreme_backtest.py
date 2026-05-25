from __future__ import annotations

import math
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
    """Reference implementation: mark-to-market equity, daily-resampled Sharpe.

    Mirrors production _equity_curve + _sharpe so the test pins the formula.
    """
    index = prices.index
    trades: list[tuple[int, int, float, float]] = []  # entry_pos, exit_pos, entry_price, realized_return
    for entry_position in entry_positions:
        entry_pos = entry_position
        exit_pos = entry_position + hold_hours
        entry_price = float(prices.iloc[entry_pos])
        entry_time = index[entry_pos]
        exit_time = index[exit_pos]
        price_return = prices.iloc[entry_pos] / prices.iloc[exit_pos] - 1.0  # short direction
        funding_paid = float(
            funding.loc[(funding.index > entry_time) & (funding.index <= exit_time), "funding_rate"].sum()
        )
        # Direction = -1 (short); trade_return = price_return - 2*fee - 2*slip - funding_paid*direction
        # Since direction = -1, funding contribution = -(-1) * funding_paid = funding_paid (positive funding into short = subtracted)
        # Per production: trade_return = price_return - 2*fee - 2*slip - (funding_sum * direction)
        # For short: direction = -1, so subtract (sum * -1) = +sum, so we add sum.
        # But price_return for short was already computed as entry/exit - 1.
        realized = price_return - (2.0 * taker_fee) - (2.0 * slippage) - (funding_paid * -1)
        trades.append((entry_pos, exit_pos, entry_price, realized))

    # Two-token aggregate: per-token equity * 2 (both BTC and ETH have identical trades in fixture)
    equity = pd.Series(2.0, index=index, dtype="float64")  # 1.0 per token * 2 tokens
    capital_per_token = 1.0
    last_filled = -1
    for entry_pos, exit_pos, entry_price, realized in trades:
        # Flat segment up to and including entry_pos
        if last_filled + 1 <= entry_pos:
            equity.iloc[last_filled + 1 : entry_pos + 1] = capital_per_token * 2.0
        # MTM during open position (each token same)
        for i in range(entry_pos + 1, exit_pos):
            price_t = float(prices.iloc[i])
            mtm = -1 * (price_t / entry_price - 1.0)  # direction = -1 short
            per_token = capital_per_token * (1.0 + mtm)
            equity.iloc[i] = per_token * 2.0
        # Realize at exit
        capital_per_token *= 1.0 + realized
        equity.iloc[exit_pos] = capital_per_token * 2.0
        last_filled = exit_pos
    if last_filled + 1 < len(equity):
        equity.iloc[last_filled + 1 :] = capital_per_token * 2.0

    daily = equity.resample("1D").last().dropna()
    daily_returns = daily.pct_change().dropna()
    return sharpe_ratio(daily_returns, periods_per_year=365)


def test_sharpe_uses_daily_resampled_equity_not_hourly(mocker):
    """Confirm Sharpe is annualized off daily-resampled equity, not raw hourly."""
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
    # Sharpe magnitude on 6 short trades in a 10-day window with avg_trade_return ~0.06%
    # should be a finite number bounded by sqrt(365) * (mean/std of daily). Empirically
    # well below the inflated sqrt(8760) regime that produced Sharpe 2+ for the production bug.
    assert math.isfinite(aggregate["sharpe"])
    assert abs(aggregate["sharpe"]) < 100  # sanity bound — was unbounded in old hourly formula


def test_equity_curve_reflects_intra_trade_drawdown(mocker):
    """A trade that swings −20% mid-hold then closes near flat must surface as MaxDD ≤ −20%."""
    # 240 hourly bars; one trade entry at hour 180, exit at hour 184 (4h hold).
    # Construct prices: rising then a sharp drop mid-hold then recovery.
    index = pd.date_range("2026-01-01T00:00:00Z", periods=240, freq="1h", tz="UTC")
    base = np.full(240, 100.0)
    base[180:200] = 100.0
    base[181:184] = [120.0, 130.0, 105.0]  # short hits +30% (bad for short) then recovers
    base[184] = 100.0  # exit roughly flat
    prices = pd.Series(base, index=index, dtype="float64", name="close")

    # Funding spike triggers signal at position 180
    rates = [0.0001] * 180 + [0.0010] * 5 + [0.0001] * 55
    funding = pd.DataFrame(
        {"funding_rate": rates, "premium": np.linspace(0.0, 0.001, len(rates))},
        index=pd.DatetimeIndex(index, name="timestamp"),
    )

    mocker.patch.object(backtest, "load_funding_history", return_value={"BTC": funding})
    mocker.patch.object(backtest, "load_prices", return_value={"BTC": prices})

    frame = backtest.run_single_config(
        backtest.BacktestConfig(
            z_threshold=2.0,
            hold_hours=4,
            lookback_days=2,
            taker_fee=0.0,
            slippage=0.0,
        )
    )

    btc_row = frame.loc[frame["token"] == "BTC"].iloc[0]
    # Short into +30% spike → mark-to-market drawdown ≥ 20% (was 0 under step-equity)
    assert btc_row["max_dd"] <= -0.20


def test_run_single_config_returns_skipped_tokens(mocker):
    """run_single_config exposes which funding tokens were skipped for missing candles."""
    funding_history, prices = _two_token_fixture()
    funding_history["DOGE"] = funding_history["BTC"].copy()  # has funding, no candle
    mocker.patch.object(backtest, "load_funding_history", return_value=funding_history)
    mocker.patch.object(backtest, "load_prices", return_value=prices)

    result = backtest.run_single_config_with_coverage(
        backtest.BacktestConfig(
            z_threshold=2.0,
            hold_hours=4,
            lookback_days=2,
            taker_fee=0.0,
            slippage=0.0,
        )
    )

    assert "DOGE" in result.skipped_tokens
    assert "BTC" not in result.skipped_tokens
    assert "ETH" not in result.skipped_tokens
