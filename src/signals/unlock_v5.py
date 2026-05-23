from __future__ import annotations

import pandas as pd

from signals._unlock_common import emit_pair_signals, filter_events


def unlock_reversal_long(
    events: pd.DataFrame,
    prices: dict[str, pd.Series],
    post_entry_days: int = 3,
    post_exit_days: int = 14,
    min_unlock_pct: float = 0.02,
    require_hl_perp: bool = True,
    coverage: pd.DataFrame | None = None,
) -> dict[str, tuple[pd.Series, pd.Series]]:
    if post_entry_days < 1:
        raise ValueError("post_entry_days must be at least 1")
    if post_exit_days <= post_entry_days:
        raise ValueError("post_exit_days must be greater than post_entry_days")
    frame = filter_events(
        events,
        min_unlock_pct=min_unlock_pct,
        require_hl_perp=require_hl_perp,
        coverage=coverage,
    )
    return emit_pair_signals(
        events=frame,
        prices=prices,
        entry_offset_days=post_entry_days,
        exit_offset_days=post_exit_days,
    )
