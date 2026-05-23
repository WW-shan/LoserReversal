# Goal: Complete Phases 1.5 + 3 + 2.5 + 4 + 5 of crypto-alpha-portfolio

You are an autonomous CCG orchestrator. Repo: `/Users/ww/Project/crypto-alpha-portfolio` on `main`.

## CRITICAL — Read these first (then proceed)

1. `docs/research/literature-review.md` — academic evidence for every Phase
2. `docs/research/loser-reversal-indicator/ROADMAP.md` — Phase priority + Pass/Kill criteria
3. `~/.claude/.ccg/engine/strategies/guided-develop.md` — three-way review protocol (Claude + Codex + superpowers subagent)
4. `~/.claude/.ccg/prompts/codex/{builder,reviewer}.md` — codex role files
5. `/Users/ww/.claude/plugins/cache/claude-plugins-official/superpowers/5.1.0/skills/requesting-code-review/code-reviewer.md` — subagent review template
6. `.ccg/tasks/archive/2026-05/phase-2-single-wallet-contrarian/prompts/` — full slice prompt examples (mirror this structure)

## Status snapshot

✅ Phase 0 — infrastructure (LGTM 97/100, archived)
🟡 Phase 1 v1 — INCONCLUSIVE (87.5% negative thesis confirmed by 3 academic studies; window/data sub-optimal; need Phase 1.5)
🟡 Phase 2 v1 — FILTER MISDESIGN (vlm-based filter selected 86%-profitable whale cohort by mistake; need Phase 2.5)

## Goal scope

Implement in this exact priority order (per ROADMAP revision):

1. **Phase 1.5 — Academic-tuned Unlock** (5 slices, highest academic confidence)
2. **Phase 3 — Funding arbitrage** (low-risk baseline, public CCXT data)
3. **Phase 2.5 — Academic-rebuilt Wallet contrarian** (5 slices)
4. **Phase 4 — Bot reverse** (independent thesis, was originally tied to Phase 2)
5. **Phase 5 — Portfolio + paper trading** (only if ≥1 phase reaches GREEN or YELLOW)

## NON-NEGOTIABLE workflow rules

### 1. CCG guided-develop strategy per Phase

- Create `.ccg/tasks/phase-N-<slug>/task.json` + `plan.md` + `prompts/`
- Update `task.json.currentPhase` + `nextAction` after each meaningful step (avoids hook LOOP DETECTED)
- Read `docs/research/literature-review.md` Part A/B for each Phase's academic spec

### 2. Three-way review loop per slice (NEW rule, codified post-Phase 2)

After each Codex builder run, dispatch **three reviewers in parallel** (all `run_in_background: true`):

**Reviewer 1 — Codex re-review**:
```bash
cat .ccg/tasks/phase-N/prompts/slice-M-reviewer.md | \
  /Users/ww/.claude/bin/codeagent-wrapper --lite --progress --backend codex - "$PWD" \
  > /tmp/codex_phaseN_sliceM_review.log 2>&1
```
With `ROLE_FILE: ~/.claude/.ccg/prompts/codex/reviewer.md` at top of prompt.

**Reviewer 2 — superpowers subagent**:
```
Agent({
  subagent_type: "general-purpose",
  description: "Slice N review",
  prompt: <fill code-reviewer.md template with BASE_SHA, HEAD_SHA, plan link>,
  run_in_background: true
})
```

**Reviewer 3 — Claude semantic** (you):
- `git show <sha>` walkthrough against `plan.md` / academic spec
- audit test quality, assertion specificity
- audit real numbers (Sharpe in plausible range? equity monotonic crash? n_trades vs threshold?)
- run `uv run pytest -q` and `uv run ruff check src tests scripts` as LAST step (not first)

**Wait for all three. Merge findings (dedupe). One builder fix run with the union.** Do NOT loop fix after each reviewer — that causes stale code reports.

### 3. "全部修好再进下一阶段" — fix ALL findings (Critical + Important + Minor)

Phase 0/1/2 precedent: Critical + Important MUST fix; Minor strongly recommended. Only Info-tagged "non-blocking documentation polish" may be deferred IF reviewer explicitly says so.

### 4. Strict commit granularity

- One commit per logical change (test → impl pairs in TDD)
- If Codex builder produces monolithic commit, fail review with Critical "process violation" and require split
- Mirror Phase 2 Slice 2 fix R1's pattern: ~7 commits per fix round

### 5. Builder MUST NOT archive

Builder spec must include: `Do NOT archive — Claude will archive after final LGTM + ROADMAP update`.

Phase 1 incident: builder self-archived prematurely (`8ea6edb`); had to revert. Never again.

### 6. Anti-monitor directive in every builder prompt

```
- Do NOT tail/ps/grep for other codex processes. Start writing code IMMEDIATELY.
- Other codex processes belong to the user; UNRELATED to this task.
- If you find yourself wanting to check process state — STOP and start coding instead.
```

Phase 2 Slice 2 initial failure: builder spent 1090 lines self-monitoring.

### 7. Pull / push strategy

- After final archive commit per Phase: `git push origin main`
- After each phase commit fully: `git log --oneline -10` to verify clean

### 8. Don't sleep / poll

When waiting on background tasks, return control to harness. You'll be notified.

## Per-Phase implementation guides

### Phase 1.5 (5 slices)

Read `ROADMAP.md` Phase 1.5 section + `literature-review.md` Part A for full spec.

- **Slice 1**: 数据补强 — HL candle 2023-01→now + DefiLlama fork + CryptoRank API + (optional) Tokenomist scrape via Playwright. Parse vesting type (cliff/linear) + recipient category. Target: 126 → 1000+ events.
- **Slice 2**: 5 signal versions (v1 T-7→T0 baseline, v2 T-30→T0, v3 T-2→T+3, v4 T-72h→T0, v5 T+3→T+14 reversal long).
- **Slice 3**: 3-dim grid sweep (Window × Size {1%,2%,5%,10%} × Category {team, team+investor, all}); cliff vs linear comparison.
- **Slice 4**: Walk-forward + multi-signal portfolio.
- **Slice 5**: Pass/Kill verdict + ROADMAP update + report.

Pass criteria: green if any signal walk-forward OOS Sharpe ≥ 1.0, n_trades ≥ 50.

### Phase 3 (3 slices)

- **Slice 1**: CCXT funding history fetcher (`src/infra/fetchers/cex_funding.py` per exchange). Top 20 perp symbols × 4 exchanges (HL/Binance/Bybit/Bitget) × 2-3 years.
- **Slice 2**: `src/signals/funding_arb_v1.py` — spread > z-score threshold → delta-neutral. Backtest with 8h funding settle, fees both sides, monthly rebalance. Practical model: min position $100, half-allocation per exchange.
- **Slice 3**: Walk-forward + Pass/Kill per ROADMAP §312 (绿灯 年化≥25%, MaxDD≤5%, 触发≥每周 1-2 次).

### Phase 2.5 (5 slices)

Read `ROADMAP.md` Phase 2.5 section + `literature-review.md` Part B.

- **Slice 1**: Academic wallet pool builder — account_value ∈ [$1k,$100k] + realized_loss_rate_90d ≥ 50% + leverage_avg ≥ 5x + n_trades ≥ 50 + size_cv ≥ 0.3. Extend to 500 wallets.
- **Slice 2**: Multi-feature reverse signal — `reverse_alpha_score = oversized × leverage × funding_extreme × time_bucket`.
- **Slice 3**: Bot exclusion filter — funding source graph + 时序同步 + size CV + round numbers. Save excluded set for Phase 4.
- **Slice 4**: Cluster signal v2 (confidence-weighted) + cascade reversal (OI drop X% in 1h → mean revert long).
- **Slice 5**: Walk-forward + verdict.

Pass criteria: green if walk-forward OOS IR ≥ 1.2, n_trades ≥ 100.

### Phase 4 (3 slices, independent bot reverse thesis)

- **Slice 1**: Bot wallet identification using Phase 2.5 exclusion set + on-chain funding source analysis.
- **Slice 2**: Bot reverse signal — test if reverse-following bots has alpha (independent thesis, NOT Phase 2 enhancement).
- **Slice 3**: Walk-forward + verdict.

### Phase 5 (2 slices)

ONLY run if Phase 1.5 OR Phase 3 OR Phase 2.5 OR Phase 4 reaches GREEN or YELLOW.

- **Slice 1**: Portfolio composer — risk-parity weights, max strategy weight 0.4.
- **Slice 2**: Paper signal generator — 5-min polling, write to `data/paper_trades.parquet` with fee/slip simulation. Run for 24-48h or until 100 simulated trades, then aggregate.

## Output requirements

For each Phase:
1. `reports/phaseN_<name>.md` — verdict + funnel + per-config stats
2. `docs/research/loser-reversal-indicator/ROADMAP.md` Phase section updated with verdict
3. `.ccg/tasks/archive/2026-MM/phase-N-<slug>/` — all slice prompts + plan.json + task.json (status=archived)
4. `git push origin main` after each Phase final archive

## Stop conditions

- Phase 1.5 + Phase 3 both RED → write summary `docs/research/all-strategies-failed.md` + STOP (don't run 2.5/4/5)
- Phase 1.5 RED but Phase 3 GREEN/YELLOW → continue to Phase 2.5 + Phase 4
- ≥1 phase reaches GREEN/YELLOW → Phase 5 runs
- Phase 5 paper PnL diverges >±20% from backtest → archive with caveat + STOP
- Any blocker (data source unreachable, infrastructure failure) → write `.ccg/tasks/phase-N/blocker.md` + STOP

## Hard rules

- KISS, no premature abstraction
- Python 3.11+, `from __future__ import annotations`, 100-char lines, UTC tz-aware, no emoji in code/commits
- TDD when adding behavior (test first commit, impl second)
- `uv run pytest -q` ≥ existing count after every commit
- `uv run ruff check src tests scripts` clean after every commit
- Force-add reports via `git add -f reports/*.md` (reports/ is gitignored — mirror Phase 2 commit `8949da8`)
- After final archive commit per phase: `git push origin main`
- If unsure between two designs, write briefly to `.ccg/tasks/phase-N/design-question.md` and continue with the simpler choice

Start with Phase 1.5 immediately. Read literature-review.md first to understand academic-tuned parameters.
