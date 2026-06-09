# Claude Code Workflow + Ultracode 深度解析

> 本文档介绍 Claude Code 中 Ultracode 模式与 Workflow（工作流）工具的定义、关系、架构设计及典型应用场景。

---

## 一、概念辨析：Ultracode vs Workflow

很多用户第一次接触时会混淆这两个概念。一句话区分：

> **Ultracode** 是"开关"（策略层），**Workflow** 是"引擎"（机制层）。

| 维度 | Ultracode | Workflow |
|------|-----------|----------|
| **本质** | 会话级运行模式 / 策略开关 | 多智能体编排工具 / 执行引擎 |
| **作用** | 控制"是否默认使用多智能体" | 提供编排能力（脚本、并发、验证） |
| **触发方式** | 用户在 prompt 中包含 `ultracode` 关键字，或会话全局开启 | 调用 `Workflow` 工具，传入编排脚本 |
| **类比** | 汽车的"运动模式" | 汽车的"发动机" |
| **依赖关系** | 依赖 Workflow 工具来实现其能力 | 可独立使用，不依赖 Ultracode 开启 |

### 两者关系图

```
Ultracode 模式 (策略层)
    │
    │  开启后，"对于每个实质性任务默认使用 Workflow"
    │
    ▼
Workflow 工具 (机制层)
    │
    │  提供 pipeline() / parallel() / agent() 等编排原语
    │
    ▼
子智能体军团 (执行层)
    │
    │  数十个 Agent 并行/流水线执行具体子任务
    │
    ▼
结果汇总 → 对抗验证 → 最终输出
```

---

## 二、Ultracode 详解

### 2.1 什么是 Ultracode？

Ultracode 是 Claude Code 的**全速多智能体模式**。当该模式激活时，系统的行为准则从"能用单智能体就用单智能体"转变为"每个实质性任务都默认编排多智能体军团"。

### 2.2 核心特征

| 特征 | 普通模式 | Ultracode 模式 |
|------|----------|----------------|
| **编排策略** | 需要用户明确要求才使用 Workflow | 每个实质性任务自动使用 Workflow |
| **Token 约束** | 默认节俭，避免过度消耗 | 移除 token 约束，追求最详尽、最正确的答案 |
| **验证深度** | 单次回答，自检为主 | 多智能体对抗验证、多视角审查 |
| **适用场景** | 日常问答、简单编辑 | 深度分析、大规模重构、安全审计、研究调研 |

### 2.3 如何启用 Ultracode

**方式一：关键字触发（单次）**

在 prompt 中包含 `ultracode` 关键字，该轮对话将激活 Ultracode 模式：

```
帮我审计这个项目的安全漏洞，ultracode
```

**方式二：会话全局开启**

通过设置让 Ultracode 在整个会话中持续生效（由系统提示中的 `ultracode` 开关控制）。

### 2.4 Ultracode 的行为变化

当 Ultracode 开启时，Claude Code 会发生以下行为变化：

1. **默认编排**：对于任何非简单编辑的任务，自动编写 Workflow 脚本进行多智能体编排
2. **深度优先**：不满足于表面答案，持续追问"还有什么遗漏？"
3. **对抗验证**：关键发现必须经过多个独立智能体验证
4. **多阶段展开**：复杂任务自动拆分为 Understand → Design → Implement → Review 多阶段 Workflow
5. **预算无上限**：不再因为 token 消耗而提前终止深度分析

### 2.5 何时使用 Ultracode

- ✅ 安全审计 / 代码审查需要高置信度
- ✅ 大规模代码迁移或重构
- ✅ 需要多角度分析的复杂技术决策
- ✅ 学术级深度调研
- ❌ 简单的一行修复或拼写纠正
- ❌ 已知答案的确认性问题
- ❌ 轻量级的文件浏览

---

## 三、Workflow 详解

### 3.1 什么是 Workflow？

Workflow 是一个**确定性的多智能体编排工具**。它通过一段 **JavaScript 脚本**精确控制多个 AI 子智能体的协作方式：

- 哪些任务**并行**执行
- 哪些任务**流水线化**处理
- 何时**收集结果**、何时做**下一步决策**

> 本质上是 **用代码编排 AI 智能体军团**，而非让模型自己猜测如何分工。

### 与普通 Agent 调用的区别

| 方式 | 控制流 | 并发 | 容错 | 可复现 |
|------|--------|------|------|--------|
| 普通 Agent | 模型自行决定 | 手动并行 | 依赖模型判断 | 低 |
| Workflow 脚本 | 脚本精确控制 | Pipeline/Parallel 自动管理 | 脚本定义的验证逻辑 | 高（支持缓存断点续跑） |

### 3.2 Workflow 的组成结构

每个 Workflow 脚本是一个标准的 JavaScript 文件，由以下核心元素构成：

```
┌─────────────────────────────────────────┐
│  export const meta = {...}              │  ← 元数据（必需）
│  // 名称、描述、阶段定义                   │
├─────────────────────────────────────────┤
│  phase('阶段名')                         │  ← 阶段分组（可选）
│  log('进度消息')                         │  ← 日志输出
├─────────────────────────────────────────┤
│  agent(prompt, opts)                    │  ← 子智能体调用（核心）
│  pipeline(items, stage1, stage2, ...)   │  ← 流水线并行
│  parallel(thunks)                       │  ← 屏障式并行
│  workflow(name, args)                   │  ← 嵌套子 Workflow
├─────────────────────────────────────────┤
│  budget.total / budget.remaining()      │  ← Token 预算感知
│  args                                   │  ← 外部传入参数
└─────────────────────────────────────────┘
```

### 3.3 如何编写一个 Workflow 脚本

**最小可运行示例：**

```javascript
export const meta = {
  name: 'hello-workflow',
  description: '我的第一个 Workflow — 并行审查两个文件',
  phases: [
    { title: '审查', detail: '并行审查代码文件' },
  ],
}

phase('审查')

const results = await parallel([
  () => agent('审查 src/utils.js 中的错误处理是否完善',
    { label: '审查 utils.js' }),
  () => agent('审查 src/api.js 中的边界条件处理',
    { label: '审查 api.js' }),
])

const findings = results
  .filter(Boolean)         // 过滤失败的调用
  .flatMap(r => r.findings || [])

log(`共发现 ${findings.length} 个问题`)
return { findings }
```

**脚本 API 速查表：**

| API | 签名 | 说明 |
|-----|------|------|
| `agent(prompt, opts?)` | `(string, object?) => Promise<any>` | 启动一个子智能体。配合 `schema` 参数返回结构化数据 |
| `pipeline(items, ...stages)` | `(T[], ...(Function)[]) => Promise<any[]>` | 每个 item 独立流经所有阶段，无屏障 |
| `parallel(thunks)` | `(() => Promise<any>)[] => Promise<any[]>` | 并发执行所有任务，等待全部完成后返回 |
| `phase(title)` | `(string) => void` | 标记一个新阶段（影响进度显示） |
| `log(message)` | `(string) => void` | 向用户输出进度日志 |
| `workflow(name, args?)` | `(string, any?) => Promise<any>` | 嵌套调用另一个 Workflow |
| `budget.total` | `number \| null` | 用户设定的 token 上限 |
| `budget.remaining()` | `() => number` | 剩余可用 token 数 |
| `args` | `any` | 外部传入的参数（通过 Workflow 工具的 `args` 字段） |

### 3.4 如何调用 Workflow

**方式一：通过 Workflow 工具直接调用（内联脚本）**

在对话中直接使用 `Workflow` 工具，将脚本以字符串形式传入 `script` 参数：

```
用户: 审查 src/ 目录下所有文件的安全性，ultracode
```

Claude Code 会自动生成并执行 Workflow 脚本。

**方式二：通过 Workflow 工具调用（脚本文件路径）**

```javascript
// 先使用 Write 工具将脚本写入磁盘
// 然后通过 Workflow 工具的 scriptPath 参数调用
Workflow({ scriptPath: "F:\study\workflows\security-review.js" })
```

**方式三：在 Ultracode 模式下自动触发**

当 Ultracode 模式开启时，对于复杂任务 Claude Code 会自动编写和执行 Workflow 脚本，无需手动调用。

### 3.5 agent() 的参数选项详解

```javascript
const result = await agent('分析这段代码的性能瓶颈', {
  // 显示标签（在进度树中展示）
  label: '性能分析',

  // 归属阶段（用于进度分组）
  phase: 'Review',

  // 结构化输出 Schema（返回验证过的 JSON 对象）
  schema: {
    type: 'object',
    properties: {
      issues: { type: 'array', items: { type: 'object' } },
      score: { type: 'number' }
    },
    required: ['issues', 'score']
  },

  // 模型覆盖（通常省略，继承父级模型）
  model: 'sonnet',  // 'sonnet' | 'opus' | 'haiku'

  // 工作树隔离（并行修改文件时避免冲突）
  isolation: 'worktree',

  // 自定义子智能体类型
  agentType: 'code-reviewer',
})
```

---

## 四、Workflow 核心优势

### 4.1 确定性执行，而非模型猜测

传统方式让模型自己决定"先做 A 再做 B"，模型可能遗漏步骤或走弯路。Workflow 由脚本精确控制执行流程：

```javascript
phase('Review')
const results = await pipeline(
  DIMENSIONS,
  d => agent(d.prompt, { phase: 'Review' }),
  review => parallel(review.findings.map(f => () =>
    agent(`Verify: ${f.title}`, { phase: 'Verify' })
  ))
)
```

### 4.2 Pipeline vs Parallel — 精妙的并发模型

这是 Workflow 最精妙的设计之一：

| 模式 | 行为 | 墙钟时间 | 适用场景 |
|------|------|----------|----------|
| **`pipeline()`** | 每个 item 独立流经所有阶段。Item A 在阶段3时，Item B 可能还在阶段1 — **无屏障** | = 最慢单条链的时间 | 大多数多阶段任务（**默认选择**） |
| **`parallel()`** | **屏障**：等待所有任务完成后才进入下一阶段 | = 各阶段最慢者之和 | 需要汇总全部结果才能做下一步决策 |

**关键洞察**：pipeline 中，一项任务的"代码审查"刚完成就能立即进入"验证"阶段，不必等其他维度的审查全部结束。这让整体吞吐量最大化。

```javascript
// Pipeline 示意：
// 时间轴 →
// Bug审查    ████████░░验证░░
// 安全审查        ████████████░░验证░░  ← 不等 bug 审查
// 性能审查            ██████░░验证░░
//                         ↑ 各自独立推进
```

### 4.3 对抗性验证（Adversarial Verify）

不是简单的"自查"，而是派出**多个独立怀疑者**试图**反驳**每个发现：

```
发现 → 派出 3 个独立智能体，各自从不同角度尝试反驳
     → 如果 ≥2 个成功反驳 → 丢弃该发现（大概率是误报）
     → 如果 ≥2 个无法反驳 → 保留（高置信度真实问题）
```

比单一自查可靠得多，大幅降低误报率。

```javascript
const votes = await parallel(
  Array.from({length: 3}, () => () =>
    agent(`Try to refute: ${claim}. Default to refuted=true if uncertain.`,
      { schema: VERDICT })
  )
)
const survives = votes.filter(Boolean).filter(v => !v.refuted).length >= 2
```

### 4.4 多视角验证（Perspective-Diverse Verify）

当一个问题可能以不同方式失败时，给每个验证者分配**不同的审查视角**：

| 验证者 | 视角 |
|--------|------|
| 验证者 A | 正确性（逻辑是否对） |
| 验证者 B | 安全性（是否有漏洞） |
| 验证者 C | 可复现性（能否稳定触发） |

不同视角覆盖的失败模式比 N 个相同视角的审查者更全面。

### 4.5 结构化输出（Structured Output）

每个子智能体可以返回**带 JSON Schema 验证**的结构化数据，而非自由文本：

```javascript
const bugs = await agent("Find bugs in this codebase", {
  schema: {
    type: "array",
    items: {
      type: "object",
      properties: {
        file: { type: "string" },
        line: { type: "number" },
        severity: { enum: ["low", "medium", "high"] },
        description: { type: "string" }
      },
      required: ["file", "line", "severity", "description"]
    }
  }
})
// bugs 已经是验证通过的 JavaScript 对象数组，无需手动解析
```

### 4.6 断点续跑与缓存

同一 workflow 脚本 + 相同参数 → **未修改的步骤直接命中缓存**，修改后的步骤才重新执行。迭代脚本时只需支付增量成本。

```
第一轮: [Scan] → [Review] → [Verify]    // 全部执行，建立缓存
第二轮: [Scan] → [Review*] → [Verify*]   // Scan 命中缓存，只跑修改后的步骤
```

### 4.7 Token 预算感知

Workflow 可以感知用户的 token 预算指令（如 `+500k`），动态调整并行规模和循环深度：

```javascript
// 根据预算决定搜索深度
const FLEET = budget.total ? Math.floor(budget.total / 100_000) : 5

// 或在预算范围内持续搜索
while (budget.total && budget.remaining() > 50_000) {
  const result = await agent("Search for more issues", { schema: BUG_SCHEMA })
  bugs.push(...result.bugs)
  log(`${bugs.length} found, ${Math.round(budget.remaining()/1000)}k remaining`)
}
```

### 4.8 Worktree 隔离

需要并行修改文件且可能冲突时，使用 `isolation: 'worktree'` 让每个子智能体在独立的工作树中操作：

```javascript
const results = await parallel(
  files.map(f => () =>
    agent(`Refactor ${f}`, { isolation: 'worktree' })
  )
)
```

---

## 五、核心编程模式

### 5.1 Loop-until-dry（搜索至收敛）

用于未知规模的发现型任务（bug 搜索、问题排查）：

```javascript
const seen = new Set(), confirmed = []
let dry = 0
while (dry < 2) {
  const found = await agent("Search for bugs", { schema: BUGS })
  const fresh = found.filter(b => !seen.has(key(b)))
  if (!fresh.length) { dry++; continue }
  dry = 0
  fresh.forEach(b => seen.add(key(b)))
  // 验证新鲜发现...
}
```

### 5.2 Judge Panel（评审面板）

生成 N 个独立方案，用并行评审评分，从最高分方案出发嫁接其他方案的优点：

```javascript
const plans = await parallel(
  APPROACHES.map(a => () => agent(a.prompt, { schema: PLAN }))
)
const scores = await parallel(
  plans.map(p => () => agent(`Score this plan: ${p}`, { schema: SCORE }))
)
```

### 5.3 Multi-modal Sweep（多模态扫描）

从不同搜索角度同时探索，每个角度都盲于其他角度发现的内容：

```javascript
const results = await parallel([
  () => agent("Search by container pattern"),
  () => agent("Search by content signature"),
  () => agent("Search by entity relationship"),
  () => agent("Search by time-based pattern"),
])
// 汇总去重 → 得到单角度搜索无法覆盖的全貌
```

### 5.4 Completeness Critic（完备性审查）

用一个最终智能体审查"还缺什么"：

```javascript
const gaps = await agent(
  `What's missing? Modality not run? Claim unverified? Source unread?`,
  { schema: GAPS }
)
// gaps 成为下一轮的工作清单
```

---

## 六、典型应用场景

### 6.1 多维度代码审查
```
         ┌→ 正确性审查 ──→ 验证
变更文件 ─┼→ 安全性审查 ──→ 验证
         └→ 性能审查   ──→ 验证
              ↓
         汇总确认报告
```
每个维度的审查一完成就进入验证，不阻塞其他维度。

### 6.2 Bug 狩猎（Loop-until-dry）
```
搜索 → 去重 → 多角度验证 → 确认 → 再搜索...
       ↑________________________________|
       直到连续 K 轮没有新发现
```

### 6.3 大规模代码迁移
```
扫描所有文件 → 按模块分组 → 并行转换（worktree 隔离）→ 汇总验证
```

### 6.4 学术/技术深度调研
```
         ┌→ 学术论文搜索
研究课题 ─┼→ 行业报告搜索
         └→ 代码仓库搜索
              ↓
         汇总去重 → 对抗性验证 → 生成引用报告
```

### 6.5 大型重构
```
         ┌→ 重构模块 A (worktree)
源码分析 ─┼→ 重构模块 B (worktree)
         └→ 重构模块 C (worktree)
              ↓
         回归验证 → 合并
```

---

## 七、最佳实践

1. **默认使用 `pipeline()`**：除非确实需要汇总全部中间结果，否则 pipeline 的并发效率更高
2. **对抗性验证至少 3 个独立审查者**：单审查者容易产生"确认偏误"
3. **用结构化输出替代自由文本**：子智能体返回 JSON Schema 验证的数据，避免解析错误
4. **善用 Loop-until-dry**：对于未知总量的发现型任务，不要预设固定次数
5. **设置 token 预算感知**：让 workflow 根据用户预算自动调整深度
6. **记住缓存特性**：迭代脚本时尽量保持前面的步骤不变，利用缓存加速

---

## 八、总结

Ultracode（策略开关）+ Workflow（执行引擎）的组合将 **"一个模型慢慢想"** 升级为 **"一个指挥官调度一支智能体军团"**。它保留了：

- **确定性** — 脚本控制流，不依赖模型猜测
- **可靠性** — 对抗验证 + 结构化输出 + 去重
- **效率** — Pipeline 并发 + 缓存复用 + 预算感知
- **可扩展性** — 从几个到上百个子智能体，同一套编程模型

这是目前 AI 辅助编程中最强大的任务编排能力，适合所有需要**深度、可靠、大规模**代码分析或生成的场景。
