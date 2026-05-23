ROLE_FILE: /Users/ww/.claude/.ccg/prompts/codex/builder.md

# Phase 2 Slice 3 — Fix Review Findings

## CRITICAL: Anti-monitor
- Do NOT tail/ps. Start IMMEDIATELY.
- Do NOT archive.
- **STRICT TDD**: test before impl for each fix. Strict commit granularity.

## Working directory
`/Users/ww/Project/crypto-alpha-portfolio`

## Background

Slice 3 scored Codex 77/100 NEEDS_FIX + subagent "With fixes". 3 Critical + 4 Important + 4 Warning + 6 Minor. Subagent caught a duplicate-event bug that Codex missed; both must be fixed.

## Fixes (priority order)

### 🔴 Critical 1 — Duplicate cluster events on identical timestamps

**File**: `src/signals/wallet_cluster_v1.py:127-145`

**Bug**: when N wallets fire at the **exact same** UTC timestamp, the per-row loop appends N candidate events. Cooldown filter at line 156 groups by `entry_time` but keeps the whole group. Result: `(entry_time, side)` duplicated N times → downstream `n_trades` inflated 3×, IR diluted, fees over-charged.

**Fix**: deduplicate by `(entry_time, side)` keeping FIRST occurrence, applied BEFORE cooldown:

```python
# After building candidates DataFrame:
candidates = candidates.drop_duplicates(subset=["entry_time", "side"], keep="first")
```

OR change the per-timestamp loop to emit at most one candidate per (timestamp, side) combination.

**Test** (add to `tests/signals/test_wallet_cluster_v1.py`):
`test_cluster_dedup_when_wallets_fire_at_identical_timestamp`:
- 3 wallets opening Long at exactly `2026-01-01T00:00:00Z`
- Expect exactly **1** cluster event with `cluster_size=3, side="short"`
- Assert no duplicate `(entry_time, side)` rows in output

### 🔴 Critical 2 — Cluster emit semantics (max cluster_size not first-reached)

**File**: `src/signals/wallet_cluster_v1.py:127-145`

**Bug**: When 4 wallets fire Long within 25 min (window=30min), N=3 threshold is reached on the 3rd wallet → emit `cluster_size=3` at 3rd wallet's timestamp. Should emit `cluster_size=4` at the 4th wallet's timestamp (or at the rolling-window maximum).

**Fix options** (choose one):
- (a) Scan with rolling window. For each (coin, direction), at each timestamp count distinct wallets in the past `window_minutes`. Emit at the timestamp where rolling distinct count is at LOCAL MAX within the cluster.
- (b) Within a single firing window (defined by cooldown), choose the timestamp with MAXIMUM `cluster_size` rather than the earliest.

Either is acceptable. Document which in the docstring. Add test:

`test_cluster_emits_max_cluster_size_when_more_wallets_join_within_window`:
- 4 wallets opening Long at t=0, t=10, t=20, t=25 (all within window=30)
- Expect emit at t=25 with `cluster_size=4` (or at t=20 with size=3 if option a finds different max)

### 🔴 Critical 3 — Walk-forward fallback silent degradation

**File**: `scripts/run_wallet_walkforward.py:185-222` (`_walk_forward_splits_with_fallback`) and `_write_report`

**Bug**: Fallback shrinks `min_train_days 120→30` and `test_days 30→15` silently. Report shows `min_train_days: 30 (effective)` next to `test_days: 30 (configured)` — confusing.

**Fix**:
1. Add `_log("[WARN] walk-forward fallback: requested (n_splits=X, min_train_days=Y, test_days=Z); using (a, b, c)")` whenever ANY dimension is reduced.
2. Update report Walk-Forward Config section to show **all 3 dimensions** as `configured / effective` pairs:
   - `n_splits: 3 (effective: 3)` — even when unchanged for consistency
   - `min_train_days: 120 (effective: 30)` — show shrinkage
   - `test_days: 30 (effective: 15)` — show shrinkage
3. If any effective < configured: prepend a `> [WARN] walk-forward fallback used` banner below the Verdict line.

### 🟡 Important 4 — `insufficient_oos_trades` documentation

**File**: `scripts/run_wallet_walkforward.py:_verdict` docstring (around line 395-410)

Document the 5-tier verdict reason taxonomy in `_verdict()` docstring:
- `data_gap`: oos_n_trades_total == 0
- `insufficient_sample`: 1 <= n < 50
- `insufficient_oos_trades`: 50 <= n < 100
- `oos_ir_below_yellow`: n >= 100 but oos_ir_mean < 1.0
- `max_drawdown_breach`: drawdown worse than -0.30
- `thresholds_not_met`: residual catch-all

### 🟡 Important 5 — Cluster cooldown picks max cluster_size

Folds into Critical 2 if you choose option (b). Otherwise need separate fix.

### 🟡 Warning 6 — `coin_universe` parameter

**File**: `src/signals/wallet_cluster_v1.py:26`

`coin_universe` parameter exists but no caller wires it. Either:
- Wire it through from cluster backtest CLI (add `--coin-filter` flag)
- OR drop from signature with deprecation comment

Drop is simpler — no caller needs it. Remove parameter + update tests + docstring.

### 🟡 Warning 7 — Underscore helper cross-module use

**File**: `scripts/run_wallet_walkforward.py:31-33`

Imports `_filter_fills_by_end`, `_filter_fills_by_start`, `_coerce_utc_timestamp`, `_backtest_freq` from `run_wallet_reverse_backtest.py`. Per Phase 1 lesson (promoted private fns to public), do the same here:

- Promote 4 functions: `filter_fills_by_end`, `filter_fills_by_start`, `coerce_utc_timestamp`, `backtest_freq`
- Update all references in both scripts and tests

### 🔵 Minor 8 — Test organization

**Files**: `tests/scripts/test_run_wallet_walkforward.py:53-181`

Move tests for `run_wallet_reverse_backtest` date-filter (lines 53-201) → `tests/scripts/test_run_wallet_reverse_backtest.py`.
Move tests for `run_wallet_cluster_backtest` → new `tests/scripts/test_run_wallet_cluster_backtest.py`.

### 🔵 Minor 9 — Report Config consistency

**File**: `scripts/run_wallet_walkforward.py` (Config section render)

Show all 3 dimensions (n_splits, min_train_days, test_days) as `configured (effective: N)` paired pattern.

Skip the remaining minors (cluster_size metadata only, quadratic perf, TDD git order) — not blocking, acceptable risk for current data scale.

## Workflow

~10-12 commits, strict TDD pairing:

1. `test(signals): cluster dedup at identical timestamp`
2. `fix(signals): dedup cluster events on (entry_time, side)`
3. `test(signals): cluster emits max cluster_size in window`
4. `fix(signals): emit cluster at max-size timestamp within window`
5. `feat(scripts): walk-forward fallback warning logs`
6. `feat(scripts): report walk-forward config configured-vs-effective pairs`
7. `docs(scripts): _verdict reason taxonomy docstring`
8. `refactor(signals): drop unused coin_universe parameter`
9. `refactor(scripts): promote private helpers (filter_fills_*, coerce_utc_timestamp, backtest_freq) to public`
10. `test(scripts): split walkforward tests by target script`
11. (optional) `chore(reports): regenerate walkforward report with new config section`

## Acceptance

- `uv run python scripts/run_wallet_walkforward.py --top-wallet-n 50 --report /tmp/wallet_wf_v2.md` exits 0
- Report shows:
  - Configured n_splits/min_train_days/test_days each with `(effective: N)` pair
  - `> [WARN] walk-forward fallback used` banner if any effective < configured
- New cluster signal: 3 wallets at same timestamp → exactly 1 event with cluster_size=3
- 4 wallets at t=0/10/20/25 → 1 event at t=20 or t=25 with cluster_size=4 (per chosen option)
- `uv run pytest -q` → ≥ 165 + new pin tests pass
- `uv run ruff check src tests scripts` clean
- No remaining underscore-prefix imports across modules in scripts/

## Out of scope

- Confidence-weighted position sizing (Phase 4)
- Quadratic perf optimization (acceptable for 50 wallets)
- TDD git history rewriting (commits already exist)
- Phase 4 sybil cluster

## Completion

Execution Report with files changed, all commits, final pytest output, ruff output, new report excerpt showing:
- Updated Walk-Forward Config (configured vs effective)
- `> [WARN] walk-forward fallback used` banner (if triggered)
- Verdict reason (still RED data_gap unless cluster fix changes anything — unlikely with current data)

Then EXIT. Do NOT archive.
