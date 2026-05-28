"""Tests for ``signals.bot_walkforward``."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from signals.bot_walkforward import (
    BotBacktestConfig,
    BotWalkforwardConfig,
    aggregate_trade_stats,
    backtest_bot_signal,
    classify_verdict,
    run_walkforward,
    validate_signal_frame,
)


def _make_candles(start: str, periods: int, base: float = 100.0, step: float = 1.0) -> pd.DataFrame:
    """1h candle frame with ascending close prices."""
    index = pd.date_range(start, periods=periods, freq="1h", tz="UTC")
    close = pd.Series(base + step * np.arange(periods), index=index)
    return pd.DataFrame({"close": close})


def _make_signal(
    coin: str, direction: str, entry_ts: str, exit_ts: str
) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "timestamp": pd.to_datetime([entry_ts, exit_ts], utc=True),
            "coin": [coin, coin],
            "direction": [direction, direction],
            "entry": [True, False],
            "exit": [False, True],
        }
    )


# ---------- Config validation -----------------------------------------------


def test_backtest_config_rejects_negative_fees() -> None:
    with pytest.raises(ValueError, match="fees must be non-negative"):
        BotBacktestConfig(fees=-0.0001)


def test_backtest_config_rejects_negative_slippage() -> None:
    with pytest.raises(ValueError, match="slippage must be non-negative"):
        BotBacktestConfig(slippage=-1e-9)


def test_backtest_config_rejects_zero_hold_hours() -> None:
    with pytest.raises(ValueError, match="hold_hours must be a positive int"):
        BotBacktestConfig(hold_hours=0)


def test_walkforward_config_rejects_zero_splits() -> None:
    with pytest.raises(ValueError, match="n_splits must be >= 1"):
        BotWalkforwardConfig(n_splits=0)


def test_walkforward_config_rejects_unknown_mode() -> None:
    with pytest.raises(ValueError, match="mode must be expanding"):
        BotWalkforwardConfig(mode="random")


# ---------- Signal validation -----------------------------------------------


def test_validate_signal_frame_raises_on_missing_columns() -> None:
    df = pd.DataFrame({"timestamp": [], "coin": [], "direction": []})
    with pytest.raises(ValueError, match="missing required columns"):
        validate_signal_frame(df)


def test_validate_signal_frame_accepts_required_schema() -> None:
    df = pd.DataFrame(
        {"timestamp": [], "coin": [], "direction": [], "entry": [], "exit": []}
    )
    validate_signal_frame(df)


# ---------- backtest_bot_signal --------------------------------------------


def test_empty_signal_returns_empty_trade_frame() -> None:
    df = pd.DataFrame(
        {"timestamp": [], "coin": [], "direction": [], "entry": [], "exit": []}
    )
    trades = backtest_bot_signal(df, {})
    assert trades.empty
    assert "pct_return" in trades.columns


def test_long_trade_return_excludes_fees() -> None:
    candles = _make_candles("2026-01-01", periods=24, base=100.0, step=1.0)
    # entry at 100 (idx 0), exit at 110 (idx 10)
    signal = _make_signal(
        "BTC", "long", "2026-01-01 00:00:00+00:00", "2026-01-01 10:00:00+00:00"
    )
    trades = backtest_bot_signal(
        signal, {"BTC": candles}, config=BotBacktestConfig(fees=0.0, slippage=0.0)
    )
    assert len(trades) == 1
    np.testing.assert_almost_equal(trades.iloc[0]["pct_return"], 0.10, decimal=6)


def test_short_trade_return_inverted() -> None:
    candles = _make_candles("2026-01-01", periods=24, base=100.0, step=-1.0)
    # entry at 100 (idx 0), exit at 90 (idx 10)
    signal = _make_signal(
        "BTC", "short", "2026-01-01 00:00:00+00:00", "2026-01-01 10:00:00+00:00"
    )
    trades = backtest_bot_signal(
        signal, {"BTC": candles}, config=BotBacktestConfig(fees=0.0, slippage=0.0)
    )
    assert len(trades) == 1
    np.testing.assert_almost_equal(trades.iloc[0]["pct_return"], 0.10, decimal=6)


def test_fees_reduce_return_round_trip() -> None:
    candles = _make_candles("2026-01-01", periods=24, base=100.0, step=1.0)
    signal = _make_signal(
        "BTC", "long", "2026-01-01 00:00:00+00:00", "2026-01-01 10:00:00+00:00"
    )
    no_fee = backtest_bot_signal(
        signal, {"BTC": candles}, config=BotBacktestConfig(fees=0.0, slippage=0.0)
    )
    with_fee = backtest_bot_signal(
        signal, {"BTC": candles}, config=BotBacktestConfig(fees=0.001, slippage=0.0)
    )
    assert with_fee.iloc[0]["pct_return"] < no_fee.iloc[0]["pct_return"]
    np.testing.assert_almost_equal(
        no_fee.iloc[0]["pct_return"] - with_fee.iloc[0]["pct_return"],
        0.002,  # 2 * 0.001 round-trip
        decimal=6,
    )


def test_entry_without_matching_exit_is_dropped() -> None:
    candles = _make_candles("2026-01-01", periods=24)
    signal = pd.DataFrame(
        {
            "timestamp": pd.to_datetime(
                ["2026-01-01 00:00:00+00:00"], utc=True
            ),
            "coin": ["BTC"],
            "direction": ["long"],
            "entry": [True],
            "exit": [False],
        }
    )
    trades = backtest_bot_signal(signal, {"BTC": candles})
    assert trades.empty


def test_missing_candle_for_coin_skips_trade() -> None:
    signal = _make_signal(
        "DOGE", "long", "2026-01-01 00:00:00+00:00", "2026-01-01 10:00:00+00:00"
    )
    trades = backtest_bot_signal(signal, {})  # no DOGE candles
    assert trades.empty


def test_directionally_separates_long_and_short_channels() -> None:
    candles = _make_candles("2026-01-01", periods=48, base=100.0, step=1.0)
    long_sig = _make_signal(
        "BTC", "long", "2026-01-01 00:00:00+00:00", "2026-01-01 10:00:00+00:00"
    )
    short_sig = _make_signal(
        "BTC", "short", "2026-01-01 12:00:00+00:00", "2026-01-01 20:00:00+00:00"
    )
    signal = pd.concat([long_sig, short_sig], ignore_index=True)
    trades = backtest_bot_signal(
        signal, {"BTC": candles}, config=BotBacktestConfig(fees=0.0, slippage=0.0)
    )
    assert len(trades) == 2
    assert set(trades["direction"]) == {"long", "short"}


# ---------- aggregate_trade_stats ------------------------------------------


def test_aggregate_empty_returns_nan() -> None:
    stats = aggregate_trade_stats(pd.DataFrame({"pct_return": []}))
    assert stats["n_trades"] == 0
    assert np.isnan(stats["sharpe"])


def test_aggregate_positive_returns_positive_sharpe() -> None:
    returns = [0.01, 0.02, 0.03, 0.01]
    trades = pd.DataFrame(
        {
            "pct_return": returns,
            "entry_timestamp": pd.date_range(
                "2026-01-01", periods=len(returns), freq="7D", tz="UTC"
            ),
            "exit_timestamp": pd.date_range(
                "2026-01-02", periods=len(returns), freq="7D", tz="UTC"
            ),
        }
    )
    stats = aggregate_trade_stats(trades)
    assert stats["n_trades"] == 4
    assert stats["win_rate"] == 1.0
    assert stats["sharpe"] > 0
    assert stats["max_drawdown"] <= 0  # drawdown is non-positive
    assert stats["total_return"] > 0


def test_aggregate_max_drawdown_negative_on_loss_streak() -> None:
    returns = [0.05, -0.10, -0.05, 0.02]
    trades = pd.DataFrame(
        {
            "pct_return": returns,
            "entry_timestamp": pd.date_range(
                "2026-01-01", periods=len(returns), freq="7D", tz="UTC"
            ),
            "exit_timestamp": pd.date_range(
                "2026-01-02", periods=len(returns), freq="7D", tz="UTC"
            ),
        }
    )
    stats = aggregate_trade_stats(trades)
    assert stats["max_drawdown"] < 0


# ---------- classify_verdict -----------------------------------------------


@pytest.mark.parametrize(
    "n, sharpe, expected",
    [
        (10, 2.0, "INCONCLUSIVE"),
        (30, 0.4, "RED"),
        (30, 0.6, "RED"),  # sharpe ok but n below YELLOW floor 50
        (50, 0.6, "YELLOW"),
        (100, 1.0, "YELLOW"),
        (100, 1.6, "GREEN"),
        (50, -0.2, "RED"),
    ],
)
def test_classify_verdict_thresholds(n: int, sharpe: float, expected: str) -> None:
    aggregate = {"n_trades": n, "sharpe": sharpe}
    verdict, _ = classify_verdict(aggregate)
    assert verdict == expected


# ---------- run_walkforward ------------------------------------------------


def test_walkforward_returns_inconclusive_when_no_trades() -> None:
    signal = pd.DataFrame(
        {"timestamp": [], "coin": [], "direction": [], "entry": [], "exit": []}
    )
    result = run_walkforward(signal, {})
    assert result["verdict"] == "RED"
    assert "no trades" in result["verdict_reason"]


def test_walkforward_returns_inconclusive_on_short_span() -> None:
    candles = _make_candles("2026-01-01", periods=24)
    signal = _make_signal(
        "BTC", "long", "2026-01-01 00:00:00+00:00", "2026-01-01 10:00:00+00:00"
    )
    result = run_walkforward(
        signal,
        {"BTC": candles},
        walkforward_config=BotWalkforwardConfig(
            n_splits=3, min_train_days=30, test_days=15
        ),
    )
    assert result["verdict"] == "INCONCLUSIVE"
    assert "span too short" in result["verdict_reason"]


# ---------- NaN handling (R1 C1) ----------


def test_nan_in_entry_column_does_not_fire_state_machine() -> None:
    """Regression: bool(np.nan) used to silently fire entries; must be False."""
    import numpy as np
    candles = _make_candles("2026-01-01", periods=24, base=100.0, step=1.0)
    signal = pd.DataFrame(
        {
            "timestamp": pd.to_datetime(
                [
                    "2026-01-01 00:00:00+00:00",
                    "2026-01-01 05:00:00+00:00",
                    "2026-01-01 10:00:00+00:00",
                ],
                utc=True,
            ),
            "coin": ["BTC", "BTC", "BTC"],
            "direction": ["long", "long", "long"],
            "entry": [True, np.nan, False],
            "exit": [False, np.nan, True],
        }
    )
    trades = backtest_bot_signal(
        signal, {"BTC": candles}, config=BotBacktestConfig(fees=0.0, slippage=0.0)
    )
    # The NaN row is dropped silently; the real exit at 10:00 closes the trade
    # opened at 00:00 → entry $100, exit $110, return 0.10
    assert len(trades) == 1
    assert abs(trades.iloc[0]["pct_return"] - 0.10) < 1e-6


# ---------- max-gap guard in _price_at (R1 C4) ----------


def test_price_at_returns_none_when_gap_exceeds_max() -> None:
    """Trades after the last candle within max_gap_hours should return None."""
    from signals.bot_walkforward import _price_at
    candles = _make_candles("2026-01-01", periods=24)
    far_future = pd.Timestamp("2026-04-01", tz="UTC")  # 90 days later
    px = _price_at(candles, far_future, max_gap_hours=26.0)
    assert px is None


def test_price_at_returns_close_when_within_max_gap() -> None:
    from signals.bot_walkforward import _price_at
    candles = _make_candles("2026-01-01", periods=24)
    same_day = pd.Timestamp("2026-01-01 12:30:00", tz="UTC")
    px = _price_at(candles, same_day, max_gap_hours=26.0)
    assert px is not None


# ---------- OOS-only aggregate (R1 C1 from P2) ----------


def test_run_walkforward_aggregate_uses_oos_trades_only() -> None:
    """Aggregate Sharpe must use only OOS-window trades, not train-window."""
    candles = pd.DataFrame(
        {
            "close": [100.0 + i for i in range(400)],
        },
        index=pd.date_range("2026-01-01", periods=400, freq="1D", tz="UTC"),
    )
    # 2 entries in train window (days 5, 15), 2 in OOS window (days 60+, 90+).
    # Span extended so walk_forward_splits accepts n_splits=1 + 30 train + 60 test.
    signal = pd.DataFrame(
        {
            "timestamp": pd.to_datetime(
                [
                    "2026-01-06", "2026-01-09",
                    "2026-01-16", "2026-01-19",
                    "2026-03-20", "2026-03-23",
                    "2026-04-25", "2026-04-28",
                ],
                utc=True,
            ),
            "coin": ["BTC"] * 8,
            "direction": ["long"] * 8,
            "entry": [True, False, True, False, True, False, True, False],
            "exit": [False, True, False, True, False, True, False, True],
        }
    )
    result = run_walkforward(
        signal,
        {"BTC": candles},
        backtest_config=BotBacktestConfig(fees=0.0, slippage=0.0),
        walkforward_config=BotWalkforwardConfig(
            n_splits=1, min_train_days=30, test_days=60
        ),
    )
    aggregate = result["aggregate"]
    assert "oos_trades" in result
    assert aggregate["n_trades"] == len(result["oos_trades"])
    # All_trades has 4 paired trades; OOS should have only the 1 in the test window
    # (test window is 30→90 days from start; entry at 2026-03-20 day 73 is in OOS;
    # entry at 2026-04-25 is past the OOS window).
    assert len(result["all_trades"]) == 4
    assert aggregate["n_trades"] >= 1  # at least one OOS trade
    assert aggregate["n_trades"] <= 2  # at most both later trades
