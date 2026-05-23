ROLE_FILE: /Users/ww/.claude/.ccg/prompts/codex/reviewer.md

# Phase 1.5 Slice 1 — Code Review

## CRITICAL: Read-only

NO write permission. Output a review report only.

## Working directory
`/Users/ww/Project/crypto-alpha-portfolio`

## What was implemented

Slice 1 — Data Enrichment for Phase 1.5 (academic-tuned unlock strategy):

1. Extended `data/seed/parse_emissions.py` to capture `vesting_type` ∈ {cliff, step, linear} per event
2. Extended `WINDOW_START` to 2023-01-01 so older events fall in scope
3. Added `vesting_type` to `UNLOCK_COLUMNS` / `UNLOCK_SCHEMA` in `src/infra/storage.py`
4. New `scripts/backfill_candles.py` CLI — fetches HL 1d candles from 2023-01-01 → now for every HL-perp token in unlocks
5. New tests covering the above
6. Real-data refresh: ran the new pipeline, expected 800-2000 unlock events with vesting_type populated, 20+ tokens with 2023-now 1d candles

## Reading list

- `.ccg/tasks/phase-1.5-unlock-academic-tuned/plan.md`
- `.ccg/tasks/phase-1.5-unlock-academic-tuned/prompts/slice-1-builder.md` (the spec the builder followed)
- `docs/research/literature-review.md` Part A (academic spec)

## Commits to review

Use `git log --oneline -15` to see the new commits. Use `git show <sha>` for each.

## What to check

### Plan alignment
- All scope items implemented (`vesting_type` capture, `WINDOW_START` to 2023, storage schema, `backfill_candles.py`, tests)?
- Nothing outside scope (signals / backtests / reports untouched)?
- Commit granularity ~8 small TDD-paired commits, no monolithic commit?

### Correctness
- `vesting_type` aggregation key: does step/linear with the same date+token+category stay separate from cliff (per spec)?
- Are linear events correctly expanded to daily rows with vesting_type=linear on every row?
- Real numbers: what does the actual parquet contain? `python -c "import pandas as pd; df = pd.read_parquet('data/parquet/unlocks.parquet'); print(df.shape, df['vesting_type'].value_counts().to_dict(), df['category'].value_counts().to_dict())"`
- Does ≥ 800 rows requirement hold? If not, why not, and is it acceptable (e.g., the fork upstream only has 310 protocols, of which many have no HL perp)?
- Candles: are at least 20 HL-perp tokens covered back to 2023? Run `python -c "..."` to verify.

### Code quality
- UTC tz-aware throughout, no naive datetimes?
- Pagination limits respected (MAX_PAGES=100 on candles, OK for 1d 3-year fetches)?
- Per-token exception handling in `backfill_candles.py` — does one bad token abort the run?
- Storage schema migration: existing tests still pass?
- Ruff clean? Pytest count ≥ 180?

### Tests
- TDD pairs (`test(...)` commit precedes `feat(...)` commit per logical change)?
- Tests actually check the new behavior, not just mock pass-through?
- `parse_emissions` test covers all 3 vesting types (cliff / step / linear) and a mixed-vesting case where two same-date entries with different vesting types stay as separate rows?

### Production readiness
- Backfill script is idempotent (`--missing-only` skip works)?
- Failure modes documented (one bad token → warning, not crash)?
- No silent data loss (any drop of a row should be logged with the reason)?

## Calibration

Phase 0 / 1 / 2 precedent says fix **Critical + Important + Minor** before next slice. Only Info-tagged polish may be deferred.

## Output format

### Strengths
[Specific things done well, file:line.]

### Issues

#### Critical (Must Fix)
[Bugs, data loss, broken functionality, spec violations.]

#### Important (Should Fix)
[Missing pieces, edge case gaps, test quality.]

#### Minor (Nice to Have)
[Style, docs polish.]

For each: file:line + what + why + how-to-fix.

### Assessment

**Ready to merge into Slice 2?** [Yes | No | With fixes]

**Reasoning:** [2-3 sentences.]
