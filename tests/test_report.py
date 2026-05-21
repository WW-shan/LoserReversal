"""Tests for markdown report writer."""

from pathlib import Path

import pandas as pd

from unlock_validation.report import write_markdown_report


def _sample_events() -> pd.DataFrame:
    return pd.DataFrame({
        "token": ["ARB", "JTO", "APT"],
        "category": ["investor", "team", "team"],
        "unlock_date": pd.to_datetime(["2025-09-16", "2025-12-07", "2025-11-12"], utc=True),
        "unlock_pct": [0.0234, 0.04, 0.03],
        "has_hl_perp": [True, False, True],
        "ar_pre": [-0.05, -0.07, 0.01],
        "ar_day": [-0.01, 0.0, 0.02],
        "ar_post": [-0.02, -0.04, 0.0],
    })


def test_report_writes_file_with_required_sections(tmp_path):
    events = _sample_events()
    overall = {
        "n_events": 3,
        "pct_pre_negative": 2 / 3,
        "pct_post_negative": 2 / 3,
        "mean_pre": -0.037,
        "mean_post": -0.02,
        "p_value_pre": 0.04,
    }
    team_subset = overall.copy()
    team_subset["mean_pre"] = -0.03
    ex_eco = overall.copy()

    decision = {
        "verdict": "STRONG",
        "passed": 4,
        "details": {
            "pct_pre_pass": True,
            "pct_post_pass": True,
            "mean_pre_pass": True,
            "p_value_pass": True,
            "team_subset_match": False,
        },
    }

    out = tmp_path / "out.md"
    write_markdown_report(out, events, overall, team_subset, ex_eco, decision)

    text = out.read_text()
    for section in [
        "# Unlock Thesis Validation Report",
        "## Verdict: STRONG",
        "## Pass/Fail Matrix",
        "## Aggregate Statistics",
        "## Team Subset",
        "## Ex-Ecosystem Subset",
        "## Event Detail",
        "ARB",
        "JTO",
    ]:
        assert section in text


def test_report_includes_hl_perp_flag_in_event_detail(tmp_path):
    events = _sample_events()
    overall = team = ex_eco = {
        "n_events": 3,
        "pct_pre_negative": 0.5,
        "pct_post_negative": 0.5,
        "mean_pre": -0.01,
        "mean_post": -0.01,
        "p_value_pre": 0.5,
    }
    decision = {"verdict": "REJECT", "passed": 0, "details": {
        "pct_pre_pass": False, "pct_post_pass": False, "mean_pre_pass": False,
        "p_value_pass": False, "team_subset_match": False,
    }}

    out = tmp_path / "out.md"
    write_markdown_report(out, events, overall, team, ex_eco, decision)

    text = out.read_text()
    # HL perp flag should be visible
    assert "HL perp" in text or "has_hl_perp" in text
