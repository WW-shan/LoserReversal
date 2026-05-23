from __future__ import annotations

import pandas as pd

from signals.unlock_grid import (
    CATEGORY_COHORTS,
    SIGNAL_REGISTRY,
    SIZE_THRESHOLDS,
    apply_category_filter,
    iter_grid,
)


def _events() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"token": "ARB", "category": "insiders"},
            {"token": "APT", "category": "privateSale"},
            {"token": "OP", "category": "ecosystem"},
        ]
    )


def test_signal_registry_has_all_5_versions():
    assert set(SIGNAL_REGISTRY) == {"v1", "v2", "v3", "v4", "v5"}
    assert SIGNAL_REGISTRY["v1"].direction == "short"
    assert SIGNAL_REGISTRY["v5"].direction == "long"


def test_category_cohort_team_only_keeps_insiders():
    result = apply_category_filter(_events(), CATEGORY_COHORTS["team"])

    assert result["token"].tolist() == ["ARB"]


def test_category_cohort_team_investor_keeps_insiders_and_private_sale():
    result = apply_category_filter(_events(), CATEGORY_COHORTS["team+investor"])

    assert result["token"].tolist() == ["ARB", "APT"]


def test_category_cohort_all_passes_everything():
    result = apply_category_filter(_events(), CATEGORY_COHORTS["all"])

    assert result["token"].tolist() == ["ARB", "APT", "OP"]


def test_iter_grid_yields_60_cells():
    cells = list(iter_grid())

    assert len(cells) == 5 * 4 * 3
    assert {cell.code for cell in cells} == set(SIGNAL_REGISTRY)
    assert {cell.min_unlock_pct for cell in cells} == set(SIZE_THRESHOLDS)
    assert {cell.cohort_name for cell in cells} == set(CATEGORY_COHORTS)
