# Backend Spec Index

> CCG `phase-guide.md` Section 8 Spec Evolution sink for backend conventions.
> Each entry: short rule + **Why** (incident / reasoning) + **How to apply**
> (where the rule kicks in).

Initialized 2026-05-26 during retro Phase 6 closure of phase-2.5-academic-wallet,
phase-1.5-rescue-ablations, phase-3-funding-arbitrage, phase-4-slice-1.

## Entries

### bot/wallet score gating — n_trades minimum threshold
**Rule**: any score function over behavioral features must gate on a minimum
n_trades count before evaluating; below threshold → return 0.0 (fail closed).

**Why**: phase-4-slice-1 Round 1 review found that `score_bot_likelihood` over
all-zero features (returned by `compute_bot_features` on empty fills) produced
0.55 — above default classification threshold — because 3 of 5 sub-scores are
inverted ("low value = bot-like"). All-zero inputs satisfy the inverted
conditions trivially. Fix: gate on `n_trades >= min_trades_for_scoring`
(default 10) before scoring.

**How to apply**: when designing a feature-weighted scoring function, always
include a "data sufficiency" gate (n_trades / n_observations / sample_size)
that returns the neutral / fail-closed value when insufficient. Add a
sanity test: `score(empty_features()) == neutral_value`. Source:
phase-4-slice-1 Round 1 C1.

### USD notional vs base-asset size for HL trade features
**Rule**: all feature math that intends "trade size in dollars" must use
`notional = abs(px * sz)`, not raw `sz`. Hyperliquid `sz` is base-asset
contract count (BTC, ETH, etc.), not USD.

**Why**: phase-4-slice-1 Round 1 review found `_round_number_pct` and
`size_uniformity_cv` operating on raw `sz`. For BTC at $67k a $1000 trade
has `sz=0.0149` — the "round $100 multiple" check fails. ROADMAP spec said
`$1000/$5000` (USD) but code matched against `sz`. Convention is established
in: `signals/wallet_cluster_v1.py:94`, `signals/wallet_reverse_v1.py:82`,
`wallet_pool/academic_pool.py:100`, `wallet_pool/reverse_signal.py:159`.

**How to apply**: when computing trade-size features from HL fills, pass
`notional` (not `sz`) to downstream consumers. Cross-coin CV otherwise
inflates by 10000× depending on coin price. Source: phase-4-slice-1 Round 1 C2.

### Threshold parameter validation
**Rule**: public scoring/classification APIs must validate threshold and
sample-size parameters with explicit ValueError; never silently clamp or
nudge with epsilon.

**Why**: phase-4-slice-1 Round 1 found `is_bot_wallet` silently `_clamp01`'ing
invalid thresholds (e.g., `threshold=2.0` → `1.0`, "no wallet ever classified"
silently) and adding `+1e-12` to scores. Round 2 fixed threshold validation
but kept the epsilon; Round 3 finally removed it.

**How to apply**: validate at the public API boundary; raise ValueError with
specific message including the offending value. Add tests for both 0 and
out-of-range. Avoid epsilon nudges — if a test depends on inclusive boundary,
make the test fixture produce the genuinely-boundary value. Source:
phase-4-slice-1 Round 1 I4, Round 3 I3.

### Per-signal entry-date semantics in regime/event filters
**Rule**: when a filter that operates on "event timestamps" (unlock dates,
funding ticks, etc.) is paired with signals that fire at varying offsets
relative to those events, the filter must evaluate the gating condition
at each signal's *actual entry timestamp*, NOT the raw event timestamp.

**Why**: phase-1.5 Ablation C (BTC <200d MA filter) initially evaluated the
regime at `unlock_date`, but v2 signal enters at T-30. The filter therefore
used 30 days of future BTC data relative to the actual short entry. v1=-7,
v3=-2, v4=-3, v5=+3 had similar (smaller-magnitude) drift. Round 2 fix
required threading `entry_offset_days` from `SIGNAL_REGISTRY` through the
walkforward → backtest → filter chain.

**How to apply**: any per-event filter should accept a `signal_offset_days`
parameter (or read from a signal-spec registry) and compute the gating
timestamp as `event_date + signal_offset_days`. Add tests parametrized over
every signal in the registry (don't just test one). Source:
phase-1.5-rescue-ablations Round 1 C1, Round 2 expanded scope.

### True-range ATR requires OHLC; close-only is a documented downgrade
**Rule**: when computing ATR-based stops, use Wilder's true range formula
`max(high-low, |high-prev_close|, |low-prev_close|)` and Wilder RMA
`ewm(alpha=1/period, adjust=False)`. The close-only proxy
`abs(close.diff()).rolling(period).mean()` is a SMA-based degradation that
systematically underestimates TR.

**Why**: phase-1.5 Ablation D-ATR Round 1 had a close-only proxy; Round 2
review caught that the production path passed only close to the helper. Round
2 fix threaded `high`/`low` through `BacktestConfig` → `_atr_stop_series` →
`_compute_atr`. After the fix, the 7 close-only `UserWarning`s in the test
suite dropped to 0.

**How to apply**: ATR helpers should accept `high: pd.Series | None = None`,
`low: pd.Series | None = None` and `warnings.warn` when falling back to
close-only. Production callers (BacktestConfig, run_cell, etc.) MUST thread
OHLC when available. Both paths should use Wilder RMA `ewm(alpha=1/period)`
for warm-up consistency. Source: phase-1.5-rescue-ablations Round 1 I1,
Round 2 expanded scope, Round 3 M-2.

### Escape `%` in argparse help strings
**Rule**: any literal `%` character in argparse `help=` strings must be
written as `%%`. argparse passes help text through `%`-formatting in
`HelpFormatter._expand_help`.

**Why**: phase-1.5-rescue-ablations Round 4 review caught that `scripts/
run_unlock_walkforward_v15.py` had `"10%"`, `"8%"`, `"25%"` literals in
help strings introduced by `--stop-loss` and ATR commits. `python ...
--help` crashed with `ValueError: unsupported format character ')'`. Tests
passed because they invoked `_parse_args(["--stop-loss", "0.1"])` directly,
never `-h`.

**How to apply**: when a help string contains a `%`, write `%%`. Add a
smoke test `test_cli_help_does_not_crash` that calls `_parse_args(["-h"])`
and asserts `SystemExit(0)` to prevent regression. Source:
phase-1.5-rescue-ablations Round 4 I1.

### Deliverable target vs. empirical population — Hyperliquid leverage cohort
**Rule**: when academic criteria from ROADMAP are intersected against a
real exchange population, validate the deliverable target (`n_wallets`,
`n_events`, etc.) against an empirical population check BEFORE committing
to it as the gate. If the empirical yield is < target, the correct
response is one of: (a) document spec deviation and accept the smaller
cohort, (b) widen the candidate universe (deeper leaderboard scan), or
(c) explicitly relax a named criterion with a recorded reason. Never
relax silently to chase a number.

**Why**: phase-2.5-academic-wallet Slice 1 ROADMAP target "200-500 wallets"
was set from generic academic precedent (Binance/CFD retail), but HL's
active-trader base differs: avg leverage 5-7x (whales) / 10-20x (retail)
per NYU Stern Duron-Carielo perpetual-futures paper and gwrx2005 HL
behavior analysis. On HL top-2000 leaderboard, the multi-criteria
academic filter (acct $1k-$100k + loss_rate ≥50% + leverage ≥5x +
n_trades ≥50 + size_cv ≥0.3) yields n=21 — the "genuine panic-retail"
cohort. Funnel: 2000 → 1516 has-fills → 803 loss_rate → 29 leverage
→ 21 n_trades. Bottleneck is leverage ≥5x ∧ loss_rate ≥50% (3.6%
intersection) which is correctly selective, not a bug. Relaxing
leverage to ≥3x would dilute signal (capture low-leverage hodlers,
not panic-FOMO traders) and break the academic basis.

**How to apply**: when delivering an academically-defined cohort from
an exchange-specific population, the report MUST contain the funnel
breakdown by criterion AND an explicit "delivered n vs target n"
section. If under target, choose (a)/(b)/(c) and record reason in the
report + this spec file. Downstream slices reference the delivered n,
not the target. Source: phase-2.5-academic-wallet Slice 1 R6 + R7
deep-research investigation (smart-search 2026-05-27).

### Time-series boundary slicing must be strict-less-than for point-in-time queries
**Rule**: when looking up a feature value "as of" some timestamp `T` from
a time-indexed frame, slice with `frame.loc[frame.index < T]` (strict
less-than), NOT `frame.loc[:T]` (inclusive). pandas inclusive label
slicing INCLUDES the row at exactly `T`.

**Why**: phase-2.5-slice-2 R1 caught lookahead leak: `_funding_context_for_fill`
used `normalized.loc[:timestamp]`. A fill at exactly `T==funding_settle_time`
included that settle row's funding zscore — information not yet known at
fill execution. Contrarian alpha is exquisitely sensitive to point-in-time
hygiene; HL retail clusters around funding-settle in anticipation, so this
boundary matters in practice.

**How to apply**: any "as-of" lookup against time-indexed data must use
`< T` not `<= T` unless there's an explicit reason the boundary row is
already settled. Add a boundary test: query at exact tick timestamp must
NOT see that tick's value. Source: phase-2.5-slice-2 R1 C1.

### Derive cadence/anchor from prior data only, not full frame
**Rule**: when auto-detecting periodic cadence (funding interval, candle
spacing, settle anchor) from time-indexed data for use at a specific
timestamp `T`, derive cadence and anchor from rows where `index < T` only,
not the full frame.

**Why**: phase-2.5-slice-2 R2 caught second-order leak: `_funding_settle_signal`
derived interval from `np.median(np.diff(full_funding_frame))` and assumed
UTC-midnight anchor. A fill BEFORE the first funding row received a "settle
window" boost from future-detected cadence. Non-midnight phases (some venues,
historical 03/11/19 UTC schedules) were misclassified.

**How to apply**: when computing time-aware features, slice the prior data
first, then derive cadence/anchor/baseline from that slice. Carry anchor
timestamp (e.g., last prior settle) into downstream context; do not assume
fixed phase. Burn-in (<2 prior samples) → return None, fail-closed.
Source: phase-2.5-slice-2 R2 I-R2.1.

### Multi-feature score product needs smooth normalization, not step thresholds
**Rule**: per-feature multipliers combined via product must use smooth
0-1/logistic functions, NOT discrete step-function thresholds. Step
functions create discontinuities at signal=threshold and a single dead
zone before threshold contributes nothing.

**Why**: phase-2.5-slice-2 R1 found `funding_extreme_multiplier` returned
literal 1.0 when `|z|<2.0` then jumped to 1.4 — step at z=2. Production
funding signal under 30-day rolling never hit |z|≥2 (0/15884 fills), so
1/4 design axes was identically dead. Switching to smooth sigmoid:
`1 + (max-1) * sigmoid((signal-pivot)/temp)` gave continuous boost,
restored signal contribution.

**How to apply**: when designing multi-feature interaction scores, use
sigmoid/logistic normalization with documented pivot and temperature.
Verify on real production data: each component's distribution should
span a non-trivial range, not collapse to constant. Source:
phase-2.5-slice-2 R1 I7 + R2 M-R2.2.

### Confidence weight features must use log-scale on long-tail metrics
**Rule**: when constructing wallet-level / item-level confidence weights
from cumulative counts (n_trades, n_orders, volume), use log-scale
transformation `_bounded_linear(math.log1p(value), low=log1p(lo), high=log1p(hi))`
not linear. Linear scaling saturates for long-tail distributions.

**Why**: phase-2.5-slice-2 R1 found `trade_component = _bounded_linear(n_trades, 50, 200)`
saturated at 1.0 for 19/21 production wallets (n_trades ∈ [103, 8175]).
Confidence weight lost 1/3 discriminative power. Log-scale `low=log1p(50),
high=log1p(5000)` restored spread to 0.598 on the same n=21 pool.

**How to apply**: for any feature where the empirical distribution
spans >2 orders of magnitude, use log-scale. Verify on real data:
component values across the actual cohort should span >0.3 wide, not
cluster at one extreme. Source: phase-2.5-slice-2 R1 I3.


### Legacy keyword paths must route through the dataclass constructor
**Rule**: when a public API supports both a `config: SomeConfig` keyword
and a legacy individual-parameter keyword (kept under
`DeprecationWarning`), the legacy path MUST construct the config dataclass
via `SomeConfig(field=legacy_value)` rather than duplicating the
validation inline or skipping it. Validation lives only in
`__post_init__`; legacy paths must not bypass it.

**Why**: phase-2.5-slice-3 R2-I1: after R1 added `BotExclusionConfig.__post_init__`
validation (rejecting `funding_source_graph_max_shared < 2`), the legacy
`exclude_funding_source_clusters(..., max_shared=1)` keyword path still
emitted only a `DeprecationWarning` then proceeded to exclude singletons.
Codex repro: `max_shared=1` on a graph of `{"0xsolo": set()}` returned
`['0xsolo']`. Fix: legacy branch calls `BotExclusionConfig(funding_source_graph_max_shared=max_shared)`,
which raises `ValueError` for invalid values before the `warnings.warn`
call, then uses the validated value for valid cases.

**How to apply**: when introducing a `config=`/legacy-keyword pair, make the
legacy branch a thin adapter that constructs the config and reads back
the validated field. ValueError fires for invalid input (no
DeprecationWarning needed — the call was malformed); DeprecationWarning
fires only for valid input (nudging migration). Add tests
parameterized over both invalid (`pytest.raises(ValueError)`) and valid
(`pytest.warns(DeprecationWarning)`) legacy values. Source:
phase-2.5-slice-3 R2-I1.

### Mixed valid/NaN duplicate row collapse must prefer valid deterministically
**Rule**: when deduplicating rows keyed by some column where values may be
NaN, plain `drop_duplicates(keep="last")` is order-dependent and can
silently overwrite a valid value with NaN. Use a 2-step pattern:
`frame.sort_values(value_col, na_position="first")` (or equivalent
factorize trick) then `drop_duplicates(subset=[key_col], keep="last")` so
NaN rows are always dropped first.

**Why**: phase-2.5-slice-3 R2-I2: `_coerce_bot_scores` used
`nunique(dropna=True)` to check conflicts then `drop_duplicates(keep="last")`.
Input `[(0xA, 0.9), (0xa, NaN)]` passed the conflict check (nunique=1) and
then NaN won via "last", erasing the real bot score. Production path
emits one row per wallet so the bug was latent, but the API silently lost
data — same class as spec rule "Threshold parameter validation" (never
silently clamp at public API).

**How to apply**: for any DataFrame-coercion helper that ingests user-supplied
rows where the value column can be NaN, choose the pattern that fails
closed for absent data and succeeds for present data: sort so NaN comes
first, drop_duplicates keep last. Add 2 regression tests with the input
in both row orders to catch order-dependent regressions. Source:
phase-2.5-slice-3 R2-I2 (Codex Important; subagent Minor — combined
strictest = Important).

### Signal state machines must compare aligned bars, not raw timestamps
**Rule**: when a signal state machine (entry/exit, hold-expiry, position
swap) compares event timestamps against decision bars to decide whether
two events collide on the same bar, the comparison MUST be on *aligned*
bars (post `_align_to_price_index` / `searchsorted`), NOT on raw
timestamps. Raw-timestamp equality fails on coarse-grid markets where
two distinct event times resolve to the same price bar.

**Why**: phase-4-slice-2 R2-M2: `_apply_candidates` originally checked
`candidate_time == hold_exit_at` (literal raw-timestamp equality) to
decide whether to defer same-direction re-entry. On 2h-bar markets with
`hold_hours=1`: `hold_exit_at=01:00` aligns to `02:00`, candidate at
`01:30` also aligns to `02:00`, but `01:30 != 01:00` so the deferral
never fires and `entry=True + exit=True` collide on the same `(02:00,
short)` slot. Production HL 1h bars with integer `hold_hours` made the
case unreachable, but the policy gap existed. Fix: compute `candidate_bar`
and `exit_bar` via `_align_to_price_index`, then compare those bars.

**How to apply**: in any signal state machine, after `searchsorted` /
`_align_to_price_index` calls return the decision bar, perform boundary
comparisons on those aligned bars. Add at least one boundary test on a
COARSER price grid than the production timeframe (e.g., 2h bars when
prod is 1h) to catch alignment-dependent collisions. Source:
phase-4-slice-2 R2-M2 (subagent Minor; Codex did not flag — combined
strictest precedent says trust subagent on alignment-class bugs).

### CCG retro fix-loop commits should be per-finding atomic
**Rule**: each CCG retro fix-loop commit should address exactly one
review finding (or one tightly-coupled finding group with documented
rationale). Aggregating N findings into 1-2 monolithic commits reduces
retro traceability — the next reviewer cannot easily verify each
finding's closure, and `git log --oneline` no longer reflects the
fix-loop's finding sequence.

**Why**: phase-4-slice-2 R1 fix-loop aggregated 13 findings into 2
commits (`b370a02` lib 6-findings, `4d44da6` script 7-findings). Both
Codex and subagent R2 reviewers flagged this. By contrast,
phase-2.5-slice-3 had 8 atomic commits in R1 fix (one per finding) and
5 in R2; reviewers verified each closure trivially from `git log` +
`git show <hash>`. Aggregation does not produce technical regressions
but obscures the audit trail.

**How to apply**: builder prompts should explicitly require atomic
per-finding commits (with `fix(...)` prefix matching the finding ID
where possible). Exceptions allowed when findings are tightly coupled
(e.g., new public API + caller-update in one feature) — must be
explicitly justified in the commit body. Source: phase-4-slice-2 R1
fix-loop + R2 process review (Codex + subagent both flagged as Minor).



