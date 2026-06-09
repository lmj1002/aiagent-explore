# Harness Engineering（驾驭工程）深度解析

> 本文档梳理 OpenAI 官方文章《Harness Engineering: Leveraging Codex in an Agent-First World》的核心内容，并整合 Anthropic、LangChain 等机构的实践，全面解读 AI 时代的第四层工程范式。

---

## 一、什么是 Harness Engineering？

### 1.1 AI 工程化四层链条

Harness Engineering（驾驭工程）位于 AI 工程化链条的**最顶层**：

| 层级 | 名称 | 解决问题 | 核心关注 |
|------|------|----------|----------|
| **L1** | 提示词工程 (Prompt Engineering) | "怎么说清楚" | 指令表达、角色设定、输出格式 |
| **L2** | 上下文工程 (Context Engineering) | "喂给模型什么" | 消息历史、外部数据、长期记忆 |
| **L3** | 智能体工程 (Agent Engineering) | "怎么让模型动起来" | 模型、工具、记忆、护栏、控制流编排 |
| **L4** | **驾驭工程 (Harness Engineering)** | **"制度化执行环境"** | **契约、权限、回滚、审计、熵控制** |

### 1.2 核心定义

> **Harness Engineering 不是把提示词写长，而是围绕高自治 AI 模型构建整套可持续执行环境。**

它是对前三层的"上卷和封装"，处于工程实践的"操作系统层"。核心公式：

```
Agent = Model + Harness
```

Harness 是模型之外的一切：系统提示、工具与技能描述、基础设施（文件系统、沙箱、浏览器）、编排逻辑（子智能体调度、交接、模型路由）、Hooks/中间件（压缩、续接、Linting）等。

### 1.3 传统方式 vs 驾驭工程

| 维度 | 传统方式 | 驾驭工程 |
|------|----------|----------|
| 关注点 | 单次对话质量 | 可持续执行环境 |
| 知识库 | 大 Prompt | 版本化文档仓库 |
| 验证 | 人工检查 | 机器可验证契约 |
| 状态管理 | 聊天窗口 | System of Record |
| 回滚机制 | 无 | Git 回滚点 |
| 人类角色 | 代码编写者 | 环境设计者 / 指挥者 |

---

## 二、OpenAI 核心实验：百万行代码，零人工编写

### 2.1 实验概览

2025 年 8 月，OpenAI 团队启动了一项激进实验：**完全由 AI 智能体编写代码，构建并维护一个百万行代码的软件产品**。

| 维度 | 数据 |
|------|------|
| **时间跨度** | 2025年8月 → 2026年1月（5个月） |
| **团队规模** | 起步3人，扩展至7人 |
| **代码量** | ~100万行（含应用逻辑、测试、CI配置、文档） |
| **人工编写** | **0行（硬性规定）** |
| **PR 合并数** | ~1500个 |
| **日吞吐量** | 3.5 PR/人/天（后期优化至 5-10） |
| **Token 消耗** | ~10亿 token/天 |
| **产品形态** | 基于 Electron 的内部 Beta 应用，部署至数百用户 |

### 2.2 关键发现

- **单次 Codex 运行可持续 6 小时以上**，经常在人类睡觉时自主工作
- **所有代码、测试、CI 配置、文档、内部工具均由 Agent 生成**，包括 `AGENTS.md` 指南本身
- **人类角色彻底转变**：从"编写者"变为"设计者"和"指挥者"
- **核心洞察**："人类掌舵，智能体执行"——这已是"已经发生的现实"

---

## 三、Harness Engineering 六大核心部件

### 3.1 机器可验证的完成契约（Completion Contract）

> "Done"不是漂亮的回答，而是可验证的完成。

**核心原则：**
- 契约必须包含：输出格式、工具使用清单、停止条件、验收方法
- 每个 Sprint 前与评估者协商"Sprint 契约"，明确"完成"的定义
- 评估者根据契约标准评分，而非主观判断

**反模式：** 让主 Agent 自证完成。证据必须来自外部世界（测试结果、指标变化）。

### 3.2 Durable Knowledge 的 System of Record

> 知识必须离开聊天窗口，进入可发现、可维护、可验证的记录系统。

**错误做法：**
- 1000页的 `AGENTS.md`（挤占情境窗口、造成"指令腐化"、稀释注意力）
- 知识散落在 Slack、Google Docs、人脑中（对 Agent 来说"不存在"）

**正确做法：**
- `AGENTS.md` 精简为约 **100行的内容目录**，指向结构化的 `docs/` 目录
- **文档即代码**：所有知识版本化存储在代码仓库中
- 运行 **doc-gardening 智能体**：周期性后台 Agent 扫描过时文档，自动提交修复 PR
- 架构决策记录（ADR）写入仓库

### 3.3 真正的感官与手脚（Senses & Actuators）

> Agent 不能只读代码，必须能读 UI、看日志、跑测试。

**OpenAI/Anthropic 实践能力清单：**

| 能力 | 工具/方式 | 用途 |
|------|-----------|------|
| 读取 UI | Chrome DevTools Protocol（截屏、DOM快照、导航） | 视觉验证、UI Bug 复现 |
| 查看日志 | LogQL（Loki） | 运行时错误排查 |
| 查询指标 | PromQL（Prometheus） | 性能回归检测 |
| 分布式追踪 | OpenTelemetry | 链路分析 |
| 运行测试 | 自动化测试套件 | 回归验证 |

**典型闭环：** Agent 可独立完成"重现 Bug → 录制视频 → 修复 → 验证 → 提交 PR → 合并"全流程。

每个 Agent 工作树获得**临时的、隔离的可观测性堆栈**——任务完成后销毁。

### 3.4 长时程失忆的解决方案（Long-Running Memory）

> 不能只靠大上下文硬扛。模型在长任务中会失去连贯性，出现"上下文焦虑"导致过早结束工作。

**核心问题：**
- 单次对话窗口有限
- "上下文焦虑"（Context Anxiety）：接近上下文上限时过早声称完成
- "一次搞定"失败模式（One-shot Failure）：试图一次做完所有事，耗尽上下文

**解决方案矩阵：**

| 机制 | 作用 |
|------|------|
| **进度文件** (progress.json) | 记录当前状态、已完成/待完成特性 |
| **Git 回滚点** | 状态可恢复、可交接、可继续 |
| **上下文重置** (Clean Slate) | 新会话从结构化 handoff 开始，比 compaction 更有效 |
| **描述性 Commit Message** | Git 日志作为跨会话交接机制 |

**Anthropic 双重智能体架构：**

```
Initializer Agent（初始化智能体）
    │  搭建环境、编写特性列表(JSON)、init.sh、进度文件、初始提交
    │
    ▼
Coding Agent（编码智能体）
    │  一次只处理一个特性，读取进度文件 + Git 日志
    │  使用描述性 commit message 作为会话间交接
```

### 3.5 外置验证回路（External Verification Loop）

> 不能让主 Agent 既当运动员又当裁判。

**Anthropic 三智能体架构：**

```
Planner（规划者）          Generator（生成者）          Evaluator（评估者）
    │                          │                            │
    │  将1-4句话的提示词        │  一次实现一个特性           │  使用 Playwright MCP
    │  扩展为完整规格书         │  自我评估                   │  像真实用户一样测试应用
    │                          │                            │  对照硬性阈值评分
    │                          │                            │
    └──────────────────────────┴────────────────────────────┘
                                │
                    效果：同样 Prompt + 同样模型 → 20x 提升
```

**关键原则：** 验证证据必须来自外部世界——测试结果、指标变化、UI 截图对比，而非 Agent 的口头声明。

### 3.6 边界、沙箱与熵控制（Boundaries, Sandbox & Entropy Control）

> 完全自治的 Agent 倾向于复制现有模式——包括坏的模式 → 代码库熵增。

**OpenAI 的机械化约束实践：**

**强制分层架构：**
```
Types → Config → Repo → Service → Runtime → UI
```
依赖方向严格限制，横切关注点通过 Providers 接口进入。

**自定义 Linter + CI 强制：**
- 依赖方向由自定义 Linter 验证（也是 Agent 写的）
- Linter 的错误消息**包含修复指令**——创造 Agent 自我纠正的反馈回路
- CI 作业自动拦截违规

**"黄金规则"系统 + 垃圾回收：**
- 周期性后台 Codex 任务扫描偏离规范的模式
- 更新代码质量评分
- 自动开启重构 PR
- 类似操作系统层面的 GC（垃圾回收）

> "AI 生成的代码不需要看起来漂亮；它需要正确且对 Agent 可读。"

---

## 四、七种反模式与陷阱

### 4.1 反模式一：把大长 Prompt 当 Harness

| 错误认知 | 真相 |
|----------|------|
| 长 Prompt = 驾驭工程 | 长 Prompt 只是入口，不是知识库本体 |
| Prompt 越详细越好 | 过长 Prompt 挤占上下文、稀释注意力 |

**正确做法：** 精简入口 Prompt，知识库进入版本化文档仓库，文档即代码。

### 4.2 反模式二：层级混淆

| 错误认知 | 真相 |
|----------|------|
| 把 Workflow 叫 Agent | 四层有明确边界，混淆导致预期和评测错位 |
| 把 Agent 叫 Harness | 需要根据层级设定正确的评测指标 |

**正确做法：** 明确 L1-L4 四层定位，在正确的层级使用正确的工具和指标。

### 4.3 反模式三：工具越多越好

| 错误认知 | 真相 |
|----------|------|
| 工具多 = 能力强 | 工具过多提高选择噪声，降低可靠性 |

**正确做法：** 追求精简和边界清晰，工具与任务匹配，定期清理无用工具。

### 4.4 反模式四：过早追求完全自治

| 错误认知 | 真相 |
|----------|------|
| 一开始就上全自动 | 高风险场景需要渐进式放权 |

**正确做法：** 采用"Agent 预处理 + 人类放行"模式，逐步提升自治级别，高风险场景保留人类裁决权。

### 4.5 反模式五：让主 Agent 自证完成

| 错误认知 | 真相 |
|----------|------|
| Agent 说完成就是完成 | Agent 的口头声明不可靠 |

**正确做法：** 证据必须来自外部世界，建立外置验证回路。

### 4.6 反模式六：无回滚点修改状态

| 错误认知 | 真相 |
|----------|------|
| 一次就能做对 | 长时运行系统必有失误，需要恢复机制 |

**正确做法：** 预设 Git 回滚点，进度文件记录状态，状态可恢复、可交接、可继续。

### 4.7 反模式七：越复杂越先进

| 错误认知 | 真相 |
|----------|------|
| 架构越复杂越厉害 | 简单结构往往更稳健 |

**正确做法：** 从最小闭环开始，逐步迭代，避免过度工程。

---

## 五、OpenAI 的五大核心原则

OpenAI 在文章中总结了 Harness Engineering 的五条指导原则：

### 原则一：知识必须是仓库原生的（Knowledge Must Be Repository-Native）

Agent 无法访问的知识（Slack、Google Docs、人脑中的隐性知识）对其而言"不存在"。将所有知识推入版本控制的代码仓库。

### 原则二：修 Harness，不修 Prompt（Fix the Harness, Not the Prompt）

当 Agent 反复犯同样的错误时，不要试图写更长的 Prompt 来"说服"它。问自己：**"缺少什么能力？"** 然后通过工具、约束、验证回路来提供该能力。

### 原则三：机械约束优于叙述性指导（Mechanical Constraints > Narrative Guidance）

Agent 遵循规则的能力远不如遵循硬约束。用自定义 Linter、类型系统、CI 检查来强制约束，而不是指望 Prompt 中的文字描述。

### 原则四：可观测性是第一公民（Observability as a First-Class Citizen）

Agent 需要能看到自己的行为后果。投入建设日志、指标、追踪的完整链条，让 Agent 能够查询和利用这些数据。

### 原则五：文档有生命周期（Documentation Has a Lifecycle）

文档会腐化。建立自动化机制（doc-gardening agent）持续检查文档新鲜度，自动修复或标记过时内容。

---

## 六、Multi-Agent 编排：OpenAI 的"Symphony"

### 6.1 架构概览

OpenAI 构建了名为 **"Symphony"** 的多智能体编排系统：

- **技术选型**：**Elixir**（由模型自己选择，基于 BEAM 的进程监督能力）
- **核心理念**：将人类从终端中完全移除
- **覆盖范围**：代码编写 → Agent 审查 → CI 管理 → 合并冲突解决 → 合并到主分支

### 6.2 人类角色的极简化

在 Symphony 系统中，人类角色被缩减为**二元的合并决策**：
- ✅ 可合并
- ❌ 不可合并

这标志着从"人类审查每一行代码"到"人类只在关键节点决策"的根本转变。

### 6.3 Anthropic 的实践对比

| 维度 | OpenAI (Symphony) | Anthropic |
|------|-------------------|-----------|
| **架构** | Elixir + BEAM 进程监督 | 双重/三重智能体分工 |
| **人类角色** | 二元合并决策 | 需求定义 + 最终验收 |
| **特点** | 全流程自动化，包括 CI 管理和冲突解决 | 结构化 Handoff，Git 作为状态交接机制 |
| **适合场景** | 大规模持续开发 | 特性级增量开发 |

---

## 七、LangChain 的组件化 Harness 模型

LangChain 将 Harness 定义为以下组件的组合：

```
Agent = Model + Harness

Harness =
    System Prompts
  + Tools / Skills / MCP+ 及其描述
  + 内嵌基础设施（文件系统、沙箱、浏览器）
  + 编排逻辑（子智能体调度、交接、模型路由）
  + Hooks / 中间件（压缩、续接、Linting 等确定性执行）
```

**关键洞察：** Harness 的质量直接决定了 Agent 能力的上限——相同的模型，更好的 Harness 可以带来 **20倍的性能提升**。

---

## 八、工程师角色的根本转变

### 8.1 从"表达者"到"设计者"

| 维度 | 过去 | 现在 |
|------|------|------|
| **核心工作** | 编写具体的 Prompt | 定义系统行为、验收标准和治理规则 |
| **角色定位** | "表达者"（告诉 AI 做什么） | "设计者"（设计执行环境） |
| **产出物** | 代码行 | 契约、约束、反馈回路 |
| **技能重心** | 编程语言熟练度 | 系统设计、产品定义、约束建模 |

### 8.2 行业瓶颈的转移

```
过去瓶颈：模型能力不足 → 让 AI 多做点
现在瓶颈：人类 QA 成为瓶颈 → 人类注意力成为稀缺资源
```

系统设计的新目标：**让人只在高杠杆节点出手。**

### 8.3 新的核心竞争力

真正稀缺的不再是模型能力，而是：

- **产品定义能力**：清晰地描述"完成"是什么
- **工程构建能力**：搭建 Harness 基础设施
- **治理合规能力**：设计约束和边界条件
- **运营维护协同能力**：管理 Agent 军团的日常运转

---

## 九、落地路线参考

### 9.1 五级成熟度模型

| 级别 | 名称 | 特征 |
|------|------|------|
| **L1** | 演示型使用 | 单点任务，人工全程介入 |
| **L2** | 辅助型使用 | Agent 预处理，人类放行 |
| **L3** | 半自动驾驶 | 特定场景完全自治 |
| **L4** | 高度自动驾驶 | 多场景自治，人类监督 |
| **L5** | 智能共生 | 人机协同，智能体自主决策 |

### 9.2 30/60/90 天推进法

| 阶段 | 目标 | 关键动作 |
|------|------|----------|
| **前30天** | 单 Agent 最小闭环 | 跑通任务切片，建立基础契约，验证可行性 |
| **31-60天** | 加状态、回退、接管阈值 | 实现100次稳定完成，建立外置验证回路，定义人工接管阈值 |
| **90天后** | 扩展至多 Agent 协同 | 关注系统级经营指标，多 Agent 协同，持续优化熵控制 |

### 9.3 核心指标

| 指标 | 说明 | 目标 |
|------|------|------|
| 高频场景完成率 | 核心任务完成比例 | ≥90% |
| 异常率 | 需要人工介入的比例 | ≤10% |
| 人工接管率 | 人类接管任务比例 | ≤5% |
| 夜间无人值守比例 | 自动化运行比例 | ≥80% |
| 恢复时长 | 从异常到恢复的时间 | ≤30分钟 |

---

## 十、总结

### 核心判断

> **Harness Engineering 的核心在于将人类判断制度化。**

它不是在 Prompt 上修修补补，而是为 AI Agent 构建一整套**可靠的、可验证的、可持续的**执行环境。这包括：

- **知识系统**：结构化的 System of Record，而非巨大的 Prompt
- **约束系统**：机械化的 Linter / CI / 类型检查，而非叙述性指导
- **验证系统**：外置评估者 + 外部证据，而非 Agent 自证
- **恢复系统**：Git 回滚点 + 进度文件，而非一次性尝试
- **观测系统**：全链路可观测性，让 Agent 能看到自己的行为后果
- **熵控系统**：黄金规则 + 后台 GC Agent，防止代码库腐化

### 行业共识

OpenAI、Anthropic、LangChain 三家的实践方向高度一致：**瓶颈已从模型能力转移到人类注意力。** Harness Engineering 是这个新现实的工程回应——人类不再是操作者，而是约束设计者和最终决策者。

---

## 参考来源

### OpenAI 官方

- [OpenAI: Harness Engineering — Leveraging Codex in an Agent-First World（核心文章）](https://openai.com/index/harness-engineering/)
- [OpenAI Cookbook: Build an Agent Improvement Loop with Traces, Evals, and Codex](https://developers.openai.com/cookbook/examples/agents_sdk/agent_improvement_loop)
- [OpenAI Build Hour: API & Codex — Agent Legibility Score & Harness Techniques](https://beta.podwise.ai/episodes/7520471)
- [InfoQ: OpenAI Begins Article Series on Codex CLI Internals](https://www.infoq.com/news/2026/02/codex-agent-loop/)
- [OpenAI Codex 官方文档](https://developers.openai.com/codex)

### Anthropic 官方

- [Anthropic: Harness Design for Long-Running Application Development（核心文章）](https://www.anthropic.com/engineering/harness-design-long-running-apps)
- [Anthropic 的 Harness 工程架构演进（阿里云解读）](https://developer.aliyun.com/article/1724413)
- [Anthropic 的 Harness 启示：当 AI Agent 开始长跑，架构才是真正的天花板（腾讯云解读）](https://cloud.tencent.com.cn/developer/article/2649399)
- [[译] Harness——用于长时运行应用的智能体框架设计（腾讯云翻译）](https://cloud.tencent.com.cn/developer/article/2647128)

### LangChain 官方

- [LangChain: Improving Deep Agents with Harness Engineering](https://www.langchain.com/blog/improving-deep-agents-with-harness-engineering)
- [LangChain: How to Build a Custom Agent Harness](https://www.langchain.com/blog/how-to-build-a-custom-agent-harness)
- [LangChain: How Middleware Lets You Customize Your Agent Harness](https://www.langchain.com/blog/how-middleware-lets-you-customize-your-agent-harness)
- [Sequoia Podcast: Harrison Chase — Context Engineering Our Way to Long-Horizon Agents](https://sequoiacap.com/podcast/context-engineering-our-way-to-long-horizon-agents-langchains-harrison-chase/)
- [ZenML: Building Production-Ready AI Agents Through Harness Engineering and Continual Learning](https://www.zenml.io/llmops-database/building-production-ready-ai-agents-through-harness-engineering-and-continual-learning)
- [ZenML: Evolution from Context Engineering to Harness Engineering](https://www.zenml.io/llmops-database/evolution-from-context-engineering-to-harness-engineering-philosophical-and-practical-approaches-to-building-production-llm-systems)

### 社区与综合解读

- [O'Reilly: Agent Harness Engineering](https://www.oreilly.com/radar/agent-harness-engineering/)
- [Arize: Agent Harnesses Have an Expiration Date](https://arize.com/blog/harnesses-have-an-expiration-date/)
- [GitHub: harness-engineering-skill（Agent Harness 工程化模板）](https://github.com/jonzarecki/harness-engineering-skill)
- [Dev.to: Harness Engineering for AI Code Review — How OpenAI, Anthropic, and HumanLayer Control Agent-to-Agent Review](https://dev.to/kenimo49/harness-engineering-for-ai-code-review-how-openai-anthropic-and-humanlayer-control-3f5h)
- [Emil Sit: OpenAI Harness Engineering 笔记](https://www.emilsit.net/t/2026/02/openai-harness-engineering/)
- [腾讯云：5个月100万行代码，0行人工编写——解读AI驾驭工程](https://cloud.tencent.com.cn/developer/article/2656470)
- [阿里云开发者社区：一些 Harness Engineering 的实践](https://developer.aliyun.com/article/1718179)
- [阿里云：Harness Engineering 被讲烂之后，Agent 工程真正难的是什么？](https://developer.aliyun.com/article/1735765)
- [36氪：OpenAI 也把工程师经验"蒸馏"进 skill 了](https://36kr.com/p/3765104802349574)
- [澎湃新闻：程序员不许写代码！OpenAI硬核实验](https://www.thepaper.cn/newsdetail_forward_32618365)
- [ZenML: Extreme Harness Engineering — Building Production Software with Zero Human-Written Code](https://www.zenml.io/llmops-database/extreme-harness-engineering-building-production-software-with-zero-human-written-code)
- [ZenML: Harness Engineering for Agentic Coding Systems](https://www.zenml.io/llmops-database/harness-engineering-for-agentic-coding-systems)
