# Phase 2 — Single-Wallet Contrarian Implementation Plan

> Build on Phase 0 infrastructure. Identify persistently-losing HL wallets and
> backtest reverse-following them. Output Pass/Kill verdict for single-wallet
> and cluster-signal modes.

**Goal**: ship `signals/wallet_reverse_v1.py` + full backtest + walk-forward.
Output verdict that decides whether reverse-follow enters the final portfolio.

**Hypothesis (from ROADMAP)**:
- Persistently-losing retail wallets exhibit anti-alpha
- Reverse-following Top losers → positive Sharpe ≥ 1.2 single-wallet OOS
- Cluster signal (N≥3 simultaneous same-direction opens) → Sharpe ≥ 1.5

**Data source (de-risked via spike)**:
- `https://stats-data.hyperliquid.xyz/Mainnet/leaderboard` — public GET, no auth
- 36,894 wallets with PnL/ROI/Volume across 4 time windows (day/week/month/allTime)
- `userFills` / `userFillsByTime` POST `/info` — paginated fill history per wallet

**Tech stack** (from Phase 0):
- `infra.hyperliquid_client`, `infra.fetchers.{candles,funding}` — existing
- `infra.fetchers.{leaderboard,user_fills}` — NEW (Slice 1)
- `infra.storage` — DuckDB + Parquet (already supports custom write paths)
- `infra.backtest.{engine,risk,walkforward}` — existing

---

## Slices

### Slice 1: Data layer (wallet pool + fills fetchers)

**Files**:
- `src/infra/fetchers/leaderboard.py` — `fetch_leaderboard() -> DataFrame`
- `src/infra/fetchers/user_fills.py` — `fetch_user_fills(address, start, end) -> DataFrame` (paginated)
- `src/infra/storage.py` — add `read_wallets()` / `write_wallets_parquet()` + `read_fills(addr)` / `write_fills_parquet(addr)`
- `scripts/build_wallet_pool.py` — CLI: fetch leaderboard → filter anti-alpha candidates → write `data/parquet/anti_alpha_wallets.parquet`
- `tests/infra/test_leaderboard.py` — unit (mocked HTTP)
- `tests/infra/test_user_fills.py` — unit (mocked HTTP + pagination)

**Wallet filter heuristic** (Slice 1 default; tune in Slice 2 if needed):
- `pnl_allTime <= -10_000` (sustained loss, not just one bad day)
- `vlm_allTime >= 500_000` (enough trades to matter, not a one-shot wallet)
- `accountValue > 0` OR (`accountValue == 0 AND vlm_allTime >= 10M`) — exclude trivial wallets
- Take top 500 by `vlm_allTime` (active losers; size > frequency tradeoff)

**Acceptance**:
- Leaderboard fetch returns 30k+ rows with expected schema
- Wallet pool parquet has ≥ 200 wallets (matches ROADMAP Phase 2 target)
- `user_fills` correctly paginates beyond the 2000-fill cap
- 16+ tests pass; ruff clean

---

### Slice 2: Reverse backtest + holding-time sweep

**Files**:
- `src/signals/wallet_reverse_v1.py` — `reverse_signal(fills, holding_hours) -> (entries, exits)` per wallet × coin
- `scripts/run_wallet_reverse_backtest.py` — single-config e2e (one wallet or pool)
- `scripts/sweep_wallet_holding.py` — sweep holding ∈ {1h, 4h, 12h, 24h} × pool
- `tests/signals/test_wallet_reverse_v1.py`

**Signal logic**:
For each fill in wallet history:
- If `fill.dir == "Open Long"` → reverse entry as SHORT on `fill.coin` at `fill.time`
- If `fill.dir == "Open Short"` → reverse entry as LONG
- Exit `holding_hours` after entry (regardless of wallet's own close)
- Filter: `fill.sz * fill.px ∈ [$1k, $200k]` per ROADMAP (exclude whales + dust)
- Per-wallet portfolio_capital = `$10k`; assets aggregated equally across all reverse-followed wallets

**Stats per (wallet, holding_h)**:
- Reverse Sharpe (annualized)
- Sortino, MaxDD, n_trades, win_rate
- IR = reverse_PnL / std

**Sweep output** (`reports/wallet_reverse_sweep.md`):
- For each `holding_h`, top-K wallets by reverse Sharpe
- Decision Gate flag per ROADMAP passCriteria (n_trades ≥ 100, IR ≥ 1.2)

**Acceptance**:
- Backtest 500 wallets × 4 holdings runs successfully (≤ 30 min with cached candles)
- Output includes per-wallet IR table + sweep summary
- ruff + pytest clean

---

### Slice 3: Cluster signal + walk-forward + Pass/Kill

**Files**:
- `src/signals/wallet_cluster_v1.py` — cluster signal: when ≥ N anti-alpha wallets open same-direction on coin C within W minutes → reverse signal
- `scripts/run_wallet_cluster_backtest.py`
- `scripts/run_wallet_walkforward.py` — walk-forward (IS picks best N, W; OOS evaluates)
- `tests/signals/test_wallet_cluster_v1.py`

**Cluster signal logic**:
- Window `W ∈ {15min, 30min, 60min}` (CLI sweep)
- Threshold `N ∈ {3, 5, 7, 10}` (CLI sweep)
- Coin filter: only coins in HL perp universe
- Confidence weight: `sum(reverse_score_per_wallet)` for ranked sizing

**Walk-forward** (reuse `infra.backtest.walkforward.walk_forward_splits`):
- 3 expanding splits over fills time range
- IS: pick best (N, W, holding) by aggregate Sharpe
- OOS: evaluate on test window
- Pass/Kill verdict per `task.json.passCriteria`

**Verdict logic** (matches ROADMAP):
- GREEN: cluster OOS IR ≥ 1.5 AND n_trades ≥ 100
- YELLOW: IR 1.0-1.5 → low-weight candidate
- RED single-wallet IR < 1.0 → Kill, skip Phase 4 (sybil cluster)

**Acceptance**:
- Walk-forward runs across 3 splits
- Final verdict written to `reports/wallet_reverse_walkforward.md`
- ROADMAP.md Phase 2 section updated with verdict

---

## Pass/Kill criteria (Slice 3)

```yaml
single_wallet:
  pass:    OOS IR >= 1.2 (most top-N wallets)
  reject:  OOS IR < 0.5

cluster:
  green:   cluster OOS IR >= 1.5 AND n_trades >= 100
  yellow:  IR 1.0-1.5 → low weight in portfolio
  red:     IR < 1.0 → Kill entire wallet-reverse line, skip Phase 4
```

If RED on cluster: ROADMAP says skip Phase 4 (sybil) since it's a Phase 2 extension. Go directly to Phase 3 (funding arb).

---

## Conventions

- Python 3.11+, pandas, no premature abstraction
- TDD: test-first separate commits
- `from __future__ import annotations`
- 100-char lines
- UTC tz-aware datetimes
- No emoji in code or commits
- Builder/reviewer loop per Phase 1 lessons:
  - Builder writes + commits
  - Claude semantic review (read source, not just pytest)
  - Codex reviewer (parallel)
  - Wait both done, merge findings, one fix run
  - LGTM ≥ 90 → next slice
- **Do NOT archive without review approval** (Phase 1 incident)

## Risks + Mitigations

| Risk | Mitigation |
|---|---|
| 36k wallets × full fill history is huge | Slice 1 caps to top 500, dynamic top-N for sweep |
| HL `userFills` 2000 cap → many requests | Paginated `userFillsByTime` (already validated in spike) |
| Fills for low-activity wallets are stale | Filter requires `vlm_allTime >= 500k` |
| `closedPnl` accuracy may differ from reverse simulation | Backtest uses HL candle close at entry/exit timestamps, ignores `closedPnl` |
| Selection bias (leaderboard exists = surviving wallets) | Note in report; Phase 4 fixes via 链上 deposit-flow analysis |
| Walk-forward data sparsity (Phase 1 lesson) | Slice 1 takes 500 wallets × many months fills = much larger sample than Phase 1's 83 events |

## Out of scope

- Sybil cluster detection (Phase 4)
- Live execution (Phase 6)
- ML features on wallet behavior (Phase 4)
- Anti-frontrunning (Phase 5)
