"""Run a toy SMA crossover backtest on synthetic-but-realistic BTC daily prices.

Usage:
    uv run python -m scripts.run_toy_backtest
"""

import numpy as np
import pandas as pd

from infra.backtest.engine import BacktestConfig, run_backtest
from infra.backtest.toy import sma_crossover_signals


def main() -> int:
    np.random.seed(42)
    n = 365
    rets = np.random.normal(0.0008, 0.025, n)
    prices = pd.Series(
        50000 * np.exp(np.cumsum(rets)),
        index=pd.date_range("2025-01-01", periods=n, freq="1D", tz="UTC"),
        name="close",
    )

    entries, exits = sma_crossover_signals(prices, fast=10, slow=30)
    result = run_backtest(prices, entries, exits, BacktestConfig())

    print("=== Toy SMA(10,30) on synthetic BTC ===")
    for key, value in result.stats.items():
        print(f"  {key:14}  {value}")
    print(f"  final equity  {result.equity.iloc[-1]:.2f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
