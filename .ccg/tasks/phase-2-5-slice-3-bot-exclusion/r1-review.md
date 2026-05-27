# Phase 2.5 Slice 3 — R1 review (2026-05-27)

Reviewers: subagent (Claude semantic) + Claude in-band semantic + Codex (hung at 10:34, dropped per spec "trust strictest reviewer" precedent set by Phase 4 Slice 2)

## Verdict
READY: NO
Critical: 0
Important: 5
Minor: 5

## Findings

### Important

**I1. `src/wallet_pool/bot_exclusion.py:12-18` — `BotExclusionConfig` no validation**
Frozen dataclass accepts `bot_score_threshold=-1.0`, `=5.0`, `funding_source_graph_max_shared=0/-1` silently. CLI validates ranges; library callers bypass. Violates spec rule "Threshold parameter validation" (phase-4-slice-1 R1 I4).
**Fix**: add `__post_init__` raising ValueError on bad inputs. Tests for both fields.

**I2. `src/wallet_pool/bot_exclusion.py:45` — NaN sentinel `-1.0` ambiguity**
`merged["bot_score"].fillna(-1.0) >= threshold` keeps NaN-score wallets. Library is silently fail-open for missing scores (the script's `_fetch_failed_excluded` compensates downstream, but the library is the public API). Sentinel `-1.0` also collides with a valid threshold value if I1 isn't fixed. Spec rule "bot/wallet score gating" requires fail-closed.
**Fix**: drop sentinel — use `notna() & (>= threshold)`; document NaN→kept and surface unscored rows separately.

**I3. `scripts/build_clean_wallet_pool.py:354-357` — CLI bounds too loose**
`--bot-score-threshold=0.0` would exclude every scored wallet silently; `--funding-source-max-shared=1` would exclude every wallet (every wallet is a 1-cluster). Both empty the deliverable — same class of "silent deliverable corruption" addressed by spec rule "Deliverable target vs. empirical population".
**Fix**: reject `bot_score_threshold <= 0.0` and `funding_source_max_shared <= 1`.

**I4. `src/wallet_pool/bot_exclusion.py:54-77` — `funding_source_graph` point-in-time-naive (lookahead potential)**
No `as_of` parameter. Slice 4/5 walkforward will query at multiple timestamps; today's code excludes a wallet at all dates if it joined a Sybil cluster at any later date. Parallels Slice 2 R1 C1 (strict-less-than slicing). The `wallet_funding_sources.parquet` may lack `first_funded_at` today — even so, surface the gap explicitly so Slice 4 author cannot miss it.
**Fix**: thread optional `as_of: pd.Timestamp` into `funding_source_graph`. When the parquet has `first_funded_at`, filter strictly `< as_of`. When missing or `as_of=None`, document "snapshot mode, walkforward-unsafe" in module docstring + raise clearly if walkforward attempts to use without as_of. Boundary test at exact `as_of`.

**I5. `src/wallet_pool/bot_exclusion.py:143` — `drop_duplicates(keep="last")` silent collapse**
Conflicting duplicate wallet scores silently dropped. Spec rule "Threshold parameter validation" precedent: never silently nudge/clamp at public API.
**Fix**: detect non-NaN conflicts → ValueError listing offending wallets. Test added.

### Minor

**M1. `src/wallet_pool/bot_exclusion.py:33-34` — empty-pool path skips wallet lowercasing**
Asymmetric with non-empty path (line 37). Harmless on empty rows but inconsistent dtype if downstream expects lowercase.

**M2. `src/wallet_pool/bot_exclusion.py:80-117` — API inconsistency**
`exclude_funding_source_clusters` takes bare `max_shared=` kwarg; `exclude_bots_from_pool` takes `config=BotExclusionConfig`. Caller threads it manually. Harmonize.

**M3. Tests — coverage gaps**
- `max_shared=2` boundary (smallest meaningful Sybil cluster)
- `--help` smoke test on `build_clean_wallet_pool.py` (spec rule "Escape `%` in argparse help")
- `BotExclusionConfig` validation tests (links to I1)
- Conflicting `bot_scores` duplicates (links to I5)
- as_of point-in-time test (links to I4)

**M4. `scripts/build_clean_wallet_pool.py:167-170` — `min_trades_for_scoring` gate not directly asserted at lib boundary**
Behavior is tested implicitly; pin the kwarg with a mock to lock spec rule "n_trades minimum threshold".

**M5. `src/wallet_pool/bot_exclusion.py:195-199` — empty-source strings silently dropped**
Corrupt `from_address=""` entries produce isolated-wallet graph nodes without surfacing. Log count in funnel.

## Process discipline
Commit history is atomic (`8bd02e5` lib → `8c66f25` CLI → `b2363dd` fail-closed fix → `434b29e` 5-round bundle). ✓
Note: `be59564` also deleted `.ccg/tasks/phase-2-5-slice-2-multi-feature-reverse-signal/review.md`; that was incidental cleanup of a stale Slice 2 duplicate already archived under `.ccg/tasks/archive/2026-05/phase-2-5-slice-2-multi-feature-reverse-signal/`.
