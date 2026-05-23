ROLE_FILE: /Users/ww/.claude/.ccg/prompts/codex/reviewer.md

# Phase 2 Slice 3 — Code Review

## CRITICAL: Read-only

NO write permission.

## Working directory
`/Users/ww/Project/crypto-alpha-portfolio`

## What to review

8 new commits introduced by Slice 3 (`5971bfa..ccbaf14`):
- `5971bfa feat(scripts): date-range filter on wallet reverse backtest config`
- `b7001ed test(signals): wallet_cluster_v1 signal cases`
- `cf5e717 feat(signals): wallet_cluster_v1 N+W cluster signal`
- `22a6415 feat(scripts): cluster backtest single-config runner`
- `6c0c8e3 test(scripts): walkforward runner verdict + date filter cases`
- `8453197 feat(scripts): wallet walk-forward validation runner`
- `ffff022 fix(scripts): relax wallet walkforward split fallback`
- `ccbaf14 chore(reports): seed wallet walkforward report`

Inspect:
- `src/signals/wallet_cluster_v1.py`
- `scripts/run_wallet_cluster_backtest.py`
- `scripts/run_wallet_walkforward.py`
- `scripts/run_wallet_reverse_backtest.py` (date-range filter addition)
- `tests/signals/test_wallet_cluster_v1.py`
- `tests/scripts/test_run_wallet_walkforward.py`
- `reports/wallet_reverse_walkforward.md`

## Spec

`.ccg/tasks/phase-2-single-wallet-contrarian/prompts/slice-3-builder.md`

## Suspicious result — INVESTIGATE

Builder reports verdict **RED (data_gap)** with `oos_n_trades_total = 0`. This mirrors Phase 1 Slice 3 outcome (also data_gap due to sparsity). Investigate:
1. Is `data_gap` correctly distinguished from `insufficient_sample` (1-99 trades) vs `oos_ir_below_yellow` (real underperformance)?
2. Why 0 OOS trades when there are 116,618 fills in cache? The cluster signal needs:
   - ≥3 wallets opening same direction within 30min on same coin
   - Within OOS window (30 days)
   - Walk-forward grid optimization should find SOME config with non-zero OOS trades unless cluster constraints are too strict.
3. Did `ffff022 fix(scripts): relax wallet walkforward split fallback` mask a real bug? Look at what got relaxed.
4. Direction sanity: ≥3 wallets opening Long → reverse SHORT, ≥3 Short → reverse LONG.
5. Cluster cooldown logic: same-coin clusters within holding_hours should fire only once.

## Review focus

### Critical
1. **Cluster signal correctness**: walk through `cluster_signal()` for an N=3, W=30min scenario with 4 wallets opening Long over 25 min. Should emit 1 reverse SHORT event with cluster_size=4. Verify in tests.
2. **Walk-forward + verdict**: same as Phase 1 Slice 3 patterns (n_trades=0 → data_gap, etc.). Verify zero-trade aggregate metrics render `n/a NO SAMPLE`, not numeric.
3. **Date-range filter**: shouldn't `date_end` be exclusive (per Phase 1 Slice 3 lesson)?
4. **IS fallback selection**: did builder copy the Phase 1 Slice 3 pattern (eligible → positive_trades_median → positive_trades_any → zero_trade_fallback)?
5. **`ffff022` relaxation**: what was relaxed? Is the relaxation principled or a workaround for an unrelated bug?

### Warnings
6. Cluster cooldown: 2 same-coin clusters within `holding_hours` — does the second one fire? Should NOT.
7. Confidence weighting: how is `cluster_size` used in position sizing? Or is it just metadata?
8. ROADMAP.md not yet updated (builder spec says "Claude will do this") — verify the spec captured a `verdict_summary` field for Claude to use.

### Info
9. Test coverage on cluster runner / walkforward runner

## Output format

```
## Phase 2 Slice 3 Review

### Summary
[overall + ROOT CAUSE of 0 OOS trades]

### Critical Issues (count: N)
- ...

### Warnings (count: N)
- ...

### Info (count: N)
- ...

### Positive Notes
- ...

### Scoring
- Spec coverage: XX/20
- Correctness: XX/20
- Result validity: XX/20  (is OOS=0 a real reality or a code bug?)
- Code quality: XX/15
- Style consistency: XX/15
- Process compliance: XX/10  (commit granularity, archive policy)

TOTAL: XX/100

RECOMMENDATION: [LGTM / NEEDS_FIX / BLOCK]
```

Read-only.
