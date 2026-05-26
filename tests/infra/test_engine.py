"""Tests for vectorbt backtest wrapper."""

import pandas as pd
import pytest

from datetime import datetime, timezone

from infra.backtest.engine import BacktestConfig, periods_per_year, run_backtest
from infra.pipeline import PipelineConfig, candles_cover_range
from scripts.run_btc_sma_e2e import _last_completed_candle_end


def test_run_backtest_buy_and_hold_tracks_price_return_after_entry_fee():
    prices = pd.Series(
        [100.0, 110.0, 120.0],
        index=pd.date_range("2026-01-01", periods=3, freq="1D", tz="UTC"),
        name="close",
    )
    entries = pd.Series([True, False, False], index=prices.index)
    exits = pd.Series([False, False, False], index=prices.index)
    config = BacktestConfig(init_cash=10_000, fees=0.001, slippage=0.0)

    result = run_backtest(prices, entries, exits, config)

    expected_final = config.init_cash / (1.0 + config.fees) * (prices.iloc[-1] / prices.iloc[0])
    assert result.equity.iloc[-1] == pytest.approx(expected_final)
    assert result.stats["total_return"] == pytest.approx(expected_final / config.init_cash - 1.0)


def test_run_backtest_counts_one_closed_trade():
    prices = pd.Series(
        [100.0, 110.0, 120.0, 115.0],
        index=pd.date_range("2026-01-01", periods=4, freq="1D", tz="UTC"),
        name="close",
    )
    entries = pd.Series([True, False, False, False], index=prices.index)
    exits = pd.Series([False, False, True, False], index=prices.index)

    result = run_backtest(prices, entries, exits, BacktestConfig(fees=0.0, slippage=0.0))

    assert result.stats["n_trades"] == 1
    assert result.stats["win_rate"] == 1.0


def test_run_backtest_no_signals_preserves_initial_cash():
    prices = pd.Series(
        [100.0, 90.0, 110.0],
        index=pd.date_range("2026-01-01", periods=3, freq="1D", tz="UTC"),
        name="close",
    )
    entries = pd.Series(False, index=prices.index)
    exits = pd.Series(False, index=prices.index)
    config = BacktestConfig(init_cash=10_000)

    result = run_backtest(prices, entries, exits, config)

    assert result.equity.tolist() == [config.init_cash, config.init_cash, config.init_cash]
    assert result.stats["total_return"] == 0.0
    assert result.stats["n_trades"] == 0


@pytest.mark.parametrize(
    ("freq", "expected"),
    [
        ("1W", 52),
        ("1M", 12),
        ("1h", 8760),
    ],
)
def test_period_lookup_uses_supported_frequencies(freq, expected):
    assert periods_per_year(freq) == expected


@pytest.mark.parametrize(
    ("config_freq", "index_freq"),
    [
        ("1W", "1W"),
        ("1M", "ME"),
        ("1h", "1h"),
    ],
)
def test_run_backtest_accepts_weekly_monthly_and_hourly_frequencies(config_freq, index_freq):
    prices = pd.Series(
        [100.0, 101.0, 102.0, 103.0],
        index=pd.date_range("2026-01-01", periods=4, freq=index_freq, tz="UTC"),
        name="close",
    )
    entries = pd.Series(False, index=prices.index)
    exits = pd.Series(False, index=prices.index)

    result = run_backtest(prices, entries, exits, BacktestConfig(freq=config_freq))

    assert result.stats["n_trades"] == 0


@pytest.mark.parametrize(
    ("interval", "now", "expected"),
    [
        (
            "1d",
            datetime(2026, 5, 22, 15, 30, tzinfo=timezone.utc),
            datetime(2026, 5, 22, 0, 0, tzinfo=timezone.utc),
        ),
        (
            "1h",
            datetime(2026, 5, 22, 15, 30, 45, tzinfo=timezone.utc),
            datetime(2026, 5, 22, 15, 0, tzinfo=timezone.utc),
        ),
        (
            "5m",
            datetime(2026, 5, 22, 15, 32, 1, tzinfo=timezone.utc),
            datetime(2026, 5, 22, 15, 30, tzinfo=timezone.utc),
        ),
    ],
)
def test_last_completed_candle_end_aligns_to_previous_boundary(interval, now, expected):
    assert _last_completed_candle_end(interval, now) == expected


def test_last_completed_candle_end_rejects_anchored_intervals():
    with pytest.raises(ValueError, match="fixed interval"):
        _last_completed_candle_end("1w", datetime(2026, 5, 22, 15, 30, tzinfo=timezone.utc))


def test_candle_range_cover_accepts_last_open_at_completed_end_boundary():
    candles = pd.DataFrame(
        {"close": [100.0]},
        index=pd.DatetimeIndex([pd.Timestamp("2026-05-21T00:00:00Z")], name="timestamp"),
    )
    config = PipelineConfig(
        symbol="BTC",
        interval="1d",
        start=datetime(2026, 5, 21, tzinfo=timezone.utc),
        end=datetime(2026, 5, 22, tzinfo=timezone.utc),
    )

    assert candles_cover_range(candles, config)


def test_run_backtest_applies_stop_loss_caps_trade_loss():
    """A short trade where price rises >10% must exit by the stop loss path.

    Phase 1.5 Ablation D: per-trade -10% stop. We compare the no-stop short
    (price climbs through entry, equity bleeds) against sl_stop=0.10 (engine
    closes the position once the running price exceeds entry x 1.10).
    """
    prices = pd.Series(
        [100.0, 105.0, 112.0, 118.0, 125.0],
        index=pd.date_range("2026-01-01", periods=5, freq="1D", tz="UTC"),
        name="close",
    )
    entries = pd.Series([True, False, False, False, False], index=prices.index)
    exits = pd.Series(False, index=prices.index)
    base_config = BacktestConfig(
        init_cash=10_000.0,
        fees=0.0,
        slippage=0.0,
        direction="shortonly",
    )
    stop_config = BacktestConfig(
        init_cash=10_000.0,
        fees=0.0,
        slippage=0.0,
        direction="shortonly",
        stop_loss=0.10,
    )

    baseline = run_backtest(prices, entries, exits, base_config)
    stopped = run_backtest(prices, entries, exits, stop_config)

    # Baseline short held through full rally: loss ~ -25% on equity.
    assert baseline.equity.iloc[-1] < 8_000.0
    # Stop loss exits the trade after price first closes above entry*1.10,
    # so final equity must be strictly larger than the unstopped run.
    assert stopped.equity.iloc[-1] > baseline.equity.iloc[-1]
    # And the stopped trade should be marked as closed with one realised trade.
    assert stopped.stats["n_trades"] == 1


def test_run_backtest_no_stop_loss_passes_through_unchanged():
    """With stop_loss=None, engine output must match the pre-Ablation-D path."""
    prices = pd.Series(
        [100.0, 105.0, 112.0, 118.0, 125.0],
        index=pd.date_range("2026-01-01", periods=5, freq="1D", tz="UTC"),
        name="close",
    )
    entries = pd.Series([True, False, False, False, False], index=prices.index)
    exits = pd.Series(False, index=prices.index)
    legacy_config = BacktestConfig(
        init_cash=10_000.0,
        fees=0.0,
        slippage=0.0,
        direction="shortonly",
    )
    explicit_none = BacktestConfig(
        init_cash=10_000.0,
        fees=0.0,
        slippage=0.0,
        direction="shortonly",
        stop_loss=None,
    )

    legacy = run_backtest(prices, entries, exits, legacy_config)
    explicit = run_backtest(prices, entries, exits, explicit_none)

    assert legacy.equity.tolist() == explicit.equity.tolist()
    assert legacy.stats["n_trades"] == explicit.stats["n_trades"]
    assert legacy.stats["total_return"] == pytest.approx(explicit.stats["total_return"])


def test_fixed_stop_mode_unchanged_behavior():
    """stop_loss_mode='fixed' default must preserve the legacy fixed-stop path."""
    prices = pd.Series(
        [100.0, 105.0, 112.0, 118.0, 125.0],
        index=pd.date_range("2026-01-01", periods=5, freq="1D", tz="UTC"),
        name="close",
    )
    entries = pd.Series([True, False, False, False, False], index=prices.index)
    exits = pd.Series(False, index=prices.index)
    legacy_config = BacktestConfig(
        init_cash=10_000.0,
        fees=0.0,
        slippage=0.0,
        direction="shortonly",
        stop_loss=0.10,
    )
    explicit_fixed = BacktestConfig(
        init_cash=10_000.0,
        fees=0.0,
        slippage=0.0,
        direction="shortonly",
        stop_loss=0.10,
        stop_loss_mode="fixed",
    )

    legacy = run_backtest(prices, entries, exits, legacy_config)
    explicit = run_backtest(prices, entries, exits, explicit_fixed)

    assert legacy.equity.tolist() == explicit.equity.tolist()
    assert legacy.stats["n_trades"] == explicit.stats["n_trades"]
    assert legacy.stats["total_return"] == pytest.approx(explicit.stats["total_return"])


def test_atr_stop_loss_widens_on_volatile_bar():
    """High volatility before entry must produce a wider ATR stop than a calm series.

    Two short trades enter on the same bar. The volatile-history close path swings
    aggressively prior to entry, so the per-bar ATR(period=3) stop is materially
    wider at entry than the calm-history equivalent. The wider stop survives the
    same +10% post-entry move; the calm stop triggers and closes the position.
    """
    index = pd.date_range("2026-01-01", periods=15, freq="1D", tz="UTC")
    # Calm history: smooth ramp before entry; volatile history: large oscillation
    # before entry. Both share the identical post-entry path (entries on bar 9).
    calm_history = [100.0, 100.5, 101.0, 100.8, 101.2, 100.9, 101.1, 101.3, 101.0, 101.5]
    volatile_history = [100.0, 115.0, 88.0, 118.0, 86.0, 120.0, 84.0, 122.0, 82.0, 101.5]
    post_entry = [108.0, 113.0, 120.0, 125.0, 130.0]  # +5..+20% after entry

    calm_prices = pd.Series(calm_history + post_entry, index=index, name="close")
    volatile_prices = pd.Series(
        volatile_history + post_entry, index=index, name="close"
    )
    entries = pd.Series([False] * 9 + [True] + [False] * 5, index=index)
    exits = pd.Series(False, index=index)
    atr_config = BacktestConfig(
        init_cash=10_000.0,
        fees=0.0,
        slippage=0.0,
        direction="shortonly",
        stop_loss_mode="atr",
        stop_loss_atr_period=3,
        stop_loss_atr_multiplier=2.0,
        stop_loss_floor=0.0,
        stop_loss_cap=1.0,
    )

    calm = run_backtest(calm_prices, entries, exits, atr_config)
    volatile = run_backtest(volatile_prices, entries, exits, atr_config)

    # Calm path's tight ATR stop fires; volatile path's wider ATR stop survives
    # the same proportional rise, so its short is still open / shows a smaller loss.
    assert calm.stats["n_trades"] == 1
    assert volatile.stats["n_trades"] >= 1
    assert volatile.equity.iloc[-1] >= calm.equity.iloc[-1] - 1e-9


def test_atr_stop_loss_caps_at_max():
    """When ATR is extreme, the per-bar sl_stop must be clipped to the cap.

    Extreme-vol synthetic series would imply >100% ATR-fraction stops without
    a cap; with stop_loss_cap=0.25 the post-entry +30% short loss must still
    trigger an exit, capping the realised loss near the cap fraction.
    """
    index = pd.date_range("2026-01-01", periods=20, freq="1D", tz="UTC")
    # Extreme oscillation gives huge ATR, then a clean 30% short-against move.
    history = [100.0, 200.0, 50.0, 200.0, 50.0, 200.0, 50.0, 200.0, 50.0, 100.0]
    post_entry = [100.0, 110.0, 120.0, 125.0, 130.0, 130.0, 130.0, 130.0, 130.0, 130.0]
    prices = pd.Series(history + post_entry, index=index, name="close")
    entries = pd.Series([False] * 9 + [True] + [False] * 10, index=index)
    exits = pd.Series(False, index=index)
    capped_config = BacktestConfig(
        init_cash=10_000.0,
        fees=0.0,
        slippage=0.0,
        direction="shortonly",
        stop_loss_mode="atr",
        stop_loss_atr_period=3,
        stop_loss_atr_multiplier=5.0,
        stop_loss_floor=0.05,
        stop_loss_cap=0.25,
    )
    uncapped_config = BacktestConfig(
        init_cash=10_000.0,
        fees=0.0,
        slippage=0.0,
        direction="shortonly",
        stop_loss_mode="atr",
        stop_loss_atr_period=3,
        stop_loss_atr_multiplier=5.0,
        stop_loss_floor=0.05,
        stop_loss_cap=1.0,
    )

    capped = run_backtest(prices, entries, exits, capped_config)
    uncapped = run_backtest(prices, entries, exits, uncapped_config)

    # Capped run must stop earlier than uncapped, so final equity must be larger
    # than the uncapped run that rides the +30% adverse move.
    assert capped.equity.iloc[-1] > uncapped.equity.iloc[-1]
    assert capped.stats["n_trades"] == 1


def test_atr_stop_loss_floors_at_min():
    """When ATR is near-zero, the per-bar sl_stop must be lifted to the floor.

    A nearly flat history produces ATR-fraction ~ 0, which would give an
    immediately-firing stop on any micro tick. The floor lifts the effective
    stop above noise: a small post-entry rally that is *less than* the floor
    must NOT trigger an exit.
    """
    index = pd.date_range("2026-01-01", periods=20, freq="1D", tz="UTC")
    # Nearly flat history -> tiny ATR -> would be ~0 without floor.
    history = [100.0] * 10
    # Post-entry rises a smooth ~5% — below floor=0.10 so stop must NOT fire.
    post_entry = [100.0, 101.0, 102.0, 103.0, 103.5, 104.0, 104.5, 105.0, 104.8, 104.5]
    prices = pd.Series(history + post_entry, index=index, name="close")
    entries = pd.Series([False] * 9 + [True] + [False] * 10, index=index)
    exits = pd.Series(False, index=index)
    floored_config = BacktestConfig(
        init_cash=10_000.0,
        fees=0.0,
        slippage=0.0,
        direction="shortonly",
        stop_loss_mode="atr",
        stop_loss_atr_period=3,
        stop_loss_atr_multiplier=2.0,
        stop_loss_floor=0.10,
        stop_loss_cap=0.25,
    )
    no_floor_config = BacktestConfig(
        init_cash=10_000.0,
        fees=0.0,
        slippage=0.0,
        direction="shortonly",
        stop_loss_mode="atr",
        stop_loss_atr_period=3,
        stop_loss_atr_multiplier=2.0,
        stop_loss_floor=0.0,
        stop_loss_cap=0.25,
    )

    floored = run_backtest(prices, entries, exits, floored_config)
    no_floor = run_backtest(prices, entries, exits, no_floor_config)

    # Floor protects the short from a sub-floor adverse move; no-floor variant
    # is stopped out almost immediately. So floored equity must be smaller (the
    # short is still open and bleeding ~5% on +5% rise) while no-floor exited
    # earlier near the entry tick.
    assert floored.stats["n_trades"] == 1
    # Floor lifts the stop above noise -> short remains open and bleeds the +5%
    # rally, so floored final equity is below the no-floor variant that exited
    # near the entry tick.
    assert floored.equity.iloc[-1] < no_floor.equity.iloc[-1]


def test_atr_stop_loss_does_not_change_no_entry_behavior():
    """With no entries, ATR-mode must produce identical equity to fixed-mode."""
    prices = pd.Series(
        [100.0, 105.0, 95.0, 110.0, 90.0],
        index=pd.date_range("2026-01-01", periods=5, freq="1D", tz="UTC"),
        name="close",
    )
    entries = pd.Series(False, index=prices.index)
    exits = pd.Series(False, index=prices.index)
    fixed_config = BacktestConfig(stop_loss_mode="fixed")
    atr_config = BacktestConfig(
        stop_loss_mode="atr",
        stop_loss_atr_period=3,
        stop_loss_atr_multiplier=2.0,
        stop_loss_floor=0.08,
        stop_loss_cap=0.25,
    )

    fixed = run_backtest(prices, entries, exits, fixed_config)
    atr = run_backtest(prices, entries, exits, atr_config)

    assert fixed.equity.tolist() == atr.equity.tolist()


def test_atr_stop_loss_rejects_unknown_mode():
    prices = pd.Series(
        [100.0, 105.0, 110.0],
        index=pd.date_range("2026-01-01", periods=3, freq="1D", tz="UTC"),
        name="close",
    )
    entries = pd.Series([True, False, False], index=prices.index)
    exits = pd.Series(False, index=prices.index)
    bad_config = BacktestConfig(stop_loss_mode="trailing")

    with pytest.raises(ValueError, match="stop_loss_mode"):
        run_backtest(prices, entries, exits, bad_config)
