from __future__ import annotations

import math
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pandas as pd

from signals.unlock_grid import GridCell, iter_grid, run_cell


DEFAULT_INIT_CASH = 10_000.0
DEFAULT_FEES = 0.0005
DEFAULT_SLIPPAGE = 0.0002
DEFAULT_GRID_PATH = Path("data/parquet/unlock_grid_v15.parquet")
TRADE_COLUMNS = [
    "signal",
    "split_idx",
    "token",
    "entry_ts",
    "exit_ts",
    "direction",
    "return",
    "hold_days",
    "win",
]


def select_best_config(
    grid_df: pd.DataFrame,
    signal_code: str,
    train_events: pd.DataFrame,
    train_prices: dict[str, pd.Series],
    train_coverage: pd.DataFrame,
    min_n_trades: int = 5,
    *,
    init_cash: float = DEFAULT_INIT_CASH,
    fees: float = DEFAULT_FEES,
    slippage: float = DEFAULT_SLIPPAGE,
    fix_cohort: str | None = None,
) -> GridCell | None:
    best_cell: GridCell | None = None
    best_sharpe = float("-inf")

    for cell in _candidate_cells(grid_df, signal_code, fix_cohort=fix_cohort):
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


def run_per_signal_walkforward(
    events: pd.DataFrame,
    prices: dict[str, pd.Series],
    coverage: pd.DataFrame,
    splits: Sequence[tuple[tuple[pd.Timestamp, pd.Timestamp], tuple[pd.Timestamp, pd.Timestamp]]],
    signals_to_run: Sequence[str],
    *,
    grid_df: pd.DataFrame | None = None,
    min_n_trades: int = 5,
    init_cash: float = DEFAULT_INIT_CASH,
    fees: float = DEFAULT_FEES,
    slippage: float = DEFAULT_SLIPPAGE,
    fallback_used: bool = False,
    record_trades: bool = False,
    fix_cohort: str | None = None,
) -> pd.DataFrame | tuple[pd.DataFrame, pd.DataFrame]:
    grid = _grid_frame(grid_df)
    rows: list[dict[str, Any]] = []
    trade_rows: list[dict[str, Any]] = []

    for split_idx, ((train_start, train_end), (test_start, test_end)) in enumerate(splits):
        train_window_start = _utc_timestamp(train_start)
        train_window_end = _utc_timestamp(train_end)
        test_window_start = _utc_timestamp(test_start)
        test_window_end = _utc_timestamp(test_end)
        train_events = _filter_events_by_window(events, train_window_start, train_window_end)
        test_events = _filter_events_by_window(events, test_window_start, test_window_end)
        train_coverage = _filter_coverage_by_window(
            coverage,
            train_window_start,
            train_window_end,
        )
        test_coverage = _filter_coverage_by_window(coverage, test_window_start, test_window_end)

        for signal_code in signals_to_run:
            selected = select_best_config(
                grid,
                signal_code,
                train_events,
                prices,
                train_coverage,
                min_n_trades=min_n_trades,
                init_cash=init_cash,
                fees=fees,
                slippage=slippage,
                fix_cohort=fix_cohort,
            )
            selected_cohort = None
            if selected is None:
                selected = _fallback_config_for_signal(
                    grid,
                    signal_code,
                    train_events,
                    prices,
                    train_coverage,
                    init_cash=init_cash,
                    fees=fees,
                    slippage=slippage,
                    fix_cohort=fix_cohort,
                )
                if selected is None:
                    selected_cohort = "no_train_signal"
            if selected is None:
                stats = _empty_stats(signal_code)
            else:
                run_kwargs: dict[str, Any] = {
                    "init_cash": init_cash,
                    "fees": fees,
                    "slippage": slippage,
                }
                if record_trades:
                    run_kwargs["record_trades"] = True
                stats = run_cell(test_events, prices, test_coverage, selected, **run_kwargs)
                if record_trades:
                    trade_rows.extend(
                        _walkforward_trade_rows(
                            signal_code,
                            split_idx,
                            stats.get("_trades", []),
                        )
                    )
            rows.append(
                _walkforward_row(
                    kind="per_signal",
                    signal=signal_code,
                    split_idx=split_idx,
                    train_start=train_window_start,
                    train_end=train_window_end,
                    test_start=test_window_start,
                    test_end=test_window_end,
                    selected=selected,
                    selected_cohort=selected_cohort,
                    stats=stats,
                    fallback_used=fallback_used,
                )
            )

    rows.extend(_aggregate_rows(rows, kind="per_signal"))
    summary = pd.DataFrame(rows)
    if record_trades:
        return summary, _trade_frame(trade_rows)
    return summary


def compose_portfolio(
    per_signal_df: pd.DataFrame,
    events: pd.DataFrame,
    prices: dict[str, pd.Series],
    coverage: pd.DataFrame,
    splits: Sequence[tuple[tuple[pd.Timestamp, pd.Timestamp], tuple[pd.Timestamp, pd.Timestamp]]],
    top_k: int = 2,
    *,
    init_cash: float = DEFAULT_INIT_CASH,
    fees: float = DEFAULT_FEES,
    slippage: float = DEFAULT_SLIPPAGE,
) -> pd.DataFrame:
    selected_signals = _top_signals_by_oos(per_signal_df, top_k)
    rows: list[dict[str, Any]] = []

    for split_idx, ((train_start, train_end), (test_start, test_end)) in enumerate(splits):
        train_window_start = _utc_timestamp(train_start)
        train_window_end = _utc_timestamp(train_end)
        test_window_start = _utc_timestamp(test_start)
        test_window_end = _utc_timestamp(test_end)
        test_events = _filter_events_by_window(events, test_window_start, test_window_end)
        test_coverage = _filter_coverage_by_window(coverage, test_window_start, test_window_end)
        components: list[dict[str, Any]] = []
        selection_labels: list[str] = []
        fallback_used = False

        for signal_code in selected_signals:
            selection = _split_selection(per_signal_df, signal_code, split_idx)
            fallback_used = fallback_used or bool(selection.get("fallback_used", False))
            cell = _cell_from_selection(selection)
            if cell is None:
                continue
            components.append(
                run_cell(
                    test_events,
                    prices,
                    test_coverage,
                    cell,
                    init_cash=init_cash,
                    fees=fees,
                    slippage=slippage,
                )
            )
            selection_labels.append(f"{cell.code}:{cell.cohort_name}")

        portfolio_signal = _portfolio_signal_label(len(components))
        rows.append(
            {
                "kind": "portfolio",
                "signal": portfolio_signal,
                "split_idx": split_idx,
                "train_start": train_window_start,
                "train_end": train_window_end,
                "test_start": test_window_start,
                "test_end": test_window_end,
                "selected_min_pct": float("nan"),
                "selected_cohort": ";".join(selection_labels),
                **_combine_equal_weight_stats(portfolio_signal, components),
                "fallback_used": fallback_used,
            }
        )

    rows.extend(_aggregate_rows(rows, kind="portfolio"))
    return pd.DataFrame(rows)


def _portfolio_signal_label(component_count: int) -> str:
    if component_count < 1:
        return "top_0_skipped"
    return f"top_{component_count}_equal_weight"


def _candidate_cells(
    grid_df: pd.DataFrame,
    signal_code: str,
    *,
    fix_cohort: str | None = None,
) -> list[GridCell]:
    lookup = {
        (cell.code, float(cell.min_unlock_pct), cell.cohort_name): cell for cell in iter_grid()
    }
    if grid_df.empty:
        cells_iter = (cell for cell in lookup.values() if cell.code == signal_code)
        if fix_cohort is None:
            return list(cells_iter)
        return [cell for cell in cells_iter if cell.cohort_name == fix_cohort]

    cells: list[GridCell] = []
    seen: set[tuple[str, float, str]] = set()
    for row in grid_df.to_dict("records"):
        code = str(row.get("signal", ""))
        min_unlock_pct = _row_min_unlock_pct(row)
        cohort = str(row.get("cohort", ""))
        key = (code, min_unlock_pct, cohort)
        cell = lookup.get(key)
        if code != signal_code or cell is None or key in seen:
            continue
        if fix_cohort is not None and cohort != fix_cohort:
            continue
        cells.append(cell)
        seen.add(key)
    return cells


def _grid_frame(grid_df: pd.DataFrame | None) -> pd.DataFrame:
    if grid_df is not None:
        return grid_df
    if DEFAULT_GRID_PATH.exists():
        return pd.read_parquet(DEFAULT_GRID_PATH)
    return pd.DataFrame()


def _top_signals_by_oos(per_signal_df: pd.DataFrame, top_k: int) -> list[str]:
    if top_k < 1:
        raise ValueError("top_k must be at least 1")
    if per_signal_df.empty:
        return []

    aggregate = per_signal_df.loc[
        per_signal_df["kind"].eq("per_signal") & per_signal_df["split_idx"].eq(-1)
    ]
    if aggregate.empty:
        aggregate = (
            per_signal_df.loc[per_signal_df["kind"].eq("per_signal")]
            .groupby("signal", as_index=False, sort=False)["sharpe"]
            .mean()
        )
    ranked = aggregate.copy()
    ranked["_sort_sharpe"] = ranked["sharpe"].map(_finite_sharpe)
    ranked = ranked.sort_values("_sort_sharpe", ascending=False)
    return [str(signal) for signal in ranked["signal"].head(top_k)]


def _split_selection(
    per_signal_df: pd.DataFrame,
    signal_code: str,
    split_idx: int,
) -> dict[str, Any]:
    rows = per_signal_df.loc[
        per_signal_df["kind"].eq("per_signal")
        & per_signal_df["signal"].eq(signal_code)
        & per_signal_df["split_idx"].eq(split_idx)
    ]
    if rows.empty:
        return {}
    return rows.iloc[0].to_dict()


def _cell_from_selection(selection: dict[str, Any]) -> GridCell | None:
    if not selection or pd.isna(selection.get("selected_min_pct")):
        return None
    signal_code = str(selection["signal"])
    min_unlock_pct = float(selection["selected_min_pct"])
    cohort = str(selection["selected_cohort"])
    for cell in iter_grid():
        if (
            cell.code == signal_code
            and math.isclose(cell.min_unlock_pct, min_unlock_pct)
            and cell.cohort_name == cohort
        ):
            return cell
    return None


def _combine_equal_weight_stats(
    signal_code: str,
    components: list[dict[str, Any]],
) -> dict[str, Any]:
    if not components:
        return _empty_stats(signal_code)

    n_trades = sum(int(component["n_trades"]) for component in components)
    trades_won = sum(
        float(component["win_rate"]) * int(component["n_trades"]) for component in components
    )
    return {
        "n_trades": n_trades,
        "win_rate": float(trades_won / n_trades) if n_trades else 0.0,
        "sharpe": _weighted_average(components, "sharpe"),
        "sortino": _weighted_average(components, "sortino"),
        "max_dd": _weighted_average(components, "max_dd"),
        "total_return": _weighted_average(components, "total_return"),
    }


def _weighted_average(rows: list[dict[str, Any]], column: str) -> float:
    return float(sum(float(row[column]) for row in rows) / len(rows))


def _fallback_config_for_signal(
    grid_df: pd.DataFrame,
    signal_code: str,
    train_events: pd.DataFrame,
    train_prices: dict[str, pd.Series],
    train_coverage: pd.DataFrame,
    *,
    init_cash: float,
    fees: float,
    slippage: float,
    fix_cohort: str | None = None,
) -> GridCell | None:
    candidate_cells = _candidate_cells(grid_df, signal_code, fix_cohort=fix_cohort)
    if not candidate_cells:
        return None

    rows: list[tuple[GridCell, dict[str, Any]]] = []
    for cell in candidate_cells:
        row = run_cell(
            train_events,
            train_prices,
            train_coverage,
            cell,
            init_cash=init_cash,
            fees=fees,
            slippage=slippage,
        )
        rows.append((cell, row))

    positive_rows = [(cell, row) for cell, row in rows if int(row["n_trades"]) > 0]
    if not positive_rows:
        return None

    best_cell, _ = max(positive_rows, key=lambda item: _fallback_sort_key(item[1]))
    return best_cell


def _fallback_sort_key(row: dict[str, Any]) -> tuple[float, int]:
    n_trades = int(row["n_trades"])
    sharpe = _finite_sharpe(row["sharpe"])
    return (sharpe, n_trades)


def _filter_events_by_window(
    events: pd.DataFrame,
    start: pd.Timestamp,
    end: pd.Timestamp,
) -> pd.DataFrame:
    if events.empty or "unlock_date" not in events.columns:
        return events.iloc[0:0].copy()

    frame = events.copy()
    frame["unlock_date"] = pd.to_datetime(frame["unlock_date"], utc=True, errors="coerce")
    frame = frame.dropna(subset=["unlock_date"])
    mask = (frame["unlock_date"] >= start) & (frame["unlock_date"] < end)
    return frame.loc[mask].reset_index(drop=True)


def _filter_coverage_by_window(
    coverage: pd.DataFrame,
    start: pd.Timestamp,
    end: pd.Timestamp,
) -> pd.DataFrame:
    if coverage.empty or "unlock_date" not in coverage.columns:
        return coverage.copy()

    frame = coverage.copy()
    frame["unlock_date"] = pd.to_datetime(frame["unlock_date"], utc=True, errors="coerce")
    frame = frame.dropna(subset=["unlock_date"])
    mask = (frame["unlock_date"] >= start) & (frame["unlock_date"] < end)
    return frame.loc[mask].reset_index(drop=True)


def _walkforward_row(
    *,
    kind: str,
    signal: str,
    split_idx: int,
    train_start: pd.Timestamp | pd.NaT,
    train_end: pd.Timestamp | pd.NaT,
    test_start: pd.Timestamp | pd.NaT,
    test_end: pd.Timestamp | pd.NaT,
    selected: GridCell | None,
    stats: dict[str, Any],
    fallback_used: bool,
    selected_cohort: str | None = None,
) -> dict[str, Any]:
    return {
        "kind": kind,
        "signal": signal,
        "split_idx": split_idx,
        "train_start": train_start,
        "train_end": train_end,
        "test_start": test_start,
        "test_end": test_end,
        "selected_min_pct": (
            float(selected.min_unlock_pct) if selected is not None else float("nan")
        ),
        "selected_cohort": (
            selected.cohort_name
            if selected is not None
            else (selected_cohort if selected_cohort is not None else "")
        ),
        "n_trades": int(stats["n_trades"]),
        "sharpe": float(stats["sharpe"]),
        "sortino": float(stats["sortino"]),
        "win_rate": float(stats["win_rate"]),
        "max_dd": float(stats["max_dd"]),
        "total_return": float(stats["total_return"]),
        "fallback_used": bool(fallback_used),
    }


def _empty_stats(signal_code: str) -> dict[str, Any]:
    return {
        "signal": signal_code,
        "min_unlock_pct": float("nan"),
        "cohort": "",
        "n_trades": 0,
        "win_rate": 0.0,
        "sharpe": 0.0,
        "sortino": 0.0,
        "max_dd": 0.0,
        "total_return": 0.0,
        "mean_pnl": 0.0,
        "median_pnl": 0.0,
    }


def _walkforward_trade_rows(
    signal: str,
    split_idx: int,
    trades: object,
) -> list[dict[str, Any]]:
    if not isinstance(trades, list):
        return []

    rows: list[dict[str, Any]] = []
    for trade in trades:
        if not isinstance(trade, dict):
            continue
        rows.append(
            {
                "signal": signal,
                "split_idx": split_idx,
                "token": str(trade.get("token", "")),
                "entry_ts": _utc_timestamp(trade.get("entry_ts")),
                "exit_ts": _utc_timestamp(trade.get("exit_ts")),
                "direction": int(trade.get("direction", 0)),
                "return": float(trade.get("return", 0.0)),
                "hold_days": float(trade.get("hold_days", 0.0)),
                "win": bool(trade.get("win", False)),
            }
        )
    return rows


def _trade_frame(rows: list[dict[str, Any]]) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame(
            {
                "signal": pd.Series(dtype="string"),
                "split_idx": pd.Series(dtype="int64"),
                "token": pd.Series(dtype="string"),
                "entry_ts": pd.Series(dtype="datetime64[ns, UTC]"),
                "exit_ts": pd.Series(dtype="datetime64[ns, UTC]"),
                "direction": pd.Series(dtype="int64"),
                "return": pd.Series(dtype="float64"),
                "hold_days": pd.Series(dtype="float64"),
                "win": pd.Series(dtype="bool"),
            }
        )

    frame = pd.DataFrame(rows, columns=TRADE_COLUMNS)
    frame["signal"] = frame["signal"].astype("string")
    frame["split_idx"] = pd.to_numeric(frame["split_idx"], errors="coerce").astype("int64")
    frame["token"] = frame["token"].astype("string")
    frame["entry_ts"] = pd.to_datetime(frame["entry_ts"], utc=True, errors="coerce")
    frame["exit_ts"] = pd.to_datetime(frame["exit_ts"], utc=True, errors="coerce")
    frame["direction"] = pd.to_numeric(frame["direction"], errors="coerce").astype("int64")
    frame["return"] = pd.to_numeric(frame["return"], errors="coerce").astype("float64")
    frame["hold_days"] = pd.to_numeric(frame["hold_days"], errors="coerce").astype("float64")
    frame["win"] = frame["win"].fillna(False).astype("bool")
    return frame[TRADE_COLUMNS]


def _aggregate_rows(rows: list[dict[str, Any]], *, kind: str) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    frame = pd.DataFrame(row for row in rows if row["kind"] == kind and row["split_idx"] >= 0)
    if frame.empty:
        return output

    for signal, signal_frame in frame.groupby("signal", sort=False):
        n_trades = int(signal_frame["n_trades"].sum())
        trades_won = (signal_frame["win_rate"] * signal_frame["n_trades"]).sum()
        returns = signal_frame["total_return"].astype("float64")
        output.append(
            {
                "kind": kind,
                "signal": str(signal),
                "split_idx": -1,
                "train_start": pd.NaT,
                "train_end": pd.NaT,
                "test_start": pd.NaT,
                "test_end": pd.NaT,
                "selected_min_pct": float("nan"),
                "selected_cohort": "aggregate",
                "n_trades": n_trades,
                "sharpe": float(signal_frame["sharpe"].mean()),
                "sortino": float(signal_frame["sortino"].mean()),
                "win_rate": float(trades_won / n_trades) if n_trades else 0.0,
                "max_dd": float(signal_frame["max_dd"].min()),
                "total_return": float((1.0 + returns).prod() - 1.0),
                "fallback_used": bool(signal_frame["fallback_used"].any()),
            }
        )
    return output


def _utc_timestamp(value: Any) -> pd.Timestamp:
    timestamp = pd.Timestamp(value)
    if timestamp.tz is None:
        return timestamp.tz_localize("UTC")
    return timestamp.tz_convert("UTC")


def _row_min_unlock_pct(row: dict[str, Any]) -> float:
    if "min_unlock_pct" in row:
        return float(row["min_unlock_pct"])
    return float(row["min_pct"])


def _finite_sharpe(value: Any) -> float:
    sharpe = float(value)
    if math.isfinite(sharpe):
        return sharpe
    return float("-inf")
