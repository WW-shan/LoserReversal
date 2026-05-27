# Phase 2.5 Slice 1 Academic Wallet Pool Review

> Retrospective CCG review-audit (review.md补交). Code shipped at commit `d229ee9`
> ahead of the review gate. Per CCG `engine/strategies/review-audit.md` this records
> dual-model findings against the actually-delivered artifacts so future work
> (Slice 2/3 downstream, Phase 4 bot exclusion) has a documented baseline.

## Scope

- `src/wallet_pool/academic_pool.py` (5 academic predicates + funnel)
- `scripts/build_academic_wallet_pool.py` (Hyperliquid leaderboard → fills → pool CLI)
- `tests/wallet_pool/test_academic_pool_metrics.py` (19 metric tests)
- `tests/wallet_pool/test_academic_pool_builder.py` (11 builder tests)
- `tests/scripts/test_build_academic_wallet_pool.py` (5 script tests)
- `reports/phase_2_5_slice_1_wallet_pool.md` (delivery report)
- `data/parquet/academic_wallet_pool.parquet` (3 wallets shipped)

Spec source: `docs/research/literature-review.md` Part B; ROADMAP Phase 2.5 Slice 1.

## Codex Review (background id `bo65tst54`, 70k tokens)

### Critical

- `reports/phase_2_5_slice_1_wallet_pool.md:11` — final pool size is 3, while the
  roadmap target is 200-500 wallets. Thresholds match the spec, so this looks
  more like sampling/top-N insufficiency than threshold-math failure.
  **Fix**: mark Slice 1 exit criteria as unmet, expand/paginate the candidate
  universe, or make the report explicitly fail the target check before
  downstream slices use this pool.

- `src/wallet_pool/academic_pool.py:178` — funnel counts skip
  `account_value <= 0`, missing fills, and empty fills before the first reported
  axis. `leaderboard=500 → account_value=43` is therefore misleading because
  pre-filter attrition is hidden (~457 wallets dropped pre-funnel without
  attribution).
  **Fix**: add explicit funnel stages `valid_account_value`, `fills_available`,
  `fetch_failed`, `empty_fills`; document that axis counts are cumulative
  survivor counts.

### Warning

- `src/wallet_pool/academic_pool.py:278` — `_filter_window` only applies
  `>= horizon`; fills after `as_of` are included if callers pass a broader
  history frame. Can leak future data in backtests.
  **Fix**: filter `(time >= horizon) & (time <= as_of)`.

- `scripts/build_academic_wallet_pool.py:83` — `except Exception` logs and
  continues, then still writes a partial parquet. Safe for isolated wallet
  failures, unsafe for systemic API/schema failures.
  **Fix**: catch expected fetch/network exceptions, retry with backoff, fail or
  mark output incomplete when failure rate exceeds a threshold.

- `src/wallet_pool/academic_pool.py:289` — missing `dir` column raises
  `AttributeError` via `filtered.get("dir").astype(...)`.
  **Fix**: validate required fill columns up front with a clear `ValueError`,
  or return an empty metrics window for missing schema fields.

### Info

- `src/wallet_pool/academic_pool.py:112` — threshold math is correct and
  inclusive: `$1k-$100k`, loss rate `>= .50`, leverage `>= 5`, trades `>= 50`,
  size CV `>= .30`.
- `scripts/build_academic_wallet_pool.py:135` — parquet schema and in-memory
  column order are aligned; output has 7 columns and UTC `eligible_at`.
- Tests run read-only: `35 passed` for builder + metrics + script tests.

### Codex Summary

Request changes before treating Slice 1 as complete. The predicate and schema
are solid, but the deliverable currently produces only 3 wallets against a
200-500 target, and the funnel hides pre-filter attrition that is needed to
diagnose why. Highest-value fixes: expand the candidate universe, make the
funnel explicit, prevent future-fill leakage.

## Claude Review (current session, semantic audit)

### Critical

None new — Codex's two Critical findings are confirmed by my own reading.

### Warning

- `src/wallet_pool/academic_pool.py:104` — `std(ddof=0)` is population std, not
  sample std. The test `test_compute_wallet_metrics_size_cv_is_std_over_mean_of_notional`
  ratifies this (CV ≈ 0.69 for notionals 1k/5k/10k). For n_trades ≥ 50 (threshold
  minimum), ddof=0 vs ddof=1 converge; for n<50 the difference matters but those
  wallets fail anyway. Worth a `# ddof=0 = population std, robust at small n`
  comment.

- `reports/phase_2_5_slice_1_wallet_pool.md` — the 3 shipped wallets have
  account_value $1090–$1806 (very low end of the $1k–$100k band) and n_trades
  539–8245 (massive activity). This skew suggests the inclusive filter at
  account_value lower-bound + the activity filter at `n_trades ≥ 50` selects
  for high-velocity sub-$2k traders, not the academic "loss-bracket retail"
  cohort the literature describes ($1k-$10k modal loser). The result is a
  cohort that may not generalize to Phase 2.5 Slice 2 reverse signal.

### Info

- Funnel attrition trace from the report:
  `leaderboard=500 → account_value=43 → realized_loss_rate=32 → leverage=3 → n_trades=3 → size_cv=3`
  The dominant bottleneck is `leverage ≥ 5x`, dropping 32→3 (29 wallets, 90%
  attrition on this axis). Loosening to `leverage ≥ 3x` would likely 5–10x
  the pool; this is a knob worth documenting.
- Tz handling in `_coerce_eligible_at` and `_window_start` correctly branches
  on `tzinfo is None`, no double-localize bug.
- Test coverage is comprehensive: boundary inclusivity, mixed-case addresses,
  missing fills, market-maker exclusion all covered.

### Claude Summary

代码与 literature-review.md Part B 规范一致、tests 全过、schema 干净。但**交付物
n=3 严重偏离 ROADMAP 目标 2000 钱包**，funnel 报告隐藏了 leaderboard→account_value
的前置衰减。3 个幸存钱包都集中在 $1k-$2k 极低账户带，与"loss-bracket retail"学术
画像不完全契合，可能影响下游 Slice 2 reverse signal 的泛化性。**Critical 是交付
完整性问题，不是代码 bug。**

## Synthesis

### Combined Critical (2)

1. **Deliverable insufficiency** [Codex/Claude consensus] — pool size 3 vs
   target 200-500. Not a code bug; sampling + threshold-combination too strict
   for leaderboard top-500 universe.
2. **Funnel hides pre-filter attrition** [Codex] — 457/500 wallets dropped
   before the funnel; reader can't diagnose where.

### Combined Warning (4)

1. `_filter_window` lookahead potential (no upper bound on `as_of`)
2. Bare `except Exception` in fetch loop
3. Missing-column AttributeError
4. ddof=0 population std intentional but uncommented; cohort skew toward low-$
   high-velocity traders

### Impact Assessment

- **Phase 4 bot-exclusion (already done downstream)**: bot_exclusion.py filters
  out detected bots from the pool. With n=3 the bot filter is a no-op; future
  work that scales the pool will need to rerun bot exclusion.
- **Phase 2.5 Slice 2 reverse signal**: built on this pool, so its OOS metrics
  reflect only 3 wallets' behavior. Sharpe / win-rate statistics from Slice 2
  carry n=3 sampling caveat that should be propagated to verdict reports.
- **Phase 5 portfolio composer**: only `unlock_v1+D` is in `strategies/active/`,
  so Phase 2.5 Slice 2 has not entered the portfolio. No production impact yet.

## CCG Phase 6 Step 1 — git diff

Scope: `14a3e40^..d229ee9` over `src/wallet_pool/academic_pool.py`,
`scripts/build_academic_wallet_pool.py`, related tests.

```
 scripts/build_academic_wallet_pool.py            | 274 +++
 src/wallet_pool/academic_pool.py                 | 302 +++
 tests/scripts/test_build_academic_wallet_pool.py | 222 +++
 tests/wallet_pool/test_academic_pool_builder.py  | 327 +++
 tests/wallet_pool/test_academic_pool_metrics.py  | 359 +++
 5 files changed, 1484 insertions(+)
```

Commit sequence (test-first TDD pattern):
`14a3e40` metrics tests → `3a053ec` metrics impl → `fd778f0` builder tests →
`f78ffbd` builder impl → `d229ee9` parquet seed.

## CCG Phase 6 Step 2 — run tests

```
tests/wallet_pool/test_academic_pool_metrics.py   19 passed
tests/wallet_pool/test_academic_pool_builder.py   11 passed
tests/scripts/test_build_academic_wallet_pool.py   5 passed
======================== 35 passed in 0.33s ========================
```

## CCG Phase 6 Step 3 (continued) — Superpowers `requesting-code-review` subagent

> Subagent id `a5b5df47181dae508`, ~88k tokens, ran ~11 min.

### Strengths (subagent)
- Strict spec alignment on all 5 thresholds vs `literature-review.md` B.3 lines 116-127
- Funnel diagnostic surfaces axis-by-axis attrition (correctly revealed leverage as heaviest gate)
- Tz-aware throughout: `_window_start`, `_coerce_eligible_at`, `_filter_window`, `_coerce_as_of`
- Pyarrow schema explicitly pinned at `build_academic_wallet_pool.py:40-50`
- CLI test coverage unusually complete (fetch-failure, top-n, parquet shape, summary, CLI validation)
- Phase 2 v1 baseline preserved (`build_wallet_pool.py` untouched for A/B)

### Critical (subagent, both empirically verified)

**C1** Same as Codex finding (pool size 3 vs target 200-500), but subagent
identified **specific root cause**: `scripts/build_academic_wallet_pool.py:70`
does `source.head(top_n)` against a leaderboard ordered **ASCENDING by
`pnl_alltime`** (per `src/infra/fetchers/leaderboard.py:55`). The worst-PnL
wallets in absolute USD are dominated by whales (large $ losses scale with
account size), over-sampling the $100k+ band and under-sampling $1k-$100k.
That's why funnel `account_value=43/500`.
**Fix**: pre-filter leaderboard to `account_value ∈ [$1k, $100k]` BEFORE
`head(top_n)`, or order by `roi_month` ASC. Re-run with `top_n=2000-5000`
against in-band universe.

**C2** **NEW — `is_academic_anti_alpha` accepts NaN for 4 of 5 metrics.**
Verified by repro: `is_academic_anti_alpha({"account_value": 25000,
"realized_loss_rate_90d": float('nan'), "leverage_avg_90d": 8.0,
"n_trades_90d": 100, "size_cv_90d": 0.5})` returns `True`. Reason: `<
THRESHOLD` checks where `NaN < anything` is `False`, so predicate returns
True for NaN inputs (only account_value is safe via chained MIN <= x <= MAX).
Docstring at line 113 advertises this as "the predicate enforcing the 5
inclusive thresholds" — documented as reusable, so external callers with
NaN columns will silently see false positives.
**Fix**: add `if not math.isfinite(value): return False` for each field, or
invert comparisons.

### Important — NEW findings beyond Codex/Claude

**I3** **NEW — `_filter_window` upper-bound lookahead verified empirically**:
"passing a frame with timestamps `2026-01-01, 2026-04-01, 2026-05-15,
2026-06-15` and `as_of=2026-05-26` keeps the `2026-06-15` row". Critical
for Phase 2.5 Slice 5 walkforward backtest.

**I4** **NEW — funnel under-reports attrition**: no axis for "no fills" or
"non-positive account_value". 457/500 wallets dropped pre-funnel without
attribution. Adds "Wallets fetched: 492" includes empty frames — there's no
way to distinguish "wallet has no 90d fills" from "wallet has fills but
failed band". When final=3, this is the diagnostic gap that hides where to
relax filters.

**I5** **NEW — no persistence/checkpointing across 1258s run**. 20 min wall
time + real API calls. If process killed (OOM, network, Ctrl-C), all
collected fills lost. The 8 failed wallets are silently dropped without
retry queue.

**I6** **NEW — production code path `time` as column (not index) is
UNEXERCISED**. All test helpers do `frame.set_index("time")`. If upstream
ever returns fills with `time` as column (parquet roundtrip without
reset_index), `_filter_window`'s `"time" in frame.columns` branch
(lines 279-281) becomes load-bearing without test coverage.

**I7** **NEW — duplicate wallet handling**: leaderboard with dup
`eth_address` rows produces duplicate output rows. Verified.

### Minor — NEW findings
- M11 `is_academic_anti_alpha` and `build_academic_pool_with_funnel`
  duplicate predicate logic (5 threshold checks inline vs centralized)
- M12 size_cv upper-bound unguarded (3.94 / 2.30 in shipped data; might be
  "panic gambler" outliers rather than persistent retail)
- M13 Minor wasted work: `mean_notional` computed when `account_value ≤ 0`

### Subagent Assessment

**Ready to merge?** No
**Reasoning**: Code quality, type safety, test coverage are solid (35/35
passing), but the delivery doesn't meet Slice 1 acceptance criterion — 3
wallets vs ROADMAP target of 200-500. Root cause is a single-line fix
(`head(top_n)` against worst-PnL ASC leaderboard biases away from $1k-$100k
cohort). NaN-tolerance bug + look-ahead exposure are correctness gaps that
will silently corrupt walkforward in later slices. None difficult to fix;
collectively "fix-then-merge" rather than hold.

## CCG Phase 6 Step 4 — Combined 3-way Synthesis

### Critical (2) — unanimous + subagent contributes specific root cause

| # | Finding | Codex | Claude | Subagent | Verified |
|---|---|---|---|---|---|
| C1 | Pool size 3 vs target 200-500 (subagent: root cause = leaderboard PnL-ASC + head(top_n) biases away from $1k-$100k) | ✓ | ✓ | ✓ + root cause | ✅ funnel data |
| C2 | **NEW** `is_academic_anti_alpha` accepts NaN for 4/5 metrics (subagent-only finding, repro verified) | — | — | ✓ | ✅ Python repro |

### Important (7) — merged after dedup

| # | Finding | Source |
|---|---|---|
| I1 | `_filter_window` only lower bound (lookahead risk) | Codex/Claude/Subagent (I3) — subagent has empirical repro |
| I2 | Bare `except Exception` in fetch loop | Codex |
| I3 | Missing `dir` column AttributeError | Codex |
| I4 | **NEW** funnel hides pre-funnel attrition (no fills / acct≤0 axes) | Subagent (I4) |
| I5 | **NEW** no checkpoint/resume across 20-min run | Subagent (I5) |
| I6 | **NEW** `time` as column path untested | Subagent (I6) |
| I7 | **NEW** leaderboard dedup missing | Subagent (I7) |

### Three-way Convergence Summary

3 reviewers agree on the **same C1 deliverable insufficiency**; subagent
adds specific root cause (PnL-ASC bias). Subagent **independently identified
C2 (NaN tolerance)** with empirical repro — a correctness bug Codex/Claude
missed. Net: **2 Critical + 7 Important + 6 Minor**.

## CCG Phase 6 Steps 5-7 — Quality Gates

### Step 5 — `ccg:verify-quality`
```
扫描路径: src/wallet_pool/ (4 files, 951 lines, 718 code lines)
检查结果: ✓ 通过
统计: 错误: 0 | 警告: 0
```

### Step 6 — `ccg:verify-security`
```
扫描路径: src/wallet_pool/ (4 files)
统计: 严重: 0 | 高危: 0 | 中危: 0 | 低危: 0
结果: ✓ 通过
```

Expected — no auth/input-validation/crypto/secrets. Critical findings are
semantic (NaN tolerance, lookahead), not security vulns.

### Step 7 — `ccg:verify-change`
Skill mode limitation (only working/staged/committed). Manual assessment:
1484 lines added across 5 files; no `docs/` updates. ROADMAP Phase 2.5
section + literature-review.md Part B serve as the spec docs — spec/code
alignment is at literature-level, OK. No per-module DESIGN.md in
`src/wallet_pool/` — `/gen-docs` candidate for future task.

## CCG Phase 6 Step 8 — User decision [HARD STOP — awaiting]

Per `phase-guide.md` Section 10 Ralph Loop, with 2 Critical:

> 有 Critical → "发现 2 个 Critical 问题。修复后再审一轮？[Y/n]"

**Decision options** (与 Task 4 一致设计)：

1. **修 Critical 后再审一轮 (Round 2)** — pre-filter leaderboard + NaN guard
   → 重跑 35 tests + 加 NaN guard test → 三方 review Round 2
2. **接受 findings 闭环关闭** — Critical 作为 Slice 2 reverse-signal
   generalization blocker 文档化
3. **修 Critical + 跳过 Round 2** — 直接修但不再审
