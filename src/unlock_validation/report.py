"""Markdown report writer for unlock thesis validation."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pandas as pd


def _fmt_pct(x: float | None) -> str:
    if x is None:
        return "—"
    return f"{x * 100:.1f}%"


def _fmt_num(x: float | None, decimals: int = 4) -> str:
    if x is None:
        return "—"
    return f"{x:.{decimals}f}"


def _stats_table(name: str, stats: dict) -> str:
    return (
        f"### {name}\n\n"
        f"| Metric | Value |\n"
        f"| --- | --- |\n"
        f"| n_events | {stats['n_events']} |\n"
        f"| pct_pre_negative | {_fmt_pct(stats['pct_pre_negative'])} |\n"
        f"| pct_post_negative | {_fmt_pct(stats['pct_post_negative'])} |\n"
        f"| mean_pre (vs BTC) | {_fmt_num(stats['mean_pre'])} |\n"
        f"| mean_post (vs BTC) | {_fmt_num(stats['mean_post'])} |\n"
        f"| p_value_pre (one-sided) | {_fmt_num(stats['p_value_pre'])} |\n"
    )


def _verdict_explainer(verdict: str) -> str:
    return {
        "STRONG": "Thesis confirmed in our sample. **Proceed to ROADMAP Phase 0** (build full infrastructure).",
        "WEAK": "Thesis partially confirmed. **Proceed to Phase 0 with reduced expectations** for the unlock strategy.",
        "REJECT": "Thesis not supported in our sample. **Skip to ROADMAP Phase 2** (single-wallet reverse).",
    }[verdict]


def write_markdown_report(
    path: Path,
    events: pd.DataFrame,
    overall_stats: dict,
    team_subset_stats: dict,
    ex_ecosystem_stats: dict,
    decision: dict,
) -> None:
    """Write a markdown report summarising the thesis validation."""
    path.parent.mkdir(parents=True, exist_ok=True)
    now = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    lines = [
        "# Unlock Thesis Validation Report",
        "",
        f"_Generated {now}_",
        "",
        f"## Verdict: {decision['verdict']}",
        "",
        _verdict_explainer(decision["verdict"]),
        "",
        f"**Metrics passed:** {decision['passed']} / 5",
        "",
        "## Pass/Fail Matrix",
        "",
        "| # | Metric | Pass? |",
        "| --- | --- | --- |",
        f"| 1 | % events with abnormal_pre < 0 ≥ 65% | {'✅' if decision['details']['pct_pre_pass'] else '❌'} |",
        f"| 2 | % events with abnormal_post < 0 ≥ 55% | {'✅' if decision['details']['pct_post_pass'] else '❌'} |",
        f"| 3 | mean(abnormal_pre) ≤ -3% | {'✅' if decision['details']['mean_pre_pass'] else '❌'} |",
        f"| 4 | t-test p-value < 0.05 | {'✅' if decision['details']['p_value_pass'] else '❌'} |",
        f"| 5 | Team-subset mean ≤ overall mean | {'✅' if decision['details']['team_subset_match'] else '❌'} |",
        "",
        "## Aggregate Statistics",
        "",
        _stats_table("Overall (all categories)", overall_stats),
        _stats_table("Team Subset", team_subset_stats),
        _stats_table("Ex-Ecosystem Subset", ex_ecosystem_stats),
        "",
        "## Event Detail",
        "",
        "| Token | Category | Unlock Date | Unlock % | HL perp | AR pre | AR day | AR post |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]

    for _, row in events.iterrows():
        lines.append(
            f"| {row['token']} | {row['category']} | "
            f"{row['unlock_date'].strftime('%Y-%m-%d')} | "
            f"{_fmt_pct(row['unlock_pct'])} | "
            f"{'✅' if row['has_hl_perp'] else '—'} | "
            f"{_fmt_num(row['ar_pre'])} | "
            f"{_fmt_num(row['ar_day'])} | "
            f"{_fmt_num(row['ar_post'])} |"
        )

    path.write_text("\n".join(lines) + "\n")
