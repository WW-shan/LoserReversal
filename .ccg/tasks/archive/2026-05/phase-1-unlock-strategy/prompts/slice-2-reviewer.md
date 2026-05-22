ROLE_FILE: /Users/ww/.claude/.ccg/prompts/codex/reviewer.md

# Phase 1 Slice 2 — Code Review

## CRITICAL: Read-only

You have NO write permission. Do NOT modify any file.

## Working directory
`/Users/ww/Project/crypto-alpha-portfolio`

## What to review

2 new commits introduced by Slice 2:
- `f28371d` feat(scripts): unlock backtest e2e runner
- `8e85f7f` feat(scripts): unlock param grid sweep

Use `git show f28371d 8e85f7f` and `cat scripts/run_unlock_backtest.py scripts/sweep_unlock_params.py` to inspect.

## Spec to validate against

The Slice 2 builder prompt: `.ccg/tasks/phase-1-unlock-strategy/prompts/slice-2-builder.md`. Read it for the architectural decisions (data flow, aggregation, CLI, sweep grid).

Phase 1 `passCriteria` (from `.ccg/tasks/phase-1-unlock-strategy/task.json`):
- in_sample_sharpe >= 1.0
- walk_forward_oos_sharpe >= 0.7
- max_drawdown <= 25%
- min_trades >= 30

The actual e2e run produced only n_trades=3 (default config). Sweep top result n_trades=2. **This is a red flag** — investigate WHY: filter too aggressive? signal mostly skipped? aggregation wrong? Don't accept "data is small" without checking the code.

## Review focus

### Critical (must-fix before Slice 3)
- **Aggregation correctness**: spec says "portfolio Sharpe = Sharpe of the summed equity curve across tokens". Verify the implementation actually sums equity curves correctly (reindex/ffill before sum) — NOT averages Sharpes, NOT concatenates trades.
- **n_trades discrepancy**: only 3 trades on 126 events is suspicious. Check:
  - Are events filtered too aggressively (multi-filter chain)?
  - Are tokens being skipped silently for the wrong reason (e.g. fetcher errors logged but eaten, leaving the token absent from `prices` dict)?
  - Is `unlock_short_signal` being called per-token correctly?
  - Is `entries.sum()` for each token > 0?
- **shortonly direction**: verify `BacktestConfig(direction="shortonly")` is actually used; otherwise the strategy is going LONG before a unlock and the Sharpe is meaningless.
- **DataFrame mutation**: scripts shouldn't mutate `events` or candle frames in-place.
- **Cache validity**: fetcher cache check — does it re-fetch if range gap, or silently use stale data?

### Warning
- Error messages on skipped tokens: do they say which token + why?
- Sortino can be NaN/inf when no negative returns; how is that handled in aggregation?
- CLI defaults match spec exactly?
- Sweep `--init-cash` / `--fees` / `--slippage` plumbed through to grid runs?
- Progress logging actually written to stderr (not stdout)?

### Info
- Naming, docstrings, type hints

## Output format

```
## Slice 2 Review

### Summary
[overall + verdict on whether n_trades=3 is a code bug or a data sparsity reality]

### Critical Issues (count: N)
- [issue, file:line, fix proposal]

### Warnings (count: N)
- [issue, file:line]

### Info (count: N)
- ...

### Positive Notes
- ...

### Scoring
- Spec coverage: XX/20
- Correctness: XX/20
- Code quality: XX/20
- Test quality: N/A (scripts, integration tested by real run)
- Style consistency: XX/20

TOTAL: XX/80 → normalize to XX/100

RECOMMENDATION: [LGTM / NEEDS_FIX / BLOCK]
```

Investigate the n_trades=3 issue with code inspection, not assumption. If code is fine, say so clearly.

Do NOT modify any file. Review only.
