# Hermes Agent 安装指南（Ubuntu 22.04 + pip）

## 环境信息

- **服务器**：Ubuntu 22.04（腾讯云）
- **安装方式**：pip install（官方 PyPI）
- **时间**：2026-06-15

---

## 前置条件

| 依赖 | 版本 | 备注 |
|------|------|------|
| Python | **≥ 3.11**（必须！） | Hermes 0.13+ 强制要求 |
| pip | 22.0+ | 会自动升级到 26.x |
| Git | 2.34+ | postinstall 阶段用到 |
| Node.js | v22+ | 浏览器工具依赖 |
| uv | 0.11+ | 可选，但推荐 |

---

## 安装步骤

### 第一步：升级 Python 到 3.11

Ubuntu 22.04 默认 Python 是 3.10，Hermes 要求 ≥ 3.11。

```bash
# 添加 deadsnakes PPA
sudo add-apt-repository ppa:deadsnakes/ppa -y
sudo apt update

# 安装 Python 3.11
sudo apt install python3.11 python3.11-venv python3.11-dev python3.11-distutils -y

# 设为默认
sudo update-alternatives --install /usr/bin/python3 python3 /usr/bin/python3.11 1

# 验证
python3 --version    # 应显示 Python 3.11.x
```

### 第二步：给 Python 3.11 安装 pip

```bash
curl -sS https://bootstrap.pypa.io/get-pip.py | sudo python3.11
```

### 第三步：安装 Hermes Agent

```bash
pip install hermes-agent -i https://pypi.org/simple/
```

> **注意**：国内用户无需加 `-i` 指定镜像源，直接用 PyPI 官方源。如果速度慢可以挂代理或用 `uv` 安装。

#### 替代方案：用 uv 安装（推荐）

如果系统上已经有 uv（Hermes 的 install.sh 会自动装），可以这样：

```bash
# uv 会自动下载 Python 3.11，无需手动升级系统 Python
uv pip install hermes-agent --python 3.11 -i https://pypi.org/simple/
```

### 第四步：Post-install 初始化

```bash
hermes postinstall
```

交互流程：

1. **Browser engine** → 选 `n`（国内下载 Chromium 极慢且非必需，可跳过）
2. **LLM Provider** → 选 `custom (direct API)`（用国内中转平台）
3. 填写中转平台的 Base URL 和 API Key
4. **API 兼容模式** → 选 `1. Auto-detect`
5. **模型选择** → 选列表中最强的（如 `gpt-5.5`）
6. **Context length** → 回车留空，自动检测
7. **Display name** → 回车用默认，或自定义
8. **Terminal backend** → 选 `Local`
9. **聊天平台** → 按需勾选（微信、飞书、QQ 等）
10. **Tools** → 保持默认，记得取消 `Computer Use (macOS)`（Linux 服务器不需要）
11. **Search Provider** → 选 `Skip`（国内网络不通，后续可配 SearXNG）

### 第五步：配置微信 Gateway（可选但推荐）

如果 postinstall 里已经勾选了微信并完成了配置，跳到第 6 小步直接看 gateway 管理。否则按以下流程：

#### 5.1 进入 gateway 配置向导

```bash
hermes setup gateway
```

在平台列表中用 **空格** 勾选 `Weixin / WeChat`，回车。

#### 5.2 授权模式

```
How should direct messages be authorized?
  → Use DM pairing approval (recommended)   ← 选这个，最安全

How should group chats be handled?
  → Disable group chats (recommended)       ← 选这个，Agent 进群风险大
```

#### 5.3 扫码绑定

配置完成后终端会显示一个链接：

```
https://liteapp.weixin.qq.com/q/7GiQu1?qrcode=xxxx&bot_type=3
```

在手机上打开链接，用微信扫码。扫码后会打开一个叫 OpenClaw/ClawBot 的微信小程序——这就是微信和 Hermes 之间的"桥梁"。

> 如果终端提示 `No module named 'qrcode'`，忽略它，直接复制链接在手机打开。

#### 5.4 Home Channel

```
Use your Weixin user ID as the home channel? [Y/n]:
```

→ 选 **Y**。Home Channel 是 Hermes 的通知/回复默认通道。

#### 5.5 安装为系统服务

```
Install the gateway as a systemd service? [Y/n]:
```

→ 选 **Y**。否则 SSH 断开后 gateway 就停了。

```
Choose how the gateway should run:
  → System service (starts on boot; requires sudo)  ← 服务器选这个
```

然后输入 sudo 密码。

```
Start the service now? [Y/n]:
```

→ 选 **Y**。

#### 5.6 授权你的微信账号

Gateway 启动后，在微信里给 Hermes 发一条消息。然后回到服务器：

```bash
# 查看待批准的请求
hermes pairing list

# 批准（code 从上面命令输出里复制）
hermes pairing approve weixin <code>
```

> ⚠️ **Code 有时效**，几分钟就过期。如果提示 `not found or expired`，重新发一条微信消息产生新 code。

**如果 pairing code 老是过期，直接用开放模式：**

```bash
echo "GATEWAY_ALLOW_ALL_USERS=true" >> ~/.hermes/.env
sudo systemctl restart hermes-gateway
```

> 个人服务器推荐此方式——省去反复审批的麻烦。

#### 5.7 验证

在微信里发一条消息（如"你好"），应该能收到 Hermes 的回复。

#### 5.8 Gateway 管理速查

```bash
sudo systemctl status hermes-gateway       # 查看状态
sudo systemctl restart hermes-gateway      # 重启
sudo systemctl stop hermes-gateway         # 停止
journalctl -u hermes-gateway -f            # 实时日志
journalctl -u hermes-gateway -n 50         # 最近 50 行
hermes pairing list                        # 待批准列表
hermes pairing approve weixin <code>       # 批准
```

---

## 常见坑及解决方案

### 坑 1：`Requires-Python >=3.11`

```
ERROR: Could not find a version that satisfies the requirement hermes-agent
```

**原因**：系统 Python 是 3.10，不满足 Hermes 的最低要求。

**解决**：
- 方案 A：升级系统 Python 到 3.11（见第一步）
- 方案 B：用 `uv pip install hermes-agent --python 3.11` 让 uv 自动管理 Python 版本

### 坑 2：`sudo pip` vs 普通 `pip`

`sudo pip` 使用的是 root 用户的 Python，可能与当前用户的不一致。建议统一用 `uv` 或确认 Python 路径后再装。

```bash
# 检查当前 pip 对应的 Python
pip --version
# 输出类似：pip 26.1.2 from /usr/lib/python3/dist-packages/pip (python 3.10)
#                                                         ↑↑↑ 这里是关键
```

### 坑 3：Git clone 卡住 / 网络不通

```
→ Trying SSH clone...
→ SSH failed, trying HTTPS...
Cloning into '/usr/local/lib/hermes-agent'... （卡住）
```

**原因**：国内服务器访问 GitHub 时 DNS 污染或 TCP 阻断。

**解决**：
- 用 pip 安装（本文方案），绕过 git clone
- 或者在 git clone 时加代理 / 镜像

### 坑 4：Chromium 下载太慢

Hermes postinstall 会尝试从 `storage.googleapis.com` 下载 Chrome 149，国内极慢。

**解决**：直接回答 `n` 跳过，不影响核心功能。需要时再装：

```bash
agent-browser install --with-deps
```

### 坑 5：搜索提供商不可用

DuckDuckGo 等国外搜索服务在国内连不上。

**解决**：
- 选 `Skip` 跳过
- 后续自建 SearXNG 实例作为搜索后端
- 或使用中转平台的内置搜索能力

### 坑 6：Gateway 启动失败 — `Permission denied (CHDIR)`

```
hermes-gateway.service: Failed at step CHDIR spawning /usr/bin/python3.11: Permission denied
hermes-gateway.service: Main process exited, code=exited, status=200/CHDIR
```

**原因**：`~/.hermes/` 目录归属于非当前用户（UID 10000 或 root）。之前用 `sudo` 跑 hermes 命令导致部分文件权限错乱。

**排查**：

```bash
sudo ls -la /home/ubuntu/.hermes
# 看到 owner 是 10000 或 root 而不是 ubuntu → 中招
```

**修复**：

```bash
sudo chown -R ubuntu:ubuntu /home/ubuntu/.hermes
sudo systemctl restart hermes-gateway
```

### 坑 7：微信消息到达但无回复 — `Unauthorized user`

```bash
journalctl -u hermes-gateway -n 50 --no-pager
# 输出：WARNING gateway.run: Unauthorized user: xxx@im.wechat on weixin
```

**原因**：消息已到达服务器，但被授权拦截——pairing code 未批准或已过期。

**修复**：

```bash
# 方式 A：批准 pairing（正式做法）
hermes pairing list
hermes pairing approve weixin <code>

# 方式 B：开放访问（个人服务器推荐）
echo "GATEWAY_ALLOW_ALL_USERS=true" >> ~/.hermes/.env
sudo systemctl restart hermes-gateway
```

### 坑 8：Gateway 显示 `No messaging platforms enabled`

```bash
sudo systemctl status hermes-gateway
# WARNING: No messaging platforms enabled.
```

**原因**：之前配置文件权限不对导致 WeChat 配置没写进去。

**修复**：先确保权限正确（见坑 6），然后重新跑 `hermes setup gateway` 勾选微信并完成配置。

---

## 安装后管理

```bash
hermes              # 启动对话
hermes setup        # 重新进入配置向导
hermes doctor       # 检查环境健康状态
hermes gateway      # 启动消息网关（微信/飞书等）
hermes config       # 查看当前配置
hermes config edit  # 编辑配置文件
```

配置文件位置：
- 设置：`~/.hermes/config.yaml`
- 密钥：`~/.hermes/.env`
- 数据：`~/.hermes/cron/`、`sessions/`、`logs/`

---

## 总结

整个安装的核心就三步：

```bash
# 1. 确保 Python 3.11
sudo apt install python3.11

# 2. 安装
pip install hermes-agent

# 3. 初始化
hermes postinstall
```

前面折腾的主要原因是 Python 版本不对 + 网络环境特殊。只要保证 Python ≥ 3.11，一条 `pip install` 就能搞定。
