ROLE_FILE: /Users/ww/.claude/.ccg/prompts/codex/reviewer.md

# Phase 1 Slice 3 — Re-review After Fix R1

## CRITICAL: Read-only

NO write permission.

## Working directory
`/Users/ww/Project/crypto-alpha-portfolio`

## Context

Round 1 Slice 3 review scored 67/100 BLOCK (2 Critical + 4 Warnings). Fix R1 added 5 commits:
- `9e4c721 fix(walkforward): distinguish data_gap and zero-trade metrics`
- `41d967b fix(backtest): make date_end filter exclusive to prevent boundary leak`
- `e191928 fix(walkforward): smarter IS fallback selection avoiding zero-OOS configs`
- `02457d3 docs(roadmap): clarify Phase 1 data_gap root cause`
- `5c1f97e fix(walkforward): clarify fallback selection review findings`

The previous archive commit (`8ea6edb`) was reverted by `f5c6707` BEFORE fix R1 started.

## Verify each Round 1 issue

### Critical
1. **Process violation (archive without approval)** — verify `8ea6edb` is reverted (already done by `f5c6707`). Confirm no new self-archive in fix R1.
2. **0-OOS-trade metrics shown as PASS/GREEN** — verify `_aggregate_rows` now renders `n/a` with `NO SAMPLE` status when `oos_n_trades_total == 0`. Check `/tmp/unlock_wf_v2.md` or `reports/unlock_v1_walkforward.md`.
3. **Verdict reason refinement** — verify `_verdict` now uses `data_gap` when `oos_n_trades_total == 0`, `insufficient_sample` for `0 < n < 15`, etc.

### Warnings
4. **Boundary leak** — verify `date_end` filter in `run_unlock_backtest.py` is now `<` (exclusive). Check docstring update. Check that the boundary test in `tests/scripts/test_walkforward_runner.py` covers an event exactly on `train_end == test_start` and asserts OOS-only assignment.
5. **IS fallback** — verify new `_select_best_is_row` logic prefers (eligible-by-trades → positive-trades-median → positive-trades-any → zero-trade fallback). `is_selection_mode` field added to split result and surfaced in per-split table.
6. **ROADMAP text** — verify Phase 1 section now mentions `data_gap` root cause, not just "0 OOS trades".

## New issues check

Watch for:
- Any new test broken by the rename or behavioral changes
- Inconsistencies between split table render and aggregate table render
- Spurious new commits (e.g. `5c1f97e` — was it really needed? Did builder over-fix?)
- ROADMAP narrative still consistent with passCriteria

## Sanity numbers

Read `/tmp/unlock_wf_v2.md` (or `reports/unlock_v1_walkforward.md`):
- Verdict label / reason
- Per-split is_selection_mode values
- Aggregate Sharpe (mean) string (should be `n/a` if oos_trades=0)
- All "Status" column values for zero-trade rows must say `NO SAMPLE`, not `PASS` / `GREEN`

## Output format

```
## Slice 3 Round 1 Re-Review

### Verdict
[LGTM / STILL NEEDS_FIX / NEW ISSUES]

### Per-item Status
1. Critical (process violation): [FIXED / NOT FIXED]
2. Critical (n/a metrics): [FIXED / NOT FIXED]
3. Critical (verdict reason): [FIXED / NOT FIXED]
4. Warning (boundary leak): [FIXED / NOT FIXED + how test covers it]
5. Warning (IS fallback): [FIXED / NOT FIXED + selection mode field present?]
6. Warning (ROADMAP text): [FIXED / NOT FIXED]

### New issues introduced (count: N)
- ...

### Scoring
- Critical resolution: XX/30
- Spec coverage: XX/20
- Correctness: XX/20
- Code quality: XX/15
- Style consistency: XX/15

TOTAL: XX/100

RECOMMENDATION: [LGTM (ready to archive) / NEEDS_FIX / BLOCK]
```

If LGTM and TOTAL ≥ 90, Phase 1 is ready for Claude to archive.

Read-only. Do NOT modify files.
