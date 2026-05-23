# Phase 1.5 — Academic-tuned Unlock Strategy (Plan)

> Reading the literature: `docs/research/literature-review.md` Part A
> Reading the ROADMAP: `docs/research/loser-reversal-indicator/ROADMAP.md` Phase 1.5 section
> Goal: turn the INCONCLUSIVE Phase 1 v1 verdict into a real GREEN / YELLOW / RED with academic parameters.

## Context

Phase 1 was a sub-optimal implementation of a thesis with 87-90% academic confidence:
- Keyrock 16k+ events: 90% negative
- Kim SSRN 2026: 88.5% pre-unlock short profit (52 events, T-72h window)
- SmartKarma: 1% unlock ≈ -0.3% weekly drop, strongest cluster T-2 → T+3
- 6thman 5,000 events: <1% no effect; 1-5% significant; >10% 2.4× sharper drop

Phase 1 problems (now well-understood):
1. Window T-7 too short — academics recommend T-30 / T-2→T+3 / T-72h windows
2. HL candle data sparse — most coverage starts 2026-02-21, so 9/14 events lost entry point
3. signal v2 (T+3→T+14 reversal long) was never implemented
4. No category bucketing (team -25% vs ecosystem -5% drawdown)
5. Only 126 events from one source (DefiLlama fork) — academic studies use 5k-16k

## Goal

Re-execute Phase 1 with academic-tuned parameters and:
- Adequate candle history (back to 2023-01)
- Multi-source events (1000+ target)
- 5 signal versions (4 short windows + 1 reversal long)
- Per-category and per-size grid sweep
- Walk-forward + multi-signal portfolio

## Slice breakdown (5)

### Slice 1 — Data Enrichment
**Goal**: get the data we need before any signal coding.

1. Backfill HL 1d candles from 2023-01-01 → now for all tokens that appear in any unlock event
2. Fetch DefiLlama emissions-adapters fork (Omni-Chain-Protocols/emissions-adapters has 310 protocols, vs the 37-protocol older fork that yielded 126 events)
3. Reparse with the existing `parse_emissions.py` extended to:
   - Capture vesting type (cliff / step / linear) per event
   - Capture recipient category granularity (team vs investor vs ecosystem etc.)
4. Verify counts:
   - Expected: ≥ 800 events post-filter (target 1000-2000)
   - Coverage of categories: team / insiders / investor / airdrop / publicSale / privateSale / ecosystem
5. Update `data/parquet/unlocks.parquet` schema:
   - Add `vesting_type: string` (one of: cliff, step, linear)
   - Keep existing columns
6. Update `data/parquet/candles/*.parquet` to span 2023-01-01 → now wherever HL has data

**Out of scope**: signals, backtests (Slice 2+)

**Pass criteria**:
- ≥ 800 unlock events with vesting_type populated
- ≥ 75% of HL-perp unlock events have ≥ 60 days of pre-event candle history. Lower
  bar caused by structural HL listing-after-unlock for 55 / 532 events (10%). Audit
  parquet at `data/parquet/event_coverage.parquet` documents the per-event status;
  Slice 2 signals must filter on `coverage_status == 'ok'` before generating entries.

### Slice 2 — 5 Signal Versions
1. `unlock_v1_short_T-7_T0` (existing v1, baseline)
2. `unlock_v2_short_T-30_T0` (Keyrock long swing)
3. `unlock_v3_short_T-2_T+3` (SmartKarma strongest cluster)
4. `unlock_v4_short_T-72h_T0` (Kim SSRN 72-hour)
5. `unlock_v5_reversal_long_T+3_T+14` (Keyrock reversal long — never implemented)

Each as a separate function in `src/signals/`. Tests for each.

### Slice 3 — Grid Sweep (3-dimensional)
- Window: {v1, v2, v3, v4, v5}
- Size threshold: {0.01, 0.02, 0.05, 0.10}
- Category: {team, team+investor, all}

Plus cliff vs linear sub-sweep.

### Slice 4 — Walk-forward + Multi-signal portfolio
- 3 splits expanding
- Best IS config per signal → OOS measure
- Weight allocator across surviving signals

### Slice 5 — Pass/Kill verdict + report
- `reports/phase1_5_unlock_academic.md`
- ROADMAP Phase 1.5 section updated with verdict

## Pass criteria (whole Phase 1.5)

- **绿灯 (GREEN)**: ≥ 1 signal walk-forward OOS Sharpe ≥ 1.0 AND n_trades ≥ 50
- **黄灯 (YELLOW)**: OOS Sharpe ∈ [0.3, 1.0) AND n_trades ≥ 30
- **红灯 (RED)**: all signals OOS Sharpe < 0.3 OR n_trades < 30 — this time it's a true thesis fail

## Non-negotiable constraints

- Python 3.11+, `from __future__ import annotations`, 100-char lines, UTC tz-aware
- Strict TDD: tests first commit, impl second
- `uv run pytest -q` ≥ baseline (170 → grow with each slice)
- `uv run ruff check src tests scripts` clean
- One commit per logical change (no monolithic commits)
- Builder must NOT archive; Claude archives after final LGTM + ROADMAP update
- Anti-monitor directive in every builder prompt

## Three-way review per slice

For each slice:
1. Codex re-review (background)
2. superpowers `requesting-code-review` subagent (background)
3. Claude semantic review

Wait for ALL THREE → merge findings → ONE builder fix run with union.
Fix ALL findings (Critical + Important + Minor) before next slice.
