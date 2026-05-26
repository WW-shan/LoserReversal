# Phase 5 Portfolio Composer Review

## Codex Local Review

### Critical

None remaining after the review-fix pass.

### Warning

- `scripts/run_portfolio_composer.py` reports the `monthly_max_drawdown <= 8%` risk check from the weighted portfolio return sequence. The current data source is per-trade OOS returns, not daily account equity, so this is a conservative portfolio drawdown proxy rather than a true calendar-month equity drawdown.
- `src/portfolio/signal_loader.py` permits parquets without a `signal` column and loads all returns in that case. This keeps tests flexible for one-signal fixtures, but future multi-signal production inputs should keep the `signal` column mandatory.
- `PortfolioComposer.combined_metrics()["n_trades"]` sums per-signal trade counts. This is correct for independent trade sleeves but will overcount if future signals fire on the same event and the desired metric is unique portfolio events.

### Info

- Scoped diff is limited to the new portfolio package, new CLI, new tests, active v1+stop config, generated portfolio composition artifacts, and the CCG task files.
- Full verification after fixes: `uv run pytest -q` -> 540 passed; `uv run ruff check src tests scripts` -> clean; scoped `git diff --check` -> clean.

## Claude Review

Initial Claude review found three Critical issues and one Major target-vol issue:

- Kelly sizing used a non-monotonic `lower / (1 + lower^2)` formula.
- Risk-check drawdown passed from configured `max_dd_observed_oos` while the report showed a worse computed drawdown.
- Disjoint timestamped returns could fall back to positional correlation.
- Single-signal allocations skipped target-vol scaling.

Fixes applied:

- Kelly now uses `lower_ci_sharpe / realized_annualized_vol * 0.25`, then caps at `weight_max`.
- Risk-check drawdown now uses weighted portfolio returns.
- Disjoint timestamped correlations return `0.0` when there are fewer than two overlapping observations.
- Single-signal risk-parity and mean-variance weights scale down when target volatility binds before `weight_max`.

External Claude re-review was attempted three times after the fixes. Each attempt started file/diff inspection but did not return a report; the spawned reviewer processes were terminated cleanly to avoid leaving running sessions. No post-fix Claude report was available.
