ROLE_FILE: /Users/ww/.claude/.ccg/prompts/codex/reviewer.md

# Phase 2 Slice 2 — Code Review

## CRITICAL: Read-only

NO write permission.

## Working directory
`/Users/ww/Project/crypto-alpha-portfolio`

## What to review

Only 1 commit added by Slice 2: `5897ba2 feat: add wallet reverse backtest slice`

`git show 5897ba2` to inspect. Read also:
- `src/signals/wallet_reverse_v1.py`
- `scripts/fetch_pool_fills.py`
- `scripts/run_wallet_reverse_backtest.py`
- `scripts/sweep_wallet_holding.py`
- `reports/wallet_reverse_v1_backtest.md`
- `reports/wallet_reverse_v1_sweep.md`

## Spec

`.ccg/tasks/phase-2-single-wallet-contrarian/prompts/slice-2-builder.md`

## Suspicious result — INVESTIGATE

Builder ran real data on 50 wallets / 116,618 fills / 28,196 trades:
- Portfolio Sharpe = **-27.13** (extremely abnormal — typical Sharpe is -3 to +3)
- MaxDD = -27.21%
- win_rate = 43.17%
- total_return = -27.2% over ~4 months

Investigate:
1. Is the Sharpe calculation correct? Builder uses `sharpe_ratio(returns, periods_per_year("1h"))` = sqrt(8760) ≈ 93.6 annualization factor. Are `returns` actually 1-hour pct_changes, OR sparse trade-level returns? If sparse, the annualization factor is wrong.
2. ROADMAP's `IR >= 1.2` is implicitly trade-level annualized. Is the implementation comparable? If not, Slice 3 decision gate is meaningless.
3. Direction sanity check: confirm "Open Long" → SHORT reverse entry, "Open Short" → LONG reverse entry. Builder report shows side="short"/"long" assignments — check signal logic in `wallet_reverse_v1.py`.

## Review focus

### Critical
1. **Sharpe scale problem**: validate 1h-based Sharpe calculation. Recommend alternative (trade-level or daily-resample). Check if MaxDD calculation also affected.
2. **Commit granularity violation**: prompt explicitly listed 6-8 separate commits (`test(signals): ...`, `feat(signals): ...`, etc.). Single commit prevents independent review.
3. Direction correctness: verify Open Long → SHORT, Open Short → LONG actually implemented and tested.
4. Aggregation correctness: when 35/50 wallets skipped, are they tracked? Per Phase 1 lesson, n_attempted vs n_backtested should be separately reported.

### Warnings
5. n_skipped_wallets=35 means 70% wallets dropped. Funnel doesn't say WHY (fills below retail size? no Open fills? no candles?). Per-wallet skip reason should be tracked and reported.
6. Test coverage on `run_wallet_reverse_backtest.py` and `sweep_wallet_holding.py` — none added per builder's spec interpretation (e2e validation). Is signal-level test sufficient?
7. `data/parquet/fills/` is gitignored; verify builder did NOT commit any generated fills.

## Output format

```
## Phase 2 Slice 2 Review

### Summary
[overall + ROOT CAUSE of Sharpe -27]

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
- Result validity: XX/20  (is the -27 Sharpe a real strategy failure or a calculation bug?)
- Code quality: XX/15
- Style consistency: XX/15
- Process compliance: XX/10  (commit granularity)

TOTAL: XX/100

RECOMMENDATION: [LGTM / NEEDS_FIX / BLOCK]
```

Investigate with code reading + actual numbers. Determine if the -27 Sharpe is:
(A) A real strategy underperformance signal (just a different scale than ROADMAP's 1.2)
(B) A calculation bug (e.g. sparse returns × dense periods_per_year)
(C) A data/signal bug (e.g. direction reversed wrong)

Read-only.
