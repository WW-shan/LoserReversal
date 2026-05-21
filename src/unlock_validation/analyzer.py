"""Statistical analysis: abnormal returns, aggregation, pass/fail."""

from __future__ import annotations

from datetime import datetime, timedelta

import numpy as np
import pandas as pd
from scipy import stats as scipy_stats

from unlock_validation.config import ECOSYSTEM_CATEGORIES, PASS_FAIL_THRESHOLDS, WINDOWS


def _price_at(prices: pd.DataFrame, target: datetime) -> float:
    """Pick the last available price at or before `target`."""
    available = prices.loc[prices.index <= pd.Timestamp(target)]
    if available.empty:
        raise ValueError(f"No price available at or before {target}")
    return float(available["price"].iloc[-1])


def compute_abnormal_return(
    token_prices: pd.DataFrame,
    btc_prices: pd.DataFrame,
    event_date: datetime,
    window: tuple[int, int],
) -> float:
    """Compute log-return abnormal return over the window relative to BTC.

    window is (offset_start_days, offset_end_days) — e.g. (-7, 0) means T-7 to T0.
    """
    day_start, day_end = window
    start = event_date + timedelta(days=day_start)
    end = event_date + timedelta(days=day_end)

    token_ret = np.log(_price_at(token_prices, end) / _price_at(token_prices, start))
    btc_ret = np.log(_price_at(btc_prices, end) / _price_at(btc_prices, start))
    return token_ret - btc_ret


def aggregate_statistics(events: pd.DataFrame) -> dict:
    """Compute the five summary metrics over a set of events with AR columns.

    Returned dict shape:
      n_events, pct_pre_negative, pct_post_negative, mean_pre, mean_post, p_value_pre
    """
    if len(events) == 0:
        return {
            "n_events": 0,
            "pct_pre_negative": None,
            "pct_post_negative": None,
            "mean_pre": None,
            "mean_post": None,
            "p_value_pre": None,
        }

    ar_pre = events["ar_pre"].to_numpy()
    ar_post = events["ar_post"].to_numpy()

    # One-sided t-test: H0 mean=0, H1 mean<0
    t_stat, p_two_sided = scipy_stats.ttest_1samp(ar_pre, popmean=0.0)
    p_one_sided = p_two_sided / 2 if t_stat < 0 else 1 - p_two_sided / 2

    return {
        "n_events": len(events),
        "pct_pre_negative": float((ar_pre < 0).mean()),
        "pct_post_negative": float((ar_post < 0).mean()),
        "mean_pre": float(ar_pre.mean()),
        "mean_post": float(ar_post.mean()),
        "p_value_pre": float(p_one_sided),
    }


def filter_ex_ecosystem(events: pd.DataFrame) -> pd.DataFrame:
    """Return events with ecosystem-style categories removed.

    Categories are matched case-insensitively against ECOSYSTEM_CATEGORIES.
    """
    cat_lower = events["category"].str.lower().str.strip()
    mask = ~cat_lower.isin(ECOSYSTEM_CATEGORIES)
    return events.loc[mask].reset_index(drop=True)


def pass_fail_decision(overall_stats: dict, team_subset_stats: dict) -> dict:
    """Apply the 5-metric Pass/Fail matrix and return a verdict.

    Verdict mapping:
      ≥ 4/5 pass → STRONG
      3/5 pass   → WEAK
      ≤ 2/5 pass → REJECT
    """
    t = PASS_FAIL_THRESHOLDS

    details = {
        "pct_pre_pass": (
            overall_stats["pct_pre_negative"] is not None
            and overall_stats["pct_pre_negative"] >= t["pct_pre_negative_pass"]
        ),
        "pct_post_pass": (
            overall_stats["pct_post_negative"] is not None
            and overall_stats["pct_post_negative"] >= t["pct_post_negative_pass"]
        ),
        "mean_pre_pass": (
            overall_stats["mean_pre"] is not None
            and overall_stats["mean_pre"] <= t["mean_pre_pass"]
        ),
        "p_value_pass": (
            overall_stats["p_value_pre"] is not None
            and overall_stats["p_value_pre"] < t["p_value_pass"]
        ),
        "team_subset_match": (
            team_subset_stats["mean_pre"] is not None
            and overall_stats["mean_pre"] is not None
            and team_subset_stats["mean_pre"] <= overall_stats["mean_pre"]
        ),
    }

    passed = sum(1 for v in details.values() if v)

    if passed >= 4:
        verdict = "STRONG"
    elif passed == 3:
        verdict = "WEAK"
    else:
        verdict = "REJECT"

    return {"verdict": verdict, "passed": passed, "details": details}


def enrich_events_with_returns(
    events: pd.DataFrame,
    prices_by_id: dict[str, pd.DataFrame],
    btc_id: str = "bitcoin",
) -> pd.DataFrame:
    """Attach ar_pre, ar_day, ar_post columns to each event.

    prices_by_id maps coingecko_id → price DataFrame (datetime index, 'price' col).
    Events whose coingecko_id is missing from prices_by_id are skipped (with warning).
    """
    btc_prices = prices_by_id[btc_id]

    rows = []
    for _, ev in events.iterrows():
        cg_id = ev["coingecko_id"]
        if cg_id not in prices_by_id:
            continue
        token_prices = prices_by_id[cg_id]
        event_date = ev["unlock_date"].to_pydatetime()

        try:
            ar_pre = compute_abnormal_return(token_prices, btc_prices, event_date, WINDOWS["pre"])
            ar_day = compute_abnormal_return(token_prices, btc_prices, event_date, WINDOWS["day"])
            ar_post = compute_abnormal_return(token_prices, btc_prices, event_date, WINDOWS["post"])
        except ValueError:
            continue

        rows.append({**ev.to_dict(), "ar_pre": ar_pre, "ar_day": ar_day, "ar_post": ar_post})

    return pd.DataFrame(rows)
