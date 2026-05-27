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
