from __future__ import annotations

from types import SimpleNamespace

import pandas as pd

from scripts import run_unlock_backtest as runner


def test_run_unlock_backtest_filters_events_by_date_window(monkeypatch):
    events = pd.DataFrame(
        [
            {
                "token": "ARB",
                "coingecko_id": "arb",
                "unlock_date": pd.Timestamp("2026-01-05T00:00:00Z"),
                "unlock_pct": 0.05,
                "category": "team",
                "has_hl_perp": True,
            },
            {
                "token": "ARB",
                "coingecko_id": "arb",
                "unlock_date": pd.Timestamp("2026-01-15T00:00:00Z"),
                "unlock_pct": 0.05,
                "category": "team",
                "has_hl_perp": True,
            },
            {
                "token": "ARB",
                "coingecko_id": "arb",
                "unlock_date": pd.Timestamp("2026-01-25T00:00:00Z"),
                "unlock_pct": 0.05,
                "category": "team",
                "has_hl_perp": True,
            },
        ]
    )
    captured: dict[str, pd.DataFrame] = {}

    monkeypatch.setattr(runner, "read_unlocks", lambda: events)
    monkeypatch.setattr(runner, "HyperliquidClient", lambda: object())

    def fake_load_or_fetch_candles(token, interval, start, end, client):
        index = pd.date_range(start, end, freq="1D", tz="UTC")
        candles = pd.DataFrame({"close": range(len(index))}, index=index)
        return candles, True

    def fake_unlock_short_signal(events_arg, prices, **kwargs):
        captured["events"] = events_arg.copy()
        index = next(iter(prices.values())).index
        series = pd.Series(False, index=index, dtype=bool)
        return {"ARB": (series, series)}

    def fake_run_backtest(prices, entries, exits, config):
        index = prices.index
        equity = pd.Series([10_000.0, 10_000.0], index=index[:2], name="equity")
        return SimpleNamespace(
            stats={
                "n_trades": 0,
                "sharpe": 0.0,
                "sortino": 0.0,
                "max_dd": 0.0,
                "total_return": 0.0,
                "win_rate": 0.0,
            },
            equity=equity,
        )

    monkeypatch.setattr(runner, "_load_or_fetch_candles", fake_load_or_fetch_candles)
    monkeypatch.setattr(runner, "unlock_short_signal", fake_unlock_short_signal)
    monkeypatch.setattr(runner, "run_backtest", fake_run_backtest)

    config = runner.UnlockBacktestConfig(
        report=None,
        date_start=pd.Timestamp("2026-01-10T00:00:00Z"),
        date_end=pd.Timestamp("2026-01-20T00:00:00Z"),
    )

    result = runner.run_unlock_backtest(config)

    assert list(captured["events"]["unlock_date"]) == [
        pd.Timestamp("2026-01-15T00:00:00Z")
    ]
    assert result["funnel"]["date_start_events"] == 2
    assert result["funnel"]["date_end_events"] == 1
