# Project Status Snapshot — crypto-alpha-portfolio

> Last updated: 2026-05-26
> Current branch: main, 370 tests passing, ruff clean

## Where we are right now

### Completed phases

| Phase | Status | Verdict | Key result |
|---|---|---|---|
| Phase 0 | ✅ archived | LGTM 97/100 | HL client + fetcher + storage + vbt engine + walkforward util + pipeline |
| Phase 1 (v1) | ✅ archived | RED (misread) → re-classified **INCONCLUSIVE** | 3 trades / 100% win / Sharpe 1.93 but window/data sub-optimal |
| Phase 2 (v1) | ✅ archived | RED (misread) → re-classified **FILTER MISDESIGN** | IR=-4.83 because vlm-based filter selected 86%-profitable whale cohort |
| **Phase 1.5** | ✅ archived | 🟡 **YELLOW** | Best: v2 (T-30→T0) OOS Sharpe 0.61, 36 trades, 75% win, +110% return / 2.5yr OOS |
| Phase 1.5 Ablation A | ✅ done | bootstrap CI **[0.84, 4.09]** | v2 trade-level Sharpe is statistically distinguishable from zero at 95%; split-3 dependent |
| **Phase 3 (reframed)** | ✅ done | 🔴 **RED** (data_gap caveat) | Aggregate OOS Sharpe 0.42, ann 5.23%, 45 trades — but 1h candle backfill only 90 days vs 3-year funding history; needs candle re-backfill before final |
| Phase 1.5 B/C/D | 🚧 pending | — | bootstrap robust → continue with B (fix cohort=team), C (BTC<200d MA), D (-10% stop) |
| Phase 2.5 | not started | — | academic-rebuilt wallet contrarian (5 slices spec) |
| Phase 4 | not started | — | bot reverse (independent thesis after Phase 2.5 bot exclusion) |
| Phase 5 | not started | — | portfolio composer + paper trading |

### Two open questions blocking progress

1. **Phase 1.5 YELLOW: can we move it to GREEN?** Ablation A done (robust, CI [0.84, 4.09]). B/C/D pending. Combined target: Sharpe ≥ 1.0 AND MaxDD ≤ 20%.
2. **Phase 3 RED revisit**: needs 1h candle backfill extension to 2023-05 (currently only 2026-02 → 2026-05). With 3-year candle data, walkforward can use proper 270/180 splits.

## What still needs to be done (priority order)

### Track 1 — Phase 1.5 救援 B/C/D (parallel-safe, no infrastructure changes)

| # | Ablation | Method | Expected output | Status |
|---|---|---|---|---|
| A | Bootstrap CI on v2 OOS Sharpe | 1000× resample 36 trade returns | CI [0.84, 4.09] — robust | ✅ done |
| **B** | Fix cohort = `team` (delete IS selection) | rerun walk-forward with `--fix-cohort team` | tells if IS-cohort-search is overfitting | 🚧 next |
| **C** | BTC < 200d MA filter (bear-only short entries) | gate signal on BTC trend | tests Q2/Q5 regime hypothesis | pending |
| **D** | Per-trade -10% stop loss | wrap `run_backtest` with stop_loss | should cut MaxDD from -29% to ~-12% | pending |
| E | (defer) Cross-thesis portfolio | requires Phase 3 + Phase 2.5 | true uncorrelated alpha | blocked |

After B/C/D run: write `docs/research/phase-1-5-ablation-results.md` with comparison.
If v2 with B+C+D reaches Sharpe ≥ 1.0 → upgrade to GREEN.

### Track 2 — Phase 3 candle backfill + re-validation

| Slice | Status |
|---|---|
| 1 — funding backfill + `funding_extreme_v1` signal | ✅ done (commits `f983554` → `9521c15`) |
| 2 — backtest + grid sweep + Fix R1 | ✅ done (commits `b029320` → `c039f1c`) |
| 3 — walk-forward + verdict | ✅ done (commits `8181193` → `6d70038`) — RED with data_gap caveat |
| **Follow-up — extend 1h candle backfill to 2023-05** | 🚧 blocked on `scripts/backfill_candles.py` rerun |
| **Follow-up — re-run walk-forward on full 3-year data** | pending #1 |

Verdict thresholds (single-venue directional, not cross-exchange neutral):
- GREEN: walk-forward OOS Sharpe ≥ 1.2 AND annualized ≥ 20%
- YELLOW: Sharpe ∈ [0.5, 1.2) AND annualized ≥ 10%
- RED: Sharpe < 0.5 OR negative annualized

### Track 3 — Phase 2.5 (academic wallet rebuild)

5 slices from `ROADMAP.md` Phase 2.5 section:
1. Academic wallet pool builder (account_value $1k-$100k cohort, leverage ≥5x, realized_loss_rate ≥50%)
2. Multi-feature reverse signal (oversized × leverage × funding × time bucket)
3. Bot exclusion filter (graph + behavior; save excluded set for Phase 4)
4. Cluster signal v2 + cascade reversal
5. Walk-forward + verdict

### Track 4 — Phase 4 (bot reverse, independent thesis)

Uses Phase 2.5 bot-excluded set. 3 slices:
1. Bot identification refinement
2. Bot reverse signal (separate from retail reverse)
3. Walk-forward + verdict

### Track 5 — Phase 5 (portfolio + paper)

Only meaningful when ≥2 phases reach GREEN/YELLOW (cross-thesis diversification per Q4 literature).
2 slices:
1. Risk-parity portfolio composer
2. Paper signal generator + 24-48h run

## Decision points awaiting user

1. **Run Phase 1.5 救援 ablations first (Track 1)** before Phase 3? — recommended; gives verdict confidence before adding more strategies
2. **Continue Phase 3 from existing partial work** (Slice 1 done) — recommended; finishes the funding contrarian
3. **Should A-D ablations be one agent task or 4 separate?** — recommend one agent producing comparison report
4. **CryptoRank API key for unlock data expansion?** — currently using DefiLlama fork only; could expand to ~5000+ events

## Reference documents

| Path | What it contains |
|---|---|
| `docs/research/literature-review.md` | Academic evidence: 11 + 6 = 17 smart-search-sourced findings; Part A unlock, Part B wallet, Part C Phase 1.5 救援 (new) |
| `docs/research/phase-1-5-diagnostic.md` | YELLOW 5-root-cause analysis + 5 救援 ablation specs (NEW this update) |
| `docs/research/status-snapshot.md` | This file |
| `docs/research/raw-search/dr-*.json` | Raw smart-search outputs (6 deep research queries) |
| `docs/research/loser-reversal-indicator/ROADMAP.md` | Master plan with revised priorities + Phase 1.5/2.5 specs |
| `.ccg/tasks/archive/2026-05/phase-1.5-unlock-academic-tuned/` | Full slice prompts + plan + task.json |
| `.ccg/tasks/phase-3-funding-arbitrage/blocker.md` | Phase 3 reframed plan (HL-only contrarian) |
| `.ccg/goals/finish-all-phases.md` | Background agent prompt (partial completion, ran 4.1h before token limit) |

## Code modules (cumulative, as of 2026-05-24)

### Phase 0 infrastructure
- `src/infra/hyperliquid_client.py` — HL `/info` API client
- `src/infra/fetchers/{candles,funding,leaderboard,user_fills}.py` — data fetchers
- `src/infra/storage.py` — Parquet + DuckDB
- `src/infra/backtest/{engine,risk,walkforward,toy}.py` — vbt wrapper + risk primitives
- `src/infra/pipeline.py` — fetch→store→load→backtest orchestrator
- `src/infra/data_audit.py` — coverage audit (added in Phase 1.5)
- `src/infra/report.py` — markdown report writer

### Phase 1 / 1.5 unlock
- `src/signals/unlock_v1.py..unlock_v5.py` — 5 academic-window signal variants
- `src/signals/_unlock_common.py` — shared filter/emitter helper
- `src/signals/unlock_grid.py` — grid cell runner + registry
- `src/signals/unlock_walkforward.py` — per-signal walk-forward + portfolio composer
- `scripts/sweep_unlock_grid_v15.py` — 3-dim grid CLI
- `scripts/run_unlock_walkforward_v15.py` — walk-forward CLI

### Phase 2 wallet (v1 archived; v2.5 not started)
- `src/signals/wallet_reverse_v1.py`, `wallet_cluster_v1.py`
- `scripts/run_wallet_*.py`, `sweep_wallet_holding.py`, `build_wallet_pool.py`

### Phase 3 funding (60% done)
- `src/signals/funding_extreme_v1.py` — z-score contrarian signal ✅
- `scripts/backfill_funding.py` — HL funding history backfill ✅
- backtest + sweep + walk-forward — TODO

### Data layer
- `data/parquet/unlocks.parquet` — 1768 events (Phase 1.5 expanded)
- `data/parquet/candles/{TOKEN}_1d.parquet` — 55 tokens × 3.4 years
- `data/parquet/funding/{TOKEN}.parquet` — 30 tokens (Phase 3 seed)
- `data/parquet/event_coverage.parquet` — 532 HL-perp coverage audit
- `data/parquet/unlock_grid_v15.parquet` — 60 cells + 3 vesting sub-sweep
- `data/parquet/phase1_5_walkforward.parquet` — 5 signals × 5 splits + portfolio + aggregates
- `data/parquet/anti_alpha_wallets.parquet` — 500 wallets (Phase 2 v1 archived)
- `data/parquet/fills/{addr}.parquet` — 50 wallet fill histories (Phase 2 v1)

## Reports
- `reports/phase1_5_unlock_academic.md` — final Phase 1.5 verdict
- `reports/phase1_5_walkforward.md` — walk-forward detail
- `reports/phase1_5_grid_sweep.md` — IS grid sweep
- `reports/unlock_thesis_report.md` — original thesis-check (Phase 0 prep)
- `reports/unlock_v1_walkforward.md` — Phase 1 v1 (archived)
- `reports/wallet_reverse_v1_*.md` — Phase 2 v1 (archived)
- `reports/backtest_btc_sma10-30.md` — Phase 0 e2e smoke
