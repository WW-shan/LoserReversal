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

```
Week:  1  2  3  4  5  6  7  8  9 10 11 12 13 14 15 16 17 18 19 20+
P0  [■■]                                                              基础设施
P1        [■■■]                                                       解锁策略
P2              [■■■]                                                 单钱包反向
P3                    [■■]                                            Funding 套利
P4                        [■■■■]                                      反 Sybil 集群
P5                                  [■■]                              组合优化+纸面
P6                                        [■■■■■■■■■■■■]              小额实盘
P7                                                          [持续]    Alpha 监控
```

**关键里程碑**：
- M1 (Week 2): 数据 pipeline 跑通，能从 Hyperliquid 拿任意币种 + 任意钱包历史
- M2 (Week 5): 解锁策略 Pass/Fail 决定（第一个能赚钱的信号 or 第一次砍策略）
- M3 (Week 14): 4 个 alpha 源全部验证完毕，挑出 ≥1 个能用的
- M4 (Week 17): 进入小额实盘
- M5 (Week 20+): 实盘 8 周后第一次复盘 + 资金放大决定

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

**Phase 1 verdict: RED — KILL**

- OOS Sharpe mean: n/a
- OOS n_trades total: 0
- Worst OOS MaxDD: n/a
- Reason: `data_gap` — OOS events filter down to unsupported tokens (LISTA) or event windows outside available candle coverage.
- Implication: current 348-day data cannot support a strategy edge claim. Rerun after 6+ months of additional unlock events; that would change the evidence base rather than the current Phase 1 kill decision.

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

### 目标
回测验证"反向跟踪特定亏钱钱包"策略，找出能持续产生正反向 alpha 的钱包池。

### 任务清单

#### Week 6: 钱包选择 + 数据
- [ ] **种子钱包池**（约 200 个）：
  - 从 Hyperdash 抓 Top Losers（手动 + Selenium）
  - 加入历史巨亏地址：James Wynn `0x5078c2fbea2b2ad61bc840bc023e35fce56bedb6` 等
  - 从 Hyperliquid leaderboard 取负 PnL 排名 top 200
- [ ] **拉历史成交**：
  ```python
  for addr in wallet_pool:
      fills = info.user_fills(addr)  # 最近 ~10k 笔
      save_to_parquet(fills, f"data/fills/{addr}.parquet")
  ```
- [ ] **过滤器实现**（`signals/wallet_filter.py`）：
  ```python
  def is_anti_alpha_wallet(wallet_df, min_trades=50, lookback_days=90):
      recent = wallet_df.filter(timestamp > now - 90d)
      if len(recent) < min_trades: return False
      sharpe_90d = calc_realized_sharpe(recent)
      if sharpe_90d > -0.5: return False
      avg_size = recent.size.mean()
      if avg_size < 1000 or avg_size > 200_000: return False  # 排除巨鲸和试探
      return True
  ```

#### Week 7: 单钱包反向 PnL 回测
- [ ] **核心函数**（`backtest/reverse_pnl.py`）：
  ```python
  def reverse_backtest(wallet_fills, price_df, holding_hours):
      pnls = []
      for fill in wallet_fills:
          reverse_side = "sell" if fill.is_buy else "buy"
          entry_px = price_at(fill.timestamp, fill.coin)
          exit_px = price_at(fill.timestamp + holding_hours, fill.coin)
          pnl = compute_pnl(reverse_side, entry_px, exit_px, fees, slippage)
          pnls.append(pnl)
      return analyze(pnls)
  ```
- [ ] 对每个候选钱包跑 4 个持仓时长：1h / 4h / 12h / 24h
- [ ] 输出每个钱包的反向 Sharpe 排序表

#### Week 8: 集群信号 + Walk-forward
- [ ] **共振信号**：当 N≥3 个 Top anti-alpha 钱包在 30 分钟内同向开仓 → 反向开仓
- [ ] 测试 N = [3, 5, 7, 10] 的 Sharpe
- [ ] Walk-forward：每 3 个月重新选 Top 钱包池（避免幸存者偏差）
- [ ] 决策报告 `phase2_decision.md`

### Pass Criteria
- **绿灯**：Top 钱包池反向 IR ≥ 1.2 + 集群共振 IR ≥ 1.5（OOS）
- **黄灯**：集群信号 IR 1.0-1.5 → 候选组合
- **红灯**：集群信号 IR < 1.0 → **Kill 单钱包路线**，跳过 #4（因为反 Sybil 是它的进化版）

### Kill 后该做什么
- 如果 Phase 2 失败 → Phase 4 也基本无望，直接跳到 Phase 3
- 节省 4 周时间

### 交付物
- `data/fills/` 含 200+ 钱包成交历史
- `notebooks/phase2_wallet_reverse.ipynb`
- `reports/phase2_wallet.html`
- `strategies/active/anti_wallet.json`（最优集群配置）

---

## Phase 3: 跨平台 Funding 套利（Week 9-10）

> **这是低风险底盘策略。即使其他全失败，这个也能扛住。**

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
