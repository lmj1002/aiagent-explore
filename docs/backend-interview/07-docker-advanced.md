# 高级 Docker 面试知识架构

> 目标读者：高级后端开发（需掌握容器化部署技能）
> 更新日期：2026-06-15

---

## 目录

1. [核心原理](#1-核心原理)
2. [Dockerfile 最佳实践](#2-dockerfile-最佳实践)
3. [网络模型](#3-网络模型)
4. [存储管理](#4-存储管理)
5. [资源限制](#5-资源限制)
6. [Docker Compose](#6-docker-compose)
7. [镜像仓库](#7-镜像仓库)
8. [安全最佳实践](#8-安全最佳实践)
9. [生产实践](#9-生产实践)
10. [与 K8s 的关系与演进路径](#10-与-k8s-的关系与演进路径)

---

## 1. 核心原理

### 1.1 Namespace 隔离

Linux Namespace 是 Docker 实现容器隔离的基石。每个 Namespace 类型负责隔离不同的系统资源。

| Namespace 类型 | 隔离内容 | 对应内核常量 | 引入版本 |
|---|---|---|---|
| PID | 进程编号 | CLONE_NEWPID | 2.6.24 |
| NET | 网络栈（网卡、路由、iptables） | CLONE_NEWNET | 2.6.29 |
| MNT | 挂载点视图 | CLONE_NEWNS | 2.4.19 |
| UTS | 主机名与域名 | CLONE_NEWUTS | 2.6.19 |
| IPC | System V IPC / POSIX 消息队列 | CLONE_NEWIPC | 2.6.19 |
| User | 用户 / UID / GID 映射 | CLONE_NEWUSER | 3.8 |
| Cgroup | Cgroup 根视图 | CLONE_NEWCGROUP | 4.6 |

```bash
# 查看容器内的 Namespace
docker exec <container> ls -la /proc/self/ns/

# 查看宿主上容器的 Namespace
ls -la /proc/$(docker inspect --format '{{.State.Pid}}' <container>)/ns/

# 演示：两个容器共享一个 Network Namespace
docker run -d --name nginx --network container:webapp nginx:alpine
```

**高频面试题：**

- **问：容器内执行 `ps aux` 为什么只能看到自己的进程？**
  > 答：因为容器具有独立的 PID Namespace。容器 init 进程的 PID 为 1，宿主机视角下容器进程有全局 PID，但在容器内被重新映射。这也是为什么僵尸进程问题在容器中特别突出——PID 1 负责回收子进程，如果它没有实现信号处理逻辑，子进程僵尸会积累。

- **问：User Namespace 的 UID 映射如何工作？**
  > 答：通过 `/etc/subuid` 和 `/etc/subgid` 定义宿主机上的 UID 段与容器内 UID 的映射。例如将宿主 `root(0)` 映射到容器的 `100000`，这样容器内的 root 在宿主机上没有实际特权。Docker 通过 `--userns-remap` 启用。

- **问：6 个 Namespace 不够隔离的是什么？**
  > 答：/sys、/proc 文件系统的一部分、时间（clock）、内核模块、SELinux 标签、内核参数（sysctl）。这些需要更底层的虚拟化技术（KVM）或额外的安全机制。

### 1.2 Cgroup（Control Groups）

Cgroup 负责**资源限制**，这是 Namespace 做不到的。当前使用 cgroup v2（自 Linux 4.5 / Docker 20.10+ 推广）。

```
/sys/fs/cgroup/
├── cpu/              # CPU 配额与周期
├── memory/           # 内存限制与 OOM 控制
├── blkio/            # 块设备 I/O
├── cpuset/           # CPU 核心绑定
├── pids/             # 进程数量限制
├── net_prio/         # 网络优先级
└── hugetlb/          # 大页内存
```

```bash
# 查看容器的 cgroup 限制
docker run -d --memory=512m --cpus=1.5 --name demo nginx:alpine
cat /sys/fs/cgroup/memory/docker/<container-id>/memory.limit_in_bytes
cat /sys/fs/cgroup/cpu/docker/<container-id>/cpu.cfs_quota_us

# cgroup v2
cat /sys/fs/cgroup/system.slice/docker-<container-id>.scope/memory.max
```

**高频面试题：**

- **问：Cgroup 和 Namespace 的关系是什么？**
  > 答：Namespace 负责"看不见"（隔离视图），Cgroup 负责"抢不到"（限制资源）。两者缺一不可：只有 Namespace 没有 Cgroup，一个容器可以耗尽宿主机全部资源；只有 Cgroup 没有 Namespace，进程之间互相可见，不存在隔离。

### 1.3 UnionFS 与 Overlay2

Docker 默认使用 `overlay2` 存储驱动（Linux 内核 4.0+ 原生支持），取代了早期的 `aufs` 和 `devicemapper`。

**OverlayFS 分层结构：**

```
Container Layer (读写层, rw)
    ↑  Merge (Upper + Lower 联合视图)
Lower Dir (镜像层, ro) ← 多个镜像层叠放
    ↑
Lower Dir (镜像层, ro)
    ↑
Lower Dir (基础镜像层, ro)
    ↑
```

```bash
# 查看镜像分层
docker history nginx:alpine

# 查看容器文件系统结构
docker inspect <container> --format '{{.GraphDriver.Data}}'

# overlay2 实际目录结构
ls -la /var/lib/docker/overlay2/
```

**写时复制（Copy-on-Write, COW）：**

- 容器读取文件：从上到下查找各层，命中则返回（不修改）
- 容器修改文件：将文件从下层**复制到读写层**，再修改（CoW 的唯一场景）
- 容器删除文件：在读写层创建 whiteout 文件（`character 0:0`），掩盖下层的同名文件
- 容器创建文件：直接在读写层写入

**踩坑经验：**

1. **大量小文件写入性能差**——CoW 需要逐文件复制到上层。解决方案：挂载 volume 或 tmpfs，跳过 UnionFS 层。
2. **overlay2 与 `xfs` 搭配需要 `ftype=1`**——否则 Docker 启动报错。生产环境务必验证：
   ```bash
   xfs_info /var/lib/docker | grep ftype
   ```
3. **容器崩溃后 overlay2 层残留**——使用 `docker container prune --force --filter "until=24h"` 清理。

### 1.4 镜像分层详解

```dockerfile
# 每个指令产生一个镜像层
FROM alpine:3.18          # Layer 1: base layer
RUN apk add --no-cache curl # Layer 2: adds curl + deps
COPY app /app             # Layer 3: adds app files
RUN pip install -r req    # Layer 4: python packages
EXPOSE 8080               # Layer 5: metadata only (不占空间)
ENTRYPOINT ["python"]     # Layer 6: metadata only
CMD ["app/main.py"]       # Layer 6: metadata only
```

**层缓存（Build Cache）：**

Docker 按 Dockerfile 指令顺序构建，每个指令前检查缓存命中：

- 缓存失效条件：前一层变化、`COPY`/`ADD` 文件内容变化、`RUN` 命令字符串变化
- **必须把变化频率低的指令放在前面**（安装依赖 → 复制代码 → 编译）

```dockerfile
# 错误示范：先 COPY 源码再装依赖 → 源码变化导致依赖重新安装
COPY . /app
RUN npm install

# 正确做法：分离依赖层
COPY package.json package-lock.json /app/
RUN npm install
COPY src/ /app/
```

---

## 2. Dockerfile 最佳实践

### 2.1 多阶段构建（Multi-stage Build）

核心价值：构建环境与运行环境分离，最终镜像只包含运行时所需内容。

```dockerfile
# ===== Stage 1: Build =====
FROM golang:1.22-alpine AS builder
WORKDIR /src
COPY go.mod go.sum ./
RUN go mod download
COPY . .
RUN CGO_ENABLED=0 go build -ldflags="-s -w" -o /app/server ./cmd/

# ===== Stage 2: Runtime =====
FROM alpine:3.18
RUN apk add --no-cache ca-certificates tzdata
COPY --from=builder /app/server /server
COPY --from=builder /src/config/prod.yaml /config.yaml
EXPOSE 8080
USER nobody
ENTRYPOINT ["/server"]
```

```dockerfile
# === 更复杂的案例：前端 + 后端一体构建 ===
FROM node:20-alpine AS frontend
WORKDIR /build
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM golang:1.22-alpine AS backend
WORKDIR /build
COPY backend/go.* ./
RUN go mod download
COPY backend/ ./
RUN CGO_ENABLED=0 go build -o /app/api ./cmd/

FROM alpine:3.18
COPY --from=frontend /build/dist/ /static/
COPY --from=backend /app/api /api
EXPOSE 8080
CMD ["/api"]
```

**高频面试题：**

- **问：多阶段构建相比单阶段有哪些优势？**
  > 优势：1）最终镜像不包含编译器、依赖管理器、构建工具链，体积缩小 5-20 倍；2）不暴露构建凭据（如 `--mount=type=secret`）；3）构建和运行环境解耦，基础镜像独立升级。

- **问：如何将多阶段的产物全部保留在一个镜像中？**
  > 使用 `--target` 参数构建特定阶段用于调试：`docker build --target builder -t myapp:dev .`

### 2.2 镜像瘦身与层缓存优化

**常用工具与指标：**

```bash
# 查看镜像各层大小
docker history --no-trunc <image>

# 使用 dive 分析镜像（交互式）
dive <image>

# 使用 docker-slim 自动瘦身
docker-slim build --http-probe myapp:latest
```

**优化技巧表：**

| 技巧 | 说明 | 效果 |
|------|------|------|
| 使用 Alpine / Distroless 基础镜像 | Alpine 约 5MB，Distroless 约 20MB | 从 800MB → 20-50MB |
| 合并 RUN 指令 | `RUN apt-get update && apt-get install -y pkg && rm -rf /var/lib/apt/lists/*` | 减少层数，清除缓存 |
| `--no-cache` / `apt-get clean` | 安装完清理包管理器缓存 | 每层省几 MB 到几十 MB |
| `COPY --chown` 在 COPY 时指定 | 避免 RUN chown 产生额外层 | 减少一层 |
| `.dockerignore` | 排除 .git、node_modules、**pycache** | 减少构建上下文 |
| `npm ci` 替代 `npm install` | 锁定版本、更快、无需网络缓存 | 稳定且更快 |
| `ldflags="-s -w"` (Go) | 去掉符号表和调试信息 | 缩小 20-30% |
| `strip` / `upx` (C/C++/Rust) | 压缩二进制文件 | 缩小 30-60% |

**Alpine vs Distroless vs Slim 对比：**

```
Alpine      5MB   musl libc + busybox  包可用 apk 安装，兼容问题需留意
Distroless  20MB  glibc + tzdata       无 shell、无包管理器，最安全
Slim        30MB  Debian 精简版         兼容性好，体积介于 Alpine 和 Full 之间
Full        800MB+ Debian/Ubuntu 完整  构建方便但体积大
```

**踩坑经验：**

- **Alpine 的 musl libc 兼容问题：**
  - Python 需要 `pip install aiohttp` 时可能编译失败 → 安装 `gcc musl-dev`
  - Java 报 `Cannot allocate memory` → Alpine 默认 `ulimit` 过小，需 `--ulimit nofile=1024:1024`
  - DNS 解析慢 → Alpine `3.13+` 已修复，老版本改 `/etc/nsswitch.conf`
- **合并 RUN 指令的隐藏问题：** 层缓存粒度过粗。开发期间可以保持拆分以便缓存，CI/CD 中再合并且使用 `--no-cache`。

### 2.3 安全最佳实践（Dockerfile 层面）

```dockerfile
# 安全强化的 Dockerfile 模板
FROM golang:1.22-alpine AS builder
RUN apk add --no-cache git ca-certificates
WORKDIR /src
# ... 构建过程 ...

FROM alpine:3.18

# 1. 使用非 root 用户
RUN addgroup -S appgroup && adduser -S appuser -G appgroup

# 2. 只安装运行时必需
RUN apk add --no-cache ca-certificates tzdata

# 3. 复制时保持最小权限
COPY --from=builder --chown=appuser:appgroup /app/server /app/server
COPY --from=builder /etc/ssl/certs /etc/ssl/certs

# 4. 只读根文件系统
USER appuser
WORKDIR /app

# 5. 安全相关 metadata
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=3s --retries=3 \
  CMD wget --no-verbose --tries=1 --spider http://localhost:8080/health || exit 1

ENTRYPOINT ["/app/server"]
```

**安全属性清单：**

- `USER` 非 root
- `RUN` 中不硬编码凭据（使用 `--mount=type=secret` 或构建参数注入）
- 不暴露 ssh 端口或安装 ssh server
- 使用 `HEALTHCHECK` 而非 `--restart always` 单独配合
- `.dockerignore` 排除配置文件中的密钥

---

## 3. 网络模型

### 3.1 网络驱动全景

| 驱动 | 用途 | 隔离级别 | 跨主机 |
|------|------|---------|--------|
| `bridge` | 默认，单机容器间通信 | 每个容器独立 NET NS | 否 |
| `host` | 容器直接使用宿主机网络栈 | 共享宿主 NET NS | 否 |
| `overlay` | Swarm / K8s 跨主机容器通信 | 每容器独立 + VXLAN 隧道 | 是 |
| `macvlan` | 容器分配物理网络 MAC 地址 | 桥接物理网络 | 否（但可达） |
| `ipvlan` | 容器共享 MAC 但有独立 IP | 同 MAC 多 IP | 否 |
| `none` | 无网络栈（loopback 仅） | 完全隔离 | — |

```bash
# 创建自定义 bridge 网络
docker network create --driver bridge --subnet 172.20.0.0/16 --gateway 172.20.0.1 mynet

# 使用 macvlan 让容器像物理机一样接入网络
docker network create -d macvlan \
  --subnet=192.168.1.0/24 \
  --gateway=192.168.1.1 \
  -o parent=eth0 \
  macnet
```

### 3.2 容器间通信

**Bridge 网络通信流程：**

```
容器A (172.17.0.2) → 容器B (172.17.0.3)
    ↓
veth pair (A 端: eth0@ifX, 宿主端: vethXXXX)
    ↓
docker0 bridge (Linux bridge, 172.17.0.1/16)
    ↓
veth pair (宿主端: vethYYYY, B 端: eth0@ifZ)
    ↓
容器B (172.17.0.3)
```

**内置 DNS 服务：**

Docker 自带的 DNS 解析器（`127.0.0.11`）提供容器名 ↔ IP 的解析，仅对自定义网络生效（默认 bridge 无 DNS 解析）。

```yaml
# docker-compose.yml - 通过服务名通信
services:
  web:
    image: nginx
    networks:
      - app-net
  api:
    image: myapi
    networks:
      - app-net
    # web 可以通过 http://api:8080 访问此服务

networks:
  app-net:
    driver: bridge
```

```bash
# 默认 bridge 网络需要 --link（已废弃，不推荐）
docker run -d --name db --network mynet redis
docker run -d --name app --network mynet myapp
# app 中通过 "db" 主机名即可访问 redis
```

### 3.3 端口映射与 iptables

```bash
# 端口映射底层：iptables DNAT + MASQUERADE
docker run -d -p 8080:80 nginx:alpine

# 查看 iptables 规则
iptables -t nat -L DOCKER -n --line-numbers
```

**端口映射的性能开销：** 小报文场景（如高频短连接，HTTP/1.1 keep-alive 断开频繁）下，DNAT + MASQUERADE 会导致约 5-10% 吞吐损失。可使用 host 网络模式消除此开销，但需自行管理端口冲突。

### 3.4 Overlay 网络（跨主机通信）

```
主机A                             主机B
┌──────────────┐                ┌──────────────┐
│ 容器A        │                │ 容器B        │
│ 10.0.0.2     │                │ 10.0.0.3     │
└──────┬───────┘                └──────┬───────┘
       │ vxlan0                         │ vxlan0
       │ (VXLAN Tunnel ID: 256)         │ (VTEP)
       └───────────┬────────────────────┘
                   │ 物理网络 (underlay)
                   └────────────────────
```

- Overlay 使用 VXLAN 封装（UDP 4789），每包增加 50 字节开销
- 性能优化方向：使用 macvlan/ipvlan 或 RDMA 绕过 VXLAN 封装
- 生产场景下不建议使用 Docker Swarm overlay，转用 K8s CNI 插件（Calico、Cilium、Flannel）

### 3.5 网络性能对比

```bash
# 使用 netperf 测试不同网络模式
docker run -it --rm --network host networkstatic/netperf netperf -H <target_ip>
docker run -it --rm --network bridge networkstatic/netperf netperf -H <target_ip>
docker run -it --rm --network overlay networkstatic/netperf netperf -H <target_ip>
```

| 网络模式 | 吞吐量 (参考) | 延迟 (参考) | 适用场景 |
|---------|--------------|------------|---------|
| Host | 40 Gbps (线速) | ~0.05ms | 延迟敏感、高性能计算 |
| Bridge (veth) | 38 Gbps | ~0.08ms | 常见场景 |
| macvlan | 39.5 Gbps | ~0.06ms | 需要直接接入物理网络 |
| Overlay (VXLAN) | 35 Gbps | ~0.15ms | 跨主机容器通信 |

**高频面试题：**

- **问：一个容器可以连接多个网络吗？**
  > 可以。`docker network connect` 将容器附加到第二个网络，容器内增加第二个 eth 接口。典型场景：一个接口连接外部网络，另一个连接内部管理网络。

- **问：默认 bridge 和自定义 bridge 的关键区别？**
  > 1）自定义 bridge 支持容器名自动 DNS 解析；2）自定义 bridge 提供更好的隔离（容器在不连接的网络之间不能通信）；3）自定义 bridge 可在容器运行中动态接入/断开；4）自定义 bridge 可配置 `--icc=false` 禁用容器间通信以增强安全。

- **问：Docker 中如何实现固定 IP？**
  > 创建自定义网络时指定 subnet，容器启动时用 `--ip` 指定地址。注意：默认 bridge 不支持固定 IP。

## 4. 存储管理

### 4.1 Volume vs Bind Mount vs tmpfs

| 特性 | Volume | Bind Mount | tmpfs |
|------|--------|-----------|-------|
| 存储位置 | `/var/lib/docker/volumes/` | 任意宿主路径 | 内存（无持久化） |
| 管理方式 | Docker 管理 | 用户自行管理 | Docker 管理 |
| 备份迁移 | `docker run --volumes-from` / Volume 驱动 | 手动复制 | 不支持 |
| 权限控制 | Docker 自动设置 | 保持宿主权限 | N/A |
| 跨主机 | Volume 驱动（NFS/云存储） | 需自行同步 | 不支持 |
| 适用 | 数据库、数据持久化 | 代码开发调试、配置文件 | 临时缓存、密钥 |

```bash
# Volume 操作
docker volume create --driver local \
  --opt type=nfs \
  --opt o=addr=192.168.1.100,rw \
  --opt device=:/data/shared \
  nfs-volume

docker run -d -v nfs-volume:/data --name app myapp

# Bind Mount（开发热重载）
docker run -d -v /host/path:/container/path:ro --name dev app

# tmpfs（敏感数据）
docker run -d --tmpfs /tmp:size=100M,noexec,nosuid,uid=1000 app

# 查看卷的挂载详情
docker inspect <container> --format '{{json .Mounts}}' | jq
```

### 4.2 存储驱动选择

| 存储驱动 | 适用场景 | 注意 |
|---------|---------|------|
| overlay2 | 所有现代 Linux (4.0+)，默认推荐 | — |
| fuse-overlayfs | rootless Docker | 性能较 overlay2 差 |
| devicemapper | 旧系统 (RHEL 7, CentOS 7) | 生产不推荐，loop-lvm 性能极差 |
| aufs | Ubuntu 早期版本 | Linux 主线不包含，已废弃 |
| zfs | ZFS 文件系统 | 有块级压缩、快照优势 |
| btrfs | Btrfs 文件系统 | 子卷快照，但稳定性有争议 |

```bash
# 查看当前存储驱动
docker info --format '{{.Driver}}'

# 更改存储驱动（修改 daemon.json）
# /etc/docker/daemon.json
{
  "storage-driver": "overlay2",
  "storage-opts": [
    "overlay2.override_kernel_check=true"
  ]
}
```

### 4.3 数据持久化策略

**数据库容器数据管理：**

```yaml
version: "3.8"
services:
  postgres:
    image: postgres:16-alpine
    volumes:
      - pgdata:/var/lib/postgresql/data   # 命名卷
      - ./init/:/docker-entrypoint-initdb.d/:ro  # 初始化脚本
    environment:
      POSTGRES_PASSWORD_FILE: /run/secrets/db_password
    secrets:
      - db_password

volumes:
  pgdata:
    driver: local
    # 生产环境可指定 NFS/EFS 驱动
    # driver: rexray/ebs
```

**应用日志持久化（不要写入容器内）：**

```yaml
services:
  app:
    image: myapp
    # 方式一：Docker 日志驱动
    logging:
      driver: json-file
      options:
        max-size: "10m"
        max-file: "3"
    
    # 方式二：卷挂载日志目录（仅临时方案）
    volumes:
      - app-logs:/var/log/app

volumes:
  app-logs:
```

**踩坑经验：**

1. **Volume 挂载后文件权限问题：** 容器内进程以非 root 运行，volume 目录在宿主机上所有者是 root，导致写失败。
   - 解决方案：在 Dockerfile 中创建用户并指定 UID，挂载后 `chown` 或使用 `security_opt` 中映射 UID。
   - 或者使用 `docker-compose` 的 `user` 字段和初始化容器（init container）修复权限。

2. **Bind Mount 与 SELinux 冲突：**
   ```bash
   # 在 SELinux 启用环境，需要添加 :Z 或 :z 标签
   docker run -v /host/data:/data:Z myapp
   # :Z = 私有标签, :z = 共享标签
   ```

3. **高性能场景：** 数据库等 IO 密集型容器应使用 Volume，而非 Bind Mount。Volume 由 Docker 直接管理，可绕过容器文件系统层的 CoW 开销。更优方案是使用 `/var/lib/postgresql/data` 外部存储（如 AWS EBS gp3、本地 NVMe SSD）。

---

## 5. 资源限制

### 5.1 CPU 限制

```bash
# CPU 配额：限制最多使用 1.5 个核
docker run --cpus=1.5 nginx

# CPU 份额：权重竞争（默认 1024，优先级 512 获得 1/2 默认的 CPU 时间）
docker run --cpu-shares=512 nginx

# CPU 核心绑定：仅使用 0-2 号核
docker run --cpuset-cpus="0-2" --cpuset-mems="0" nginx

# CPU 周期与配额（细粒度控制）
docker run --cpu-period=100000 --cpu-quota=50000 nginx  # 最多 0.5 核
```

**高频面试题：**

- **问：`--cpus=1.5` 和 `--cpuset-cpus="0-1"` 的区别？**
  > `--cpus` 是软限制，定义了 CPU 时间配额（实际对应 cgroup 的 cpu.cfs_quota_us / cpu.cfs_period_us = 1.5）。`--cpuset-cpus` 是硬绑定，将进程绑定到特定物理/逻辑核上。后者适合 NUMA 感知场景（避免跨 NUMA 节点内存访问延迟）。

- **问：CPU 限制的实际效果取决于宿主机负载吗？**
  > 是的。`--cpus` 确保容器在满负载时不超过配额。但宿主机空闲时，CFS 调度器允许容器使用全部 CPU（如果配额允许）。`--cpuset-cpus` 则无论负载如何都固定绑定到指定核。

### 5.2 内存限制

```bash
# 硬限制与软限制
docker run -m 512m --memory-reservation=256m nginx
# -m (--memory): 硬限制，超过则 OOM kill
# --memory-reservation: 软限制，宿主机内存不足时优先压缩到此值
# --memory-swap: 限制 swap 用量（-1 表示无限制）
# --oom-kill-disable: 禁止 OOM kill（谨慎使用，可能导致宿主机 OOM）
```

```bash
# 查看容器实际内存使用
docker stats <container>

# cgroup 中查看详细
cat /sys/fs/cgroup/memory/docker/<id>/memory.usage_in_bytes
cat /sys/fs/cgroup/memory/docker/<id>/memory.stat
```

### 5.3 OOM 分析

**OOM 优先级调整：**

```bash
# --oom-score-adj: -1000（不 kill）到 1000（优先 kill），默认 0
docker run --oom-score-adj=500 nginx
# Docker 守护进程自身 oom_score_adj = -999
```

**OOM 排查步骤：**

```bash
# 1. 确认 OOM
docker logs <container> | grep -i "killed\|out of memory"
dmesg | grep -i "killed process" | tail -10

# 2. 查看 OOM 分数
cat /proc/$(docker inspect --format '{{.State.Pid}}' <container>)/oom_score

# 3. 调整容器内存
docker update -m 1g --memory-swap 1.5g <container>
```

**踩坑经验：**

- **Java 容器 OOM 经典问题：** JVM 默认堆大小取决于宿主机内存（`-XX:+PrintFlagsFinal`），而不是容器的 `-m` 限制。Java 10+ 的 `UseContainerSupport` 默认开启，但老版本必须显式设置 `-Xmx`。
  ```dockerfile
  # 正确做法
  ENV JAVA_OPTS="-XX:+UseContainerSupport -XX:MaxRAMPercentage=75.0"
  ENTRYPOINT ["sh", "-c", "java $JAVA_OPTS -jar app.jar"]
  ```

- **Go 应用问题：** Go runtime 使用 `GOMAXPROCS` 自动检测 cgroup CPU 限制（Go 1.21+），但老版本需要用 Uber 的 `automaxprocs` 库：
  ```go
  import _ "go.uber.org/automaxprocs"
  ```

### 5.4 资源监控

```bash
# 实时监控
docker stats --no-stream --format "table {{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}"

# cadvisor 容器监控（用于 Prometheus 采集）
docker run -d \
  --name cadvisor \
  --restart always \
  -p 8080:8080 \
  -v /:/rootfs:ro \
  -v /var/run:/var/run:ro \
  -v /sys:/sys:ro \
  -v /var/lib/docker:/var/lib/docker:ro \
  gcr.io/cadvisor/cadvisor:v0.47.0

# 限制并监控
docker run -d \
  --memory=512m \
  --cpus=0.5 \
  --restart=on-failure:5 \
  --name monitored-app \
  myapp
```

---

## 6. Docker Compose

### 6.1 多服务编排

```yaml
# docker-compose.yml（生产级模板）
version: "3.8"

services:
  api:
    build:
      context: ./api
      dockerfile: Dockerfile
      args:
        - BUILD_ENV=production
    image: registry.example.com/api:${TAG:-latest}
    ports:
      - "127.0.0.1:8080:8080"  # 仅绑定 localhost
    environment:
      - DB_HOST=db
      - REDIS_HOST=redis
      - LOG_LEVEL=info
    env_file:
      - ./env/api.env
    depends_on:
      db:
        condition: service_healthy
      redis:
        condition: service_started
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8080/health"]
      interval: 30s
      timeout: 5s
      retries: 3
      start_period: 15s
    restart: unless-stopped
    deploy:                                # Swarm mode
      replicas: 3
      resources:
        limits:
          cpus: '1.0'
          memory: 512M
      update_config:
        parallelism: 1
        delay: 10s
        order: start-first

  db:
    image: postgres:16-alpine
    volumes:
      - pgdata:/var/lib/postgresql/data
    environment:
      - POSTGRES_DB=myapp
      - POSTGRES_USER=myapp
      - POSTGRES_PASSWORD_FILE=/run/secrets/db_password
    secrets:
      - db_password
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U myapp"]
      interval: 10s
      timeout: 5s
      retries: 5
    restart: always

  redis:
    image: redis:7-alpine
    command: ["redis-server", "--appendonly", "yes"]
    volumes:
      - redis-data:/data
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 10s
      timeout: 3s
      retries: 5

volumes:
  pgdata:
    driver: local
  redis-data:
    driver: local

secrets:
  db_password:
    file: ./secrets/db_password.txt
```

### 6.2 环境变量管理

```yaml
# 多层 env 文件策略
# .env（项目根，自动加载）
COMPOSE_PROJECT_NAME=myapp
TAG=1.2.0
USER_UID=1000

# docker-compose.yml 引用 ${VARIABLE}
```

```bash
# 多环境文件叠加
docker compose -f docker-compose.yml -f docker-compose.prod.yml config

# 验证配置
docker compose config

# 仅重建特定服务
docker compose up -d --no-deps --build api
```

```yaml
# docker-compose.prod.yml（生产覆盖）
version: "3.8"
services:
  api:
    restart: always
    deploy:
      replicas: 5
      resources:
        limits:
          cpus: '2.0'
          memory: 1G
    logging:
      driver: "json-file"
      options:
        max-size: "50m"
        max-file: "5"

# docker-compose.dev.yml（开发覆盖）
version: "3.8"
services:
  api:
    ports:
      - "8080:8080"
    volumes:
      - ./api:/app:cached    # 热重载
      - /app/node_modules     # 排除 node_modules
    environment:
      - LOG_LEVEL=debug
      - DEBUG=true
    profiles: ["dev"]
```

### 6.3 生产 vs 开发配置差异

| 维度 | 开发环境 | 生产环境 |
|------|---------|---------|
| 构建策略 | `build` 本地构建 | 使用 CI/CD 推送的镜像 |
| 端口暴露 | 直接暴露宿主端口 | 仅 localhost 绑定或反向代理 |
| 热重载 | Bind mount 代码目录 | 无 volume 或只读复制 |
| 日志 | 挂载到本地查看 | 日志驱动 → 集中收集 |
| 资源限制 | 通常不设 | 严格限制 |
| 副本数 | 单副本 | 多副本（Swarm/K8s） |
| secrets | `.env` 文件 | Docker secrets / 外部密钥管理 |
| 健康检查 | 可选 | 必需 |
| 网络 | 默认 bridge / 自定义 | overlay / CNI |

### 6.4 高频面试题

- **问：`depends_on` 的 `condition: service_healthy` 和 `condition: service_started` 区别？**
  > `service_started` 仅保证服务容器启动，不保证应用就绪。`service_healthy` 等待健康检查通过。数据库场景必须使用 `service_healthy`，否则应用启动时会连接不上数据库。

- **问：Compose 中如何实现服务间发现？**
  > Compose 自动为每个服务创建 DNS 记录，服务名即主机名。在自定义网络中，`api` 可以通过 `redis:6379` 访问 `redis` 服务。

- **问：如何在 docker-compose 中优雅处理配置文件？**
  > 1）敏感信息使用 `secrets`；2）通用配置使用 `env_file`；3）不同部署环境用 `-f` 叠加配置文件；4）使用 `configs`（Swarm mode）管理非敏感配置文件。

---

## 7. 镜像仓库

### 7.1 Registry vs Harbor

| 特性 | Docker Registry | Harbor |
|------|---------------|--------|
| 基础功能 | 镜像存储 + 推送拉取 | 镜像存储 + 推送拉取 |
| Web UI | 无（可选第三方） | 企业级 UI |
| 认证 | 基本 auth / 无 | LDAP/OIDB/AD 集成 |
| 访问控制 | 无 | 项目级 RBAC |
| 安全扫描 | 无 | Trivy / Clair 集成 |
| 镜像签名 | 无 | Cosign / Notary |
| 复制 | 无 | 跨数据中心镜像复制 |
| 垃圾回收 | 手动 | 自动（自动清理未引用层） |
| 审计日志 | 无 | 详细操作审计 |

```bash
# 搭建私有 Registry
docker run -d \
  --name registry \
  --restart always \
  -p 5000:5000 \
  -v registry-data:/var/lib/registry \
  -v registry-auth:/auth \
  -e "REGISTRY_AUTH=htpasswd" \
  -e "REGISTRY_AUTH_HTPASSWD_REALM=Registry Realm" \
  -e "REGISTRY_AUTH_HTPASSWD_PATH=/auth/htpasswd" \
  registry:2

# 配置 insecure registry（非 TLS 环境）
# /etc/docker/daemon.json
{
  "insecure-registries": ["registry.internal:5000"]
}
```

### 7.2 镜像签名与安全扫描

**镜像签名（Cosign）：**

```bash
# 生成密钥对
cosign generate-key-pair

# 签名镜像
cosign sign --key cosign.key registry.example.com/myapp:v1.2.0

# 验证签名
cosign verify --key cosign.pub registry.example.com/myapp:v1.2.0

# 在 CI/CD 中集成
# GitHub Actions:
# - uses: sigstore/cosign-installer@main
# - run: cosign sign --key ${{ secrets.COSIGN_KEY }} $IMAGE
```

**镜像扫描（Trivy）：**

```bash
# 扫描本地镜像
trivy image --severity=CRITICAL,HIGH myapp:latest

# 扫出结果示例
# +-------------------+---------------------+-------------+-----------------------+
# |     LIBRARY       |  VULNERABILITY ID   | SEVERITY    |  INSTALLED VERSION   |
# +-------------------+---------------------+-------------+-----------------------+
# | libcrypto1.1      | CVE-2023-4807       | CRITICAL    | 1.1.1n-r0            |
# | openssl           | CVE-2023-5363       | HIGH        | 3.0.9-r0             |
# +-------------------+---------------------+-------------+-----------------------+

# 扫描并只输出 JSON
trivy image --format json --output trivy-report.json myapp:latest

# 在 Dockerfile 构建过程中集成
docker build -t myapp:test .
trivy image --exit-code 1 --severity CRITICAL myapp:test || exit 1

# 扫描仓库中的镜像
trivy image --severity=CRITICAL --ignore-unfixed \
  registry.example.com/myapp:latest
```

### 7.3 分发策略与 GC

**镜像拉取优化：**

```bash
# 设置镜像拉取并发数
# /etc/docker/daemon.json
{
  "max-concurrent-downloads": 10,
  "max-concurrent-uploads": 5
}

# 使用 registry mirror 加速
{
  "registry-mirrors": [
    "https://mirror.ccs.tencentyun.com",
    "https://docker.mirrors.ustc.edu.cn"
  ]
}
```

**Registry GC（垃圾回收）：**

```bash
# Registry v2 自动启用在线 GC
# 配置存储限制
docker run -d \
  --name registry \
  -e REGISTRY_STORAGE_DELETE_ENABLED=true \
  -e REGISTRY_STORAGE_MAINTENANCE_READONLY_ENABLED=false \
  registry:2

# 手动触发 GC
docker exec registry bin/registry garbage-collect \
  /etc/docker/registry/config.yml \
  --delete-untagged=true

# Harbor 中设置自动清理策略
# 项目 → 配置 → 自动清理：
# - 保留最近 N 个标签的版本
# - 删除超过 X 天未拉取的镜像
# - 删除无标签的镜像（dangling images）
```

**高频面试题：**

- **问：镜像层的缓存位置和清理方式？**
  > 镜像层缓存位于 `/var/lib/docker/overlay2/`。清理方式：`docker image prune -a`（删除所有未使用的镜像）、`docker system prune -a --volumes`（系统级清理）。注意两层缓存：本地层缓存（overlay2） + BuildKit 缓存（`/var/lib/docker/buildkit/`）。

- **问：Harbor 的镜像复制如何实现跨区域分发？**
  > Harbor 支持基于规则的镜像复制（push-based 和 pull-based）。规则按项目过滤，支持正则匹配镜像名与标签。复制通过 Harbor Job Service 异步执行，失败自动重试，支持网络代理穿透。

---

## 8. 安全最佳实践

### 8.1 容器运行时安全

```bash
# 综合安全配置
docker run -d \
  --name secure-app \
  --read-only \                                          # 根文件系统只读
  --tmpfs /tmp:noexec,nosuid,size=64M \                  # 可写临时目录
  --security-opt seccomp=/path/to/seccomp-profile.json \ # seccomp 白名单
  --security-opt apparmor=myapp-profile \                # AppArmor 限制
  --security-opt no-new-privileges:true \                # 禁止提权
  --cap-drop=ALL \                                       # 删除所有能力
  --cap-add=NET_BIND_SERVICE \                           # 仅添加必要能力
  --user 1000:1000 \                                     # 非 root 用户
  --cgroup-parent=/docker/secure \                       # 独立 cgroup 层级
  myapp
```

**Linux Capabilities 最小化原则：**

```
默认容器拥有约 50 个 capabilities，大部分不需要
推荐：--cap-drop=ALL --cap-add=必要项

常见应用所需能力：
- NET_BIND_SERVICE   绑定 <1024 端口
- NET_ADMIN          网络配置（极少需要）
- SYS_PTRACE         调试与 strace（生产不建议）
- SYS_ADMIN          挂载等管理操作（禁止生产使用）
- CHOWN / DAC_OVERRIDE / FOWNER / SETUID / SETGID 等通常也不需要
```

### 8.2 Seccomp 配置

```json
{
  "defaultAction": "SCMP_ACT_ERRNO",
  "architectures": ["SCMP_ARCH_X86_64", "SCMP_ARCH_AARCH64"],
  "syscalls": [
    {
      "names": ["read", "write", "open", "close", "stat", "mmap", 
                "brk", "pread64", "pwrite64", "readv", "writev",
                "nanosleep", "futex", "epoll_wait", "sched_yield",
                "exit", "exit_group", "getpid", "gettid"],
      "action": "SCMP_ACT_ALLOW"
    },
    {
      "names": ["setuid", "setgid"],
      "action": "SCMP_ACT_ALLOW"
    }
  ]
}
```

```bash
# 加载自定义 seccomp 配置
docker run --security-opt seccomp=./seccomp-app.json myapp

# 查看 seccomp 状态
docker inspect <container> --format '{{.HostConfig.SecurityOpt}}'
```

**踩坑经验：**

> 使用 distroless 基础镜像的 Go 应用在默认 seccomp 配置下运行正常，但若添加了 `--security-opt seccomp=unconfined` 反而会降低安全性。不要轻易放松 seccomp 限制——宁可调 Docker 默认配置也不要完全关闭。

### 8.3 Rootless Docker

```bash
# 安装 rootless Docker（非 root 用户运行）
dockerd-rootless-setuptool.sh install

# rootless 模式的关键限制：
# - 端口 < 1024 需要 rootlesskit 或 proxy（如 socat 转发）
# - overlay2 不可用 → 使用 fuse-overlayfs
# - cgroup v2 支持有限
# - CVE-2019-5736 等逃逸风险降低
# - ping 命令可能需要额外配置

# 配置 rootless 下绑定低端口
dockerd-rootless-setuptool.sh install \
  --skip-iptables \
  --userland-proxy-path=/usr/bin/slirp4netns
```

### 8.4 容器内进程安全

```bash
# 禁止容器内获取新权限
--security-opt no-new-privileges:true

# 只读根文件系统 + 指定可写路径
--read-only \
--tmpfs /tmp:noexec,nosuid,size=128M \
--tmpfs /var/run:noexec,size=64M

# 内核能力精细控制（Go 应用示例）
--cap-drop=ALL \
--cap-add=NET_BIND_SERVICE

# 防止容器内进程获得宿主机信息
--security-opt mask=/proc/acpi:ro \
--security-opt mask=/proc/scsi:ro \
--security-opt mask=/sys/firmware:ro
```

### 8.5 CVE 扫描与镜像生命周期安全

```bash
# CI/CD 流水线集成
# 阶段1：构建时扫描基础镜像
trivy image --severity=CRITICAL --exit-code=1 alpine:3.18 || exit 1

# 阶段2：构建应用镜像后扫描
docker build -t app:${CI_COMMIT_SHA} .
trivy image --severity=CRITICAL,HIGH --exit-code=1 app:${CI_COMMIT_SHA}

# 阶段3：部署前扫描（可选，通常与阶段2 合并）
trivy image --severity=CRITICAL app:${CI_COMMIT_SHA} \
  --format sarif --output trivy-results.sarif

# 阶段4：定期间隔扫描已部署镜像
trivy image --severity=CRITICAL registry.example.com/app:latest
```

**高频面试题：**

- **问：容器内 root 的真实特权？**
  > 容器的 root（UID 0）在宿主机上不是 root，但有两个重要风险：1）默认配置下，UID 0 映射到宿主 UID 0，如果容器内有 mount 等系统调用，能操作宿主机文件系统；2）Docker 的 `--privileged` 模式会完全突破隔离。所以即使容器内 root 受限，也强烈建议用非 root 用户运行。

- **问：`--privileged` 为什么是安全红线？**
  > `--privileged` 会授予所有 capabilities、禁用 seccomp 和 AppArmor、允许访问宿主机所有设备（`/dev/*`）。这基本等同于容器获得宿主机 root 权限。生产环境不应使用，即使调试也建议用 `--cap-add` 精确授权。

---

## 9. 生产实践

### 9.1 日志收集

**Docker 日志驱动：**

| 驱动 | 说明 | 场景 |
|------|------|------|
| `json-file` | 默认，写入宿主机文件 | 单机调试 |
| `syslog` | 发送到 syslog 服务 | 传统日志中心 |
| `journald` | systemd journal | 与 systemd 集成 |
| `fluentd` | 发送到 fluentd 聚合 | 日志管道 |
| `gelf` | Graylog Extended Log Format | Graylog 集中管理 |
| `awslogs` | Amazon CloudWatch Logs | AWS 环境 |
| `gcplogs` | Google Cloud Logging | GCP 环境 |
| `splunk` | Splunk HTTP Event Collector | Splunk 环境 |

```bash
# fluentd 收集日志架构
# 应用 → fluentd → Elasticsearch/Kafka → Kibana/Grafana

# 配置 fluentd 日志驱动
docker run -d \
  --log-driver=fluentd \
  --log-opt fluentd-address=192.168.1.10:24224 \
  --log-opt tag="app.{{.Name}}" \
  --log-opt env=prod \
  myapp

# 生产推荐日志配置（daemon.json）
{
  "log-driver": "json-file",
  "log-opts": {
    "max-size": "10m",
    "max-file": "3"
  }
}
```

**应用日志规范：**

1. 应用始终写 stdout/stderr（不要写文件）
2. 日志格式统一 JSON（方便结构化处理）
3. 每条日志包含 `@timestamp`、`level`、`logger`、`message`、`trace_id`
4. 多行日志处理：fluentd/filebeat 的 multiline 解析器

```json
// 推荐日志格式
{"@timestamp":"2026-06-15T10:30:00.123Z","level":"ERROR","logger":"http","message":"request failed","trace_id":"abc123","duration_ms":2304,"status_code":500,"path":"/api/order"}
```

### 9.2 健康检查

```dockerfile
# Dockerfile 中定义（推荐）
HEALTHCHECK --interval=30s --timeout=3s --start-period=15s --retries=3 \
  CMD curl -f http://localhost:8080/health || exit 1

# 不同类型服务的健康检查
HEALTHCHECK --interval=10s --timeout=5s --retries=5 \
  CMD pg_isready -U myapp -d myapp || exit 1

HEALTHCHECK --interval=5s --timeout=2s --retries=3 \
  CMD redis-cli ping | grep PONG || exit 1
```

```bash
# 查看容器健康状态
docker inspect --format '{{.State.Health.Status}}' <container>
# 输出: healthy | unhealthy | starting | none

# 在 Compose 中配置依赖等待
services:
  app:
    depends_on:
      db:
        condition: service_healthy
```

**健康检查设计要点：**

1. 检查**应用层的就绪状态**（数据库连接可达、缓存初始化完毕），而非仅进程存活
2. 端点应尽可能轻量（不查询数据库即可证明存活），但独立的就绪探针可以检查依赖
3. 超时时间要短（2-5秒），避免长时间等待阻塞容器调度
4. 启动宽容期（`start_period`）给应用初始化时间，期间失败不计入重试次数

### 9.3 优雅关闭

```bash
# Docker 默认发送 SIGTERM，等待 10 秒后 SIGKILL
# 应用需捕获 SIGTERM 并执行清理

# 调整停止超时
docker stop --time=30 myapp

# docker-compose 中配置
services:
  app:
    stop_grace_period: 60s
    stop_signal: SIGINT  # 某些应用希望用 SIGINT 而非 SIGTERM
```

**应用端优雅关闭实现：**

```go
// Go 示例
func main() {
    srv := &http.Server{Addr: ":8080"}

    go func() {
        if err := srv.ListenAndServe(); err != http.ErrServerClosed {
            log.Fatal(err)
        }
    }()

    // 等待 SIGTERM
    quit := make(chan os.Signal, 1)
    signal.Notify(quit, syscall.SIGTERM, syscall.SIGINT)
    <-quit

    log.Println("Shutting down...")
    ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
    defer cancel()
    srv.Shutdown(ctx)  // 优雅关闭：停止接受新请求，处理完正在处理的请求
}
```

```python
# Python 示例
import signal, sys

def handle_sigterm(signum, frame):
    print("Received SIGTERM, shutting down gracefully...")
    # 关闭数据库连接
    # 等待处理中的请求完成
    sys.exit(0)

signal.signal(signal.SIGTERM, handle_sigterm)
```

### 9.4 调试技巧

```bash
# 进入运行中的容器（确保有 shell）
docker exec -it <container> /bin/sh

# 在容器上下文中执行单条命令
docker exec -it <container> env
docker exec -it <container> cat /etc/os-release

# 导出容器文件系统查看
docker export <container> > container.tar
tar -tf container.tar

# 从镜像复制文件（无需运行容器）
docker cp <container>:/app/logs/app.log ./local_logs.log

# 查看容器内进程
docker top <container>

# 查看容器更改的文件
docker diff <container>
# A: 新增, C: 修改, D: 删除

# 使用 nsenter 进入容器命名空间（需 root）
docker inspect <container> --format '{{.State.Pid}}'
nsenter -t <PID> -n -m -u -i -p
```

**性能调试：**

```bash
# 实时资源监控
docker stats --no-stream <container>

# 查看容器 cgroup 统计
cat /sys/fs/cgroup/cpu/docker/<id>/cpu.stat
cat /sys/fs/cgroup/memory/docker/<id>/memory.stat

# 查看容器网络流量
docker exec <container> cat /proc/net/dev

# iotop 查看容器 IO（宿主机执行）
iotop -p $(docker inspect --format '{{.State.Pid}}' <container>)

# strace 调试容器进程（宿主机执行）
strace -p $(docker inspect --format '{{.State.Pid}}' <container>)
```

### 9.5 性能分析

```bash
# 容器级别的 perf 分析（宿主机执行）
perf top -p $(docker inspect --format '{{.State.Pid}}' <container>)

# 使用 pprof 远程分析 Go 容器
# 确保容器暴露了 pprof 端口
go tool pprof http://<container-ip>:6060/debug/pprof/profile

# 使用 async-profiler 分析 Java 容器
# 需挂载 /tmp/.java_pid$PID 和 --cap-add=SYS_PTRACE
docker run --cap-add=SYS_PTRACE -v /tmp:/tmp my-java-app
```

**高频面试题：**

- **问：`docker logs` 性能问题和替代方案？**
  > `json-file` 驱动下，`docker logs` 读取宿主机的 JSON 日志文件（`/var/lib/docker/containers/<id>/<id>-json.log`）。文件过多或过大时性能差。替代方案：1）使用 fluentd/syslog 驱动直接发送到日志平台；2）应用自身输出结构化日志直接写入 ELK/ClickHouse；3）只用 Docker 日志驱动做崩溃前最后日志的保留。

- **问：容器中 core dump 如何收集？**
  > 容器默认不生成 core dump。启用：1）宿主机设置 `ulimit -c unlimited`；2）容器运行时加 `--ulimit core=-1`；3）设置 `/proc/sys/kernel/core_pattern` 指向共享卷；4）挂载 volume 用于存放 core dump 文件。生产环境不建议开启，因为可能包含内存敏感数据且占用大量磁盘。

## 10. 与 K8s 的关系与演进路径

### 10.1 Docker 在 K8s 中的角色变化

```
历史演进：
2013: Docker 诞生
2014: K8s 诞生（容器编排，原生支持 Docker）
2016: CRI（Container Runtime Interface）引入
2017: containerd 成为 CNCF 项目
2020: K8s 1.20 弃用 Docker Shim（dockershim）
2021: K8s 1.24 移除 dockershim

当前格局（2026）：

用户层 (CLI/API)
    ↓
Kubernetes (kubelet)
    ↓
CRI-O               containerd
    ↓                    ↓
runc / runsc (gVisor) / kata (轻量 VM)
    ↓
Linux Kernel (cgroup v2 + Namespace)
```

**关键理解：**

- K8s 不再直接依赖 Docker Engine，而是通过 CRI 接口与任意容器运行时通信
- K8s 管理的是 **Pod**（一个或多个容器的调度单元），而非单个容器
- Docker Compose 的职责被 K8s 的 **Deployment / Service / ConfigMap / Secret** 等对象覆盖
- Docker 在 K8s 生态中逐渐退居"镜像构建与开发调试"角色

### 10.2 Docker 技能到 K8s 的映射

| Docker 概念 | K8s 对应概念 | 说明 |
|------------|-------------|------|
| `docker run` | Pod / Deployment | Pod 是最小调度单元 |
| `docker compose` | Deployment + Service + ConfigMap | 多容器声明式管理 |
| Container | Container（在 Pod 内） | 一个 Pod 可含多个容器 |
| Network | Service / Ingress / NetworkPolicy | 服务发现与暴露 |
| Volume | PersistentVolume / PVC / ConfigMap | 存储与配置管理 |
| Healthcheck | Liveness / Readiness / Startup Probe | 更细粒度探针 |
| `docker build` | Kaniko / BuildKit | Docker-in-Docker 或独立构建 |
| Image Registry | ImagePullSecrets / Registry | 认证与拉取策略 |
| Port mapping | NodePort / LoadBalancer / Ingress | 多种暴露方式 |
| Environment | ConfigMap / Secret | 配置与密钥分离 |
| `--restart` | RestartPolicy | Always/OnFailure/Never |
| Resource limits | Resource requests/limits | 更精细的 QoS |
| Labels | Labels + Selectors | 资源选择与组织 |

### 10.3 从 Docker 到 K8s 的典型演进路径

```
阶段 1: 单机 Docker
      单台服务器，docker-compose 管理
      → 适合：开发环境、小型项目、MVP

阶段 2: Docker Swarm
      多机集群，Docker 原生编排
      → 适合：中小规模，团队已有 Docker 经验
      → 注意：生态萎缩，社区已基本停止演进

阶段 3: K8s（kubeadm / 托管集群）
      完整容器编排平台
      → 适合：生产级多服务部署
      → 推荐托管方案：EKS / AKS / GKE / TKE

阶段 4: 云原生全家桶
      K8s + Istio (Service Mesh) + Prometheus (监控)
      + ArgoCD (GitOps) + Knative (Serverless)
      → 适合：微服务完备的基础设施
```

### 10.4 面试中 Docker 与 K8s 的衔接问题

- **问：K8s 移除 dockershim 后，Docker 还有用吗？**
  > 仍然有用。Docker 仍然是主流的镜像构建工具（`docker build`）、开发调试工具（`docker run`、`docker exec`），也是了解容器原理的最佳实践工具。K8s 只是不再把 Docker Engine 作为运行时，但 containerd 本身就是从 Docker 项目分出来的。

- **问：会 Docker 还需要学 K8s 吗？**
  > 需要。Docker 的核心原理（Namespace/Cgroup/UnionFS）是 K8s 的基础，而 K8s 是生产环境中管理容器的标准方式。从面试角度来看，高级岗位必然需要同时理解两者——Docker 问的是"容器怎么工作"，K8s 问的是"怎么管好容器"。

- **问：没有 Docker，K8s 怎么运行容器？**
  > K8s 通过 kubelet 调用 CRI 接口 → containerd/CRI-O → runc/runcsc/kata 运行 OCI 标准容器。镜像仍然遵循 OCI Image Spec，所以 Docker 构建的镜像不需要修改即可运行。镜像层面的兼容性没有变化。

---

## 附录

### A. 高频面试题汇总

**基础原理：**
1. Docker 镜像和容器的本质区别是什么？
2. 解释 UnionFS 的写时复制（CoW）流程
3. 容器和虚拟机的根本区别？
4. `docker commit` 做了什么？为什么不推荐？
5. Docker 的 8 个 Namespace 各自隔离什么？

**Dockerfile：**
6. 多阶段构建为什么能减小镜像体积（举例说明）
7. `COPY` 和 `ADD` 的区别？推荐用哪个？
8. 如何加速 Docker 构建缓存命中？
9. alpine、distroless、slim 基础镜像的选型依据？
10. 为什么 `RUN rm -rf /var/lib/apt/lists/*` 放在同一层？

**网络：**
11. docker0 网桥的工作流程
12. 容器间通信的三种方式
13. `-p 8080:80` 底层的 iptables 规则
14. overlay 网络性能瓶颈在哪里？
15. CNI 与 Docker 网络模型的关系

**存储：**
16. Volume 相比 Bind Mount 的 3 个优势
17. 数据库容器应该用 Volume 还是 Bind Mount？
18. tmpfs 适合什么场景？
19. 如何备份和迁移 Volume 数据？
20. overlay2 中删除一个文件实际发生了什么？

**资源限制：**
21. `--memory` 超过限制会发生什么？
22. OOM Score 的计算规则
23. Java 容器中 OutOfMemoryError 的排查思路
24. CPU 限制的三种方式及其区别

**安全：**
25. `--privileged` 为什么是安全红线？
26. Docker 容器如何避免提权攻击？
27. seccomp、AppArmor、SELinux 的关系
28. Rootless Docker 的优缺点
29. 如何保证 Dockerfile 中不泄漏密钥？

**生产：**
30. 容器优雅关闭如何实现？
31. 健康检查的三种探针区别
32. 应用日志应该写文件还是 stdout？
33. 容器中 core dump 怎么获取？
34. 线上容器性能分析的常用工具链？

### B. 常用命令速查

```bash
# 构建
docker build -t myapp:tag .
docker build --no-cache --build-arg VERSION=1.0 -t myapp:latest .
docker buildx build --platform linux/amd64,linux/arm64 -t myapp:multi .

# 运行
docker run -d --name app --restart=always --memory=512m --cpus=0.5 \
  -p 8080:80 -v data:/data myapp:latest

# 调试
docker exec -it app sh
docker logs -f --tail 100 app
docker inspect app | jq '.[0].State'
docker stats app
docker top app
docker diff app

# 清理
docker container prune
docker image prune -a
docker volume prune
docker system prune -a --volumes

# 网络
docker network create --driver bridge --subnet 172.20.0.0/16 mynet
docker network ls
docker network inspect mynet

# Compose
docker compose up -d
docker compose logs -f api
docker compose exec api sh
docker compose down -v
docker compose config
```

### C. 推荐工具链

| 类别 | 工具 | 用途 |
|------|------|------|
| 镜像分析 | dive / docker-slim | 层分析与自动瘦身 |
| 安全扫描 | Trivy / Grype / Snyk | CVE 检测 |
| 镜像签名 | Cosign / Notation | 供应链安全 |
| 镜像仓库 | Harbor / Nexus | 私有仓库 |
| 构建加速 | BuildKit / Kaniko | 高性能镜像构建 |
| 容器调试 | nsenter / ctop / lazydocker | 交互式调试 |
| 资源监控 | cAdvisor / Prometheus + Node Exporter | 集群监控 |
| 日志收集 | fluentd / Filebeat / Loki | 日志管道 |
| 多集群管理 | Rancher / OpenShift | K8s 管理 |
| 配置检查 | hadolint / docker-compose-check | Dockerfile lint |

---

> 本文档持续更新中。建议结合实际项目经验阅读每个章节的"踩坑经验"和"高频面试题"部分，将知识内化为解决真实问题的能力。
>
> 进阶阅读推荐：
> - 《Docker Deep Dive》- Nigel Poulton
> - 《Kubernetes in Action》- Marko Luksa
> - 《Container Security》- Liz Rice
> - 官方文档: docs.docker.com / kubernetes.io
