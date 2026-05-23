from __future__ import annotations

from typing import Protocol

import pandas as pd
import pytest

from signals.unlock_v1 import unlock_short_signal
from signals.unlock_v2 import unlock_short_30d
from signals.unlock_v3 import unlock_short_tactical
from signals.unlock_v4 import unlock_short_72h
from signals.unlock_v5 import unlock_reversal_long


class SignalFn(Protocol):
    def __call__(
        self,
        events: pd.DataFrame,
        prices: dict[str, pd.Series],
        *,
        coverage: pd.DataFrame | None = None,
    ) -> dict[str, tuple[pd.Series, pd.Series]]: ...


def _events() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "token": "ARB",
                "unlock_date": pd.Timestamp("2026-02-01T00:00:00Z"),
                "unlock_pct": 0.05,
                "category": "team",
                "has_hl_perp": True,
                "vesting_type": "cliff",
            },
            {
                "token": "APT",
                "unlock_date": pd.Timestamp("2026-02-05T00:00:00Z"),
                "unlock_pct": 0.06,
                "category": "investor",
                "has_hl_perp": True,
                "vesting_type": "linear",
            },
            {
                "token": "OP",
                "unlock_date": pd.Timestamp("2026-02-10T00:00:00Z"),
                "unlock_pct": 0.07,
                "category": "ecosystem",
                "has_hl_perp": True,
                "vesting_type": "step",
            },
        ]
    )


def _prices() -> dict[str, pd.Series]:
    index = pd.date_range("2026-01-01", periods=60, freq="1D", tz="UTC")
    return {
        token: pd.Series(range(len(index)), index=index, dtype="float64", name="close")
        for token in ["ARB", "APT", "OP"]
    }


def _coverage() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"token": "ARB", "unlock_date": "2026-02-01", "coverage_status": "ok"},
            {"token": "APT", "unlock_date": "2026-02-05", "coverage_status": "ok"},
            {"token": "OP", "unlock_date": "2026-02-10", "coverage_status": "listing_after"},
        ]
    )


@pytest.mark.parametrize(
    ("signal_name", "signal_fn"),
    [
        ("v1", unlock_short_signal),
        ("v2", unlock_short_30d),
        ("v3", unlock_short_tactical),
        ("v4", unlock_short_72h),
        ("v5", unlock_reversal_long),
    ],
)
def test_unlock_signals_emit_with_shared_covered_fixture(
    signal_name: str,
    signal_fn: SignalFn,
) -> None:
    result = signal_fn(_events(), _prices(), coverage=_coverage())

    assert set(result) == {"ARB", "APT"}, signal_name
    for entries, exits in result.values():
        assert entries.sum() == 1
        assert exits.sum() == 1
