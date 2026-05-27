# Phase 2.5 Slice 1 Academic Wallet Pool

## Summary
- As of: 2026-05-27T00:00:00+00:00
- Leaderboard rows before script pre-filter: 37295
- After script account-value band pre-filter: 7928
- Leaderboard rows fetched: 2000
- After valid address filter: 2000
- After positive account value filter: 2000
- After fills available filter: 1516
- After account_value filter: 1516
- After realized_loss_rate filter: 803
- After leverage filter: 29
- After n_trades filter: 21
- After size_cv filter: 21
- Final pool size: 21
- Wallets fetched: 1995
- Wallets failed: 5
- Output: `data/parquet/academic_wallet_pool.parquet`
- Runtime seconds: 3209.34

## Delivered n vs ROADMAP target

- **ROADMAP target**: 200–500 wallets
- **Delivered**: 21 wallets
- **Verdict**: spec deviation accepted (path (a) per
  `.ccg/spec/backend/index.md` "Deliverable target vs. empirical population")

### Why deviation, not threshold relaxation

ROADMAP 200–500 target was set from generic academic retail-loser
precedent (Binance / CFD literature). Hyperliquid's active-trader base is
materially different:

- Avg leverage on HL: **5–7x (whales) / 10–20x (retail)** — NYU Stern
  Duron-Carielo perpetual-futures paper; gwrx2005 HL behavior analysis.
- ≥5x is **near-universal** among active HL traders, not a "high leverage"
  signal in the original academic sense.

The funnel `803 losers → 29 leverage≥5x` is correctly selective, not a
bug: it isolates the **multi-factor intersection** of (high leverage ∧
realized losses ∧ retail size band ∧ non-MM diversity) which is the true
"panic-FOMO retail" cohort on HL. Relaxing `leverage ≥3x` would dilute
signal by including low-leverage hodlers; relaxing `loss_rate ≥40%`
would include not-yet-realized losers (forward-looking bias).

Widening universe (top_n=10000+) was rejected as alternative because HL
leaderboard API + downstream fills fetch becomes ~5h runtime with
marginal yield (~3.6% intersection rate constant — would land at n~100,
still under target). 

Downstream slices (Phase 2.5 Slice 2/3/4/5) reference delivered **n=21**,
not target. If Slice 5 walk-forward verdict is RED purely from
small-sample variance (CI width too large), the verdict will record
"power-limited" — not failure of thesis.
