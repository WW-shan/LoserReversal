"""Tests for config constants."""

from unlock_validation.config import (
    CACHE_DIR,
    DATA_DIR,
    ECOSYSTEM_CATEGORIES,
    PASS_FAIL_THRESHOLDS,
    REPORTS_DIR,
    SEED_EVENTS_CSV,
    WINDOWS,
)


def test_windows_define_three_event_study_periods():
    assert WINDOWS["pre"] == (-7, 0)
    assert WINDOWS["day"] == (0, 1)
    assert WINDOWS["post"] == (0, 3)


def test_pass_fail_thresholds_have_five_metrics():
    keys = {
        "pct_pre_negative_pass",
        "pct_post_negative_pass",
        "mean_pre_pass",
        "p_value_pass",
        "team_subset_must_match_overall",
    }
    assert set(PASS_FAIL_THRESHOLDS.keys()) == keys


def test_pass_thresholds_are_numerically_correct():
    assert PASS_FAIL_THRESHOLDS["pct_pre_negative_pass"] == 0.65
    assert PASS_FAIL_THRESHOLDS["pct_post_negative_pass"] == 0.55
    assert PASS_FAIL_THRESHOLDS["mean_pre_pass"] == -0.03
    assert PASS_FAIL_THRESHOLDS["p_value_pass"] == 0.05


def test_ecosystem_categories_lowercased_for_filtering():
    for c in ECOSYSTEM_CATEGORIES:
        assert c == c.lower()


def test_paths_resolve_under_repo_root():
    assert DATA_DIR.name == "data"
    assert CACHE_DIR.parent == DATA_DIR
    assert CACHE_DIR.name == "cache"
    assert SEED_EVENTS_CSV.parent.name == "seed"
    assert REPORTS_DIR.name == "reports"
