# Literature Review — crypto-alpha-portfolio

> 调研基于 11 个 smart-search query（Tavily + xAI Grok primary）+ 工业级 16k events 分析 + SSRN preliminary academic paper + Hyperliquid 124k whale trade simulation。
>
> Last updated: 2026-05-24
> Purpose: 用学术 + 行业证据指导 Phase 1.5 / Phase 2.5 重做，避免之前 verdict 误读

---

## Part A — Token Unlock Strategy (Phase 1 / 1.5)

### A.1 Thesis confirmed by multi-source evidence

| Source | Sample | Negative rate | Key finding |
|---|---|---|---|
| Keyrock 2024/2025 | **16,000+ events / 40 tokens** | **90%** negative | Impact starts **~30 days pre-event**; team -25% drawdown |
| HoKwang Kim SSRN 2026 ("72-Hour Shock?") | 52 Binance events | **88.5%** profit on pre-unlock 72h short | Direct alpha confirmation |
| SmartKarma empirical | Multi-token | 1% unlock ≈ -0.3% drop per week | Strongest effect window **-2d to +3/4d** |
| 6thman Ventures | 5,000 unlocks | Threshold effect | <1% no effect; 1-5% significant; 5-10% strong |
| Tokenomics.com | 200+ projects | First-year median -72% (high TGE) | Vesting design matters |
| **My thesis-check (Phase 0 prep)** | 8 fork-derived events | **87.5% negative** AR | mean AR T-7→T0 = -8.21%, p=0.01 |

**Convergence**: 87.5% (mine) / 88.5% (Kim) / 90% (Keyrock) 完全一致 → thesis 高 confidence。

### A.2 Window selection (critical)

| Window | Evidence | Use case |
|---|---|---|
| **T-30 → T0** | Keyrock 推荐主入场区间；anticipation 早盘 | 长 swing short |
| T-14 → T0 | SmartKarma 强效区间起点 | 中等持仓 |
| **T-2 → T+3** | SmartKarma "strongest cluster" | 短 tactical |
| T-72h → T0 | Kim SSRN 88.5% profit | 高频精准 |
| T+3 → T+14 | Keyrock 推荐反弹 long 入场 | **未实施，signal v2** |

**Phase 1 sub-optimal**：只测 T-7→T0，没测 30d 长 window 和 post-event reversal。

### A.3 Size threshold

| Bucket | Effect (Keyrock + 6thman) |
|---|---|
| <1% of circ supply | 无显著 |
| 1-5% | 显著 negative pressure |
| 5-10% | 强 drop 概率 |
| **>10%** | **2.4× sharper** drop |

**Phase 1 用 ≥2%**：剔除了大量 noise events，但也漏掉 1-5% 中等 events 的渐进效应。新设计应该 sweep `{1%, 2%, 5%, 10%}`。

### A.4 Category 排序（影响强度）

```
Team / Insider (-25% avg)  >  Investor (similar low cost basis)
  >  Advisor (high immediate sell)
  >  Airdrop (recipients sell quickly but allocation 小)
  >  Ecosystem (gradual deployment, weakest)
```

**Phase 1 全 category 混跑**：稀释了 team-only 的强信号。Phase 1.5 应该按 category 分桶分析。

### A.5 Vesting type

- **Cliff**: 一次性释放 → 更尖锐冲击
- **Linear/graded**: 渐进释放 → 平滑但仍 negative
- Phase 1 没区分。Phase 1.5 加 `is_cliff` 维度。

### A.6 Data sources comparison

| Platform | API | Coverage | Notes |
|---|---|---|---|
| **CryptoRank** | Public API ✓ | 数百 tokens, watchlist + analytics | 适合 ongoing tracking |
| **Messari** | Enterprise API ✓ | 全企业级 | 收费 |
| **token.unlocks.app (Tokenomist)** | 浏览器 only | 综合 | Phase 0 试图爬，session-bound token 失败 |
| **DefiLlama emissions** | Public ✓ | adapter-based, 我们 fork 派生 126 events | 已用 |
| **6thman dataset** | Research-only | 5000 events | Reference only |

**Phase 1.5 数据源策略**：DefiLlama fork + CryptoRank API + Tokenomist scrape（用 Playwright）→ 多源 dedupe 应达 1000-2000 events。

### A.7 Practical execution

- **Slippage**: HL spread + market impact，大 unlock 期间流动性变薄
- **Funding rate**: pre-event 时段 funding 通常 turn negative（short crowded），需要计 funding cost
- **Perp 可用性**: 不是所有 unlock token 在 HL 有 perp（我们用 has_hl_perp filter）

---

## Part B — Wallet Contrarian Strategy (Phase 2 / 2.5)

### B.1 HL retail loss statistics

| Account Size | Profitable % | 含义 |
|---|---|---|
| < $1K | 15% | 85% 亏损 — 强 anti-alpha cohort |
| $1K-$10K | 17% | 85%+ 亏损 |
| $100K-$1M | 26% | 中等 anti-alpha |
| $1M-$10M | 42% | 弱 anti-alpha |
| **>$10M** | **86%** | **反向 alpha**（whales win） |

**关键反转**：HL 124k whale trade simulation 显示 **"Trade size alone is a poor or negative predictor of success. Strategies copying larger trades underperformed."** Win rate 60% (>$10k) → 44.5% (>$5M)。

### B.2 Phase 2 设计错误剖析

| 我做的 | 学术建议 | 问题 |
|---|---|---|
| 按 `vlm_alltime` DESC 选 wallet | 按 `account_value` 选小账户 | **选到了大账户低 ROI 用户混合体（其中 86% 实际是 winners）** |
| `pnl_alltime/vlm < -0.5%` filter | `realized_loss_rate ≥ 50%` per 90-day window | 用 lifetime ratio，忽略时序 |
| `notional ∈ [$1k, $200k]` trade filter | `notional/account_value ≥ 0.05` ratio | trade size 是负指标（学术明确） |
| 没用 leverage | 高 leverage = retail dumb money | 漏关键信号 |
| 没用 time-of-day | Asian session + funding settle = cascade window | 漏 cascade alpha |
| 没用 funding context | Extreme funding = crowded direction | 漏 contrarian timing |

### B.3 真正的 anti-alpha wallet 特征

学术 + Hyperliquid 数据综合：

```python
def is_real_anti_alpha_wallet(wallet, lookback_days=90):
    return (
        # 1. Account size cohort (85% loss bracket)
        1_000 <= wallet.account_value <= 100_000
        # 2. Recent persistent loss
        and wallet.realized_loss_rate_90d >= 0.50
        # 3. High leverage user (dumb money signal)
        and wallet.leverage_avg_90d >= 5
        # 4. Active enough to matter
        and wallet.n_trades_90d >= 50
        # 5. Not market making (uniform-size trades)
        and wallet.size_cv_90d >= 0.3   # variation in trade size
    )
```

### B.4 Per-fill reverse signal weighting

不是所有 fill 都同等强反向 alpha。Per-fill features：

```python
def reverse_alpha_score(fill, wallet, context):
    score = 1.0
    # Oversized bet (panic/FOMO indicator)
    risk_ratio = fill.notional / wallet.account_value
    if risk_ratio >= 0.05:    # 5%+ account at risk
        score *= 1.5
    if risk_ratio >= 0.10:    # 10%+ = severe FOMO
        score *= 2.0
    # High leverage at entry
    if fill.leverage >= 10:
        score *= 1.3
    if fill.leverage >= 20:
        score *= 1.6
    # Funding-extreme context (crowded direction)
    if abs(context.funding_zscore) >= 2:
        score *= 1.4
    # Time-of-day
    if context.is_asian_session or context.is_funding_settle_window:
        score *= 1.2
    return score
```

### B.5 Funding extreme contrarian (overlap Phase 3 thesis)

- 92% time positive funding bias
- Extreme >0.05-0.1% per 8h → crowded longs → contrarian short
- Deep negative <-0.05% → crowded shorts → contrarian long
- **直接证实 Phase 3 funding arb thesis**
- 同时为 Phase 2 提供 timing context

### B.6 Liquidation cascade reversal

- Bitcoin 1-4h frame **negative autocorrelation** (mean reversion 学术证据)
- 越大 wick 越强反弹
- Cascade 后 **long** 是独立 alpha signal
- Phase 2.5 可加 cascade-reversal 模块

### B.7 Order Flow Imbalance (OFI)

- Cont-Kukanov-Stoikov 2014 model
- 10s-1min OFI 线性预测 ΔP
- 需要 L2 order book data（HL 不公开历史 L2）
- **Out of scope for Phase 2.5**（可作 Phase 5+ enhancement）

### B.8 Bot detection vs human retail

| 维度 | Bot | Human retail |
|---|---|---|
| 资金来源 | Shared / radial pattern | 各自交易所提现 |
| 时序 | Synchronized 高频 | Random / FOMO bursts |
| Trade size | Uniform (low CV) | Heterogeneous (high CV) |
| Round numbers | 多 (1000, 5000) | 不规则 |
| 行为 | Programmatic | Emotional |

**Phase 2 反向跟踪 mixed pool 时**：bot wallets 反向跟踪没意义（programmatic, no panic）。**应该先 filter out bots**。

→ Phase 4 bot 反向是独立 thesis，但 Phase 2.5 也要先做 **bot exclusion**（不然 retail signal 被稀释）。

---

## Part C — 修订的 execution priority

基于证据强度排序：

| 优先级 | Phase | 证据强度 | 预期 verdict |
|---|---|---|---|
| 1 | **Phase 1.5** Unlock v2 (academic-tuned) | 3 独立学术 + 我 thesis-check converge 87-90% | 大概率 GREEN / YELLOW |
| 2 | **Phase 3** Funding arb | 92% positive bias + extreme contrarian 学术验证 | GREEN / YELLOW |
| 3 | **Phase 2.5** Wallet v2 (academic filter) | 学术明确 account-size > trade-size | YELLOW（高于原 Phase 2） |
| 4 | **Phase 4** Bot 反向 (独立 thesis) | 数据可识别 bot vs human，但反向 bot 未验证 | 未知 |
| 5 | Phase 5 portfolio | 依赖至少一个 GREEN | — |

---

## Cited sources (all from smart-search 2026-05-23 / 24)

### Phase 1 sources
1. Keyrock — "From Locked to Liquidity: What 16,000+ Token Unlocks Teach Us"
   https://keyrock.com/from-locked-to-liquidity-what-16000-token-unlocks-teach-us/
2. HoKwang Kim — "The 72-Hour Shock?" SSRN 2026
   https://papers.ssrn.com/sol3/papers.cfm?abstract_id=6632838
3. SmartKarma — "The Impact of Token Unlock Events on Cryptocurrency Prices"
   https://www.smartkarma.com/insights/the-impact-of-token-unlock-events-on-cryptocurrency-prices-an-empirical-analysis
4. Streamflow — "What 40,000+ Crypto Projects Reveal About Unlock Design"
   https://streamflow.finance/blog/token-vesting-benchmark-report
5. 6thman Ventures — "Token Unlocks Analysis (5,000 events)"
   https://6thman.ventures/writing/token-unlocks
6. Lauren Stephanian — "The Optimal Token Vesting Schedule"
   https://offchaindata.substack.com/p/the-optimal-token-vesting-schedule
7. Phemex / Bitget Academy — Practitioner trading guides
8. Messari Token Unlocks docs — https://docs.messari.io/user-guides/intel/token-unlocks
9. CryptoRank Token Unlock — https://cryptorank.io/token-unlock
10. DefiLlama unlocks — https://defillama.com/unlocks

### Phase 2 sources
11. envyprotocol — "I Analyzed 10,000 Hyperliquid Traders"
    https://medium.com/@envyprotocol/i-analyzed-10-000-hyperliquid-traders-the-results-are-brutal-a29adcca8c2a
12. gwrx2005 — "Combining Simulation and Machine Learning Analysis of Whale Trading on Hyperliquid" (124k trades)
    https://medium.com/@gwrx2005/combining-simulation-and-machine-learning-analysis-of-whale-trading-on-hyperliquid-93f10d96941b
13. gwrx2005 — "Hyperliquid's Trading Behavior" (leverage analysis)
    https://medium.com/@gwrx2005/hyperliquids-trading-behavior-f867c897d970
14. Whale Portal — "How to Track Smart Money on Hyperliquid"
    https://whaleportal.com/blog/how-to-track-smart-money-on-hyperliquid-using-wallet-data/
15. eliquinox — "Order Flow Analysis of Cryptocurrency Markets" (OFI)
    https://medium.com/@eliquinox/order-flow-analysis-of-cryptocurrency-markets-b479a0216ad8
16. dm13450 — "Order Flow Imbalance" technical reference
    https://dm13450.github.io/2022/02/02/Order-Flow-Imbalance.html
17. Cont, Kukanov, Stoikov 2014 — OFI academic paper
18. arXiv 2505.09313 — Sybil cluster detection
    https://arxiv.org/html/2505.09313v1
19. Ledger Journal — Bitcoin intraday mean reversion
    https://ledgerjournal.org/ojs/ledger/article/download/213/212/1232
20. ResearchGate Oct 2025 cascade analysis
    https://www.researchgate.net/publication/396645981_Anatomy_of_the_Oct_10-11_2025_Crypto_Liquidation_Cascade_Macroeconomic_Triggers_Market_Microstructure_and_Systemic_Risk_Lessons

### Phase 3 sources
21. BitMEX funding rate study — 92% positive bias
    https://www.dlnews.com/external/bitmex-study-finds-cryptocurrency-funding-rates-positive-92-of-the-time-revealing-a-structural-market-bias/
22. MetaMask — "Perpetual Futures Funding Frequency Strategies"
    https://metamask.io/news/perpetual-futures-funding-frequency-strategies
23. NYU Stern — "Is There A Future In Perpetual Futures"
    https://www.stern.nyu.edu/sites/default/files/assets/documents/Duron-Carielo_Is%20There%20A%20Future%20In%20Perpetual%20Futures.pdf

---

## Open questions (deferred research)

1. **Bot 反向跟踪 alpha** — Phase 4 thesis, 未验证
2. **Cliff vs Linear quantitative impact** — Q1.4 search 失败，需要 retry
3. **HL L2 order book data availability** — 影响 OFI 可行性
4. **CryptoRank API pricing** — 决定是否能用做 Phase 1.5 数据源
5. ~~**Combined signal portfolio weight**~~ — 已在 Part C #4 (Q4 dr-4) 回答：需要 cross-thesis 不是 cross-window

---

## Part C — Phase 1.5 YELLOW 救援学术调研 (6 个 deep research, 2026-05-24)

> Trigger: Phase 1.5 v2 OOS Sharpe 0.61 = YELLOW. 调研 6 个救援方向的学术依据。
> Raw search outputs: `docs/research/raw-search/dr-1.json` 到 `dr-6.json`

### C.1 (Q1 dr-1) Walk-forward 中的 cohort 选择 overfit

**Source**: arxiv 2512.12924, algotrading101, marketcalls

> "Overfitting (Curve-Fitting): A model/strategy fits historical noise rather than true signals... Multiple parameters worsen this by increasing the search space."

**应用到 Phase 1.5**：每 split IS 自由选 cohort × min_pct = 12 cells search，5 splits 选 3 cohort → search space 过大产生 overfit。

**救援**：固定 cohort=`team`（学术 Part A 已证最强 -25% drawdown），只让 IS 选 min_pct。降 search space 4×。

### C.2 (Q2 dr-2) BTC 200d MA regime filter

**Source**: bitcoinmagazinepro, luxalgo, ResearchGate Adaptive Regime-Based Trading on Bitcoin, pyquantlab, grayscale

> "200-day SMA is a popular long-term trend filter for BTC strategies. Price above the 200-day SMA generally signals a bull regime (favor long exposure), while below signals a bear regime (favor cash or reduced exposure)."
>
> "Combining the 200-day MA filter with regime detection helps avoid whipsaws in choppy markets and improves risk-adjusted returns (Sharpe ratio) by limiting trades or sizing positions to favorable conditions."

**关键反直觉**：传统 trend filter "BTC > 200d MA 才入场" 适用于 **趋势跟随** 策略。
**对 contrarian short 是反向**：BTC > 200d MA = bull 期 → 反向 short 容易被 squeezed（参见 Q5）。所以正确 filter 是 "BTC < 200d MA 才开 short"。

**应用到 Phase 1.5**：Split 4 (2025-09→2026-03) 是 BTC 高位震荡期，unlock short 被多次反弹打掉 → -29% MaxDD。

### C.3 (Q3 dr-3) Event-driven stop loss + position sizing

**Source**: zignaly, IG, tradealgo, optimusfutures

> "Place [stop losses] based on: Technical levels — Below recent support, volatility (ATR multiples), or structure. **Event-specific buffers — Wider stops (5-10%+) around news to avoid whipsaws from volatility spikes**."
>
> Kelly Criterion: `f = (bp - q) / b`; in crypto use **fractional Kelly (half-Kelly)** due to fat tails

**应用到 Phase 1.5**：
- 当前没有 stop loss → MaxDD -29% 失控
- 加 -10% per-trade stop (event-specific buffer 上限)
- 或 ATR-based 自适应 (2×ATR 经典)
- 单笔风险 1-2% account equity（标准 retail risk management）

### C.4 (Q4 dr-4) 多 signal portfolio 组合的 Sharpe drag

**Source**: robotwealth, quantpedia

> "'**Sharpe drag**' occurs when high-volatility assets (common in crypto) increase the denominator more than the numerator, **or when assets correlate highly and fail to diversify risk**."
>
> "**Uncorrelated Alpha**: Returns from signals or assets with low/negative correlations to each other and the broader market. This boosts overall Sharpe by smoothing returns."

**应用到 Phase 1.5**：
v1 (T-7) + v2 (T-30) 共享同一 unlock thesis，只是 window 不同 → 它们在 unlock event 周围必然 **highly correlated** → portfolio Sharpe 0.54 < v2 alone 0.61。

**真正的 Sharpe boost** 必须 cross-thesis：
- v2 unlock short (event-driven)
- Phase 3 funding extreme contrarian (microstructure)
- Phase 2.5 wallet anti-alpha reverse (flow-driven)

这 3 个 thesis 之间预期相关性 < 0.3 → portfolio Sharpe lift = √N ≈ 1.7× 单 signal。

**结论**：Phase 1.5 内部混 v1+v2 无意义；要等 Phase 3 + Phase 2.5 完成才能做真分散组合。

### C.5 (Q5 dr-5) Bull/Bear regime 对 contrarian short 的影响

**Source**: RePEc 2018-09, changelly, arkm

> "Bull markets: High momentum, rising correlation across assets, and over-optimism create opportunities for contrarian shorts at peaks... However, **persistent upward trends can punish premature shorts via squeezes**."
>
> "Bear markets: ... high volatility favor shorts. Contrarian elements emerge in oversold conditions for mean-reversion longs, but **short-selling (via perpetual futures) is a direct profit path**. Grinding declines punctuated by relief rallies trap bulls."
>
> "Regime shifts (detectable via Hidden Markov Models or volatility/momentum filters) are critical—strategies that ignore them underperform."

**应用到 Phase 1.5**：
- Split 4 表现差 ✓ 与 "bull 期 short 被 squeeze" 一致
- Phase 1.5 当前没 regime filter → bull/bear 期间盲目开 short
- 加 BTC regime filter（Q2 的反向应用）应该剔除 squeeze 风险

### C.6 (Q6 dr-6) Walk-forward "lucky fold" 与 bootstrap CI

**Source**: Wikipedia walk-forward, Interactive Brokers, balaena medium, levelup gitconnected

> "Single split is prone to '**lucky fold**' bias — one favorable random or arbitrary split can produce overly optimistic results that fail in live trading."
>
> "Walk-forward helps by evaluating performance across many rolling OOS periods. **Bootstrap resampling** of trade returns provides confidence intervals on Sharpe estimates."

**应用到 Phase 1.5**：
- Split 3 单 split Sharpe 1.70 拉高 mean → 典型 lucky-fold sign
- 36 trades 可做 bootstrap：resample with replacement 10,000 次 → 算 Sharpe 95% CI
- 决策：
  - CI lower bound > 0 → 信号 robust，值得 tuning toward GREEN
  - CI lower bound < 0 → 0.61 可能是 lucky-fold 假象，应该承认 YELLOW 上限或 RED

### C 部分综合结论

5 root causes（详见 `phase-1-5-diagnostic.md`）每个都有学术 mitigation：

| Root cause | Source | Mitigation |
|---|---|---|
| 1. Split 3 outlier | Q6 | Bootstrap CI |
| 2. Cohort drift | Q1 | Fix cohort=team |
| 3. Bear-period failure | Q2 + Q5 | BTC < 200d MA filter |
| 4. MaxDD -29% | Q3 | Per-trade stop loss |
| 5. Portfolio Sharpe drag | Q4 | Defer to cross-thesis (P3 + P2.5) |

### Part C cited sources (6 new)

24. arXiv 2512.12924 — Walk-Forward Optimization
    https://arxiv.org/html/2512.12924v1
25. algotrading101 — Walk-Forward Optimization Guide
    https://algotrading101.com/learn/walk-forward-optimization/
26. marketcalls — Lookahead bias in Python
    https://www.marketcalls.in/python/understanding-look-ahead-bias-and-how-to-avoid-it-in-trading-strategies.html
27. Bitcoin Magazine Pro — 200-day MA chart
    https://www.bitcoinmagazinepro.com/charts/bitcoin-200-day-moving-average/
28. LuxAlgo — Position trading with 200-day MA
    https://www.luxalgo.com/blog/position-trading-with-200-day-moving-average/
29. ResearchGate 395401021 — Adaptive Regime-Based Trading on Bitcoin
    https://www.researchgate.net/publication/395401021_Adaptive_Regime-Based_Trading_on_Bitcoin_Backtesting_and_Walk-Forward_Evaluation
30. pyquantlab — Regime-filtered momentum strategy
    https://pyquantlab.medium.com/building-a-regime-filtered-risk-adjusted-momentum-strategy-for-cryptocurrencies-926f4bfa1240
31. Grayscale — Trend filter momentum signals
    https://research.grayscale.com/reports/the-trend-is-your-friend-managing-bitcoins-volatility-with-momentum-signals
32. zignaly — Event-driven crypto strategies
    https://zignaly.com/crypto-trading/event-driven-trading-strategies
33. tradealgo — Crypto risk management
    https://www.tradealgo.com/trading-guides/crypto/crypto-risk-management
34. RoboWealth — Combining crypto alphas
    https://robotwealth.com/quantifying-and-combining-crypto-alphas/
35. Quantpedia — Diversification tag
    https://quantpedia.com/tag/diversification/
36. RePEc 2018-09 — Cycle-dependent crypto contrarian
    https://ideas.repec.org/p/war/wpaper/2018-09.html
37. Changelly — Bears vs Bulls in crypto
    https://changelly.com/blog/bears-vs-bulls-in-crypto-market-players/
38. Wikipedia — Walk forward optimization
    https://en.wikipedia.org/wiki/Walk_forward_optimization
39. Interactive Brokers — Walk-forward analysis deep dive
    https://www.interactivebrokers.com/campus/ibkr-quant-news/the-future-of-backtesting-a-deep-dive-into-walk-forward-analysis/
40. balaena — Train/test/walk-forward for on-chain factors
    https://medium.com/balaena-quant-insights/train-test-split-cross-validation-and-walk-forward-testing-for-on-chain-factors-b5fcf01572e2
