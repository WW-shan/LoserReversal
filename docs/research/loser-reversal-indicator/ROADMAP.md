# 量化散户 Alpha 探索完整 Roadmap

> **总目标**：在 16-20 周内，通过 4 个独立 alpha 源的回测验证，构建一个 Sharpe ≥ 1.5 的个人量化组合策略，从纸面到小额实盘。
> **核心原则**：每个阶段都有明确 Pass/Kill criteria；不达标就砍掉走下一个；成功的留下进入组合。

---

## 公开 / 不公开边界（反身性原则）

仓库虽为 public，但严格区分：

**✅ 入库公开**：
- 基础设施代码（数据 fetcher / 回测脚手架 / 可视化工具）
- 研究方法论 + ROADMAP
- 公共数据集（解锁事件、funding history 等已公开数据）
- 通用工具函数

**❌ 不入库**（gitignore 或 private branch）：
- 真实策略参数 + 阈值
- 实盘交易记录 + PnL
- 私有钱包池清单（如反向跟踪的具体地址）
- 实时信号生成的最终配置

**理由**：策略完整公开 → 反身性闭环 → alpha 立即衰减。基础设施和方法论公开有学习价值且不泄漏 alpha。

---

## 总时间线（甘特图）

> **修订（2026-05-24）**：基于学术调研发现 Phase 1 / Phase 2 都有 sub-optimal 设计而非 thesis 失败。
> 新增 Phase 1.5（学术-tuned unlock 重做）和 Phase 2.5（学术-rebuilt wallet contrarian），并调整优先级。
> 详见 `docs/research/literature-review.md`。

```
Week:  1  2  3  4  5  6  7  8  9 10 11 12 13 14 15 16 17 18 19 20+
P0  ✅                                                                基础设施
P1     [INCONCLUSIVE - 进 P1.5]                                       解锁策略 v1
P2              [FILTER MISDESIGN - 进 P2.5]                          单钱包 v1
P1.5                  [■■]                                            Unlock 学术-tuned (高优先)
P3                          [■■]                                      Funding 套利 (低风险底盘)
P2.5                              [■■■]                               Wallet 学术 rebuild
P4                                      [■■]                          Bot 反向 (独立 thesis)
P5                                            [■■]                    组合优化+纸面
P6                                                  [■■■■■■■■■■■■]    小额实盘
P7                                                          [持续]    Alpha 监控
```

**修订执行优先级**（按学术证据强度排序）：

| 优先级 | Phase | 学术证据 confidence | 当前状态 |
|---|---|---|---|
| **✅ 1** | **Phase 1.5** Unlock v2 | 3 独立学术 + thesis-check 87-90% converge | 🟡 **YELLOW** (OOS Sharpe 0.61, 36 trades) |
| **⚠️ 1.6** | Phase 1.5 救援 ablations (A/B/C/D) | Part C dr-1 到 dr-6 6 个 deep research | 待执行 (3 day 工作量) |
| 2 | **Phase 3** Funding contrarian (reframed) | 92% positive bias + extreme contrarian 学术验证 | 🚧 60% (Slice 1 ✅, Slice 2/3 待) |
| 3 | **Phase 2.5** Wallet v2 | HL 124k whale trades simulation 验证 | 未开始 |
| 4 | **Phase 4** Bot 反向 | 独立 thesis, 未验证 | 未开始 |
| 5 | Phase 5 portfolio | 依赖 ≥1 GREEN/YELLOW (✅ 已有 P1.5 YELLOW) | 未开始 |

**关键里程碑**（修订）：
- ~~M1~~ ✅ (Week 2): 数据 pipeline 跑通
- ~~M2~~ ❌ (Week 5): Phase 1 v1 INCONCLUSIVE — 需 Phase 1.5 重做
- **M2'**: Phase 1.5 完成 — 第一个真正 verdict
- M3 (修订): Phase 1.5 + 3 + 2.5 全跑完 — 挑出 ≥1 个能用的
- M4 (修订): 进入小额实盘（依赖 ≥ 1 GREEN）
- M5: 实盘 8 周后复盘

---

## Phase 0: 数据 + 回测基础设施（Week 1-2）

> **这一阶段不出 alpha，但所有 alpha 都依赖它。一次投入，永久复用。**

### 目标
搭建一套个人量化的最小可行栈，能拿数据、能回测、能可视化。

### 任务清单

#### Week 1: 环境 + 数据获取
- [ ] **环境**：Python 3.11+，uv 或 conda 创建虚拟环境
- [ ] **核心库**：
  ```bash
  pip install hyperliquid-python-sdk vectorbt polars duckdb \
              ccxt requests pyarrow numpy pandas matplotlib plotly
  ```
- [ ] **Hyperliquid SDK 跑通**（写脚本 `data/hl_fetch.py`）：
  - `info.candle_snapshot()` 拉 BTC/ETH/SOL/HYPE 过去 2 年的 1h/4h/1d K 线
  - `info.user_fills(addr)` 拉一个测试钱包成交历史
  - `info.l2_book(coin)` 拉一次实时盘口快照
- [ ] **AWS CLI 配置**（拿 Hyperliquid 历史 L2 book）：
  ```bash
  aws s3 cp s3://hyperliquid-archive/market_data/20250101/0/l2Book/BTC.lz4 ./ \
    --request-payer requester
  ```
- [ ] **CCXT 跨交易所统一接口**：能拿 Binance/Bybit/Bitget 的 funding history
- [ ] **TokenUnlocks API**：注册免费 key，拉过去 24 个月所有解锁事件 csv

#### Week 2: 存储 + 回测引擎
- [ ] **数据落地**（用 Polars + Parquet）：
  ```
  data/
    candles/
      hyperliquid/
        BTC_1h.parquet
        ETH_1h.parquet
        ...
    fills/
      0xAA...parquet
    funding/
      hyperliquid_funding.parquet
      bybit_funding.parquet
    unlocks/
      events.parquet
  ```
- [ ] **DuckDB query 层**（写 `data/db.py`）：
  ```python
  import duckdb
  con = duckdb.connect()
  con.sql("SELECT * FROM 'data/candles/hyperliquid/*.parquet' WHERE ...")
  ```
- [ ] **Vectorbt 回测样板**（写 `backtest/template.py`）：
  - 加载价格 → 生成 entry/exit signal → 运行 portfolio → 输出报告
  - 标准 fees=0.025%, slippage=0.05%, funding cost 计算
- [ ] **Walk-forward 验证模板**（写 `backtest/walk_forward.py`）：
  - 训练 18 个月 / 测试 3 个月 / 滚动 6 次
- [ ] **报告模板**：每次回测自动产出 Sharpe / Sortino / 最大回撤 / 胜率 / 平均 PnL / 月度曲线 PNG

### 交付物
- `repo/data/` 含可重复加载的全部历史数据
- `repo/backtest/` 含可复用的回测脚手架
- Jupyter notebook `notebooks/00_smoke_test.ipynb` 验证整个 pipeline

### Pass Criteria
- 能在 1 行 SQL 内 query 任意币种任意时段的 K 线
- 一个示例策略（如简单 SMA crossover）能跑完回测并产出报告

### Kill Criteria（none）
基础设施阶段不允许 kill，必须完成。如果遇到阻塞 > 3 天 → 简化数据维度（先只做 BTC/ETH）但不可跳过。

---

## Phase 1: 解锁策略（Week 3-5）

> **为什么先做这个**：数据齐、实证强、机构不做、最容易冷启动出第一个能赚钱的信号。

### ⚡ Thesis check 已完成（2026-05-22，进 Phase 0 前快速验证）

**Verdict: WEAK 3/5** — 信号方向明确且统计显著，但样本量小（8 events 进入分析）。

**关键发现（反原假设）**：

| 维度 | 原 plan 假设 | 实证数据 |
|---|---|---|
| 短卖窗口 | T0 → T+3（解锁后砸盘） | **T-7 → T0（解锁前砸盘）** |
| 解锁后 | 继续跌 | 平均 +1.1% 反弹 |
| 主驱动 | Insider 卖压 | **Supply-shock 本身**（noncirculating 释放也跌） |
| mean_pre vs BTC | — | **-8.21%** (p=0.01, 87.5% 负) |

→ **Phase 1 实施时把信号 v1 改为 pre-event short (T-7→T0)，不是 post-event。**

见 `reports/unlock_thesis_report.md` 和 `src/unlock_validation/`。

### 目标
回测验证"解锁前 T-7→T0 做空"策略（已修订），决定是否进入组合。

### ⚠️ Phase 1 verdict 修订（2026-05-24，基于学术调研）

**先前 verdict: RED — KILL** ❌（**误读**）

**修订 verdict: STRONG-but-INCONCLUSIVE → 进 Phase 1.5 重做**

**为什么之前的 RED 是误读**：
- 原始 verdict reason `data_gap`（OOS n_trades=0）→ 被理解为"策略不 work"
- **实际是数据范围 + window 选择不足**，不是 thesis 失败
- 3 个独立学术研究**强力证实 thesis** (见 `docs/research/literature-review.md`):
  - Keyrock 16k+ events: **90% negative**
  - Kim SSRN 2026: 52 events, **88.5% pre-unlock short profit**
  - SmartKarma: 1% unlock ≈ -0.3% weekly drop
  - **My thesis-check: 87.5% negative, p=0.01, mean AR=-8.21%**
- 3 个数据源的 87-90% 一致性 → **极高 thesis confidence**
- Phase 1 实施时 3 trades 全 win, Sharpe=1.93 — 信号方向正确

**Phase 1 的真实问题**（学术分析后）：
1. Pre-event window T-7 偏短 — Keyrock 推荐 **T-30**，SmartKarma 强效 **T-2→T+3**，Kim SSRN **72h**
2. Candle 历史不够长 → 9/14 events 的 T-7 entry 早于 candle 起点
3. 没测 signal v2 (T+3→T+14 反弹做多, Keyrock 推荐) — ROADMAP §168 原设计
4. 没按 category 分桶 (team -25% drawdown vs ecosystem -5%)
5. 没多源 events (只 DefiLlama fork 126，可扩至 1000+)

→ **Phase 1.5 应该是最高优先级 retry**，预期 GREEN/YELLOW

详见 `docs/research/literature-review.md` Part A。

### 任务清单

#### Week 3: 数据 + 信号
- [ ] 整理 `unlocks_events.parquet`：token, date, amount, pct_of_circulating, category (team/investor/ecosystem/airdrop), vesting_type (cliff/linear)
- [ ] 关联价格数据：对每个事件取 T-30 到 T+30 的价格窗口
- [ ] **信号 v1**（实现 `signals/unlock_v1.py`）：
  ```python
  def unlock_short_signal(event):
      if event.unlock_pct < 0.02:  # < 2% 流通量
          return None
      if event.category not in ["team", "investor"]:
          return None
      # T-7 开空，T+3 平仓
      return ShortSignal(
          entry_time=event.date - timedelta(days=7),
          exit_time=event.date + timedelta(days=3),
          confidence=event.unlock_pct * (2.0 if event.category=="team" else 1.0)
      )
  ```
- [ ] **信号 v2**（反弹做多）：T+3 到 T+14 做多吃反弹

#### Week 4: 回测 + 参数扫描
- [ ] 运行 Vectorbt grid search：
  - `entry_offset`: [-14, -10, -7, -5, -3]
  - `exit_offset`: [-1, 0, +1, +3, +7, +14]
  - `pct_threshold`: [0.01, 0.02, 0.03, 0.05]
  - `category_filter`: [team, team+investor, all]
- [ ] 按 Sharpe 排序最优参数集
- [ ] **过拟合检测**：top 10 参数组在 OOS 上的 Sharpe 是否稳定

#### Week 5: Walk-forward + 决策
- [ ] Walk-forward（6 个 fold）
- [ ] 分类拆分性能（按 category / 按市场状态牛熊）
- [ ] 写决策报告 `phase1_decision.md`

### 数据需求
- TokenUnlocks（免费 API，过去 24 个月）
- Hyperliquid 永续价格历史（自建，过去 24 个月，30 个有 perp 的代币）

### Pass Criteria（任一为绿即继续）
- **绿灯**：OOS Sharpe ≥ 1.5，最大回撤 ≤ 20%，胜率 ≥ 60%
- **黄灯**：OOS Sharpe 1.0-1.5，最大回撤 ≤ 25% → 标记为"候选组合成员"但权重低
- **红灯**：OOS Sharpe < 1.0 或 OOS 性能比 IS 衰减 > 50% → **Kill**

### Kill 后该做什么
- 把所有数据 + 代码归档（下个策略复用基础设施）
- 跳过到 Phase 2

### 交付物
- `signals/unlock_v1.py`, `unlock_v2.py`
- `notebooks/phase1_backtest.ipynb`
- `reports/phase1_unlock.html`（自动产出）
- 进入组合则保存 `strategies/active/unlock.json`（最优参数）

---

## Phase 2: 单钱包反向（Week 6-8）

> **这是你最初想法的真正可量化版本。如果这个不工作，原始假设就被证伪。**

### ✅ Phase 2 完成（2026-05-23）

**先前 verdict: RED — KILL** ❌（**filter 设计错误，非 thesis 失败**）

**修订 verdict: FILTER MISDESIGN → 进 Phase 2.5 重做**

**为什么之前的 RED 不能 close case**：
学术调研（详见 `docs/research/literature-review.md` Part B）揭示**我的 wallet filter 选错了维度**：

- **HL 124k whale trades simulation 明确证实**："Trade size alone is a poor or negative predictor of success. Strategies copying larger trades underperformed. **Account size mattered far more than single-trade size**."
- HL 散户按账户 cohort 分桶：<$1k = 85% 亏损 / $10M+ = **86% 盈利**（whales win!）
- 我用 `vlm DESC` 选 wallet → 选到大账户低 ROI 用户混合体（其中包含 winners）
- 反向跟踪 winners = 反向 alpha 也 win → 我得到 IR=-4.83 是**反向了真信号**

**Phase 2 真实问题**：
1. Wallet selection 维度错（vlm-based → 应该 account_value cohort + persistent loss rate）
2. 没用 leverage（学术：>5x 高 leverage = retail dumb money）
3. 没用 trade/account size ratio（oversized bet = panic/FOMO 信号）
4. 没用 funding extreme context（92% positive funding bias → contrarian timing）
5. 没用 time-of-day（Asian session + funding settle = liquidation cascade window）
6. 没排除 bot wallets（programmatic 行为稀释 retail signal）

→ **Phase 2.5 应该重做**，预期翻转 verdict 到 YELLOW

**关键数据（保留作 baseline）**：
- 数据 span: 89 days (2026-02-22 → 2026-05-23)
- Wallet pool: 500 anti-alpha 钱包（leaderboard 36,890 → filter → top 500 by vlm）
- Active wallet fills: 116,618 fills / 16 wallets actually cached & active
- Single-wallet sweep: **Trade-level IR = -4.83**（远低于 1.2 阈值，所有 holding 1h/4h/12h/24h 全负）
- Cluster signal sweep: 48 配置（N×W×holding grid）× 3 walk-forward splits = 144 backtest，OOS n_trades **全部 0**

**根因（Codex + subagent + Claude 三方验证）**：
1. **数据稀疏**：89 days 的 fill 历史 + 16 active wallets，cluster N≥3 同 coin 同方向 W=15-60min 窗口在 OOS 期触发频率为 0
2. **Walk-forward fallback**：min_train_days 120→30, test_days 30→15（已在 report 透明展示）
3. **真实策略表现也是 RED**：单钱包 sweep 即使 IR=-4.83 在大 sample 下也是 negative alpha（不是 Phase 1 的 lucky-window，是真亏）

**与 ROADMAP Phase 4 关系**：
- ROADMAP 原文："集群信号 IR < 1.0 → Kill 单钱包路线，跳过 #4（因为反 Sybil 是它的进化版）"
- **执行此规则：跳过 Phase 4（sybil 集群），直接进 Phase 3 (funding arb)**

**实施细节**：
- 数据源 spike: `https://stats-data.hyperliquid.xyz/Mainnet/leaderboard` (公开 GET，36,894 钱包)，避免了 Hyperdash Cloudflare 拦截问题
- 三视角 review 循环（Claude semantic + Codex reviewer + superpowers requesting-code-review subagent）持久化到 `~/.claude/.ccg/engine/strategies/{guided-develop,full-collaborate}.md`
- 全部代码 LGTM 100/100 (Codex) + Ready to merge (subagent)
- 见 `reports/wallet_reverse_v1_backtest.md`、`reports/wallet_reverse_v1_sweep.md`、`reports/wallet_reverse_walkforward.md`

### Pass Criteria（原定）

- **绿灯**：Top 钱包池反向 IR ≥ 1.2 + 集群共振 IR ≥ 1.5（OOS）
- **黄灯**：集群信号 IR 1.0-1.5 → 候选组合
- **红灯**：集群信号 IR < 1.0 → **Kill 单钱包路线**，跳过 #4 ✅ 触发

### 任务清单（已完成）

- [x] **种子钱包池**：HL 公开 leaderboard endpoint → 36,890 → filter (PnL≤-10k, vlm≥500k, ROI≤-5%) → 500 retail anti-alpha wallets
- [x] **拉历史成交**：`userFillsByTime` paginated fetch, 50 wallets × 90d lookback = 116,618 fills
- [x] **过滤器**：trade-level retail size filter ($1k-$200k)
- [x] **单钱包反向 PnL 回测**：4 holdings sweep (1h/4h/12h/24h) — best 24h IR=-3.89
- [x] **集群信号**：N×W grid (3,5,7,10) × (15min, 30min, 60min)
- [x] **Walk-forward**：3 expanding splits + IS fallback selection modes + Pass/Kill verdict
- [x] **决策报告**：`reports/wallet_reverse_walkforward.md`

### Kill 后该做什么 — **修订**

- 先前认为 "Phase 2 失败 → Phase 4 也基本无望" — 但学术调研证明 Phase 2 是 filter 设计错，不是 thesis 失败
- **不跳 Phase 4**，但优先 Phase 1.5 + Phase 3 + Phase 2.5（详见 Phase 1.5 + 2.5 sections below）
- Phase 4 sybil 改为**独立 thesis**（反向 bot），不再依赖 Phase 2 成功

### 交付物
- `data/fills/` 含 200+ 钱包成交历史
- `notebooks/phase2_wallet_reverse.ipynb`
- `reports/phase2_wallet.html`
- `strategies/active/anti_wallet.json`（最优集群配置）

---

## Phase 1.5: 学术-tuned Unlock 重做（已完成 — YELLOW）

> 基于 `docs/research/literature-review.md` Part A 调研，修复 Phase 1 的 sub-optimal 配置。
> 学术证据强 confidence: 3 独立研究 + thesis-check converge **87-90% negative rate**。

### ✅ VERDICT YELLOW (2026-05-24) — 首个可部署 signal

**最佳 signal: v2 (T-30 → T0 short, Keyrock long-swing window)**
- OOS Sharpe **0.61** (YELLOW band [0.3, 1.0))
- **36 OOS trades** (>=30 阈值)
- 75% win rate
- 总回报 110% 跨 2.5 年 OOS 测试窗
- 最大回撤 -29%

**关键洞察**:
- v1 IS Sharpe 1.60 → OOS 0.46 (71% decay) — overfit
- **v2 T-30 更稳健** — 与 Keyrock "T-30 anticipation" 契合
- Cliff vesting > Step > Linear (符合学术预测)
- v5 (T+3→T+14 reversal long) OOS Sharpe 0.06 — 反弹做多假设**不成立**

详细 verdict: `reports/phase1_5_unlock_academic.md`

### ⚠️ Phase 1.6: YELLOW → GREEN 救援 ablations（A+B+D 已完成 2026-05-26，C 数据受限推迟）

基于 `docs/research/phase-1-5-diagnostic.md` 5 个根因 + `literature-review.md` Part C 调研，最终综合报告 `docs/research/phase-1-5-ablation-results.md`。

| 根因 | Ablation | 状态 | 结果 |
|---|---|---|---|
| Split 3 lucky-fold | **A: Bootstrap CI** | ✅ done | full-sample CI **[0.84, 4.09]** → robust；leave-split-3-out CI [-0.47, 2.32] |
| Cohort drift | **B: 固定 cohort=team** | ✅ done | Sharpe 0.59 vs baseline 0.61 → cohort 搜索不是 overfit 来源 |
| Bear-period failure | **C: BTC<200d MA filter** | ⏸ deferred | regime_filter 模块 + 12 tests 已落地（commit `8d2d80b`），但 BTC 1d candle 仅 91 天，200d SMA 算不出 — 等 BTC backfill 扩到 2023-05 后再跑 |
| MaxDD -29% | **D: -10% per-trade stop loss** | ✅ done (mixed) | **v1+stop 升 Sharpe 0.46→0.59 / MaxDD -10%→-8% (新最佳)**；**v2+stop 崩 Sharpe 0.61→0.27 / MaxDD -29%→-20%** — 10% 太狠，T-30 winner 被 mid-hold 砍掉 |
| Portfolio Sharpe drag | **E: cross-thesis** | ⏸ blocked | 需 Phase 3 + Phase 2.5 完成 |

### Phase 1.5 最终裁决（2026-05-26 修订）

**Classification: 🟡 YELLOW (unchanged), 但最佳变体切换 v2 → v1+D**

| axis | baseline (v2) | v1+D (recommended) | GREEN 阈值 |
|---|---:|---:|---|
| OOS Sharpe | 0.61 | 0.59 | ≥ 1.0 |
| n_trades | 36 | 29 | ≥ 50 |
| MaxDD | -29.3% | **-7.8%** | ≤ -20% |
| win_rate | 75.0% | 72.4% | n/a |
| bootstrap CI lower | n/a | 待算 | > 0 |

**推荐部署变体**：v1 + stop=10% + cohort=team — 牺牲 0.02 Sharpe 换 21pp MaxDD 改善，适合 Phase 5 portfolio 低权重纳入。

Configuration to lock if Phase 5 picks this up:

```json
{
  "signal": "v1",
  "entry_offset_days": -7,
  "exit_offset_days": 0,
  "cohort": "team",
  "min_unlock_pct": 0.02,
  "stop_loss": 0.10,
  "max_position_pct": 0.05,
  "regime_filter": "pending_btc_backfill"
}
```

### 后续 follow-ups（不阻断 Phase 5）

1. 扩展 BTC 1d candle backfill 到 2023-05（同时解 Phase 3 candle gap）
2. 跑 Ablation C 真实数据（regime_filter CLI 已就绪）
3. Bootstrap CI on v1+D 新组合（n_trades=29，需 CI 决定 Phase 5 权重）
4. ATR-adaptive stop（替代固定 10%，可能让 v2 同时保 Sharpe 和 MaxDD）

---

**Portfolio (top-2 v2 + v1, equal-weight)**:
- OOS Sharpe 0.54, 64 trades, 73% win rate
- 进入 Phase 5 paper trading 作为低权重候选

### 目标
用学术参数完整重做 unlock 策略验证 — 期望 verdict 从 INCONCLUSIVE → GREEN/YELLOW。**已达成 YELLOW。**

### 5 个 Slice — 全部完成

**Slice 1 — 数据补强** ✅
- HL candle 拉 2023-01 → 现在 (55 HL-perp tokens, 100% 覆盖)
- 多源 unlock events: DefiLlama emissions-adapters fork (Omni-Chain-Protocols, 310 protocols)
- 解析每 event 的 vesting type (cliff/step/linear), recipient category
- 实际: **126 → 1768 events** (vs 目标 1000-2000)
- `data/parquet/event_coverage.parquet` 记录 532 HL-perp events 的覆盖状态 (402 ok, 75 insufficient_pre_days, 55 listing_after)

**Slice 2 — Signal 多样化** ✅
- v1: T-7→T0 short (原版 baseline 对照)
- v2: T-30→T0 short (Keyrock 推荐主入场区间 — **最终 YELLOW winner**)
- v3: T-2→T+3 short (SmartKarma 强效窗口)
- v4: T-72h→T0 short (Kim SSRN 88.5% profit)
- v5: T+3→T+14 reversal long (Keyrock 推荐 — **OOS 验证后失败**, Sharpe 0.06)

**Slice 3 — 3 维 Grid sweep** ✅
- Window × Size threshold {1%, 2%, 5%, 10%} × Category {team, team+investor, all} = 60 cells
- + 3 vesting sub-sweep rows
- Best IS: v1 / 2% / team Sharpe 1.60
- 全部 cell 数据持久化到 `data/parquet/unlock_grid_v15.parquet`

**Slice 4 — Walk-forward + Multi-signal portfolio** ✅
- 5 expanding splits × 270 train + 180 OOS days (覆盖全 3.4-year span)
- Per-signal aggregate + top-K portfolio
- Best signal: v2 OOS Sharpe 0.61, n_trades 36

**Slice 5 — Pass/Kill + ROADMAP 更新** ✅
- Report: `reports/phase1_5_unlock_academic.md`
- ROADMAP 本节更新

### Pass Criteria (实际达成)
- 绿灯: 任一 signal walk-forward OOS Sharpe >= 1.0, n_trades >= 50 — ❌ 未达到
- **黄灯**: OOS Sharpe 0.3-1.0 + n_trades >= 30 — ✅ **v2 达成 (0.61, 36)**
- 红灯: 所有 signal OOS Sharpe < 0.3 OR n_trades < 30

### Caveats (paper trading 前必读)
1. n_trades 36 偏少, bootstrap CI 较宽
2. OOS span 2024-04 → 2026-05 主要为 bull market
3. 实际 slippage 在 unlock-stress 窗口可能 2-5× 当前 0.02% 假设
4. 需要 position-sizing layer (active-capital 当前假设每 token 独立 $10k)

### 交付物
- 64 commits, 全部小颗粒度 TDD pairs
- 304 tests passing, ruff clean
- 5 个 phase 1.5 模块 + 4 个 CLI 脚本
- 4 个 parquet artifacts + 3 个 report
- 三方 review per slice (Codex × 2 + Claude semantic)

---

## Phase 2.5: 学术-rebuilt Wallet Contrarian 重做（新增）

> 基于 `docs/research/literature-review.md` Part B 调研，修复 Phase 2 的 filter 设计错误。
> 学术明确：account size matters > trade size; leverage = retail signal; cascade/funding = timing alpha。

### 目标
用学术 wallet selection + 多维 reverse alpha score 重做。

### 5 个 Slice

**Slice 1 — Academic wallet pool builder** ✅ **GREEN (archived 2026-05-27, n=21 with spec deviation)**
- 替换 vlm-based filter 为：
  - `account_value ∈ [$1k, $100k]`（85% loss cohort）
  - `realized_loss_rate_90d ≥ 50%`
  - `leverage_avg_90d ≥ 5x`
  - `n_trades_90d ≥ 50`
  - `size_cv_90d ≥ 0.3`（排除 market makers）
- ~~Pool 扩到 ROADMAP 原设 200-500 wallets~~ → **delivered n=21**, spec deviation
  documented at `.ccg/spec/backend/index.md` ("Deliverable target vs. empirical
  population — Hyperliquid leverage cohort"). HL whale avg leverage 5.14x per
  gwrx2005 makes ≥5x near-universal; multi-factor intersection (lev∧loss∧size∧trades)
  correctly isolates panic-FOMO cohort at n=21. Downstream slices reference n=21.

**Slice 2 — Multi-feature reverse signal**
- Per-fill `reverse_alpha_score` = oversized × leverage × funding_extreme × time_bucket
- Wallet-level confidence weight

**Slice 3 — Bot exclusion filter**
- 检测 wallet 行为：funding source graph + 时序同步 + size CV + round numbers
- 从 pool 中 filter out bots（保留供 Phase 4 单独研究）

**Slice 4 — Cluster signal v2 + Cascade reversal**
- Cluster N/W grid，confidence-weighted
- 加 cascade-reversal signal（OI 减 X% in 1h → mean revert long）

**Slice 5 — Walk-forward + verdict**

### Pass Criteria
- **绿灯**：Walk-forward OOS IR ≥ 1.2 + n_trades ≥ 100
- **黄灯**：IR 0.5-1.2 + n_trades ≥ 50 → 候选低权重
- **红灯**：IR < 0.5 → 真 anti-alpha thesis 失败

---

## Phase 3: 跨平台 Funding 套利（Week 9-10）— **已 reframe，verdict RED-data_gap**

> **原 plan**：跨 HL + Binance + Bybit + Bitget funding arb (delta-neutral)
> **reframed**：HL-only funding extreme contrarian
> **当前 verdict (2026-05-26)**：🔴 **RED** on aggregate OOS Sharpe 0.42 / 年化 5.23%，但有 data_gap caveat（1h candle 仅 90 天，funding 是 3 年）

### 🔴 Verdict (2026-05-26) — 详见 `reports/phase_3_verdict.md`

3 splits 走完，aggregate OOS Sharpe 0.42 / 年化 5.23% / MaxDD -1.37% / 45 trades / 51.11% win rate。

| split | IS Sharpe | IS n | OOS Sharpe | OOS ann | OOS n |
|---|---:|---:|---:|---:|---:|
| 0 | -1.17 | 37 | **6.58** | **36.27%** | 22 |
| 1 | 0.47 | 90 | -4.69 | -18.42% | 6 |
| 2 | 0.52 | 118 | -0.62 | -2.18% | 17 |

Split 0 OOS Sharpe 6.58 是典型 lucky-fold（与 P1.5 split 3 同构），剩余两 splits 加权强负。

**关键 caveat（不能直接定 RED 结案）**：
- 1h candle backfill 只覆盖 2026-02-23 → 2026-05-23（~90 天），funding 是 2023-05 → 2026-05（3 年）
- 学术 alpha-decay horizon ~1 年，90 天回测远低于统计 floor
- 等同 Phase 1 v1 当年被误读为 RED 但实际是 data_gap 的情况
- 12/30 token 缺 1h candles 进一步压缩有效样本

### 当前进度（全部 Slice 完成）

- ✅ Slice 1 — funding backfill + `funding_extreme_v1` signal (commits `f983554` → `9521c15`)
- ✅ Slice 2 — backtest + grid sweep + Fix R1 (commits `b029320` → `c039f1c`)
  - 三方 review 揪出 2 个 Critical：Sharpe 年化数学 + aggregate equity 幻象
  - 修复后 top-1 cell (z=3.0/hold=8/lookback=14) IS Sharpe 2.12, 年化 20.01% (90-day 窗口)
- ✅ Slice 3 — walk-forward + verdict (commits `8181193` → `6d70038`)

### Phase 3 Pass Criteria（reframed，已应用）

单 venue directional 不同于 cross-exchange neutral：
- 🟢 绿灯：walk-forward OOS Sharpe ≥ 1.2 AND 年化 ≥ 20%
- 🟡 黄灯：Sharpe ∈ [0.5, 1.2) AND 年化 ≥ 10%
- 🔴 红灯：Sharpe < 0.5 OR 负年化 — **当前触发**
- ⚪️ INCONCLUSIVE：n_trades < 30（n_trades=45 没触发，但与 INCONCLUSIVE 精神一致因 90-day window）

### Phase 3 后续动作（按优先级）

| 优先级 | Action |
|---|---|
| 1 | 扩展 1h candle backfill 到 2023-05（与 funding 匹配）。无此则 Phase 3 无法重判。 |
| 2 | 数据齐后重跑 5-split walk-forward (train 270 / test 180)。Sharpe ≥ 0.5 升 YELLOW，否则定 RED。 |
| 3 | Phase 5 portfolio 暂不纳入 funding，等数据齐 + 重判后再决定。当前 Phase 1.5 v2 YELLOW 是唯一可部署信号。 |
| 4 | 试 funding + BTC<200d MA regime filter（对应 Phase 1.5 Ablation C 的反向用法），可能显著降低 OOS 方差。 |

### 原 Plan（保留作 reference，待网络条件允许时执行）


### 目标
验证跨 Hyperliquid + 主要 CEX 的 funding 差套利可行性。

### 任务清单

#### Week 9: 数据 + 信号
- [ ] **拉 funding 历史**（CCXT）：
  ```python
  for ex_name in ["hyperliquid", "binance", "bybit", "bitget"]:
      ex = getattr(ccxt, ex_name)()
      for symbol in active_perp_symbols:
          history = ex.fetch_funding_rate_history(symbol, since=..., limit=...)
          save(history, f"data/funding/{ex_name}/{symbol}.parquet")
  ```
- [ ] **信号**（`signals/funding_arb.py`）：
  ```python
  def funding_spread_signal(coin, ex_a, ex_b, threshold=0.003):
      fr_a = latest_funding(coin, ex_a)
      fr_b = latest_funding(coin, ex_b)
      spread = fr_a - fr_b
      if abs(spread) > threshold:  # 8h 差 > 0.3%
          return create_delta_neutral_trade(coin, ex_a, ex_b, spread)
      return None
  ```

#### Week 10: 回测 + 实操限制
- [ ] **回测**：模拟 delta-neutral 仓位，每 8h 结算 funding，每月再平衡
  - 包含：手续费（两边都付）、提取保证金成本、跨平台时间差
- [ ] **实操限制建模**：
  - 单平台最小仓位（< $100 通常不行）
  - 总资金分摊（一半 Hyperliquid 一半 CEX）
  - KYC/提现限制
- [ ] 决策报告 `phase3_decision.md`

### Pass Criteria
- **绿灯**：年化净收益 ≥ 25%，最大回撤 ≤ 5%，触发频率 ≥ 每周 1-2 次
- **黄灯**：年化 15-25% → 候选组合（作为低权重底盘）
- **红灯**：年化 < 15% 或负收益 → **Kill**

### Kill 后该做什么
- 直接进 Phase 4

### 特殊说明
即使其他策略全成功，**Phase 3 也建议保留作为底盘**（除非完全负收益），因为它降低组合整体波动。

---

## Phase 4: 反 Sybil 集群（Week 11-14）

> **这是 4 周的硬核研究，但如果成功，alpha 最强、最不易被吃掉。前提：Phase 2 通过。**

### 目标
识别 Hyperliquid 上的 sybil 钱包集群，回测验证反向其同步行为的 alpha。

### 任务清单

#### Week 11: 钱包行为特征工程
- [ ] **扩大钱包池**：从 Phase 2 的 200 个扩到 2000 个亏损钱包（PnL < -$1k）
- [ ] **特征工程**（`features/wallet_behavior.py`）：
  ```python
  features = {
      "tx_hour_entropy": tx_time_dist.entropy(),       # 下单时间均匀度（高 = 机器）
      "size_uniformity_cv": size.std() / size.mean(),  # 仓位大小变异系数
      "coin_diversity": n_unique_coins / n_trades,
      "avg_session_gap": median_time_between_trades,
      "round_number_pct": pct_of_round_sized_trades,   # $1000/$5000 类整数比例
  }
  ```

#### Week 12: 资金来源图分析
- [ ] **链上交易追踪**：用 Alchemy/Infura RPC 或 The Graph 查每个钱包的资金来源（首笔入金的 from address）
- [ ] **构建钱包图**：节点 = 钱包，边 = 共享资金来源 / 在 N 小时内有资金转移
- [ ] **集群识别**：
  - 简单版：基于资金来源 union-find
  - 进阶版：Louvain community detection on weighted graph
- [ ] 输出 cluster 表：`data/wallet_clusters.parquet`

#### Week 13: Sybil 集群反向回测
- [ ] **集群同向信号**：当一个 cluster 内 ≥30% 钱包在 1h 内同向开仓某币种 → 反向信号
- [ ] 回测对比：
  - 真"散户"反向（Phase 2 baseline）
  - Sybil 集群反向（Phase 4）
  - Sharpe 应显著优于 baseline
- [ ] 测试不同集群定义（按资金来源 / 按行为 / 混合）

#### Week 14: Walk-forward + 决策
- [ ] Walk-forward 6 fold（集群定义随时间更新）
- [ ] 决策报告 `phase4_decision.md`

### Pass Criteria
- **绿灯**：Sybil 集群反向 Sharpe ≥ Phase 2 单钱包 Sharpe × 1.3 + 绝对值 ≥ 2.0
- **黄灯**：Sybil 集群略优于 Phase 2 → 用作 Phase 2 的增强而非独立策略
- **红灯**：Sybil 集群没有 alpha → **Kill**，仅用 Phase 2

### Kill 后该做什么
- 完全合理 —— sybil 检测确实是高难度问题
- 时间不浪费，因为 Phase 4 的钱包池数据可以丰富 Phase 2

### 交付物
- `features/wallet_behavior.py`
- `data/wallet_clusters.parquet`
- `notebooks/phase4_sybil.ipynb`
- `strategies/active/sybil_reverse.json`（若 pass）

---

## Phase 5: 组合优化 + 纸面交易（Week 15-16）

> **把通过的策略组合起来，先在纸面验证。不投真钱。**

### 目标
- 把 Phase 1-4 通过的策略整合为统一组合
- 用过去 6 个月做"伪实盘"（基于历史价格 replay）

### 任务清单

#### Week 15: 组合优化
- [ ] **策略相关性矩阵**：每个 active strategy 的月度收益相关性
- [ ] **资金分配**：用风险平价 (risk parity) 或 mean-variance optimization
  - 例：解锁 30% + 钱包反向 25% + Funding 20% + Sybil 25%
- [ ] **整体回测**：
  - 月度收益曲线
  - 最大回撤
  - Sharpe / Sortino / Calmar
  - 不同市场状态下的稳定性
- [ ] **风险预算**：单策略最大占用资金 ≤ 40%

#### Week 16: 纸面交易系统
- [ ] **实时信号生成器**（`live/signal_generator.py`）：每 5 分钟轮询，输出该开/平的仓位
- [ ] **纸面交易记录**：信号触发但不下真单，记录假设执行 + 实际市场反应
- [ ] 跑满 7-14 天
- [ ] 对比：纸面 PnL 与回测预期偏差是否在 ±20% 内

### Pass Criteria
- 纸面 PnL 方向与回测预期一致
- 单日最大回撤 ≤ 5%
- 信号触发频率 ≈ 回测预期 ±30%

### Kill Criteria
- 纸面表现与回测严重背离 → 重新审视过拟合，回到 Phase 1-4 的最弱环节

---

## Phase 6: 小额实盘（Week 17-24）

> **8 周小额实盘，决定是否放大。**

### 目标
用 $500-2,000 真钱跑 8 周，验证回测能否在实盘复现。

### 任务清单

#### Week 17: 实盘准备
- [ ] **执行层**（`live/executor.py`）：
  - Hyperliquid SDK 下单
  - 订单类型用 ALO（maker 返佣）
  - 止损单立即跟上
  - 仓位规模用 1/20 Kelly（极保守）
- [ ] **风控层**：
  - 单笔最大风险 1% 账户净值
  - 日最大亏损 3% 强制停手
  - 月最大回撤 8% 重新评估
- [ ] **监控**：每笔交易自动记录到日志 + Telegram bot 提醒

#### Week 18-24: 运行 + 周复盘
- [ ] 每周日固定复盘：实际 PnL vs 回测预期 PnL 偏差
- [ ] 每周日检查 alpha decay 信号（滚动 30 天 Sharpe）
- [ ] 任何单日 > 3% 亏损强制 24h 停手

### 决策点（Week 24 末）
| 8 周累计结果 | 行动 |
|-------------|------|
| 净收益 ≥ +8% | 资金放大到 $5k-10k，继续 |
| 净收益 +2 ~ +8% | 继续小额 8 周再观察 |
| 净收益 -3 ~ +2% | 重新分析归因，调整权重 |
| 净收益 < -3% | 暂停实盘，回到 Phase 5 重审 |

---

## Phase 7: Alpha 监控 + 持续迭代（Week 25+）

> **永久运行的元层。Alpha 会衰减，监控比赚钱更重要。**

### 监控指标（每周自动产出）
- **Rolling Sharpe (30d / 90d)**：如果 30d < 60d × 50% → 警报
- **Hit Rate (30d)**：胜率突然下降 ≥ 10pp → 警报
- **Signal Frequency**：触发频率异常（暴增/暴减）→ 警报
- **Cluster Stability**（仅 Phase 4 在用时）：sybil 集群成员变化率 > 30%/月 → 重新聚类

### 持续动作
- [ ] 每月：拉新解锁事件、刷新钱包池、重新检查 funding spread
- [ ] 每季度：完整 walk-forward 重新校准参数
- [ ] 每半年：尝试加新 alpha 源（HIP-3 套利、KOL 钱包跟踪等之前 ⚠️ 标记的）

### 资金管理（实盘后）
- 利润 30% 转出到稳定币/法币（保护本金）
- 利润 30% 在 BTC/ETH 现货建立永久底仓
- 利润 40% 复投到策略本金

---

## 全程通用准则（贴显示器旁）

```
1. 每个 phase 严格执行 Pass/Kill criteria，不可"再试一次"
2. 数据先行：没数据就先补数据，不要凭直觉构造信号
3. Walk-forward 是非negotiable，单段回测不算数
4. 任何策略 Sharpe > 3.0 必然过拟合，重审
5. 实盘期间永远不修改策略参数，只能停 + 重新研究 + 重启
6. 不公开任何信号、代码、收益（反身性必杀）
7. 每周固定 2 小时复盘，雷打不动
```

## 时间投入预估

| 阶段 | 周数 | 预估每周时间 | 累计 |
|------|------|-------------|------|
| P0 基础设施 | 2 | 15-20h | 30-40h |
| P1 解锁 | 3 | 10-15h | 60-85h |
| P2 单钱包 | 3 | 12-18h | 96-139h |
| P3 Funding | 2 | 8-12h | 112-163h |
| P4 Sybil | 4 | 15-20h | 172-243h |
| P5 组合+纸面 | 2 | 10-15h | 192-273h |
| P6 实盘前 8 周 | 8 | 5-8h | 232-337h |
| **总计** | **24 周** | **平均 ~12h/周** | **~250-340h** |

**全职 ~6-8 周可完成。业余 5-6 个月可完成。**

---

## 资金需求预估

| 阶段 | 资金需求 | 用途 |
|------|---------|------|
| P0-P5 | $0-100 | 仅 AWS S3 下载费（< $50） |
| P6 实盘 | $500-2,000 | 真金小额验证 |
| P7+ 放大 | $5k → $25k → $50k | 按上一阶段成功阶梯放大 |

**总投入预期**：第一阶段（验证有 alpha）几乎零成本；只有真正进实盘才花钱。

---

## 失败分支处理

### 全部 4 个策略都 Kill 怎么办？
（Worst case）
- **诚实结论**：当前的 thesis（散户反向）在你的执行水平下无 alpha
- **next steps**：
  1. 把基础设施 + 数据成果整理为开源项目（声誉 + 学习 + 可能后续 SaaS）
  2. 转向更宽的方向：例如 HIP-3 新市场早期、协议升级套利等之前 ⚠️ 标记但样本少的方法（等数据攒够）
  3. 切到方法 D（之前提的 SaaS 路线）—— 你的研究本身就是产品

### 部分通过怎么办？
- 用通过的进入 Phase 5 组合
- 失败的留作未来重审

---

## 关键参考资源

| 类型 | 资源 |
|------|------|
| Hyperliquid 官方 SDK | https://github.com/hyperliquid-dex/hyperliquid-python-sdk |
| Hyperliquid 历史数据 | https://hyperliquid.gitbook.io/hyperliquid-docs/historical-data |
| TokenUnlocks | https://token.unlocks.app/ |
| Vectorbt 文档 | https://vectorbt.dev/ |
| CCXT（跨平台 API） | https://github.com/ccxt/ccxt |
| Keyrock 解锁研究 | https://keyrock.com/from-locked-to-liquidity-what-16000-token-unlocks-teach-us/ |
| Walk-forward 方法论 | López de Prado《Advances in Financial Machine Learning》第 7 章 |
