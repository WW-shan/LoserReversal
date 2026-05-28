# Session Primer — crypto-alpha-portfolio

> **Read this first when starting a new session on this project.**
> Last updated: 2026-05-29

---

## 1. What this project is

Personal quant crypto research portfolio. Goal: validate 4 independent
alpha sources on Hyperliquid perps, build a Sharpe ≥1.5 multi-strategy
portfolio, deploy to paper trading then small-money live.

**Master plan**: `docs/research/loser-reversal-indicator/ROADMAP.md`
(read first 80 lines for the 2026-05-29 update + 4-thesis status).

**Current snapshot**: `docs/research/status-snapshot.md` (read entirely
— it has current verdicts, gate state, and next-session priorities).

---

## 2. Must-read files (in this order)

1. **This file** (`docs/research/SESSION_PRIMER.md`) — orientation
2. `docs/research/status-snapshot.md` — current state, all verdicts, next priorities
3. `docs/research/loser-reversal-indicator/ROADMAP.md` §2026-05-29 update (first 100 lines) — master plan + concept clarifications
4. `.ccg/spec/backend/index.md` — 16 spec rules from accumulated retros (each rule has Why + How to apply)
5. `/Users/ww/.claude/projects/-Users-ww-Project-crypto-alpha-portfolio/memory/MEMORY.md` — auto-loaded; check for new entries
6. `/Users/ww/.claude/.ccg/engine/phase-guide.md` — CCG universal phase guide
7. `/Users/ww/.claude/.ccg/engine/strategies/guided-develop.md` — M-complexity strategy (most tasks use this)

---

## 3. CCG flow × user's actual workflow

### CCG canonical design (for reference)
- `/ccg:go` slash command auto-routes by complexity
- `guided-develop` strategy for M (2-5 files, single module)
- 8 phases: 1-requirements → 2-context → 3-analysis → 4-plan (**HARD STOP**) → 5-implement → 6-verify (Ralph Loop) → 7-spec-evolution → 8-archive

### User's actual workflow (manual orchestration)

User does NOT use `/ccg:go` slash commands. Instead, manual CCG orchestration:

1. **Requirements**: discuss in chat, no separate doc
2. **Context**: read relevant code via Read tool
3. **Analysis** (Phase 3): for M+ complexity, dispatch Codex + Claude local in parallel. Codex via `codeagent-wrapper`:
   ```bash
   /Users/ww/.claude/bin/codeagent-wrapper --lite --progress --backend codex - "$WORKDIR" < prompt.md > output.md 2>&1
   ```
   In background via `run_in_background: true`. Wait for completion notification, then read output.
4. **Plan (HARD STOP)**: use `AskUserQuestion` tool with 2-4 options. **Never skip this.** User has called this out twice when violated.
5. **Implement**: Backend → Codex builder, Frontend → Claude local. Atomic per-finding commits (spec rule).
6. **Ralph Loop verify**: 3-way review per round, max 3 rounds:
   - Claude local (read source, audit logic vs spec)
   - superpowers subagent via `Agent` tool with `subagent_type: "general-purpose"`, prompt fills `code-reviewer.md` template, `run_in_background: true`
   - Codex reviewer via `codeagent-wrapper` (same pattern as analyzer)
   Convergence = READY: YES, 0 Critical + 0 Important.
7. **Spec Evolution**: ⛔ never silent. Use `AskUserQuestion` to confirm each rule. Write to `.ccg/spec/backend/index.md` (or frontend/guides). Source quote in body.
8. **Archive**: `.ccg/tasks/archive/$(date +%Y-%m)/{task-name}/` with `task.json` containing rounds + spec_evolution. Commit `chore(ccg): archive ...`.

### Manual workflow vs `/ccg:go`

| Step | Manual | Slash command |
|---|---|---|
| Task dir | manual `mkdir .ccg/tasks/{slug}/` | auto |
| task.json | manual | auto-tracked |
| Spec injection | manual (read CLAUDE.md / specs) | PreToolUse hook |
| Codex dispatch | manual `codeagent-wrapper` | wired |
| Subagent dispatch | manual `Agent` tool | wired |
| Plan HARD STOP | manual `AskUserQuestion` | enforced |
| Archive | manual `mv` | auto-cleanup |

**Don't try to switch user mid-task to `/ccg:go`** — they have explicitly chosen manual ("就按现在这个在本项目设计好的流程继续").

---

## 4. Adversarial Ralph Loop is non-negotiable for M+

R1/R2/R3 on 2026-05-29 found:
- R1: 6 Critical (lookahead leaks, NaN, max-gap)
- R2: 3 more Critical I introduced fixing R1
- R3: converged 0/0/0

Single-pass review caught **0 of 9 Critical**. The bugs were genuinely
subtle (e.g., `bool(np.nan) == True`). Pytest + ruff passed all 871 the
whole time. The only thing that catches these is:

1. Three reviewers (Codex / subagent / Claude semantic) in parallel
2. Iterating until 0/0/0 — don't trust R1 single-pass

When user says "完整完成 token 不用省" or similar, they mean **also do
the Ralph Loop**. Don't ship M+ features without it.

---

## 5. Key concepts (frequently confused)

### Funding rate direction
- **Positive funding**: longs PAY shorts → SHORT collects funding (NOT long)
- This is opposite of common intuition

### Strategy A vs B (both use funding, very different)
- **Strategy A (Farming, hedged)**: SHORT perp + LONG spot → pure funding income, no price risk. Needs spot venue for hedge.
- **Strategy B (Directional contrarian)**: SHORT perp at extreme positive funding → bet on mean-reversion. No hedge. This is Phase 3 `funding_extreme_v1`.

### Lookahead leak forms (3 levels of subtlety)
1. **Direct**: tomorrow's price in today's decision
2. **Subtle**: threshold from full-sample distribution (caught 3 times in 2026-05-29 retro)
3. **Boundary**: same-day data for entry decision (e.g., daily mean of full day T for an entry at T+intraday)

PIT regression test (`truncate-then-compare`) is the only reliable defense — see spec rule "PIT regression test pattern".

### CLT floor 30
- n<30: ~12% statistical power → Sharpe is noise → INCONCLUSIVE not RED
- A "RED with bugs" is FALSE confidence — could wrongly kill thesis
- Per 2026-05-29 retro: 3 RED verdicts demoted to INCONCLUSIVE

### Cross-thesis diversification
- v1+D, v1+ATR, v2+ATR are unlock thesis variants → correlated → count as 1 source
- Phase 5 gate ≥2 GREEN/YELLOW requires DIFFERENT alpha sources (unlock + funding + wallet + bot)
- Two YELLOW from same thesis = 1 cross-thesis YELLOW for gate purposes

---

## 6. Operational facts

### CEX proxy
- `127.0.0.1:10808` unblocks Binance / Bybit / Bitget / OKX APIs (was Phase 3 blocker)
- Python: `requests.get(url, proxies={"http": "http://127.0.0.1:10808", "https": "http://127.0.0.1:10808"})`
- ccxt: `exchange.proxies = {"http": "...", "https": "..."}`

### Test count baseline (2026-05-29)
- 871 passing
- Phase 1.5 + 2.5 + 4 + 5 + infra modules
- 26 tests bot_walkforward + 22 tests wallet_reverse_signal + 27 regime_filter

### Repo conventions
- `data/parquet/` is .gitignored — use `git add -f` for new artifacts
- `reports/` is .gitignored — same
- `.ccg/` is .gitignored — same
- All three need `-f` flag when committing

### Smart-search CLI
- For external research, `smart-search` is configured (xAI + Tavily + Context7)
- `smart-search doctor --format json` to check
- See skill file `userSettings:smart-search-cli` for full usage

---

## 7. Current state (2026-05-29, 22 commits ahead of 2026-05-27)

### Phase 5 gate: 1/2

Only 1 YELLOW signal (Phase 1.5 v1+D). Need ≥2 cross-thesis to unlock #19 paper signal generator.

### 4 features post-Ralph-Loop:
| Feature | True verdict |
|---|---|
| D-ATR sweep | YELLOW v2+ATR mult=1.5 (real but same thesis as v1+D) |
| Phase 4 Slice 3 bot reverse | INCONCLUSIVE n=0 (need 500+ wallet pool) |
| Phase 2.5 Slice 5 wallet reverse | INCONCLUSIVE n=29 (need wallet-aware exits) |
| Phase 1.5 funding-regime | v5 RED (rescue was lookahead artifact, abandoned) |

### Pending priorities

1. **#16** Phase 3 1h candle backfill + walkforward re-run (50-80k tokens + 50-90min wall)
2. **#21** Phase 3 cross-exchange funding arb (proxy unblocked, 100-150k)
3. **#22** Expand bot pool 50→500 + re-run Slice 3 (40-60k + 30-60min API)
4. **#23** Wallet-aware exits + re-run Slice 5 (60-90k)
5. **#18** Phase 2.5 Slice 4 cluster v2 + cascade (100-150k)
6. **#19** Phase 5 paper signal generator (gated)

---

## 8. Common pitfalls to avoid

### From 2026-05-29 retro experience:

1. **Don't treat M complexity as quick-implement**. Skipping Phase 4 HARD STOP and Phase 6 Ralph Loop = 9 Critical bugs that fabricate false verdicts.

2. **Don't claim "tests pass, looks good"** without semantic review. All 9 Critical bugs passed pytest + ruff.

3. **Don't write to `.ccg/spec/`** without user confirmation via `AskUserQuestion`. Spec evolution is the only path to compounding rules.

4. **Don't normalize verdicts as RED prematurely**. If n < 30 OOS trades, it's INCONCLUSIVE (data insufficient), not RED (thesis tested and failed).

5. **Don't conflate same-thesis variants with cross-thesis diversification**. v1+D and v2+ATR are not 2 Phase 5 gate units, they are 1.

6. **`bool(np.nan) == True`** — always wrap DataFrame bool reads in `_safe_bool` helper. NaN landmine.

7. **Searchsorted side="left" without max_gap_hours guard** is a price leak waiting to happen on sparse candle data. Always guard.

8. **Full-sample quantile** is lookahead leak. Use expanding-prior-window with strict-time count (`sorted_times.searchsorted(times, side="left")`), NOT `expanding().shift(1)` which is row-order PIT.

---

## 9. How to quickly resume

```
Read this file in full.
Read docs/research/status-snapshot.md.
Read .ccg/spec/backend/index.md (skim, focus on rules with "2026-05-29" timestamp).
Check MEMORY.md for any new entries since last session.
git log --oneline -20  # see what shipped recently
git status  # confirm clean tree
uv run pytest -q  # confirm 871 baseline holds
```

Then ask: "where do you want to continue from?" — user will pick from
Pending priorities (status-snapshot.md §"Recommended next-session order").
