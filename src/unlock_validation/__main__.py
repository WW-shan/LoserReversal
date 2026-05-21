"""CLI: end-to-end run that fetches data, computes stats, writes report."""

from __future__ import annotations

from datetime import timedelta

from unlock_validation.analyzer import (
    aggregate_statistics,
    enrich_events_with_returns,
    filter_ex_ecosystem,
    pass_fail_decision,
)
from unlock_validation.config import CACHE_DIR, REPORTS_DIR, SEED_EVENTS_CSV
from unlock_validation.fetcher import fetch_prices, load_events
from unlock_validation.report import write_markdown_report


PRICE_WINDOW_BUFFER_DAYS = 14  # extra days around event to ensure window coverage


def main() -> int:
    events = load_events(SEED_EVENTS_CSV, min_pct=0.02)
    print(f"[1/4] loaded {len(events)} events (≥ 2% supply)")

    coingecko_ids = sorted(set(events["coingecko_id"]) | {"bitcoin"})
    span_start = events["unlock_date"].min() - timedelta(days=30 + PRICE_WINDOW_BUFFER_DAYS)
    span_end = events["unlock_date"].max() + timedelta(days=14 + PRICE_WINDOW_BUFFER_DAYS)

    prices_by_id: dict = {}
    for cg_id in coingecko_ids:
        prices_by_id[cg_id] = fetch_prices(cg_id, span_start, span_end, cache_dir=CACHE_DIR)
    print(f"[2/4] fetched prices for {len(prices_by_id)} ids (cache: {CACHE_DIR})")

    enriched = enrich_events_with_returns(events, prices_by_id)
    print(f"[3/4] enriched {len(enriched)} events with abnormal returns")

    overall_stats = aggregate_statistics(enriched)
    team_stats = aggregate_statistics(enriched[enriched["category"] == "team"])
    ex_eco_stats = aggregate_statistics(filter_ex_ecosystem(enriched))

    decision = pass_fail_decision(overall_stats, team_stats)

    out_path = REPORTS_DIR / "unlock_thesis_report.md"
    write_markdown_report(out_path, enriched, overall_stats, team_stats, ex_eco_stats, decision)
    print(f"[4/4] verdict: {decision['verdict']} ({decision['passed']}/5) → {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
