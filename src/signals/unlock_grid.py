from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass

import pandas as pd

from signals.unlock_v1 import unlock_short_signal
from signals.unlock_v2 import unlock_short_30d
from signals.unlock_v3 import unlock_short_tactical
from signals.unlock_v4 import unlock_short_72h
from signals.unlock_v5 import unlock_reversal_long


SignalFn = Callable[..., dict[str, tuple[pd.Series, pd.Series]]]


@dataclass(frozen=True)
class SignalSpec:
    signal_fn: SignalFn
    direction: str
    default_kwargs: dict[str, object]


@dataclass(frozen=True)
class GridCell:
    code: str
    min_unlock_pct: float
    cohort_name: str
    signal_fn: SignalFn
    direction: str
    category_filter: set[str] | None


SIGNAL_REGISTRY: dict[str, SignalSpec] = {
    "v1": SignalSpec(unlock_short_signal, "short", {}),
    "v2": SignalSpec(unlock_short_30d, "short", {}),
    "v3": SignalSpec(unlock_short_tactical, "short", {}),
    "v4": SignalSpec(unlock_short_72h, "short", {}),
    "v5": SignalSpec(unlock_reversal_long, "long", {}),
}
CATEGORY_COHORTS: dict[str, set[str] | None] = {
    "team": {"insiders"},
    "team+investor": {"insiders", "privateSale"},
    "all": None,
}
SIZE_THRESHOLDS: tuple[float, ...] = (0.01, 0.02, 0.05, 0.10)


def apply_category_filter(events: pd.DataFrame, category_filter: set[str] | None) -> pd.DataFrame:
    if category_filter is None:
        return events.copy()
    if events.empty or "category" not in events.columns:
        return events.iloc[0:0].copy()
    return events.loc[events["category"].isin(category_filter)].copy()


def iter_grid() -> Iterator[GridCell]:
    for code, spec in SIGNAL_REGISTRY.items():
        for min_unlock_pct in SIZE_THRESHOLDS:
            for cohort_name, category_filter in CATEGORY_COHORTS.items():
                yield GridCell(
                    code=code,
                    min_unlock_pct=min_unlock_pct,
                    cohort_name=cohort_name,
                    signal_fn=spec.signal_fn,
                    direction=spec.direction,
                    category_filter=category_filter,
                )
