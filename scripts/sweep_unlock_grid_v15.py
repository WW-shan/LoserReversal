"""Run the Phase 1.5 unlock signal grid sweep."""

from __future__ import annotations

from typing import Any

import pandas as pd

from signals.unlock_grid import iter_grid, run_cell


def run_main_grid(
    events: pd.DataFrame,
    prices: dict[str, pd.Series],
    coverage: pd.DataFrame,
    *,
    init_cash: float,
    fees: float,
    slippage: float,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for cell in iter_grid():
        row = run_cell(
            events,
            prices,
            coverage,
            cell,
            init_cash=init_cash,
            fees=fees,
            slippage=slippage,
        )
        row["eligible"] = int(row["n_trades"]) >= 30
        rows.append(row)
    return rows
