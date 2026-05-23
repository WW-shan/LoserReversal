ROLE_FILE: /Users/ww/.claude/.ccg/prompts/codex/builder.md

# Phase 2 Slice 1 — Patch: All 4 Warnings

## CRITICAL: Anti-monitor directive
- Do NOT tail/ps. Start coding IMMEDIATELY.
- Do NOT archive.

## Working directory
`/Users/ww/Project/crypto-alpha-portfolio`

## Background

Slice 1 LGTM 89/100 (Codex+Claude) with 0 Critical + 4 Warnings. Repo policy: fix ALL warnings before advancing slice.

## 4 Warnings to fix

### Warning 1+2 — `user_fills` pagination across repeated final timestamps

**File**: `src/infra/fetchers/user_fills.py`

**Problem**: When a 2000-row page ends with multiple fills sharing the same `time` (e.g. 5 fills at `t=1779455392525`), advancing to `last_time + 1` silently skips any remaining fills at `t=1779455392525` that didn't fit in the cap. Current code only catches the case where the entire page has identical timestamps (`first_time == last_time`).

**Fix**: change advance strategy to **keep `startTime = last_time` and dedupe by `tid` instead of strictly advancing by +1**. The dedup logic already exists; we just need to allow overlap on the same millisecond.

Logic:
1. Initial request `startTime=start_ms, endTime=end_ms`
2. If response len < 2000: done (no more pages)
3. Else:
   - Get last fill's `time` as `last_time`
   - Get last fill's `tid` set in response as `last_tids` (for safety check)
   - If `last_time == first_time_in_response`: it's the single-millisecond cap case → keep current warning behavior, advance by +1, log it
   - Else: advance `startTime = last_time` (NOT +1) — overlap is OK because `tid` dedup catches duplicates
4. Continue until empty or hard cap (50)

**Add Test** (`tests/infra/test_user_fills.py`):

`test_fetch_user_fills_handles_repeated_final_timestamp_across_pages`:
- Page 1: 2000 fills, last 5 share `time=t1`, last fill `tid=5`
- Page 2: 6 fills at `t1` with `tid` in {3, 4, 5, 6, 7, 8} (first 3 are dups from page 1 last 3 due to overlap, then 3 new) + 1 fill at `t2 > t1`
- Combined result after dedup: 2000 + 4 new fills = 2004 (not 2006 — the 2 dups removed)
- Assert no fills lost at `t=t1`
- Assert no duplicates by `tid`

### Warning 3 — `build_wallet_pool` CLI test

**File**: `tests/scripts/test_build_wallet_pool.py` (NEW)

Add unit tests with `pytest-mock` mocking `fetch_leaderboard`:

3 cases:
1. **Whale exclusion (retail filter)**: 3 mock wallets:
   - retail: PnL=-50k vlm=500k roi=-0.10 → kept
   - whale-MM: PnL=-300k vlm=$30B roi=-0.000001 (PnL/vlm = -1e-8) → excluded
   - high-roi: PnL=-100k vlm=2M roi=-0.02 → excluded
   - assert pool has 1 row
2. **Sort by vlm desc**: 3 mock wallets all pass filter, with different vlms → assert output ordering `vlm_alltime` desc
3. **CLI arg validation**: `--max-roi=0.1` → `SystemExit` via `parser.error`

### Warning 4 — Wallet filter retail ROI gate

**File**: `scripts/build_wallet_pool.py`

Add 2 new flags + filter predicates:

```python
def build_wallet_pool(
    min_loss: float = -10_000.0,
    min_volume: float = 500_000.0,
    max_roi: float = -0.05,            # NEW: ROI <= -5%
    max_pnl_vlm_ratio: float = -0.005, # NEW: PnL/vlm <= -0.5% (excludes MMs)
    top_n: int = 500,
    out: Path = ...,
    limit: int | None = None,
) -> dict[str, object]:
    ...
    pnl_vlm_ratio = source["pnl_alltime"] / source["vlm_alltime"]
    filtered = source.loc[
        (source["pnl_alltime"] <= min_loss)
        & (source["vlm_alltime"] >= min_volume)
        & ((source["account_value"] > 0) | (source["vlm_alltime"] >= 10_000_000))
        & (source["roi_alltime"] <= max_roi)
        & (pnl_vlm_ratio <= max_pnl_vlm_ratio)
    ].copy()
    ...
```

CLI args:
```python
parser.add_argument("--max-roi", type=float, default=-0.05)
parser.add_argument("--max-pnl-vlm-ratio", type=float, default=-0.005)
```

Validation: both must be ≤ 0.

Regenerate `data/parquet/anti_alpha_wallets.parquet` via real CLI run.

## Workflow

5-6 commits expected (one per logical fix + test):
1. `test(infra): user_fills repeated-timestamp pagination case` (RED)
2. `fix(infra): preserve overlap across repeated-timestamp pagination boundary` (GREEN)
3. `test(scripts): build_wallet_pool filter + sort + CLI validation cases` (RED)
4. `feat(scripts): add ROI and PnL/vlm filters for retail focus` (GREEN — implements W4, makes W3 tests pass)
5. `chore(data): rebuild anti_alpha_wallets.parquet with retail filter`
   - Run `uv run python scripts/build_wallet_pool.py`
   - Confirm new top-5 PnL/vlm ratios are ≥ |0.005| (retail-level, not MM)
   - The parquet is gitignored under `data/` — only regenerate locally, do NOT git add

## Acceptance

- `uv run pytest -q` → 127 + 4 (W1+W2 test) + 3 (W3 test) = ~134 tests pass
- `uv run ruff check src tests scripts` clean
- `uv run python scripts/build_wallet_pool.py` outputs:
  - filter chain reduced from 14711 → new (probably 100-300 retail wallets)
  - top-5 sample shows PnL/vlm ratios ≥ |0.5%|
- No archive

## Out of scope

- Slice 2 (reverse backtest)
- Phase 3+

## Completion

Execution Report with files changed, all commits, real run summary showing new top-5 retail wallets with PnL/vlm ratios. Then EXIT.
