# LoserReversal

个人量化研究项目：探索基于链上数据的散户反向交易策略。

## 概述

基于 Hyperliquid 等链上数据，验证多个独立 alpha 源：

- 解锁日做空（基于 token unlock 事件）
- 单钱包反向（跟踪并反向操作亏损钱包池）
- 跨平台 Funding 套利
- 反 Sybil 集群信号

完整研究背景、可行性分析与执行路线见 [`.ccg/tasks/loser-reversal-indicator-research/research/`](./.ccg/tasks/loser-reversal-indicator-research/research/)。

## 技术栈

- Python 3.11+
- Hyperliquid Python SDK / CCXT
- Vectorbt（回测）/ NautilusTrader（实盘）
- DuckDB + Parquet（数据层）

## 使用

环境准备（即将提供）：

```bash
# TODO: setup steps once Phase 0 infrastructure is in
```

## License

MIT
