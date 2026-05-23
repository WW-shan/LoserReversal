ROLE_FILE: /Users/ww/.claude/.ccg/prompts/codex/reviewer.md

# Phase 2 Slice 1 — Code Review

## CRITICAL: Read-only

NO write permission.

## Working directory
`/Users/ww/Project/crypto-alpha-portfolio`

## What to review

9 new commits:
- `0aca4ed test(infra): leaderboard fetcher cases`
- `31be883 feat(infra): leaderboard fetcher with retry`
- `59366ea test(infra): user fills fetcher pagination cases`
- `7e88fd2 feat(infra): user fills paginated fetcher`
- `a1f27d5 test(infra): wallets and fills storage cases`
- `6be67d2 feat(infra): wallets and fills parquet storage`
- `a7bd1a1 feat(scripts): build wallet pool CLI`
- `9dc7615 test(infra): user fills edge case guards`
- `897cb9a fix(infra): guard user fills pagination edges`

Use `git show <sha>`, `cat src/infra/fetchers/leaderboard.py`, `cat src/infra/fetchers/user_fills.py`, `cat src/infra/storage.py`, `cat scripts/build_wallet_pool.py`.

Real wallet pool was generated:
- 36,890 leaderboard rows → 14,711 filtered → 500 written to `data/parquet/anti_alpha_wallets.parquet`

## Spec

`.ccg/tasks/phase-2-single-wallet-contrarian/prompts/slice-1-builder.md` (this file). The builder added 2 extra commits to address its own Claude-review findings — verify those fixes are actual improvements not regressions.

## Review focus

### Critical
1. **Pagination correctness**: does `fetch_user_fills` correctly handle the 2000-cap boundary + 50-page hard cap + `tid` dedup? Walk through edge cases (single-millisecond cap, gap pagination).
2. **HL leaderboard schema parse**: are PnL/ROI/Volume string→float conversions handling inf/NaN/negative-zero gracefully?
3. **Wallet pool filter logic**: confirm builder's filter matches plan: `pnl_alltime <= -10000 AND vlm_alltime >= 500000 AND (account_value > 0 OR vlm_alltime >= 10M)`. Verify the 500-row output is sorted by `vlm_alltime` desc (not by PnL — that would be different).
4. **liquidation field**: `liquidation` boolean correctly derived from non-null dict in raw fill?

### Warnings
5. Retry policy on the GET (tenacity)—reasonable backoff?
6. Storage parquet schemas: timestamp columns tz-aware? Numeric dtypes consistent (float64)?
7. CLI argparse defaults match plan exactly?
8. Tests cover all the edge cases the plan listed (8 user_fills cases + 4 leaderboard + storage)?
9. Any private function leakage in imports across the new files?

### Info
10. Naming, docstrings, error messages

## Output format

```
## Phase 2 Slice 1 Review

### Summary
[overall assessment]

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
- Test quality: XX/20
- Code quality: XX/20
- Style consistency: XX/20

TOTAL: XX/100

RECOMMENDATION: [LGTM / NEEDS_FIX / BLOCK]
```

Read-only. Do NOT modify.
