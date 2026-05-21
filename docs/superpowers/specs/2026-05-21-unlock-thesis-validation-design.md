# Spec: Unlock Thesis Validation

**Date**: 2026-05-21
**Status**: Approved (user confirmed inline during brainstorming)
**Owner**: WW
**Decides**: Whether to proceed with ROADMAP Phase 0 (build full infra) or skip to Phase 2 (single-wallet reverse)

## Purpose

验证 Keyrock 16000+ 事件研究里 "解锁产生负价格压力" 的实证结论，在我们关心的标的池里（过去 12 个月的 token unlock 事件）是否成立。这是 thesis-check，不是回测，不需要完整基础设施。

**输出**：1 份统计报告（markdown）+ 1 个探索性 notebook + 1 个清晰的 Pass/Fail 决策。

## Scope (YAGNI)

**In scope**：
- 拉过去 12 个月的 token unlock 事件（占流通量 > 2%）
- 拉对应 token + BTC 的 spot 价格历史
- 计算每个事件的 abnormal return（相对 BTC）
- 统计聚合 + 简单可视化
- 自动产出 markdown 报告

**Out of scope**：
- 任何回测引擎（vectorbt 等）
- Hyperliquid SDK 集成（用 CoinGecko spot 就够）
- 数据库 / Parquet 存储（JSON cache 即可）
- Walk-forward / 参数扫描
- Web dashboard
- Live signal generation

## Architecture

```
src/unlock_validation/
├── __init__.py
├── config.py        # 常量 (阈值/路径/类别白名单)
├── fetcher.py       # TokenUnlocks + CoinGecko clients (with cache + mocking)
├── analyzer.py      # abnormal return + 统计 + Pass/Fail 判定
└── report.py        # markdown 报告生成

tests/
├── conftest.py      # 共享 fixture
├── test_fetcher.py  # mock requests, 验证 parse + cache
├── test_analyzer.py # 合成数据 → 已知统计结果
└── test_report.py   # 验证 markdown 输出结构

notebooks/01_unlock_thesis.ipynb  # 探索 + 可视化
data/cache/                       # gitignored, fetcher 落地
reports/unlock_thesis_report.md   # 最终产出
```

## Data Flow

```
TokenUnlocks API ──┐
                   ├──► fetcher.load_events()  ──► event_df
CoinGecko API ─────┤    fetcher.load_prices() ──► price_df
                   │
                   ▼
            analyzer.compute_abnormal_returns(events, prices, btc_price)
                   │
                   ▼
            analyzer.aggregate_statistics(events_with_returns)
                   │
                   ▼
            analyzer.pass_fail_decision(stats)
                   │
                   ▼
            report.write_markdown(stats, decision, "reports/...")
```

## Key Design Decisions

### D1: 事件类别处理 — 双轨对比
跑两次聚合分析：
- **All categories**: team + investor + airdrop + ecosystem
- **Ex-ecosystem**: 排除 ecosystem unlock（Keyrock 显示这类几乎中性）

如果 ex-ecosystem 显著优于 all → 验证了"类别 matter"，给 Phase 0 设计提供细分依据。

### D2: 价格数据 — Spot 优先 + HL 子集标记
- 主数据用 CoinGecko spot price（覆盖广、免费）
- 对每个事件，单独标记其在 Hyperliquid 是否有 perp 市场
- 报告输出 HL 子集子集的同一组统计，作为"未来可交易事件"的预览

### D3: 收益度量 — 相对 BTC 的超额收益
```python
abnormal_return = log_return(token, window) - log_return(BTC, window)
```
- 标准事件研究方法
- 不引入 beta 估算（30-60 样本时 beta 噪声 > 信号）

### D4: 三个时间窗
| 窗口 | 含义 | 主要信号 |
|------|------|---------|
| `[T-7, T0]` | 解锁前 7 天 | **核心信号**（提前抛售/做空机会）|
| `[T0, T0+1]` | 解锁当日 | 波动率（实际抛压释放）|
| `[T0, T+3]` | 解锁后 3 天 | 是否继续跑输（反弹时机）|

### D5: Pass/Fail Decision Matrix

| # | Metric | Pass | Fail |
|---|--------|------|------|
| 1 | `% events abnormal_pre < 0` | ≥ 65% | < 55% |
| 2 | `% events abnormal_post < 0` | ≥ 55% | < 45% |
| 3 | `mean(abnormal_pre)` | ≤ -3% | ≥ -1% |
| 4 | `t-test(abnormal_pre vs 0)` p-value | < 0.05 | > 0.10 |
| 5 | Team-subset performance | ≥ overall | < overall (suggests data issues) |

**Verdict**:
- ≥ 4/5 pass → **STRONG validation** → 进 Phase 0
- 3/5 pass → **WEAK validation** → 进 Phase 0 但降低对解锁策略的预期权重
- ≤ 2/5 pass → **REJECT** → 跳到 ROADMAP Phase 2（单钱包反向）

## Testing Strategy (TDD)

**测试先写，实现后跟**。每个模块的 happy-path + 1-2 个 edge case：

### `test_fetcher.py`
- `test_parse_tokenunlocks_event_with_all_fields` — fixture JSON → 验证字段映射
- `test_parse_event_handles_missing_category` — 缺字段时 default 而非 crash
- `test_fetch_prices_caches_to_disk` — 第二次调用不应该发 HTTP
- `test_fetch_prices_handles_429` — 触发 rate limit 时退避重试

### `test_analyzer.py`
- `test_compute_abnormal_return_known_values` — 输入 token=+5%, btc=+3%, 输出 +2%
- `test_aggregate_handles_empty_events` — 0 个事件不应 crash
- `test_pass_fail_5_of_5_strong` — 合成数据让全部 metric pass → verdict="STRONG"
- `test_pass_fail_3_of_5_weak` — 验证 WEAK 边界
- `test_pass_fail_2_of_5_reject` — 验证 REJECT 边界
- `test_ecosystem_filter_excludes_correctly` — 验证双轨对比的过滤逻辑

### `test_report.py`
- `test_markdown_contains_required_sections` — 5 个 Pass/Fail 指标 + 总评 + 事件清单

## Done Definition

1. ✅ `pytest -v` 全绿（最少 12 个测试）
2. ✅ `python -m unlock_validation.analyzer` 跑完无错产出 `reports/unlock_thesis_report.md`
3. ✅ 报告含：事件清单（含类别 + HL 子集标记）+ 5 个指标的实际数值 + 总评（STRONG/WEAK/REJECT）
4. ✅ Notebook 跑得通，含价格曲线 + 散点图等可视化

## Tech Stack

```toml
[project]
requires-python = ">=3.11"
dependencies = [
    "requests >= 2.31",
    "pandas >= 2.1",
    "numpy >= 1.26",
    "scipy >= 1.11",        # t-test
    "matplotlib >= 3.8",    # 可视化
    "python-dateutil",
    "tenacity >= 8.2",      # API 重试
]
[tool.uv.dev-dependencies]
dependencies = [
    "pytest >= 7.4",
    "pytest-mock",
    "pytest-cov",
    "ruff",
    "ipython",
    "jupyter",
]
```

## Pass/Fail Threshold Rationale

Keyrock baseline 是 ~90% 负压力（16000+ 样本）。我们设：
- 65% (metric 1) 是给小样本量 + 时间区间偏差留余量
- p < 0.05 (metric 4) 是社会科学标准统计显著性
- Team-subset ≥ overall (metric 5) 是 sanity check（如果 team subset 反而弱，说明数据筛选有问题）

要求 4/5 强 / 3/5 弱 / ≤2 拒绝，保留中间区域的不确定性。

## Risks & Mitigations

| Risk | Mitigation |
|------|-----------|
| TokenUnlocks API 限流或字段变化 | tenacity 重试 + JSON cache + 文档化 raw 数据 |
| CoinGecko free tier rate limit | 拉一次缓存到 `data/cache/`，复用 |
| 小样本量统计不稳 | 跑 12 个月数据，目标 40-60 事件 |
| 自我确认偏差（我们想要 pass） | 严格预先承诺 Pass/Fail 阈值，不事后调整 |
| 数据 lookahead bias | 严格按事件公告日（announce date）做 cutoff，不按 unlock date |
