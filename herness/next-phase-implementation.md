# 个人 AI 软件工程平台 — 下一阶段实施方案

> **文档用途**：本文档既是一份技术方案，也是一个可直接喂给 Claude Code 执行的提示词。
> 在远程服务器上，将本文档放到项目目录下，用 Claude Code 打开后按 Phase 顺序逐步执行即可。
>
> **前置条件**：
> - ✅ Hermes 已部署并连接微信
> - ✅ Claude Code 已安装可用
> - ✅ Git MCP / SearXNG MCP 已配置
> - ✅ 微信 → Hermes → Claude Code → Git Push 链路已打通
>
> **当前完成度**：约 40%（理解需求 → 修改代码 → Commit）
>
> **目标**：补齐剩下的 60%（规划 → 验证 → 评审 → PR → 部署 → 监控），构建完整的自主软件工程 Agent。

---

## 目录

1. [架构总览](#1-架构总览)
2. [Claude Code 多模型角色分工](#2-claude-code-多模型角色分工)
3. [Sandbox 沙盒隔离方案](#3-sandbox-沙盒隔离方案)
4. [开发流程规范化设计](#4-开发流程规范化设计)
5. [分阶段实施路线图](#5-分阶段实施路线图)
6. [Phase 1：基础工程设施（本周）](#6-phase-1基础工程设施)
7. [Phase 2：质量保障体系（下周）](#7-phase-2质量保障体系)
8. [Phase 3：智能增强层（第 3-4 周）](#8-phase-3智能增强层)
9. [Phase 4：DevOps 自动化（长期）](#9-phase-4devops-自动化)
10. [附录：Claude Code 配置模板](#10-附录claude-code-配置模板)

---

## 1. 架构总览

### 1.1 最终目标架构

```
微信
 ↓
Hermes（AI 操作系统层）
 ├── Session Manager      — 会话管理（多项目、多用户、多会话隔离）
 ├── Workspace Manager    — 工作区管理（prod/sandbox 分离）
 ├── Memory Manager       — 长期记忆（项目规范、业务规则、编码约定）
 ├── Permission Manager   — 权限控制（危险操作需微信确认）
 ├── Task Scheduler       — 任务调度（拆解 → 分配 → 追踪 → 汇总）
 └── Model Router         — 模型路由（按角色分派不同模型）
      ↓
MCP 工具层
 ├── Git MCP              — 版本控制（clone/push/branch/worktree）
 ├── SearXNG MCP          — 搜索能力
 ├── Sandbox MCP          — 沙盒管理（创建/销毁/同步）
 ├── Knowledge MCP        — 知识库读取
 ├── Deploy MCP           — 部署操作
 └── Monitor MCP          — 监控告警
      ↓
Claude Code Runtime（代码执行引擎层）
 ├── Planner   [GPT-5.5]        — 需求分析 & 任务拆解
 ├── Architect [Claude Sonnet*] — 架构设计 & 跨文件理解
 ├── Coder     [DeepSeek V4]    — 代码生成 & 批量修改
 ├── Tester    [DeepSeek V4]    — 测试执行 & 自动修复
 ├── Reviewer  [GPT-5.5]        — 代码审查 & 质量评分
 └── PR Agent  [GPT-5.5]        — PR 生成 & 变更说明
      ↓
Workspace 运行时层
 ├── prod-workspace/            — 正式工作区（只读基准）
 └── sandboxes/                 — 任务级隔离沙盒（可销毁）
      ├── task-{id}/            — git worktree per task
      └── ...
      ↓
Git → CI/CD → Server → Monitor → 微信通知
```

> `*` 标注的模型为后续接入，当前留占位符

### 1.2 职责分离原则

| 层级 | 角色 | 职责 | 比喻 |
|------|------|------|------|
| **Hermes** | AI 操作系统 | 连接微信、会话管理、工作区管理、任务调度、权限控制 | 技术经理 |
| **Claude Code** | 代码引擎 | 搜索代码、生成代码、执行测试、Git 操作 | 高级工程师 |
| **多模型** | 认知层 | 不同角色用不同模型，显式路由 | 不同级别的工程师 |
| **MCP** | 工具层 | 提供标准化的外部能力 | 工具链 |
| **Workspace** | 运行时 | 隔离执行、安全验证 | 办公环境 |

---

## 2. Claude Code 多模型角色分工

### 2.1 模型路由规则（显式路由，禁止 Agent 自选）

```
router:
  # ===== 规划类角色 → GPT-5.5 =====
  planner:
    model: gpt-5.5                    # 【占位符：替换为你的 GPT-5.5 模型 ID】
    description: "需求分析 & 任务拆解"
    capabilities:
      - 需求理解
      - 任务拆解
      - 上下文总结
      - 方案设计

  reviewer:
    model: gpt-5.5                    # 【占位符：替换为你的 GPT-5.5 模型 ID】
    description: "代码审查 & 质量评分"
    capabilities:
      - 架构审查
      - 安全审查
      - 性能审查
      - 规范审查

  pr_agent:
    model: gpt-5.5                    # 【占位符：替换为你的 GPT-5.5 模型 ID】
    description: "PR 生成 & 文档输出"
    capabilities:
      - PR 描述生成
      - 变更说明
      - 测试报告
      - 文档生成

  # ===== 执行类角色 → DeepSeek V4 Pro =====
  coder:
    model: deepseek-v4-pro            # 【占位符：替换为你的 DeepSeek 模型 ID】
    description: "代码生成 & 批量修改"
    capabilities:
      - 代码生成
      - 批量修改
      - SQL 生成
      - Shell 执行
      - 简单重构

  tester:
    model: deepseek-v4-pro            # 【占位符：替换为你的 DeepSeek 模型 ID】
    description: "测试执行 & 自动修复"
    capabilities:
      - 单元测试
      - 静态分析
      - 错误修复
      - 回归测试

  # ===== 架构类角色 → Claude Sonnet（待接入） =====
  architect:
    model: ""                         # 【占位符：待填入 Claude Sonnet 4/4.5 模型 ID】
    description: "架构设计 & Repository 理解"
    capabilities:
      - 跨文件理解
      - DDD 设计
      - 大型重构
      - Repository Reasoning
    status: "待接入"

  # ===== 扩展角色（预留） =====
  security_scanner:
    model: ""                         # 【占位符：待填入安全扫描专用模型 ID】
    description: "安全漏洞扫描"
    status: "待实现"

  docs_writer:
    model: gpt-5.5                    # 【占位符：可复用 GPT-5.5 模型 ID】
    description: "文档生成 & 知识库维护"
    status: "待实现"
```

### 2.2 为什么不用模型自动选择

| 自动选择 | 显式路由（推荐） |
|----------|-----------------|
| 简单 CRUD 可能错调 GPT-5.5，成本高 | 确定性的成本控制 |
| 复杂架构可能错调 DeepSeek，质量差 | 稳定的输出质量 |
| 同一输入两次结果不同，难以调优 | 可复现、可调优 |
| Agent 的"判断"本身可能出错 | 规则明确，不会出错 |

---

## 3. Sandbox 沙盒隔离方案

### 3.1 核心概念

```
Sandbox ≠ 一个单独的文件夹

Sandbox = 每个任务拥有独立、可销毁、可回滚、互不影响的执行环境
```

### 3.2 推荐方案：Git Worktree + Task Sandbox

这是为 AI Coding Agent 天然设计的方案，也是当前阶段最推荐的做法。

#### 目录结构

```
/ai-platform
├── workspaces/                        # 正式工作区（保持干净）
│   └── hyperf-project/
│       ├── source/                    # 主仓库（git worktree bare repo 或主分支）
│       ├── memory/                    # 项目记忆（知识库）
│       │   ├── architecture.md
│       │   ├── coding_style.md
│       │   ├── business_rules.md
│       │   ├── glossary.md
│       │   └── db_design.md
│       ├── metadata.yaml              # 项目元数据
│       └── graph/                     # 代码图谱（Phase 3）
│
├── sandboxes/                         # 任务级隔离沙盒
│   ├── task-1001/                     # git worktree: feature/task-1001
│   │   ├── ...（完整项目文件）
│   │   └── .sandbox-meta.yaml
│   ├── task-1002/                     # git worktree: feature/task-1002
│   └── ...
│
└── templates/                         # 沙盒模板 & 配置
    ├── sandbox-init.sh
    ├── sandbox-destroy.sh
    └── quality-gates.sh
```

#### 标准工作流

```
微信收到需求
     ↓
1. Hermes 创建 Task ID
     ↓
2. git worktree add sandboxes/task-{id} -b feature/task-{id}
     ↓
3. Claude Code 进入 Sandbox，修改代码
     ↓
4. 执行质量门禁（test → lint → review）
     ↓                          ↓
   通过                     不通过 → 自动修复 → 重新测试
     ↓                                        ↓  (最多3次)
5. git push origin feature/task-{id}      仍失败 → 微信通知
     ↓
6. git worktree remove sandboxes/task-{id}（销毁沙盒）
     ↓
7. 创建 PR（可选）
     ↓
8. 微信通知结果
```

### 3.3 沙盒方案对比

| 维度 | Level 1: 文件夹复制 | Level 2: Git Worktree（推荐） | Level 3: Docker 容器 |
|------|---------------------|------------------------------|----------------------|
| 实现难度 | ⭐ 极简 | ⭐⭐ 简单 | ⭐⭐⭐⭐ 复杂 |
| 磁盘占用 | 高（每次 clone） | 低（共享 .git） | 中 |
| 创建速度 | 慢（clone） | 快（秒级） | 中 |
| 隔离程度 | 弱 | 强（分支隔离） | 最强（进程/网络隔离） |
| 并发支持 | 差 | 好（天然多分支） | 最好 |
| 数据库隔离 | 无 | 无 | 有（独立 MySQL/Redis） |
| 适合阶段 | 现在 | **现在就可以上** | Phase 4 |

### 3.4 为什么不能直接在 Workspace 改

```
场景：
  Workspace 正在修改"消息中心"（改了 20 个文件，未提交）
  微信又来消息："修复登录 BUG"

如果共用 Workspace：
  → 消息中心修改一半 + 登录 BUG 修改
  → git 状态脏乱
  → Claude Code 可能 git add . 把两个需求一起提交
  → 回滚不了

Sandbox 方案：
  sandbox/task-1001 → 消息中心
  sandbox/task-1002 → 登录 BUG
  → 互不影响，各自独立提交
```

---

## 4. 开发流程规范化设计

### 4.1 完整 Agent Pipeline

将现有的 7 阶段 Issue → PR 流水线与 Hermes 远程工作流整合：

```
微信输入需求
     ↓
┌─────────────────────────────────────────────────┐
│ Phase A: 需求理解（GPT-5.5 Planner）             │
│  - 需求分析 & 澄清                              │
│  - 输出：需求摘要 + 验收标准                     │
└─────────────────────────────────────────────────┘
     ↓
┌─────────────────────────────────────────────────┐
│ Phase B: 任务拆解（GPT-5.5 Planner）             │
│  - 拆解为可执行子任务                           │
│  - 输出：Task List（每项含文件范围 + 验收条件）  │
└─────────────────────────────────────────────────┘
     ↓
┌─────────────────────────────────────────────────┐
│ Phase C: 架构设计（Architect — 复杂需求时启用） │
│  - DDD 设计 / 数据库变更 / API 设计             │
│  - 输出：技术方案（可选，简单需求跳过）          │
└─────────────────────────────────────────────────┘
     ↓
┌─────────────────────────────────────────────────┐
│ Phase D: 沙盒创建                               │
│  - git worktree add sandbox/task-{id}           │
│  - 读取项目 Memory（知识库）                    │
└─────────────────────────────────────────────────┘
     ↓
┌─────────────────────────────────────────────────┐
│ Phase E: 编码实现（DeepSeek Coder）              │
│  - 逐个执行 Task List                           │
│  - 每完成一个 Task，记录进度                    │
└─────────────────────────────────────────────────┘
     ↓
┌─────────────────────────────────────────────────┐
│ Phase F: 质量门禁（质量门）                      │
│  ┌───────────────────────────────────────────┐  │
│  │ F1: 自动测试（DeepSeek Tester）            │  │
│  │  - composer test / phpunit                 │  │
│  │  - phpstan / psalm                         │  │
│  │  - 失败 → 自动修复（最多 3 次循环）        │  │
│  │  - 3 次仍失败 → 微信通知 + 人工介入        │  │
│  └───────────────────────────────────────────┘  │
│       ↓                                         │
│  ┌───────────────────────────────────────────┐  │
│  │ F2: 代码审查（GPT-5.5 Reviewer）           │  │
│  │  - 架构合规检查                            │  │
│  │  - 安全检查（SQL 注入/XSS/Token 泄漏）     │  │
│  │  - 性能检查（N+1/Redis TTL/MQ 幂等）       │  │
│  │  - 规范检查（DDD/Hyperf 规范）             │  │
│  │  - 输出：Review Score + 问题列表           │  │
│  └───────────────────────────────────────────┘  │
│       ↓                                         │
│  ┌───────────────────────────────────────────┐  │
│  │ F3: 自动修复 Review 问题                   │  │
│  │  - 修复 → 重新 Review（最多 2 次循环）    │  │
│  └───────────────────────────────────────────┘  │
└─────────────────────────────────────────────────┘
     ↓
┌─────────────────────────────────────────────────┐
│ Phase G: 提交 & PR（Git MCP + PR Agent）         │
│  - git add + git commit                         │
│  - git push origin feature/task-{id}            │
│  - 生成 PR 描述                                 │
│  - gh pr create                                 │
└─────────────────────────────────────────────────┘
     ↓
┌─────────────────────────────────────────────────┐
│ Phase H: 清理 & 通知                             │
│  - 记录结果到 Memory                            │
│  - git worktree remove sandbox/task-{id}        │
│  - 微信通知：✅ 成功 / ❌ 失败                   │
└─────────────────────────────────────────────────┘
```

### 4.2 质量门禁指标

| 门禁 | 通过标准 | 失败处理 |
|------|----------|----------|
| 单元测试 | 全部 PASS | 自动修复 ≤3 次，仍失败则微信通知 |
| 静态分析 | phpstan level 5+ 无新增错误 | 自动修复 ≤2 次 |
| 安全审查 | 无高危/严重问题 | 必须人工确认 |
| 架构审查 | 无重大违规（如 Service 直接操作 DB） | 自动修复 ≤2 次 |
| 代码规范 | 符合 Hyperf 规范 | 自动修复 |

### 4.3 危险操作拦截清单

以下操作在 Sandbox 外执行时，必须通过微信二次确认：

| 操作 | 风险等级 | Sandbox 内 | Sandbox 外 |
|------|:--------:|------------|------------|
| `rm -rf` | 🔴 严重 | 允许 | **必须确认** |
| `DROP TABLE` / `TRUNCATE` | 🔴 严重 | 允许 | **必须确认** |
| `git push --force` | 🔴 严重 | 允许 | **必须确认** |
| `docker compose down -v` | 🔴 严重 | 允许 | **必须确认** |
| `git reset --hard` | 🟠 高 | 允许 | **必须确认** |
| `composer update`（大版本） | 🟡 中 | 允许 | 建议确认 |

---

## 5. 分阶段实施路线图

| 阶段 | 时间 | 主题 | 交付物 | 优先级 |
|------|------|------|--------|:------:|
| **Phase 1** | 本周 | 基础工程设施 | Workspace Manager / Project Memory / Sandbox | ⭐⭐⭐⭐⭐ |
| **Phase 2** | 下周 | 质量保障体系 | Tester / Reviewer / PR Agent / Auto Fix | ⭐⭐⭐⭐⭐ |
| **Phase 3** | 2 周 | 智能增强层 | Multi-Model Router / Knowledge MCP / Code Graph | ⭐⭐⭐⭐ |
| **Phase 4** | 长期 | DevOps 自动化 | Deploy Agent / Monitor / Incident Agent | ⭐⭐⭐ |

---

## 6. Phase 1：基础工程设施

> **目标**：建立安全的代码执行环境和标准化的项目记忆体系
>
> **时间**：1 周
>
> **交付物**：
> - [ ] Workspace Manager — 多项目管理
> - [ ] Project Memory — 项目知识库
> - [ ] Sandbox — Git Worktree 任务隔离
> - [ ] Task Planner — 需求自动拆解

### Step 1.1：创建统一工作区目录结构

```bash
# === 在远程服务器上执行 ===

# 创建顶层目录
mkdir -p /ai-platform/{workspaces,sandboxes,templates,logs}
mkdir -p /ai-platform/workspaces/.templates

# 验证
tree -L 2 /ai-platform
```

### Step 1.2：实现 Workspace Manager（项目元数据管理）

为每个项目创建 `metadata.yaml`：

```yaml
# /ai-platform/workspaces/{project-name}/metadata.yaml

project:
  name: "hyperf-project"                    # 【占位符：替换为实际项目名】
  description: ""                           # 【占位符：项目描述】
  remote: "git@github.com:xxx/xxx.git"      # 【占位符：替换为实际 Git 远程地址】
  language: "php"
  framework: "hyperf"
  version: "3.1"
  php_version: "8.2"
  default_branch: "main"

conventions:
  architecture: "DDD + Repository 模式"
  naming: "PSR-4"
  test_framework: "phpunit"
  static_analysis: ["phpstan", "psalm"]

contacts:
  owner: ""                                 # 【占位符：负责人】
  wechat_id: ""                             # 【占位符：微信 ID】

sandbox:
  strategy: "git-worktree"
  max_concurrent: 3
  auto_destroy_after_hours: 24
```

### Step 1.3：搭建 Project Memory（项目知识库）

为每个项目创建知识库目录。这是 AI 输出质量的**核心杠杆**：

```bash
# === 在远程服务器上执行 ===

# 创建项目知识库目录
mkdir -p /ai-platform/workspaces/{project-name}/memory

# 创建知识库文件模板
cat > /ai-platform/workspaces/{project-name}/memory/architecture.md << 'KBEOF'
# {项目名} 架构说明

## 技术栈
- PHP 8.2 + Hyperf 3.1
- MySQL 8.0
- Redis
- RabbitMQ / Kafka

## 分层架构

Controller → Service → Repository → Model → DB

## 关键设计决策
- (待补充) 为什么选了这些技术选型
- (待补充) 架构上的取舍

## 模块依赖图
(待补充：哪些模块依赖哪些模块)
KBEOF

cat > /ai-platform/workspaces/{project-name}/memory/coding_style.md << 'KBEOF'
# {项目名} 编码规范

## PHP 规范
- 严格遵循 PSR-4 / PSR-12
- 使用 PHP 8.2 特性（枚举、只读属性、Fibers）

## 命名规范
- Controller: {Feature}Controller
- Service: {Feature}Service
- Repository: {Feature}Repository
- DTO: {Feature}DTO / {Feature}Request
- Entity: {Feature}Entity

## 禁止事项
- ❌ Service 直接操作 Model（必须通过 Repository）
- ❌ Controller 包含业务逻辑
- ❌ 直接写 SQL（必须用 ORM / Repository）
- ❌ 硬编码配置值（必须走 Config）

## 推荐模式
- ✅ Repository 模式封装所有 DB 操作
- ✅ DTO 用于输入验证和类型安全
- ✅ 异常统一用 Hyperf 的异常体系
- ✅ Redis Key 必须设置 TTL
KBEOF

cat > /ai-platform/workspaces/{project-name}/memory/business_rules.md << 'KBEOF'
# {项目名} 业务规则

## 核心业务流程
(待补充：最重要的 5-10 条业务规则)

## 业务术语表
(待补充：领域专有名词解释)

## 状态机
(待补充：订单/工单/流程等状态流转)

## 约束条件
(待补充：不能违反的硬性规则)
KBEOF

cat > /ai-platform/workspaces/{project-name}/memory/db_design.md << 'KBEOF'
# {项目名} 数据库设计

## 核心表结构
(待补充：最重要的表及字段说明)

## 索引策略
(待补充：关键索引及设计原因)

## 数据迁移规范
- 所有迁移必须有 rollback
- 大表变更必须分批执行
- 禁止在迁移中写业务逻辑
KBEOF

cat > /ai-platform/workspaces/{project-name}/memory/glossary.md << 'KBEOF'
# {项目名} 术语表

## 业务术语
| 术语 | 英文 | 含义 | 相关模块 |
|------|------|------|----------|
| (示例) |       |      |          |

## 技术术语
| 术语 | 含义 | 使用场景 |
|------|------|----------|
KBEOF

echo "✅ Project Memory 模板已创建，请根据实际项目填充内容"
```

### Step 1.4：实现 Git Worktree Sandbox

创建沙盒管理脚本：

```bash
# === 在远程服务器上执行 ===

# 1. 创建沙盒初始化脚本
cat > /ai-platform/templates/sandbox-init.sh << 'SANDBOXEOF'
#!/bin/bash
# 用法: sandbox-init.sh <project-name> <task-id>
# 示例: sandbox-init.sh hyperf-project task-1001

set -e

PROJECT=$1
TASK_ID=$2

if [ -z "$PROJECT" ] || [ -z "$TASK_ID" ]; then
    echo "用法: $0 <project-name> <task-id>"
    exit 1
fi

BASE="/ai-platform"
WORKSPACE="${BASE}/workspaces/${PROJECT}/source"
SANDBOX="${BASE}/sandboxes/${TASK_ID}"
BRANCH="feature/${TASK_ID}"

echo "📦 创建沙盒: ${SANDBOX}"
echo "   分支: ${BRANCH}"
echo "   项目: ${PROJECT}"

# 进入主工作区
cd "${WORKSPACE}"

# 拉取最新代码
git fetch origin

# 创建 git worktree
git worktree add "${SANDBOX}" -b "${BRANCH}" "origin/main"

# 创建沙盒元数据
cat > "${SANDBOX}/.sandbox-meta.yaml" << EOF
task_id: "${TASK_ID}"
project: "${PROJECT}"
branch: "${BRANCH}"
created_at: "$(date -Iseconds)"
expires_at: "$(date -Iseconds -d '+24 hours')"
status: "active"
EOF

# 复制项目记忆到沙盒
if [ -d "${BASE}/workspaces/${PROJECT}/memory" ]; then
    mkdir -p "${SANDBOX}/.ai-memory"
    cp -r "${BASE}/workspaces/${PROJECT}/memory/"* "${SANDBOX}/.ai-memory/"
    echo "✅ 项目知识库已加载到沙盒"
fi

echo "✅ 沙盒创建完成: ${SANDBOX}"
echo "📂 Claude Code 工作目录: ${SANDBOX}"
SANDBOXEOF
chmod +x /ai-platform/templates/sandbox-init.sh

# 2. 创建沙盒销毁脚本
cat > /ai-platform/templates/sandbox-destroy.sh << 'SANDDESEOF'
#!/bin/bash
# 用法: sandbox-destroy.sh <project-name> <task-id>
# 示例: sandbox-destroy.sh hyperf-project task-1001

set -e

PROJECT=$1
TASK_ID=$2

if [ -z "$PROJECT" ] || [ -z "$TASK_ID" ]; then
    echo "用法: $0 <project-name> <task-id>"
    exit 1
fi

BASE="/ai-platform"
WORKSPACE="${BASE}/workspaces/${PROJECT}/source"
SANDBOX="${BASE}/sandboxes/${TASK_ID}"
BRANCH="feature/${TASK_ID}"

echo "🗑️  销毁沙盒: ${SANDBOX}"

# 进入主工作区
cd "${WORKSPACE}"

# 删除 git worktree
git worktree remove "${SANDBOX}" --force 2>/dev/null || true

# 删除分支（如果已 push）
git branch -D "${BRANCH}" 2>/dev/null || true

# 清理残留目录
rm -rf "${SANDBOX}" 2>/dev/null || true

echo "✅ 沙盒已销毁"
SANDDESEOF
chmod +x /ai-platform/templates/sandbox-destroy.sh

# 3. 创建质量门禁脚本
cat > /ai-platform/templates/quality-gates.sh << 'QGEOF'
#!/bin/bash
# 用法: 在沙盒目录内执行
# 返回: 0 = 全部通过, 非0 = 有失败项

set -e

SANDBOX_DIR=$(pwd)
RESULTS_FILE="${SANDBOX_DIR}/.quality-results.txt"

echo "========================================"
echo "  质量门禁检查"
echo "  目录: ${SANDBOX_DIR}"
echo "  时间: $(date)"
echo "========================================"

PASS_COUNT=0
FAIL_COUNT=0

# --- 门禁 1: 语法检查 ---
echo ""
echo "📋 Gate 1/4: PHP 语法检查"
if command -v php &> /dev/null; then
    SYNTAX_ERRORS=$(find . -name "*.php" -not -path "./vendor/*" -exec php -l {} \; 2>&1 | grep -c "Parse error" || true)
    if [ "$SYNTAX_ERRORS" -eq 0 ]; then
        echo "   ✅ PASS"
        ((PASS_COUNT++))
    else
        echo "   ❌ FAIL: ${SYNTAX_ERRORS} 个语法错误"
        ((FAIL_COUNT++))
    fi
else
    echo "   ⏭️  SKIP (php not found)"
fi

# --- 门禁 2: 单元测试 ---
echo ""
echo "📋 Gate 2/4: 单元测试"
if [ -f "phpunit.xml" ] || [ -f "phpunit.xml.dist" ]; then
    if command -v php &> /dev/null && [ -f "vendor/bin/phpunit" ]; then
        if php vendor/bin/phpunit --no-progress 2>&1 | tail -5; then
            echo "   ✅ PASS"
            ((PASS_COUNT++))
        else
            echo "   ❌ FAIL: 单元测试未通过"
            ((FAIL_COUNT++))
        fi
    else
        echo "   ⏭️  SKIP (phpunit not found)"
    fi
else
    echo "   ⏭️  SKIP (no phpunit config)"
fi

# --- 门禁 3: 静态分析 ---
echo ""
echo "📋 Gate 3/4: 静态分析 (phpstan)"
if [ -f "phpstan.neon" ] || [ -f "phpstan.neon.dist" ]; then
    if [ -f "vendor/bin/phpstan" ]; then
        if php vendor/bin/phpstan analyse --no-progress 2>&1 | tail -3; then
            echo "   ✅ PASS"
            ((PASS_COUNT++))
        else
            echo "   ❌ FAIL: 静态分析未通过"
            ((FAIL_COUNT++))
        fi
    else
        echo "   ⏭️  SKIP (phpstan not found)"
    fi
else
    echo "   ⏭️  SKIP (no phpstan config)"
fi

# --- 门禁 4: 安全扫描 ---
echo ""
echo "📋 Gate 4/4: 安全关键字扫描"
DANGEROUS=$(grep -rE "(shell_exec|exec\(|system\(|passthru\(|eval\(|base64_decode)" --include="*.php" . --exclude-dir=vendor 2>/dev/null | wc -l || true)
if [ "$DANGEROUS" -eq 0 ]; then
    echo "   ✅ PASS (无危险函数调用)"
    ((PASS_COUNT++))
else
    echo "   ⚠️  WARNING: 发现 ${DANGEROUS} 处可疑函数调用，请人工审查"
fi

# --- 汇总 ---
echo ""
echo "========================================"
echo "  结果: ${PASS_COUNT} PASS / ${FAIL_COUNT} FAIL"
echo "========================================"

exit ${FAIL_COUNT}
QGEOF
chmod +x /ai-platform/templates/quality-gates.sh

echo "✅ 沙盒管理脚本已创建"
echo ""
echo "📋 使用方式："
echo "  创建: /ai-platform/templates/sandbox-init.sh <project> <task-id>"
echo "  门禁: cd /ai-platform/sandboxes/<task-id> && /ai-platform/templates/quality-gates.sh"
echo "  销毁: /ai-platform/templates/sandbox-destroy.sh <project> <task-id>"
```

### Step 1.5：实现 Task Planner 提示词

创建 Claude Code 可调用的 Task Planner 提示词模板。复制以下内容作为 Prompt 使用：

````markdown
# Task Planner 提示词模板

> 将此提示词发送给配置了 GPT-5.5 的 Claude Code 实例来执行任务拆解。

## Role
你是一个资深技术经理（Tech Lead），负责将产品需求拆解为可执行的开发任务。

## Input
用户会通过微信发送一个需求描述。

## Task
将需求拆解为结构化的任务列表。每个任务必须满足：
1. **独立可执行** — 一个开发者可以独立完成
2. **有明确产出** — 知道做完的标准是什么
3. **有文件范围** — 指出需要修改哪些文件（如果已知）
4. **有依赖关系** — 标记哪些任务必须先完成
5. **有预估复杂度** — S/M/L/XL

## Output Format
```yaml
requirement: "原始需求描述"
total_tasks: N
tasks:
  - id: "T1"
    title: "任务标题"
    description: "详细说明"
    files_scope: ["需要修改的文件列表"]
    dependencies: []
    complexity: "S|M|L|XL"
    acceptance: "验收条件"
  - id: "T2"
    ...
execution_order: ["T1", "T3", "T2", ...]  # 推荐执行顺序
risk_points: ["可能的风险点"]
```

## Example
需求："给用户系统增加手机号登录功能"

```yaml
requirement: "给用户系统增加手机号登录功能"
total_tasks: 5
tasks:
  - id: "T1"
    title: "新增 user_phone 表迁移"
    description: "创建 user_phone 表，含 phone/verified_at/user_id 字段"
    files_scope: ["database/migrations/", "database/schema/"]
    dependencies: []
    complexity: "S"
    acceptance: "migration 可正常执行和回滚"
  - id: "T2"
    title: "新增 PhoneLoginDTO"
    description: "创建手机号登录请求 DTO，含格式验证"
    files_scope: ["app/DTO/User/PhoneLoginDTO.php"]
    dependencies: []
    complexity: "S"
    acceptance: "DTO 验证规则通过单元测试"
  - id: "T3"
    title: "新增 PhoneLoginService"
    description: "实现手机号登录逻辑：验证码校验 → 查用户 → 生成 Token"
    files_scope: ["app/Service/User/PhoneLoginService.php"]
    dependencies: ["T1", "T2"]
    complexity: "M"
    acceptance: "Service 单元测试覆盖正常/异常流程"
  - id: "T4"
    title: "新增 API 路由和 Controller"
    description: "POST /api/auth/phone-login"
    files_scope: ["app/Controller/Api/AuthController.php", "config/routes.php"]
    dependencies: ["T3"]
    complexity: "S"
    acceptance: "API 返回正确的 Token 或错误码"
  - id: "T5"
    title: "集成测试 + API 文档"
    description: "端到端测试 + 更新 API 文档"
    files_scope: ["tests/Feature/PhoneLoginTest.php", "docs/api/"]
    dependencies: ["T4"]
    complexity: "M"
    acceptance: "集成测试全部通过"
execution_order: ["T1", "T2", "T3", "T4", "T5"]
risk_points:
  - "验证码服务如果挂了，需要降级方案"
  - "手机号格式需要支持国际号码"
```
````

---

## 7. Phase 2：质量保障体系

> **目标**：在每个沙盒内自动执行测试、审查、修复闭环
>
> **时间**：1 周
>
> **前置依赖**：Phase 1 完成（有 Sandbox）
>
> **交付物**：
> - [ ] Tester Agent — 自动测试 + 修复循环
> - [ ] Reviewer Agent — 代码审查 + 评分
> - [ ] PR Agent — PR 自动生成
> - [ ] Auto Fix — 失败自动回路

### Step 2.1：创建 Tester Agent 配置

```markdown
# Tester Agent 系统提示词

> 在 Claude Code 中创建 sub-agent 时使用此配置

## Role
你是一个高级测试工程师（QA Engineer），负责对代码变更执行全面测试。

## Responsibilities
1. 执行项目的测试套件
2. 分析测试失败原因
3. 自动修复可以修复的简单错误
4. 无法自动修复的，输出清晰的问题定位报告

## Test Execution Order
1. **语法检查** — `php -l` on changed files
2. **单元测试** — `php vendor/bin/phpunit`
3. **静态分析** — `php vendor/bin/phpstan analyse`
4. **代码风格** — `php vendor/bin/php-cs-fixer check`（如已配置）

## Auto-Fix Loop（最多 3 次）
```
测试失败
  ↓
分析错误 → 可修？→ 是 → 修改代码 → 重新测试
                    → 否 → 记录问题 → 输出报告
  ↓
(循环，最多 3 次)
  ↓
3 次仍失败 → 输出失败报告 + 微信通知
```

## Output Format
```json
{
  "task_id": "task-1001",
  "status": "PASS|FAIL",
  "total_tests": 152,
  "passed": 152,
  "failed": 0,
  "iterations": 1,
  "fixed_automatically": [],
  "unresolved_issues": [],
  "summary": "全部测试通过"
}
```
```

### Step 2.2：创建 Reviewer Agent 配置

```markdown
# Reviewer Agent 系统提示词

> 在 Claude Code 中创建 sub-agent 时使用此配置
> 推荐模型：GPT-5.5

## Role
你是一个资深代码审查专家（Senior Code Reviewer），负责对代码变更进行全面审查。

## Review Dimensions

### 1. 架构审查 (Architecture)
- [ ] 是否遵循 DDD 分层架构？
- [ ] Service 是否通过 Repository 操作 DB？（禁止直接操作 Model）
- [ ] Controller 是否只做路由和参数绑定？
- [ ] 是否有循环依赖？

### 2. 安全审查 (Security)
- [ ] SQL 注入风险？（参数化查询）
- [ ] XSS 风险？（输出编码）
- [ ] Token / Session 泄漏？
- [ ] 敏感数据是否加密存储？
- [ ] 文件上传是否有类型/大小限制？

### 3. 性能审查 (Performance)
- [ ] N+1 查询问题？
- [ ] Redis Key 是否设置 TTL？
- [ ] MQ 消费者是否幂等？
- [ ] 是否有不必要的全表扫描？

### 4. 代码质量 (Code Quality)
- [ ] 方法长度是否合理？（≤50 行为佳）
- [ ] 是否有重复代码？
- [ ] 命名是否符合 PSR 规范？
- [ ] 异常处理是否完善？

### 5. Hyperf 规范 (Framework Convention)
- [ ] 依赖注入是否通过 __construct 而非容器直接获取？
- [ ] 协程上下文是否正确使用？
- [ ] 配置是否正确注入？

## Output Format
```json
{
  "task_id": "task-1001",
  "review_score": 87,
  "verdict": "APPROVE|REQUEST_CHANGES|REJECT",
  "issues": [
    {
      "severity": "HIGH|MEDIUM|LOW",
      "dimension": "architecture|security|performance|quality|convention",
      "file": "app/Service/PushService.php",
      "line": 143,
      "description": "问题描述",
      "suggestion": "修复建议",
      "auto_fixable": true|false
    }
  ],
  "summary": "代码整体质量良好，发现 1 个 HIGH 和 2 个 MEDIUM 问题需要修复"
}
```

## Scoring
- 90-100: APPROVE（可直接合并）
- 70-89: REQUEST_CHANGES（有改进建议）
- <70: REJECT（必须修复高危问题）
```

### Step 2.3：创建 PR Agent 配置

```markdown
# PR Agent 系统提示词

> 在 Claude Code 中创建 sub-agent 时使用此配置
> 推荐模型：GPT-5.5

## Role
你是一个技术文档撰写专家，负责为代码变更生成 Pull Request 描述。

## Task
基于 git diff 和 Task 上下文，生成结构化的 PR 描述。

## Output Format
```markdown
## 📝 变更概述
{一句话描述这个 PR 做了什么}

## 🎯 关联需求
- 微信需求：{原始需求描述}
- Task ID: {task-id}

## 📂 文件变更
| 文件 | 操作 | 说明 |
|------|:----:|------|
| app/Service/PushService.php | 修改 | 新增按用户偏好过滤推送 |
| app/Repository/PushPreferenceRepository.php | 新增 | 推送偏好仓储 |
| database/migrations/xxx.php | 新增 | user_preference 表 |

## 🧪 测试结果
- 单元测试: 152/152 PASS ✅
- 静态分析: 0 errors ✅
- 安全扫描: No issues ✅

## 📊 代码审查
- Review Score: 87/100
- 问题: 1 HIGH / 2 MEDIUM（已全部修复 ✅）

## 🚀 部署说明
{如果有特殊的部署步骤，在此说明}

## 📸 截图（如涉及 UI 变更）
{如有前端变更，附截图}
```
```

---

## 8. Phase 3：智能增强层

> **目标**：引入模型路由和多维代码理解能力
>
> **时间**：2 周
>
> **前置依赖**：Phase 1 + Phase 2 完成
>
> **交付物**：
> - [ ] Multi-Model Router — 模型显式路由
> - [ ] Knowledge MCP — 知识库自动读取
> - [ ] Code Graph — 代码关系图谱
> - [ ] Project Graph — 项目结构图谱

### Step 3.1：实现 Model Router 配置

创建模型路由配置文件：

```yaml
# /ai-platform/templates/model-router.yaml
# Claude Code 模型路由配置

# ===== 模型定义（请替换为你的实际模型 ID） =====
models:
  gpt55:
    provider: "openai"                    # 【占位符：替换为你的 Provider】
    model_id: ""                          # 【占位符：替换为你的 GPT-5.5 模型 ID】
    description: "GPT-5.5 — 规划、审查、文档"
    max_tokens: 16000
    temperature: 0.3
    cost_per_1k_input: 0.0               # 【占位符：填入实际价格】
    cost_per_1k_output: 0.0              # 【占位符：填入实际价格】

  deepseek:
    provider: "deepseek"                  # 【占位符：替换为你的 Provider】
    model_id: ""                          # 【占位符：替换为你的 DeepSeek 模型 ID】
    description: "DeepSeek V4 Pro — 编码、测试、批量修改"
    max_tokens: 16000
    temperature: 0.0
    cost_per_1k_input: 0.0               # 【占位符：填入实际价格】
    cost_per_1k_output: 0.0              # 【占位符：填入实际价格】

  claude_sonnet:
    provider: "anthropic"                 # 【占位符：替换为你的 Provider】
    model_id: ""                          # 【占位符：待填入 Claude Sonnet 4/4.5 模型 ID】
    description: "Claude Sonnet — 架构设计、跨文件重构"
    max_tokens: 16000
    temperature: 0.2
    cost_per_1k_input: 0.0               # 【占位符：填入实际价格】
    cost_per_1k_output: 0.0              # 【占位符：填入实际价格】
    status: "待接入"

# ===== 角色 → 模型映射（显式路由，禁止自动选择） =====
router:
  planner:
    model: gpt55
    description: "需求分析 & 任务拆解"
    prompt_template: "planner-system.md"

  architect:
    model: claude_sonnet                  # 待接入
    fallback: gpt55                       # 接入前降级到 GPT-5.5
    description: "架构设计 & Repository 理解"
    prompt_template: "architect-system.md"

  coder:
    model: deepseek
    description: "代码生成 & 批量修改"
    prompt_template: "coder-system.md"

  tester:
    model: deepseek
    description: "测试执行 & 自动修复"
    prompt_template: "tester-system.md"

  reviewer:
    model: gpt55
    description: "代码审查 & 质量评分"
    prompt_template: "reviewer-system.md"

  pr_agent:
    model: gpt55
    description: "PR 生成 & 文档输出"
    prompt_template: "pr-agent-system.md"

  security_scanner:
    model: ""                             # 【占位符：待填入安全扫描专用模型 ID】
    fallback: gpt55
    description: "安全漏洞扫描"
    status: "待实现"

  docs_writer:
    model: gpt55
    description: "文档生成 & 知识库维护"
    status: "待实现"

# ===== 执行规则 =====
rules:
  - "禁止 Agent 自行选择模型，必须按角色显式路由"
  - "简单 CRUD (< 200 行) 可用 Hermes 直接处理，不经过 Claude Code"
  - "复杂需求 (> 5 文件) 必须走完整 Pipeline"
  - "危险操作必须在沙盒内执行"
  - "每个 Task 必须有一个独立的 Sandbox"
```

### Step 3.2：建立 Code Graph 概念

```markdown
# Code Graph 设计

## 目的
让 Claude Code 的 Architect 角色能够精准定位代码，而非全仓库盲目搜索。

## 结构（每个项目维护一张图）
```
PushController
  ├── depends_on → PushService
  │                 ├── depends_on → PushRepository → PushModel → push_table
  │                 ├── depends_on → UserPreferenceRepository → user_preference
  │                 └── depends_on → Redis (queue:push)
  ├── return → PushResponseDTO
  └── input → PushRequestDTO
```

## 维护方式
1. 初始版本：人工标注核心 Controller → Service → Repository 关系
2. 后续更新：每次 Task 完成后自动更新受影响的子图
3. 存储格式：YAML 文件（可读、可 diff、可版本控制）
4. 位置：`/ai-platform/workspaces/{project}/graph/code-graph.yaml`
```

---

## 9. Phase 4：DevOps 自动化

> **目标**：从代码提交到部署全流程自动化
>
> **时间**：长期迭代
>
> **前置依赖**：Phase 1-3 完成
>
> **交付物**：
> - [ ] Deploy Agent — 一键部署
> - [ ] Monitoring Agent — 部署后监控
> - [ ] Incident Agent — 故障自动响应
> - [ ] 多 Agent 协同 — 完整的自主软件工程能力

### Phase 4 预留内容（待后续细化）

```yaml
phase_4:
  deploy_agent:
    capabilities:
      - "git pull on target server"
      - "docker compose up -d"
      - "health check endpoint"
      - "auto rollback on failure"
      - "微信通知部署结果"
    
  monitoring_agent:
    capabilities:
      - "错误率监控 (Sentry/自建)"
      - "接口响应时间监控"
      - "DB 慢查询告警"
      - "Redis 内存告警"
    
  incident_agent:
    capabilities:
      - "自动回滚到上一个稳定版本"
      - "自动重启异常服务"
      - "自动扩容（如已配 K8s）"
      - "微信紧急通知"
```

---

## 10. 附录：Claude Code 配置模板

### 10.1 Claude Code 多 Provider 配置（settings.json）

> 此配置用于 Claude Code 的 `settings.json`。
> 路径：项目级 `.claude/settings.json` 或用户级 `~/.claude/settings.json`

```json
{
  "models": {
    "gpt55": {
      "provider": "openai",
      "apiKey": "sk-xxx",
      "baseURL": "https://api.your-proxy.com/v1",
      "model": "gpt-5.5"
    },
    "deepseek": {
      "provider": "deepseek",
      "apiKey": "sk-xxx",
      "baseURL": "https://api.deepseek.com/v1",
      "model": "deepseek-chat"
    },
    "claude_sonnet": {
      "provider": "anthropic",
      "apiKey": "sk-ant-xxx",
      "model": "claude-sonnet-4-5-20250901"
    }
  },
  "agents": {
    "planner": {
      "model": "gpt55",
      "systemPrompt": ".claude/agents/planner.md"
    },
    "architect": {
      "model": "gpt55",
      "systemPrompt": ".claude/agents/architect.md"
    },
    "coder": {
      "model": "deepseek",
      "systemPrompt": ".claude/agents/developer.md"
    },
    "tester": {
      "model": "deepseek",
      "systemPrompt": ".claude/agents/tester.md"
    },
    "reviewer": {
      "model": "gpt55",
      "systemPrompt": ".claude/agents/reviewer.md"
    },
    "pr_agent": {
      "model": "gpt55",
      "systemPrompt": ".claude/agents/pr-agent.md"
    },
    "security": {
      "model": "gpt55",
      "systemPrompt": ".claude/agents/security.md"
    }
  }
}
```

### 10.2 Claude Code 一键执行提示词

> 以下提示词可以在 Claude Code 中直接使用，按 Phase 顺序执行。

---

#### 提示词 A：初始化项目基础设施（Phase 1 一键执行）

```
请按以下步骤在远程服务器上初始化 AI 软件工程平台的基础设施：

## 工作目录
所有操作在 /ai-platform 下执行

## Step 1: 创建目录结构
执行如下命令：
- mkdir -p /ai-platform/{workspaces,sandboxes,templates,logs}

## Step 2: 创建项目元数据模板
在 /ai-platform/templates/ 下创建 metadata-template.yaml：
(内容见 herness/next-phase-implementation.md 的 Step 1.2)

## Step 3: 创建项目知识库模板
在 /ai-platform/templates/ 下创建 memory/ 目录，含：
- architecture.md（架构说明）
- coding_style.md（编码规范）
- business_rules.md（业务规则）
- db_design.md（数据库设计）
- glossary.md（术语表）
(内容参考 next-phase-implementation.md Step 1.3)

## Step 4: 创建沙盒管理脚本
在 /ai-platform/templates/ 下创建：
- sandbox-init.sh（沙盒创建）
- sandbox-destroy.sh（沙盒销毁）
- quality-gates.sh（质量门禁）
(脚本内容参考 next-phase-implementation.md Step 1.4)

## Step 5: 验证
- tree -L 3 /ai-platform
- 确认所有脚本有执行权限
```

---

#### 提示词 B：接入第一个项目（Phase 1 项目初始化）

```
请帮我将一个现有项目接入 AI 平台。

## 项目信息
- 项目名：[在此填入项目名]
- Git 地址：[在此填入 Git 远程地址]
- 技术栈：[在此填入，如 PHP 8.2 + Hyperf 3.1]
- 默认分支：[在此填入，如 main]

## 执行步骤

### Step 1: 克隆项目到工作区
```bash
mkdir -p /ai-platform/workspaces/[项目名]
git clone [Git地址] /ai-platform/workspaces/[项目名]/source
cd /ai-platform/workspaces/[项目名]/source
git checkout [默认分支]
```

### Step 2: 创建项目元数据
根据项目实际情况，填充 /ai-platform/workspaces/[项目名]/metadata.yaml

### Step 3: 初始化项目知识库
复制模板到 /ai-platform/workspaces/[项目名]/memory/
根据项目实际情况，填写 architecture.md、coding_style.md 等文件
重点：分析项目中的关键业务规则、分层架构、命名模式

### Step 4: 创建测试沙盒验证
```bash
/ai-platform/templates/sandbox-init.sh [项目名] test-sandbox-001
```
确认沙盒正常创建，目录结构完整。

### Step 5: 清理测试沙盒
```bash
/ai-platform/templates/sandbox-destroy.sh [项目名] test-sandbox-001
```
```

---

#### 提示词 C：完整 Agent Pipeline 执行（Phase 1+2 联合）

```
请按照完整的 Agent Pipeline 执行一个开发任务。

## 任务信息
- 项目：[项目名]
- 需求：[在此填入需求描述，如：给评估系统增加消息推送中心]
- Task ID：[如 task-1001]

## Pipeline 流程

### Stage 1: 需求分析 (Planner — GPT-5.5)
1. 读取 /ai-platform/workspaces/[项目名]/memory/ 下的所有知识库文件
2. 分析需求，输出结构化的需求摘要

### Stage 2: 任务拆解 (Planner — GPT-5.5)
1. 将需求拆解为可执行的任务列表
2. 输出格式：YAML（每个任务含 id/title/files_scope/complexity/acceptance）

### Stage 3: 创建沙盒
1. 执行 /ai-platform/templates/sandbox-init.sh [项目名] [task-id]

### Stage 4: 编码实现 (Coder — DeepSeek)
1. 逐个执行 Stage 2 拆解出的任务
2. 每完成一个任务，标记进度

### Stage 5: 质量门禁
1. 执行 /ai-platform/templates/quality-gates.sh
2. 如有失败，自动修复并重试（最多 3 次）

### Stage 6: 代码审查 (Reviewer — GPT-5.5)
1. 对变更进行全面审查
2. 输出 Review Score + 问题列表

### Stage 7: 提交
1. git add + git commit
2. git push origin feature/[task-id]

### Stage 8: 清理
1. /ai-platform/templates/sandbox-destroy.sh [项目名] [task-id]
2. 输出交付摘要
```

---

### 10.3 微信快捷指令设计（给 Hermes 配置）

以下微信指令可以直接发给 Hermes 触发对应流程：

| 微信指令 | 触发动作 | 示例 |
|----------|----------|------|
| `@hermes 新需求：xxx` | 启动完整 Pipeline | `@hermes 新需求：给推送系统增加按标签过滤` |
| `@hermes 修BUG：xxx` | 轻量模式（Hermes 直接改，不经过 Sandbox） | `@hermes 修BUG：登录页验证码不显示` |
| `@hermes 审查：task-1001` | 仅执行 Review | `@hermes 审查：task-1001` |
| `@hermes 进度` | 查看所有活跃 Task 状态 | `@hermes 进度` |
| `@hermes 取消：task-1001` | 终止并清理指定 Task | `@hermes 取消：task-1001` |
| `@hermes 部署：预发布` | 触发 Deploy Agent（Phase 4） | `@hermes 部署：预发布` |
| `@hermes 回滚：task-1001` | 回滚指定 PR | `@hermes 回滚：task-1001` |

---

## 附录：与现有 CLAUDE.md Pipeline 的整合

本方案与仓库已有的 Issue → PR 流水线（`.claude/` 目录下）的关系：

```
                    ┌──────────────────────────┐
                    │   Hermes 远程工作流（新）   │
                    │   微信 → Sandbox → Push   │
                    └──────────┬───────────────┘
                               │
               共享：Task Planner / Review / PR Agent
                               │
                    ┌──────────┴───────────────┐
                    │   现有 Issue → PR 流水线   │
                    │   /issue → /plan → /auto-fix │
                    └──────────────────────────┘
```

- **复用**：Review Agent、PR Agent 的定义可同时用于两条链路
- **互补**：Hermes 链路覆盖「微信远程编码」场景，现有流水线覆盖「本地 Issue 驱动」场景
- **统一**：最终输出（代码 + PR + Review）格式一致

---

> **版本**: v0.1 — 初版方案，占位符标记为 `【占位符】`
>
> **下一步**: 将本文档 git push 到远程仓库，在服务器上按 Phase 1 → Phase 2 → Phase 3 → Phase 4 顺序逐步执行
>
> **反馈**: 执行过程中遇到的问题和调整，记录回本文档的对应 Phase 小节
