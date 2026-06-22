# MCP Server 自动化安装与配置工作流

> **触发方式**: `/mcp-install` 或直接提交本提示词执行
>
> **目标**: 在一台 Linux 服务器（已安装 Node.js ≥ 18、npm）上，全自动完成 6 个 MCP Server 的安装、配置、Harness 集成及验证，最终输出安装成功验证报告。

---

## 🎯 任务概述

安装并验证以下 MCP Server，确保可被 Claude / Harness 调用：

| # | MCP Server | 用途 | 需要凭证 |
|---|-----------|------|---------|
| 1 | `@modelcontextprotocol/server-github` | GitHub 仓库操作 | `GITHUB_TOKEN` |
| 2 | `@modelcontextprotocol/server-postgres` | PostgreSQL 查询 | `POSTGRES_CONNECTION_STRING` |
| 3 | `@modelcontextprotocol/server-sqlite` | SQLite 操作 | 无 |
| 4 | `@modelcontextprotocol/server-filesystem` | 文件系统操作 | 无 |
| 5 | `@modelcontextprotocol/server-brave-search` | Brave 搜索 | `BRAVE_API_KEY` |
| 6 | `@playwright/mcp@latest` | 浏览器自动化 | 无 |

---

## 🔧 关键要求（强约束）

1. ✅ 所有 MCP Server 必须支持**按需启动**（不常驻 crash）
2. ✅ 所有 Token 必须通过 **env 注入**，不可写死
3. ✅ 配置文件结构必须**可扩展**（后续可增加 MCP Server）
4. ✅ 最终输出**安装成功验证报告**

---

## 🚀 工作流执行

本任务使用 **Ultrawork 多智能体编排** 完成，通过 `Workflow` 工具调度子智能体并行执行安装、验证及报告生成。

### 工作流脚本

```javascript
export const meta = {
  name: 'mcp-auto-install',
  description: '全自动安装 6 个 MCP Server 并集成到 Harness Gateway，输出验证报告',
  phases: [
    { title: '环境检查', detail: '检查 Node.js / npm / npx / git / 网络' },
    { title: '安装 MCP Server', detail: '并行安装 6 个 MCP Server (npx)' },
    { title: '配置与集成', detail: '生成 ~/.mcp/config.json + Harness Gateway 集成' },
    { title: '验证测试', detail: '逐项验证每个 MCP Server 启动与工具调用' },
    { title: '生成报告', detail: '汇总所有状态，输出安装成功验证报告' },
  ],
}

// ============================================================
// Phase 1: 环境检查
// ============================================================
phase('环境检查')

const envCheckResult = await agent(
  `你是一名 DevOps 工程师，请检查当前 Linux 服务器环境是否满足以下要求，并输出结构化结果。

检查项目：
1. node -v（要求 >= 18）
2. npm -v（可用即可）
3. npx --help（验证 npx 可用）
4. git --version（验证 git 可用）
5. curl -I https://registry.npmjs.org/（验证网络可访问 npm registry）
6. 当前用户 home 目录路径
7. 是否存在 ~/.mcp/ 目录

请逐项检查，标记 ✅ 或 ❌。如有缺失，说明如何修复。

输出格式：
\`\`\`json
{
  "node": {"status": "ok|fail", "version": "vX.Y.Z"},
  "npm": {"status": "ok|fail", "version": "X.Y.Z"},
  "npx": {"status": "ok|fail"},
  "git": {"status": "ok|fail", "version": "X.Y.Z"},
  "network": {"status": "ok|fail"},
  "homeDir": "/home/xxx",
  "mcpDirExists": true|false
}
\`\`\``,
  { label: '环境检查', schema: ENV_CHECK_SCHEMA }
)

// 环境检查不通过则中止
if (!envCheckResult || envCheckResult.node?.status === 'fail') {
  log('❌ 环境检查未通过：Node.js 版本不足或缺失，请先安装 Node.js >= 18')
  throw new Error('环境检查未通过')
}

log(`✅ 环境检查通过：Node ${envCheckResult.node?.version}, npm ${envCheckResult.npm?.version}`)

// ============================================================
// Phase 2: 并行安装 6 个 MCP Server
// ============================================================
phase('安装 MCP Server')

const installResults = await parallel([
  () => agent(
    `安装并验证 @modelcontextprotocol/server-github。
在 Shell 中执行：npx @modelcontextprotocol/server-github --help
检查是否正常输出 help 信息，返回安装状态。`,
    { label: 'install:server-github', phase: '安装 MCP Server', schema: INSTALL_SCHEMA }
  ),
  () => agent(
    `安装并验证 @modelcontextprotocol/server-postgres。
在 Shell 中执行：npx @modelcontextprotocol/server-postgres --help
检查是否正常输出 help 信息，返回安装状态。`,
    { label: 'install:server-postgres', phase: '安装 MCP Server', schema: INSTALL_SCHEMA }
  ),
  () => agent(
    `安装并验证 @modelcontextprotocol/server-sqlite。
在 Shell 中执行：npx @modelcontextprotocol/server-sqlite --help
检查是否正常输出 help 信息，返回安装状态。`,
    { label: 'install:server-sqlite', phase: '安装 MCP Server', schema: INSTALL_SCHEMA }
  ),
  () => agent(
    `安装并验证 @modelcontextprotocol/server-filesystem。
在 Shell 中执行：npx @modelcontextprotocol/server-filesystem --help
检查是否正常输出 help 信息，返回安装状态。`,
    { label: 'install:server-filesystem', phase: '安装 MCP Server', schema: INSTALL_SCHEMA }
  ),
  () => agent(
    `安装并验证 @modelcontextprotocol/server-brave-search。
在 Shell 中执行：npx @modelcontextprotocol/server-brave-search --help
检查是否正常输出 help 信息，返回安装状态。`,
    { label: 'install:server-brave-search', phase: '安装 MCP Server', schema: INSTALL_SCHEMA }
  ),
  () => agent(
    `安装并验证 @playwright/mcp@latest。
在 Shell 中执行：npx @playwright/mcp@latest --help
检查是否正常输出 help 信息，返回安装状态。`,
    { label: 'install:playwright-mcp', phase: '安装 MCP Server', schema: INSTALL_SCHEMA }
  ),
])

const installedOk = installResults.filter(Boolean).filter(r => r.status === 'ok')
const installedFail = installResults.filter(Boolean).filter(r => r.status !== 'ok')
log(`📦 安装完成：${installedOk.length} 成功 / ${installedFail.length} 失败`)
if (installedFail.length > 0) {
  log(`❌ 安装失败: ${installedFail.map(r => r.name).join(', ')}`)
}

// ============================================================
// Phase 3: 配置与集成
// ============================================================
phase('配置与集成')

// Step 3a: 生成 MCP 配置文件
log('📝 生成 MCP 配置文件...')

const configResult = await agent(
  `你是一名配置管理专家，请在当前 Linux 服务器上完成以下操作：

### 3a. 创建目录与配置文件

如果目录不存在，创建 ~/.mcp/ 目录，然后写入配置文件 ~/.mcp/config.json。

### 3b. 配置文件内容

根据以下模板，结合实际安装结果和环境变量（如已设置）填充：

\`\`\`json
{
  "mcpServers": {
    "github": {
      "command": "npx",
      "args": ["@modelcontextprotocol/server-github"],
      "env": {
        "GITHUB_TOKEN": "${GITHUB_TOKEN:-替换为实际token}"
      }
    },
    "postgres": {
      "command": "npx",
      "args": ["@modelcontextprotocol/server-postgres"],
      "env": {
        "POSTGRES_CONNECTION_STRING": "${POSTGRES_CONNECTION_STRING:-postgresql://user:pass@host:5432/db}"
      }
    },
    "sqlite": {
      "command": "npx",
      "args": ["@modelcontextprotocol/server-sqlite"]
    },
    "filesystem": {
      "command": "npx",
      "args": ["@modelcontextprotocol/server-filesystem", "/home/${USER}/workspace"]
    },
    "brave-search": {
      "command": "npx",
      "args": ["@modelcontextprotocol/server-brave-search"],
      "env": {
        "BRAVE_API_KEY": "${BRAVE_API_KEY:-替换为API KEY}"
      }
    },
    "playwright": {
      "command": "npx",
      "args": ["@playwright/mcp@latest"]
    }
  }
}
\`\`\`

### 3c. 安全检查

配置写入后，执行以下检查：
- chmod 600 ~/.mcp/config.json（防止 token 泄露）
- grep -r "替换为" ~/.mcp/config.json 检查是否有未替换的占位符
- 如有未替换的占位符，输出警告信息

### 3d. 环境变量导出

在 ~/.bashrc 或 ~/.profile 中追加（如未存在）：
\`\`\`bash
export MCP_CONFIG_PATH=~/.mcp/config.json
\`\`\`

返回配置操作结果。`,
  { label: '生成配置文件', schema: CONFIG_SCHEMA }
)

// Step 3b: Harness Gateway 集成检查
log('🔗 检查 Harness Gateway 集成...')

const harnessResult = await agent(
  `检查 Harness / Hermes Gateway 是否已接入 MCP，并完成集成配置：

### 检查项

1. 搜索 hermes/gateway 相关进程：ps aux | grep -i -E "hermes|gateway|harness"
2. 检查 gateway 是否读取 MCP 配置：
   - 查看是否设置了 MCP_CONFIG_PATH 环境变量
   - 查看 gateway 日志中是否有 MCP 相关输出
3. 如果 gateway 作为 systemd 服务运行：
   - 检查 service 文件位置（常见：/etc/systemd/system/hermes-gateway.service）
   - 确认 Environment 配置中是否包含 MCP_CONFIG_PATH
4. 如未配置 systemd Environment，执行：
   \`\`\`bash
   # 在 service 文件的 [Service] 段追加
   Environment="MCP_CONFIG_PATH=/home/ubuntu/.mcp/config.json"
   systemctl daemon-reload
   \`\`\`

### 验证方法

\`\`\`bash
journalctl -u hermes-gateway -n 50 --no-pager | grep -i mcp
\`\`\`

返回 Harness 集成状态。`,
  { label: 'Harness集成检查', schema: HARNESS_SCHEMA }
)

log(`⚙️ 配置完成：Config=${configResult?.configCreated ? '✅' : '⚠️'}, Harness=${harnessResult?.integrated ? '✅' : '⚠️'}`)

// ============================================================
// Phase 4: 验证测试
// ============================================================
phase('验证测试')

// 并行验证所有已安装成功的 Server
const verifyTargets = installedOk.map(r => r.name)

const verifyResults = await parallel(
  verifyTargets.map(name => () => {
    const verifyMap = {
      'server-github': `验证 GitHub MCP Server：执行 npx @modelcontextprotocol/server-github --help 确认可用，并用 gh api 测试 GitHub API 连通性`,
      'server-postgres': `验证 PostgreSQL MCP Server：执行 npx @modelcontextprotocol/server-postgres --help 确认可用（需要有效的 POSTGRES_CONNECTION_STRING）`,
      'server-sqlite': `验证 SQLite MCP Server：执行 npx @modelcontextprotocol/server-sqlite --help 确认可用`,
      'server-filesystem': `验证 Filesystem MCP Server：执行 npx @modelcontextprotocol/server-filesystem --help 确认可用，并测试读取 ~/workspace 目录`,
      'server-brave-search': `验证 Brave Search MCP Server：执行 npx @modelcontextprotocol/server-brave-search --help 确认可用（需要有效的 BRAVE_API_KEY）`,
      'playwright-mcp': `验证 Playwright MCP Server：执行 npx @playwright/mcp@latest --help 确认可用`,
    }
    return agent(
      verifyMap[name] || `验证 ${name} MCP Server 启动能力`,
      { label: `verify:${name}`, phase: '验证测试', schema: VERIFY_SCHEMA }
    )
  })
)

const verifiedOk = verifyResults.filter(Boolean).filter(r => r.status === 'pass')
const verifiedFail = verifyResults.filter(Boolean).filter(r => r.status !== 'pass')
log(`🧪 验证完成：${verifiedOk.length} 通过 / ${verifiedFail.length} 失败`)

// ============================================================
// Phase 5: 生成最终报告
// ============================================================
phase('生成报告')

const finalReport = await agent(
  `你是一名 QA 工程师，请根据以下数据生成 MCP 安装成功验证报告。

### 输入数据

- 环境检查: ${JSON.stringify(envCheckResult)}
- 安装结果: ${JSON.stringify(installResults)}
- 配置结果: ${JSON.stringify(configResult)}
- Harness 集成: ${JSON.stringify(harnessResult)}
- 验证结果: ${JSON.stringify(verifyResults)}

### 报告要求

请生成 Markdown 格式的完整报告，包含：

1. **总体状态**: ✅ 全部成功 / ⚠️ 部分成功 / ❌ 失败
2. **环境信息**: Node/npm 版本、Home 目录
3. **安装清单**: 每个 MCP Server 的状态表（名称/版本/状态/备注）
4. **配置状态**: config.json 是否生成、权限是否安全、是否有未替换占位符
5. **Harness 集成**: 是否成功接入、Gateway 日志摘要
6. **验证结果**: 每个 Server 的验证通过/失败详情
7. **风险项**: 列出所有 ⚠️/❌ 项及修复建议
8. **下一步**: 如果存在失败项，给出具体的修复步骤

将报告写入 ~/mcp-install-report.md 并在终端输出摘要。`,
  { label: '生成最终报告' }
)

log(finalReport)

// ============================================================
// 返回汇总
// ============================================================
return {
  envCheck: envCheckResult,
  install: { ok: installedOk.length, fail: installedFail.length, details: installResults },
  config: configResult,
  harness: harnessResult,
  verify: { ok: verifiedOk.length, fail: verifiedFail.length, details: verifyResults },
  report: finalReport,
}
```

---

## 📋 Schema 定义

工作流使用的结构化输出 Schema：

### ENV_CHECK_SCHEMA

```json
{
  "type": "object",
  "properties": {
    "node": {
      "type": "object",
      "properties": {
        "status": { "type": "string", "enum": ["ok", "fail"] },
        "version": { "type": "string" }
      },
      "required": ["status", "version"]
    },
    "npm": {
      "type": "object",
      "properties": {
        "status": { "type": "string", "enum": ["ok", "fail"] },
        "version": { "type": "string" }
      },
      "required": ["status", "version"]
    },
    "npx": { "type": "object", "properties": { "status": { "type": "string", "enum": ["ok", "fail"] } }, "required": ["status"] },
    "git": {
      "type": "object",
      "properties": {
        "status": { "type": "string", "enum": ["ok", "fail"] },
        "version": { "type": "string" }
      },
      "required": ["status", "version"]
    },
    "network": { "type": "object", "properties": { "status": { "type": "string", "enum": ["ok", "fail"] } }, "required": ["status"] },
    "homeDir": { "type": "string" },
    "mcpDirExists": { "type": "boolean" }
  },
  "required": ["node", "npm", "npx", "git", "network", "homeDir", "mcpDirExists"]
}
```

### INSTALL_SCHEMA

```json
{
  "type": "object",
  "properties": {
    "name": { "type": "string" },
    "status": { "type": "string", "enum": ["ok", "fail", "skipped"] },
    "version": { "type": "string" },
    "error": { "type": "string" }
  },
  "required": ["name", "status"]
}
```

### CONFIG_SCHEMA

```json
{
  "type": "object",
  "properties": {
    "configCreated": { "type": "boolean" },
    "configPath": { "type": "string" },
    "permissionsFixed": { "type": "boolean" },
    "hasUnfilledPlaceholders": { "type": "boolean" },
    "envExported": { "type": "boolean" },
    "warnings": { "type": "array", "items": { "type": "string" } }
  },
  "required": ["configCreated", "configPath", "permissionsFixed", "hasUnfilledPlaceholders", "envExported"]
}
```

### HARNESS_SCHEMA

```json
{
  "type": "object",
  "properties": {
    "integrated": { "type": "boolean" },
    "gatewayRunning": { "type": "boolean" },
    "mcpConfigEnvSet": { "type": "boolean" },
    "serviceFileUpdated": { "type": "boolean" },
    "logFindings": { "type": "string" },
    "warnings": { "type": "array", "items": { "type": "string" } }
  },
  "required": ["integrated", "gatewayRunning", "mcpConfigEnvSet"]
}
```

### VERIFY_SCHEMA

```json
{
  "type": "object",
  "properties": {
    "name": { "type": "string" },
    "status": { "type": "string", "enum": ["pass", "fail", "skipped"] },
    "helpOutput": { "type": "string" },
    "error": { "type": "string" }
  },
  "required": ["name", "status"]
}
```

---

## 🧭 工作流阶段总览

```
Phase 1: 环境检查          → 单 Agent 检查 Node/npm/npx/git/网络
                              ↓ (通过)
Phase 2: 安装 MCP Server   → 6 个 Agent 并行安装 (npx)
                              ↓
Phase 3: 配置与集成         → 顺序执行: 生成 config.json → Harness 集成检查
                              ↓
Phase 4: 验证测试           → N 个 Agent 并行验证（仅验证安装成功的）
                              ↓
Phase 5: 生成报告           → 单 Agent 汇总所有数据生成报告
```

---

## 🔁 失败处理策略

| 阶段 | 失败策略 | 说明 |
|------|---------|------|
| Phase 1 环境检查 | **中止工作流** | Node.js 缺失则无法继续，抛出 Error 中止 |
| Phase 2 安装失败 | **记录并继续** | 单个 Server 安装失败不影响其他，最终报告中标记 |
| Phase 3 配置失败 | **警告并继续** | 配置文件写入失败时输出警告，但不阻断后续 |
| Phase 3 Harness 未找到 | **记录并继续** | Gateway 未运行可能是正常情况（未部署），记录状态 |
| Phase 4 验证失败 | **记录失败项** | 仅验证安装成功的 Server，失败项输出修复建议 |
| Phase 5 报告生成 | **始终执行** | 无论前面结果如何，始终输出汇总报告 |

---

## 📄 最终产物

工作流执行完成后，产出以下文件：

```
/home/${USER}/
├── .mcp/
│   └── config.json          # MCP 统一配置文件 (chmod 600)
├── mcp-install-report.md    # 安装成功验证报告
└── .bashrc                  # 已追加 MCP_CONFIG_PATH（如有修改）
```

### 报告的终端摘要示例

```markdown
## 🎉 MCP 自动化安装完成

### 总体状态: ⚠️ 部分成功 (5/6)

| MCP Server | 状态 | 备注 |
|-----------|------|------|
| server-github | ✅ 通过 | v0.1.0 |
| server-postgres | ✅ 通过 | v0.1.0 |
| server-sqlite | ✅ 通过 | v0.1.0 |
| server-filesystem | ✅ 通过 | v0.1.0 |
| server-brave-search | ⚠️ 跳过 | 缺少 BRAVE_API_KEY |
| playwright-mcp | ✅ 通过 | latest |

### 风险项
1. ⚠️ BRAVE_API_KEY 未设置 → server-brave-search 无法使用
2. ⚠️ POSTGRES_CONNECTION_STRING 为占位符 → 需替换真实连接串

### 下一步
- 设置环境变量后重新运行验证: export BRAVE_API_KEY="your-key"
- 编辑 ~/.mcp/config.json 替换占位符后重新测试
```

---

## 🚫 注意事项

1. **凭证安全**: 所有 Token/API Key 必须通过环境变量注入，禁止在 config.json 中写死真实值
2. **网络依赖**: 安装过程需要访问 npm registry，确保服务器网络畅通
3. **权限要求**: 安装 npx 包不需要 sudo，但写 systemd service 文件可能需要 sudo
4. **幂等性**: 工作流支持重复执行，已安装的 Server 会检测并跳过

---

## 🔧 手动执行入口

如果工作流无法自动执行，也可以手动调用每个阶段：

```bash
# 1. 环境检查
node -v && npm -v && npx --help && git --version

# 2. 逐个安装
npx @modelcontextprotocol/server-github
npx @modelcontextprotocol/server-postgres
npx @modelcontextprotocol/server-sqlite
npx @modelcontextprotocol/server-filesystem
npx @modelcontextprotocol/server-brave-search
npx @playwright/mcp@latest

# 3. 生成配置
mkdir -p ~/.mcp && cat > ~/.mcp/config.json << 'EOF'
{ ... }
EOF
chmod 600 ~/.mcp/config.json

# 4. 设置环境变量
echo 'export MCP_CONFIG_PATH=~/.mcp/config.json' >> ~/.bashrc

# 5. 验证
npx @modelcontextprotocol/server-github --help
```
