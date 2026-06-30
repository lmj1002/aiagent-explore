# Lumen 云服务器部署指南

> 编写日期：2026-06-22 | 适用环境：Linux 云服务器，同时运行 Claude Code + Hermes Agent

## 一、背景

### 你的当前环境

| 工具 | 用途 | 使用模型 / API |
|------|------|---------------|
| **Claude Code** | AI 编程 CLI | 自定义 baseUrl（非官方 Anthropic） |
| **Hermes Agent** | 多 Agent 框架 | 不同模型 + 独立 baseUrl |

两个工具各自对接不同上游，目前无法**统一追踪所有 token 消耗**。

### Lumen 解决什么

Lumen 是一个轻量级的 **Rust 编写的 LLM API 中继代理 + 实时监控仪表盘**，部署一次后：

```
Claude Code ──┐
Hermes ───────┼──→ Lumen (代理层) ──→ Anthropic / OpenAI / 自定义 API
其他工具 ─────┘         │
                        ↓
            浏览器仪表盘 (http://服务器IP:9091/dashboard)
            实时看 Token 消耗、费用、缓存命中率
```

**你不需要每次手动启动追踪**——Lumen 作为守护进程常驻，所有指向它的工具自动被记录。

---

## 二、安装

### 2.1 前置条件

```bash
# 检查 Rust 是否已安装（需要 1.70+）
rustc --version

# 如果未安装
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh
# 重启终端后生效
source ~/.cargo/env
```

### 2.2 编译 Lumen

```bash
# 克隆仓库
cd /opt
git clone https://github.com/DataGrout/lumen.git
cd lumen

# 编译（release 模式，约 3-5 分钟）
cargo build --release

# 二进制文件位置
ls -lh target/release/lumen-core
# 约 8-12 MB，零运行时依赖
```

### 2.3 部署二进制

```bash
# 创建运行目录
sudo mkdir -p /opt/lumen /var/lib/lumen

# 复制二进制
sudo cp target/release/lumen-core /opt/lumen/

# 验证
/opt/lumen/lumen-core --help
```

---

## 三、配置为系统服务

### 3.1 创建专用用户

```bash
sudo useradd -r -s /bin/false lumen
sudo chown -R lumen:lumen /opt/lumen /var/lib/lumen
```

### 3.2 创建 systemd 服务

```bash
sudo tee /etc/systemd/system/lumen.service << 'EOF'
[Unit]
Description=Lumen LLM Proxy and Monitor
After=network.target

[Service]
Type=simple
User=lumen
Group=lumen
WorkingDirectory=/opt/lumen
ExecStart=/opt/lumen/lumen-core
Restart=on-failure
RestartSec=5

# 安全加固
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=/var/lib/lumen

# 日志
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF
```

### 3.3 启动服务

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now lumen.service
sudo systemctl status lumen.service

# 查看日志
sudo journalctl -u lumen.service -f
```

---

## 四、配置防火墙与安全

### 4.1 云服务器防火墙（二选一）

> ⚠️ **强烈建议**：不要直接把 9090/9091 暴露到公网。使用下面的反向代理方案或白名单 IP。

```bash
# 方案 A：仅限本地 + 反向代理（推荐）
# 不开放 9090/9091，通过 nginx 反向代理对外

# 方案 B：IP 白名单（如果只是自己用）
sudo ufw allow from 你的本地IP to any port 9091
sudo ufw allow from 你的本地IP to any port 9090
```

### 4.2 Nginx 反向代理（推荐）

Lumen 仪表盘**无内置认证**，建议用 nginx 加上 Basic Auth：

```bash
# 安装 nginx
sudo apt install nginx apache2-utils -y

# 创建认证文件
sudo htpasswd -c /etc/nginx/.htpasswd lumen_admin
# 输入密码
```

```nginx
# /etc/nginx/sites-available/lumen
server {
    listen 443 ssl;
    server_name lumen.your-domain.com;  # 换成你的域名

    ssl_certificate     /etc/ssl/certs/your-cert.pem;
    ssl_certificate_key /etc/ssl/private/your-key.pem;

    # 仪表盘（对外）
    location /dashboard {
        auth_basic "Lumen Dashboard";
        auth_basic_user_file /etc/nginx/.htpasswd;
        proxy_pass http://127.0.0.1:9091;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }

    # API
    location /api/ {
        auth_basic "Lumen API";
        auth_basic_user_file /etc/nginx/.htpasswd;
        proxy_pass http://127.0.0.1:9091;
    }

    # 代理/中继（给 AI 工具用，不暴露公网）
    # 这个 location 只在内网使用
    location /relay/ {
        allow 127.0.0.1;
        allow 10.0.0.0/8;       # 你的内网段
        allow 172.16.0.0/12;
        deny all;
        proxy_pass http://127.0.0.1:9090/;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_buffering off;
    }
}

# HTTP → HTTPS 重定向
server {
    listen 80;
    server_name lumen.your-domain.com;
    return 301 https://$host$request_uri;
}
```

```bash
# 启用站点
sudo ln -s /etc/nginx/sites-available/lumen /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
```

> **没有域名？** 可以直接用 IP + 端口，但务必将云服务商的安全组/防火墙配置为**仅允许你的 IP 访问 9091 端口**。

---

## 五、配置 AI 工具走 Lumen

### 5.1 Lumen 中继端点

Lumen 内置了以下路由：

| Lumen 中继地址 | 转发到 |
|---|---|
| `http://127.0.0.1:9090/anthropic` | `https://api.anthropic.com` |
| `http://127.0.0.1:9090/openai` | `https://api.openai.com` |
| `http://127.0.0.1:9090/google` | Google AI API |

**自定义上游**：在仪表盘 `http://服务器IP:9091/dashboard` → Settings → Endpoints 中添加。

### 5.2 配置 Claude Code

根据你的场景（自定义 baseUrl），有两种方式：

**方式 A：中继模式（推荐，无需改证书）**

```bash
# 如果你的 Claude Code 用的是 Anthropic 兼容 API
# 直接将 ANTHROPIC_BASE_URL 指向 Lumen
export ANTHROPIC_BASE_URL=http://127.0.0.1:9090/anthropic
claude

# 永久生效：写入 ~/.claude/settings.json
# 修改 apiBaseUrl 为 http://127.0.0.1:9090/anthropic
```

**方式 B：自定义端点模式（你的场景最可能用这个）**

如果你的 baseUrl 不是标准的 Anthropic API（比如 `https://ai-router.plugins-world.cn`），需要在 Lumen 仪表盘中添加自定义端点：

1. 打开 `http://服务器IP:9091/dashboard`
2. 点击 **Endpoints** → **+ Add**
3. 添加 `ai-router.plugins-world.cn`
4. 然后设置：

```bash
export ANTHROPIC_BASE_URL=http://127.0.0.1:9090
claude
```

Lumen 会自动解析目标 host 并路由到对应上游。

> ⚠️ **注意**：中继模式是 `http://` 不是 `https://`，因为 Lumen 在本地监听。

### 5.3 配置 Hermes Agent

Hermes 支持多 provider，需要为每个 provider 配置 base_url：

```bash
# 在 Hermes 配置中（~/.hermes/config 或环境变量）
# 将所有 provider 的 api_base 指向 Lumen

# 示例：OpenAI 兼容的 provider
OPENAI_BASE_URL=http://127.0.0.1:9090/openai

# 示例：Anthropic 兼容的 provider
ANTHROPIC_BASE_URL=http://127.0.0.1:9090/anthropic

# 自定义 provider
CUSTOM_PROVIDER_URL=http://127.0.0.1:9090
```

---

## 六、仪表盘使用

### 6.1 访问地址

```
https://lumen.your-domain.com/dashboard    # 通过域名 + nginx
http://服务器公网IP:9091/dashboard           # 直连（需防火墙放行）
```

### 6.2 仪表盘功能

| 模块 | 说明 |
|------|------|
| **Lap Cost** | 实时弧形表盘，显示当前会话累计费用 |
| **Token Rate** | 每秒 token 速率（输入 + 输出） |
| **Total Spend** | 总计花费仪表盘 |
| **Token Breakdown** | 输入 / 输出 / 缓存命中的 token 分布 |
| **Event Feed** | 每次 API 调用的详细日志（模型、token 数、费用） |
| **Lap 追踪** | 按 Lap 标记对比前后成本 |

### 6.3 仪表盘截图位置

打开后你会看到类似这样的界面（核心仪表盘区域）：

```
┌──────────────────────────────────────────────────┐
│  Lumen Dashboard                          [设置]  │
├──────────┬──────────┬──────────┬─────────────────┤
│  Lap $   │ Tokens/s │  Total   │  最近事件         │
│  $0.042  │  1245 t/s│  $2.31   │  claude-sonnet   │
│   ◔弧线   │   ◔弧线   │  ◔弧线   │  输入: 1024 tok  │
│          │          │          │  输出: 348 tok   │
│          │          │          │  费用: $0.008    │
└──────────┴──────────┴──────────┴─────────────────┘
```

---

## 七、实际架构总览

部署完成后，你的服务器架构如下：

```
                    云服务器
    ┌────────────────────────────────────┐
    │                                    │
    │  Claude Code                       │
    │  ANTHROPIC_BASE_URL=               │
    │    http://127.0.0.1:9090/anthropic │────┐
    │                                    │    │
    │  Hermes Agent                      │    │
    │  Provider → 127.0.0.1:9090         │────┤
    │                                    │    │    ┌──────────────┐
    │                                    │    ├───→│ api.anthropic │
    │  lumen-core (systemd 常驻)          │    │    └──────────────┘
    │  ├─ :9090 代理/中继 ────────────────┼────┤
    │  └─ :9091 API + 仪表盘              │    │    ┌──────────────┐
    │       ↑                            │    ├───→│ api.openai    │
    │       │                            │    │    └──────────────┘
    │  nginx :443 (Basic Auth)           │    │
    │       │                            │    │    ┌──────────────┐
    └───────┼────────────────────────────┘    └───→│ 自定义 API     │
            │                                      └──────────────┘
    你的浏览器
    https://lumen.xxx.com/dashboard
    实时看到所有工具的 token 消耗
```

---

## 八、运维命令速查

```bash
# 服务管理
sudo systemctl status lumen     # 查看状态
sudo systemctl restart lumen    # 重启
sudo systemctl stop lumen       # 停止

# 日志
sudo journalctl -u lumen -f                     # 实时日志
sudo journalctl -u lumen --since "10 min ago"   # 近 10 分钟

# 查看端口监听
ss -tlnp | grep -E '9090|9091'

# 测试代理是否正常
curl http://127.0.0.1:9091/api/stats
```

---

## 九、注意事项与限制

| 项目 | 说明 |
|------|------|
| **数据持久化** | ⚠️ Lumen 默认使用内存聚合，**重启服务历史数据丢失**。如需持久化，需要自行扩展或定期导出 |
| **自定义 baseUrl** | 非标准 Anthropic/OpenAI API 需在仪表盘中手动添加自定义端点 |
| **认证** | 仪表盘无内置登录，务必通过 nginx + Basic Auth 或 IP 白名单保护 |
| **缓存命中** | 如果你的反向代理自身有缓存（如 ai-router），Lumen 只能看到转发后的结果，缓存命中率统计可能偏低 |
| **端口冲突** | 确保 9090、9091 端口未被占用 |
| **HTTPS 上游** | 中继模式下，Lumen → 上游 API 走 HTTPS；客户端 → Lumen 走 HTTP（本地） |

---

## 十、与 claude-tap 的分工

| 场景 | 用什么 |
|------|--------|
| **日常持续监控** — 随时打开仪表盘看 token 总量/费用 | **Lumen** |
| **深入调试** — 审查某次会话的系统提示、工具调用链、逐轮对比 | **claude-tap** |
| **导出报告** — 生成自包含 HTML/Markdown 追踪报告 | **claude-tap** |
| **忘记开启追踪** | Lumen 常驻无此问题；claude-tap 不手动启动就漏了 |

**建议两个都装**：Lumen 常驻做监控层，claude-tap 按需做深度分析层。
