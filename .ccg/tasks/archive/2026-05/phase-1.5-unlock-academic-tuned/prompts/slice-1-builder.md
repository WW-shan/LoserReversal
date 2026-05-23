ROLE_FILE: /Users/ww/.claude/.ccg/prompts/codex/builder.md

# Phase 1.5 Slice 1 — Data Enrichment

## CRITICAL: Anti-monitor directive

- Do NOT tail/ps/grep for other codex processes. Start writing code IMMEDIATELY.
- Other codex processes belong to the user; UNRELATED to this task.
- If you find yourself wanting to check process state — STOP and start coding instead.
- Do NOT archive this task. Claude will archive after the final verdict.

## Working directory

`/Users/ww/Project/crypto-alpha-portfolio`

Use `uv run` for all execution. Python 3.11+, `from __future__ import annotations` on every new module, 100-char lines, UTC tz-aware, no emojis in code/commits.

## Required reading (skim first)

- `docs/research/literature-review.md` (Part A — academic-tuned unlock spec)
- `docs/research/loser-reversal-indicator/ROADMAP.md` (Phase 1.5 section)
- `.ccg/tasks/phase-1.5-unlock-academic-tuned/plan.md` (this slice's plan)
- `data/seed/parse_emissions.py` (existing parser — you will extend it)
- `src/infra/storage.py` (parquet schemas — you will add `vesting_type` to UNLOCK_SCHEMA)
- `src/infra/fetchers/candles.py` (Hyperliquid candle fetcher, paginated)

## Goal of this slice

Build enough data so signals (Slice 2) can actually compute. Two outputs:

1. **Multi-source unlock events** in `data/parquet/unlocks.parquet` — target ≥ 800 rows post-filter, with new `vesting_type` column populated for every row.
2. **Backfilled HL daily candles** under `data/parquet/candles/{TOKEN}_1d.parquet` for every token that appears in unlocks, going back to 2023-01-01 (or as far as HL has data for that token).

The signals in Slice 2 will be window-based around `unlock_date`. They need ≥ 60 days of pre-event candles for each token, on each event. This slice creates that runway.

## Out of scope (DO NOT TOUCH)

- Any file under `src/signals/`
- Any file under `scripts/run_unlock_*.py` or `scripts/sweep_unlock_*.py`
- Any backtest / walk-forward / report file
- CryptoRank or Tokenomist scrapers (deferred — they need keys / browser auth we don't have)

## Data sources (verified working)

### Hyperliquid candles (existing fetcher reused)
- Existing module: `src/infra/fetchers/candles.py` — already supports paginated fetch with 5000-bar cap and 100 page max
- `info.candle_snapshot` (POST /info, `type: candleSnapshot`)
- 1d candles ≈ 365 bars/year × 3 years = ~1100 bars/token → 1-2 pages per token, safe within MAX_PAGES=100

### DefiLlama emissions-adapters fork (replacing the old `/tmp/emissions-adapters` clone)
- Active fork: `https://github.com/Omni-Chain-Protocols/emissions-adapters` (310 protocols, updated 2026-04-01)
- Clone to `/tmp/emissions-adapters/` so the existing parser path works:
  ```bash
  rm -rf /tmp/emissions-adapters && \
    git clone --depth=1 https://github.com/Omni-Chain-Protocols/emissions-adapters /tmp/emissions-adapters
  ```
- Existing parser `data/seed/parse_emissions.py` walks `/tmp/emissions-adapters/protocols/*.ts`
- Parser already handles `manualCliff`, `manualStep`, `manualLinear` calls

### Hyperliquid universe (for `has_hl_perp`)
- Existing call: `HyperliquidClient().universe()` returns the perp list
- `parse_emissions.py` already does this via `hyperliquid_symbols()`

## Scope (concrete file list)

### Modify
- `data/seed/parse_emissions.py`
  - Capture vesting type per generated event: `cliff` | `step` | `linear`
  - Pass `vesting_type` through `add_event` / `aggregate_rows` / CSV writer
  - Extend CSV fieldnames: `["token", "coingecko_id", "unlock_date", "unlock_pct", "category", "has_hl_perp", "vesting_type"]`
  - Aggregate-rows key now includes `vesting_type` so cliff+step+linear are not merged into one row
  - WINDOW_END remains existing value if still in future, otherwise bump to today
  - WINDOW_START — extend backward to `2023-01-01` so we capture older events that fall within HL candle coverage
- `src/infra/storage.py`
  - Add `"vesting_type"` to `UNLOCK_COLUMNS`
  - Add `("vesting_type", pa.string())` to `UNLOCK_SCHEMA`
  - `write_unlocks_csv_to_parquet`: read with the new column, dtype=string
  - `read_unlocks` (and existing callers) must keep working — confirm by adding/extending tests

### Create (new)
- `scripts/backfill_candles.py`
  - CLI: `uv run python scripts/backfill_candles.py [--start 2023-01-01] [--end now] [--interval 1d] [--tokens TOK1,TOK2,...] [--missing-only]`
  - Default: read `data/parquet/unlocks.parquet`, get unique tokens where `has_hl_perp == true`, fetch 1d candles for each, write `data/parquet/candles/{TOKEN}_1d.parquet` (overwrite — full refresh) unless `--missing-only` is set (then skip files whose existing min-date ≤ start)
  - Use `infra.fetchers.candles.fetch_candles` + `infra.storage.write_candles`
  - Catch per-token exceptions, log a warning, continue (one missing token must not abort the entire backfill)
  - End-of-run summary: total tokens, tokens fetched OK, tokens skipped, tokens failed, range covered
- `tests/seed/test_parse_emissions_vesting_type.py`
  - Three small synthetic protocols files (cliff-only, step-only, linear-only) under a tmp path
  - Patch `PROTOCOLS_DIR`, `hyperliquid_symbols`, `load_coins` to controlled values
  - Run `main()` (or extracted helper) and verify CSV / aggregated rows include the correct vesting_type for each
  - Mixed-vesting protocol: two unlocks on same date with different vesting types stay as TWO rows after aggregation
- `tests/infra/test_storage_unlocks_vesting.py`
  - Construct a small CSV with a `vesting_type` column → `write_unlocks_csv_to_parquet` → `read_unlocks` returns column
  - Existing test file for storage stays green
- `tests/scripts/test_backfill_candles.py`
  - Mock `fetch_candles` to return a small DataFrame
  - Mock `read_unlocks` to return 3 tokens (1 with `has_hl_perp=False`)
  - Verify only the 2 HL tokens are fetched
  - Verify `--missing-only` skips a token whose existing parquet already covers start date
  - Verify per-token exception → logged warning → other tokens still processed
  - Verify run summary printed (capture stdout)

### Do NOT modify
- Anything outside the file list above
- `src/signals/`, `src/infra/backtest/`, `reports/`

## Workflow (strict TDD, ~8 commits expected)

For each module:
1. Add tests first → confirm RED (the symbol doesn't exist yet) → commit `test(...)`
2. Implement → confirm GREEN + ruff clean → commit `feat(...)` or `refactor(...)`

Suggested commit sequence:

1. `test(seed): vesting_type capture cases for parse_emissions`
2. `feat(seed): emit vesting_type per unlock event`
3. `test(infra): vesting_type column in unlocks parquet round-trip`
4. `feat(infra): add vesting_type to unlocks schema`
5. `test(scripts): backfill_candles CLI cases`
6. `feat(scripts): backfill HL candle history for unlock tokens`
7. `chore(seed): widen WINDOW_START to 2023-01-01`
8. (real-data refresh) `chore(data): refresh unlocks parquet + 2023-now candles` (force-add `data/seed/unlocks_curated.csv` + `data/parquet/unlocks.parquet` + new candle files)

After each commit:
- `uv run pytest -q` ≥ existing count
- `uv run ruff check src tests scripts data` clean (note: existing `data/seed/*.py` is already lint-clean; keep it that way)

## Real-data refresh (do this AFTER all code commits)

1. Clone fork:
   ```bash
   rm -rf /tmp/emissions-adapters && \
     git clone --depth=1 https://github.com/Omni-Chain-Protocols/emissions-adapters /tmp/emissions-adapters
   ```
2. Reparse:
   ```bash
   uv run python -m data.seed.parse_emissions
   ```
   Expected output: `parsed_files: 150-250, rows: 800-2000, categories: {...}` — log the actual numbers in your Execution Report.
3. Reseed parquet:
   ```bash
   uv run python -m scripts.seed_unlocks_parquet
   ```
4. Backfill candles:
   ```bash
   uv run python scripts/backfill_candles.py --start 2023-01-01
   ```
   Expected: ~30-50 unique HL-perp tokens, all 1d candles back to 2023 or earliest HL listing. Log per-token min/max date in the run summary.
5. Final sanity check (run this with `uv run python -c "..."`):
   ```python
   import pandas as pd
   df = pd.read_parquet("data/parquet/unlocks.parquet")
   print("rows:", len(df))
   print("with vesting_type:", df["vesting_type"].notna().sum())
   print("categories:", df["category"].value_counts().to_dict())
   print("vesting_types:", df["vesting_type"].value_counts().to_dict())
   print("hl_perp coverage:", df["has_hl_perp"].mean())
   ```

## Acceptance criteria

1. `data/parquet/unlocks.parquet` has ≥ 800 rows (target 1000-2000)
2. Every row has a non-null `vesting_type` ∈ {cliff, step, linear}
3. Category distribution includes at least: team/insiders, investor/privateSale, airdrop, publicSale, noncirculating, ecosystem/community (some may be 0)
4. `data/parquet/candles/*_1d.parquet` exists for every HL-perp token referenced in unlocks; per-token min date ≤ max(2023-01-01, first HL-listing-date for that coin)
5. `uv run pytest -q` ≥ 170 pre-existing + ~10 new tests = 180+
6. `uv run ruff check src tests scripts data` clean
7. Git log shows ~8 small commits (NOT one monolithic commit)

## Out-of-scope guardrails

If you find yourself wanting to:
- Write a signal — STOP (Slice 2)
- Modify a backtest — STOP (Slice 2-4)
- Touch `reports/` — STOP (Slice 5)
- Reach to CryptoRank / Tokenomist — STOP (deferred for now; document in `.ccg/tasks/phase-1.5-unlock-academic-tuned/design-question.md` if you have new info)

## Completion (Execution Report)

In your last message, output:

```
## Execution Report

### Files touched
- {file}: {summary}
...

### Commits (in order)
- {sha} {subject}
...

### Pytest
- baseline: 170
- final: {N}
- last 3 lines of output

### Ruff
- final: clean

### Data refresh numbers
- parse_emissions: parsed_files={N}, rows={M}
- unlocks parquet: rows={N}, vesting_type {cliff=A, step=B, linear=C}, categories {...}
- candles: tokens fetched OK={N}, skipped={M}, failed={K}, earliest min date={ISO}, latest max date={ISO}

### Acceptance checklist
- [ ] ≥ 800 rows in unlocks.parquet
- [ ] vesting_type non-null on every row
- [ ] ≥ 6 distinct categories appear
- [ ] ≥ 20 HL-perp tokens have 2023-now 1d candle parquet
- [ ] pytest ≥ 180
- [ ] ruff clean
- [ ] ~8 small commits, no monolithic commit
```

Then EXIT. Do NOT archive. Do NOT push. Claude does both after the review loop.
