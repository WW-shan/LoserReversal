# Project Status Snapshot — crypto-alpha-portfolio

> Last updated: 2026-05-29 (post R1 Critical fixes on 4 retro-Ralph-Loop features)
> Current branch: main, 871 tests passing, ruff clean

## Where we are right now

### Completed phases

| Phase | Status | Verdict | Key result |
|---|---|---|---|
| Phase 0 | ✅ archived | LGTM 97/100 | HL client + fetcher + storage + vbt engine + walkforward util + pipeline |
| Phase 1 (v1) | ✅ archived | RED (misread) → re-classified **INCONCLUSIVE** | 3 trades / 100% win / Sharpe 1.93 but window/data sub-optimal |
| Phase 2 (v1) | ✅ archived | RED (misread) → re-classified **FILTER MISDESIGN** | IR=-4.83 because vlm-based filter selected 86%-profitable whale cohort |
| **Phase 1.5** | ✅ done | 🟡 **YELLOW (v1+D recommended)** | Switched: v1 (T-7) + stop=10% + cohort=team: Sharpe 0.59 / MaxDD -7.8% / 29 trades. Was v2 (T-30): Sharpe 0.61 / MaxDD -29% / 36 trades. |
| Phase 1.5 Ablations A/B/D | ✅ done | mixed | A robust [0.84,4.09] / B team-is-driver (Δ-0.02) / D mixed (v1 up, v2 collapse) |
| **Phase 1.5 D-ATR sweep** | ✅ done 2026-05-28 + R1 closed 2026-05-29 | 🟡 v2 rescued | v2+ATR(mult=1.5) Sharpe 0.521 / MaxDD -21.7% / n=34 — bootstrap CI [0.61, 3.40] robust. Same thesis as v1+D so doesn't unlock Phase 5 gate (gate needs cross-thesis). R1 fixed 3 Important (n_trades count, floor saturation claim, v1+ATR mult=1.5 reclassified INCONCLUSIVE-by-n). |
| Phase 1.5 Ablation C | ✅ done | 🔴 **REJECT** (bear-filter unusable) | Bear-only filter collapses sample to 1 trade/signal across 5 splits — `reports/phase-1-5-ablation-c.md`. BTC <200d windows too sparse layered with cohort=team. |
| **Phase 3 (reframed)** | ✅ done | 🔴 **RED (data_gap)** | Aggregate OOS Sharpe 0.42 / ann 5.23% / 45 trades — but 1h candle backfill only 90 days; re-run needed after backfill |
| Phase 2.5 Slice 1 | ✅ archived 2026-05-27 | 🟢 **GREEN with spec deviation** | academic wallet pool n=21 (target 200-500 unattainable on HL — see backend spec rule). 10-round 3-way review converged. |
| Phase 2.5 Slice 2 | ✅ archived 2026-05-27 | 🟢 5-round CCG retro converged | reverse_alpha_score = oversized × leverage × funding × time_bucket (smooth sigmoid + log-scale confidence). 64 tests. 4 spec rules added. |
| Phase 2.5 Slice 3 | ✅ archived 2026-05-27 | 🟢 3-round CCG retro converged | `src/wallet_pool/bot_exclusion.py` + `scripts/build_clean_wallet_pool.py` + 49 tests. 3 spec rules added (legacy kwarg validation routing, mixed valid/NaN dedup, Codex hang fallback). |
| Phase 2.5 Slice 4 (cluster v2 + cascade reversal) | not started | — | depends on Slice 2/3 archive |
| Phase 2.5 Slice 5 (walkforward verdict) | ✅ done 2026-05-28 + R1 closed 2026-05-29 | 🔴 INCONCLUSIVE after R1 PIT + OOS-only fixes | wallet_reverse_signal + walkforward harness + 22 new tests. R1 fixes: PIT score percentile, OOS-only aggregate, max-gap candle guard, _normalize_direction extended to liquidation/ADL/flip. After fixes: Sharpe -0.11, n=29 < CLT floor 30 (INCONCLUSIVE not RED). Reverse-fill thesis on 21-wallet pool yields too-small OOS sample. |
| Phase 4 Slice 1 (bot identification) | ✅ archived | LGTM | bot_detector + bot_pool 5-round CCG retro closure (2026-05-27) |
| Phase 4 Slice 2 (bot reverse signal) | ✅ archived 2026-05-27 | 🟢 3-round CCG retro converged | `src/bot_reverse/cluster_signal.py` + `scripts/run_bot_reverse_signal.py` + 53 tests. 2 spec rules added (aligned-bar state machine, atomic commit discipline). |
| Phase 4 Slice 3 (walkforward verdict) | ✅ done 2026-05-28 + R1 closed 2026-05-29 | 🔴 INCONCLUSIVE after R1 max-gap guard | bot_walkforward harness + 30 tests. R1 5 Critical fixed (NaN entry guard, _price_at max_gap_hours=26, OOS-only aggregate, point-in-time corrections). After fixes: default sweep cell n=1 (INCONCLUSIVE). Need 100+ wallet pool for real verdict. |
| Phase 5 portfolio composer | 🟡 implemented, gate NOT met | — | `src/portfolio/composer.py` (386 LOC) + signal_loader (129 LOC) + tests. ROADMAP gate: ≥2 GREEN/YELLOW signals — currently only 1 (Phase 1.5 v1+D YELLOW). Phase 2.5 Slice 1 GREEN is for the pool, not a signal yet. |
| Phase 5 paper signal generator | not started | — | depends on composer archive + gate |

### Open questions blocking progress

1. **Phase 1.5 救援 closed**: A robust (CI [0.84, 4.09]) / B team-is-driver / C REJECT-then-pivot-to-funding-regime / D mixed.
   Combined v1+D YELLOW remains best. Path to GREEN: needs cross-thesis portfolio (gated on Phase 2.5/3/4 success).
2. **Phase 3 RED revisit blocked on 1h candle backfill** (HL `/info` candleSnapshot 5000-cap → paginated rewrite needed; ~50-90 min wall time for full 70-token 3-year backfill). See `.ccg/tasks/phase-3-funding-arbitrage/blocker.md`. **Smart-search 2026-05-27 confirms: 90-day window + 45 OOS trades is below 100+ statistical floor — true data_gap, not thesis fail.**
3. **Phase 2.5 Slice 4 / Slice 5 decoupled per 2026-05-27 research**: Slice 5 walkforward can run on Slice 2's `reverse_alpha_score` independently at fill-level (1000s observations), not blocked on Slice 4 cluster v2. This unlocks parallel P1/P2 work.
4. **Phase 4 Slice 2 archived but un-verified**: Signal generator complete; alpha verdict in Phase 4 Slice 3 walkforward. Per smart-search, must include (N,W) sensitivity sweep.
5. **Phase 5 implemented before gate met** (only 1 YELLOW signal in inventory vs required ≥2). Gate-check happens when P1/P2/P3/P5 lands.

## What still needs to be done (priority order)

### Track 1 — Phase 1.5 救援 — ✅ CLOSED 2026-05-27

All 4 ablations done. Final outcome:

| # | Ablation | Verdict |
|---|---|---|
| A | Bootstrap CI on v2 OOS Sharpe | ✅ robust, CI [0.84, 4.09] |
| B | Fix cohort = team | ✅ team-is-driver (Δ-0.02 — confirms hypothesis) |
| C | BTC < 200d MA bear-only filter | 🔴 REJECT — sample collapses to 1 trade/signal |
| D | Per-trade -10% stop loss | ✅ mixed — v1 improved, v2 collapsed |
| D-ATR | ATR-adaptive stop | ✅ comparison in `reports/phase-1-5-ablation-d-atr.md` |
| E | Cross-thesis portfolio | ⏸ blocked, requires Phase 3 + Phase 2.5 GREEN |

Best Phase 1.5 signal: **v1+D (T-7 short + 10% stop + team cohort) → YELLOW** (Sharpe 0.59 / MaxDD -7.8% / 29 trades). Cannot reach GREEN standalone; needs cross-thesis combination (Phase 5).

### Track 2 — Phase 3 candle backfill + re-validation

| Slice | Status |
|---|---|
| 1 — funding backfill + `funding_extreme_v1` signal | ✅ done (commits `f983554` → `9521c15`) |
| 2 — backtest + grid sweep + Fix R1 | ✅ done (commits `b029320` → `c039f1c`) |
| 3 — walk-forward + verdict | ✅ done (commits `8181193` → `6d70038`) — RED with data_gap caveat |
| 4h walkforward revision | ✅ done (`e35260c`) |
| **Follow-up — extend 1h candle backfill to 2023-05** | 🚧 needs paginated `backfill_candles.py` rewrite per `.ccg/tasks/phase-3-funding-arbitrage/blocker.md` (smart-search 2026-05-27 documented strategy) |
| **Follow-up — re-run walk-forward on full 3-year data** | pending #1 |

Verdict thresholds (single-venue directional, not cross-exchange neutral):
- GREEN: walk-forward OOS Sharpe ≥ 1.2 AND annualized ≥ 20%
- YELLOW: Sharpe ∈ [0.5, 1.2) AND annualized ≥ 10%
- RED: Sharpe < 0.5 OR negative annualized

### Track 3 — Phase 2.5 (academic wallet rebuild)

| Slice | Code | Tests | CCG retro closure | Archived |
|---|---|---|---|---|
| 1 — Academic wallet pool builder | ✅ | ✅ 49 tests | ✅ 10-round 3-way converged 2026-05-27 | ✅ |
| 2 — Multi-feature reverse signal | ✅ 358 LOC + 254 LOC CLI | ✅ 64 tests | ✅ 5-round 3-way converged 2026-05-27 | ✅ |
| 3 — Bot exclusion filter | ✅ | ✅ 49 tests | ✅ 3-round 3-way converged 2026-05-27 | ✅ |
| 4 — Cluster v2 + cascade reversal | ❌ not started | — | — | ❌ |
| 5 — Walkforward + verdict | ❌ not started | — | — | ❌ |

### Track 4 — Phase 4 (bot reverse, independent thesis)

| Slice | Code | Tests | CCG retro closure | Archived |
|---|---|---|---|---|
| 1 — Bot identification refinement | ✅ 303 LOC | ✅ | ✅ 5-round 3-way converged 2026-05-27 | ✅ |
| 2 — Bot reverse signal | ✅ | ✅ | 🟡 Codex review pass; Claude review hung 3× via codeagent-wrapper; subagent not run | ❌ |
| 3 — Walkforward + verdict | ❌ not started | — | — | ❌ |

### Track 5 — Phase 5 (portfolio + paper) — gated on ≥2 GREEN/YELLOW signals

| Slice | Code | Gate met? | CCG retro closure | Archived |
|---|---|---|---|---|
| 1 — Portfolio composer | ✅ 386 LOC + 129 LOC loader | ❌ currently 1/2 (v1+D YELLOW) | review exists | ❌ |
| 2 — Paper signal generator | ❌ not started | — | — | ❌ |

Phase 5 only meaningful when ≥2 phases reach GREEN/YELLOW (cross-thesis diversification per Q4 literature). Slice 1 implementation existed before gate met; archive deferred until cumulative signal inventory satisfies gate.

## 2026-05-27 Smart-Search Failed-Case Investigation

Investigated 5 failed/unclear cases via smart-search. Evidence at
`/tmp/smart-search-evidence/2026-05-27-failed-cases/01-05.json` (reproducible —
re-run smart-search to regenerate). Key reclassifications:

| Failed Case | Prior Read | Smart-Search Finding | Reclassified Root Cause |
|---|---|---|---|
| Phase 3 funding RED | thesis 失败 | 100+ trades needed; 34 folds → 12% power | **data_gap + entry threshold too strict**, not thesis fail |
| Phase 1.5 D mixed (v2 崩) | 10% stop wrong size | ATR-adaptive outperforms fixed % for crypto long holds | **固定 % stop 错** — ATR is textbook answer |
| Phase 1.5 Ablation C deferred | BTC candle 不足 | BTC<200d SMA has lag + whipsaw + 24/7 issues | **SMA suboptimal regardless** — funding/F&G/vol regime is better |
| Phase 2.5 n=21 power | wallet-level n=21 too small | n=20 OOS folds → 12% power; bootstrap CI is correct tool | **fill-level walkforward** (1000s observations), not wallet-level |
| Phase 4 bot N/W design | needs academic precedent | No hyperparameter; behavioral patterns + (N,W) sweep | **sensitivity sweep**, current N=3/W=30min reasonable |

## Recommended next-session order (revised 2026-05-27 post smart-search)

Now organized by ROI + dependency unlock, not original ROADMAP order:

| ID | Task | Tokens | Unblocks Phase 5 gate? |
|---|---|---|---|
| #15 (P3) | Phase 1.5 Ablation D-ATR full walkforward (rescue v2) | 30-50k | ✓ cheapest bet |
| #13 (P1) | Phase 4 Slice 3 walkforward + (N,W) sweep + bootstrap CI | 80-120k | ✓ |
| #14 (P2) | Phase 2.5 Slice 5 walkforward (fill-level, skip Slice 4) | 80-120k | ✓ |
| #17 (P5) | Phase 1.5 Ablation C — funding-regime filter (not BTC SMA) | 40-60k | ✓ (combo with v1+D) |
| #16 (P4) | Phase 3 1h candle paginated backfill + walkforward re-run | 50-80k + 90min wall | independent track |
| #18 (P6) | Phase 2.5 Slice 4 cluster v2 + cascade reversal (innovation) | 100-150k | independent track |
| #19 (P7) | Phase 5 paper signal generator | 80-100k | gated on ≥2 GREEN/YELLOW |

**Phase 5 gate status**: 1/2 (Phase 1.5 v1+D YELLOW). Any of P1/P2/P3 reaching
cross-thesis YELLOW+ satisfies gate. **P3 (D-ATR sweep) does NOT unlock gate**
— v2+ATR is same Phase 1.5 unlock thesis as v1+D, only cross-thesis verdicts
(Phase 4 Slice 3, Phase 2.5 Slice 5, Phase 3 re-run) move the count from 1 → 2.
D-ATR sweep is still the lowest-cost discovery (verified v2 rescue-able to
YELLOW Sharpe 0.521 with ATR mult=1.5).

## Reference documents

| Path | What it contains |
|---|---|
| `docs/research/literature-review.md` | Academic evidence: 11 + 6 = 17 smart-search-sourced findings; Part A unlock, Part B wallet, Part C Phase 1.5 救援 (new) |
| `docs/research/phase-1-5-diagnostic.md` | YELLOW 5-root-cause analysis + 5 救援 ablation specs (NEW this update) |
| `docs/research/status-snapshot.md` | This file |
| `docs/research/raw-search/dr-*.json` | Raw smart-search outputs (6 deep research queries) |
| `/tmp/smart-search-evidence/2026-05-27-failed-cases/01-05.json` | **2026-05-27 failed-case research evidence (5 queries)** |
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
