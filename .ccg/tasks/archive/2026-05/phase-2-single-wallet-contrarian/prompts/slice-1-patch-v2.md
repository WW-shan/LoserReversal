ROLE_FILE: /Users/ww/.claude/.ccg/prompts/codex/builder.md

# Phase 2 Slice 1 — Patch v2: end-boundary guard + missing test

## CRITICAL: Anti-monitor directive
Do NOT tail/ps. Start IMMEDIATELY. Do NOT archive.

## Working directory
`/Users/ww/Project/crypto-alpha-portfolio`

## Background

Patch v1 fixed 4 warnings, but Codex re-review found 2 new issues. Fix both.

## Fix 1 — `user_fills.py` end-boundary guard (Warning)

**File**: `src/infra/fetchers/user_fills.py`

**Bug**: when single-ms cap case advances `next_cursor = last_time + 1`, but `last_time == end_ms`, the next request has `startTime > endTime`. Previous code had a `last_time >= end_ms` break that was removed in commit `953fae3` to enable overlap behavior. Now need a more precise guard.

**Fix**: after computing `next_cursor`, add a guard before continuing the loop:

```python
if next_cursor > end_ms:
    break
```

Place this right after `next_cursor = last_time + 1` (or `last_time`) but before the loop continues. Specifically right after the `if first_time == last_time: ... next_cursor = last_time + 1` else block.

**Test** (`tests/infra/test_user_fills.py`):

`test_fetch_user_fills_stops_when_single_ms_cap_lands_on_end_ms`:
- Mock returns 2000 fills all at `time = end_ms` (cap-sized single-ms page exactly at boundary)
- Expect: 2000 rows returned, exactly 1 paginated call (no second call with `startTime > endTime`)
- Optional: assert RuntimeWarning fires for single-ms cap

## Fix 2 — `test_build_wallet_pool.py` missing test (Info)

**File**: `tests/scripts/test_build_wallet_pool.py`

Add a test mirroring the existing `--max-roi` positive-rejection test, but for `--max-pnl-vlm-ratio`:

```python
def test_build_wallet_pool_rejects_positive_max_pnl_vlm_ratio_cli_arg(mocker, capsys):
    mocker.patch("sys.argv", ["build_wallet_pool.py", "--max-pnl-vlm-ratio", "0.1"])
    with pytest.raises(SystemExit):
        builder._parse_args()
    assert "--max-pnl-vlm-ratio must be less than or equal to 0" in capsys.readouterr().err
```

## Workflow

2 commits:
1. `test(infra): user_fills end-boundary single-ms cap case` + `test(scripts): max_pnl_vlm_ratio positive arg rejection` (combined: RED)
2. `fix(infra): bail user_fills pagination when next cursor exceeds end_ms` (GREEN)

(Order matters; the second commit just adds the guard.)

## Acceptance

- `uv run pytest -q` passes (~133 tests now)
- `uv run ruff check src tests scripts` clean
- New tests added for both fixes

## Completion

Execution Report with commits, final pytest output, ruff output. Then EXIT.
