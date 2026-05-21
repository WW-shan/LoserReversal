# crypto-alpha-portfolio

> Personal quant research — discover, validate, and live-trade independent crypto alpha edges.

A 16-20 week structured exploration of four uncorrelated alpha sources on on-chain markets (Hyperliquid + DeFi). Each edge runs through a Pass/Kill thesis-check, and only the survivors enter the final paper-traded portfolio.

## Roadmap

| Phase | Edge | Pass/Kill |
|-------|------|-----------|
| 0 | Data + backtest infrastructure | — (geological foundation) |
| 1 | **Token unlock → price reaction** | Thesis ✅ verified (T-7 → T0 short window, mean AR=-8.2%, p=0.01) |
| 2 | Single-wallet contrarian (mirror losing whales) | Pending |
| 3 | Cross-venue funding arbitrage | Pending |
| 4 | Anti-Sybil cluster signals | Pending |
| 5 | Portfolio optimization + paper trading | — |
| 6 | Small-size live trading | — |

See [`docs/research/loser-reversal-indicator/ROADMAP.md`](docs/research/loser-reversal-indicator/ROADMAP.md) for full timeline and Pass/Kill criteria.

## Phase 1 finding (already shipped)

The token-unlock thesis is **directionally confirmed** with a key correction to the original hypothesis:

- **Original guess**: unlocks dump price *after* the event (T0 → T+3 short)
- **Empirical reality**: pre-event window T-7 → T0 shows mean abnormal return -8.21% vs BTC, p=0.01, 87.5% of events negative
- **Post-event**: 50/50, mean +1.1% — bounce, not continued dump
- **Driver**: supply-shock magnitude (not insider selling specifically) — noncirculating releases drop equally hard

Code + report: [`src/unlock_validation/`](src/unlock_validation/), [`reports/unlock_thesis_report.md`](reports/unlock_thesis_report.md).

## Public / Private boundary

The repo is public but strictly separated:

✅ **In repo**: research methodology, backtest infrastructure, data fetchers, public datasets, plan documents
❌ **Not in repo**: strategy parameters, live PnL, private wallet pools, CCG workflow state (`.ccg/` is gitignored)

Reason: full strategy disclosure would create a reflexivity loop and decay the alpha. Methodology and tooling are safe to share.

## Tech stack

- **Python 3.11+** (uv-managed)
- Data: `requests`, `pandas`, `numpy`, `scipy`, `tenacity` — minimal core; heavier libs added per-phase
- Sources: Hyperliquid `info` API, CoinGecko `market_chart`, DefiLlama emissions-adapters fork
- Tests: `pytest` + `pytest-mock`, TDD per module

## Layout

```
src/unlock_validation/   Phase 1 module (fetcher / analyzer / report / CLI)
data/seed/               Curated event datasets (e.g. unlocks_curated.csv)
data/cache/              API response cache (gitignored)
docs/research/           Research foundation (ROADMAP, REPORT, evidence)
docs/superpowers/        Phase-specific plans + design specs
reports/                 Generated analysis reports (gitignored)
tests/                   Per-module test suites
```

## Quick start

```bash
uv sync --group dev
uv run pytest -v                    # full test suite
uv run python -m unlock_validation  # end-to-end thesis check
```

## Phase 0 — Infrastructure (shipped)

```bash
uv run python -m scripts.seed_unlocks_parquet
uv run python -m scripts.run_toy_backtest
uv run python -m scripts.run_btc_sma_e2e [--days N]
```

## License

MIT
