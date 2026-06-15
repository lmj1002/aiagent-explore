# 高级 Kafka 面试知识架构

> 本文面向资深后端工程师 / 架构师岗位，从源码原理到生产调优，系统梳理 Kafka 核心知识体系。

---

## 基础概念

### 1. 消息模型与核心概念

| 术语 | 定义 |
|------|------|
| **Message (消息)** | Kafka 中数据的基本单元，由 Key、Value、Header、Timestamp、Offset 组成 |
| **Topic (主题)** | 消息的逻辑分类容器，生产者向 Topic 投递消息，消费者从 Topic 拉取消息 |
| **Partition (分区)** | 物理存储单元，每个 Topic 包含多个 Partition，分布在不同 Broker 上；**单 Partition 内消息严格有序** |
| **Broker (代理节点)** | Kafka 服务器节点，多个 Broker 组成集群，管理本地 Partition 副本 |
| **Consumer Group (消费者组)** | 同一组内消费者共同消费 Topic 全量 Partition；一个 Partition 只能被组内一个消费者消费 |
| **Controller (控制器)** | Kafka 集群的"大脑"，负责分区 Leader 选举、元数据管理、Broker 上下线处理 |

### 2. 消息投递语义

| 语义 | 定义 | 实现方式 |
|------|------|----------|
| **At Most Once** | 最多一次，消息可能丢失但不重复 | `acks=0`，Producer 不等待确认 |
| **At Least Once** | 至少一次，消息可能重复但不丢失 | `acks=1` 或 `acks=all` + 重试 |
| **Exactly Once** | 精确一次，不丢不重 | 幂等 Producer + 事务 + `read_committed` |

### 3. 架构演进里程碑

- **0.8.x**: 引入副本机制、Consumer Group
- **0.10.0**: Kafka Streams 发布
- **0.11.0**: 幂等 Producer、事务消息、Leader Epoch
- **2.8.0**: KRaft 模式（去 ZooKeeper）预览
- **3.3.0**: KRaft 生产可用
- **4.0**: 彻底移除 ZooKeeper

---

## 核心原理

### 1. 分区副本与一致性

#### AR / ISR / OSR

| 术语 | 全称 | 含义 |
|------|------|------|
| **AR** | Assigned Replicas | 分区所有副本的统称 |
| **ISR** | In-Sync Replicas | 与 Leader 保持同步的副本集合（含 Leader 自身） |
| **OSR** | Out-of-Sync Replicas | 与 Leader 同步滞后的副本集合 |

关系：`AR = ISR + OSR`

#### ISR 准入与剔除

- **准入**: Follower 须在 `replica.lag.time.max.ms`（默认 10s）内持续向 Leader 发送 FETCH 请求并追赶上 LEO
- **剔除**: 超过时间阈值未发送 FETCH 或无法追上最新数据，踢出 ISR
- **伸缩**: Kafka 启动 `isr-expiration` 定时任务周期性检查并缩减 ISR

#### LEO 与 HW

| 概念 | 定义 |
|------|------|
| **LEO (Log End Offset)** | 当前日志文件中下一条待写入消息的 offset（= 最后一条消息 offset + 1） |
| **HW (High Watermark)** | 已提交消息的最大 offset，消费者只能消费 HW 之前的消息 |

HW 更新流程：

1. Producer 发消息 -> Leader 写入，LEO 更新，HW 暂不变
2. Follower 发送 FETCH 请求拉取消息，写入本地日志，更新自身 LEO
3. Leader 收到所有 ISR 内 Follower 的 FETCH 响应后，重新计算 HW = min(所有副本 LEO)
4. 后续 FETCH 响应中携带新 HW，Follower 据此更新自身 HW

#### Leader Epoch（0.11.0 引入）

**解决的问题**：纯 HW 机制存在数据丢失和数据错乱两个缺陷。

**原理**：
- 为每个 Leader 任期分配单调递增的 epoch 编号
- 记录每个 epoch 对应的起始偏移量
- Follower 重启后先发送 `LeaderEpochRequest` 询问 Leader 当前 epoch 的最新偏移量
- 根据响应判断是否需要截断日志，解决数据不一致问题

### 2. 高吞吐设计

#### 顺序读写

| 类型 | 性能 | 差距 |
|------|------|------|
| 磁盘顺序写 | ~600 MB/s | -- |
| 磁盘随机写 | ~100 KB/s | 相差约 6000 倍 |

Kafka 采用 Append-Only 追加写模式，所有消息只追加到日志文件末尾；日志分为多个 Segment 文件（默认 1GB）。

#### PageCache（页缓存）

**写入流程**: 消息 -> 直接写入 PageCache（内存）-> 返回成功 -> OS 异步刷盘
**读取流程**: 优先从 PageCache 命中 -> 无磁盘 IO

**优势**: 无 GC 影响、内核自动管理、JVM 堆分配 6-8G 即可，剩余内存全留给 PageCache。

#### 零拷贝（Zero-Copy）

消费者读取使用 `sendfile` 系统调用：

```
传统 IO: 磁盘 -> 内核读缓冲 -> 用户态 -> Socket 缓冲 -> 网卡（4 次拷贝 + 4 次上下文切换）
零拷贝: 磁盘 -> PageCache -> 网卡（2 次 DMA 拷贝 + 0 次 CPU 拷贝 + 2 次上下文切换）
```

- **sendfile**: 适用于消费者读取（磁盘/PageCache -> 网卡，文件无需修改）
- **mmap**: 适用于索引文件（.index、.timeindex）的随机读写

#### 稀疏索引

Kafka 不为每条消息建索引，而是每写入 `log.index.interval.bytes`（默认 4KB）才写入一条索引项。

**索引项结构**: 相对 offset（4B）+ 物理位置（4B）

**查询流程**：
1. 二分查找定位目标 Segment 文件
2. 计算相对 offset
3. 二分查找 .index 文件，找到 <= 目标值的索引项
4. 从对应物理位置开始顺序扫描 .log 文件

### 3. 生产者核心机制

#### ACK 参数

| 值 | 含义 | 可靠性 | 延迟 |
|------|------|------|------|
| `acks=0` | 不等待任何确认 | 最低 | 最快 |
| `acks=1` | Leader 写入即确认（默认） | 中等 | 较快 |
| `acks=all/-1` | ISR 全部确认 | 最高 | 最慢 |

#### 幂等性

- **开启**: `enable.idempotence=true`（Kafka 2.0+ 默认开启）
- **原理**: `<PID, Partition, SequenceNumber>` 三元组唯一标识每条消息，Broker 对相同主键只持久化一次
- **效果**: 单分区内 Exactly-Once，防止重试导致重复写入
- **局限性**: 仅单会话单分区有效，跨分区/跨主题需要事务

#### 事务

- **解决的问题**: 跨分区/跨主题的原子性写入、跨会话幂等性
- **核心组件**: Transaction Coordinator、`__transaction_state` 主题、Transactional Producer
- **API 流程**: `initTransactions()` -> `beginTransaction()` -> `send()` -> `commitTransaction()/abortTransaction()`
- **消费端**: `isolation.level=read_committed` 只读到已提交数据
- **代价**: 吞吐量降低 10%-50%，延迟增加

#### 压缩算法对比

| 算法 | 压缩比 | CPU 开销 | 推荐场景 |
|------|--------|----------|----------|
| none | 无 | 无 | 不推荐 |
| snappy | 中等 | 低 | 兼顾性能与压缩率 |
| lz4 | 较好 | 低 | **推荐（速度快、压缩率好）** |
| zstd | 很高 | 中等 | 高压缩比需求（Kafka 2.1+） |
| gzip | 高 | 高 | 不推荐高吞吐场景 |

#### 批量发送

| 参数 | 说明 | 推荐值 |
|------|------|--------|
| `batch.size` | 单批次最大字节数（默认 16KB） | 32KB ~ 128KB |
| `linger.ms` | 等待更多消息的时间（默认 0ms） | 5~20ms |

### 4. 消费者核心机制

#### Rebalance 触发场景

1. 消费者数量变化（加入/退出/宕机）
2. Topic 分区数增加
3. 订阅的 Topic 变更
4. 心跳超时（`session.timeout.ms` 默认 45s）
5. 消费超时（`max.poll.interval.ms` 默认 5min）

#### Rebalance 分配策略

| 策略 | 说明 |
|------|------|
| **Range**（默认） | 按 Topic 范围分配，可能导致不均匀 |
| **RoundRobin** | 轮询分配，较均匀 |
| **Sticky** | 保留已有分配，减少变动 |
| **Cooperative Sticky** | 增量重平衡，避免全组暂停（**推荐**） |

#### Offset 管理

- **自动提交**: `enable.auto.commit=true`，定时提交（默认 5s），简单但有丢消息风险
- **手动提交**: `commitSync()`（同步，保证提交成功）或 `commitAsync()`（异步，不阻塞）
- **事务提交**: `sendOffsetsToTransaction()`，将 offset 提交纳入事务

#### 消息重复/丢失解决方案

| 问题 | 根因 | 解决方案 |
|------|------|----------|
| 消息丢失 | 自动提交 + 消费未完成触发 Rebalance | 关闭自动提交，先处理再提交 |
| 消息重复 | Rebalance 打断手动提交，处理完但未提交 | 业务幂等、去重表、Kafka 事务 |
| 消费超时踢出 | 处理耗时 > `max.poll.interval.ms` | 调大超时参数、减少 `max.poll.records`、异步处理 |
| Rebalance 风暴 | 频繁心跳超时或成员变动 | 静态成员（`group.instance.id`）、Cooperative Sticky |

### 5. Exactly-Once 语义实现

#### 端到端 Exactly-Once 完整链路

```
生产者侧: 幂等 Producer（enable.idempotence=true）+ 事务（transactional.id）
  |
Broker侧: acks=all + replication.factor>=3 + min.insync.replicas>=2
  |
消费者侧: isolation.level=read_committed + enable.auto.commit=false + sendOffsetsToTransaction()
```

#### read_committed 实现原理

- **LSO (Log Stable Offset)**: Broker 维护 LSO 到第一条未提交的事务消息的 offset
- read_committed 消费者只能消费 LSO 之前的消息
- 通过 `.txnindex` 文件过滤已回滚的消息

#### 幂等 Producer vs 事务 Producer

| 特性 | 幂等 Producer | 事务 Producer |
|------|---------------|---------------|
| 保障级别 | 单会话单分区不丢不重 | 跨分区、跨会话原子性 |
| 跨分区原子性 | 不支持 | 支持 |
| 跨会话幂等性 | 不支持 | 支持 |
| 性能开销 | 几乎无 | 10%-50% 吞吐下降 |
| 配置 | `enable.idempotence=true` | 额外配置 `transactional.id` |

---

## 高频面试题

### 基础篇（3 年以下）

#### Q1: Kafka 为什么这么快？简述核心设计。

**答案要点**：
- 顺序写（磁盘顺序写 ~600MB/s，随机写 ~100KB/s，差距 6000 倍）
- PageCache（利用 OS 页缓存，避免 JVM GC，热数据达内存级读写）
- 零拷贝 sendfile（2 次 DMA 拷贝，0 次 CPU 拷贝，2 次上下文切换）
- 稀疏索引（每 4KB 一条索引项，索引文件极小可完全加载到内存）
- 批量处理 + 压缩（Producer 批量发送、Consumer 批量拉取，配合 lz4/zstd 压缩）

#### Q2: 什么是 ISR？ISR、OSR、AR 的关系是什么？

**答案要点**：
- AR = ISR + OSR，AR 是全量副本集合
- ISR 是与 Leader 保持同步的副本（含 Leader），OSR 是同步滞后的副本
- 准入条件：Follower 须在 `replica.lag.time.max.ms`（默认 10s）内持续拉取并追上 LEO
- ISR 中选新 Leader，禁止 OSR 参与选举（生产环境 `unclean.leader.election.enable=false`）

#### Q3: acks=0、acks=1、acks=all 的区别？分别适用什么场景？

**答案要点**：
- `acks=0`：不等待确认，可能丢消息，适用于日志采集等能容忍丢失的场景
- `acks=1`：Leader 写入即确认，Leader 宕机可能丢消息（默认值），平衡吞吐与可靠性
- `acks=all`：ISR 全部确认，最高可靠性，但吞吐最低，需配合 `min.insync.replicas>=2`

#### Q4: Producer 端如何保证消息不丢失？

**答案要点**：
- `acks=all` + `retries=Integer.MAX_VALUE`
- `enable.idempotence=true`（防止重试导致重复）
- 使用回调（Callback）处理发送失败，不要盲目 `fire-and-forget`
- `delivery.timeout.ms` 设置合理的超时时间

#### Q5: 什么是 Rebalance？触发条件有哪些？

**答案要点**：
- 消费者数量变化（加入、退出、宕机）
- Topic 分区数增加
- 订阅的 Topic 变更
- `session.timeout.ms` 心跳超时
- `max.poll.interval.ms` 消费超时

### 进阶篇（3-5 年）

#### Q6: HW（高水位）和 LEO 是什么？HW 是如何更新的？

**答案要点**：
- LEO = Log End Offset，当前日志下一条待写入消息的 offset
- HW = High Watermark，已提交消息的最大 offset，消费者只能消费 HW 之前的消息
- HW = min(ISR 集合中所有副本的 LEO)
- 更新流程：Producer 写入 -> Leader 更新 LEO -> Follower FETCH -> 返回 HW -> Leader 重新计算 HW

#### Q7: Leader Epoch 解决了什么问题？原理是什么？

**答案要点**：
- 解决纯 HW 机制的数据丢失和数据错乱问题（Kafka 0.11.0 之前）
- 原理：每个 Leader 任期分配单调递增 epoch + 记录 epoch 起始偏移量
- Follower 重启后先问 Leader 当前 epoch 的最新偏移量，再决定是否截断
- 避免了 Follower 基于过期 HW 错误截断数据

#### Q8: 幂等 Producer 的实现原理是什么？它的局限性是什么？

**答案要点**：
- 原理：`<PID, Partition, SequenceNumber>` 三元组唯一标识消息
- Broker 校验：序列号 == last_sn + 1 正常接收；<= last_sn 丢弃（重复）；> last_sn + 1 说明丢消息
- 局限性：只保证单会话单分区，Producer 重启 PID 变化后跨会话无法去重，跨分区无法保证原子性

#### Q9: Kafka 事务的实现原理？两阶段提交是怎么工作的？

**答案要点**：
- 生产者注册 `transactional.id` -> Transaction Coordinator 分配 PID + epoch
- Phase 1：写入事务消息，消息标记为"未提交"，写入 `__transaction_state` 记录状态
- Phase 2：commitTransaction() 写入 COMMIT Marker / abortTransaction() 写入 ABORT Marker
- 消费端 `read_committed` 根据 Marker 过滤，LSO 标记第一条未提交消息的 offset
- 失败必须调用 abortTransaction()，未完成的事务会阻塞 read_committed 消费者

#### Q10: 什么是粘性分区策略（Sticky Partition Assignor）？原理和优势？

**答案要点**：
- **原理**：Rebalance 时尽量保留消费者已经拥有的分区，只对需要平衡的分区进行重新分配
- 使用 `CooperativeStickyAssignor` 实现增量重平衡（Incremental Rebalance）
- **优势**：减少分区重新分配的代价、降低 Rebalance 期间的暂停时间、减少重复消费
- Kafka 2.4+ 默认为 CooperativeStickyAssignor

#### Q11: Read_committed 隔离级别下，卡住的事务会有什么影响？如何解决？

**答案要点**：
- 一个长时间未提交的事务会导致 LSO 不推进，消费端阻塞
- 默认 `transaction.timeout.ms=60s`，超时后 Coordinator 自动中止事务
- 建议：设置合理的 `transaction.timeout.ms`（如 15s）、监控未完成事务数量

### 高级篇（5 年以上 / 架构师）

#### Q12: Kafka 消息不丢失需要从哪几个维度保证？请完整阐述。

**答案要点**：
从 Producer、Broker、Consumer 三个维度（缺一不可）：

1. **Producer 侧**：`acks=all` + `enable.idempotence=true` + `retries=Integer.MAX_VALUE` + 回调处理失败
2. **Broker 侧**：`replication.factor>=3` + `min.insync.replicas>=2` + `unclean.leader.election.enable=false` + 磁盘 RAID 10
3. **Consumer 侧**：`enable.auto.commit=false` + 先处理消息再手动提交 + 业务幂等兜底

**不能忽略的细节**：
- `acks=all` 但 `min.insync.replicas=1` 时 ISR 只剩 Leader，Leader 宕机依然丢消息
- 网络分区 + `min.insync.replicas` 不足，Producer 写入失败，但已写 Leader 的数据可能因新 Leader 选举丢失
- 日志删除策略（`retention.ms`/`retention.bytes`）到达后即使消费者未消费也会被删除

#### Q13: Kafka 的零拷贝是如何实现的？为什么不用 mmap 实现数据传输？mmap 的适用场景？

**答案要点**：

**零拷贝实现细节**：
- 使用 `FileChannel.transferTo()` -> 底层调用 `sendfile()` 系统调用
- 数据直接从 PageCache 到网卡，全程在内核态完成
- 仅对 Consumer 读取场景使用，Producer 写入使用 PageCache + 异步刷盘

**为什么 Consumer 读取不用 mmap**：
- mmap 映射的文件长度有限（受虚拟地址空间限制），不适合大文件传输
- mmap 涉及缺页中断（Page Fault），读大文件时性能抖动
- mmap 需要用户态参与拷贝，没有真正消除 CPU 拷贝

**mmap 适用场景**：
- 索引文件（.index、.timeindex）的随机读写
- 文件较小且需要频繁随机访问（Kafka 索引使用 MMap）

#### Q14: 假设 10 个 Broker、1 个 Topic 5 个分区、replication.factor=3。描述该 Topic 的副本分布和 Leader 选举过程。

**答案要点**：

**副本分布（机架感知）**：
- 每个分区有 3 个副本（1 Leader + 2 Follower）
- 副本分布在不同的 Broker 上（确保容错）
- 若有机架感知（rack awareness），副本分布在不同的机架

**Leader 选举**：
- AR 列表第一个副本为 Preferred Leader（优先副本）
- Leader 宕机时，Controller 从 ISR 中选举新 Leader
- ISR 都不可用且 `unclean.leader.election.enable=false` 时，分区不可用
- ISR 都不可用但设置为 true 时，从 OSR 中选 LEO 最大的副本作为 Leader（存在数据丢失风险）

#### Q15: Kafka 分区数过多为什么会影响性能？如何合理规划分区数？

**答案要点**：

**分区数过多的影响**：
1. **文件句柄开销**: 每个分区对应 N（副本因子）个目录，每个目录含多个 Segment 文件，文件句柄暴涨
2. **选举时间变长**: Controller 选举时需为所有分区选举 Leader，分区过多时选举时间显著增长
3. **内存开销**: 每个分区需在内存中维护元数据、LEO、HW 等状态
4. **Leader 切换延迟**: 大量分区同时需要 Leader 切换时，Controller 成为瓶颈

**合理规划方法**：
- 分区数 = Max(预期吞吐量 / 单分区能力，消费者线程数)
- 单 Partition 写入能力约 10MB/s
- 每 Broker 承载 100-200 个分区为宜
- 分区数 = Broker 数量的整数倍（均匀分布）

#### Q16: Kafka 消息积压（Lag）的排查思路和解决方案。

**答案要点**：

**排查步骤**：
1. 查看 `kafka-consumer-groups --bootstrap-server --group --describe` 获取各分区 Lag
2. 确定是消费能力不足还是消费阻塞（`max.poll.interval.ms` 超时被踢）
3. 检查消费者 CPU、内存、网络、磁盘 IO 是否存在瓶颈
4. 确认下游（数据库、外部 API）是否成为瓶颈

**解决方案**：
1. 扩容消费者（消费者数 <= 分区数，不足则需先增加分区）
2. 增大 `fetch.max.bytes` 和 `max.poll.records`，提高单次拉取量
3. 开启批量处理，减少网络开销
4. 异步消费（注意控制并发度，打满下游）
5. 优化业务逻辑，缩短单条消息处理时间
6. 临时方案：跳过非关键消息（设置 `auto.offset.reset=latest`，注意数据丢失）

#### Q17: KRaft 模式相比 ZooKeeper 模式的优势是什么？两者在 Leader 选举机制上有何区别？

**答案要点**：

**KRaft 优势**：
1. 架构简化：无需维护两套系统（Kafka + ZooKeeper）
2. 故障检测更快：ZooKeeper session timeout 秒级 -> Raft 心跳百毫秒级
3. 元数据同步更快：直接基于 Raft Log，不经过 ZK 序列化/反序列化
4. 支持更大规模集群：测试验证 200 万分区
5. 减少运维复杂度：无需额外配置 ZK 集群

**选举机制对比**：

| 对比项 | ZooKeeper 模式 | KRaft 模式 |
|--------|---------------|------------|
| 选举基础 | ZK 临时节点 + Watcher | Raft 共识协议 |
| 故障检测 | ZK session timeout（6-18s） | 心跳超时（百毫秒级） |
| 脑裂风险 | 存在 | Raft 多数派机制避免 |
| 领导者变更 | Controller 再选举，可能需要秒级 | 百毫秒级完成 |

#### Q18: 如何设计一个支持 Exactly-Once 的流处理管道（Kafka -> Flink/Kafka Streams -> Kafka）？

**答案要点**：

**关键配置**：
```
生产者: enable.idempotence=true + transactional.id + acks=all
消费者: isolation.level=read_committed + enable.auto.commit=false
```
使用 Flink 的 `CheckpointingMode.EXACTLY_ONCE` 或 Kafka Streams 的 `processing.guarantee=EXACTLY_ONCE_V2`。

**幂等检查点（Flink 场景）**：
1. Flink 从 Source Kafka 消费 -> barrier 对齐进行 Checkpoint
2. 处理后的结果写入 Sink Kafka（使用两阶段提交 Sink）
3. 故障时从最近 Checkpoint 恢复，Source 回退 offset，Sink 回滚未提交的事务

**注意事项**：
- EOS 只保证 Kafka 生态内的一致性，涉及外部系统（DB、API）仍需要业务幂等
- EOS 带来性能开销（吞吐降低 30-50%），非必要场景不启用
- 使用 EOS v2（Kafka 2.5+）减少协调器交互，性能提升约 30%

#### Q19: Kafka 集群升级（滚动升级）的完整步骤和注意事项。

**答案要点**：

**步骤**：
1. 关闭自动 Leader 均衡（`auto.leader.rebalance.enable=false`）
2. 逐台关闭 Broker，等待分区完成 Leader 切换
3. 升级版本，重启 Broker
4. 确认 ISR 完整，分区 Leader 恢复正常
5. 验证集群 Lag 指标正常
6. 重复步骤 2-5 直至全部 Broker 升级完成
7. 开启自动 Leader 均衡

**⚠️ 注意事项**：
- 版本兼容性：确认版本间 RPC 协议兼容，跨大版本升级需逐版本升级
- 先升级 Broker，再升级客户端（Producer/Consumer）
- 监控 ISR 状态，确保每台 Broker 重启后 ISR 恢复
- 准备回滚方案，保留旧版本安装包
- KRaft 模式升级需注意元数据版本兼容性

#### Q20: 如何理解 Stream-Table Duality（流表二象性）？在 Kafka Streams/ksqlDB 中如何体现？

**答案要点**：

**核心定义**：
- **Stream（流）**: 不可变的、仅追加的事件序列，记录历史
- **Table（表）**: 可变的键值视图，代表当前状态

**二者关系**：
- Stream -> Table：通过聚合（group by key，取最新值）将事件流变为状态表
- Table -> Stream：通过捕获变更日志（changelog）将状态表变为事件流

**在 Kafka 生态中的体现**：
- `KStream`: 流，每条消息都是新的独立事件
- `KTable`: 表，每个 key 只有最新值（由 Compacted Topic 支持）
- `GlobalKTable`: 全局复制表，用于维表关联
- ksqlDB 中的 `CREATE STREAM` vs `CREATE TABLE` 正是这一理论在 SQL 层面的映射

**典型应用**：
```sql
-- 输入流
CREATE STREAM pageviews (user_id INT, page_id INT) WITH (...);
-- 聚合为物化视图（表）
CREATE TABLE pageviews_per_user AS
SELECT user_id, COUNT(*) AS cnt
FROM pageviews WINDOW TUMBLING (SIZE 1 HOUR)
GROUP BY user_id;
```

---

## 最佳实践

### 生产环境配置清单

#### 1. Producer 配置（金融级可靠）

```properties
acks=all
enable.idempotence=true
retries=2147483647
delivery.timeout.ms=120000
request.timeout.ms=30000
max.in.flight.requests.per.connection=5
batch.size=65536            # 64KB
linger.ms=10                # 10ms
compression.type=lz4        # 或 zstd
buffer.memory=134217728     # 128MB
```

#### 2. Broker 配置

```properties
# 线程
num.network.threads=8       # CPU 核数 * 2/3
num.io.threads=8            # CPU 核数 * 1/2
num.replica.fetchers=2      # CPU 核数 * 1/6

# 复制
default.replication.factor=3
min.insync.replicas=2
unclean.leader.election.enable=false

# 存储
log.dirs=/data1/kafka,/data2/kafka   # 多磁盘
log.segment.bytes=1073741824          # 1GB
log.retention.hours=168               # 7天
log.retention.bytes=-1                # 按时间不按大小

# 网络
socket.send.buffer.bytes=102400       # 100KB
socket.receive.buffer.bytes=102400
socket.request.max.bytes=104857600    # 100MB
```

#### 3. Consumer 配置

```properties
enable.auto.commit=false
session.timeout.ms=60000        # 60s
heartbeat.interval.ms=20000     # session.timeout.ms / 3
max.poll.interval.ms=300000     # 5min（根据处理耗时调整）
max.poll.records=500            # 单次拉取条数
fetch.min.bytes=524288          # 512KB
fetch.max.wait.ms=500           # 500ms
auto.offset.reset=earliest      # 或 latest，取决于业务
```

#### 4. JVM / OS 调优

| 维度 | 建议 |
|------|------|
| **JVM 堆** | -Xms6G -Xmx6G（留充足内存给 PageCache） |
| **GC** | G1GC：`-XX:+UseG1GC -XX:MaxGCPauseMillis=200`；JDK 11+ 可考虑 ZGC |
| **磁盘** | SSD / NVMe，独立挂载，RAID 10 |
| **内核** | `vm.swappiness=1`（禁用 swap 优先 PageCache）；增大 `vm.max_map_count` |
| **文件句柄** | `ulimit -n 100000` |

### 性能调优清单

| 目标 | 调优动作 |
|------|----------|
| **提升 Producer 吞吐** | 增大 `batch.size`（64KB~1MB）、增大 `linger.ms`（5~20ms）、开启压缩（lz4/zstd） |
| **提升 Consumer 吞吐** | 增大 `fetch.max.bytes` 和 `max.poll.records`、增加分区/消费者并行度 |
| **降低延迟** | 减小 `linger.ms`（0~5ms）、减小 `batch.size`、选择更快的压缩算法（lz4） |
| **提升 Broker 吞吐** | 多磁盘 `log.dirs`、增大 `num.io.threads`、优化 PageCache 预留、使用 SSD |
| **减少 Rebalance** | 使用 CooperativeStickyAssignor、设置 `group.instance.id`、调大超时参数 |
| **提升副本同步速度** | 增大 `replica.fetch.max.bytes`、增加 `num.replica.fetchers` |

### 常见坑

1. **partition 数量拍脑袋定** -> 并行度上限无法扩展。估算公式：分区数 >= max(预期峰值吞吐/单分区能力, 消费者线程数 * 2)

2. **重试未开幂等** -> Broker 写入成功但 ACK 超时导致重试，消息重复写入。必须 `enable.idempotence=true`

3. **acks=all 但 min.insync.replicas=1** -> ISR 只剩 Leader 时，Leader 宕机丢消息。必须 `min.insync.replicas>=2`

4. **自动提交 offset** -> Rebalance 导致大量消息重复或丢失。生产环境务必手动提交

5. **消费者处理时间 > max.poll.interval.ms** -> 触发 Rebalance，形成"消费超时 -> Rebalance -> 重分配 -> 再超时"恶性循环

6. **Topic 未隔离** -> 实时消息和离线数据混用 Topic，消费能力互相影响

7. **未监控 Lag** -> 积压到磁盘爆满才被发现。配置 Grafana + Prometheus 监控 Consumer Lag

8. **分区倾斜** -> Key 分布不均导致部分 Broker 过热。检查分区策略，必要时使用自定义分区器或增加随机盐值

9. **JVM 堆过大** -> 堆 > 16G 时 GC 停顿显著，导致 Broker 心跳超时被踢出集群

10. **KRaft 模式元数据存储和非元数据共用磁盘** -> 元数据磁盘 IO 争抢导致性能抖动。建议独立磁盘

---

## 进阶拓展

### Kafka vs RocketMQ vs Pulsar 对比

#### 架构对比

| 维度 | Kafka | RocketMQ | Pulsar |
|------|-------|----------|--------|
| **开发语言** | Scala/Java | Java | Java + Go(BookKeeper) |
| **架构** | 计算存储耦合 | NameServer + Broker 主从 | **计算存储分离** |
| **元数据管理** | KRaft（自管理） | NameServer（轻量无状态） | ZooKeeper |
| **存储结构** | Partition -> Segment 顺序日志 | CommitLog + ConsumeQueue | BookKeeper Ledger + 分层存储 |

#### 性能与功能对比

| 维度 | Kafka | RocketMQ | Pulsar |
|------|-------|----------|--------|
| **吞吐量** | **百万级 TPS（最高）** | 十万~百万级 | 十万~百万级 |
| **延迟** | 毫秒级 | **最低**（<3ms 核心交易） | P99 较高（20-35ms） |
| **最大 Topic 数** | 数万（多分区性能下降） | 数万无性能损失 | **百万级** |
| **顺序消息** | 分区内有序 | 全局 + 分区有序 | 分区内有序 |
| **事务消息** | 支持 | **原生支持（2PC，非常成熟）** | 原生支持 |
| **延迟/定时消息** | **不支持** | **原生支持**（18级/任意精度） | 原生支持 |
| **死信队列** | 不支持 | 原生支持 | 原生支持 |
| **消息过滤** | 基于分区/Key | **Tag 过滤**（高效二级过滤） | Tag 过滤 |
| **多租户** | 弱 | 命名空间隔离 | **原生强隔离** |
| **跨地域复制** | 需配置 | 需配置 | **原生支持** |
| **云原生适配** | 中等 | 中等 | **最佳**（天生适配 K8s） |
| **运维控制台** | 无（需第三方） | **自带（功能完整）** | 自带（功能完整） |

#### 选型建议

- **大数据、日志、流处理、高吞吐 -> Kafka**：日志采集、CDC、事件溯源、Flink/Spark 流处理
- **电商金融、事务顺序、高可靠 -> RocketMQ**：订单、支付、交易、库存，双 11 级高并发
- **云原生、多租户、跨地域 -> Pulsar**：K8s 部署、SaaS 平台、无限堆积、流+队列混合负载

### Kafka Streams 与 ksqlDB

#### Kafka Streams 核心抽象

| 抽象 | 说明 |
|------|------|
| **KStream** | 不可变的、仅追加的事件流 |
| **KTable** | 可变的键值表（由 Compacted Topic 支持） |
| **GlobalKTable** | 全局复制表，用于维表关联 |
| **State Store** | 本地状态存储（RocksDB），由 Changelog Topic 支持故障恢复 |

#### 流表二象性（Stream-Table Duality）

- **Stream -> Table**: 通过聚合（group by key 取最新值）将事件流变为状态表
- **Table -> Stream**: 通过捕获变更日志将状态表变为事件流
- 同一个 Kafka Topic 既可以被读作 Stream，也可以被读作 Table，区别是对数据的语义解释不同

#### 时间窗口类型

| 窗口类型 | 说明 |
|----------|------|
| **Tumbling Window** | 固定大小、不重叠 |
| **Hopping Window** | 固定大小、可重叠 |
| **Session Window** | 基于活动间隔，不活动后关闭 |
| **Sliding Window** | 用于流-流 Join |

#### ksqlDB 查询类型

- **Pull Query**：对物化视图进行点查（类似传统数据库）
- **Push Query**：持续推送结果到客户端（实时仪表盘）
- **Persistent Query**：持续将结果写回 Kafka Topic

---

## 参考资源

### 官方资料

- [Apache Kafka 官方文档](https://kafka.apache.org/documentation/)
- [Confluent 官方文档](https://docs.confluent.io/platform/current/overview.html)
- [Kafka Improvement Proposals (KIPs)](https://cwiki.apache.org/confluence/display/KAFKA/Kafka+Improvement+Proposals)

### 推荐书籍

- 《Kafka: The Definitive Guide》（第 2 版）- Neha Narkhede 等
- 《深入理解 Kafka：核心设计与实践原理》- 朱虹
- 《Apache Kafka 源码剖析》- 徐郡明
- 《Mastering Kafka Streams and ksqlDB》- Mitch Seymour

### 推荐博客与专栏

- [Confluent Blog](https://www.confluent.io/blog/)（英文前沿技术）
- [阿里云开发者社区 - Kafka 专题](https://developer.aliyun.com/search?q=Kafka)
- [腾讯云开发者社区 - Kafka 专题](https://cloud.tencent.com/developer/search?q=Kafka)
- [Kafka 源码阅读笔记 - 知乎专栏](https://zhuanlan.zhihu.com/p/358918515)

### 面试资源

- [Kafka 高频面试 40 问（2025 最新版）](https://www.e-com-net.com/article/2039462781765345280.htm)
- [Kafka 高级工程师面试问题及答案（2026 完整版）](https://mp.weixin.qq.com/s/...)
- [Kafka 面试高频题（原理辨析、背诵版）](https://www.cnblogs.com/springwu/articles/19594374)

---

> **本文由 WebSearch 多源检索生成，结合阿里云开发者社区、腾讯云开发者社区、博客园、知乎、Confluent 官方等多篇高质量技术文章整理而成。**
