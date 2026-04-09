# Veritas v0.1 — Product Brief

> First reference implementation of Veritas: trust infrastructure for agent-native finance.
> A **Lean-native** trading agent on Hyperliquid that knows what it's betting on, monitors whether the bet still holds, and gets smarter every time it's wrong.

---

## 1. 目标

构建一个 **Lean 4 原生**的 trading agent,运行在 Hyperliquid 永续合约上,作为 Veritas trust infrastructure 的第一个 reference implementation。

Lean-native 的意思是:**所有核心决策逻辑、仓位计算、风险约束、学习更新都用 Lean 4 写成**。Python 只负责 I/O——连接 Hyperliquid API、调用 LLM、读写 SQLite。**信任边界在 Lean 和 Python 之间清晰存在**: Lean 是 verified core,Python 是 untrusted I/O shell,两者通过编译边界连接。

它要证明的不是"我们能做交易",而是三件比所有现有 trading agent 多走一步的事:

- **这个 agent 知道自己每笔交易在赌什么** — assumption 是 Lean 里的类型,不是 Python 里的字符串
- **持续监控这些赌注是否还成立** — monitor 的逻辑在 Lean 里,其退出条件的正确性可被形式化证明
- **从每次对错中更新自己对世界的理解** — learner 的统计更新规则在 Lean 里,其单调性和收敛性可被形式化证明

### 为什么是 Hyperliquid

完全链上 orderbook、API 干净、testnet 免费、无 KYC、24/7 交易、反馈循环极快。Crypto perps 是 agent 已经在大规模交易但完全没有 trust 层的地方——这是 Veritas 战略上要先占的"农村"。Hyperliquid 又通过 HIP-3 / HIP-4 把战场从 crypto 扩展到传统金融和 prediction market,意味着同一套 agent 架构未来可以无缝跨资产类别延伸。

### 为什么是 Lean 4 原生

因为如果 Veritas 的定位是"trust infrastructure for agent-native finance",那核心逻辑就不能是事后补证明的 Python 代码。核心逻辑必须**从一开始就是可证明的形式**。这意味着:

- 所有纯函数(计算、决策、统计更新)写在 Lean 4 里
- 关键性质作为定理陈述在同一个文件里(v0.1 证明可暂时用 `sorry`,v0.2 逐步补全)
- Python 的角色被严格限制为"跟外部世界说话的薄壳",它不含任何可以被形式化的逻辑
- 信任边界由编译和执行结构强制,不是靠开发者自律

这种路线的代价是开发速度慢 2-3 倍,可维护性对非 Lean 程序员为零。但这是 Veritas 必须付的代价——**否则它就跟市面上所有其他 trading agent 没有本质区别**。

### 为谁做

两类人。

第一类是已经在 Hyperliquid 或其他 crypto perps 上交易、有技术能力、有风险意识的个人用户和小型团队。他们厌倦了现有 bot 的两种极端——要么是静态规则没有智能,要么是 LLM 黑箱不知道在做什么。

第二类是 formal methods 和 DeFi 社区里的人——Lean 社区、以太坊基金会、Certora 这种 formal verification 公司、做 agent infra 的研究者。他们会看 Veritas 的代码,不是因为想交易,而是想看"Lean 4 在生产级金融应用里到底长什么样"。**这一类人今天几乎没有对应的开源项目可看,Veritas 是第一个**。

### 核心原则(不可妥协)

- **Lean-native**: 所有核心逻辑在 Lean 里。Python 只做 I/O 胶水。边界清晰,不混淆。
- **Frictionless**: `elan install` → `lake build` → `pip install` → 填 config → 在 testnet 上跑起来。构建复杂度隐藏在 lake + pyproject 背后,用户不感知。
- **Proactive**: Agent 自己看市场、自己决策、自己执行、自己监控、自己出场。人类是 legislator(设约束),不是 operator(按按钮)。
- **Self-evolving with context**: 每笔交易都更新假设库。**这是它跟所有现有 trading agent 的本质区别**。
- **State-first, then prove, then audit axioms**: 所有关键性质必须被显式陈述在 Lean 代码里。v0.1 已将全部 sorry 替换为完整证明,但这些证明依赖 20 个 Float 公理——公理数量是下一个要压缩的 trust signal。

### 不做什么(明确边界)

- 不做策略生成 — 策略模板固定
- 不做多 agent 模拟 — 一个主循环,一个 LLM brain(在 Python 侧),不搞辩论
- 不做 Web UI — 终端输出 + JSONL 日志
- 不做多交易所 — Hyperliquid 一家
- 不做 mainnet 真钱 — v0.1 只在 testnet
- **不把 LLM 调用放进 Lean** — LLM 输出是 non-deterministic,天然属于 Python 的"不可信区"。Lean 验证的是"无论 LLM 输出什么决策,Veritas 的响应都在约束内"。这是 Veritas 的核心哲学: **LLM 是 untrusted oracle,Lean 是 trusted envelope**。

---

## 2. 工程 MVP

**核心假设**: 一个 trading agent 只要能做到"显式声明赌注 + 持续监控赌注 + 从对错中学习",且这三件事的核心逻辑是形式化的,就已经跟市面上所有开源 agent 有质的区别。

**v0.1 只支持一个交易对**: `BTC-USDC perp`。一个交易所、一个交易对、一种策略。

### 唯一策略: funding rate 回归套利

为什么选这个:
- Hyperliquid 的 funding 数据一个 API 调用就能拿到
- 策略的假设极其清晰可表达("funding rate 会从极端值回归正常范围")
- 反馈周期短(每小时一次 funding 结算)
- 天然包含 carry + mean reversion 两个引擎,是 Veritas 哲学的最佳展示场
- 数学结构简单,适合作为第一个 Lean 定理库的对象

### 架构: Lean Core + Python I/O Shell

```
┌─────────────────────────────────────────────────────────┐
│                   User / Terminal                        │
└─────────────────────────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────┐
│ Python I/O Shell (≤ 300 lines)                           │
│   main.py      — orchestration loop                      │
│   observer.py  — Hyperliquid API client                  │
│   executor.py  — Hyperliquid order placement             │
│   extractor.py — LLM client (v0.1 placeholder, unused)   │
│   journal.py   — SQLite read/write                       │
│   bridge.py    — subprocess + JSON bridge to Lean core   │
└─────────────────────────────────────────────────────────┘
                           │
                  subprocess + JSON
                           │
                           ▼
┌─────────────────────────────────────────────────────────┐
│ Lean 4 Verified Core (compiled via `lake build`)         │
│                                                           │
│   Veritas.Types       — Assumption, Signal, Position     │
│   Veritas.Finance     — PositionSizing, MaxLoss, Kelly   │
│   Veritas.Strategy    — FundingReversion, ExitLogic      │
│   Veritas.Learning    — Reliability, Update rules        │
│   Veritas.Main        — Core decision entry point        │
│                                                           │
│   Compiled to native binary: `veritas-core`             │
│   Invoked as: veritas-core <command> <json-input>        │
│   Output: JSON via stdout                                │
└─────────────────────────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────┐
│ Hyperliquid Testnet API / SQLite / LLM API               │
└─────────────────────────────────────────────────────────┘
```

**信任边界**: Python 壳子不可信(它跟外部世界说话,受网络、LLM、用户输入影响)。Lean 核心可信(它是纯函数,所有输入由 Python 壳子喂入,所有输出由 Python 壳子处理)。**Veritas 的安全声明永远只针对 Lean 侧,Python 侧被视为敌对环境**。

### 八步主循环

主循环由 Python 编排,但**每一步的核心决策都下放给 Lean core**:

```
1. observe  (Python) → 查 Hyperliquid funding rate、价格、持仓 → MarketSnapshot JSON
2. decide   (Lean)   → veritas-core decide <snapshot>          → Signal | null
3. declare  (Lean)   → veritas-core extract <signal>           → Assumption list
4. check    (Python) → 从 SQLite 查每个 assumption 的 reliability
5. size     (Lean)   → veritas-core size <equity, enriched>    → PositionSize
6. execute  (Python) → Hyperliquid SDK 开仓
7. monitor  (Lean)   → veritas-core monitor <snapshot, pos>    → ExitDecision
8. learn    (Lean)   → veritas-core update-reliability <...>   → NewStats
                       (Python 把新 stats 写回 SQLite)
```

**注意: Python 侧永远不做决策逻辑判断**。所有 if/else 都在 Lean 里。Python 只负责"把数据塞给 Lean,把 Lean 的输出塞给外部世界"。**这是架构不变量,不能违反**。

### 关键不变量(Veritas 的灵魂)

这些不变量一部分在 Lean 类型系统里强制,一部分由定理陈述保证:

1. **每次交易必须有显式 assumption 声明** — `TradeDecision` 类型里 `assumptions : List Assumption` 是 non-empty 字段。类型系统强制。
2. **每次平仓必须归类原因** — `ExitReason` 是 sum type: `AssumptionMet | AssumptionBroke | StopLoss`。类型系统强制。
3. **position size 永远非负且有上界** — `positionSize_nonneg` 和 `positionSize_capped` 定理陈述。v0.1 用 `sorry`,v0.2 证明。
4. **reliability 更新单调** — 连续 n 次 assumption_met 之后 reliability 单调不减。`reliabilityUpdate_monotone_on_wins` 定理陈述。
5. **硬止损兜底** — `monitor` 的退出判断里,stop_loss 是最后的 fallback,永远在另外两个条件之后检查但一旦触发必然执行。类型 + 定理双重保证。

### 技术栈

**Lean 侧:**
- Lean 4 (stable 最新版,由 `lean-toolchain` 锁定)
- Mathlib (用于实数、概率、基础数学)
- `lake` build 系统
- 输出 native binary (通过 `lean_exe` target)

**Python 侧:**
- Python 3.11+
- `hyperliquid-python-sdk` (官方)
- `anthropic` 或 `openai` (v0.1 仅作依赖占位,当前策略不调 LLM)
- `sqlite3` (stdlib)
- `subprocess` (stdlib)
- `tomllib` (stdlib, 读 config)

**不用**: Docker、Postgres、Redis、Kubernetes、Web 框架、LangGraph、任何 agent 框架。

### 目录结构

```
veritas/
├── README.md                    # Lean-native positioning + quickstart
├── NORTH_STAR.md                # 项目指南针
├── PRODUCT_BRIEF.md             # 本文档
├── config.example.toml          # 配置模板
├── lakefile.lean                # Lean build 配置
├── lean-toolchain               # Lean 版本锁定
├── requirements.txt             # Python 依赖
├── pyproject.toml               # Python 包配置
│
├── Veritas/                     # Lean 源码(核心)
│   ├── Types.lean               # 核心类型定义
│   ├── Finance/
│   │   ├── PositionSizing.lean  # sizer + 定理
│   │   ├── MaxLoss.lean         # risk bound + 定理
│   │   └── Kelly.lean           # Kelly criterion 形式化
│   ├── Strategy/
│   │   ├── FundingReversion.lean  # decider + extractor 逻辑
│   │   └── ExitLogic.lean         # monitor 逻辑
│   ├── Learning/
│   │   └── Reliability.lean     # learner 更新规则 + 定理
│   └── Main.lean                # 主入口 (lean_exe target)
│
├── python/                      # Python I/O 壳子
│   ├── __init__.py
│   ├── main.py                  # 八步循环的编排
│   ├── observer.py              # Hyperliquid 数据查询
│   ├── executor.py              # Hyperliquid 下单
│   ├── extractor.py             # LLM 客户端占位 (v0.1 未使用)
│   ├── journal.py               # SQLite 读写
│   └── bridge.py                # subprocess + JSON 桥
│
├── data/
│   └── veritas.db               # SQLite (gitignore)
├── logs/
│   └── veritas.jsonl            # 事件流 (gitignore)
└── tests/
    ├── test_bridge.py           # Python ↔ Lean 桥测试
    ├── test_full_loop.py        # 端到端循环测试(用 fake market)
    └── FakeMarket.lean          # Lean 侧的模拟数据生成
```

### 用户体验

```bash
$ git clone github.com/[you]/veritas && cd veritas
$ elan install $(cat lean-toolchain)    # 安装 Lean
$ lake build                             # 构建 Lean 核心
$ pip install -r requirements.txt        # 装 Python I/O 依赖
$ cp config.example.toml config.toml
$ # 编辑 config.toml: 填入 Hyperliquid testnet 私钥
$ python -m python.main

Veritas v0.1 | Lean-native core | Hyperliquid Testnet | BTC-USDC perp
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Core: Veritas.Main (Lean 4, compiled to native)
Proven theorems: 9/9 | Sorry count: 0 | Axiom count: 20 (see FloatAxioms.lean)
Assumption library: 1 assumption, 0 historical trades

[12:03:01] observe → snapshot: funding=-0.042%, price=$68,420
[12:03:01] decide  → Lean core: SIGNAL LONG
[12:03:01] extract → Lean core: 1 assumption
             • "funding_rate_reverts_within_8h" (reliability: 50%, default)
[12:03:01] size    → Lean core: 0.3x leverage
             (reduced from 1x baseline due to low reliability)
             Max loss if stopped: 1.5% of equity
[12:03:04] execute → Hyperliquid: LONG 0.1 BTC @ $68,420

[14:11:22] monitor → Lean core: HOLD (funding=-0.008%, approaching target)
[15:02:15] monitor → Lean core: EXIT (reason: assumption_met)
[15:02:18] execute → Hyperliquid: CLOSE @ $68,890 (+0.69%)
[15:02:18] learn   → Lean core: reliability 0.5 → 1.0 (1/1)
```

### 不在 v0.1 范围内

- 消除 Float 公理依赖 (v0.2 目标: 将 rounding-dependent 公理降为零)
- 多策略、多资产
- LLM 动态 extraction (v0.1 Lean 侧硬编码 assumption template)
- Web dashboard
- 实时通知
- ZK certificate 生成 (v0.3+)
- 假设库的 oracle 化 (v0.3+)

**v0.1 的代码量目标**: Lean 约 400-600 行, Python 约 200-300 行。总计 600-900 行。如果超过说明过度工程。

---

## 2.5 三个 Gate 在 v0.1 的体现

Veritas 的原始设计提出了三个验证 Gate,作为 agent 信任模型的三个独立维度。v0.1 实现了其中一个的完整版本,另外两个的部分形式或占位。这一节说明每个 Gate 在当前代码中的对应位置,以及它们在后续版本中如何展开。

### Gate 1: 信号一致性(部分实现)

**原始设想**: 一个交易信号的内部逻辑是否自洽?多个并发信号是否互相矛盾?

**v0.1 中的位置**: `Veritas/Strategy/FundingReversion.lean` 的 `decide` 函数和 `extractAssumptions` 函数。`decide` 检查 funding rate 是否到达极端阈值(信号触发的基本条件),`extractAssumptions` 把信号翻译成显式假设清单。

**为什么是部分实现**: v0.1 只有一个策略(funding rate 回归),所以"信号一致性"被退化为"funding rate 是否在阈值之外"——这只是一个 if 语句,不是真正的多信号一致性验证。真正的 Gate 1 需要至少两种策略并存,然后形式化检查它们的信号组合是否互相矛盾(例如 funding 信号建议做空但基差信号建议做多)。

**v0.2 中将加入的定理**: `theorem signal_consistency : ∀ s : SignalSet, MutuallyConsistent s.signals`

### Gate 2: 策略-约束兼容性(已实现,这是 v0.1 的核心成就)

**原始设想**: 任何策略的执行都必须满足预设的风险约束,无论 LLM 决策多么疯狂。

**v0.1 中的位置**: `Veritas/Finance/PositionSizing.lean` 中的四个已证明定理,加上 `Veritas/Strategy/ExitLogic.lean` 的 `exitReason_exhaustive`。

具体对应:

| 定理 | 保证的不变量 |
|------|--------------|
| `positionSize_nonneg` | 仓位永远非负 |
| `positionSize_capped` | 仓位永远不超过 equity 的 25% |
| `positionSize_zero_at_no_edge` | 可靠度 ≤ 0.5 时仓位为 0 |
| `positionSize_monotone_in_reliability` | 可靠度越高仓位越大(单调) |
| `exitReason_exhaustive` | 每次出场必归类为三种 reason 之一 |

这五个定理加起来构成 Gate 2 的形式化版本——它们保证**无论 LLM 或外部信号源给出什么决策,sizer 输出的仓位永远在数学保证的安全范围内,且每次出场的归因都是穷尽的**。这是 v0.1 唯一一个在形式化层面完整的 Gate。

### Gate 3: 多策略干扰检测(不存在,v0.2+ 工作)

**原始设想**: 当一个新信号到来时,加入它之后,整个 portfolio 的总风险敞口是否仍在约束内?多个 active position 之间是否存在隐藏的相关性集中?

**v0.1 中的位置**: 不存在。Gate 3 只在多策略并存的系统里有意义,v0.1 单策略架构下根本没有"多策略干扰"这件事。

**为什么 v0.1 不做**: Gate 3 不是一个独立的 feature,它是策略多样化的副产品。在只有一种策略时强行实现 Gate 3 等于在只有一个员工时设计组织架构——形式上能写,但没有任何对象可以验证。**正确的做法是先单策略跑稳,再加第二个策略,然后 Gate 3 自然出现**。

**v0.2 中将加入的定理**:
`theorem portfolio_invariant : ∀ (existing : List Position) (new : Signal),`
`  portfolioRisk (existing ++ [openFromSignal new]) ≤ maxAllowedRisk`

### 当前 Gate 完整度图景

| Gate | 状态 | v0.1 中的形式 | 形式化完整度 |
|------|------|---------------|-------------|
| Gate 1: 信号一致性 | 部分 | 单策略 if 判断 | 0/1 定理 |
| Gate 2: 策略-约束兼容 | **完整** | 5 个已证明定理 | **5/5 定理** |
| Gate 3: 多策略干扰 | 不存在 | N/A(单策略) | 0/1 定理 |

**v0.1 的核心成就是把 Gate 2 做扎实**,作为单策略系统的最小完整 trust 形态。Gate 1 和 Gate 3 的展开依赖于 v0.2 加入第二种策略——加策略不是"feature 扩展",是激活另外两个 Gate 的物理前提。这是为什么 v0.2 的方向是策略多样化而不是 Lean 证明数量的增加。

---

## 2.6 Layer 5b: Hyperliquid Testnet 对接(关键路径)

v0.1 的 Lean 核心已完成(0 sorry, 9 定理, 20 公理)。当前瓶颈是 **Python I/O 壳的 testnet 对接**——`observer.py` 和 `executor.py` 的真实 Hyperliquid API 调用仍为 `NotImplementedError`。

这是完成标准第一条("跑通: 14 天 + 20 笔交易")的唯一阻塞项。

### 需要实现的内容

| 文件 | 当前状态 | 需要做的事 |
|------|---------|-----------|
| `python/observer.py` | `FakeObserver` 可用,`HyperliquidObserver` 是 stub | 用 `hyperliquid-python-sdk` 实现 `snapshot()`, `equity()`, `current_position()` |
| `python/executor.py` | `FakeExecutor` 可用,`HyperliquidExecutor` 是 stub | 用 `hyperliquid-python-sdk` 实现 `open_position()`, `close_position()`, `current_position()`, `equity()` |
| `python/main.py` | 硬编码使用 `FakeObserver` + `FakeExecutor` | 加 `--live` flag 切换到真实 observer/executor,读 `config.toml` 的私钥 |

### 不需要改动的内容

- **Lean 核心**: 零改动。`veritas-core` binary 已编译,决策逻辑不变。
- **bridge.py**: 零改动。subprocess 桥与数据来源无关。
- **journal.py**: 零改动。SQLite schema 不变。

这就是 Lean-native 架构的价值——**I/O 层替换不影响核心逻辑层,因为信任边界是编译边界**。

### 风险和注意事项

- Hyperliquid testnet 的 funding rate 可能长时间不触发阈值(0.05%/hr),导致 agent 长时间无交易。**应对**: 可临时降低 `fundingThreshold` 参数(需在 Lean 侧修改并重新 `lake build`)。
- testnet 资金需要通过 faucet 获取,额度有限。
- testnet API 可能不稳定,需要在 `observer.py` 和 `executor.py` 中加 retry/reconnect(这是 I/O 层的职责,不影响 Lean 核心)。

---

## 3. 完成标准

完成不是"代码写完了",是下面**四件事**同时为真。任何一条不满足,v0.1 没完成。

### 第一: 跑通

Agent 在 Hyperliquid testnet 上无人工干预连续运行 14 天,期间至少完成 20 笔完整交易。每笔交易都有完整的 assumption 声明 + exit reason 归类 + 假设库更新。**决策全部由 Lean 核心产生**,Python 侧没有任何 if/else 走入决策路径。

### 第二: 可演示

任何人 clone repo 后能在 10 分钟内(不算 Lean toolchain 安装时间,算 `lake build` 时间)让 agent 跑起来。`README.md` 有能复制粘贴的 quickstart。第一次 `lake build` 成功 + 第一次 `python -m python.main` 输出 `observe → snapshot: ...` 两件事都能无痛完成。

### 第三: Lean 核心的完整性

所有核心决策函数(`decide`, `extractAssumptions`, `calculatePositionSize`, `checkExit`, `updateReliability`)在 Lean 里定义,不在 Python 里。**在 repo 里运行 `grep -rE "if.*(Signal|ExitDecision|PositionSize)" python/` 应该无输出**——Python 没有决策逻辑。

同时,以下 9 个定理在 Lean 里被**陈述并证明**(零 `sorry`):

- `positionSize_nonneg` — 仓位永远非负
- `positionSize_capped` — 仓位不超过 equity 的 25%
- `positionSize_monotone_in_reliability` — 可靠度越高仓位越大(单调)
- `positionSize_zero_at_no_edge` — 可靠度 ≤ 0.5 时仓位为 0
- `kellyFraction_nonneg` — Kelly fraction 非负
- `kellyFraction_mono` — Kelly fraction 对胜率单调
- `exitReason_exhaustive` — 每次 exit 必归类为三种 reason 之一
- `reliabilityUpdate_monotone_on_wins` — 连续胜利下 reliability 单调不减
- `reliabilityUpdate_bounded` — reliability 永远在 [0, 1] 区间

**Sorry count: 0。** 所有 9 个定理全部有完整证明,`lake build` 零 sorry 警告。

**Axiom count: 20。** 这些证明依赖 `Veritas/Finance/FloatAxioms.lean` 中的 20 个公理。这是 v0.1 trust story 的诚实边界:Lean 4 的 `Float` 是不透明 FFI 类型,标准库不提供任何代数引理,因此我们必须公理化 IEEE 754 的基本性质才能证明任何 Float 函数的属性。

这 20 个公理分为两类:
- **13 个精确公理**(ordering、sign preservation、Nat.toFloat):在 IEEE 754 非 NaN 有限值上严格成立,无近似
- **7 个 rounding-dependent 公理**(乘法/减法/除法的单调性):假设 IEEE 754 舍入不反转不等式方向。对 Veritas 使用的数值范围(概率 ∈ [0,1]、小整数计数、Kelly 分数)这个假设在实践中成立,但严格来说不对所有 Float 值普遍为真

公理的完整清单、soundness 分类和设计理由见 `FloatAxioms.lean` 顶部的 doc comment。**axiom count 是与 sorry count 同等重要的透明 trust signal**——它告诉读者"我们的证明信任了什么"。v0.2 的目标之一是减少 axiom count,尤其是探索将 Float 替换为可证明的数值类型(如 `Rat` 或 Mathlib 的 `Real`),从而将 rounding-dependent 公理降为零。

### 第四: 可被讨论

Veritas GitHub repo 公开,并且在下列**三个**圈子中至少两个发布并产生回应:

- **Hyperliquid Discord** `#builders` 频道: demo 帖收到至少 5 条非自动回复
- **Lean Zulip** 或 **Lean Community Reddit**: announcement 帖收到至少 3 条评论(加分项: 有 Lean 核心开发者留言)
- **LessWrong** 或 **EthResearch**: 长文介绍"Lean-native trust layer for agent finance"收到至少 3 条评论

**重点不是数量,是确认 Veritas 在 Lean 圈子和 crypto 圈子同时被注意到**——这是 Veritas 战略双重定位的第一次验证。

### 当前状态与下一步

截至 v0.1 开发的当前 checkpoint:

- ✓ Lean core: 9 个定理全部证明 (0 sorries, 20 axioms 透明记录)
- ✓ Python shell: bridge / journal / observer 接口 / executor 接口 / main 编排
- ✓ Layer 5a: 8 步循环在 fake market 上 deterministic 跑通,test_loop.py 通过,demo_output.txt 生成
- ☐ Layer 5b: 真实 Hyperliquid testnet 集成 (下一步)
- ☐ 14 天连续运行 + 20 笔真交易 (v0.1 完成标准第一条)
- ☐ 公开发布到三个核心圈子 (v0.1 完成标准第四条)

**Layer 5b 的具体内容**:

1. 实现 `python/observer.py` 的真实版本——用 `hyperliquid-python-sdk` 接 testnet API,返回真实的 BTC funding rate / price / liquidations,保持跟 fake observer 完全一致的 JSON schema
2. 实现 `python/executor.py` 的真实版本——四个方法 (`open_position`, `close_position`, `current_position`, `equity`) 全部映射到 hyperliquid SDK
3. 第一次 `python -m python.main` 跑 testnet,debug 任何 I/O 层 bug,持续运行直到稳定

**Layer 5b 的特点**: 所有可能出现的 bug 都在 Python I/O 层,不在 Lean core——因为 Lean 已经被 5a 验证过,Python orchestration 也被 5a 验证过。新出现的任何问题一定来自 observer 或 executor 的真实实现。这是先做 5a 再做 5b 的好处——它把 bug 定位的范围缩到了一个层。

完成 Layer 5b 之后,Veritas 进入"挂着跑"阶段,目标是连续运行 14 天 + 完成 20 笔真实 testnet 交易。这一步达成后,v0.1 的完成标准第一条满足,可以开始准备公开发布。

---

## 决策原则

任何时候面临"加这个功能吗"的取舍,回到这两条:

> 1. **这个改动能让 agent 更好地知道自己在赌什么、更好地监控赌注是否还成立、或者更好地从错误中学习吗?**
> 2. **这个改动是在 Lean 核心里还是 Python 壳里?如果在 Python 里,它是不是真的只涉及 I/O?如果不是,把它推到 Lean 里**。

两条都是 → 做。其中一条不是 → 不做或重新设计。

---

## 后续路线图(不在本文档范围,仅作锚定)

**v0.2 — 多策略激活 Gate 1 和 Gate 3**

加入第二种策略(候选:基差套利 / 清算瀑布反向 / 永续-永续跨交易所价差)。重点不是策略本身的盈利能力,而是它的存在让 Gate 1 和 Gate 3 第一次有真实的验证对象。具体工作:

- 实现第二种策略的 `decide` 和 `extractAssumptions` Lean 函数
- 实现 `signal_consistency` 定理和 `portfolio_invariant` 定理(允许 sorry)
- 把 sizer 升级为 portfolio-aware 版本(考虑现有 position 的相关性)
- 探索将 `Float` 替换为可证明的数值类型(`Rat` 或 Mathlib `Real`),减少 rounding-dependent 公理
- 在 testnet 上跑双策略并发,验证两个 Gate 的形式化保证在实际运行中成立

**v0.3 — 假设库的 oracle 化**

把假设库的每个 entry 关联到一个 Lean 定理的 hash,建立 Lean 到自然语言的可验证映射。这是 Veritas 从 "trading agent" 演化成 "trust infrastructure" 的第一步——假设库不再只是内部数据结构,而是一个可被外部 agent 查询的信任凭证 registry。

- 假设库 schema 改造:每个 assumption 加 `lean_theorem_path` 和 `lean_theorem_hash` 字段
- 第一批 ZK certificate 实验(可能用 SP1 或 RISC Zero 包装核心 sizer 函数)
- 把假设库以 read-only API 形式暴露,任何外部程序可查

**v0.4 — Trust infrastructure 公开化**

把假设库 + 定理 registry 暴露成一个公开服务(可以是链上 contract,可以是 IPFS 内容寻址,可以是 federated registry)。任何外部 agent 可以查询"这个假设的可靠度是什么、对应的 Lean 定理是什么、证明状态如何"。Veritas 第一次从一个 agent 变成一个 protocol。

**v0.5+ — 跨策略、跨资产类别、跨 agent 的扩展**

支持 Hyperliquid HIP-3 的 tradfi perps(GOLD、S&P500、OIL)。支持 HIP-4 prediction markets。与 Eigen Labs / Certora / Lean FRO 建立合作层。开始接触机构用户。

v0.2 的设计等 v0.1 四条完成标准都达成那一刻再开始想。现在不想。

---

## 哲学注脚

Veritas 不是"加了 Lean 的 trading bot",是"Lean-native 的金融决策系统,恰好第一个应用是 trading"。这个顺序关系不能颠倒,否则整个定位会滑回"又一个用形式化装饰的交易工具",失去 trust infrastructure 的核心价值。

每次写代码时在心里问一遍: **"如果我只有 Lean,这段逻辑会长什么样?"** 如果答案是"它在 Lean 里更自然",那它就应该在 Lean 里,不管实现的短期代价有多大。

这是 v0.1 的全部方法论。
