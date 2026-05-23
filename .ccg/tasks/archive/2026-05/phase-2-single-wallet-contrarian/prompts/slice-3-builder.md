ROLE_FILE: /Users/ww/.claude/.ccg/prompts/codex/builder.md

# Phase 2 Slice 3 — Cluster Signal + Walk-Forward + Pass/Kill Verdict

## CRITICAL: Anti-monitor directive
- Do NOT tail/ps. Start coding IMMEDIATELY.
- **Do NOT archive the task this slice.** Claude will archive after final verdict + ROADMAP update.
- Strict commit granularity (TDD per task).

## Working directory
`/Users/ww/Project/crypto-alpha-portfolio`

Use `uv run` for execution.

## Goal

Add cluster signal (N≥3 anti-alpha wallets opening same direction within W minutes → reverse) and walk-forward validation. Output Phase 2 final Pass/Kill verdict.

**Expected outcome (from single-wallet data)**: Single-wallet trade-level IR = -4.83 portfolio-wide. ROADMAP says "If cluster IR < 1.0 → Kill entire wallet-reverse line, skip Phase 4". Likely RED, but verdict must come from walk-forward OOS evidence, not assumption.

## Scope (DO NOT exceed)

Create:
- `src/signals/wallet_cluster_v1.py` — cluster signal generator
- `scripts/run_wallet_cluster_backtest.py` — single-config cluster backtest
- `scripts/run_wallet_walkforward.py` — walk-forward + Pass/Kill verdict
- `tests/signals/test_wallet_cluster_v1.py` — unit tests on cluster logic
- `tests/scripts/test_run_wallet_walkforward.py` — unit tests on walkforward runner (date filter, verdict logic)

Modify:
- `scripts/run_wallet_reverse_backtest.py` if adding `date_start`/`date_end` filter (for walkforward IS/OOS splits — mirror Phase 1 Slice 3 pattern)
- `docs/research/loser-reversal-indicator/ROADMAP.md` — Phase 2 verdict line at end (Claude will do this, but builder may prepare a `verdict_summary` field)

## Architectural decisions (use these, do NOT redesign)

### Cluster signal (`wallet_cluster_v1.py`)

```python
def cluster_signal(
    pool_fills: dict[str, pd.DataFrame],   # address → fills DataFrame
    coin_universe: set[str] | None = None,  # default: all HL perp coins
    min_wallets: int = 3,                   # N
    window_minutes: int = 30,                # W
    holding_hours: float = 4.0,
    coin_filter: Iterable[str] | None = None,
) -> dict[str, pd.DataFrame]:               # coin → events DataFrame
    """
    For each coin, find timestamps where ≥ min_wallets distinct addresses open
    same-direction (Long or Short) within a rolling window_minutes window.
    Emit reverse signal: short the coin if ≥ N opened Long, long if ≥ N opened Short.
    """
```

Per-coin events DataFrame:
- `entry_time` (UTC tz-aware)
- `exit_time` = entry_time + holding_hours
- `side` ("long" or "short" — the REVERSE direction)
- `cluster_size` (number of wallets participating)
- `confidence_score` = `cluster_size / min_wallets` (or similar)

Filter:
- Same retail-size filter as `wallet_reverse_v1`: per-fill notional ∈ [$1k, $200k]
- Only count `Open Long` / `Open Short` (not `Close`)
- Dedup: if same wallet opens same direction multiple times in window, count as 1
- Cluster cooldown: after cluster fires at t0, ignore same-coin clusters for `holding_hours` (no overlapping reverse positions per coin)

### Sweep grid (in `run_wallet_cluster_backtest.py` if needed)

- `min_wallets ∈ {3, 5, 7, 10}` (N)
- `window_minutes ∈ {15, 30, 60}` (W)
- `holding_hours ∈ {1, 4, 12, 24}`
- 4 × 3 × 4 = 48 combos for walkforward IS optimization

Single-config `run_wallet_cluster_backtest.py` runs ONE (N, W, holding) combo.

### Walk-forward (`run_wallet_walkforward.py`)

Mirror Phase 1 Slice 3 pattern:
1. Load all wallet fills (`read_fills` for each pool wallet)
2. Date range: `[earliest_fill, latest_fill]`
3. `walk_forward_splits(start, end, n_splits=3, mode="expanding", min_train_days=120, test_days=30)` (with fallback)
4. For each split:
   - IS: run cluster_backtest for grid of (N, W, holding) on IS window. Pick best by trade_level_ir among eligible (n_trades ≥ 100). Fallback: `positive_trades_median → positive_trades_any → zero_trade_fallback`.
   - OOS: run cluster_backtest on OOS with IS best config. Capture trade_level_ir, daily_sharpe, max_dd, n_trades.
5. Aggregate OOS:
   - `oos_ir_mean`, `oos_ir_min`, `oos_max_dd_worst`, `oos_n_trades_total`
   - `is_oos_decay = (mean_is_ir - mean_oos_ir) / mean_is_ir`
6. Verdict (per ROADMAP):
   - **GREEN** (single-wallet pass): `oos_ir_mean ≥ 1.2 AND oos_n_trades_total ≥ 100 AND oos_max_dd_worst ≥ -0.25`
   - **YELLOW** (cluster pass): `oos_ir_mean ≥ 1.0 AND oos_n_trades_total ≥ 100 AND oos_max_dd_worst ≥ -0.25`
   - **RED**: everything else
   - Reason: `data_gap` (n_trades=0), `insufficient_sample` (0 < n < 50), `oos_ir_below_yellow` (< 1.0), `max_drawdown_breach`, etc.

### Report (`reports/wallet_reverse_walkforward.md`)

Same structure as Phase 1 Slice 3:
- Verdict at top with reason
- Data span
- Walk-Forward Config
- Per-Split Results table (IS best config, IS IR, IS n_trades, OOS IR, OOS n_trades, OOS max_dd, eligible_in_is, is_selection_mode)
- Aggregate OOS Stats (with `n/a NO SAMPLE` rendering for zero-trade splits)
- Decision paragraph

### Decision Gate Check semantics

When `oos_n_trades_total == 0`: aggregate Sharpe/IR/MaxDD show `n/a` + `NO SAMPLE`. n_trades row shows `0 FAIL`. Verdict = RED reason `data_gap`.

## Conventions

- `from __future__ import annotations`
- 100-char lines
- argparse with validation
- UTC tz-aware throughout
- No emoji
- TDD (test → impl per file)
- Commit per task (8-10 commits expected)

## Workflow

1. `feat(scripts): date-range filter on wallet reverse backtest config` (mirror Phase 1 Slice 3)
2. `test(signals): wallet_cluster_v1 signal cases`
3. `feat(signals): wallet_cluster_v1 N+W cluster signal`
4. `feat(scripts): cluster backtest single-config runner`
5. `test(scripts): walkforward runner verdict + date filter cases`
6. `feat(scripts): wallet walk-forward validation runner`
7. `docs(roadmap): Phase 2 verdict from walk-forward run` (Claude may do this manually)
8. `chore(reports): seed wallet walkforward report` (auto-generated)

## Acceptance

- `uv run python scripts/run_wallet_walkforward.py --top-wallet-n 50 --report /tmp/wallet_wf.md` exits 0
- Report has Verdict label + reason at top
- Per-split table with `is_selection_mode` column
- `uv run pytest -q` passes (~165+ tests)
- `uv run ruff check src tests scripts` clean
- ROADMAP.md Phase 2 section updated (or marked TODO for Claude)

## Test cases (unit)

`tests/signals/test_wallet_cluster_v1.py` (5+):
1. Single coin, 3 wallets opening Long within 30min → 1 cluster event (reverse SHORT)
2. 2 wallets only → no cluster
3. Mixed Long/Short within window → independent clusters per direction
4. Same wallet opening same direction multiple times → counted as 1
5. Cluster cooldown: 2 clusters on same coin within holding_hours → only first fires
6. Window 30min, fills exactly 30min apart → boundary inclusion / exclusion (document choice)

`tests/scripts/test_run_wallet_walkforward.py` (4+):
1. Date filter inclusivity (mirror Phase 1)
2. IS fallback selection modes (eligible / positive_trades_median / etc.)
3. Verdict logic for various aggregate stats
4. Report rendering with `n/a NO SAMPLE` for zero-trade splits

## Out of scope

- Sybil cluster detection (Phase 4)
- Live execution
- ML features

## Completion

Execution Report with:
- files changed, commits (8-10)
- final pytest output, ruff output
- walkforward verdict + key numbers (mean OOS IR, total OOS trades, worst MaxDD, decay%)
- 10-line excerpt of walkforward report showing Verdict + Aggregate OOS Stats

Then EXIT. Do NOT archive. ROADMAP update will be done by Claude.
