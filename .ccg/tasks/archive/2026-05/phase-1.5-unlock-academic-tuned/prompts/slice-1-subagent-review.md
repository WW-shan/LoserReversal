ROLE_FILE: /Users/ww/.claude/.ccg/prompts/codex/reviewer.md

# Phase 1.5 Slice 1 — Code Review (Senior Reviewer Template)

## CRITICAL: Read-only

NO write permission. Output a structured review report only.

## Working directory
`/Users/ww/Project/crypto-alpha-portfolio`

## What Was Implemented

Slice 1 of Phase 1.5 (academic-tuned unlock strategy). Extended `data/seed/parse_emissions.py` to capture vesting type (cliff/step/linear) per event, widened scan window to 2023-01-01, fixed two parser bugs (fork-level supply totals + farming→community category canonicalization). Added `vesting_type` column to unlocks parquet schema. New `scripts/backfill_candles.py` CLI to backfill HL 1d candles from 2023-01 → now for every HL-perp token in unlocks.

Real data refresh outcome:
- 1773 unlock events (target ≥ 800, exceeded)
- vesting_types: step=1215, cliff=313, linear=245
- categories: insiders=574, noncirculating=479, privateSale=339, community=209, airdrop=104, publicSale=47, other=21
- 55 HL-perp 1d candle parquets, earliest 2023-01-01, latest 2026-05-23

## Requirements / Plan

`.ccg/tasks/phase-1.5-unlock-academic-tuned/plan.md` and
`.ccg/tasks/phase-1.5-unlock-academic-tuned/prompts/slice-1-builder.md`

## Git Range to Review

**Base:** `a37087a` (the goals commit before Slice 1 started)
**Head:** `4dcc82d`

```bash
git diff --stat a37087a..4dcc82d
git diff a37087a..4dcc82d -- data/seed/parse_emissions.py src/infra/storage.py scripts/backfill_candles.py
git diff a37087a..4dcc82d -- tests/
```

(parquet/csv diffs are binary or huge — skim the row counts via `python -c "import pandas as pd; print(pd.read_parquet('data/parquet/unlocks.parquet').shape)"`)

## What to Check

You are a Senior Code Reviewer with expertise in software architecture, design patterns, and best practices. Review the work against its plan and identify issues before they cascade into Slice 2.

**Plan alignment:**
- Does the implementation match the slice-1-builder.md scope (vesting_type, schema migration, backfill CLI, tests)?
- Are deviations justified improvements (fork-supply fallback, community category) or problematic departures?
- Is all planned functionality present?

**Code quality:**
- Are the per-token failure paths in `backfill_candles.py` truly non-fatal (one bad token doesn't abort)?
- UTC tz-aware time arithmetic in `_existing_covers_start`?
- `parse_emissions._infer_total_supply` (or whichever helper handles fork-supply fallback) — does it accept the right ranges (catastrophic to mis-pick a million-token vs billion-token constant)?
- `aggregate_rows` includes vesting_type in the dedup key — verified for linear events that produce multiple daily rows?
- Storage migration: existing tests still pass; schema is backward-incompatible (older parquet without vesting_type) — is that intentional?

**Architecture:**
- Sound design decisions for the data layer?
- Integration risk: any downstream code reading `unlocks.parquet` that assumed the old column set (test_storage.py, signal/unlock_v1.py)?

**Testing:**
- TDD pairs: every `feat(...)` preceded by `test(...)` in commit order?
- Tests verify real behavior (not just mock pass-through)?
- Coverage of: cliff/step/linear vesting; mixed-vesting same-date no-merge; fork-supply fallback; community category canonicalization; daily linear retention; backfill CLI HL-token filter; backfill `--missing-only` skip; backfill per-token exception handling?

**Production readiness:**
- Idempotency of `backfill_candles.py` (re-running shouldn't corrupt)?
- Logging on failures (warnings printed, not just swallowed)?
- Documentation: is there ANY hint that the schema added `vesting_type` (commit message is sufficient, or do we need a docstring update)?
- 75.7% coverage of ≥60 pre-event days (slightly below 80% spec target) — is the cause structural (HL listings post-dating early unlock events for some tokens like MANTA/W/VIRTUAL) or fixable?

## Calibration

Phase 0 / 1 / 2 precedent says fix Critical + Important + Minor before next slice. Only Info-tagged polish may be deferred.

Categorize by actual severity. Acknowledge what was done well before listing issues — accurate praise helps trust in the rest of the feedback.

## Output Format

### Strengths
[Specific things done well, file:line.]

### Issues

#### Critical (Must Fix)
[Bugs, data loss risks, broken functionality, spec violations.]

#### Important (Should Fix)
[Missing pieces, architecture problems, test gaps.]

#### Minor (Nice to Have)
[Style, docs polish.]

For each: file:line + what's wrong + why it matters + how to fix.

### Recommendations
[Code quality / architecture / process improvements.]

### Assessment

**Ready to merge into Slice 2?** [Yes | No | With fixes]

**Reasoning:** [2-3 sentences technical assessment.]

## Critical Rules

DO:
- Categorize by actual severity (not everything is Critical)
- Be specific (file:line, not vague)
- Explain WHY each issue matters
- Acknowledge strengths
- Give a clear verdict

DON'T:
- Say "looks good" without checking diffs
- Mark nitpicks as Critical
- Give feedback on code you didn't actually read
- Be vague ("improve error handling")
- Avoid giving a clear verdict
