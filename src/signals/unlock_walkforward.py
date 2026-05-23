from __future__ import annotations

import math
from typing import Any

import pandas as pd

from signals.unlock_grid import GridCell, iter_grid, run_cell


DEFAULT_INIT_CASH = 10_000.0
DEFAULT_FEES = 0.0005
DEFAULT_SLIPPAGE = 0.0002


def select_best_config(
    grid_df: pd.DataFrame,
    signal_code: str,
    train_events: pd.DataFrame,
    train_prices: dict[str, pd.Series],
    train_coverage: pd.DataFrame,
    min_n_trades: int = 15,
    *,
    init_cash: float = DEFAULT_INIT_CASH,
    fees: float = DEFAULT_FEES,
    slippage: float = DEFAULT_SLIPPAGE,
) -> GridCell | None:
    best_cell: GridCell | None = None
    best_sharpe = float("-inf")

    for cell in _candidate_cells(grid_df, signal_code):
        row = run_cell(
            train_events,
            train_prices,
            train_coverage,
            cell,
            init_cash=init_cash,
            fees=fees,
            slippage=slippage,
        )
        n_trades = int(row["n_trades"])
        sharpe = _finite_sharpe(row["sharpe"])
        if n_trades >= min_n_trades and sharpe > best_sharpe:
            best_cell = cell
            best_sharpe = sharpe

    return best_cell


def _candidate_cells(grid_df: pd.DataFrame, signal_code: str) -> list[GridCell]:
    lookup = {
        (cell.code, float(cell.min_unlock_pct), cell.cohort_name): cell for cell in iter_grid()
    }
    if grid_df.empty:
        return [cell for cell in lookup.values() if cell.code == signal_code]

    cells: list[GridCell] = []
    seen: set[tuple[str, float, str]] = set()
    for row in grid_df.to_dict("records"):
        code = str(row.get("signal", ""))
        min_unlock_pct = _row_min_unlock_pct(row)
        cohort = str(row.get("cohort", ""))
        key = (code, min_unlock_pct, cohort)
        cell = lookup.get(key)
        if code == signal_code and cell is not None and key not in seen:
            cells.append(cell)
            seen.add(key)
    return cells


def _row_min_unlock_pct(row: dict[str, Any]) -> float:
    if "min_unlock_pct" in row:
        return float(row["min_unlock_pct"])
    return float(row["min_pct"])


def _finite_sharpe(value: Any) -> float:
    sharpe = float(value)
    if math.isfinite(sharpe):
        return sharpe
    return float("-inf")
