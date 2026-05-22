ROLE_FILE: /Users/ww/.claude/.ccg/prompts/codex/builder.md

# Phase 1 Slice 2 — Fix Review Findings (Round 2)

## CRITICAL: Anti-monitor directive
- Do NOT tail/ps/grep. Start fixing IMMEDIATELY.

## Working directory
`/Users/ww/Project/crypto-alpha-portfolio`

Use `uv run` for validation.

## Background

Round 2 review. Round 1 fixed 1 Critical + 6 Warnings; this round addresses 1 new Critical + 2 Warnings introduced or partially-fixed by Round 1.

The previous round changed how the portfolio aggregates equity (leading=init_cash, trailing=ffill), but two reporting/scoping bugs surfaced:

```
n_tokens (config field) = 8       ← events with surviving filters
backtested token count   = 7      ← LISTA's parquet is missing
portfolio start equity   = $70k   ← only counts 7 included tokens
```

The report's wording promises "sum across all attempted tokens" but actually sums only backtested tokens — confusing the reader about capital allocation.

## Fixes (3 commits expected)

### Fix 1 — Capital accounting consistency (CRITICAL)

**File**: `scripts/run_unlock_backtest.py`

The cleanest fix is **option A: report what we actually do, in clear language**. Do NOT add failed-token $10k cash to the equity sum (that's a bigger change with its own gotchas).

Specifically:

1. Track and surface **both** counts in the report and in the returned dict:
   - `n_candidate_tokens` = `len(tokens)` (events.token.unique() after filters)
   - `n_backtested_tokens` = `len(token_stats)` (tokens that successfully fetched candles)
2. Rename the existing `n_tokens` field in the returned dict to `n_candidate_tokens`. Add `n_backtested_tokens`.
3. Config table should show both, plus `n_failed_tokens = n_candidate_tokens - n_backtested_tokens`. Failed tokens listed by name if any.
4. Update the report `portfolio_model` line to be exact:

   > Per-token init_cash assumed for **backtested** tokens only; leading gaps = init_cash (cash held); trailing gaps = last equity (position held); portfolio = sum across backtested tokens. Failed-fetch tokens are NOT included in the portfolio capital base.

5. Decision Gate Check section should show the n_backtested figure in its row (not n_candidate).

### Fix 2 — `_failed_tokens` module-global → local

**File**: `scripts/sweep_unlock_params.py`

1. Remove module-level `_failed_tokens: set[str] = set()` declaration at line 24.
2. Inside `run_sweep`, declare `failed_tokens: set[str] = set(config.skip_tokens or ())`.
3. Update all references inside the function. Confirm no test/import references `_failed_tokens`.

### Fix 3 — Update report text accuracy (covered by Fix 1's wording update)

This is folded into Fix 1's portfolio_model rewrite. No separate file change.

## Workflow

3 commits:
1. `fix(scripts): report candidate vs backtested token counts separately`
2. `refactor(scripts): scope sweep failed_tokens cache to run_sweep`
3. (optional) `docs(reports): correct portfolio_model wording for failed tokens` — fold into commit 1 if minimal.

## Acceptance

- `uv run python scripts/run_unlock_backtest.py --report /tmp/unlock_e2e_v3.md`
  - Config table shows `n_candidate_tokens`, `n_backtested_tokens`, and `n_failed_tokens` separately
  - If LISTA still fails: `failed_tokens: ['LISTA']` listed
  - `portfolio_model` line matches Fix 1's exact text
- `uv run python scripts/sweep_unlock_params.py --report /tmp/unlock_sweep_v3.md` exits 0
- `uv run pytest -q` → 101+ tests pass
- `uv run ruff check src tests scripts` clean

## Out of scope

- Including failed-token $10k as cash in portfolio sum (not a bug given option A above)
- New tests (still scripts-only)
- Walk-forward (Slice 3)

## Completion

Execution Report with files changed, commit SHAs, final pytest output (last 3 lines), final ruff output, 5-line excerpt from new report showing `n_candidate_tokens` vs `n_backtested_tokens` + updated `portfolio_model` wording.

Then EXIT.
