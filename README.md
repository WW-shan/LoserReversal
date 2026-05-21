# LoserReversal

> 个人量化研究项目：基于链上数据的散户反向交易策略探索。
> 核心思路 → 多 alpha 源回测 → 小额实盘验证。

## 项目背景

最初想法：在链上监控亏损散户钱包地址，按权重反向开仓。

经过深度研究后，扩展为 **4 个独立可量化的 alpha 源**：
1. **解锁日做空**（Keyrock 16000+ 事件实证 90% 负价格压力）
2. **单钱包反向**（最初想法的精确量化版）
3. **跨平台 Funding 套利**（低风险底盘）
4. **反 Sybil 集群信号**（最初想法的终极进化版）

## 当前阶段

**Phase 0: 基础设施搭建**（Roadmap Week 1-2）

完整路线见 [ROADMAP.md](.ccg/tasks/loser-reversal-indicator-research/research/ROADMAP.md)。

## 研究产出

- [ROADMAP](.ccg/tasks/loser-reversal-indicator-research/research/ROADMAP.md) — 16-20 周完整执行路线
- [REPORT](.ccg/tasks/loser-reversal-indicator-research/research/REPORT.md) — 最初可行性研究报告
- [PROFIT-PATH](.ccg/tasks/loser-reversal-indicator-research/research/PROFIT-PATH.md) — 盈利路径分析
- [evidence/](.ccg/tasks/loser-reversal-indicator-research/research/evidence/) — 22 份原始搜索证据 + 3 份关键页面抓取

## 技术栈

- **数据**：Hyperliquid Python SDK + CCXT + Parquet + DuckDB
- **回测**：Vectorbt（research）+ NautilusTrader（后期 live）
- **数据源**：Hyperliquid 公共 S3 archive + TokenUnlocks API + Coinglass

## 项目结构（规划）

```
LoserReversal/
├── data/                   # 历史数据（gitignored）
│   ├── candles/           # K 线
│   ├── fills/             # 钱包成交
│   ├── funding/           # 资金费率
│   └── unlocks/           # 解锁事件
├── signals/                # 信号生成
├── backtest/               # 回测脚手架
├── features/               # 特征工程
├── live/                   # 实盘执行
├── strategies/             # 已验证策略配置
├── notebooks/              # 研究笔记本
├── reports/                # 回测报告（gitignored）
└── .ccg/                   # 研究历史 + CCG 工作流
```

## 工作流

后续开发基于 [CCG](https://github.com/) 工作流推进，每个 phase 作为一个独立 task。

## 不公开声明

本仓库私有，禁止公开任何信号、参数、收益数据 —— **反身性必杀**。
