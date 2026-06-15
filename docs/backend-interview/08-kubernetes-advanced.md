# 高级 Kubernetes 面试知识架构

> 目标受众：高级后端开发（需具备 K8s 部署运维能力）
> 文档定位：面试准备 + 生产实操参考

---

## 目录

1. [架构原理](#1-架构原理)
2. [核心资源](#2-核心资源)
3. [网络模型](#3-网络模型)
4. [存储管理](#4-存储管理)
5. [调度与资源管理](#5-调度与资源管理)
6. [安全机制](#6-安全机制)
7. [可观测性](#7-可观测性)
8. [服务网格](#8-服务网格)
9. [生产运维](#9-生产运维)
10. [对后端开发者的核心要求](#10-对后端开发者的核心要求)

---

## 1. 架构原理

### 1.1 Master 组件

#### API Server（kube-apiserver）

**职责**：Kubernetes 控制面的前端，所有组件和客户端的唯一入口。

- 提供 RESTful API（HTTPS 6443 端口）
- 认证、授权、准入控制（Admission Controller）三道防线
- 将资源状态持久化到 etcd
- 支持 Watch 机制，供各组件监听资源变化

**高频面试题**：

- **Q：API Server 的认证链是怎样的？**
  A：Client → TLS（双向/单向）→ 认证插件（Client Cert/Token/OpenID Connect/Webhook）→ 授权插件（RBAC/ABAC/Webhook）→ 准入控制器（Mutating → Validating）→ etcd

- **Q：API Server 如何处理大规模 Watch 请求？**
  A：使用 etcd 的 Watch 机制 + 本地缓存（ListWatch）。API Server 将 etcd 事件转换为 Kubernetes 资源事件，通过 HTTP/1.1 长连接推送。每个 Watch 连接对应一个 goroutine，大量连接会消耗内存，需配置 `--max-request-inflight` 和 `--max-mutating-request-inflight` 限流。

#### Scheduler（kube-scheduler）

**职责**：将未调度的 Pod 绑定到合适的 Node。

**调度两阶段**：

```
Predicates（过滤） → 选出满足条件的 Node
    ↓
Priorities（打分） → 对 Node 排序，选最优
```

**高频面试题**：

- **Q：Scheduler 的调度框架（Scheduling Framework）包含哪些扩展点？**
  A：QueueSort → PreFilter → Filter → PostFilter → PreScore → Score → NormalizeScore → Reserve → Permit → PreBind → Bind → PostBind。用户可以在这 12 个扩展点注入自定义调度插件。

- **Q：如何保证多个 Scheduler 实例不会重复调度同一个 Pod？**
  A：通过 etcd 的 Lease 对象做 Leader Election，只有一个 Scheduler 实例作为 Leader 执行调度决策。

#### Controller Manager（kube-controller-manager）

**职责**：运行各种控制器，维护集群期望状态。

**核心控制器**：

| 控制器 | 职责 |
|--------|------|
| Node Controller | 节点健康检测与驱逐 |
| Replication Controller | 确保 Pod 副本数 |
| Deployment Controller | 管理滚动更新和回滚 |
| StatefulSet Controller | 管理有状态 Pod 的有序操作 |
| Endpoint Controller | 维护 Service 与 Pod 的映射 |
| Namespace Controller | 管理 Namespace 生命周期 |
| ServiceAccount Controller | 自动创建默认 ServiceAccount |

**高频面试题**：

- **Q：Controller Manager 的 Work Queue 和 Informer 机制如何工作？**
  A：Informer 通过 ListWatch 监听资源变化 → 事件放入 Delta FIFO Queue → Process 函数处理 → 将 key（namespace/name）加入 Work Queue → Worker goroutine 从 Work Queue 取出 key 执行 Sync 逻辑。使用 Rate Limiting Queue 防止失败任务过快重试，支持背压和去重。

#### etcd

**职责**：Kubernetes 的分布式键值存储，存放所有集群状态。

**高频面试题**：

- **Q：etcd 的 Raft 共识算法如何保证一致性？**
  A：Leader 发起提案 → Follower 追加日志 → 多数派确认（Quorum = N/2 + 1）→ Leader 提交 → 通知 Follower 提交。读请求默认也走 Raft（Linearizable Read），确保读到最新数据。

- **Q：etcd 集群的容量规划和性能瓶颈？**
  A：建议使用 SSD，定期 defrag（`etcdctl defrag`）。默认请求大小限制 1.5 MiB。单个 etcd 集群建议 < 8GiB 数据。K8s 3.8+ 支持 etcd v3 的 Compact 自动压缩。监控 `db_total_size` 和 `fsync_duration_seconds` 指标。

### 1.2 Node 组件

#### kubelet

**职责**：每个 Node 上的代理，管理 Pod 生命周期。

**高频面试题**：

- **Q：kubelet 创建 Pod 的完整流程？**
  A：kubelet Watch API Server 发现 Pod 调度到本节点 → 调用 CRI 创建容器 → 调用 CNI 配置网络 → 调用 CSI 挂载存储 → 启动容器 → 执行 Startup Probe → 执行 Readiness Probe → 执行 Liveness Probe（持续）→ 上报 Pod 状态到 API Server。

- **Q：PLEG（Pod Lifecycle Event Generator）问题是什么？如何排查？**
  A：PLEG 是 kubelet 内部模块，周期性重新列举容器状态并与期望状态对比。当容器运行时响应慢（如 Docker 卡死），PLEG 检测超时 → kubelet 误判 Pod 异常 → 重新创建 Pod。排查：检查 `PLEG relist` 耗时、容器运行时性能、磁盘 I/O。

#### kube-proxy

**职责**：实现 Service 的网络代理和负载均衡。

**高频面试题**：

- **Q：kube-proxy 的三种模式（userspace / iptables / IPVS）有什么区别？**
  A：
  - `userspace`（已废弃）：用户态代理，性能差
  - `iptables`（默认）：通过 iptables NAT 规则实现，DNAT + 随机选择，Pod 数量 > 1000 时规则更新延迟高
  - `IPVS`（推荐）：内核态 L4 LB，支持更多调度算法（rr/wrr/lc/dh/sed/nq），高性能，O(1) 复杂度，适合大规模集群

- **Q：kube-proxy 如何保持连接一致性（Session Affinity）？**
  A：设置 Service 的 `sessionAffinity: ClientIP` 和 `sessionAffinityConfig.clientIP.timeoutSeconds`，kube-proxy 在 iptables/IPVS 层面记录源 IP → 后端 Pod 的映射关系。

#### Container Runtime

**高频面试题**：

- **Q：CRI（Container Runtime Interface）的 Shim 层是什么？**
  A：CRI 是 kubelet 与容器运行时的 gRPC 接口。Shim 是适配层，如 dockershim（已移除）、containerd（推荐）、CRI-O。containerd 直接实现 CRI，不再经过 Docker daemon，减少一层调用，性能和稳定性更好。

- **Q：Pod 的本质 —— 如何用底层容器运行时创建 Pod？**
  A：Pod 本质是共享同一 Network Namespace 的容器组。创建流程：创建 Pause 容器（持有 Network/UTS Namespace）→ 创建业务容器（加入 Pause 容器的 Namespace）→ 可选挂载共享 Volume。Pause 容器是 Pod 的生命周期锚点。

### 1.3 声明式 API 与控制循环

**高频面试题**：

- **Q：Kubernetes 控制循环（Control Loop）的通用模式是什么？**
  A：Observe（观察当前状态）→ Diff（对比期望状态）→ Actuate（执行动作缩小差距）。每个 Controller 独立运行控制循环，只关注自己负责的资源类型。例如 ReplicaSet Controller 持续对比 `rs.Status.ReadyReplicas` 与 `rs.Spec.Replicas`。

- **Q：Finalizer 机制有什么用途？**
  A：Finalizer 是 pre-delete 钩子，防止资源被直接删除。删除资源时，API Server 将 `deletionTimestamp` 置为当前时间，但资源保留直到 Finalizer 列表为空。典型场景：PV 保护（防止 PVC 在使用时删除 PV）、外部资源清理（负载均衡器、DNS 记录）。

**YAML 示例 — Finalizer**：

```yaml
apiVersion: v1
kind: Namespace
metadata:
  name: test-ns
  finalizers:
  - kubernetes
```

删除此 Namespace 会卡住直到 Finalizer 被手动移除。

**生产最佳实践**：

- API Server 配置 `--advertise-address` 和 `--secure-port` 绑定到内网，不对外暴露 6443
- etcd 定期备份（`etcdctl snapshot save`），集群 3 或 5 节点奇数部署
- 启用 `NodeLease` 功能：kubelet 通过轻量级 Lease 对象更新心跳，降低 etcd 负载
- 使用 `--feature-gates` 按需开启 Alpha/Beta 功能，生产环境避免 Alpha 功能

---

## 2. 核心资源

### 2.1 Pod

#### Pod 生命周期

**高频面试题**：

- **Q：Pod 的生命周期状态有哪些？**
  A：`Pending` → `Running` → `Succeeded` / `Failed`。详细阶段：`Pending`（未调度或镜像拉取中）→ `ContainerCreating`（容器创建中）→ `Running`（正常运行）→ 终止过程（PreStop Hook → SIGTERM → Grace Period → SIGKILL）。

- **Q：Pod 的 RestartPolicy 对生命周期有何影响？**
  A：
  - `Always`：任何退出都会重启（默认），适合 Web 服务
  - `OnFailure`：非 0 退出码时重启，适合批处理任务
  - `Never`：从不重启，适合一次性 Job

#### 探针（Probe）

**高频面试题**：

- **Q：三种探针的区别和使用场景？**

| 探针 | 时机 | 失败后果 | 最佳场景 |
|------|------|----------|----------|
| Startup Probe | 启动时，成功后不再执行 | 重启容器 | 启动慢的应用（Java、Legacy App） |
| Liveness Probe | 运行期持续检测 | 重启容器 | 检测死锁、死循环 |
| Readiness Probe | 运行期持续检测 | 从 Service Endpoint 移除 | 检测服务是否可接受流量 |

- **Q：Liveness 和 Readiness 探针使用同一个接口会有什么问题？**
  A：如果接口返回 503（Readiness 应该不接收流量），但 Liveness 也会判定失败重启容器。最佳实践：Liveness 检测进程存活（如 `/healthz?live=1`），Readiness 检测业务就绪（如 `/healthz?ready=1`），两个不同的 Endpoint。

**YAML 示例 — 探针配置**：

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: backend-app
spec:
  containers:
  - name: app
    image: myapp:1.0
    ports:
    - containerPort: 8080
    startupProbe:
      httpGet:
        path: /healthz/startup
        port: 8080
      initialDelaySeconds: 3
      periodSeconds: 5
      failureThreshold: 30   # 允许最多 30*5=150s 启动
    livenessProbe:
      httpGet:
        path: /healthz/live
        port: 8080
      periodSeconds: 10
      timeoutSeconds: 3
      failureThreshold: 3
    readinessProbe:
      httpGet:
        path: /healthz/ready
        port: 8080
      periodSeconds: 5
      successThreshold: 1
      failureThreshold: 2
```

#### 资源限制

**高频面试题**：

- **Q：Requests 和 Limits 的语义？实际调度如何起作用？**
  A：
  - `Requests`：调度保证。Scheduler 按 `Requests` 计算 Node 剩余资源。cgroups 的 `cpu.shares` 基于 `cpu request` 比例分配 CPU 时间。
  - `Limits`：硬限制。CPU 限制使用 `cpu.cfs_quota_us` 限流；Memory 限制触发 OOM Killer。
  - 当 Node 内存压力时，优先 OOM Kill 超出 `request` 最多的容器（`/dev/oom_score_adj`）。

- **Q：如何设置合理的 Requests/Limits 比例？**
  A：推荐模型：
  - Web 服务：`limits : requests = 1.5~2`（如 request 1C/2G, limit 2C/4G）
  - 批处理作业：`limits == requests`（Guaranteed QoS），避免因资源争抢被 OOM Kill
  - Java 应用：`limits.memory = request.memory + 25%`，给 JVM Heap 以外的开销留余量

**YAML 示例 — QoS 等级**：

```yaml
# Guaranteed（limits == requests）
resources:
  requests:
    cpu: "1"
    memory: "2Gi"
  limits:
    cpu: "1"
    memory: "2Gi"

# Burstable（requests < limits 或只设置了 requests）
resources:
  requests:
    cpu: "500m"
    memory: "1Gi"
  limits:
    cpu: "1"
    memory: "2Gi"

# BestEffort（不设置 requests 和 limits）
resources: {}
```

**生产最佳实践**：
- 所有容器必须设置 Requests 和 Limits，否则可能导致节点过载
- 使用 `VerticalPodAutoscaler`（VPA）推荐值作为设置参考
- 配置 `--system-reserved` 和 `--kube-reserved` 为系统组件预留资源，防止节点级不稳定

#### 调度策略

**高频面试题**：

- **Q：Pod 如何固定调度到某个 Node？有哪些方案？**
  A：
  1. `nodeSelector`：按 Node Label 简单选择
  2. `nodeAffinity`：更灵活的亲和性，支持硬（required）和软（preferred）规则
  3. `PodAffinity / PodAntiAffinity`：Pod 间的亲和/反亲和
  4. `Taints + Tolerations`：排斥 + 容忍机制
  5. `staticPod`：由 kubelet 直接管理，不受 Scheduler 调度

### 2.2 Deployment

**高频面试题**：

- **Q：Deployment 滚动更新的策略参数如何影响发布速度？**

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: web-app
spec:
  replicas: 10
  strategy:
    type: RollingUpdate
    rollingUpdate:
      maxSurge: 2         # 最多比期望多 2 个 Pod
      maxUnavailable: 1   # 最多允许 1 个 Pod 不可用
  minReadySeconds: 10     # Pod Ready 后等待 10s 才算可用
  revisionHistoryLimit: 5 # 保留 5 个历史版本用于回滚
  template:
    spec:
      containers:
      - name: app
        image: myapp:1.0
        readinessProbe:
          httpGet:
            path: /healthz/ready
            port: 8080
          periodSeconds: 2
```

- **Q：`maxSurge` 和 `maxUnavailable` 配合不同的策略分别适用于什么场景？**

| maxSurge | maxUnavailable | 行为 | 适用场景 |
|----------|---------------|------|----------|
| 25% | 25% | 先启动新 Pod，等新 Pod Ready 后终止旧 Pod | 默认，平滑发布 |
| 0 | 1 | 逐个替换，保证总容量不低于期望值 | 资源有限的集群 |
| 100% | 100% | 先全部删除旧版本，再创建新版本 | 冷发布（Blue-Green 简化版） |
| 1 | 0 | 先创建新 Pod，新 Pod Ready 后再删旧 Pod | 对容量敏感的服务 |

- **Q：如何实现零停机滚动更新？**

**生产最佳实践**：
1. Readiness Probe 必须在滚动更新时准确反映服务状态
2. `minReadySeconds` 设置足够时间，让监控系统确认新版本稳定
3. 启用 PDB（PodDisruptionBudget）防止主动驱逐导致全部不可用
4. 使用 `kubectl rollout status` 监控发布状态
5. 配置 `progressDeadlineSeconds` 让 Deployment 在发布卡死时自动标记失败

```yaml
spec:
  progressDeadlineSeconds: 600  # 10分钟无进展则标记为失败
```

**回滚操作**：

```bash
# 查看历史版本
kubectl rollout history deployment/web-app

# 回滚到上一个版本
kubectl rollout undo deployment/web-app

# 回滚到特定版本
kubectl rollout undo deployment/web-app --to-revision=2
```

### 2.3 StatefulSet

**高频面试题**：

- **Q：StatefulSet 与 Deployment 的核心区别？**

| 特性 | Deployment | StatefulSet |
|------|-----------|-------------|
| Pod 名称 | 随机后缀（如 `web-7d9f8c6b9-a1b2c`） | 有序标识（如 `web-0`, `web-1`） |
| 启动顺序 | 并行 | 顺序（0 → 1 → 2 → ...） |
| 停止顺序 | 无保证 | 逆序（... → 2 → 1 → 0） |
| 存储 | 共享 PVC/无状态 | 每个 Pod 独立 PVC |
| 网络标识 | 随机 IP | 稳定的 DNS（`web-0.nginx.default.svc`） |
| 适用 | 无状态应用 | 有状态应用（数据库、消息队列） |

**YAML 示例 — StatefulSet**：

```yaml
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: mysql
spec:
  serviceName: mysql   # 必须关联 Headless Service
  replicas: 3
  podManagementPolicy: OrderedReady  # 或 Parallel
  updateStrategy:
    type: RollingUpdate
    rollingUpdate:
      partition: 2     # 只更新序号 >= 2 的 Pod（金丝雀发布）
  template:
    spec:
      containers:
      - name: mysql
        image: mysql:8.0
        volumeMounts:
        - name: data
          mountPath: /var/lib/mysql
  volumeClaimTemplates:  # 自动为每个 Pod 创建 PVC
  - metadata:
      name: data
    spec:
      storageClassName: ssd
      accessModes: ["ReadWriteOnce"]
      resources:
        requests:
          storage: 100Gi
```

- **Q：StatefulSet 缩容时，PVC 会怎么处理？**
  A：StatefulSet 缩容只删除 Pod，**不会删除 PVC**。这是为了防止数据丢失。管理员需要手动清理不再需要的 PVC。这种设计意味着缩容后扩容回来，Pod 会挂载之前的数据。

- **Q：`partition` 在金丝雀发布中如何使用？**
  A：当 `partition = N` 时，只有序号 >= N 的 Pod 会更新到新版本。例如 `partition = 2`，3 个副本中只有 `mysql-2` 更新，`mysql-0` 和 `mysql-1` 保留旧版本。验证新版本稳定后，将 `partition` 设为 0 即可更新全部 Pod。

**生产最佳实践**：
- StatefulSet 操作数据库时，结合 Operator（如 `mysql-operator`, `etcd-operator`）管理
- 配置 `persistentVolumeClaimRetentionPolicy`（K8s 1.23+）控制缩容时 PVC 行为
- 更新策略优先使用 `RollingUpdate` 带 `partition` 灰度

### 2.4 DaemonSet

**高频面试题**：

- **Q：DaemonSet 的典型应用场景？调度行为是什么？**
  A：确保每个 Node（或部分 Node）运行一个 Pod 副本。
  - 日志采集：Fluentd / Filebeat / Logstash
  - 监控代理：Prometheus Node Exporter / Datadog Agent
  - 网络插件：Calico / Cilium 的 Node Agent
  - 安全审计：Falco / Sysdig

  DaemonSet 默认在所有 Node 上调度，可以通过 `nodeSelector` / `affinity` / `tolerations` 限制到特定 Node。

- **Q：DaemonSet 的更新策略有哪些？**

```yaml
spec:
  updateStrategy:
    type: RollingUpdate
    rollingUpdate:
      maxUnavailable: 2   # 允许同时最多 2 个 Pod 不可用
```

  K8s 1.26+ 支持 `OnDelete` 策略：手动删除 Pod 后才重建为新版本，适合需要逐个确认的场景。

### 2.5 Job / CronJob

**高频面试题**：

- **Q：Job 的并行处理模式有哪些？**

```yaml
# 1. 非并行 Job（默认）：只运行一个 Pod，Pod 成功结束即 Job 完成
apiVersion: batch/v1
kind: Job
metadata:
  name: single-job

# 2. 固定完成次数的并行 Job
spec:
  completions: 6     # 共需成功 6 次
  parallelism: 2     # 同时运行 2 个 Pod
  template: ...

# 3. Work Queue 模式（每个 Pod 消费队列里的任务）
spec:
  parallelism: 5
  completions: 1     # 每个 Pod 成功 1 次即可，实际结束取决于队列空时退出码
  template: ...
```

- **Q：CronJob 的时间精度和并发策略？**

```yaml
apiVersion: batch/v1
kind: CronJob
metadata:
  name: daily-cleanup
spec:
  schedule: "0 3 * * *"     # 每天凌晨 3 点
  concurrencyPolicy: Forbid # Allow / Forbid / Replace
  startingDeadlineSeconds: 100  # 如果错过调度时间，最多延迟多久执行
  successfulJobsHistoryLimit: 3
  failedJobsHistoryLimit: 1
  jobTemplate:
    spec:
      template:
        spec:
          containers:
          - name: cleanup
            image: busybox
            command: ["sh", "-c", "cleanup.sh"]
          restartPolicy: Never
```

  - `concurrencyPolicy`：
    - `Allow`：允许并发执行（默认）
    - `Forbid`：禁止并发，上一次未完成则不执行
    - `Replace`：取消上一次执行，启动新 Job
  - 时间精度：CronJob 控制器检查最小精度为分钟级，不适用于秒级精确调度

**生产最佳实践**：
- Job 设置 `backoffLimit`（默认 6）防止无限重试
- 批量数据处理 Job 配合 Work Queue（如 RabbitMQ / Redis）使用，提高吞吐
- CronJob 使用 `Forbid` 策略避免定时任务重叠导致数据竞争
- 监控 `failedJobsHistoryLimit` 避免历史记录堆积

---

## 3. 网络模型

### 3.1 CNI 插件

**高频面试题**：

- **Q：Kubernetes 网络模型的核心要求（3 条原则）？**
  A：
  1. 所有 Pod 可以和所有其他 Pod 直接通信（无需 NAT）
  2. 所有 Node 可以直接与所有 Pod 通信（无需 NAT）
  3. Pod 看到的自身 IP 与其他人看到的 IP 相同

- **Q：主流的 CNI 方案及其优缺点？**

| 方案 | 模式 | 优势 | 劣势 |
|------|------|------|------|
| **Flannel** | VXLAN / host-gw | 简单轻量，适合中小集群 | 功能单一，无 NetworkPolicy |
| **Calico** | BGP / IPIP / VXLAN | 高性能，原生 NetworkPolicy，可回传到物理网络 | BGP 配置复杂，大规模需 Route Reflector |
| **Cilium** | eBPF | 超高性能，透明加密，L7 策略，替代 kube-proxy | 内核要求高（>=5.10），技术较新 |
| **Weave** | 自定义 UDP 封装 | 无需外部依赖，自动组网 | 性能较差，不再活跃维护 |
| **Antrea** | OpenFlow / OVS | 兼容 OpenStack，功能丰富 | OVS 运维复杂 |

- **Q：Calico BGP 模式和 VXLAN 模式如何选择？**
  A：
  - **BGP 模式**：直接路由，无额外封装，延迟最低。适合裸金属/同子网集群。需要所有 Node 与 BGP Route Reflector 建立对等连接。
  - **IPIP 模式**：Overlay 封装，允许跨子网通信，性能略低于 BGP。
  - **VXLAN 模式**：Overlay 封装，兼容性更好（通过 UDP 跨网络），但 MTU 开销更大。
  - 推荐：同子网用 BGP，跨子网用 VXLAN。

- **Q：Cilium 的 eBPF 相比传统 iptables 的优势？**
  A：
  - 动态加载，无需重启内核或服务
  - 每个网络包事件可编程，而非静态规则匹配
  - Pod 间通信延迟降低 30-50%
  - 直接替换 kube-proxy，消除 iptables 规则更新延迟问题
  - 原生支持 L3/L4/L7 网络策略和可观测性

### 3.2 Service

**高频面试题**：

- **Q：Service 的四种类型及底层实现？**

```yaml
apiVersion: v1
kind: Service
metadata:
  name: my-service
spec:
  # ClusterIP（默认）
  type: ClusterIP
  clusterIP: 10.96.0.100    # 也可不指定，自动分配

  # NodePort（ClusterIP 的超集）
  type: NodePort
  ports:
  - port: 80          # 集群内访问端口
    targetPort: 8080  # Pod 端口
    nodePort: 30080   # Node 上暴露的端口（30000-32767）

  # LoadBalancer（NodePort 的超集）
  type: LoadBalancer
  loadBalancerIP: 192.168.1.100  # 云厂商支持

  # ExternalName
  type: ExternalName
  externalName: mydb.example.com

  # Headless Service（clusterIP: None）
  clusterIP: None
```

- **Q：ClusterIP 是如何做到 VIP 的？为什么不是传统的虚拟 IP？**
  A：ClusterIP 是 iptables 或 IPVS 规则实现的**伪 VIP**，不是真正的主备切换 VIP。每个 Service 的 ClusterIP 在控制面创建时分配，kube-proxy 在 Node 上写入 iptables DNAT 规则或 IPVS 虚拟服务器规则。流量匹配 `--dst $CLUSTER_IP` 时执行 DNAT 到选中的 Pod IP。

- **Q：Headless Service 的用途？**
  A：`clusterIP: None`，不分配 VIP，DNS A/AAAA 记录直接返回所有 Pod IP。用于：
  - StatefulSet 稳定的网络标识（`pod-name.service-name.namespace.svc.cluster.local`）
  - 应用自行实现服务发现（如 Cassandra、Elasticsearch）
  - 需要直连 Pod 而非负载均衡的场景

**生产最佳实践**：
- 大量 Service（>5000）时使用 IPVS 模式替代 iptables
- 配置 `externalTrafficPolicy: Local` 保留客户端源 IP（但会导致负载不均）
- 使用 `internalTrafficPolicy: Local`（K8s 1.26+）将流量限制在同 Node 内
- 关键应用设置 `publishNotReadyAddresses: true` 谨慎使用

### 3.3 Ingress / Gateway API

**高频面试题**：

- **Q：Ingress 和 Gateway API 的区别？**

```yaml
# Ingress（传统）
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: my-ingress
  annotations:
    nginx.ingress.kubernetes.io/rewrite-target: /
spec:
  ingressClassName: nginx
  rules:
  - host: api.example.com
    http:
      paths:
      - path: /v1
        pathType: Prefix
        backend:
          service:
            name: v1-service
            port:
              number: 80
  tls:
  - hosts:
    - api.example.com
    secretName: tls-secret
```

| 特性 | Ingress | Gateway API |
|------|---------|-------------|
| 标准化 | 功能由 Ingress Controller 注解定义，不统一 | 多层资源（GatewayClass → Gateway → HTTPRoute），标准化 |
| 职责 | 单层资源 | Gateway（基础设施） + HTTPRoute（应用），角色分离 |
| 路由能力 | Host + Path，复杂场景依赖注解 | Header Match、Weight、Mirror 等原生支持 |
| 跨命名空间 | 不直接支持 | 通过 ReferenceGrant 控制 |
| 状态 | stable (v1) | Beta（K8s 1.26+ GA），正在逐步成为 Ingress 演进方向 |

- **Q：Ingress Controller 的工作原理？**
  A：Ingress Controller 是一个运行在集群中的 Pod（如 ingress-nginx），它：
  1. Watch Ingress 资源变化
  2. Watch Service/Endpoint 获取后端 Pod IP
  3. 动态生成配置（nginx.conf / Envoy 配置）
  4. 通过 reload 或 socket 热更新应用配置
  5. 监听宿主机端口（通常 80/443）接收外部流量

**生产最佳实践**：
- Ingress 使用 `ssl-passthrough`（by SNI）或 TLS 卸载两种模式
- 配置 `annotation` 限制请求体大小、超时、速率限制
- 使用 Gateway API 实现更细粒度的流量分割和跨团队协作
- 生产环境 Ingress Controller 至少部署 2 副本 + PDB，绑定到独占 Node

### 3.4 网络策略 NetworkPolicy

**高频面试题**：

- **Q：NetworkPolicy 的隔离模型是什么？**
  A：默认情况下 Pod 接受所有流量。一旦某个 Pod 被 NetworkPolicy selecctor 选中，则遵循"白名单"模式——只允许明确放行的流量，未明确允许的一律拒绝。

- **Q：如何实现"允许来自特定 Namespace 的流量"？**

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-from-monitoring
  namespace: production
spec:
  podSelector:
    matchLabels:
      app: backend
  ingress:
  - from:
    - namespaceSelector:
        matchLabels:
          kubernetes.io/metadata.name: monitoring
    ports:
    - port: 9090
      protocol: TCP
```

**YAML 示例 — 零信任网络策略**：

```yaml
# 默认拒绝所有入站流量
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: default-deny-all
  namespace: production
spec:
  podSelector: {}          # 选中所有 Pod
  policyTypes:
  - Ingress

---
# 只允许 frontend Namespace 访问 backend 的 8080 端口
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-frontend
  namespace: production
spec:
  podSelector:
    matchLabels:
      app: backend
  ingress:
  - from:
    - namespaceSelector:
        matchLabels:
          role: frontend
    ports:
    - port: 8080
```

**生产最佳实践**：
- 采用"默认拒绝 + 显式白名单"的零信任策略
- 使用 CiliumNetworkPolicy（Cilium CRD）支持 L7 层策略（如允许特定 HTTP Path）
- 将 NetworkPolicy 纳入 CI/CD 的合规检查
- 使用 `kubectl netpol` 插件辅助调试策略效果

---

## 4. 存储管理

### 4.1 PV / PVC / StorageClass

**高频面试题**：

- **Q：PV 与 PVC 的生命周期关系？**

```yaml
# StorageClass 定义
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata:
  name: ssd
provisioner: kubernetes.io/gce-pd  # 或 rancher.io/local-path
parameters:
  type: pd-ssd
  replication-type: none
reclaimPolicy: Delete   # 或 Retain
allowVolumeExpansion: true
volumeBindingMode: WaitForFirstConsumer  # 延迟绑定

---
# PVC 声明
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: data-pvc
spec:
  storageClassName: ssd
  accessModes:
  - ReadWriteOnce      # 单节点读写
  resources:
    requests:
      storage: 100Gi
```

- **Q：AccessModes 的区别？**

| 模式 | 说明 | 典型场景 |
|------|------|----------|
| ReadWriteOnce（RWO） | 单节点读写 | 数据库 Pod |
| ReadOnlyMany（ROX） | 多节点只读 | 配置文件共享 |
| ReadWriteMany（RWX） | 多节点读写 | 共享存储、日志聚合 |

- **Q：`volumeBindingMode: WaitForFirstConsumer` 解决什么问题？**
  A：默认 `Immediate` 模式下，PVC 创建后立即绑定 PV，可能绑定到 Pod 调度到的 Node 不可达的存储区域。`WaitForFirstConsumer` 延迟绑定到 Pod 调度后再执行 PV 绑定，确保 PV 与 Pod 在同一个可用区（Zone），对于云平台多区域集群至关重要。

- **Q：reclaimPolicy 为 Retain 时，PV 删除后如何恢复数据？**
  A：Retain 模式下 PV 进入 `Released` 状态，底层存储数据保留。恢复步骤：
  1. 删除 PVC（PV 状态变为 Released）
  2. 手动清理 PV 的 `claimRef`（`kubectl edit pv <pv-name>`，删除 `claimRef` 字段）
  3. PV 状态变为 Available
  4. 创建新 PVC 绑定此 PV

**生产最佳实践**：
- 线上数据库使用 `Retain` 策略防止误删数据
- 开启动态扩容 `allowVolumeExpansion` 并在 PVC 中修改 `storage`
- 非关键应用使用 `Delete` 策略避免存储资源浪费
- 使用 `topology.kubernetes.io/zone` 标签确保 PV 在正确可用区

### 4.2 CSI 驱动

**高频面试题**：

- **Q：CSI（Container Storage Interface）架构如何工作？**
  A：

  ```
  kubelet → CSI Sidecar Container（Node Driver Registrar）
              ↓
          CSI Identity Service（标识驱动信息）
          CSI Controller Service（创建/删除/挂载/快照等控制面操作）
          CSI Node Service（节点上线管/格式化/挂载）
  ```

  CSI 驱动由三个 gRPC 服务组成：
  - **Identity**：返回驱动信息（名称、能力）
  - **Controller**：管理卷的创建、删除、快照、克隆（可选部署为 StatefulSet）
  - **Node**：节点上执行卷的挂载、格式化（部署为 DaemonSet）

- **Q：CSI 相比 FlexVolume 有哪些优势？**
  A：
  - 标准化协议（gRPC），无需编译到 kubelet 二进制中
  - 支持快照、克隆、扩容等高级操作
  - 解耦开发，驱动独立部署升级
  - 安全（非 root 运行，Unix Socket 通信）

### 4.3 ConfigMap / Secret

**高频面试题**：

- **Q：ConfigMap 和 Secret 的使用方式？两者的安全性差异？**

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: app-config
data:
  app.properties: |
    log.level=INFO
    max.connections=100
---
apiVersion: v1
kind: Secret
metadata:
  name: db-credentials
type: Opaque
stringData:
  username: admin
  password: s3cret!  # 不推荐 stringData，应使用 data（base64）

---
apiVersion: v1
kind: Pod
spec:
  containers:
  - name: app
    image: myapp
    env:
    - name: DB_USER
      valueFrom:
        secretKeyRef:
          name: db-credentials
          key: username
    - name: MAX_CONN
      valueFrom:
        configMapKeyRef:
          name: app-config
          key: max.connections
    envFrom:
    - configMapRef:
        name: app-config
    volumeMounts:
    - name: config
      mountPath: /etc/config
    - name: secrets
      mountPath: /etc/secrets
      readOnly: true
  volumes:
  - name: config
    configMap:
      name: app-config
  - name: secrets
    secret:
      secretName: db-credentials
```

- **Q：Secret 真的安全吗？如何加密？**
  A：默认 Secret 仅 base64 编码，不加密。任何人只要有 `get secret` 权限即可查看明文。增强方案：
  - **Encryption at Rest**：配置 kube-apiserver `--encryption-provider-config`，使用 AES-CBC / KMS（推荐）加密 etcd 中的 Secret
  - **External Secret Store**：使用 External Secrets Operator / Sealed Secrets / Vault CSI Provider，Secret 数据不存入 etcd
  - **审计日志**：监控 `get secret` 操作

**生产最佳实践**：
- 永远不要将 Secret 提交到 Git 仓库，使用 External Secrets Operator 同步
- 使用 `immutable: true` 优化 ConfigMap/Secret 性能（K8s 1.21+）
- ConfigMap/Secret 更新后，Pod 需要手动重启或使用 `kubectl rollout restart` 才能加载新值
- 使用 `checksum/config` 注解触发 Deployment 滚动更新：`annotations: { checksum/config: ${sha256sum(config)}}`

---

## 5. 调度与资源管理

### 5.1 调度算法

**高频面试题**：

- **Q：Scheduler 默认的 Predicates（过滤）和 Priorities（打分）有哪些？**

**Predicates（过滤条件）**：

| 谓词 | 作用 |
|------|------|
| PodFitsResources | Node 剩余资源 >= Pod Requests |
| PodFitsHostPorts | Node 端口不冲突 |
| PodMatchNodeSelector | Node Label 满足 nodeSelector 和亲和性 |
| PodToleratesNodeTaints | Pod 容忍 Node 的 Taints |
| CheckNodeCondition | Node 状态正常（Ready, DiskPressure, MemoryPressure） |
| CheckNodeUnschedulable | Node 未被标记为 unschedulable |
| NoDiskConflict | 卷不冲突 |

**Priorities（打分条件）**：

| 优先级 | 权重 | 作用 |
|--------|------|------|
| LeastRequestedPriority | 1 | 优先调度到资源利用率低的 Node（负载分散）|
| BalancedResourceAllocation | 1 | 优先调度到 CPU/内存均衡的 Node |
| NodeAffinityPriority | 2 | 满足 nodeAffinity 规则的加分 |
| SelectorSpreadPriority | 1 | 优先跨 Node/Zone 分散 Pod |
| ImageLocalityPriority | 1 | 优先选择已拉取镜像的 Node |

- **Q：自定义调度器的三种方式？**
  A：
  1. **Scheduler Extender**：通过 HTTP Webhook 扩展过滤/打分逻辑（已不推荐）
  2. **Scheduling Framework 插件**：在扩展点注入 Go 插件（推荐，K8s 1.19+）
  3. **多 Scheduler**：部署额外的调度器（`--scheduler-name=my-scheduler`），Pod 通过 `schedulerName` 指定

### 5.2 亲和性与反亲和性

**高频面试题**：

- **Q：Node Affinity 和 Pod Affinity / Anti-Affinity 的区别？**

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: affinity-demo
spec:
  affinity:
    # Node 亲和性
    nodeAffinity:
      requiredDuringSchedulingIgnoredDuringExecution:  # 硬要求
        nodeSelectorTerms:
        - matchExpressions:
          - key: topology.kubernetes.io/zone
            operator: In
            values:
            - us-east-1a
      preferredDuringSchedulingIgnoredDuringExecution:  # 软要求
      - weight: 100
        preference:
          matchExpressions:
          - key: disk-type
            operator: In
            values:
            - ssd

    # Pod 亲和性：与已运行的 app=cache Pod 尽量同 Zone
    podAffinity:
      preferredDuringSchedulingIgnoredDuringExecution:
      - weight: 100
        podAffinityTerm:
          labelSelector:
            matchExpressions:
            - key: app
              operator: In
              values:
              - cache
          topologyKey: topology.kubernetes.io/zone

    # Pod 反亲和性：app=web 的 Pod 尽量分散到不同 Node
    podAntiAffinity:
      preferredDuringSchedulingIgnoredDuringExecution:
      - weight: 100
        podAffinityTerm:
          labelSelector:
            matchExpressions:
            - key: app
              operator: In
              values:
              - web
          topologyKey: kubernetes.io/hostname
```

- **Q：`requiredDuringSchedulingIgnoredDuringExecution` 和 `requiredDuringSchedulingRequiredDuringExecution` 的区别？**
  A：
  - `IgnoredDuringExecution`：调度时强制执行，调度后即使 Label 变化也不驱逐 Pod
  - `RequiredDuringExecution`：调度时强制执行，调度后 Node Label 变化会驱逐 Pod（未 GA，需开启特定 Feature Gate）

- **Q：topologyKey 的作用是什么？**
  A：topologyKey 定义 Pod 亲和性/反亲和性的拓扑域范围。常见值：
  - `kubernetes.io/hostname`：Node 级别（最细粒度）
  - `topology.kubernetes.io/zone`：可用区级别
  - `topology.kubernetes.io/region`：地域级别

### 5.3 污点与容忍

**高频面试题**：

- **Q：Taints 和 Tolerations 的典型使用场景？**

**核心概念**：
```
Node 打污点：kubectl taint nodes node1 key=value:Effect
Pod 加容忍：spec.tolerations 字段

Effect 类型：
- NoSchedule：不调度到该 Node（已有 Pod 不受影响）
- PreferNoSchedule：尽量不调度
- NoExecute：不调度 + 已有 Pod 如果没有对应容忍会被驱逐
```

**YAML 示例**：

```yaml
# 给 Node 打污点（专用 GPU 节点）
# kubectl taint nodes gpu-node1 gpu=true:NoSchedule

# 对应 Pod 的容忍
apiVersion: v1
kind: Pod
spec:
  tolerations:
  - key: "gpu"
    operator: "Equal"
    value: "true"
    effect: "NoSchedule"
  - key: "node.kubernetes.io/not-ready"
    operator: "Exists"
    effect: "NoExecute"
    tolerationSeconds: 300  # 300 秒后驱逐
```

**典型场景**：

| 场景 | Node Taint | Pod Toleration |
|------|-----------|----------------|
| GPU 专用 | `nvidia.com/gpu=true:NoSchedule` | 只有 GPU 任务的 Pod 添加容忍 |
| 网络敏感 | `network-sensitive=true:NoSchedule` | 延迟敏感的 Pod 添加容忍 |
| 节点维护 | `node.kubernetes.io/unschedulable:NoSchedule` | 控制面自动添加 |
| 节点故障 | `node.kubernetes.io/out-of-disk:NoExecute` | 控制面自动添加 |

**生产最佳实践**：
- 使用 `kubectl taint nodes node1 dedicated=:NoSchedule` 标记独占 Node
- 关键组件（CoreDNS、Ingress Controller）添加 `tolerations` 容忍所有污点

### 5.4 ResourceQuota / LimitRange

**高频面试题**：

- **Q：ResourceQuota 和 LimitRange 的作用范围？**

```yaml
# ResourceQuota —— 命名空间级别总量控制
apiVersion: v1
kind: ResourceQuota
metadata:
  name: dev-quota
  namespace: dev
spec:
  hard:
    requests.cpu: "10"
    requests.memory: "20Gi"
    limits.cpu: "20"
    limits.memory: "40Gi"
    persistentvolumeclaims: "10"
    pods: "50"
    count/services: "20"
    count/secrets: "20"

---
# LimitRange —— 单个 Pod/容器默认值和范围
apiVersion: v1
kind: LimitRange
metadata:
  name: dev-limits
  namespace: dev
spec:
  limits:
  - type: Container
    default:          # 默认 limits
      cpu: "500m"
      memory: "512Mi"
    defaultRequest:   # 默认 requests
      cpu: "100m"
      memory: "128Mi"
    max:              # 最大 limits
      cpu: "2"
      memory: "4Gi"
    min:              # 最小 requests
      cpu: "50m"
      memory: "64Mi"
    maxLimitRequestRatio:
      cpu: "4"        # limits : requests 比值不超过 4
      memory: "4"
```

- **Q：ResourceQuota 与 LimitRange 结合使用的最佳实践？**
  A：LimitRange 设置**硬约束**（最大值、默认值），ResourceQuota 设置**容量上限**。二者配合防止：
  - 单个 Pod 申请过多资源（LimitRange max）
  - Pod 未设置资源限制导致节点不稳定（LimitRange default）
  - 单 Namespace 耗尽集群资源（ResourceQuota hard）
  - `maxLimitRequestRatio` 防止过度超卖

### 5.5 HPA / VPA 自动伸缩

**高频面试题**：

- **Q：HPA（Horizontal Pod Autoscaler）的工作原理？**

```yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: web-app-hpa
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: web-app
  minReplicas: 3
  maxReplicas: 20
  metrics:
  - type: Resource
    resource:
      name: cpu
      target:
        type: Utilization
        averageUtilization: 70
  - type: Resource
    resource:
      name: memory
      target:
        type: Utilization
        averageUtilization: 80
  - type: Pods
    pods:
      metric:
        name: requests_per_second
      target:
        type: AverageValue
        averageValue: 1000
  behavior:
    scaleDown:
      stabilizationWindowSeconds: 300  # 缩容稳定窗口 5 分钟
      policies:
      - type: Pods
        value: 1          # 每次最多缩 1 个 Pod
        periodSeconds: 60
    scaleUp:
      stabilizationWindowSeconds: 0
      policies:
      - type: Percent
        value: 100        # 每次最多扩容 100%
        periodSeconds: 15
```

**计算公式**：

```
desiredReplicas = ceil[currentReplicas × (currentMetricValue / desiredMetricValue)]
```

- 聚合方式：取所有 Pod metric 的平均值（`averageUtilization` 或 `averageValue`）
- 多个 metric 时取计算结果最大值
- 支持自定义 metrics（Prometheus Adapter / Custom Metrics API）

- **Q：VPA（Vertical Pod Autoscaler）的三种更新模式？**
  A：
  - `Off`：只给出推荐值，不自动调整
  - `Initial`：只在 Pod 创建时设置推荐值
  - `Auto`：自动更新并驱逐 Pod 以应用新资源限制（需要与 Cluster Autoscaler 配合）
  - `Recreate`：同 Auto，但驱逐策略一致

**生产最佳实践**：
- HPA 配置 `stabilizationWindowSeconds` 防止频繁扩缩容（Thrashing）
- 结合 **Cluster Autoscaler** 实现 Node 级别自动扩缩容
- HPA + VPA **不要同时用同一个 metric**，否则相互冲突
- 使用 **Custom Metrics**（如 gRPC QPS）比 CPU/Memory 更准确反映业务负载
- 关键业务设置 HPA `minReplicas >= 2` 保证 HA

---

## 6. 安全机制

### 6.1 RBAC

**高频面试题**：

- **Q：RBAC 的四要素及权限检查流程？**

```
User/ServiceAccount → Role/ClusterRole（绑定 perms）← RoleBinding/ClusterRoleBinding
        ↓
API Server 收到请求 → 认证（你是谁）→ 授权（RBAC: 你有权限吗？）→ 准入控制 → etcd
```

**YAML 示例 — 完整的 RBAC 配置**：

```yaml
# 1. 创建 ServiceAccount
apiVersion: v1
kind: ServiceAccount
metadata:
  name: ci-bot
  namespace: ci

---
# 2. 创建 ClusterRole（全局权限集合）
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: deploy-manager
rules:
- apiGroups: ["apps"]
  resources: ["deployments", "deployments/scale"]
  verbs: ["get", "list", "watch", "update", "patch"]
- apiGroups: [""]
  resources: ["pods", "services", "configmaps"]
  verbs: ["get", "list", "watch"]
- apiGroups: ["autoscaling"]
  resources: ["horizontalpodautoscalers"]
  verbs: ["get", "list", "watch", "create", "update", "delete"]

---
# 3. 绑定到命名空间级别（RoleBinding）
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: ci-bot-binding
  namespace: production
subjects:
- kind: ServiceAccount
  name: ci-bot
  namespace: ci
roleRef:
  kind: ClusterRole
  name: deploy-manager
  apiGroup: rbac.authorization.k8s.io
```

- **Q：Role 与 ClusterRole 的区别？RoleBinding 与 ClusterRoleBinding 的区别？**

| 资源 | 作用域 | 举例 |
|------|--------|------|
| Role | 命名空间 | 允许读取 dev 命名空间的 Pod |
| ClusterRole | 集群级别 | 允许读取所有 Namespace 的 Pod、管理 Node、查看 PV |
| RoleBinding + Role | 命名空间 | 将 Role 授予某一命名空间的用户 |
| RoleBinding + ClusterRole | 命名空间 | 复用 ClusterRole 授予命名空间内用户 |
| ClusterRoleBinding + ClusterRole | 全局 | 授予集群管理员 |

**生产最佳实践**：
- 遵循**最小权限原则**，只授予所需的最小 API 操作集合
- 使用 `kubectl auth can-i --as=system:serviceaccount:ns:sa-name --list` 验证权限
- 审计 `system:anonymous` 和 `system:unauthenticated` 的绑定，生产环境应禁止匿名访问
- 使用 `--authorization-mode=Node,RBAC,Webhook` 多级授权链

### 6.2 PodSecurityPolicy / PodSecurity Admission

**高频面试题**：

- **Q：Pod Security Admission（PSA）与废弃的 PSP 的区别？**

```yaml
# K8s 1.23+，Pod Security Admission
apiVersion: v1
kind: Namespace
metadata:
  name: production
  labels:
    pod-security.kubernetes.io/enforce: restricted
    pod-security.kubernetes.io/enforce-version: latest
    pod-security.kubernetes.io/audit: baseline
    pod-security.kubernetes.io/warn: baseline
```

| 特性 | PSP（PodSecurityPolicy） | PSA（PodSecurity Admission） |
|------|------------------------|----------------------------|
| K8s 版本 | 1.6 — 1.21（废弃） | 1.23+（Beta → GA 1.25） |
| 模式 | CRD 资源，复杂 | 内置准入控制器，Label 驱动 |
| 层级 | 无内置层级 | 三个层级：Privileged / Baseline / Restricted |
| 动态审计 | 需要额外工具 | 原生支持 enforce / audit / warn 三种模式 |
| 易用性 | 配置复杂，常导致 Pod 意外被拒 | 简单清晰，逐步收紧 |

**三个层级**：

| 层级 | 说明 | 示例限制 |
|------|------|----------|
| **Privileged** | 无限制 | 可运行特权容器、宿主机网络等 |
| **Baseline** | 最低限制 | 禁止 privileged、hostPID、hostNetwork 等 |
| **Restricted** | 严格限制 | 必须非 root、只读根文件系统、禁止 Capabilities 添加 |

**生产最佳实践**：
- 默认使用 **Baseline** 层级，特定需要特权的 Pod 使用 Privileged
- 逐步采用：先 `audit`（记录违规但不拒绝）→ `warn`（警告）→ `enforce`（强制实施）
- 结合 OPA/Gatekeeper 实现更精细的策略控制

### 6.3 Secret 加密管理

**高频面试题**：

- **Q：etcd 中加密 Secret 的最佳方案？**

```yaml
# EncryptionConfiguration
apiVersion: apiserver.config.k8s.io/v1
kind: EncryptionConfiguration
resources:
- resources:
  - secrets
  providers:
  - kms:
      name: aws-encryption-provider  # 或 gcp/azure/hashicorp-vault
      endpoint: unix:///var/run/kms-plugin/socket.sock
  - aescbc:
      keys:
      - name: key1
        secret: <base64-encoded-32-byte-key>
  - identity: {}  # 回退：不加密（兜底）
```

- **Q：External Secrets Operator 如何工作？**
  A：ESO 是 Kubernetes Operator，从外部 Secret 存储（AWS Secrets Manager / GCP SM / Azure KV / HashiCorp Vault）同步 Secret 到 Kubernetes Secret 资源。

  ```
  ExternalSecret（CRD）
      ↓
  ESO Controller → 从外部存储拉取 Secret
      ↓
  创建/更新 Kubernetes Secret
      ↓
  Pod 正常引用此 Secret
  ```

**生产最佳实践**：
- 生产环境必须配置 `EncryptionConfiguration` 使用 KMS Provider
- 使用 External Secrets Operator 实现 GitOps 安全的 Secret 管理
- 定期轮换加密密钥（KMS Key Rotation）
- 审计 `get secret` 操作，监控异常访问

---

## 7. 可观测性

### 7.1 监控（Prometheus + Grafana）

**高频面试题**：

- **Q：Prometheus Operator 的核心组件和工作原理？**

```
ServiceMonitor（CRD）→ 自动发现 Service，生成抓取目标
    ↓
Prometheus Server → 拉取 /metrics Endpoint
    ↓
Alertmanager → 告警路由 → 通知
    ↓
Grafana → 可视化 Dashboard
```

- **Q：Prometheus 的 Pull 模式和 Push 模式的区别？**

| 特性 | Pull（Prometheus） | Push（VictoriaMetrics / M3DB） |
|------|-------------------|-------------------------------|
| 服务发现 | 由 Prometheus 主动拉取 | 应用自动推送 |
| 防火墙 | 需要访问目标端口 | 目标只连推入口 |
| 生命周期 | 目标消失后不再采集 | 可临时推送，适合短生命周期 Job |
| 存储压力 | 采集端控制节奏 | 推端控制，可能过载 |

- **Q：Kubernetes 核心监控指标有哪些？**

| 层面 | 指标 | 说明 |
|------|------|------|
| **Node** | `node_cpu_seconds_total` | CPU 使用率 |
| | `node_memory_MemAvailable_bytes` | 可用内存 |
| | `node_filesystem_avail_bytes` | 磁盘剩余空间 |
| **Pod** | `container_cpu_usage_seconds_total` | 容器 CPU 使用 |
| | `container_memory_working_set_bytes` | 容器内存使用（OOM 判断依据）|
| | `container_network_receive_bytes_total` | 网络接收字节 |
| **K8s** | `apiserver_request_total` | API Server QPS |
| | `etcd_server_leader_changes_seen_total` | etcd Leader 切换 |
| | `kubelet_pleg_relist_interval_seconds` | PLEG 检测延迟 |

**生产最佳实践**：
- Prometheus 使用 **Persistent Volume** 存储数据，配置合理的 `retention`（建议 15-30 天）
- 使用 **Thanos** 或 **VictoriaMetrics** 实现长期存储和高可用
- 核心告警规则：`KubePodCrashLooping`、`KubeNodeUnreachable`、`KubeHpaMaxedOut`
- Prometheus Server 的 `--storage.tsdb.retention.time` 和 `--storage.tsdb.retention.size` 同时限制

### 7.2 日志收集（EFK / Loki）

**高频面试题**：

- **Q：EFK 与 Loki 的区别？**

| 特性 | EFK（Elasticsearch + Fluentd + Kibana） | Loki + Promtail + Grafana |
|------|----------------------------------------|--------------------------|
| 存储 | Elasticsearch（全文索引） | 只索引 metadata（Labels），不索引日志内容 |
| 查询 | 全文搜索 | LogQL（Label 过滤 + 内容正则） |
| 成本 | 高（存储 + 内存） | 低（比 ES 低 5-10 倍） |
| 扩展 | 复杂 | 简单（无状态） |
| 适合 | 需要复杂全文搜索 | 快速排障、与 Metrics 关联 |

- **Q：Pod 日志采集的两种模式（DaemonSet vs Sidecar）？**

| 模式 | 部署 | 优点 | 缺点 |
|------|------|------|------|
| **DaemonSet** | 每个 Node 一个采集 Agent（Fluentd/Filebeat/Promtail） | 低资源消耗，统一管理 | 无法区分同 Node 不同团队的日志处理需求 |
| **Sidecar** | 每个 Pod 附带日志容器 | 隔离性好，可定制处理逻辑 | 资源消耗大，管理复杂 |

推荐方案：**DaemonSet 模式 + 集中式日志后端**，Sidecar 模式仅用于特殊处理需求。

**生产最佳实践**：
- 应用日志标准输出到 `stdout/stderr`，由容器运行时管理日志文件
- 配置 `logrotate` 防止日志占满磁盘（Docker/containerd 默认配置）
- Loki 配合 **Minio** 或 **S3** 作为对象存储，实现成本优化
- 使用 **结构化日志**（JSON 格式）方便自动解析
- 设置 `namespace` 级别的日志采集策略

### 7.3 链路追踪（Jaeger）

**高频面试题**：

- **Q：Jaeger 在 K8s 中的部署模式？**

**推荐部署**（All-in-One 仅适合开发，生产用微服务模式）：

```
Jaeger Agent（DaemonSet）— 接收 UDP span → Jaeger Collector（Deployment）→ Storage（Elasticsearch / Cassandra）
                                                                            ↓
                                                                       Jaeger Query（Deployment）→ UI
```

- **Q：OpenTelemetry（OTel）与 Jaeger 的关系？**
  A：
  - **OpenTelemetry**：CNCF 统一的遥测数据采集规范（Metrics + Logs + Traces）
  - **Jaeger**：链路追踪的后端存储和可视化平台
  - OTel Collector 可以替代 Jaeger Agent + Collector，将数据发送到 Jaeger 后端
  - 推荐架构：应用 → OTel SDK → OTel Collector → Jaeger/其他后端

### 7.4 健康检查

**高频面试题**：

- **Q：Kubernetes 中的健康检查异常排查思路？**

**常见问题和排查**：

| 现象 | 可能原因 | 排查命令 |
|------|----------|----------|
| Pod CrashLoopBackOff | 探针失败、OOM、应用异常退出 | `kubectl logs` / `kubectl describe pod` |
| ImagePullBackOff | 镜像不存在/认证失败/拉取限流 | `kubectl describe pod` 看 Events |
| RunContainerError | 容器运行时错误 | `kubectl describe pod` + Node 上 crictl logs |
| OOMKilled | 超过内存 Limit | `kubectl describe pod` 看 Last State |
| Pod 一直 Pending | 资源不足、PVC 未绑定、调度失败 | `kubectl describe pod` 看 Events |
| Probe 失败频繁 | 探针参数不合理、应用慢启动 | 调整 `initialDelaySeconds`、`failureThreshold` |

**生产最佳实践**：
- liveness 和 readiness 探针的 Endpoint 分开实现
- 启动慢的应用（Java Spring Boot 启动 30-60s）一定要用 `startupProbe`
- 不要将外部依赖的健康检查放在 liveness 探针中，否则外部故障会导致 Pod 重启
- gRPC 应用使用 `grpc-health-probe` 作为探针

---

## 8. 服务网格

### 8.1 Istio Sidecar 原理

**高频面试题**：

- **Q：Istio Sidecar 注入的原理？Sidecar 劫持流量的机制？**

**自动注入**：
1. 在 Namespace 上打 Label `istio-injection=enabled`
2. Pod 创建时，Mutating Admission Webhook 自动修改 Pod Spec
3. 注入包含 `istio-proxy`（Envoy）和 `istio-init`（Init Container）

**流量劫持**：

```
Init Container（istio-init）：
    ↓
设置 iptables 规则：
- PREROUTING → 所有入站流量重定向到 Envoy（15006）
- OUTPUT → 所有出站流量重定向到 Envoy（15001）
- 排除端口：15090（metrics）、15021（health）

正常流量路径：
Client Pod → Client Envoy（出站劫持）→ 原始目的地 → Server Pod → Server Envoy（入站劫持）→ 应用容器
```

- **Q：Sidecar 模式有什么缺点？如何解决？**
  A：
  - **缺点**：额外的资源消耗（每个 Pod 增加 ~40MB 内存 + proxy 延迟）、注入过程侵入性
  - **解决**：
    - Ambient Mesh（K8s 1.25+，Istio 1.18+）：去 Sidecar，使用 ztunnel 节点代理
    - sidecar 资源调整：`proxy.resources.requests/limits`
    - 非服务网格流量设置 `excludeInboundPorts/excludeOutboundPorts` 减少劫持

### 8.2 流量管理

**高频面试题**：

- **Q：Istio 流量管理的核心 CRD 使用？**

```yaml
# VirtualService —— 定义路由规则
apiVersion: networking.istio.io/v1beta1
kind: VirtualService
metadata:
  name: reviews
spec:
  hosts:
  - reviews
  http:
  - match:
    - headers:
        end-user:
          exact: jason
    route:
    - destination:
        host: reviews
        subset: v2
  - route:
    - destination:
        host: reviews
        subset: v1
      weight: 80
    - destination:
        host: reviews
        subset: v2
      weight: 20

---
# DestinationRule —— 定义子集和负载均衡策略
apiVersion: networking.istio.io/v1beta1
kind: DestinationRule
metadata:
  name: reviews-destination
spec:
  host: reviews
  subsets:
  - name: v1
    labels:
      version: v1
  - name: v2
    labels:
      version: v2
  trafficPolicy:
    loadBalancer:
      simple: ROUND_ROBIN
    connectionPool:
      tcp:
        maxConnections: 100
      http:
        http1MaxPendingRequests: 10
        maxRequestsPerConnection: 10
    outlierDetection:
      consecutive5xxErrors: 5
      interval: 30s
      baseEjectionTime: 3m
```

- **Q：金丝雀发布（Canary Release）在 Istio 中的实现？**
  A：通过 VirtualService 权重路由实现：
  1. 部署新版本 Pod（label `version: v2`），不接入流量
  2. 配置 VirtualService 将 5% 流量路由到 v2
  3. 观察错误率和延迟
  4. 逐步增加 v2 权重（10% → 50% → 100%）
  5. 最终移除 v1

**生产最佳实践**：
- 使用 **Canary** + **Mirroring（流量镜像）** 在不影响生产的情况下验证新版本
- DestinationRule 配置 `circuitBreaker` 防止级联故障
- 配置 `requestTimeout` 和 `retries` 控制超时和重试行为
- 使用 **WasmPlugin** 扩展 Envoy 功能（无需改动 Sidecar）

### 8.3 可观测性

**高频面试题**：

- **Q：Istio 如何提供可观测性数据？**
  A：
  - **Metrics**：Envoy 自动生成标准化指标（请求总数、延迟分布、错误率、流量大小），无需应用改动
  - **Distributed Tracing**：Envoy 自动转发 Trace Header（x-request-id），需配合 Jaeger/Zipkin
  - **Access Log**：Envo y 记录每个请求的日志（来源 IP、方法、路径、响应码、持续时间）

```yaml
# 启用 Istio 全局遥测配置
apiVersion: telemetry.istio.io/v1alpha1
kind: Telemetry
metadata:
  name: mesh-default
  namespace: istio-system
spec:
  # 默认指标
  metrics:
  - providers:
    - name: prometheus
  # 访问日志
  accessLogging:
  - providers:
    - name: envoy
  # 链路追踪
  tracing:
  - providers:
    - name: jaeger
    randomSamplingPercentage: 10.0  # 采样率
```

### 8.4 安全通信 mTLS

**高频面试题**：

- **Q：Istio mTLS 如何工作？**

```
服务 A → Sidecar Envoy（发起 mTLS）
    ↓
认证：使用 SPIFFE 格式身份证书（spiffe://cluster.local/ns/default/sa/sleep）
    ↓
加密：双向 TLS 握手
    ↓
服务 B → Sidecar Envoy（验证身份）
    ↓
授权：基于服务身份的 RBAC 策略
```

**基于身份授权（PeerAuthentication + AuthorizationPolicy）**：

```yaml
# 全局启用 STRICT mTLS
apiVersion: security.istio.io/v1beta1
kind: PeerAuthentication
metadata:
  name: default
  namespace: istio-system
spec:
  mtls:
    mode: STRICT  # STRICT / PERMISSIVE / DISABLE

---
# 细粒度访问控制
apiVersion: security.istio.io/v1beta1
kind: AuthorizationPolicy
metadata:
  name: httpbin-policy
  namespace: default
spec:
  selector:
    matchLabels:
      app: httpbin
  action: DENY
  rules:
  - from:
    - source:
        namespaces: ["unknown"]
    to:
    - operation:
        methods: ["GET"]
```

**生产最佳实践**：
- 逐步启用 mTLS：`PERMISSIVE` → `STRICT`，避免服务炸掉
- 使用 `AuthorizationPolicy` 实现应用层零信任
- 证书自动轮换（默认 24h），可通过 `meshConfig.certificates` 调整

---

## 9. 生产运维

### 9.1 集群规划

**高频面试题**：

- **Q：Kuberenetes 集群规划的要点？**

| 维度 | 建议 |
|------|------|
| **控制面** | 3 或 5 节点（奇数），建议独立节点（不调度业务 Pod）|
| **Worker Node** | 按业务需求规划，集群规模建议 < 5000 Node |
| **etcd** | 单独节点或与控制面同一节点（但磁盘和网络隔离），SSD 必备 |
| **Pod CIDR** | 根据规模规划，常用 /16（> 65K Pod），确保不与 VPC 冲突 |
| **Service CIDR** | 常用 /12，不超 4096 个 Service 时 /16 足够 |
| **DNS** | 部署 CoreDNS，多副本 + HPA |
| **Ingress** | 至少 2 副本 + PDB，绑定到独立 Node 或专用 LB |

- **Q：Pod 数量和 Node 数量的限制？**

| 资源 | Kubernetes 官方上限（v1.28）| 实际建议 |
|------|---------------------------|----------|
| Nodes | 5000 | < 2000 |
| Pods / Node | 110 | 30-50（视资源密度）|
| Pods / Cluster | 150000 | < 50000 |
| Services / Cluster | 10000 | < 5000 |

### 9.2 版本升级策略

**高频面试题**：

- **Q：Kuberentes 版本升级策略和步骤？**

**版本跳跃规则**：只能升一个次版本（如 1.27 → 1.28），跨两个版本需先升到中间版本。

**升级步骤**：

```
1. 准备工作
   - 备份 etcd（etcdctl snapshot save）
   - 验证当前组件兼容性（CRD、Webhook、CNI、CSI）
   - 节点排水（drain）准备

2. 控制面升级（逐个节点）
   - 升级 kube-apiserver（先升级此组件）
   - 升级 kube-controller-manager
   - 升级 kube-scheduler
   - 升级 etcd（如需要）

3. Worker Node 升级（逐个节点）
   - kubectl cordon node → drain
   - 升级 kubelet + kube-proxy
   - kubectl uncordon node

4. 验证
   - 检查所有组件版本：kubectl get nodes
   - 运行 conformance 测试
   - 验证业务应用正常运行
```

**生产最佳实践**：
- 生产集群升级前务必在测试环境验证
- 使用 **Blue-Green 升级**或**滚动升级**，避免所有控制面同时不可用
- 升级过程中保留至少一个 Kubernetes 版本的回滚能力
- 使用 **kubeadm**（自建）或 **托管 K8s**（EKS/AKS/GKE）减少升级复杂度

### 9.3 备份恢复 etcd

**高频面试题**：

- **Q：etcd 备份和恢复的完整命令？**

```bash
# === 备份 ===
ETCDCTL_API=3 etcdctl \
  --endpoints=https://127.0.0.1:2379 \
  --cacert=/etc/kubernetes/pki/etcd/ca.crt \
  --cert=/etc/kubernetes/pki/etcd/server.crt \
  --key=/etc/kubernetes/pki/etcd/server.key \
  snapshot save /backup/etcd-snapshot-$(date +%Y%m%d).db

# === 恢复（在空目录中恢复） ===
ETCDCTL_API=3 etcdctl snapshot restore /backup/etcd-snapshot-20260101.db \
  --data-dir=/var/lib/etcd-restored \
  --initial-cluster=master=https://127.0.0.1:2380 \
  --initial-cluster-token=etcd-cluster-restore \
  --initial-advertise-peer-urls=https://127.0.0.1:2380

# 恢复后重启 etcd，使用新的 --data-dir
```

- **Q：etcd 数据损坏的常见原因和预防？**
  A：
  - **常见原因**：磁盘空间满、磁盘 I/O 延迟过高、etcd 版本不兼容、非正常关闭
  - **预防**：
    - SSD 磁盘 + 独立 dedicated 节点
    - 监控 `etcd_db_total_size_in_bytes` 和 `etcd_server_fsync_duration_seconds`
    - 定期 `etcdctl defrag` 释放空间
    - 配置 `--auto-compaction-retention=5`（保留 5 分钟的 Revision 历史）
    - etcd 集群至少 3 节点

### 9.4 故障排查思路

**高频面试题**：

- **Q：Pod 无法启动的排查路径？**

```
1. kubectl get pod <pod-name>                           # 查看当前状态
2. kubectl describe pod <pod-name>                      # 查看 Events、Conditions
3. kubectl logs <pod-name> [--previous]                  # 查看应用日志
4. kubectl exec -it <pod-name> -- /bin/sh                # 进入容器排查
5. kubectl get events --sort-by='.lastTimestamp'         # 集群级事件

Node 级别排查：
6. kubectl describe node <node-name>                     # Node 状态和资源
7. ssh node → journalctl -u kubelet -f                   # kubelet 日志
8. ssh node → crictl ps / crictl logs <container-id>     # 容器运行时状态
```

- **Q：集群 DNS 解析失败的排查路径？**

```
1. 确认 CoreDNS Pod 运行正常
   kubectl -n kube-system get pod -l k8s-app=kube-dns

2. 确认 CoreDNS 日志无异常
   kubectl -n kube-system logs -l k8s-app=kube-dns

3. 从测试 Pod 验证 DNS 解析
   kubectl run test-dns --image=busybox:1.28 --rm -it -- nslookup kubernetes.default.svc.cluster.local

4. 检查 Service 配置
   kubectl -n kube-system get svc kube-dns

5. 检查 CoreDNS ConfigMap
   kubectl -n kube-system get configmap coredns -o yaml

6. 确认 Node 的 resolv.conf 不能指向 ClusterIP（防止递归循环）
```

- **Q：Node NotReady 怎么排查？**

```
1. kubectl get node <node-name> -o yaml                # 查看 Node Conditions
2. ssh node → systemctl status kubelet                  # kubelet 是否运行
3. ssh node → journalctl -u kubelet -n 100 --no-pager  # 最近的 kubelet 日志
4. ssh node → crictl ps                                 # 容器运行时是否正常
5. ssh node → df -h                                     # 磁盘是否占满？
6. ssh node → top / free -m                             # 内存是否耗尽？
7. ssh node → ping <apiserver-ip>                       # kubelet 到 API Server 网络？
8. ssh node → openssl s_client -connect <apiserver>:6443 # 证书是否过期？
```

### 9.5 GitOps（ArgoCD / Flux）

**高频面试题**：

- **Q：GitOps 的核心原则和常见工具比较？**

**核心原则**：
1. **声明式**：整个系统的期望状态存储在 Git 仓库
2. **唯一事实来源**：Git 仓库是唯一的配置中心
3. **自动同步**：GitOps Operator 自动将集群状态同步到 Git 仓库状态
4. **自愈**：手动修改集群资源会被 Operator 自动恢复

| 特性 | ArgoCD | Flux |
|------|--------|------|
| 架构 | Controller + API Server + UI | 单一的 Controller |
| UI | 内置 Web UI，功能丰富 | Web UI 依赖第三方（如 Weave） |
| SSO | 原生支持 OIDC/OAuth2 | 通过 GitHub/GitLab 外部 |
| Sync 策略 | Manual / Auto / 带 Prune | 类似的策略 |
| 多集群 | 原生支持 | 需要额外配置 |
| 流行度 | 更高 | 也不错 |

**ArgoCD Application YAML 示例**：

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: guestbook
  namespace: argocd
spec:
  project: default
  source:
    repoURL: https://github.com/argoproj/argocd-example-apps.git
    targetRevision: HEAD
    path: guestbook
  destination:
    server: https://kubernetes.default.svc
    namespace: guestbook
  syncPolicy:
    automated:
      prune: true          # 自动删除不再存在的资源
      selfHeal: true       # 自动修复漂移
    syncOptions:
    - CreateNamespace=true # 自动创建命名空间
```

**生产最佳实践**：
- 使用 **Kustomize** 或 **Helm** 管理环境差异（dev/staging/prod）
- 配置 **Image Updater**（ArgoCD Image Updater / Flux Image Automation）自动更新镜像版本
- 使用 **Pull Request** 驱动 GitOps 变更，审批后自动同步
- 设置 **Webhook**（GitHub/GitLab）触发增量同步，避免轮询延迟
- 生产环境使用 **manual sync** + approval，防止自动同步导致故障

---

## 10. 对后端开发者的核心要求

### 10.1 应用如何适配 K8s

**高频面试题**：

- **Q：将现有应用迁移到 K8s 需要做哪些改造？**

#### 1. 健康检查

```yaml
# 后端应用必须实现三个独立健康检查接口
GET /healthz/startup  # 启动检查：进程已启动、基础初始化完成（成功后停止调用）
GET /healthz/live     # 存活检查：进程存活、非死锁（失败→重启）
GET /healthz/ready    # 就绪检查：所有依赖可用、可接收流量（失败→从 LB 移除）
```

**实现要点**：
- `/live` 不要检测外部依赖（数据库、缓存），否则外部故障会导致 Pod 反复重启
- `/ready` 检测所有上游依赖是否就绪
- 启动慢的服务（>30s）必须实现 `startupProbe`

#### 2. 优雅关闭（Graceful Shutdown）

**高频面试题**：

- **Q：K8s Pod 终止流程是什么？应用如何优雅关闭？**

```
kubectl delete pod → API Server 更新 Pod 状态
    ↓
PreStop Hook 开始执行（如果有）
    ↓
SIGTERM 信号发送给主进程（PID 1）
    ↓
Grace Period 倒计时（默认 30s，可配置 `terminationGracePeriodSeconds`）
    ↓
SIGKILL（强制杀死）
```

**应用端的适配**：

```python
# Python（Flask）示例
import signal
import time

def handle_sigterm(*args):
    print("收到 SIGTERM，开始优雅关闭...")
    # 1. 停止接收新请求（从注册中心摘除自身）
    # 2. 等待正在处理的请求完成（不超过 grace period）
    # 3. 关闭数据库连接池
    # 4. 刷新缓存
    print("关闭完成，退出")
    exit(0)

signal.signal(signal.SIGTERM, handle_sigterm)
```

```java
// Spring Boot (application.properties)
server.shutdown=graceful
spring.lifecycle.timeout-per-shutdown-phase=30s

// PreStop Hook 补充
lifecycle:
  preStop:
    exec:
      command:
      - sh
      - -c
      - "sleep 5 && curl -X POST http://localhost:8080/actuator/shutdown"
```

**PreStop Hook 最佳实践**：

```yaml
# 在收到 SIGTERM 前先执行 PreStop，给 Load Balancer 时间移除本 Pod
lifecycle:
  preStop:
    exec:
      command:
      - /bin/sh
      - -c
      - |
        # 1. 通知注册中心下线
        curl -X POST http://consul:8500/v1/agent/service/deregister/myapp
        # 2. 等待 15s 让 LB 完成流量切换
        sleep 15
        # 3. 触发应用优雅关闭（发送 SIGTERM）
        kill -TERM 1
terminationGracePeriodSeconds: 45
```

#### 3. 配置外挂

**高频面试题**：

- **Q：如何实现在不重建镜像的情况下修改配置？**

```yaml
# 错误做法：将配置硬编码在 Dockerfile 或镜像中
# 正确做法：通过 ConfigMap 外挂配置

apiVersion: apps/v1
kind: Deployment
spec:
  template:
    metadata:
      annotations:
        # 配置变更时触发滚动更新（配合 CI/CD 工具更新此值）
        checksum/config: ${CONFIG_SHA256}
    spec:
      containers:
      - name: app
        image: myapp:1.0
        volumeMounts:
        - name: config
          mountPath: /app/config
          readOnly: true
      volumes:
      - name: config
        configMap:
          name: app-config
          items:
          - key: application.yml
            path: application.yml
```

**通过环境变量注入**（适合简单配置）：

```yaml
env:
- name: DB_HOST
  valueFrom:
    configMapKeyRef:
      name: app-config
      key: db_host
- name: DB_PASSWORD
  valueFrom:
    secretKeyRef:
      name: db-secret
      key: password
```

**配置重载方案**：

| 方案 | 说明 | 适合场景 |
|------|------|----------|
| 重启 Pod | `kubectl rollout restart` | 配置变更不频繁 |
| Reload 信号 | 应用监听文件变化或 SIGHUP | 配置变更频繁 |
| Sidecar Reloader | 如 stakater/Reloader，ConfigMap 变更自动触发重启 | 自动化 |
| 配置中心 | Apollo / Nacos / Consul KV | 需要热更新的微服务架构 |

#### 4. 日志 stdout

**高频面试题**：

- **Q：为什么 K8s 要求日志输出到 stdout/stderr？**

```
应用日志 → stdout/stderr
    ↓
容器运行时（containerd）定向到日志文件（/var/log/pods/...）
    ↓
日志采集 Agent（Fluentd/Promtail）读取日志文件
    ↓
日志后端（ES/Loki）归集和索引
```

**反模式**（不要这样做）：
- 日志写入 `/var/log` 或 `/app/logs/app.log` —— 如果已经输出到文件，使用 symlink 到 stdout

```
# 在 Dockerfile 中
# BAD: 应用日志写入文件（需要 sidecar 或额外的 Volume 才能被采集）
# GOOD: 应用直接输出到控制台
CMD ["/bin/sh", "-c", "myapp > /dev/stdout 2>&1"]
```

**输出格式要求**：

```json
// JSON 结构化日志（推荐）
{"timestamp":"2026-06-15T10:30:00Z","level":"INFO","trace_id":"abc123","request_id":"req-456","message":"用户登录成功","duration_ms":45}

// 非结构化日志（可接受，但解析成本高）
"2026-06-15 10:30:00 [INFO] [user-service] 用户登录成功 | trace=abc123"
```

#### 5. 无状态设计

**高频面试题**：

- **Q：无状态设计的 12-Factor App 核心原则在 K8s 中的体现？**

| 12-Factor 原则 | K8s 中如何实现 |
|----------------|----------------|
| **代码库** | 一个应用一个 Git 仓库，CI/CD 构建镜像 |
| **依赖** | 声明在 Dockerfile / Container Image 中 |
| **配置** | 通过 ConfigMap / Secret 注入 |
| **后端服务** | 通过 Service / ExternalName 连接数据库、缓存 |
| **构建、发布、运行** | CI/CD Pipeline → Image Registry → Deployment |
| **进程** | 一个容器一个进程（PID 1 控制）|
| **端口绑定** | 应用通过 port 暴露，Service 发现 |
| **并发** | HPA + 多副本 Deployment |
| **可处置性** | 快速启动 + 优雅关闭 |
| **开发/生产对等** | 使用相同的镜像和配置结构，仅环境值不同 |
| **日志** | stdout/stderr |
| **管理进程** | Job / CronJob |

**有状态设计是否需要 StatefulSet？**

```
需要 StatefulSet：
  - 数据库（MySQL、PostgreSQL、MongoDB）
  - 消息队列（Kafka、RabbitMQ）
  - 分布式存储（Cassandra、Elasticsearch、MinIO）
  - 需要稳定网络标识（etcd、ZooKeeper）

不需要 StatefulSet，用 Deployment + 外部存储：
  - Redis（可以使用 StatefulSet 或 外部托管 Redis）
  - Session 存储（推荐用外部 Redis，不依赖 Pod 本地存储）
  - 文件上传（使用对象存储 S3/MinIO，不上传到 Pod 本地磁盘）
```

### 10.2 进阶话题

**高频面试题**：

- **Q：作为后端开发，你遇到过哪些 K8s 生产事故？如何解决的？**

**典型事故案例**：

| 案例 | 原因 | 解决方案 |
|------|------|----------|
| **滚动更新导致全线崩溃** | readiness probe 返回 200 但应用实际还未就绪 | 增加 startupProbe + 修复 readiness 逻辑 |
| **OOMKilled 频繁** | JVM 未感知容器内存限制，Heap 超出 Limit | 使用 `-XX:+UseContainerSupport`, `-XX:MaxRAMPercentage=75` |
| **DNS 解析缓慢** | CoreDNS 单副本被压垮 | 多副本 + HPA + ndots 配置优化（改为 1 或 3）|
| **iptables 规则满了** | Service 太多，iptables 性能劣化 | 切换到 IPVS 模式 |
| **etcd 空间满** | 未配置自动压缩，历史版本过多 | 配置 `--auto-compaction-retention=5` + 定期 defrag |
| **节点 NotReady 连锁反应** | kubelet PLEG 卡住 → 控制器驱逐所有 Pod | 升级容器运行时 + 设置 PLEG Relist 超时 |

- **Q：你们团队使用 K8s 的成熟度模型是什么？**

**K8s 成熟度模型**（参考 4 阶段）：

```
Level 1: Lift & Shift（容器化）
  - 传统应用直接容器化，简单 Deployment
  - 不太关心资源限制、健康检查

Level 2: 云原生基础
  - 实现健康检查、优雅关闭、资源限制
  - 使用 ConfigMap/Secret 管理配置
  - 日志 stdout + 集中式日志采集

Level 3: 自动化运维
  - CI/CD + GitOps（ArgoCD/Flux）
  - HPA/VPA 弹性伸缩
  - 完善的可观测性（Metrics + Logs + Traces）
  - SLO 驱动告警

Level 4: 高级模式
  - 服务网格（Istio）、安全策略（mTLS + NetworkPolicy）
  - Operator 模式管理复杂有状态服务
  - 混沌工程、故障注入测试
  - FinOps 成本优化
```

---

## 附录

### A. 常用排查命令速查

```bash
# Pod 级别
kubectl get pods -n <ns>                                 # 查看所有 Pod 状态
kubectl describe pod <pod> -n <ns>                       # 查看 Pod 详细信息
kubectl logs <pod> -n <ns> [-c <container>] [--previous] # 查看日志
kubectl exec -it <pod> -n <ns> -- /bin/sh                # 进入容器

# Node 级别
kubectl get nodes                                        # 查看 Node 状态
kubectl describe node <node>                             # 查看 Node 资源详情
kubectl top node                                         # Node 资源排行
kubectl top pod -n <ns>                                  # Pod 资源排行

# 事件
kubectl get events -n <ns> --sort-by='.lastTimestamp'   # 按时间排事件

# 资源操作
kubectl rollout status deployment/<name> -n <ns>        # 发布状态
kubectl rollout undo deployment/<name> -n <ns>          # 回滚
kubectl scale deployment/<name> --replicas=5 -n <ns>    # 扩缩容
kubectl cordon <node> && kubectl drain <node> --ignore-daemonsets  # 节点维护
kubectl uncordon <node>                                  # 节点恢复

# 高级
kubectl get pv -o yaml | grep -A 10 "status:"           # 查看 PV 状态
kubectl api-resources --verbs=list --namespaced         # 列出所有资源类型
kubectl auth can-i <verb> <resource> --as=<user>        # 验证权限
kubectl debug <pod> --image=nicolaka/netshoot:latest    # 临时调试容器

# etcd
ETCDCTL_API=3 etcdctl endpoint health                   # etcd 健康检查
ETCDCTL_API=3 etcdctl member list                       # etcd 成员列表
ETCDCTL_API=3 etcdctl endpoint status -w table          # etcd 状态
ETCDCTL_API=3 etcdctl snapshot save /backup/snap.db     # etcd 快照备份
```

### B. 面试高频题目汇总

按难度分级：

**初级（P1）**：
- Pod 的生命周期有哪些？
- Deployment 和 StatefulSet 的区别？
- Service 有哪些类型？
- ConfigMap 和 Secret 的区别？
- kubectl 常用命令说出 5 个？

**中级（P2）**：
- HPA 的工作原理？计算公式？
- RBAC 的角色绑定关系？
- NetworkPolicy 如何实现隔离？
- Pod 亲和性和反亲和性如何使用？
- PV 的 reclaimPolicy 有哪些？

**高级（P3）**：
- Scheduler 调度框架的扩展点有哪些？
- 如何实现零停机滚动更新？
- etcd Raft 如何保证一致性？
- Istio Sidecar 劫持流量的原理？
- 如何排查 CoreDNS 解析失败？
- 应用如何适配 K8s 实现优雅关闭？

**资深（P4）**：
- 设计一个支持多可用区的 K8s 集群架构
- 如何实现 GitOps 工作流？组件交互流程？
- Service Mesh 相比传统 Ingress 的优势和缺点？
- 如何处理 etcd 数据损坏恢复？
- 大规模集群（5000+ Node）的网络瓶颈和优化方案？
- 如何设计一个 K8s 原生 Operator？

---

> 文档版本：v1.0
> 最后更新：2026-06-15
> 维护者：K8s 面试知识架构组
