"""Auto-build curated unlock CSV from public APIs.

Method: detect supply jumps from CoinGecko market_caps history
(implied_supply = market_cap / price). A jump ≥1% on a single day is
treated as an unlock event. Category is left as 'unknown' for manual
labelling; has_hl_perp is derived from Hyperliquid universe.

Why this works without a vesting-schedule dataset:
- CoinGecko free tier returns daily prices + market_caps for 365 days
- supply = mcap / price (exact on each daily snapshot)
- A genuine unlock distribution shows up as a discrete supply step
- 1% is conservative enough to filter staking rewards / minor minting

Usage (from repo root):
    uv run python data/seed/build_seed.py [--max-tokens N] [--threshold 0.01]
"""
from __future__ import annotations

import argparse
import csv
import json
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import requests
from tenacity import retry, stop_after_attempt, wait_exponential

REPO_ROOT = Path(__file__).resolve().parents[2]
OUT_CSV = REPO_ROOT / "data" / "seed" / "unlocks_curated.csv"
CACHE_DIR = REPO_ROOT / "data" / "cache" / "seed_build"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

CG_BASE = "https://api.coingecko.com/api/v3"
HL_INFO = "https://api.hyperliquid.xyz/info"

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=2, min=2, max=30))
def _cg_get(path: str, params: dict | None = None) -> dict:
    r = requests.get(f"{CG_BASE}{path}", params=params, headers={"User-Agent": UA}, timeout=30)
    if r.status_code == 429:
        raise RuntimeError("rate limited")
    r.raise_for_status()
    return r.json()


def hl_universe() -> list[str]:
    r = requests.post(HL_INFO, json={"type": "meta"}, headers={"Content-Type": "application/json"}, timeout=20)
    r.raise_for_status()
    return [u["name"] for u in r.json()["universe"]]


def hl_mcap_proxy() -> dict[str, float]:
    """Use Hyperliquid 24h notional volume as a market-cap proxy for ranking."""
    r = requests.post(HL_INFO, json={"type": "metaAndAssetCtxs"}, headers={"Content-Type": "application/json"}, timeout=20)
    r.raise_for_status()
    meta, ctxs = r.json()
    out: dict[str, float] = {}
    for u, c in zip(meta["universe"], ctxs):
        try:
            out[u["name"]] = float(c.get("dayNtlVlm") or 0)
        except (TypeError, ValueError):
            out[u["name"]] = 0.0
    return out


def cg_coins_list() -> list[dict]:
    cache = CACHE_DIR / "coins_list.json"
    if cache.exists():
        return json.loads(cache.read_text())
    data = _cg_get("/coins/list")
    cache.write_text(json.dumps(data))
    return data


def cg_top_market_caps(ids: list[str]) -> dict[str, float]:
    """Batch-fetch market caps to disambiguate symbol collisions."""
    out: dict[str, float] = {}
    for i in range(0, len(ids), 100):
        chunk = ids[i:i + 100]
        data = _cg_get("/coins/markets", {"vs_currency": "usd", "ids": ",".join(chunk), "per_page": 250})
        for row in data:
            out[row["id"]] = float(row.get("market_cap") or 0)
        time.sleep(1.5)
    return out


def resolve_coingecko_id(symbol: str, coins_list: list[dict], mcap_table: dict[str, float] | None = None) -> str | None:
    """Pick the best CoinGecko id for an HL ticker.

    Strategy: collect all coins with matching symbol → choose the one with
    highest market cap (the canonical token, not low-volume namesakes).
    """
    candidates = [c for c in coins_list if c["symbol"].upper() == symbol.upper()]
    if not candidates:
        return None
    if len(candidates) == 1:
        return candidates[0]["id"]
    if mcap_table is None:
        return candidates[0]["id"]
    return max(candidates, key=lambda c: mcap_table.get(c["id"], 0))["id"]


def cg_market_chart(coingecko_id: str, days: int = 365) -> tuple[dict, bool]:
    """Return (chart, fetched_from_network). Caller throttles only on cache miss."""
    cache = CACHE_DIR / f"chart_{coingecko_id}_{days}d.json"
    if cache.exists():
        return json.loads(cache.read_text()), False
    data = _cg_get(f"/coins/{coingecko_id}/market_chart", {"vs_currency": "usd", "days": days, "interval": "daily"})
    cache.write_text(json.dumps(data))
    return data, True


def detect_unlock_events(chart: dict, threshold: float = 0.01) -> list[dict]:
    """Return unlock candidates: list of {date, unlock_pct} dicts.

    Filter rules:
    - day-over-day implied-supply increase ≥ threshold
    - drops are ignored (those are usually data noise, not 'reverse unlocks')
    - duplicates within 3 days of each other are merged to the largest
    """
    prices = chart.get("prices", [])
    mcaps = chart.get("market_caps", [])
    if len(prices) < 30 or len(mcaps) != len(prices):
        return []
    supply = []
    for (ts, p), (_, m) in zip(prices, mcaps):
        if p and p > 0:
            supply.append((ts, m / p))
    events: list[dict] = []
    for i in range(1, len(supply)):
        prev_ts, prev_s = supply[i - 1]
        ts, s = supply[i]
        if prev_s <= 0:
            continue
        pct = (s - prev_s) / prev_s
        if pct >= threshold:
            events.append({
                "ts": ts,
                "date": datetime.fromtimestamp(ts / 1000, tz=timezone.utc).strftime("%Y-%m-%d"),
                "unlock_pct": round(pct, 6),
            })
    # merge events within 3 days, keeping max
    merged: list[dict] = []
    for e in events:
        if merged and (e["ts"] - merged[-1]["ts"]) <= 3 * 86400 * 1000:
            if e["unlock_pct"] > merged[-1]["unlock_pct"]:
                merged[-1] = e
        else:
            merged.append(e)
    return merged


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-tokens", type=int, default=80, help="cap on HL tokens to scan (by 24h vol)")
    ap.add_argument("--threshold", type=float, default=0.01, help="min supply jump pct to count as unlock")
    ap.add_argument("--min-pct", type=float, default=0.015, help="min unlock_pct kept in final CSV")
    args = ap.parse_args()

    print("[1/5] fetching Hyperliquid universe + volume...")
    hl_tickers = hl_universe()
    hl_vol = hl_mcap_proxy()
    print(f"      {len(hl_tickers)} perp tickers")

    # rank by 24h notional volume, take top N
    ranked = sorted(hl_tickers, key=lambda t: hl_vol.get(t, 0), reverse=True)[:args.max_tokens]
    print(f"      top {len(ranked)} by 24h vol → first 10: {ranked[:10]}")

    print("[2/5] loading CoinGecko coin index...")
    coins_list = cg_coins_list()
    print(f"      {len(coins_list)} known CoinGecko ids")

    # Build candidate id table for symbol disambiguation
    sym_to_candidates = defaultdict(list)
    for c in coins_list:
        sym_to_candidates[c["symbol"].upper()].append(c["id"])

    # Disambiguate by market cap for any symbol with >1 candidate among ranked
    ambig_ids = []
    for t in ranked:
        cands = sym_to_candidates.get(t.upper(), [])
        if len(cands) > 1:
            ambig_ids.extend(cands)
    ambig_ids = list(set(ambig_ids))
    print(f"[3/5] disambiguating {len(ambig_ids)} ids by market cap...")
    mcap_table = cg_top_market_caps(ambig_ids) if ambig_ids else {}

    # Resolve final symbol → id
    resolved: list[tuple[str, str]] = []
    for t in ranked:
        cid = resolve_coingecko_id(t, coins_list, mcap_table)
        if cid:
            resolved.append((t, cid))
    print(f"      resolved {len(resolved)} / {len(ranked)} tokens to CoinGecko ids")

    print("[4/5] scanning supply jumps (~6 req/min target on cache miss)...")
    all_events: list[dict] = []
    for i, (sym, cid) in enumerate(resolved):
        try:
            chart, fetched = cg_market_chart(cid, days=365)
        except Exception as e:
            print(f"      [{i+1:3}/{len(resolved)}] {sym:10} {cid:30}  ERR {type(e).__name__}: {str(e)[:60]}")
            continue
        events = detect_unlock_events(chart, threshold=args.threshold)
        kept = [e for e in events if e["unlock_pct"] >= args.min_pct]
        for e in kept:
            all_events.append({
                "token": sym,
                "coingecko_id": cid,
                "unlock_date": e["date"],
                "unlock_pct": e["unlock_pct"],
                "category": "unknown",
                "has_hl_perp": True,
            })
        flag = "fetched" if fetched else "cached "
        print(f"      [{i+1:3}/{len(resolved)}] {sym:10} {cid:30}  {flag}  events={len(events):2}  kept={len(kept):2}")
        if fetched:
            time.sleep(10.5)

    print(f"[5/5] writing {len(all_events)} events → {OUT_CSV}")
    all_events.sort(key=lambda r: r["unlock_date"])
    with OUT_CSV.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["token", "coingecko_id", "unlock_date", "unlock_pct", "category", "has_hl_perp"])
        w.writeheader()
        for row in all_events:
            w.writerow({**row, "has_hl_perp": str(row["has_hl_perp"]).lower(), "unlock_pct": f"{row['unlock_pct']:.4f}"})

    print("\ndone. categories='unknown' — review and label manually for dual-track analysis.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
