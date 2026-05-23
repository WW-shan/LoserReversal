from __future__ import annotations

import pandas as pd

from signals._unlock_common import emit_pair_signals, filter_events


V1_REQUIRED_EVENT_COLUMNS = {"token", "unlock_date", "unlock_pct", "has_hl_perp"}


def unlock_short_signal(
    events: pd.DataFrame,
    prices: dict[str, pd.Series],
    pre_window_days: int = 7,
    min_unlock_pct: float = 0.02,
    require_hl_perp: bool = True,
    coverage: pd.DataFrame | None = None,
) -> dict[str, tuple[pd.Series, pd.Series]]:
    if pre_window_days < 1:
        raise ValueError("pre_window_days must be at least 1")
    frame = filter_events(
        events,
        min_unlock_pct=min_unlock_pct,
        require_hl_perp=require_hl_perp,
        coverage=coverage,
        required_columns=V1_REQUIRED_EVENT_COLUMNS,
    )
    return emit_pair_signals(
        events=frame,
        prices=prices,
        entry_offset_days=-pre_window_days,
        exit_offset_days=0,
    )
