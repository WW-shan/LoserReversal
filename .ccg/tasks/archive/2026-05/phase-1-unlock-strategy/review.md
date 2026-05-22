# Review — Phase 1 Slice 3 Walk-Forward

## Local Codex Review

- Critical: none.
- Warning: inclusive split boundaries can include an event exactly at `train_end` in both IS
  and OOS, but the implementation follows the Slice 3 plan's explicit inclusive
  `date_start` / `date_end` filter contract and the existing walk-forward splitter contract.
- Warning: no-eligible IS fallback intentionally selects max Sharpe overall and marks
  `eligible_in_is=false`, matching the plan. The final verdict is RED because OOS sample is
  insufficient.
- Info: `run_sweep` explicitly passes `date_start` / `date_end` through `replace()` as required,
  even though `dataclasses.replace` would otherwise preserve those fields.

## External Claude Review

- Critical: none.
- Warning: boundary-day leakage is possible because split boundaries are equal and filters are
  inclusive on both sides.
- Warning: fallback floor behavior is only active when `min_train_days > 90`; this is acceptable
  for the default and documented fallback path.
- Warning: no-eligible IS fallback can noise-select thin configs; this is surfaced in the report
  through `eligible_in_is=no` and the sample-size RED gate.
- Warning: `IS->OOS decay` can be misleading for negative mean IS Sharpe. The plan specified the
  exact decay formula; the actual run has positive mean IS Sharpe.

## Verification

- `uv run python scripts/run_unlock_walkforward.py --report /tmp/unlock_wf.md` -> pass.
- `uv run pytest -q` -> 102 passed.
- `uv run ruff check src tests scripts` -> pass.
