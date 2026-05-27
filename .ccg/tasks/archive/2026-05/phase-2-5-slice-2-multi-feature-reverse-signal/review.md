# Review — Phase 2.5 Slice 2 Multi-feature Reverse Signal

## Original review (2026-05-26, pre-CCG-retro)

### Codex Local Review

- Critical: none.
- Warning: full-project `uv run pytest -q` currently fails in
  `tests/scripts/test_build_clean_wallet_pool.py`, outside Slice 2 scope.
- Info: scoped Slice 2 tests and ruff are clean.

### Claude Review

- First pass: no Critical findings; two Major findings:
  - Non-finite `funding_zscore` serialized as non-standard JSON `Infinity`.
  - CLI token assignment was positional without a row-count guard.
- Fixes applied with regression tests.
- Second pass: approved; no Critical or Major findings remain.

### Verification

- Baseline before Slice 2 changes: `uv run pytest -q` -> 540 passed.
- Latest scoped Slice 2 verification:
  - `uv run pytest tests/wallet_pool/test_reverse_signal.py tests/scripts/test_run_reverse_alpha_scoring.py -q` -> 24 passed.
  - `uv run ruff check src tests scripts` -> all checks passed.
- Latest full-suite verification:
  - `uv run pytest -q` -> 588 passed, 3 failed in unrelated clean-wallet-pool tests.

---

## CCG Retro R1 — 2026-05-27

Three-way review per `.ccg/spec/guides/index.md` "CCG retro closure flow" rule.

### Subagent R1 verdict (general-purpose agent, full run)

**READY: NO — Critical: 2, Important: 4, Minor: 7**

#### Critical (2) — must fix before archive

**C1. Lookahead leak at funding-settle boundary**
- `src/wallet_pool/reverse_signal.py:216`
- `window = normalized.loc[:timestamp]` uses inclusive label slicing. A fill at exactly `T == funding_settle_time` includes the funding row published at `T`.
- Repro: precomputed `funding_zscore` at `T=16:00:00Z` value `99.9`; fill at `T=16:00:00Z` returns the just-settled value.
- Why critical: HL retail clusters around funding settle in anticipation. Fill_id at boundary uses post-settle info.
- Fix: `window = normalized.loc[normalized.index < timestamp]` strict less-than. Add boundary test.

**C2. CLI crashes on `wallet=pd.NA` row**
- `scripts/run_reverse_alpha_scoring.py:56`
- `str(wallet_metrics.get("wallet", "") or "").lower()` — when StringDtype with NA, `pd.NA or ""` raises `TypeError: boolean value of NA is ambiguous`.
- Fix: `wallet = wallet_metrics.get("wallet"); if pd.isna(wallet) or not str(wallet): continue`. Also `pool = pool.dropna(subset=["wallet"])` in `_read_pool`.

#### Important (4)

**I1. Funding zscore signal effectively dead in production**
- `src/wallet_pool/reverse_signal.py:228-244`
- Fallback computes zscore from current-vs-all-prior-history. With ~26k 8h rows, std collapses to long-run baseline; `|z| ≥ 2.0` essentially never fires.
- Evidence: production 15884 fills → `funding_zscore` dist `min=-1.60 max=0.05 mean=-0.32`, `|z|≥2.0` count = **0**. `funding_extreme_multiplier` identically 1.0 for all sampled.
- Why important: 1/4 design axes contributing zero signal. ROADMAP §467 lists funding_extreme as load-bearing.
- Fix: add `funding_lookback_days: int = 30` to `ReverseScoreConfig`, apply rolling window (match `src/signals/funding_extreme_v1.py:128-150` semantics).

**I2. `_fill_id` returns string `'<NA>'` for `pd.NA`**
- `src/wallet_pool/reverse_signal.py:278-283`
- Check `if value is not None and str(value) != ""` misses pd.NA (which is not None, and `str(pd.NA) == '<NA>'`).
- Fix: reuse `_string_value(value)` and synthesize positional id when None.

**I3. `trade_component` saturated for 19/21 production wallets**
- `src/wallet_pool/reverse_signal.py:44`
- `_bounded_linear(n_trades, low=50.0, high=200.0)` caps at 1.0 for n_trades≥200. Academic pool n_trades ∈ [103, 8175] → 19/21 saturated.
- Fix: raise `high` to ~5000 OR log-scale `_bounded_linear(math.log1p(n_trades), low=math.log1p(50), high=math.log1p(5000))`. Also consider folding `size_cv_90d`.

**I4. `funding_zscore` precomputed-column path doesn't drop NaN**
- `src/wallet_pool/reverse_signal.py:220-223`
- Asymmetric with funding_rate path which DOES dropna. Single trailing NaN row silently blanks signal.
- Fix: `series = pd.to_numeric(window[column], errors='coerce').dropna(); if not series.empty: return {'funding_zscore': float(series.iloc[-1])}`.

#### Minor (7)

- **M1** `_funding_zscore` returns +inf when std=0 (intentional per test but worth documenting)
- **M2** CLI silently writes 0-row output when intersection empty
- **M3** `_json_safe` mishandles np.int64 / np.bool_ (latent)
- **M4** Hardcoded `8 * 60` funding cadence — derive from `np.median(np.diff(funding_index))` or expose config
- **M5** Default `asian_session_hours = (0, 8)` is END of Tokyo, likely should be `(23, 7)` (Tokyo OPEN) per literature §107 cascade-window thesis
- **M6** Missing test for tz-naive fill timestamp branch (`_fill_timestamp:193-194`)
- **M7** `_print_summary` path coverage uneven

### Codex R1 verdict

Awaiting saved transcript merge (Codex R1 completed but output not parsed before session ended).
Transcript at `/private/tmp/claude-501/-Users-ww-Project-crypto-alpha-portfolio/16b91372-a972-49e2-bba1-dfd9a5f16ea8/tasks/bkaauj2ck.output`.

### Claude R1 verdict (partial — interrupted before completion)

Verified before interruption:
- `wallet_confidence_weight` distribution on n=21 pool: min 0.378, max 0.964, mean 0.544, no saturation ✓
- 24/24 tests pass, ruff clean ✓
- `_bounded_linear` clamps inf → 0 (NOT propagated to score) ✓

Findings deferred — likely overlap with subagent C1/C2/I1.

---

## Next session work

1. **Read this review.md first** to pick up state.
2. Read Codex R1 transcript and merge findings into above.
3. Dispatch Codex builder for R1 fix run addressing **2 Critical + 4 Important + 7 Minor**.
4. Re-run 3-way R2 review.
5. Loop to convergence (estimate 3-5 rounds based on Phase 2.5 Slice 1 / Phase 4 Slice 1 precedent).
6. Spec evolution + archive.

## Cross-cutting concerns (for future thought)

- **I1 funding signal degradation** is the most impactful — if 1/4 design axes contributes zero, alpha story is materially weaker than designed. Re-derive expected score variance after fix.
- **I3 + I1 combined** mean signal stack effectively relies on `loss × leverage × oversized × time_bucket`. If walkforward verdict is weak, suspect this first.
- Consider propagating `size_cv_90d` into Slice 2 confidence weight (subagent I3 fix suggestion); Slice 1 archives the field but Slice 2 doesn't use it.
