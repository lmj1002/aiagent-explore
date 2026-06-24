# 高级 Kafka 面试知识架构

> 目标读者：高级后端开发 / 系统架构师
> 本文从源码、原理、生产实践三个维度深度剖析 Apache Kafka，涵盖高频面试题与最佳实践。

---

## 目录

1. [基础概念](#1-基础概念)
2. [存储原理](#2-存储原理)
3. [生产者原理](#3-生产者原理)
4. [消费者原理](#4-消费者原理)
5. [副本机制](#5-副本机制)
6. [控制器与协调器](#6-控制器与协调器)
7. [KRaft 模式](#7-kraft-模式)
8. [性能调优](#8-性能调优)
9. [生产运维](#9-生产运维)
10. [与 RabbitMQ 场景对比](#10-与-rabbitmq-场景对比)

---

## 1. 基础概念

### 1.1 消息模型

Kafka 采用 **发布-订阅（Pub-Sub）** 消息模型，以 Topic 为逻辑单位组织消息。

**核心抽象：**

```
Producer → Topic[Partition0, Partition1, Partition2] → Consumer Group
```

- **Producer**：发布消息到指定 Topic
- **Consumer**：从 Topic 订阅消息，以 Consumer Group 为单位消费
- **Broker**：Kafka 服务器节点，存储消息数据
- **Topic**：消息的逻辑分类
- **Partition**：Topic 的分片，是消息存储的最小有序单元
- **Consumer Group**：多个 Consumer 组成一个逻辑消费组，组内各 Consumer 消费不同 Partition

### 1.2 Topic / Partition / Broker / Consumer Group

**面试高频题：**

> Q: Kafka 为什么使用 Partition？Partition 数量如何确定？

A: Partition 是 Kafka 实现水平扩展和并行消费的核心机制。
- **并行度**：一个 Partition 只能被一个 Consumer 消费，Partition 数决定了 Consumer Group 内最大并行度
- **存储扩展**：Partition 分布在多个 Broker 上，突破单机磁盘容量限制
- **有序性保证**：单个 Partition 内消息有序，跨 Partition 无序

Partition 数量确定原则：
- 下限：`max(预期峰值吞吐量 / 单 Partition 吞吐量, 预期消费者数量)`
- 上限：不超过 Broker 总磁盘数 * 磁盘 I/O 能力的合理倍数（建议单 Broker 不超过 2000 个 Partition）
- 经验公式：`Partition数 = (目标吞吐量 MB/s) / (单 Partition 吞吐量 MB/s)`
- 注意：Partition 越多，选举、重平衡、元数据管理的开销越大

---

**源码级原理：**

`kafka.log.Log` 是 Partition 的日志表示，每个 Partition 对应一个目录（`<topic>-<partitionId>`），内部包含多个 LogSegment：

```go
// 等价概念（Go 伪代码，对应 Kafka Scala 源码 kafka.log.Log）
type PartitionLog struct {
    Dir                  string            // 日志目录: /data/kafka/topics/my-topic-0/
    Config               LogConfig
    RecoveryPoint        int64
    Segments             map[int64]*LogSegment // baseOffset → Segment
    ProducerStateManager *ProducerStateManager // 幂等/事务状态管理
}
```

### 1.3 投递语义（Delivery Semantics）

| 语义 | 生产者设置 | 消费者设置 | 消息可能 |
|------|-----------|-----------|---------|
| At Most Once | `acks=0` | 不等偏移量提交 | 丢失 |
| At Least Once | `acks=all` | 提交偏移量后处理 | 重复 |
| Exactly Once | `acks=all` + `enable.idempotence=true` | 事务或幂等消费 | 恰好一次 |

**面试高频题：**

> Q: Exactly Once 在 Kafka 中如何实现？

A: Exactly Once 是生产者幂等性 + 事务 API 的组合实现：

1. **生产者幂等性**（`enable.idempotence=true`）：
   - 每个 Producer 分配唯一的 `producerId`（PID）
   - 每条消息附带单调递增的 `sequence number`
   - Broker 端按 `<PID, Partition, SeqNo>` 去重
   - 网络重试导致的重复消息被 Broker 自动过滤

2. **事务（`transactional.id`）**：
   - 跨 Partition/跨 Topic 的原子写入
   - 使用 `__transaction_state` 内部 Topic 记录事务状态
   - 两阶段提交：`prePareCommit` → `commit`
   - 消费者需设置 `isolation.level=read_committed` 才能读到已提交事务消息

**生产最佳实践：**

- 大多数场景使用 **At Least Once** + 下游幂等去重即可
- Exactly Once 会引入约 20% 的性能开销，仅在金融级场景使用
- 事务消息的 Producer Session 超时（`transaction.timeout.ms`）默认 60000ms，大事务需要调大

---

## 2. 存储原理

### 2.1 日志存储（Log Segment）

**物理结构：**

```
/topics/__consumer_offsets-0/
├── 00000000000000000000.log       # 消息数据
├── 00000000000000000000.index     # 偏移量索引（稀疏）
├── 00000000000000000000.timeindex # 时间戳索引
└── 00000000000000000059.snapshot  # 生产者状态快照
```

- LogSegment 是 Kafka 存储的最小物理单元，默认 1GB 或 `log.segment.bytes` 配置
- 活跃 Segment（active segment）可写，历史 Segment 只读
- 每个 Segment 的命名以该 Segment 第一条消息的偏移量为基准（20 位补零）

**面试高频题：**

> Q: Kafka 为什么能够做到毫秒级消息写入？为什么即使磁盘读写也能这么快？

A: 核心原因：

1. **顺序 I/O**：Kafka 写入采用追加写，充分利用磁盘顺序读写性能（顺序写约 600 MB/s，随机写约 100 KB/s）
2. **Page Cache 利用**：写入先落到 OS Page Cache，异步刷盘，避免直接磁盘 I/O
3. **零拷贝**：消费者读取时通过 `sendfile` 系统调用，数据直接从 Page Cache 发送到网卡
4. **批量处理**：Producer 批次发送，Broker 批次写入，Consumer 批次拉取

### 2.2 索引文件（偏移量索引 & 时间戳索引）

**偏移量索引（`.index`）：**

- 稀疏索引，默认每写入 4KB 消息数据记录一条索引（`log.index.interval.bytes`）
- 映射关系：`<相对偏移量, 物理位置>`
- 定位过程：二分查找索引文件 → 拿到物理位置范围 → 顺序扫描 `.log` 文件

```
索引示例（稀疏结构）：
相对偏移量  | 物理位置
0          | 0
100        | 4096
200        | 8192
```

**时间戳索引（`.timeindex`）：**

- 映射关系：`<时间戳, 相对偏移量>`
- 用于按时间戳查找消息（如 `--offset --timestamp` 重设消费者偏移量）
- 每条索引记录占用 12 字节（8 字节时间戳 + 4 字节偏移量）

**面试高频题：**

> Q: 如果索引文件不存在或被损坏，Kafka 怎么恢复？

A: Kafka 通过**重建索引**机制恢复：扫描 `.log` 文件中消息的 `offset` 和 `timestamp` 字段，重新生成索引文件。这也是为什么 `.log` 文件已经包含完整数据，索引只是加速文件。

### 2.3 日志清理与压缩（Log Cleanup & Compaction）

两种策略，由 `log.cleanup.policy` 控制：

| 策略 | 配置值 | 行为 |
|------|-------|------|
| 删除（DELETE） | `delete` | 根据保留时间或大小删除老 Segment |
| 压缩（COMPACT） | `compact` | 保留每个 Key 的最新版本，丢弃旧版本 |

**日志压缩原理：**

```
原始日志:
offset 10: key=user1, value=A
offset 11: key=user2, value=B
offset 12: key=user1, value=C   ← 覆盖 offset 10
offset 13: key=user3, value=D

压缩后:
offset 11: key=user2, value=B
offset 12: key=user1, value=C
offset 13: key=user3, value=D
```

- 使用 **Cleaner 线程**独立执行压缩
- `min.cleanable.dirty.ratio` = 0.5（默认），脏数据占比超过 50% 触发压缩
- 压缩后的 Log 仍然保持与原 Log 相同的偏移量（offset 不连续）

**生产最佳实践：**

- 日志压缩适用于**KV 语义**的数据，如用户配置、地址簿等
- 普通日志使用 **DELETE** 策略
- 不要对高吞吐的普通业务 Topic 启用 `compact`
- `log.retention.bytes` 和 `log.retention.hours` 配合使用，优先满足较严格的条件

### 2.4 零拷贝（Zero Copy / sendfile）

**面试高频题：**

> Q: Kafka 消费消息时如何实现零拷贝？相比传统方式节省了什么？

A: 传统文件读取到网络发送的路径：

```
磁盘 → 内核缓冲区 → 用户缓冲区 → Socket 缓冲区 → 网卡
（DMA读取）  （CPU拷贝）   （CPU拷贝）    （DMA写入）
```

共经历 **4 次上下文切换 + 4 次数据拷贝**。

Kafka 使用 `sendfile`（`FileChannel.transferTo`）后的路径：

```
磁盘 → 内核缓冲区 → 网卡
（DMA读取）        （DMA写入）
```

共经历 **2 次上下文切换 + 3 次数据拷贝（或 1 次，如果网卡支持 scatter-gather）**。

**关键代码：**

```go
// 零拷贝核心：Linux sendfile 系统调用（Go net 包底层自动使用）
// 等价于 Java NIO FileChannel.transferTo()
// Go 中通过 os.File + net.Conn 组合，运行时自动选择 sendfile
f, _ := os.Open(logSegmentPath)
defer f.Close()
// net.Conn.ReadFrom(f) 内部触发 sendfile，数据不经过用户态
conn.(io.ReaderFrom).ReadFrom(f)

// 路径：磁盘 →(DMA)→ 内核页缓存 →(sendfile)→ 网卡，跳过用户态拷贝
```

**生产最佳实践：**

- Kafka Broker JVM 堆外内存（off-heap）数据不走零拷贝，因为需要通过 Java 堆
- 零拷贝对**压缩消息**同样有效，消息在发送前已压缩，消费者解压即可
- `file.0.0.0` 模式的 `.log` 文件直接内存映射（Memory Mapped），提供更快随机访问

---

## 3. 生产者原理

### 3.1 分区策略

**默认分区器（DefaultPartitioner）：**

- **Key 不为 null**：`murmur2(key) % numPartitions` 确定 Partition
- **Key 为 null**：Round-Robin（粘性分桶策略 Sticky Partitioner，Kafka 2.4+）
- **自定义分区器**：实现 `Partitioner` 接口，通过 `partitioner.class` 配置

**粘性分桶（Sticky Partitioner）演进：**

```
旧版本（2.4 之前）：每次 send 轮询一个 Partition，产生大量小批次
新版本（2.4+）：在一个批次未满期间，所有无 Key 消息发送到同一 Partition，提高批次利用率
```

**面试高频题：**

> Q: 如何保证有序消息？如何保证将同一业务实体路由到同一 Partition？

A: 两种方式：

1. **Key 哈希**：为同一业务实体（如 orderId）设置相同的 Key，保证相同 Key 的消息进入同一 Partition
2. **自定义分区器**：实现 `Partitioner.partition()` 方法，自定义路由逻辑

关键约束：
- 有序性只能在**单 Partition 内**保证
- 增加 Partition 数量会破坏既有路由关系，需谨慎操作

### 3.2 消息批次与压缩

**生产者内存模型：**

```
Producer 实例
├── accumulator: BufferPool       // 消息缓冲区
│   ├── batch1 (TopicPartition-0)  // 未压缩
│   ├── batch2 (TopicPartition-0)  // 压缩后
│   └── batch3 (TopicPartition-1)
└── sender: SenderThread          // 后台发送线程
```

- `buffer.memory`：生产者缓冲区总大小（默认 32MB）
- `batch.size`：单个批次最大字节数（默认 16KB）
- `max.request.size`：单次请求的最大字节数（默认 1MB）

**压缩算法对比：**

| 算法 | 压缩比 | CPU 开销 | 速度 | 适用场景 |
|------|-------|---------|------|---------|
| gzip | 高 | 高 | 慢 | 带宽受限、高压缩比要求 |
| snappy | 中 | 低 | 快 | 吞吐优先，默认推荐 |
| lz4 | 中 | 低 | 快 | 吞吐优先，与 snappy 相近 |
| zstd | 最高 | 中 | 中快 | 追求极致压缩比，3.0+ 推荐 |

**生产最佳实践：**

- Producer 端压缩还是 Broker 端压缩？
  - **Producer 端压缩**（推荐）：`compression.type=gzip|snappy|lz4|zstd`
  - Broker 端压缩：`compression.type=producer`（默认），由 Producer 决定
  - 如果 Broker 需要重新压缩（`compression.type` 与 Producer 不同），会增加 CPU 负载
- 压缩 + 批处理结合使用效果最好
- `max.request.size` 需同步调整消费者 `max.partition.fetch.bytes`

### 3.3 幂等 Producer

**开启方式：** `enable.idempotence=true`

**原理：**

```go
// 幂等 Producer 请求协议字段（伪代码，对应 Kafka ProducerRequest）
type ProducerRequest struct {
    ProducerID     int64         // 服务端分配的 PID（首次请求返回）
    ProducerEpoch  int16         // 每次 Producer 初始化递增，用于 fencing 旧 Producer
    SequenceNumber int32         // 按 Partition 单调递增，从 0 开始
    Data           []RecordBatch
}
// Broker 端：接受条件 sequenceNumber == expectedSeq+1，否则拒绝（重复或乱序）
```

- Broker 端维护 `<PID, Partition>` 维度的 `sequenceNumber` 状态
- `sequenceNumber` = `expectedSeq + 1` 时接受，否则拒绝（重复或乱序）
- Producer 崩溃恢复后获取新 PID 的 `producerEpoch`，旧 Producer 被 fencing

**面试高频题：**

> Q: 幂等 Producer 的局限性是什么？

A:
1. **只能保证单 Partition 内 Exactly Once**：跨 Partition 幂等需要事务 API
2. **只能保证 Producer — Broker 间的 Exactly Once**：Consumer 端仍可能重复投递
3. **只能在单 Session 内去重**：Producer 重启后 PID 变化，无法去重旧 PID 的未决消息
4. **Broker 端状态不会无限保留**：`transaction.state.log.segment.bytes` 控制，超额后清理可能导致去重失败

### 3.4 事务消息

**配置参数：**

```properties
# Producer 端
transactional.id=my-transactional-id  # 唯一业务标识
enable.idempotence=true               # 事务必须开启幂等
transaction.timeout.ms=60000

# Consumer 端
isolation.level=read_committed        # 只消费已提交事务消息
```

**事务 API：**

```go
// Go kafka 客户端事务示例（使用 IBM/sarama 库）
producer, _ := sarama.NewSyncProducer(brokers, config) // config.Producer.Transaction.ID = "my-tx-id"

producer.BeginTxn()
producer.SendMessage(&sarama.ProducerMessage{Topic: "topic-a", Key: sarama.StringEncoder(key), Value: sarama.ByteEncoder(value)})
producer.SendMessage(&sarama.ProducerMessage{Topic: "topic-b", Key: sarama.StringEncoder(key), Value: sarama.ByteEncoder(value)})
// 将消费者偏移量纳入事务（消费-转发场景）
producer.AddOffsetsToTxn(offsets, consumerGroup)

if err != nil {
    producer.AbortTxn() // 回滚
} else {
    producer.CommitTxn() // 提交
}
```

**事务状态流转：**

```
EMPTY → ONGOING → COMMITTING_TRANSACTION → COMMITTED
     → ONGOING → ABORTING_TRANSACTION  → ABORTED
```

- 事务协调器（Transaction Coordinator）负责管理状态
- 事务日志存储在 `__transaction_state` 内部 Topic（默认 50 个 Partition）
- `transaction.max.timeout.ms` 限制 Producer 的最大事务超时

**生产最佳实践：**

- 事务消息用 `read_committed` 消费者会增加 Broker 端额外过滤开销
- 高吞吐场景优先考虑**下游幂等**而非事务
- 事务超时不要设置过大（建议 ≤ 120s），否则长时间未决事务会阻塞消费

---

## 4. 消费者原理

### 4.1 消费者组重平衡（Rebalance）

**触发条件：**

1. 新 Consumer 加入组
2. Consumer 主动离开（`leaveGroup`）或超时（`session.timeout.ms`）
3. Partition 数量变化
4. Topic 订阅正则匹配到新增/删除 Topic

**重平衡策略（`partition.assignment.strategy`）：**

| 策略 | 类名 | 特点 |
|------|------|------|
| Range（默认） | `RangeAssignor` | 按 Topic 顺序连续分配，可能不均匀 |
| RoundRobin | `RoundRobinAssignor` | 轮询分配，较均匀 |
| Sticky | `StickyAssignor` | 在 Rebalance 时尽量保持已有分配，2.3+ 推荐 |
| Cooperative Sticky | `CooperativeStickyAssignor` | 增量式 Rebalance，避免 Stop The World，3.0+ 推荐 |

**Eager vs. Cooperative Rebalance：**

```
Eager Rebalance（旧）:
全体 Consumer 撤销所有 Partition → 停止消费 → 重新分配 → 恢复消费
                 [stop the world]

Cooperative Rebalance（新，Kafka 2.3+）:
Consumer1 撤销部分 Partition → 重新分配 → Consumer2 接管
                [增量式，不停顿]
```

**面试高频题：**

> Q: 如何减少 Rebalance 对业务的影响？如何诊断频繁 Rebalance？

A:

**减少影响的措施：**
1. 使用 `CooperativeStickyAssignor` 替代 Range/RoundRobin
2. 合理设置 `session.timeout.ms`（默认 45s）和 `heartbeat.interval.ms`（默认 3s）
3. 避免 Consumer 在 polls 间隔内处理过长逻辑，或适当增大 `max.poll.interval.ms`
4. `group.initial.rebalance.delay.ms` 设置合理值（如 3s）避免空转 Topic 频繁 Rebalance
5. 静态成员 `group.instance.id` 让 Consumer 以固定 ID 注册，重启不触发 Rebalance

**诊断方法：**
1. 监控 `kafka.consumer:type=consumer-coordinator-metrics` 中的 `rebalance-total` 和 `rebalance-rate-per-hour`
2. 检查 Broker 日志 `[GroupCoordinator ...]: ...` 中的 Rebalance 原因
3. 检查 Consumer 端 `max.poll.interval.ms` 是否超过实际处理时间

### 4.2 Coordinator

**面试高频题：**

> Q: GroupCoordinator 是如何选举出来的？消费者如何找到它的 Coordinator？

A:

**确定 Coordinator 的流程：**

```
// 1. 消费者计算 group.id 的哈希值
groupIdHash = hash("my-consumer-group") % groupMetadataTopicPartitionCount

// 2. 确定 __consumer_offsets 的目标 Partition
coordinatorPartition = groupIdHash % __consumer_offsets 的 Partition 数（默认50）

// 3. 查询该 Partition 的 Leader 所在的 Broker → 这就是 GroupCoordinator
```

**Coordinator 的职责：**
- 管理消费者组成员注册与注销
- 触发和协调 Rebalance
- 管理偏移量提交和读取（存储在 `__consumer_offsets`）
- 管理事务状态（Transaction Coordinator 共用部分逻辑）

**源码位置：**

```scala
// kafka.coordinator.group.GroupCoordinator.scala
class GroupCoordinator(
  brokerId: Int,
  groupConfig: GroupConfig,
  replicaManager: ReplicaManager,
  offsetConfig: OffsetConfig,
  groupManager: GroupMetadataManager,
  heartbeatPurgatory: DelayedOperationPurgatory[DelayedHeartbeat],
  rebalancePurgatory: DelayedOperationPurgatory[DelayedRebalance],
  time: Time,
  metrics: Metrics
) extends Logging {
  // ...
  def handleJoinGroup(...): Unit   // 处理加入组请求
  def handleSyncGroup(...): Unit   // 处理同步组请求
  def handleLeaveGroup(...): Unit  // 处理离开组请求
  def handleCommitOffsets(...): Unit
  def handleFetchOffsets(...): Unit
}
```

### 4.3 偏移量管理

**存储机制：**

- 2.0+ **默认**提交到 `__consumer_offsets` 内部 Topic（而非 ZooKeeper）
- 偏移量提交 Key：`<groupId, topic, partition>`
- 偏移量提交 Value：`<offset, metadata, timestamp>`

**提交方式：**

| 方式 | API | 说明 |
|------|-----|------|
| 自动提交 | `enable.auto.commit=true` | 定时提交，`auto.commit.interval.ms` 默认 5s |
| 手动同步提交 | `consumer.commitSync()` | 阻塞直到提交成功 |
| 手动异步提交 | `consumer.commitAsync()` | 非阻塞，回调处理失败 |
| 提交指定偏移 | `consumer.commitSync(offsetsMap)` | 精细控制，需要自定义偏移量 |

**面试高频题：**

> Q: `commitAsync` 和 `commitSync` 应该如何配合使用？

A: 推荐模式：正常处理循环使用 `commitAsync`，关闭 Consumer 前的最终提交使用 `commitSync`。

```go
// 正常循环用异步提交（非阻塞，高吞吐）
for {
    records, _ := consumer.ReadMessage(ctx)
    process(records)
    consumer.CommitOffsets() // sarama: 异步批量提交
}

// 关闭前用同步提交确保最终偏移量落地
defer func() {
    consumer.CommitOffsets() // 同步等待完成
    consumer.Close()
}()
```

### 4.4 再均衡监听器（RebalanceListener）

**面试高频题：**

> Q: 如何在 Rebalance 时优雅地处理未完成的消息？请给出代码模式。

A: 使用 `ConsumerRebalanceListener`，在分区撤销前（`onPartitionsRevoked`）提交偏移量，在分区分配后（`onPartitionsAssigned`）重新初始化资源。

```go
// sarama ConsumerGroup Handler 实现再均衡回调
type orderHandler struct {
    currentOffsets map[string][]*sarama.PartitionOffsetManager
}

// Rebalance 前触发：提交偏移量防止重复消费
func (h *orderHandler) Cleanup(sess sarama.ConsumerGroupSession) error {
    sess.Commit() // 提交当前所有偏移量
    // 清理分区相关资源（本地状态、数据库连接等）
    return nil
}

// 新分区分配后触发：恢复处理状态
func (h *orderHandler) Setup(sess sarama.ConsumerGroupSession) error {
    for _, partitions := range sess.Claims() {
        for _, partition := range partitions {
            // 从外部存储恢复偏移量，覆盖 Broker 端记录
            offset := externalStore.ReadOffset(partition)
            sess.ResetOffset("topic", partition, offset, "")
        }
    }
    return nil
}

func (h *orderHandler) ConsumeClaim(sess sarama.ConsumerGroupSession, claim sarama.ConsumerGroupClaim) error {
    for msg := range claim.Messages() {
        process(msg)
        sess.MarkMessage(msg, "") // 标记消费，下次 Commit 生效
    }
    return nil
}
```

**生产最佳实践：**

- **至少一次语义**：业务处理成功后再提交偏移量
- **避免重复处理**：如果业务处理在 commit 之后、存储完成之前失败，会触发重复消费，需要**下游幂等**
- **偏移量回退**：通过 `consumer.seek()` 可以回溯到任意偏移量重放消息

---

## 5. 副本机制

### 5.1 ISR / OSR

**面试高频题：**

> Q: 解释 ISR、OSR、AR 的概念。ISR 的判定标准是什么？

A:

- **AR（Assigned Replicas）**：Partition 的所有副本列表
- **ISR（In-Sync Replicas）**：与 Leader 保持同步的副本集合
- **OSR（Out-of-Sync Replicas）**：与 Leader 不同步的副本集合，即 AR - ISR

**ISR 判定标准：**

Follower 副本需满足以下条件才能留在 ISR 中：

```
replica.lag.time.max.ms = 30000（默认）
```

- 在 `replica.lag.time.max.ms` 时间内 Follower 向 Leader 发起过 **fetch 请求**
- 注意：Kafka 0.9+ 不再通过消息条数判断延迟，只通过请求时间判断
- 如果 Follower 超过 `replica.lag.time.max.ms` 未 Fetch，被踢出 ISR
- 重新追上后自动加回 ISR

**源码关键逻辑：**

```scala
// kafka.cluster.Partition.scala
private def maybeShrinkIsr(): Unit = {
  val leaderLog = log.getOrElse {
    warn(s"Trying to shrink ISR for partition $topicPartition with no leader log")
    return
  }
  val leaderLogEndOffset = leaderLog.logEndOffset
  val currentIsr = inSyncReplicas.read
  
  // 找出不同步的副本
  val outOfSyncReplicas = currentIsr.filter { replica =>
    replica.logEndOffset == -1 ||  // 没有数据
    (leaderLogEndOffset - replica.logEndOffset) > 0 ||  // 落后
    (time.milliseconds() - replica.lastFetchTimeMs) > configs.replicaLagTimeMaxMs  // 超时未Fetch
  }
  
  if (outOfSyncReplicas.nonEmpty) {
    val newIsr = currentIsr -- outOfSyncReplicas.toSet
    // 更新 ISR 到 ZooKeeper（或 KRaft 元数据日志）
    updateIsr(newIsr)
    isrChangeListener.onIsrChange(topicPartition, newIsr.toList)
  }
}
```

### 5.2 HW / LEO

**面试高频题：**

> Q: 解释 HW、LEO 的含义及其在副本同步中的作用。Consumer 能读到 HW 以内的数据还是 LEO 以内的数据？

A:

- **LEO（Log End Offset）**：当前副本的最后一条消息的下一个位置
- **HW（High Watermark）**：所有 ISR 副本都同步到的 Offset，Consumer 只能读到 HW 之前的数据
- **LW（Low Watermark）**：日志清理后 Partition 的第一条消息偏移量

**同步流程：**

```
                    Leader                    Follower 1         Follower 2
LEO:                |10|                      |8|                |5|
ISR: {Leader, F1, F2}
HW = min(Leader.LEO, F1.LEO, F2.LEO) = min(10, 8, 5) = 5
Consumer 可见范围: offset < 5
```

**HW 更新机制：**

1. Follower 向 Leader 发送 FetchRequest
2. Leader 在返回数据时，附带当前 Leader 的 LEO
3. Follower 收到响应后更新其 HW = min(已同步的 LEO, Leader LEO)
4. Leader 侧 HW = min(Leader LEO, 所有 ISR 副本的 LEO)

**源码关键路径：**

```scala
// kafka.cluster.Partition.scala
// Leader 更新 HW 的逻辑
def updateLeaderHWAndMaybeShrinkISR(): Unit = {
  // 取所有 ISR 副本的最小 LEO
  val leo = leaderLog.logEndOffset  // Leader 的 LEO
  val minIsrLeo = isrReplicas.map(_.logEndOffset).min
  val newHw = math.min(leo, minIsrLeo.value)
  
  if (newHw > leaderLog.highWatermark) {
    leaderLog.updateHighWatermark(newHw)
    // 通知等待的消费者：有新数据可读了
    leaderLog.maybeIncrementHighWatermark(newHw)
  }
}
```

### 5.3 Leader Epoch

**面试高频题：**

> Q: Kafka 0.11 引入 Leader Epoch 的作用是什么？解决了什么问题？

A: Leader Epoch 解决 HW 截断机制导致的**数据丢失**和**数据不一致**问题。

**问题场景：**

```
初始: Leader(0), Follower(1), HW=5, LEO=10

Step 1: Leader 接收新消息，LEO=12，HW 未更新（Follower 落后）
Step 2: Leader 宕机，Follower 成为新 Leader，HW=5
Step 3: 原 Leader 恢复，发现 HW=5，截断 LEO 到 5 → 数据丢失！
```

**Leader Epoch 解决方案：**

```
每个 Leader 任期记录：<epoch, startOffset>
Leader 在恢复时，Follower 提供 epoch 信息而不是 HW：
  → 新 Leader 告知 epoch 对应的起始偏移量
  → 旧 Leader 截断到该偏移量，而不是 HW
```

**源码：**

```scala
// kafka.server.epoch.LeaderEpochFileCache
// epoch 缓存存储在 leader-epoch-checkpoint 文件中
class LeaderEpochFileCache(topicPartition: TopicPartition, ...) {
  // epoch => startOffset 映射
  // 如: [(0, 0), (1, 100), (2, 200)] 
  // epoch 0: offset 0 开始
  // epoch 1: offset 100 开始
  // epoch 2: offset 200 开始
  
  def assign(epoch: Int, startOffset: Long): Unit
  def latestEpoch(): Option[Int]
  def endOffsetFor(epoch: Int): Option[Long]
}
```

**生产最佳实践：**

- 升级到 Kafka 2.8+ 获取最新 Leader Epoch 改进
- 配合 `unclean.leader.election.enable=false` 保证数据一致性

### 5.4 不完全 Leader 选举（Unclean Leader Election）

**面试高频题：**

> Q: `unclean.leader.election.enable` 设置为 true 或 false 分别有什么影响？

A:

| 配置值 | 行为 | 数据一致性 | 可用性 |
|--------|------|-----------|--------|
| `false`（推荐） | 只允许 ISR 中的副本成为 Leader | 强一致 | 降低（ISR 全部下线时不可用） |
| `true` | 允许 OSR 副本成为 Leader | 弱一致 | 提高（有副本即可领选） |

**选择建议：**

- **核心业务/金融系统**：`unclean.leader.election.enable=false`，宁可不可用也不能丢数据
- **日志收集/可观测**：`unclean.leader.election.enable=true`，可用性优先
- **预防措施**：`min.insync.replicas` 配合使用，保证至少 N 个 ISR 副本

```properties
# 典型生产配置
unclean.leader.election.enable=false
min.insync.replicas=2
default.replication.factor=3
```

---

## 6. 控制器与协调器

### 6.1 Controller 选举与职责

**面试高频题：**

> Q: Controller 在 Kafka 集群中扮演什么角色？Controller 宕机后如何恢复？

A: **Controller 职责：**

- 管理 Partition 的 Leader 选举
- 监听 Broker 上下线，触发分区重分配
- 管理元数据变更（创建/删除 Topic、增删 Partition）
- 将元数据变更同步到所有 Broker

**选举机制：**

Kafka 2.8 前依赖 ZooKeeper：

```
1. 所有 Broker 尝试在 ZK 创建 /controller 临时节点
2. 第一个创建成功的成为 Controller
3. Controller 在 ZK 注册 Watcher 监听 /controller 节点
4. Controller 宕机 → 临时节点消失 → Watcher 通知其他 Broker
5. 所有 Broker 再次竞争创建 /controller 节点
```

Kafka 3.x+（KRaft）不依赖 ZK，使用基于 Raft 的选举（见 KRaft 章节）。

**Controller 的唯一性保证：**

- 通过 ZK 的**临时节点 + 递增 epoch** 保证
- 每个 Controller 消息包含 `controller_epoch`，Broker 只接受更高 epoch 的消息
- 出现僵尸 Controller 时，其请求因 epoch 较低被拒绝

### 6.2 GroupCoordinator

已在 4.2 节详述。此处补充内部 Topic 结构。

`__consumer_offsets` 内部 Topic 的消息格式（Kafka 2.0+）：

```
Key:   [groupId, topic, partition]
Value: [offset, leaderEpoch, metadata, commitTimestamp, metadataVersion]

// 当 group.id=my-group, topic=my-topic, partition=0 时
// offsets 存储在 __consumer_offsets-{hash} 的某个 Partition 中
```

**生产最佳实践：**

- `offsets.topic.num.partitions`（默认 50）— 如果 Consumer Group 数量很大（>1000），应调大
- `offsets.topic.replication.factor`（默认 3）— 生产环境至少 3
- `offsets.retention.minutes`（默认 10080 = 7天）— Group 下线后的偏移量保留时间

### 6.3 元数据管理

**元数据自动刷新：**

- 生产者端：`metadata.max.age.ms`（默认 300s），定期刷新
- 消费者端：每次 `poll()` 时附带元数据请求
- 服务端：Controller 推送元数据变更到所有 Broker

**元数据内容：**

```json
{
  "brokers": [
    {"id": 0, "host": "kafka-0", "port": 9092},
    {"id": 1, "host": "kafka-1", "port": 9092}
  ],
  "topics": {
    "order-events": [
      {"partition": 0, "leader": 0, "replicas": [0, 1, 2], "isr": [0, 1]},
      {"partition": 1, "leader": 1, "replicas": [1, 2, 0], "isr": [1, 2]}
    ]
  },
  "controller_id": 0
}
```

---

## 7. KRaft 模式

### 7.1 去 ZooKeeper 架构

**演进历史：**

| 版本 | 依赖 | 架构 |
|------|------|------|
| 0.8.x - 2.7.x | ZooKeeper 必选 | Controller + ZK 管理元数据 |
| 2.8.x - 3.2.x | ZooKeeper 可选 | KRaft 预览/Migration 模式（ZK + KRaft 共存） |
| 3.3.x+ | ZK 可选 | KRaft 生产可用，ZK 模式仍支持 |
| 4.0+ | **仅 KRaft** | ZK 模式彻底移除 |

**架构变化：**

```
旧架构（ZK 模式）:
                  ZooKeeper
                 /    |    \
                /     |     \
         Broker1  Controller  Broker2
          (Leader选举, 元数据存储)

新架构（KRaft 模式）:
        元数据日志（Metadata Topic） ← Raft 共识
        /          |           \
  Controller1  Controller2  Controller3 (奇数个，如 3)
       \          |           /
      Broker ← 从元数据日志同步
```

### 7.2 元数据日志（Metadata Log）

**面试高频题：**

> Q: KRaft 模式中元数据日志是如何工作的？它和普通消息日志有什么区别？

A:

KRaft 引入**元数据日志（Metadata Log）**，替代 ZK 存储所有元数据。Controller 通过 Raft 共识将元数据变更写入元数据日志，其他节点（Controller Observer 和 Broker）从日志中复制。

**元数据日志内容类型（`RecordType`）：**

- `REGISTER_BROKER`：Broker 注册信息
- `TOPIC_RECORD`：Topic 创建/配置/删除
- `PARTITION_RECORD`：Partition 分配
- `ISR_CHANGE_RECORD`：ISR 变更
- `CONTROLLER_EPOCH`：Controller 任期记录
- `CONFIG_RECORD`：动态配置变更

**与普通消息日志的区别：**

| 特性 | 普通消息日志 | 元数据日志 |
|------|-------------|-----------|
| 存储位置 | 本地磁盘（data dir） | 本地磁盘（metadata dir） |
| 共识协议 | 异步复制（ISR） | Raft 同步复制 |
| 清理策略 | DELETE / COMPACT | COMPACT（仅保留最新状态） |
| 写入方式 | Leader 写入 | Active Controller 写入 |
| 消费者 | 普通 Consumer | 内部 Follower/Observer 同步 |

### 7.3 KRaft 选举

**面试高频题：**

> Q: KRaft 模式下的 Controller 选举和 ZK 模式有何不同？

A:

KRaft 使用基于 **Raft 协议** 的选举，不再是 ZK 的临时节点竞争：

1. **Voter 节点**：配置在 `process.roles=controller` 的节点（需奇数个，如 1、3、5）
2. **选举触发**：Active Controller（Leader）心跳超时
3. **选举过程**：
   - Candidate 发起 VoteRequest，携带 `term`（任期号）
   - 多数派（Quorum，如 3 节点集群需 2 票）同意后成为 Leader
4. **Leader 任期**：每个 term 对应一个 epoch，保证唯一性
5. **Observer**：`process.roles=broker` 或 `process.roles=broker,controller` 的节点只同步不参与投票

**配置示例：**

```properties
# KRaft 模式最小配置
process.roles=broker,controller
node.id=1
controller.quorum.voters=1@node1:9093,2@node2:9093,3@node3:9093

# 独立 Controller 节点配置
process.roles=controller
node.id=1
controller.quorum.voters=1@controller1:9093,2@controller2:9093,3@controller3:9093

# 独立 Broker 节点配置
process.roles=broker
node.id=4
controller.quorum.voters=1@controller1:9093,2@controller2:9093,3@controller3:9093
```

**生产最佳实践：**

- KRaft 模式下**混合节点**（`process.roles=broker,controller`）适合小规模集群（≤ 3 节点）
- 大规模集群推荐**分离节点**：3 或 5 个独立 Controller + N 个 Broker
- Controller Quorum 大小公式：`n = 2f + 1`，容忍 f 个节点故障
- 迁移路径：ZK → Migration（2.8+）→ KRaft（3.3+）→ ZK 移除（4.0+）
- 迁移前使用 `kafka-metadata-quorum` 工具验证集群状态

---

## 8. 性能调优

### 8.1 OS 层面

**Page Cache & Swappiness**

```bash
# 减少 swap 倾向，Kafka 大量使用 Page Cache
# 建议 swappiness = 1（有 swap 但仅当内存几乎耗尽时使用）
sysctl -w vm.swappiness=1

# 调整脏页回写阈值，让脏页在 Page Cache 中停留更长时间
# 触发回写的脏页比例（默认 20%）
sysctl -w vm.dirty_background_ratio=5
# 强制回写的脏页比例（默认 50%）
sysctl -w vm.dirty_ratio=20
```

**文件系统与磁盘：**

- **文件系统**：推荐 XFS（优于 ext4），IOPS 更高
- **挂载参数**：`noatime,nodiratime` 减少元数据写入
- **磁盘**：SSD 优先，避免 HDD 做 RAID5（奇偶校验开销大）
- **内核参数**：`kernel.numa_balancing=0`（大数据场景禁用 NUMA balancing）

**面试高频题：**

> Q: Kafka 重度使用 Page Cache，这意味着什么？如何监控 Page Cache 使用情况？

A:

Kafka 的设计哲学是将数据**先写到 Page Cache** 而不是直接刷盘：
- Producer 写入 → **Page Cache**（毫秒级返回） → 异步刷盘
- Consumer 读取 → **Page Cache** 命中（直接读内存） → 零拷贝 发送

这意味着：
- Kafka 不依赖 JVM 堆，消息数据存放在 OS 管理的 Page Cache 中
- JVM 堆主要存储：索引缓存、生产者批次、消费者元数据
- **建议 JVM 堆 = 4~8GB**，其余系统内存给 Page Cache
- 监控指标：`kafka.server:type=BrokerTopicMetrics,name=BytesInPerSec` / `BytesOutPerSec`
- Linux 命令：`sar -B` 查看 page fault，`free -h` 查看 cache

### 8.2 JVM GC

**生产推荐配置：**

```bash
# G1 GC 推荐（JDK 11+）
-XX:+UseG1GC
-XX:MaxGCPauseMillis=20
-XX:InitiatingHeapOccupancyPercent=35
-XX:G1HeapRegionSize=16M
-XX:+DisableExplicitGC
-XX:+ParallelRefProcEnabled
-XX:G1NewSizePercent=10
-XX:G1MaxNewSizePercent=30

# 堆大小
-Xms6G
-Xmx6G

# 元空间
-XX:MetaspaceSize=128M
-XX:MaxMetaspaceSize=256M
```

**面试高频题：**

> Q: Kafka 为什么推荐使用 G1 并给出上述参数？为什么堆大小不建议超过 8GB？

A:

1. **G1 优于 CMS**：
   - CMS 在 Full GC 时是串行单线程，大堆（>6G）下停顿过长
   - G1 可预测停顿时间，通过 `MaxGCPauseMillis` 控制
   - G1 能有效处理大堆（4~32G）

2. **堆大小不超过 8GB 的原因**：
   - Kafka 的消息数据存在 **Page Cache**，不在堆内
   - 堆主要存：索引缓存、未刷盘批次、网络连接缓冲区
   - 堆太大 → GC 停顿时间长 → Broker 响应超时 → 分区 Leader 迁移
   - 经验值：**4~8GB** 足够 Kafka 元数据缓存，剩余系统内存给 Page Cache

**GC 监控指标：**

- `kafka.producer:type=producer-metrics,name=waiting-threads`（等待内存的线程）
- `kafka.server:type=BrokerTopicMetrics,name=TotalTimeMs`（请求处理时间分布）
- JVM 指标：G1 Young GC 频率 < 10次/秒，Full GC = 0

### 8.3 网络与 IO 线程

**参数配置建议：**

```properties
# 网络线程（Processor）
num.network.threads=3              # CPU 核心数 / 2

# IO 线程（处理请求）
num.io.threads=8                   # CPU 核心数 * 2

# 后台线程（日志清理等）
background.threads=10

# 网络连接相关
queued.max.requests=500            # IO 线程排队上限
socket.receive.buffer.bytes=102400
socket.send.buffer.bytes=102400
```

**架构图：**

```
Acceptors → Processors (Network Threads) → Request Queue → IO Threads → Response Queue → Processors → 客户端
                 ↓ TCP Accept                       ↓ 请求处理                     ↓ TCP Send
            多个 Processor 轮询                   多个 IO Thread                异步发送响应
```

### 8.4 批次与压缩

**核心参数与原理：**

```properties
# 生产者端
batch.size=131072                  # 128KB，增大可提高吞吐
linger.ms=10                       # 等待时长，增加批次填充度
compression.type=snappy            # 网络带宽敏感用 gzip
buffer.memory=67108864             # 64MB 缓冲区
max.block.ms=1000                  # 缓冲区满后的阻塞时间

# Broker 端
compression.type=producer          # 沿用 Producer 压缩格式，避免重新压缩
log.flush.interval.messages=Long.MaxValue  # 不因消息数触发刷盘
log.flush.interval.ms=Long.MaxValue       # 不因时间间隔触发刷盘（交给 OS）
```

**面试高频题：**

> Q: `linger.ms` 和 `batch.size` 如何权衡？增大它们一定提高吞吐吗？

A:

`batch.size` 和 `linger.ms` 共同决定 Batch 的填充度和发送延迟：

| 策略 | 延迟 | 吞吐 | 适用场景 |
|------|------|------|---------|
| low latency（毫秒级） | 低 | 低 | 实时响应型 |
| high throughput（秒级） | 高 | 高 | 大吞吐批量型 |

权衡点：
- `batch.size` 太大 → 排队时间增加，小消息场景浪费
- `linger.ms` 太大 → 增加延迟，消息堆积在 Producer 端
- 推荐初始值：`batch.size=64KB`，`linger.ms=5~10ms`
- 如果 Producer 端 `waiting-threads` 不为 0，说明缓冲区满，需增大 `buffer.memory` 或优化下游

---

## 9. 生产运维

### 9.1 集群规划

**节点规模估算公式：**

```
所需 Broker 数 = max(
    总吞吐 / 单机吞吐,
    (总存储 × 副本因子) / 单机存储,
    (总 Partition 数) / (单机建议 Partition 数上限)
)

单机吞吐 = min(磁盘顺序写吞吐, 网络带宽, CPU 压缩解压能力)
```

**硬件配置推荐：**

| 组件 | 小规模（< 100MB/s） | 中规模（100~500MB/s） | 大规模（> 500MB/s） |
|------|-------------------|---------------------|-------------------|
| CPU | 8 核 | 16 核 | 32 核+ |
| 内存 | 16GB | 32GB | 64GB+（建议 128GB） |
| 磁盘 | 4×2TB HDD | 4×4TB SSD | 8×8TB NVMe |
| 网络 | 10Gbps | 25Gbps | 100Gbps |
| 部署模式 | 3 节点 | 6 节点 | 12 节点+ |

**操作系统参数汇总：**

```bash
# /etc/sysctl.conf
vm.swappiness=1
vm.dirty_background_ratio=5
vm.dirty_ratio=20
net.core.somaxconn=2048
net.ipv4.tcp_max_syn_backlog=2048
fs.file-max=10000000
```

### 9.2 监控指标

**必监控的三类指标：**

**1. 吞吐与延迟：**

| 指标名 | JMX MBean | 告警阈值 |
|--------|-----------|---------|
| BytesInPerSec | `kafka.server:type=BrokerTopicMetrics,name=BytesInPerSec` | 周期性对比 |
| BytesOutPerSec | `kafka.server:type=BrokerTopicMetrics,name=BytesOutPerSec` | 周期性对比 |
| TotalTimeMs | `kafka.server:type=BrokerTopicMetrics,name=TotalTimeMs` | p99 > 500ms |
| RequestQueueSize | `kafka.server:type=RequestMetrics,name=RequestQueueSize` | > 500 |

**2. 消费者健康：**

| 指标名 | JMX MBean | 告警阈值 |
|--------|-----------|---------|
| ConsumerLag | `kafka.consumer:type=consumer-fetch-manager-metrics,client-id=*,name=records-lag-max` | > 阈值 |
| RebalanceRate | `kafka.consumer:type=consumer-coordinator-metrics,name=rebalance-rate-per-hour` | > 10/h |

**3. 服务端健康：**

| 指标名 | JMX MBean | 告警阈值 |
|--------|-----------|---------|
| UnderReplicatedPartitions | `kafka.server:type=ReplicaManager,name=UnderReplicatedPartitions` | > 0 |
| OfflinePartitions | `kafka.controller:type=KafkaController,name=OfflinePartitionsCount` | > 0 |
| ISRShrinkRate | `kafka.server:type=ReplicaManager,name=ISRShrinkRate` | > 异常 |
| ActiveControllerCount | `kafka.controller:type=KafkaController,name=ActiveControllerCount` | != 1 |

**面试高频题：**

> Q: Consumer Lag 滞后通常是哪些原因导致的？排查思路是什么？

A:

**原因排查树：**

```
Consumer Lag 上升
├── 消费者处理能力不足
│   ├── 单条消息处理耗时过长 (检查 max.poll.interval.ms)
│   ├── Consumer 线程数不足 (检查 num.stream.threads)
│   └── 下游（DB/API）阻塞
├── 生产者流量突增
│   ├── 排查上游流量来源
│   └── 检查是否需要扩容 Partition + Consumer
├── Rebalance 频繁
│   ├── session.timeout.ms 过小
│   ├── Consumer 处理超时
│   └── 网络抖动
└── Broker 端瓶颈
    ├── 磁盘 I/O Wait 高（Page Cache 不足或磁盘故障）
    ├── 网络带宽打满
    └── 分区 Leader 分布不均
```

### 9.3 分区重分配

**触发场景：**

1. 集群扩容或缩容
2. 磁盘利用率不均衡
3. Broker 下线维护

**命令：**

```bash
# 生成重分配计划
kafka-reassign-partitions.sh \
  --bootstrap-server localhost:9092 \
  --generate \
  --topics-to-move-json-file topics.json \
  --broker-list "1,2,3,4,5"

# 执行重分配
kafka-reassign-partitions.sh \
  --bootstrap-server localhost:9092 \
  --execute \
  --reassignment-json-file reassign.json

# 验证进度
kafka-reassign-partitions.sh \
  --bootstrap-server localhost:9092 \
  --verify \
  --reassignment-json-file reassign.json
```

**面试高频题：**

> Q: 分区重分配过程中会影响生产消费吗？如何减少影响？

A:

分区重分配的本质是**数据搬迁**，过程如下：

1. 新 Leader 开始从旧 Leader 同步数据（增量复制）
2. 当新副本赶上 HW 后，加入 ISR
3. 切换 Leader 到目标 Broker
4. 删除旧的副本数据

影响控制：
- 数据同步期间网络 IO 增加，可能影响正常请求
- 可通过 `--throttle` 限制带宽：`kafka-reassign-partitions.sh --execute --throttle 50000000`（约 50MB/s）
- 建议在**业务低峰期**执行
- 监控 `UnderReplicatedPartitions` 确保重分配完成后恢复正常

### 9.4 数据保留策略

**参数：**

```properties
# 基于时间的保留（默认 7 天）
log.retention.hours=168

# 基于大小的保留（默认无限制）
log.retention.bytes=-1

# Segment 文件大小（默认 1GB）
log.segment.bytes=1073741824

# Segment 删除前检查时间间隔
log.retention.check.interval.ms=300000
```

**删除机制：**

```
日志删除管理器（LogManager）每 5 分钟执行一次：
1. 计算每个 Log 的可删除 Segment 列表
2. 删除过期 Segment（超过 retention.hours）
3. 删除超限 Segment（所有 Segment 总和超过 retention.bytes）
4. 如果都不是，检查 Log Start Offset 之前的部分
```

**生产最佳实践：**

- **日志类场景**：保留时间较短（如 3~7 天），用 `log.retention.hours` 控制
- **事件溯源场景**：使用**日志压缩**（`log.cleanup.policy=compact`）
- **关键审计数据**：保留时间设置较长（如 30~90 天），需做好容量规划
- 不要单纯依赖时间策略，搭配 `log.retention.bytes` 做硬性上限

### 9.5 MirrorMaker 跨集群复制

**工具演进：**

| 版本 | 工具 | 特点 |
|------|------|------|
| 2.x | MirrorMaker 1 | 简单的 Consumer → Producer 管道 |
| 2.5+ | MirrorMaker 2 | 基于 Kafka Connect，支持双向同步、偏移量翻译、Topic 重命名 |
| 3.0+ | MirrorMaker 2 | 生产推荐（已移除 MM1） |

**MirrorMaker 2 配置示例：**

```properties
# mm2.properties
clusters=source, target
source.bootstrap.servers=source-cluster:9092
target.bootstrap.servers=target-cluster:9092

source->target.enabled=true
target->source.enabled=false  # 单向复制

# Topic 自动创建
target.auto.create.internal.topics=true

# 重命名规则
target->target.topic.patterns=.*
target->target.topic.rename.pattern=(.*)
target->target.topic.rename.replace.with=dr-$1

# 偏移量同步
sync.topic.acls.enabled=true
sync.topic.configs.enabled=true
replication.factor=3

# 消费者配置
source.consumer.group.id=mm2-source-consumer
source.consumer.max.poll.records=5000
```

**面试高频题：**

> Q: MirrorMaker 2 如何保证跨集群的偏移量一致性？

A:

MirrorMaker 2 创建内部 Topic：`mm2-offsets.<source-cluster>.<target-cluster>`，存储源集群每个 Consumer Group 的偏移量映射，使得在灾备切换时目标集群可以从正确位置继续消费。

```
源集群状态：
consumer-group A / topic T / partition 0 → offset 1000

转换成目标集群：
topic dr-T / partition 0 → offset 980（经过同步转换）

MirrorMaker 2 自动将偏移量写入目标集群的 __consumer_offsets，
使用相同的 Consumer Group ID，实现无缝切换。
```

### 9.6 常见故障排查

**场景 1：Producer 发送超时**

```
错误: `Failed to update metadata after 60000 ms.`
排查:
1. 检查 Broker 是否在线（telnet broker:9092）
2. 检查 metadata.max.age.ms 是否设置过小
3. 检查 Broker 端 RequestQueue 是否堆积（IO 线程不够）
```

**场景 2：消费者组卡住**

```
症状: Consumer Lag 持续增长
排查:
1. Consumer 日志是否出现多次 Rebalance
2. 检查 max.poll.records 与单条处理时间的乘积是否大于 max.poll.interval.ms
3. 检查 session.timeout.ms 是否过小（网络抖动导致踢出组）
```

**场景 3：磁盘写满**

```
紧急处理:
1. 调整 log.retention.hours 或 log.retention.bytes 立即触发清理
2. 手动删除旧 Segment（需先停止 Kafka，极危险，仅当紧急）
3. 扩容新磁盘并执行分区重分配
```

**场景 4：Leader 频繁切换**

```
症状: UnderReplicatedPartitions > 0，大量 ISR 抖动
排查:
1. 检查网络延迟和丢包（ping, traceroute）
2. 检查 GC 停顿是否过长（G1 GC日志）
3. 检查副本同步线程是否被 IO Wait 阻塞
4. 检查 broker 间最大 fetch 大小是否不匹配
```

---

## 10. 与 RabbitMQ 场景对比

### 10.1 架构与模型对比

| 维度 | Kafka | RabbitMQ |
|------|-------|----------|
| 定位 | 分布式流平台 | 消息中间件（AMQP 0-9-1） |
| 消息模型 | Topic / Partition / Offset | Exchange / Queue / Routing Key |
| 存储 | 持久化日志 Log Segment | 内存 / 普通文件 |
| 消费模型 | Pull（消费者拉取） | Push / Pull 兼有 |
| 路由 | 分区 Key + 分区策略 | Exchange Type（direct/fanout/topic/headers） |
| 顺序保证 | 单 Partition 内有序 | 单 Queue 内有序 |
| 消息过滤 | Broker 端不支持 | Broker 端支持（Header/Routing Key） |
| 延迟消息 | 不原生支持 | 支持（插件或 TTL+DLQ） |

### 10.2 功能与特性对比

| 特性 | Kafka | RabbitMQ |
|------|-------|----------|
| 重试机制 | 需自行实现（DLT）+ 重试 Topic | 原生死信 + 重新入队 |
| 死信队列 | DLT（需要手动配置） | DLX（原生支持） |
| 消息 TTL | 按 Topic 级别设置 | 按消息/Queue 级别设置 |
| 优先级 | 不原生支持 | 原生支持 |
| 延迟队列 | 不原生支持（需 Kafka Streams） | 原生支持（延迟插件） |
| 事务 | 生产者事务 + Exactly Once | AMQP 事务（性能差） |
| 大规模分区 | 万级 | 不明显（单节点瓶颈） |

### 10.3 性能对比

| 场景 | Kafka | RabbitMQ |
|------|-------|----------|
| 吞吐量 | **百万条/秒**（顺序 I/O + 零拷贝） | 万~十万条/秒 |
| 延迟 | 毫秒级（大规模批量下几毫秒），但微秒级要求达不到 | **微秒级**（Erlang 天生低延迟） |
| 持久化 | 高（日志追加，顺序 I/O） | 中（随机 I/O） |
| 高可用 | 复制因子 + ISR + 区域部署 | 镜像队列 / 仲裁队列 + 自动同步 |

### 10.4 选型决策树

```
业务场景
├── 高吞吐日志收集、埋点数据、Metrics、审计日志
│   → Apache Kafka
├── 事件流处理、Stream、数据管道（CDC、ETL）
│   → Apache Kafka + Kafka Streams / ksqlDB
├── 金融交易、订单状态变更，需要 Exactly Once
│   → Apache Kafka（事务 API）
├── 任务调度、异步解耦、需要灵活的投递策略
│   → RabbitMQ（直连/主题/广播+死信）
├── 延迟消息、定时任务
│   → RabbitMQ
├── RPC 风格的消息通信、需要消息确认等复杂交互
│   → RabbitMQ
└── "我不知道未来需求是什么"
    → 场景复杂选 Kafka（扩展性好），简单直连选 RabbitMQ（运维成本低）
```

**面试高频题：**

> Q: 在微服务架构中，Kafka 和 RabbitMQ 各适合什么场景？为什么不能互相替代？

A:

**必须用 RabbitMQ 的场景：**
- 需要**灵活路由**（Header Exchange、Topic Exchange 多级通配符）
- 需要**延迟/定时消息**（付款超时取消、预约提醒）
- 需要**每个消息独立确认**（任务分发，每条消息状态独立）
- 服务间调用需要**消息优先级**
- 小规模团队，需要**低运维复杂度**

**必须用 Kafka 的场景：**
- **高吞吐**（日处理百亿+条消息）
- **数据管道**（MySQL CDC → 数据湖 / ES）
- **事件驱动架构**（Event Sourcing + CQRS）
- **流处理**（实时聚合、Join、窗口计算）
- **长期数据保留**（回溯消费、审计追踪）
- Replay / 重放能力（偏移量重置）

**核心观点：**
- RabbitMQ 是**消息代理**（Message Broker）— 将消息投递给正确的消费者，投递完成后通常可以删除
- Kafka 是**流式存储平台**（Streaming Platform）— 长期保存消息，支持回溯消费
- 两者不是完全的替代关系，混合使用是常见架构

---

## 附录：参数速查表

### 生产者端关键参数

```properties
bootstrap.servers=broker1:9092,broker2:9092,broker3:9092
key.serializer=org.apache.kafka.common.serialization.StringSerializer
value.serializer=org.apache.kafka.common.serialization.StringSerializer

# 可靠性
acks=all                   # -1 同义，所有副本确认
enable.idempotence=true    # 开启幂等
max.in.flight.requests.per.connection=5  # 幂等下仍可保证有序

# 吞吐
batch.size=131072          # 128KB
linger.ms=10               # 10ms 等待积累批次
compression.type=snappy    # 或 lz4, zstd
buffer.memory=67108864     # 64MB

# 超时
request.timeout.ms=30000
delivery.timeout.ms=120000
```

### 消费者端关键参数

```properties
bootstrap.servers=broker1:9092,broker2:9092
key.deserializer=org.apache.kafka.common.serialization.StringDeserializer
value.deserializer=org.apache.kafka.common.serialization.StringDeserializer
group.id=my-consumer-group

# 偏移量
enable.auto.commit=false     # 手动提交（推荐）
auto.offset.reset=earliest   # 或 latest, none
isolation.level=read_committed  # 事务场景

# 吞吐
max.poll.records=500          # 单次 poll 最大条数
fetch.min.bytes=65536         # 64KB 最小拉取量
fetch.max.wait.ms=500         # 等待时间

# 重平衡
session.timeout.ms=45000
heartbeat.interval.ms=3000
max.poll.interval.ms=300000
partition.assignment.strategy=org.apache.kafka.clients.consumer.CooperativeStickyAssignor
```

### Broker 端关键参数

```properties
# 基础
broker.id=1
log.dirs=/data/kafka/data
num.network.threads=3
num.io.threads=8

# 副本
default.replication.factor=3
min.insync.replicas=2
unclean.leader.election.enable=false
replica.lag.time.max.ms=30000

# 存储
log.segment.bytes=1073741824    # 1GB
log.retention.hours=168         # 7 天
log.retention.bytes=-1          # 无限
log.cleanup.policy=delete       # 或 compact

# 网络
socket.send.buffer.bytes=102400
socket.receive.buffer.bytes=102400
queued.max.requests=500

# 压缩
compression.type=producer

# Controller
controller.quorum.voters=1@controller1:9093,2@controller2:9093,3@controller3:9093
```

---

> 撰写说明：本文内容基于 Apache Kafka 3.x 版本特性。Kafka 版本迭代较快（尤其是 KRaft 模式），请以官方文档为准。持续关注 [KIP（Kafka Improvement Proposals）](https://cwiki.apache.org/confluence/display/KAFKA/Kafka+Improvement+Proposals) 获取最新演进。
