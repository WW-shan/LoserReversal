"""Tests for analyzer: abnormal returns, aggregation, pass/fail."""

from datetime import datetime, timezone

import numpy as np
import pandas as pd
import pytest

from unlock_validation.analyzer import compute_abnormal_return


def _price_series(values: list[float], start: str = "2025-09-10") -> pd.DataFrame:
    idx = pd.date_range(start, periods=len(values), freq="D", tz="UTC")
    return pd.DataFrame({"price": values}, index=idx)


def test_abnormal_return_zero_when_token_and_btc_move_identically():
    token = _price_series([100, 105])
    btc = _price_series([60000, 63000])  # both +5%
    event_date = datetime(2025, 9, 11, tzinfo=timezone.utc)

    ar = compute_abnormal_return(token, btc, event_date, window=(-1, 0))

    assert ar == pytest.approx(0.0, abs=1e-6)


def test_abnormal_return_positive_when_token_outperforms_btc():
    token = _price_series([100, 110])  # +10%
    btc = _price_series([60000, 63000])  # +5%
    event_date = datetime(2025, 9, 11, tzinfo=timezone.utc)

    ar = compute_abnormal_return(token, btc, event_date, window=(-1, 0))

    # log(1.1) - log(1.05) ≈ 0.0465
    assert ar == pytest.approx(np.log(1.1) - np.log(1.05), abs=1e-6)


def test_abnormal_return_negative_when_token_underperforms_btc():
    token = _price_series([100, 100])  # 0%
    btc = _price_series([60000, 63000])  # +5%
    event_date = datetime(2025, 9, 11, tzinfo=timezone.utc)

    ar = compute_abnormal_return(token, btc, event_date, window=(-1, 0))

    assert ar == pytest.approx(-np.log(1.05), abs=1e-6)


def test_abnormal_return_handles_pre_window():
    token = _price_series([100, 95, 90, 90])  # T-2..T+1, T0 at index 2
    btc = _price_series([60000, 60000, 60000, 60000])
    event_date = datetime(2025, 9, 12, tzinfo=timezone.utc)  # T0

    ar = compute_abnormal_return(token, btc, event_date, window=(-2, 0))

    assert ar < 0
    assert ar == pytest.approx(np.log(90 / 100), abs=1e-6)


from unlock_validation.analyzer import aggregate_statistics


def test_aggregate_statistics_computes_pct_negative():
    events = pd.DataFrame({
        "ar_pre": [-0.05, -0.02, 0.01, -0.10, 0.03],   # 3 negative out of 5
        "ar_day": [0.01, -0.02, 0.0, -0.01, 0.02],
        "ar_post": [-0.03, -0.04, 0.02, -0.01, -0.05], # 4 negative out of 5
        "category": ["team", "investor", "ecosystem", "team", "investor"],
    })

    stats = aggregate_statistics(events)

    assert stats["pct_pre_negative"] == pytest.approx(3 / 5)
    assert stats["pct_post_negative"] == pytest.approx(4 / 5)
    assert stats["n_events"] == 5


def test_aggregate_statistics_computes_mean_pre():
    events = pd.DataFrame({
        "ar_pre": [-0.05, -0.02, 0.01, -0.10, 0.03],
        "ar_day": [0.0, 0.0, 0.0, 0.0, 0.0],
        "ar_post": [0.0, 0.0, 0.0, 0.0, 0.0],
        "category": ["team"] * 5,
    })

    stats = aggregate_statistics(events)

    expected_mean = (-0.05 - 0.02 + 0.01 - 0.10 + 0.03) / 5
    assert stats["mean_pre"] == pytest.approx(expected_mean)


def test_aggregate_statistics_computes_t_test_p_value():
    """With clearly negative AR values, p-value (one-sided AR<0) should be < 0.05."""
    np.random.seed(42)
    events = pd.DataFrame({
        "ar_pre": np.random.normal(loc=-0.05, scale=0.02, size=30),
        "ar_day": np.zeros(30),
        "ar_post": np.zeros(30),
        "category": ["team"] * 30,
    })

    stats = aggregate_statistics(events)

    assert stats["p_value_pre"] < 0.05


def test_aggregate_statistics_empty_events_returns_safe_defaults():
    events = pd.DataFrame(columns=["ar_pre", "ar_day", "ar_post", "category"])

    stats = aggregate_statistics(events)

    assert stats["n_events"] == 0
    assert stats["pct_pre_negative"] is None
    assert stats["mean_pre"] is None
    assert stats["p_value_pre"] is None


from unlock_validation.analyzer import filter_ex_ecosystem


def test_filter_ex_ecosystem_removes_ecosystem_rows():
    events = pd.DataFrame({
        "token": ["A", "B", "C", "D"],
        "category": ["team", "ecosystem", "investor", "ecosystem development"],
    })

    filtered = filter_ex_ecosystem(events)

    assert len(filtered) == 2
    assert set(filtered["token"]) == {"A", "C"}


def test_filter_ex_ecosystem_handles_case_insensitivity():
    events = pd.DataFrame({
        "token": ["A", "B"],
        "category": ["team", "Ecosystem"],  # mixed case
    })

    filtered = filter_ex_ecosystem(events)

    assert len(filtered) == 1
    assert filtered.iloc[0]["token"] == "A"


def test_filter_ex_ecosystem_does_not_mutate_input():
    events = pd.DataFrame({"token": ["A", "B"], "category": ["team", "ecosystem"]})
    original_len = len(events)

    filter_ex_ecosystem(events)

    assert len(events) == original_len


from unlock_validation.analyzer import pass_fail_decision


def _stats(pct_pre=0.7, pct_post=0.6, mean_pre=-0.04, p_value=0.01, n=30):
    return {
        "n_events": n,
        "pct_pre_negative": pct_pre,
        "pct_post_negative": pct_post,
        "mean_pre": mean_pre,
        "mean_post": -0.02,
        "p_value_pre": p_value,
    }


def test_pass_fail_all_metrics_pass_returns_strong():
    overall = _stats()
    team_subset = _stats(mean_pre=-0.05)  # team stronger than overall
    decision = pass_fail_decision(overall, team_subset)
    assert decision["verdict"] == "STRONG"
    assert decision["passed"] == 5


def test_pass_fail_three_metrics_pass_returns_weak():
    # pct_pre fails, p-value fails; rest pass
    overall = _stats(pct_pre=0.5, p_value=0.5)
    team_subset = _stats(pct_pre=0.5, p_value=0.5, mean_pre=-0.05)
    decision = pass_fail_decision(overall, team_subset)
    assert decision["verdict"] == "WEAK"
    assert decision["passed"] == 3


def test_pass_fail_two_metrics_pass_returns_reject():
    overall = _stats(pct_pre=0.4, pct_post=0.3, p_value=0.5)
    team_subset = _stats(pct_pre=0.4, pct_post=0.3, p_value=0.5, mean_pre=0.0)
    decision = pass_fail_decision(overall, team_subset)
    assert decision["verdict"] == "REJECT"
    assert decision["passed"] <= 2


def test_pass_fail_team_subset_weaker_than_overall_fails_metric_5():
    overall = _stats(mean_pre=-0.05)
    team_subset = _stats(mean_pre=-0.01)  # weaker than overall
    decision = pass_fail_decision(overall, team_subset)
    assert decision["details"]["team_subset_match"] is False


def test_pass_fail_per_metric_details_are_exposed():
    overall = _stats()
    team_subset = _stats(mean_pre=-0.05)
    decision = pass_fail_decision(overall, team_subset)
    keys = {
        "pct_pre_pass",
        "pct_post_pass",
        "mean_pre_pass",
        "p_value_pass",
        "team_subset_match",
    }
    assert set(decision["details"].keys()) == keys


from unlock_validation.analyzer import enrich_events_with_returns


def test_enrich_events_attaches_three_ar_columns(tmp_path, mocker):
    """Given events and prices, returns DataFrame with ar_pre/ar_day/ar_post columns."""
    events = pd.DataFrame({
        "token": ["TST"],
        "coingecko_id": ["test-token"],
        "unlock_date": pd.to_datetime(["2025-09-15"], utc=True),
        "unlock_pct": [0.03],
        "category": ["team"],
        "has_hl_perp": [True],
    })

    token_idx = pd.date_range("2025-09-01", "2025-09-25", freq="D", tz="UTC")
    token_prices = pd.DataFrame({"price": np.linspace(100, 90, len(token_idx))}, index=token_idx)

    btc_idx = pd.date_range("2025-09-01", "2025-09-25", freq="D", tz="UTC")
    btc_prices = pd.DataFrame({"price": np.linspace(60000, 60000, len(btc_idx))}, index=btc_idx)

    enriched = enrich_events_with_returns(
        events,
        prices_by_id={"test-token": token_prices, "bitcoin": btc_prices},
    )

    assert "ar_pre" in enriched.columns
    assert "ar_day" in enriched.columns
    assert "ar_post" in enriched.columns
    assert enriched["ar_pre"].iloc[0] < 0  # token down, btc flat → negative AR
