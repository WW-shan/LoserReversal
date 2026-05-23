ROLE_FILE: /Users/ww/.claude/.ccg/prompts/codex/reviewer.md

# Phase 1.5 Slice 1 — Fix R1 Re-Review

## CRITICAL: Read-only

NO write permission. Output review report only.

## Working directory
`/Users/ww/Project/crypto-alpha-portfolio`

## What to verify

Slice 1 Fix R1 closed 9 reviewer findings. Confirm:

1. **Critical #1 path traversal** — `scripts/backfill_candles.py` now validates token (regex `^[A-Z0-9:_-]{1,32}$`) + interval (allowlist) + resolved path stays under `CANDLES_DIR`. Both code branches (auto-discovery from unlocks + user `--tokens`) covered.
2. **Critical #2 coverage shortfall** — Plan `.ccg/tasks/phase-1.5-unlock-academic-tuned/plan.md` now says "≥75%" not "≥80%" with explicit structural-cause documentation. `data/parquet/event_coverage.parquet` exists with per-event `coverage_status`.
3. **Important #1 stale/empty candles** — `backfill_candles.main` counts `empty` and `stale` separately, skips empty writes, logs warnings.
4. **Important #2 supply inference** — `parse_emissions.infer_total_supply` tiers `_PRIMARY` vs `_FALLBACK`, fallback rejected when implausible.
5. **Important #3 backward-compat read** — `read_unlocks` handles old-schema parquet without `vesting_type`.
6. **Important #4 vesting_type validation** — `write_unlocks_csv_to_parquet` normalizes case + rejects invalid values.
7. **Important #5 parser drop counters** — `parse_emissions.main` prints `protocols_scanned/parsed/dropped_*` + `events_emitted/dropped_*`.
8. **Minor #1 docstring** — `src/unlock_validation/fetcher.py` schema mention of `vesting_type` updated.

## What you must do

For each finding above:
1. `git show <relevant-commit-sha>` and read the diff
2. Confirm the fix is correct AND has a real test (not just no-op assertion)
3. If a fix is incomplete or has new issues, flag as Critical/Important/Minor

Also check:
- Did any fix introduce a regression elsewhere?
- Tests added in Fix R1 all pass with the new code (`uv run pytest -q`)?
- Real data refresh numbers consistent (1768 vs 1773 — supply inference rejected some)?

## Commits in Fix R1

`a05b148` test(scripts): backfill rejects path traversal + invalid interval
`1939283` feat(scripts): validate token + interval + target path in backfill
`29e8cf9` test(scripts): backfill flags empty and stale candle responses
`25f2e31` feat(scripts): backfill counts empty and stale, skips empty writes
`9761cd3` test(seed): supply inference primary vs fallback plausibility
`c5fa188` feat(seed): tier total supply inference with plausibility check
`721d460` test(infra): read_unlocks handles legacy parquet without vesting_type
`b57dd3c` feat(infra): read_unlocks tolerates missing vesting_type column
`c2dc0c4` test(infra): write_unlocks rejects and normalizes vesting_type
`d7073a4` feat(infra): validate vesting_type domain on write
`15f6007` test(seed): parse_emissions audit counters
`304fe61` feat(seed): emit parser drop-reason counters in main summary
`76488e3` test(infra): event coverage audit helper
`b12519b` feat(infra): event coverage audit module + CLI
`09473ad` docs(unlock_validation): refresh fetcher docstring for vesting_type
`f2cdb4c` chore(data): refresh event coverage parquet + plan acceptance criteria
`2f7719d` docs(unlock_validation): wrap fetcher schema docstring

## Output Format

### Strengths
[Specific things done well.]

### Issues

#### Critical (Must Fix)
[Genuine bugs / spec violations introduced by Fix R1.]

#### Important (Should Fix)
[Edge cases missed, weak fixes.]

#### Minor (Nice to Have)
[Style polish.]

### Assessment
**Ready to merge into Slice 2?** [Yes | No | With fixes]
**Reasoning:** [2-3 sentences.]
