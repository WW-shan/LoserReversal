ROLE_FILE: /Users/ww/.claude/.ccg/prompts/codex/builder.md

# Phase 2 Slice 3 — Fix R2 (docstring + test + cleanup)

## CRITICAL: Anti-monitor
- Do NOT tail/ps. Start IMMEDIATELY.
- Do NOT archive.
- Strict TDD (test → impl) where adding behavior.

## Working directory
`/Users/ww/Project/crypto-alpha-portfolio`

## Background

Slice 3 fix R1 LGTM most critical, 3 Important + 4 Minor remain. Subagent caught docstring vs code mismatch (the project's "Claude verify must be semantic review" lesson in action).

## Fixes

### Important 1 — `_verdict` docstring must match code

**File**: `scripts/run_wallet_walkforward.py` (around `_verdict` docstring, lines 404-413)

The docstring claims `max_drawdown_breach < -0.30`, `thresholds_not_met` exists, and lists range characterizations that don't match code. **Rewrite docstring to match what the code actually does**:

```python
"""
Determine verdict label and reason from aggregate stats.

RED reason order (first match wins):
- data_gap: oos_n_trades_total == 0
- insufficient_sample: 0 < oos_n_trades_total < 50
- max_drawdown_breach: oos_n_trades_total >= 50 AND oos_max_dd_worst < -0.25
- oos_ir_below_yellow: oos_n_trades_total >= 50, dd ok, but oos_ir_mean < 1.0
- insufficient_oos_trades: 50 <= oos_n_trades_total < 100, ir >= 1.0, dd ok

YELLOW: oos_n_trades_total >= 100 AND 1.0 <= oos_ir_mean < 1.2 AND dd >= -0.25 (yellow_thresholds_met)
GREEN: oos_n_trades_total >= 100 AND oos_ir_mean >= 1.2 AND dd >= -0.25 (green_thresholds_met)

Note: thresholds_not_met is NOT emitted by this function (only by unlock_walkforward).
"""
```

Verify the actual code branches match this exactly. If code has slight differences, update docstring to reflect code (NOT spec) — code is the source of truth.

### Important 2 — Test `insufficient_oos_trades` verdict

**File**: `tests/scripts/test_run_wallet_walkforward.py` (extend `test_walkforward_verdict_logic_for_green_yellow_and_red_reasons`)

Add assertion:

```python
# 50 <= n < 100, ir >= 1.0, dd ok → insufficient_oos_trades
assert walkforward._verdict(
    {"oos_ir_mean": 1.4, "oos_n_trades_total": 70, "oos_max_dd_worst": 0.0}
) == walkforward.Verdict("RED", "insufficient_oos_trades")
```

### Important 3 — Refresh `reports/wallet_reverse_walkforward.md`

This will be done AFTER all other fixes. At the end of this fix round, run:

```bash
uv run python scripts/run_wallet_walkforward.py --top-wallet-n 50 --report reports/wallet_reverse_walkforward.md
```

Then commit: `chore(reports): refresh wallet walkforward report with R2 fixes`

(Use `git add -f` if `reports/` is in `.gitignore`, mirroring Phase 1 Slice 3 commit `8949da8`.)

Confirm the regenerated report shows:
- `min_train_days: 120 (effective: 30)` style pairs (or the equivalent for actual config)
- `> [WARN] walk-forward fallback used` banner below Verdict line
- New `Reason: data_gap` (or whatever the verdict is)

### Minor 4 — Remove dead underscore alias block

**File**: `scripts/run_wallet_reverse_backtest.py:703-706`

Delete these 4 reverse aliases (`_backtest_freq = backtest_freq` etc.) — no code uses them.

Keep the forward aliases at lines 698-702 (`daily_sharpe`, `load_or_fetch_candles`, `run_path_backtest`, `summed_equity`, `trade_level_ir`) — those are used by cluster backtest.

### Minor 5 — Alias style consistency

After deleting the reverse aliases (Minor 4), all aliases should be the `public = _private` pattern. Either:
- (a) Keep current convention: internal definitions stay `_`-prefixed, public is alias (no further changes after Minor 4)
- (b) Rename internal `_daily_sharpe` etc. to drop underscore and remove all aliases

Choose (a) — minimal diff. Add a one-line comment above the alias block:

```python
# Public stable API for cross-module callers (cluster backtest, walkforward).
# Internal definitions retain underscore prefix for module-private style.
daily_sharpe = _daily_sharpe
...
```

### Minor 6 — Boundary test scans all scripts

**File**: `tests/scripts/test_script_import_boundaries.py`

Currently checks only `run_wallet_cluster_backtest.py` and `run_wallet_walkforward.py`. Extend to scan ALL `scripts/*.py`:

```python
import ast
from pathlib import Path

def test_no_underscore_prefix_cross_script_imports():
    scripts_dir = Path("scripts")
    for script in scripts_dir.glob("*.py"):
        tree = ast.parse(script.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                # Same-module self-imports are not a thing in scripts/, but guard
                if node.module and node.module not in {script.stem, "infra", ...}:
                    continue
                for alias in node.names:
                    assert not alias.name.startswith("_"), (
                        f"{script.name} imports private {alias.name} from {node.module}"
                    )
```

Adjust the implementation as needed for the actual project layout — the goal is "ALL `scripts/*.py` files are scanned, none imports `_`-prefixed name from another script".

## Workflow

5-6 commits, strict TDD where adding behavior:

1. `test(scripts): pin insufficient_oos_trades verdict reason`
2. `docs(scripts): rewrite _verdict docstring to match code`
3. `refactor(scripts): drop dead underscore reverse aliases + add comment`
4. `test(scripts): extend boundary test to all scripts/*.py`
5. `chore(reports): refresh wallet walkforward report with R2 fixes`

## Acceptance

- `uv run pytest -q` → 170 + new test pass
- `uv run ruff check src tests scripts` clean
- New `insufficient_oos_trades` test passes
- `_verdict` docstring matches code line by line
- `reports/wallet_reverse_walkforward.md` shows `(effective: N)` pairs + `> [WARN] walk-forward fallback used` banner
- No `_`-prefixed cross-script imports anywhere in `scripts/`

## Out of scope

- Per-coin cooldown opposite-side bug (subagent Minor 6 — file as follow-up issue, not for R2)
- New cluster signal features
- Pre-existing TDD git history

## Completion

Execution Report with files changed, all commits, final pytest output, ruff output, regenerated report excerpt (first 25 lines showing Verdict banner + Config effective pairs).

Then EXIT. Do NOT archive.
