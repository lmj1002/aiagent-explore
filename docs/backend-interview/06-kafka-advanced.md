# 高级 Kafka 面试知识架构

> 目标读者：高级后端开发 / 系统架构师
> 本文从源码、原理、生产实践三个维度深度剖析 Apache Kafka，涵盖高频面试题与最佳实践。
>

---

## 目录

**篇一 · Kafka 入门与集群搭建**

1. [Kafka 产品介绍](#1-kafka-产品介绍)
2. [快速上手 Kafka](#2-快速上手-kafka)
3. [搭建 ZooKeeper 集群](#3-搭建-zookeeper-集群)
4. [搭建并使用 Kafka 集群](#4-搭建并使用-kafka-集群)

**篇二 · 客户端开发详解**（对应视频 kfk2）

5. [基础客户端开发流程](#5-基础客户端开发流程)
6. [消费者分组消费机制详解](#6-消费者分组消费机制详解)
7. [生产者拦截器机制详解](#7-生产者拦截器机制详解)
8. [消息序列化机制](#8-消息序列化机制)
9. [消息分区路由机制](#9-消息分区路由机制)
10. [生产者消息缓存机制](#10-生产者消息缓存机制)
11. [生产者发送应答机制](#11-生产者发送应答机制)
12. [生产者消息幂等性](#12-生产者消息幂等性)
13. [消息压缩机制与消息事务](#13-消息压缩机制与消息事务)

**附录**

- [附录 A · 服务端原理与生产运维（待对齐视频后续目录）](#附录-a服务端原理与生产运维待对齐视频后续目录)
- [附录 B · 高频面试题库（分级）](#附录-b高频面试题库分级)
- [附录 C · 参数速查表](#附录-c参数速查表)
- [附录 D · 参考资源](#附录-d参考资源)

---

# 篇一 · Kafka 入门与集群搭建

## 1. Kafka 产品介绍

### 1.1 Kafka 是什么

Apache Kafka 是一个**分布式流处理平台**（Distributed Streaming Platform），最初由 LinkedIn 开发用于解决日志聚合问题，2011 年开源。它的三大核心能力：

1. **消息系统（Messaging）**：发布-订阅模型，替代传统 MQ
2. **存储系统（Storage）**：消息持久化到磁盘，支持长期保留与回溯消费
3. **流处理（Stream Processing）**：通过 Kafka Streams / ksqlDB 做实时计算

> Kafka 不只是「消息队列」。它的定位是**流式存储平台** —— 消息默认长期保留、支持任意回溯消费，这是与 RabbitMQ 这类「投递完即删除」的消息代理最本质的区别。

### 1.2 核心概念

Kafka 采用**发布-订阅（Pub-Sub）** 消息模型，以 Topic 为逻辑单位组织消息：

```
Producer → Topic[Partition0, Partition1, Partition2] → Consumer Group
```

| 术语 | 定义 |
|------|------|
| **Message（消息）** | Kafka 中数据的基本单元，由 Key、Value、Header、Timestamp、Offset 组成 |
| **Topic（主题）** | 消息的逻辑分类容器，生产者向 Topic 投递，消费者从 Topic 拉取 |
| **Partition（分区）** | 物理存储单元，每个 Topic 含多个 Partition，分布在不同 Broker 上；**单 Partition 内消息严格有序** |
| **Broker（代理节点）** | Kafka 服务器节点，多个 Broker 组成集群，存储并管理本地 Partition 副本 |
| **Producer（生产者）** | 发布消息到指定 Topic |
| **Consumer（消费者）** | 从 Topic 订阅消息，以 Consumer Group 为单位消费 |
| **Consumer Group（消费者组）** | 同组内消费者共同消费 Topic 全量 Partition；**一个 Partition 只能被组内一个消费者消费** |
| **Offset（偏移量）** | 消息在 Partition 内的唯一编号，单调递增 |
| **Controller（控制器）** | 集群的"大脑"，负责分区 Leader 选举、元数据管理、Broker 上下线处理 |

**【面试】Kafka 为什么使用 Partition？Partition 数量如何确定？**

Partition 是 Kafka 实现水平扩展和并行消费的核心机制：

- **并行度**：一个 Partition 只能被一个 Consumer 消费，Partition 数决定了 Consumer Group 内最大并行度
- **存储扩展**：Partition 分布在多个 Broker 上，突破单机磁盘容量限制
- **有序性保证**：单个 Partition 内消息有序，跨 Partition 无序

Partition 数量确定原则：
- 下限：`max(预期峰值吞吐量 / 单 Partition 吞吐量, 预期消费者数量)`
- 经验公式：`Partition数 = 目标吞吐量(MB/s) / 单 Partition 吞吐量(MB/s)`，单 Partition 写入能力约 10 MB/s
- 上限：建议单 Broker 不超过 2000 个 Partition；每 Broker 承载 100~200 个分区为宜
- 分区数尽量取 Broker 数量的整数倍（保证均匀分布）
- 注意：Partition 越多，选举、重平衡、元数据管理、文件句柄开销越大

### 1.3 架构演进里程碑

| 版本 | 关键特性 |
|------|---------|
| **0.8.x** | 引入副本机制、Consumer Group |
| **0.10.0** | Kafka Streams 发布 |
| **0.11.0** | 幂等 Producer、事务消息、Leader Epoch |
| **2.8.0** | KRaft 模式（去 ZooKeeper）预览 |
| **3.3.0** | KRaft 生产可用 |
| **4.0** | 彻底移除 ZooKeeper，仅保留 KRaft |

### 1.4 应用场景

| 场景 | 说明 |
|------|------|
| 日志聚合 | 收集分散的服务日志，统一写入下游（ES / HDFS / 数据湖） |
| 指标监控 | 应用埋点、Metrics 上报的传输通道 |
| 消息系统 | 服务解耦、异步削峰 |
| 流处理 | 实时聚合、Join、窗口计算（Flink / Kafka Streams） |
| 事件溯源 | Event Sourcing + CQRS，依赖长期保留与回溯能力 |
| 数据管道 | MySQL CDC → 数据仓库 / 搜索引擎 |

---

## 2. 快速上手 Kafka

### 2.1 单机部署（以 KRaft 模式为例，Kafka 3.x+）

```bash
# 1. 下载并解压
wget https://downloads.apache.org/kafka/3.7.0/kafka_2.13-3.7.0.tgz
tar -xzf kafka_2.13-3.7.0.tgz && cd kafka_2.13-3.7.0

# 2. 生成集群 UUID
KAFKA_CLUSTER_ID="$(bin/kafka-storage.sh random-uuid)"

# 3. 格式化存储目录
bin/kafka-storage.sh format -t $KAFKA_CLUSTER_ID -c config/kraft/server.properties

# 4. 启动 Broker
bin/kafka-server-start.sh config/kraft/server.properties
```

> Kafka 2.x 及更早版本需先启动 ZooKeeper（`bin/zookeeper-server-start.sh`），再启动 Broker。详见第 3、4 节。

### 2.2 命令行工具基础操作

```bash
# 创建 Topic（3 分区、1 副本）
bin/kafka-topics.sh --create --topic quickstart \
  --partitions 3 --replication-factor 1 \
  --bootstrap-server localhost:9092

# 查看 Topic 详情
bin/kafka-topics.sh --describe --topic quickstart \
  --bootstrap-server localhost:9092

# 列出所有 Topic
bin/kafka-topics.sh --list --bootstrap-server localhost:9092

# 生产消息（控制台生产者）
bin/kafka-console-producer.sh --topic quickstart \
  --bootstrap-server localhost:9092

# 消费消息（从头开始）
bin/kafka-console-consumer.sh --topic quickstart \
  --from-beginning --bootstrap-server localhost:9092

# 查看消费者组的 Lag
bin/kafka-consumer-groups.sh --describe --group my-group \
  --bootstrap-server localhost:9092
```

### 2.3 第一条消息的完整链路

```
Producer.send()
  → 序列化 Key/Value
  → 分区器选择 Partition
  → 写入 RecordAccumulator 缓存
  → Sender 线程批量发送到 Broker Leader
  → Leader 写入本地 Log（PageCache）
  → ISR 副本同步
  → 返回 ack
  → Consumer poll() 拉取
  → 反序列化 → 业务处理 → 提交 offset
```

> 这条链路贯穿篇二的全部章节：序列化（第 8 节）、分区路由（第 9 节）、消息缓存（第 10 节）、发送应答（第 11 节）、消费（第 6 节）。

---

## 3. 搭建 ZooKeeper 集群

> 适用于 Kafka 3.x 之前（或仍使用 ZK 模式的集群）。Kafka 4.0 已移除 ZK，新集群建议直接用 KRaft（见第 4 节与附录 A）。

### 3.1 ZooKeeper 在 Kafka 中的职责

| 职责 | 说明 |
|------|------|
| Broker 注册 | 每个 Broker 启动时在 `/brokers/ids` 注册临时节点 |
| Controller 选举 | 抢占式创建 `/controller` 临时节点，成功者为 Controller |
| Topic 元数据 | 存储 Topic / Partition / 副本分配信息 |
| ISR 变更 | 记录每个 Partition 的 ISR 集合 |
| 配额与 ACL | 存储动态配置、客户端配额、权限信息 |

> 注意：偏移量（Offset）在 0.9+ 之后**不再存 ZooKeeper**，而是存入内部 Topic `__consumer_offsets`。

### 3.2 集群规划与配置

ZooKeeper 集群需**奇数个节点**（3、5、7），遵循 `n = 2f + 1` 公式容忍 f 个节点故障。3 节点配置示例：

```properties
# conf/zoo.cfg
tickTime=2000
initLimit=10
syncLimit=5
dataDir=/data/zookeeper
clientPort=2181

# 集群成员（server.id=host:数据同步端口:选举端口）
server.1=zk1:2888:3888
server.2=zk2:2888:3888
server.3=zk3:2888:3888
```

每个节点需在 `dataDir` 下创建 `myid` 文件，内容为该节点的 server.id：

```bash
echo "1" > /data/zookeeper/myid   # zk1 上
echo "2" > /data/zookeeper/myid   # zk2 上
echo "3" > /data/zookeeper/myid   # zk3 上
```

### 3.3 启动与验证

```bash
# 每个节点启动
bin/zkServer.sh start

# 查看角色（leader / follower）
bin/zkServer.sh status

# 连接客户端验证
bin/zkCli.sh -server zk1:2181
[zk] ls /brokers/ids      # Kafka 启动后可见 Broker 列表
```

**【面试】ZooKeeper 的选举机制（ZAB 协议）简述？**

- ZooKeeper 使用 **ZAB（ZooKeeper Atomic Broadcast）** 协议保证一致性
- 选举时比较 `(epoch, zxid, myid)`：优先选 epoch 最大、事务 ID（zxid）最新、myid 最大的节点为 Leader
- 需要**多数派（Quorum）** 同意，因此节点数必须为奇数
- Leader 负责写请求并广播给 Follower，Follower 可处理读请求

---

## 4. 搭建并使用 Kafka 集群

### 4.1 集群配置（ZK 模式）

3 个 Broker 的核心配置差异在 `broker.id`、`listeners` 和共享的 `zookeeper.connect`：

```properties
# server.properties（broker-1）
broker.id=1
listeners=PLAINTEXT://kafka1:9092
log.dirs=/data/kafka/data
zookeeper.connect=zk1:2181,zk2:2181,zk3:2181/kafka

# 副本与可靠性默认值（生产建议）
default.replication.factor=3
min.insync.replicas=2
unclean.leader.election.enable=false
num.partitions=3
```

> `zookeeper.connect` 末尾的 `/kafka` 是 **chroot**，让多个 Kafka 集群共用一套 ZK 时互不干扰。

### 4.2 集群配置（KRaft 模式，推荐）

```properties
# 混合节点（小集群 ≤3 节点）
process.roles=broker,controller
node.id=1
controller.quorum.voters=1@kafka1:9093,2@kafka2:9093,3@kafka3:9093
listeners=PLAINTEXT://kafka1:9092,CONTROLLER://kafka1:9093

# 大规模集群推荐分离：独立 Controller + 独立 Broker
# Controller 节点：process.roles=controller
# Broker 节点：    process.roles=broker
```

### 4.3 Topic 管理实操

```bash
# 创建生产级 Topic（多分区 + 3 副本）
bin/kafka-topics.sh --create --topic order-events \
  --partitions 12 --replication-factor 3 \
  --config min.insync.replicas=2 \
  --config retention.ms=604800000 \
  --bootstrap-server kafka1:9092

# 增加分区（注意：会破坏既有 Key 路由，需谨慎）
bin/kafka-topics.sh --alter --topic order-events \
  --partitions 24 --bootstrap-server kafka1:9092

# 动态修改 Topic 配置
bin/kafka-configs.sh --alter --topic order-events \
  --add-config retention.ms=259200000 \
  --bootstrap-server kafka1:9092
```

### 4.4 集群健康验证

```bash
# 查看分区副本分布与 ISR
bin/kafka-topics.sh --describe --topic order-events \
  --bootstrap-server kafka1:9092
# 重点关注：Leader / Replicas / Isr 三列是否齐全

# 查看 Broker 与 Controller（KRaft）
bin/kafka-metadata-quorum.sh --bootstrap-server kafka1:9092 describe --status
```

**【面试】副本（replica）应该如何分配到 Broker？**

Kafka 默认采用**机架感知（rack-aware）+ 轮询**的副本分配算法：
- 每个分区的多个副本尽量分布在**不同 Broker**（容忍单机故障）
- 配置 `broker.rack` 后，副本尽量分布在**不同机架**（容忍整机架故障）
- AR 列表的第一个副本是 **Preferred Leader（优先副本）**，正常情况下应作为 Leader，便于负载均衡

---

# 篇二 · 客户端开发详解

## 5. 基础客户端开发流程

### 5.1 生产者开发流程

标准的生产者使用分五步：配置 → 创建 → 构造消息 → 发送 → 关闭。

```java
// Java 原生客户端
Properties props = new Properties();
props.put("bootstrap.servers", "kafka1:9092,kafka2:9092");
props.put("key.serializer", "org.apache.kafka.common.serialization.StringSerializer");
props.put("value.serializer", "org.apache.kafka.common.serialization.StringSerializer");
props.put("acks", "all");

Producer<String, String> producer = new KafkaProducer<>(props);
ProducerRecord<String, String> record =
    new ProducerRecord<>("order-events", "order-123", "{...}");

// 异步发送 + 回调（推荐，不要 fire-and-forget）
producer.send(record, (metadata, exception) -> {
    if (exception != null) {
        log.error("发送失败", exception);
    } else {
        log.info("分区={} 偏移量={}", metadata.partition(), metadata.offset());
    }
});
producer.close();   // flush 缓冲区并释放资源
```

**三种发送方式对比：**

| 方式 | 写法 | 特点 |
|------|------|------|
| Fire-and-forget | `send(record)` | 不关心结果，可能丢消息，不推荐 |
| 同步发送 | `send(record).get()` | 阻塞等待 ack，可靠但吞吐低 |
| 异步发送 | `send(record, callback)` | 非阻塞 + 回调处理失败，**推荐** |

### 5.2 消费者开发流程

```java
Properties props = new Properties();
props.put("bootstrap.servers", "kafka1:9092");
props.put("group.id", "order-consumer-group");
props.put("key.deserializer", "org.apache.kafka.common.serialization.StringDeserializer");
props.put("value.deserializer", "org.apache.kafka.common.serialization.StringDeserializer");
props.put("enable.auto.commit", "false");   // 手动提交（推荐）
props.put("auto.offset.reset", "earliest");

KafkaConsumer<String, String> consumer = new KafkaConsumer<>(props);
consumer.subscribe(Arrays.asList("order-events"));

try {
    while (true) {
        ConsumerRecords<String, String> records = consumer.poll(Duration.ofMillis(100));
        for (ConsumerRecord<String, String> record : records) {
            process(record);                 // 先处理
        }
        consumer.commitSync();               // 再提交（至少一次语义）
    }
} finally {
    consumer.close();
}
```

### 5.3 Go 客户端（sarama）等价实现

```go
// 生产者（IBM/sarama）
config := sarama.NewConfig()
config.Producer.RequiredAcks = sarama.WaitForAll      // acks=all
config.Producer.Return.Successes = true
producer, _ := sarama.NewSyncProducer([]string{"kafka1:9092"}, config)
partition, offset, err := producer.SendMessage(&sarama.ProducerMessage{
    Topic: "order-events",
    Key:   sarama.StringEncoder("order-123"),
    Value: sarama.StringEncoder("{...}"),
})

// 消费者组（实现 ConsumerGroupHandler 接口）
group, _ := sarama.NewConsumerGroup([]string{"kafka1:9092"}, "order-consumer-group", config)
group.Consume(ctx, []string{"order-events"}, &handler{})
```

**`auto.offset.reset` 三个取值：**

| 取值 | 行为 |
|------|------|
| `earliest` | 无有效 offset 时从最早消息开始 |
| `latest`（默认） | 无有效 offset 时从最新消息开始 |
| `none` | 无有效 offset 时抛异常 |

---

## 6. 消费者分组消费机制详解

### 6.1 Consumer Group 模型

```
Topic（4 个 Partition）
P0 P1 P2 P3
 │  │  │  │
 ▼  ▼  ▼  ▼
Group-A: C1(P0,P1)  C2(P2,P3)   ← 组内分摊，负载均衡
Group-B: C3(P0,P1,P2,P3)        ← 另一组独立消费全量
```

核心规则：
- **同一 Partition 在一个 Group 内只会被一个 Consumer 消费**（保证组内不重复）
- 不同 Group 之间相互独立，各自消费全量消息（广播效果）
- Consumer 数 > Partition 数时，多出的 Consumer **空闲**（无分区可分）

### 6.2 Rebalance（重平衡）

**触发条件：**

1. 新 Consumer 加入组
2. Consumer 主动离开（`leaveGroup`）或心跳超时（`session.timeout.ms`，默认 45s）
3. Consumer 消费超时（`max.poll.interval.ms`，默认 5min）被踢出
4. Topic 的 Partition 数量增加
5. 订阅的 Topic 集合变化（正则订阅匹配到新 Topic）

**分配策略（`partition.assignment.strategy`）：**

| 策略 | 类名 | 特点 |
|------|------|------|
| Range（默认） | `RangeAssignor` | 按 Topic 顺序连续分配，可能不均匀 |
| RoundRobin | `RoundRobinAssignor` | 轮询分配，较均匀 |
| Sticky | `StickyAssignor` | Rebalance 时尽量保持已有分配，2.3+ |
| Cooperative Sticky | `CooperativeStickyAssignor` | 增量式 Rebalance，避免 STW，**3.0+ 推荐** |

**Eager vs. Cooperative Rebalance：**

```
Eager Rebalance（旧）:
全体 Consumer 撤销所有 Partition → 停止消费 → 重新分配 → 恢复消费
                 [stop the world]

Cooperative Rebalance（新，2.3+）:
Consumer1 仅撤销需要转移的 Partition → 重新分配 → Consumer2 接管
                [增量式，未受影响的分区不停顿]
```

**【面试】如何减少 Rebalance 对业务的影响？如何诊断频繁 Rebalance？**

减少影响：
1. 使用 `CooperativeStickyAssignor` 替代 Range/RoundRobin
2. 合理设置 `session.timeout.ms`（默认 45s）与 `heartbeat.interval.ms`（默认 3s，约为 session 的 1/3）
3. 避免 poll 间隔内处理过长，或调大 `max.poll.interval.ms` / 减小 `max.poll.records`
4. 使用**静态成员** `group.instance.id`，让 Consumer 以固定 ID 注册，重启不触发 Rebalance
5. `group.initial.rebalance.delay.ms` 设置合理值（如 3s），避免启动期频繁 Rebalance

诊断：
1. 监控 `consumer-coordinator-metrics` 的 `rebalance-rate-per-hour`（> 10/h 需警惕）
2. 检查 Broker 端 `[GroupCoordinator]` 日志中的 Rebalance 原因
3. 核对 `max.poll.records × 单条处理耗时` 是否超过 `max.poll.interval.ms`

### 6.3 Coordinator（消费者组协调器）

**【面试】GroupCoordinator 如何确定？消费者如何找到它？**

```
// 1. 对 group.id 哈希，对 __consumer_offsets 分区数取模
coordinatorPartition = hash("my-group") % offsets.topic.num.partitions(默认 50)

// 2. 该 Partition 的 Leader 所在 Broker 即为该 Group 的 GroupCoordinator
```

Coordinator 职责：管理成员注册/注销、触发并协调 Rebalance、管理偏移量提交与读取（存于 `__consumer_offsets`）。

### 6.4 偏移量（Offset）管理

**存储机制：** 2.0+ 默认提交到内部 Topic `__consumer_offsets`（而非 ZooKeeper）。
- Key：`<groupId, topic, partition>`
- Value：`<offset, leaderEpoch, metadata, commitTimestamp>`

**提交方式：**

| 方式 | API | 说明 |
|------|-----|------|
| 自动提交 | `enable.auto.commit=true` | 定时提交，`auto.commit.interval.ms` 默认 5s，有丢/重风险 |
| 手动同步 | `commitSync()` | 阻塞直到成功，自动重试 |
| 手动异步 | `commitAsync()` | 非阻塞，回调处理失败，不重试 |
| 提交指定偏移 | `commitSync(offsetsMap)` | 精细控制 |

**【面试】`commitAsync` 和 `commitSync` 如何配合？**

推荐：正常循环用 `commitAsync`（高吞吐），关闭前最终提交用 `commitSync`（确保落地）。

```java
try {
    while (running) {
        ConsumerRecords<String, String> records = consumer.poll(Duration.ofMillis(100));
        process(records);
        consumer.commitAsync();        // 正常循环：异步，不阻塞
    }
} finally {
    try {
        consumer.commitSync();         // 关闭前：同步，确保最终偏移量落地
    } finally {
        consumer.close();
    }
}
```

### 6.5 消息重复 / 丢失的成因与对策

| 问题 | 根因 | 解决方案 |
|------|------|----------|
| 消息丢失 | 自动提交 + 消费未完成就触发 Rebalance | 关闭自动提交，先处理再提交 |
| 消息重复 | 处理完成后、提交前发生 Rebalance/宕机 | 业务幂等、去重表、Kafka 事务 |
| 消费超时踢出 | 单批处理耗时 > `max.poll.interval.ms` | 调大超时、减小 `max.poll.records`、异步处理 |
| Rebalance 风暴 | 频繁心跳超时或成员抖动 | 静态成员 + CooperativeSticky + 调大超时 |

### 6.6 再均衡监听器（RebalanceListener）

**【面试】如何在 Rebalance 时优雅处理未完成的消息？**

在分区被撤销前（`onPartitionsRevoked`）提交偏移量，在分区分配后（`onPartitionsAssigned`）恢复状态：

```java
consumer.subscribe(topics, new ConsumerRebalanceListener() {
    @Override
    public void onPartitionsRevoked(Collection<TopicPartition> partitions) {
        consumer.commitSync(currentOffsets);   // 撤销前提交，防止重复消费
    }
    @Override
    public void onPartitionsAssigned(Collection<TopicPartition> partitions) {
        for (TopicPartition tp : partitions) {
            consumer.seek(tp, externalStore.readOffset(tp));   // 从外部存储恢复
        }
    }
});
```

---

## 7. 生产者拦截器机制详解

### 7.1 ProducerInterceptor 接口

拦截器允许在消息**发送前**和**收到 ack 后**插入自定义逻辑，无需修改业务代码。

```java
public interface ProducerInterceptor<K, V> {
    // 消息序列化和分区分配之前调用（可修改消息）
    ProducerRecord<K, V> onSend(ProducerRecord<K, V> record);
    // 消息被 ack 或发送失败时调用（统计、监控）
    void onAcknowledgement(RecordMetadata metadata, Exception exception);
    void close();
}
```

执行时机：

```
producer.send()
  → onSend()           ← 拦截器：可改写/打标 record
  → 序列化
  → 分区器选分区
  → 累加器缓存 → Sender 发送
  → onAcknowledgement() ← 拦截器：成功/失败回调（在 Sender 线程执行）
```

### 7.2 典型应用场景

| 场景 | 实现 |
|------|------|
| 统一打标签 | `onSend` 给 Header 注入 traceId、租户 ID |
| 全链路追踪 | 注入 OpenTelemetry trace context |
| 发送统计 | `onAcknowledgement` 统计成功率、延迟分布 |
| 消息审计 | 记录敏感 Topic 的发送方与内容摘要 |

### 7.3 配置与链式拦截器

```java
// 可配置多个拦截器，按列表顺序形成拦截链
props.put("interceptor.classes", Arrays.asList(
    "com.example.TraceInterceptor",
    "com.example.MetricsInterceptor"
));
```

**注意事项：**
- `onAcknowledgement` 在 **Sender 线程**执行，逻辑必须轻量，否则拖慢发送
- 拦截器抛出的异常会被捕获并记录日志，**不会中断发送**（不影响主流程）
- 拦截链中某个拦截器对 record 的修改，会传递给下一个拦截器

---

## 8. 消息序列化机制

### 8.1 序列化器与反序列化器

Kafka 只传输字节数组，Key/Value 在发送前需序列化、消费时需反序列化。

```java
public interface Serializer<T> {
    byte[] serialize(String topic, T data);
}
public interface Deserializer<T> {
    T deserialize(String topic, byte[] data);
}
```

**内置序列化器：** `StringSerializer`、`IntegerSerializer`、`LongSerializer`、`ByteArraySerializer`、`ByteBufferSerializer`、`DoubleSerializer` 等。

### 8.2 序列化方案对比

| 方案 | 体积 | 跨语言 | Schema 演进 | 可读性 | 适用 |
|------|------|--------|------------|--------|------|
| JSON | 大 | 好 | 弱 | 高 | 调试友好、Schema 不严格 |
| Avro | 小 | 好 | **强**（Schema Registry） | 低 | 大数据生态首选 |
| Protobuf | 小 | 好 | 强 | 低 | gRPC 生态、强类型 |
| Thrift | 小 | 好 | 强 | 低 | 老牌 RPC 生态 |
| Java 原生序列化 | 大 | **差** | 弱 | 低 | 不推荐（跨语言不可用） |

### 8.3 自定义序列化器

```java
public class OrderSerializer implements Serializer<Order> {
    private final ObjectMapper mapper = new ObjectMapper();
    @Override
    public byte[] serialize(String topic, Order order) {
        if (order == null) return null;
        try {
            return mapper.writeValueAsBytes(order);
        } catch (Exception e) {
            throw new SerializationException("序列化 Order 失败", e);
        }
    }
}
// 使用
props.put("value.serializer", "com.example.OrderSerializer");
```

### 8.4 Schema Registry（Schema 注册中心）

**【面试】生产环境为什么需要 Schema Registry？**

在大规模数据管道中，生产者与消费者由不同团队维护，消息结构会持续演进。Schema Registry（Confluent / Apicurio）解决：

- **Schema 集中管理**：消息体只携带 Schema ID（几字节），而非完整 Schema，节省带宽
- **兼容性校验**：注册新 Schema 时检查兼容性（BACKWARD / FORWARD / FULL），防止破坏下游
- **演进安全**：
  - `BACKWARD`：新 Schema 可读旧数据（最常用，可先升级消费者）
  - `FORWARD`：旧 Schema 可读新数据（可先升级生产者）
  - `FULL`：双向兼容

```
Producer → 序列化(Avro) → 向 Registry 注册/查询 Schema ID
        → 消息 = [magic byte][schema id][avro payload] → Kafka
Consumer → 取 schema id → 向 Registry 拉取 Schema → 反序列化
```

---

## 9. 消息分区路由机制

### 9.1 默认分区器（DefaultPartitioner）

消息最终落到哪个 Partition，由分区器决定：

| 情况 | 路由规则 |
|------|---------|
| 指定了 `partition` | 直接使用指定分区 |
| 未指定 partition、**Key 不为 null** | `murmur2(key) % numPartitions`（相同 Key 必到同一分区） |
| 未指定 partition、**Key 为 null** | 粘性分区（Sticky Partitioner，2.4+） |

### 9.2 粘性分区（Sticky Partitioner）

```
旧版本（2.4 之前）：无 Key 消息每次轮询一个 Partition → 产生大量小批次，吞吐低
新版本（2.4+）：在一个批次未满期间，无 Key 消息都发往同一 Partition
              → 批次填满后才换分区，提高批次利用率，降低延迟
```

### 9.3 自定义分区器

```java
public class OrderPartitioner implements Partitioner {
    @Override
    public int partition(String topic, Object key, byte[] keyBytes,
                         Object value, byte[] valueBytes, Cluster cluster) {
        int numPartitions = cluster.partitionsForTopic(topic).size();
        // 例：VIP 订单固定路由到 0 号分区
        if (key != null && key.toString().startsWith("VIP")) {
            return 0;
        }
        return Math.abs(Utils.murmur2(keyBytes)) % numPartitions;
    }
}
props.put("partitioner.class", "com.example.OrderPartitioner");
```

### 9.4 有序性保证

**【面试】如何保证消息有序？如何把同一业务实体路由到同一 Partition？**

1. **Key 哈希**：为同一业务实体（如 orderId）设置相同 Key，相同 Key 必进同一 Partition，Partition 内有序
2. **自定义分区器**：实现 `partition()` 自定义路由

关键约束：
- 有序性只能在**单 Partition 内**保证，跨 Partition 无序
- 重试可能打乱顺序：需设 `max.in.flight.requests.per.connection=1`，**或** 开启幂等（`enable.idempotence=true`，此时即使 `max.in.flight=5` 也能保证单分区有序）
- 增加 Partition 数量会破坏既有 Key 路由关系，需谨慎

**分区倾斜**：Key 分布不均会导致部分分区/Broker 过热。对策：检查分区策略、必要时加随机盐值或改用自定义分区器。

---

## 10. 生产者消息缓存机制

### 10.1 RecordAccumulator 内存模型

生产者并非每条消息都立即发送，而是先攒批到缓存区，由后台 Sender 线程批量发出。

```
Producer 实例
├── RecordAccumulator（消息累加器，大小 = buffer.memory，默认 32MB）
│   ├── TopicPartition-0 → Deque<ProducerBatch>  [batch1][batch2]
│   ├── TopicPartition-1 → Deque<ProducerBatch>  [batch3]
│   └── ...（每个分区一个双端队列）
└── Sender 线程（后台）
    → 从累加器取就绪批次 → 按 Broker 分组 → 组成 ClientRequest → 发送
```

### 10.2 关键参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `buffer.memory` | 32MB | 累加器总内存上限 |
| `batch.size` | 16KB | 单个 ProducerBatch 的字节上限，攒满即发 |
| `linger.ms` | 0 | 批次未满时，最多等待多久再发（攒批窗口） |
| `max.block.ms` | 60000 | 缓冲区满时 `send()` 的最大阻塞时间，超时抛异常 |
| `max.request.size` | 1MB | 单次请求最大字节数 |

### 10.3 批次发送的触发时机

一个批次在满足任一条件时被 Sender 发送：
1. 批次大小达到 `batch.size`
2. 距离批次创建经过了 `linger.ms`
3. 有新批次要分配但 `buffer.memory` 不足，触发刷出
4. 调用了 `flush()` 或 `close()`

**【面试】`linger.ms` 和 `batch.size` 如何权衡？增大它们一定提高吞吐吗？**

二者共同决定批次填充度与发送延迟：

| 策略 | linger.ms | 延迟 | 吞吐 | 适用 |
|------|-----------|------|------|------|
| 低延迟 | 0~5ms | 低 | 低 | 实时响应型 |
| 高吞吐 | 10~100ms | 高 | 高 | 批量型 |

权衡点：
- `batch.size` 过大 → 小消息场景内存浪费、排队时间增加
- `linger.ms` 过大 → 延迟上升，消息堆积在 Producer 端
- 推荐初始值：`batch.size=64KB`，`linger.ms=5~10ms`
- 若 Producer 端 `waiting-threads` 指标 > 0，说明缓冲区满，需增大 `buffer.memory` 或优化下游消费速度

### 10.4 内存满时的行为

```
send() 被调用
  → 累加器申请内存
  → 若 buffer.memory 不足
      → 阻塞，最多等 max.block.ms
      → 期间 Sender 持续发送以腾出空间
      → 仍超时 → 抛 TimeoutException
```

> 这是「背压（backpressure）」机制：当下游/网络跟不上时，生产端主动阻塞，避免内存溢出。

---

## 11. 生产者发送应答机制

> 应答机制（acks）决定「消息算写成功」的标准，它直接依赖 Broker 端的**副本机制**。本节先讲 acks，再深入其背后的 ISR / HW / Leader Epoch。

### 11.1 acks 参数

| 值 | 含义 | 可靠性 | 延迟 |
|----|------|--------|------|
| `acks=0` | 不等任何确认，发出即认为成功 | 最低（可能丢） | 最快 |
| `acks=1`（旧默认） | Leader 写入本地即确认 | 中（Leader 宕机可能丢） | 较快 |
| `acks=all`/`-1` | ISR 全部副本确认 | 最高 | 最慢 |

> `acks=all` 必须搭配 `min.insync.replicas>=2` 才有意义：若 ISR 只剩 Leader 一个副本，`acks=all` 退化为 `acks=1`，Leader 宕机仍丢数据。

### 11.2 副本机制：AR / ISR / OSR

**【面试】解释 AR、ISR、OSR，以及 ISR 的判定标准。**

- **AR（Assigned Replicas）**：分区的全部副本列表
- **ISR（In-Sync Replicas）**：与 Leader 保持同步的副本集合（含 Leader 自身）
- **OSR（Out-of-Sync Replicas）**：同步滞后的副本，`AR = ISR + OSR`

ISR 判定标准（由 `replica.lag.time.max.ms` 控制，默认 30s）：
- Follower 须在该时间内持续向 Leader 发起 **fetch 请求**并追上 Leader 的 LEO
- 0.9+ 后**只按时间判断**，不再按落后消息条数（避免突发流量误判）
- 超时未追上 → 踢出 ISR；重新追上 → 自动加回

```scala
// kafka.cluster.Partition#maybeShrinkIsr —— 找出不同步副本并收缩 ISR
val outOfSyncReplicas = currentIsr.filter { replica =>
  (time.milliseconds() - replica.lastFetchTimeMs) > configs.replicaLagTimeMaxMs
}
if (outOfSyncReplicas.nonEmpty) updateIsr(currentIsr -- outOfSyncReplicas)
```

### 11.3 HW 与 LEO

**【面试】HW、LEO 是什么？Consumer 能读到 HW 还是 LEO 以内的数据？**

- **LEO（Log End Offset）**：当前副本最后一条消息的下一个位置
- **HW（High Watermark）**：所有 ISR 副本都已同步到的 offset，**Consumer 只能读到 HW 之前的数据**

```
                Leader          Follower1      Follower2
LEO:            10              8              5
HW = min(所有 ISR 副本的 LEO) = min(10, 8, 5) = 5
Consumer 可见范围：offset < 5
```

HW 更新流程：
1. Producer 写入 Leader → Leader 的 LEO 增加，HW 暂不变
2. Follower 发 FetchRequest 拉取 → 写本地日志 → 更新自身 LEO
3. Leader 收到 ISR 内所有 Follower 的 fetch 进度后，HW = min(所有 ISR 副本 LEO)
4. 后续 fetch 响应携带新 HW，Follower 据此更新自身 HW

### 11.4 Leader Epoch

**【面试】Leader Epoch（0.11 引入）解决了什么问题？**

解决纯 HW 截断机制导致的**数据丢失**与**数据不一致**：

```
问题场景：
Step1: Leader LEO=12，Follower 落后，HW=5
Step2: Leader 宕机，Follower 成为新 Leader，HW=5
Step3: 原 Leader 恢复，按旧 HW=5 截断日志 → offset 5~11 的数据丢失！
```

Leader Epoch 方案：每个 Leader 任期记录 `<epoch, startOffset>`。副本重启后先发 `LeaderEpochRequest` 询问新 Leader 该 epoch 的起始偏移量，据此精确截断，而非盲目按 HW 截断。

```scala
// kafka.server.epoch.LeaderEpochFileCache —— 存于 leader-epoch-checkpoint
// 如 [(0,0),(1,100),(2,200)]：epoch 1 从 offset 100 开始
def assign(epoch: Int, startOffset: Long): Unit
def endOffsetFor(epoch: Int): Option[Long]
```

### 11.5 Unclean Leader Election（不完全 Leader 选举）

**【面试】`unclean.leader.election.enable` 设 true / false 的影响？**

| 配置 | 行为 | 一致性 | 可用性 |
|------|------|--------|--------|
| `false`（推荐） | 只允许 ISR 副本当 Leader | 强一致 | 较低（ISR 全下线则分区不可用） |
| `true` | 允许 OSR 副本当 Leader | 弱一致（可能丢数据） | 较高 |

- **金融/核心业务**：`false`，宁可不可用也不丢数据
- **日志/可观测**：`true`，可用性优先
- 配合 `min.insync.replicas=2`、`replication.factor=3` 形成典型可靠配置

### 11.6 Producer 端如何保证不丢消息（完整链路）

**【面试】消息不丢失需要从哪几个维度保证？**

从 Producer、Broker、Consumer 三个维度，缺一不可：

```
Producer 侧：acks=all + enable.idempotence=true
           + retries=Integer.MAX_VALUE + 回调处理失败（不要 fire-and-forget）
Broker 侧：  replication.factor>=3 + min.insync.replicas>=2
           + unclean.leader.election.enable=false
Consumer 侧：enable.auto.commit=false + 先处理再提交 + 业务幂等兜底
```

易忽略的细节：
- `acks=all` 但 `min.insync.replicas=1` 时，ISR 只剩 Leader，宕机仍丢
- 日志保留策略（`retention.ms`/`retention.bytes`）到期后，即使未消费也会删除

---

## 12. 生产者消息幂等性

### 12.1 开启方式与原理

开启：`enable.idempotence=true`（Kafka 3.0+ **默认开启**）。

```go
// 幂等 Producer 请求协议字段（对应 Kafka ProducerRequest）
type ProducerRequest struct {
    ProducerID     int64   // 服务端分配的 PID（首次请求返回）
    ProducerEpoch  int16   // Producer 初始化递增，用于 fencing 旧 Producer
    SequenceNumber int32   // 按 <PID, Partition> 单调递增，从 0 开始
    Data           []RecordBatch
}
```

Broker 端按 `<PID, Partition, SequenceNumber>` 三元组去重：
- `seq == expectedSeq + 1` → 接受
- `seq <= expectedSeq` → 丢弃（重复，由网络重试导致）
- `seq > expectedSeq + 1` → 拒绝（说明中间有消息丢失，乱序）

### 12.2 局限性

**【面试】幂等 Producer 的局限性是什么？**

1. **只保证单 Partition 内 Exactly Once**：跨 Partition 需事务 API
2. **只保证 Producer → Broker 间不重复**：Consumer 端仍可能重复投递
3. **只在单 Session 内有效**：Producer 重启后 PID 变化，无法对旧 PID 的消息去重
4. 因此「端到端 Exactly Once」需要 **幂等 + 事务 + 消费端 read_committed** 三者配合

### 12.3 幂等 vs 事务

| 特性 | 幂等 Producer | 事务 Producer |
|------|---------------|---------------|
| 保障级别 | 单会话单分区不丢不重 | 跨分区、跨会话原子性 |
| 跨分区原子性 | 不支持 | 支持 |
| 跨会话幂等 | 不支持 | 支持 |
| 性能开销 | 几乎无 | 吞吐下降 10%~50% |
| 配置 | `enable.idempotence=true` | 额外配 `transactional.id` |

---

## 13. 消息压缩机制与消息事务

### 13.1 压缩算法对比

| 算法 | 压缩比 | CPU 开销 | 速度 | 适用场景 |
|------|--------|---------|------|---------|
| none | 无 | 无 | — | 不推荐 |
| gzip | 高 | 高 | 慢 | 带宽受限、追求高压缩比 |
| snappy | 中 | 低 | 快 | 吞吐优先 |
| lz4 | 中 | 低 | 快 | **吞吐优先，常用推荐** |
| zstd | 最高 | 中 | 中快 | 追求极致压缩比（2.1+） |

### 13.2 压缩配置与原理

```properties
# Producer 端压缩（推荐，在客户端就压缩，节省网络）
compression.type=lz4

# Broker 端：沿用 Producer 压缩格式，避免重新压缩
compression.type=producer
```

要点：
- 压缩在**批次级别**进行，批次越大压缩比越高（压缩 + 攒批效果叠加）
- 若 Broker 的 `compression.type` 与 Producer 不同，Broker 会**解压再重新压缩**，增加 CPU 开销
- 压缩对零拷贝**无影响**：消息以压缩态存储和传输，由 Consumer 解压

### 13.3 事务消息

**配置：**

```properties
# Producer
transactional.id=order-tx-1      # 唯一事务标识（跨会话幂等的关键）
enable.idempotence=true          # 事务必须开启幂等
transaction.timeout.ms=60000

# Consumer
isolation.level=read_committed   # 只消费已提交事务的消息
```

**事务 API 流程：**

```java
producer.initTransactions();
try {
    producer.beginTransaction();
    producer.send(new ProducerRecord<>("topic-a", key, value));
    producer.send(new ProducerRecord<>("topic-b", key, value));
    // 消费-处理-生产场景：把消费位移也纳入事务
    producer.sendOffsetsToTransaction(offsets, consumerGroupMetadata);
    producer.commitTransaction();
} catch (Exception e) {
    producer.abortTransaction();
}
```

**事务状态流转：**

```
EMPTY → ONGOING → COMMITTING → COMMITTED
              └→ ABORTING  → ABORTED
```

- 由**事务协调器（Transaction Coordinator）** 管理，状态存于内部 Topic `__transaction_state`（默认 50 分区）
- 两阶段提交：写消息（标记未提交）→ 写 COMMIT/ABORT Marker

### 13.4 Exactly-Once 与 read_committed

**【面试】Exactly Once 如何实现？read_committed 的原理？**

端到端 EOS = 幂等 Producer + 事务 + 消费端 `read_committed`：

```
生产者：enable.idempotence=true + transactional.id
Broker：acks=all + replication.factor>=3 + min.insync.replicas>=2
消费者：isolation.level=read_committed + 手动提交 + sendOffsetsToTransaction()
```

`read_committed` 原理：
- Broker 维护 **LSO（Log Stable Offset）** = 第一条未提交事务消息的 offset
- `read_committed` 消费者只能读到 LSO 之前的消息
- 通过 `.txnindex` 文件过滤已回滚（ABORT）的消息

**【面试】卡住的事务（长时间未提交）有什么影响？如何解决？**

- 长时间未提交的事务会使 LSO 停滞，`read_committed` 消费者被阻塞
- `transaction.timeout.ms`（默认 60s）超时后，Coordinator 自动 abort 该事务
- 建议：设置合理超时（如 ≤ 120s）、监控未完成事务数量
- 高吞吐场景优先考虑**下游幂等**而非事务（EOS 带来 10%~50% 吞吐下降）；EOS v2（2.5+）可减少协调器交互，性能提升约 30%

---

# 附录 A · 服务端原理与生产运维（待对齐视频后续目录）

> 以下内容属于服务端深度原理与生产运维，对应视频在 kfk2-9 之后的章节（你贴出的目录尚未覆盖到这里）。先按主题归档保留，待补全后续目录后再对齐章节编号。源码级更深入的剖析见 [`deep-dive/kafka-internals-deep-dive.md`](./deep-dive/kafka-internals-deep-dive.md)。

## A.1 存储原理

### 日志存储（Log Segment）

```
/topics/order-events-0/
├── 00000000000000000000.log       # 消息数据
├── 00000000000000000000.index     # 偏移量索引（稀疏）
├── 00000000000000000000.timeindex # 时间戳索引
└── 00000000000000000059.snapshot  # 生产者状态快照
```

- LogSegment 是存储的最小物理单元，默认 1GB（`log.segment.bytes`）
- 活跃 Segment 可写，历史 Segment 只读
- Segment 命名以其首条消息的偏移量为基准（20 位补零）

**【面试】Kafka 为什么快？**

1. **顺序 I/O**：追加写，顺序写约 600MB/s vs 随机写约 100KB/s（差约 6000 倍）
2. **Page Cache**：写先落 OS Page Cache 异步刷盘，读优先命中 Page Cache
3. **零拷贝**：消费读取走 `sendfile`，数据从 Page Cache 直达网卡
4. **批量 + 压缩**：Producer 批量发、Broker 批量写、Consumer 批量拉
5. **稀疏索引**：索引文件小，可常驻内存

### 索引文件

- **偏移量索引（.index）**：稀疏索引，每写 `log.index.interval.bytes`（默认 4KB）记一条 `<相对偏移, 物理位置>`。查找：二分索引 → 物理位置范围 → 顺序扫描 .log
- **时间戳索引（.timeindex）**：`<时间戳, 相对偏移>`，用于按时间查找消息

> 索引损坏可由 .log 重建（.log 含完整数据，索引仅加速）。索引文件用 **mmap** 做随机读写。

### 零拷贝（sendfile）

```
传统路径：磁盘→内核缓冲→用户缓冲→Socket缓冲→网卡（4 次拷贝 + 4 次上下文切换）
零拷贝：  磁盘→PageCache→网卡（2 次 DMA 拷贝 + 0 次 CPU 拷贝 + 2 次上下文切换）
```

- `sendfile`（`FileChannel.transferTo`）用于 Consumer 读取
- 索引文件用 `mmap`（适合小文件随机读写，sendfile 适合大文件传输）

### 日志清理与压缩

| 策略 | `log.cleanup.policy` | 行为 |
|------|---------------------|------|
| 删除 | `delete` | 按时间/大小删除老 Segment |
| 压缩 | `compact` | 每个 Key 只保留最新值 |

```
压缩前：k1=A, k2=B, k1=C, k3=D
压缩后：k2=B, k1=C, k3=D（offset 不连续）
```

- Cleaner 线程独立执行，`min.cleanable.dirty.ratio=0.5` 触发
- 适用 KV 语义数据（用户配置、`__consumer_offsets`）；普通业务 Topic 用 `delete`

## A.2 Controller 与协调器

**【面试】Controller 的职责？如何选举？宕机如何恢复？**

职责：管理分区 Leader 选举、监听 Broker 上下线、管理元数据变更并同步到所有 Broker。

ZK 模式选举：
```
1. 所有 Broker 抢占创建 ZK 临时节点 /controller
2. 第一个成功者成为 Controller
3. 其余 Broker 注册 Watcher 监听 /controller
4. Controller 宕机 → 临时节点消失 → Watcher 触发 → 重新竞选
```

- 唯一性靠 ZK 临时节点 + 递增 `controller_epoch` 保证
- 僵尸 Controller 的请求因 epoch 较低被拒绝

## A.3 KRaft 模式

**演进：** 2.8 预览 → 3.3 生产可用 → 4.0 移除 ZK。

```
KRaft 架构：
  元数据日志（Metadata Topic）← Raft 共识
  Controller1  Controller2  Controller3（奇数个 Voter）
  Broker ← 从元数据日志同步（Observer）
```

**【面试】KRaft 相比 ZK 的优势？**

1. 架构简化：无需维护 Kafka + ZK 两套系统
2. 故障检测更快：ZK session 秒级 → Raft 心跳百毫秒级
3. 元数据同步更快：直接基于 Raft Log，无 ZK 序列化开销
4. 支持更大规模：测试验证 200 万分区
5. 选举机制：ZK 临时节点 + Watcher → Raft 多数派共识（避免脑裂）

```properties
# KRaft 最小配置
process.roles=broker,controller
node.id=1
controller.quorum.voters=1@n1:9093,2@n2:9093,3@n3:9093
```

Controller Quorum 遵循 `n = 2f + 1`，容忍 f 个节点故障。

## A.4 性能调优

### OS 层

```bash
vm.swappiness=1               # Kafka 重度依赖 Page Cache，尽量不 swap
vm.dirty_background_ratio=5   # 脏页后台回写阈值
vm.dirty_ratio=20             # 脏页强制回写阈值
```

- 文件系统推荐 XFS，挂载 `noatime`；优先 SSD/NVMe
- Kafka 消息数据在 Page Cache，**JVM 堆建议 4~8GB**，其余内存留给 Page Cache

### JVM GC

```bash
-XX:+UseG1GC -XX:MaxGCPauseMillis=20
-XX:InitiatingHeapOccupancyPercent=35
-Xms6G -Xmx6G            # 堆不超 8GB，否则 GC 停顿长导致 Broker 被踢
```

**【面试】堆为什么不建议超过 8GB？**
消息数据在 Page Cache 不在堆内；堆太大 → GC 停顿长 → Broker 响应超时 → 分区 Leader 迁移。

### 网络与 IO 线程

```properties
num.network.threads=3    # ≈ CPU 核数 / 2
num.io.threads=8         # ≈ CPU 核数 * 2
num.replica.fetchers=2
queued.max.requests=500
```

## A.5 生产运维

### 监控核心指标

| 类别 | 指标 | 告警阈值 |
|------|------|---------|
| 服务端 | `UnderReplicatedPartitions` | > 0 |
| 服务端 | `OfflinePartitionsCount` | > 0 |
| 服务端 | `ActiveControllerCount` | != 1 |
| 服务端 | `ISRShrinkRate` | 异常升高 |
| 消费者 | `records-lag-max`（Consumer Lag） | 超业务阈值 |
| 消费者 | `rebalance-rate-per-hour` | > 10/h |
| 吞吐 | `BytesInPerSec` / `BytesOutPerSec` | 周期对比 |

**【面试】Consumer Lag 上升如何排查？**

```
Consumer Lag 上升
├── 消费能力不足（单条耗时长 / 线程不足 / 下游 DB/API 阻塞）
├── 生产流量突增（排查上游 / 扩容分区 + 消费者）
├── Rebalance 频繁（session.timeout 过小 / 处理超时 / 网络抖动）
└── Broker 瓶颈（磁盘 IO Wait / 网络打满 / Leader 分布不均）
```

解决：扩容消费者（≤ 分区数，不足先加分区）、增大 `max.poll.records`/`fetch.max.bytes`、异步处理、优化业务逻辑。

### 分区重分配

```bash
# 生成 → 执行（限流 50MB/s）→ 验证
kafka-reassign-partitions.sh --execute \
  --reassignment-json-file reassign.json \
  --throttle 50000000 --bootstrap-server localhost:9092
```

本质是数据搬迁：新副本同步 → 追上 HW 加入 ISR → 切 Leader → 删旧副本。建议低峰执行并监控 `UnderReplicatedPartitions`。

### 数据保留

```properties
log.retention.hours=168      # 7 天
log.retention.bytes=-1       # 大小上限（默认无限）
log.segment.bytes=1073741824 # 1GB
```

LogManager 每 5 分钟检查：删过期 Segment、删超限 Segment。建议时间 + 大小双策略。

### 滚动升级要点

1. 关闭自动 Leader 均衡 → 逐台关停 Broker 等待 Leader 切换 → 升级重启 → 确认 ISR 恢复 → 重复
2. 先升级 Broker 再升级客户端；确认 RPC 协议兼容，跨大版本需逐版本升级
3. 准备回滚方案；KRaft 模式注意元数据版本兼容

### 常见故障速查

| 现象 | 排查方向 |
|------|---------|
| Producer 发送超时 | Broker 是否在线、RequestQueue 是否堆积、IO 线程不足 |
| 消费者组卡住 | 是否频繁 Rebalance、`max.poll.records × 处理耗时` 是否超时 |
| 磁盘写满 | 调小 retention 立即触发清理、扩容 + 重分配 |
| Leader 频繁切换 | 网络延迟/丢包、GC 停顿、副本同步被 IO Wait 阻塞 |

## A.6 与其他 MQ 选型对比

### Kafka vs RabbitMQ

| 维度 | Kafka | RabbitMQ |
|------|-------|----------|
| 定位 | 分布式流平台 | 消息代理（AMQP） |
| 模型 | Topic/Partition/Offset | Exchange/Queue/RoutingKey |
| 消费 | Pull | Push/Pull |
| 顺序 | 单 Partition 内有序 | 单 Queue 内有序 |
| 延迟消息 | 不原生支持 | 原生支持（插件/TTL+DLQ） |
| 吞吐 | 百万条/秒 | 万~十万条/秒 |
| 延迟 | 毫秒级 | 微秒级 |
| 长期保留/回溯 | 强 | 弱（投递完即删） |

### Kafka vs RocketMQ vs Pulsar

| 维度 | Kafka | RocketMQ | Pulsar |
|------|-------|----------|--------|
| 架构 | 计算存储耦合 | NameServer + 主从 | **计算存储分离** |
| 吞吐 | **百万级 TPS** | 十万~百万 | 十万~百万 |
| 延迟 | 毫秒级 | **最低 <3ms** | P99 较高 |
| 最大 Topic 数 | 数万 | 数万 | **百万级** |
| 延迟/定时消息 | 不支持 | **原生（任意精度）** | 原生 |
| 事务消息 | 支持 | **原生成熟（2PC）** | 原生 |
| 多租户 | 弱 | 命名空间 | **原生强隔离** |
| 云原生 | 中 | 中 | **最佳** |

**选型建议：**
- 大数据/日志/流处理/高吞吐 → **Kafka**
- 电商金融/事务顺序/高可靠 → **RocketMQ**
- 云原生/多租户/跨地域 → **Pulsar**
- 灵活路由/延迟消息/逐条确认/低运维 → **RabbitMQ**

## A.7 Kafka Streams 与 ksqlDB

| 抽象 | 说明 |
|------|------|
| KStream | 不可变、仅追加的事件流 |
| KTable | 可变键值表（由 Compacted Topic 支持） |
| GlobalKTable | 全局复制表，用于维表关联 |
| State Store | 本地状态存储（RocksDB），由 Changelog Topic 容错 |

**流表二象性（Stream-Table Duality）：** Stream 经聚合（取每个 Key 最新值）变 Table；Table 经变更日志（changelog）变 Stream。同一 Topic 既可读作 Stream 也可读作 Table。

**窗口类型：** Tumbling（固定不重叠）、Hopping（固定可重叠）、Session（活动间隔）、Sliding（流-流 Join）。

**ksqlDB 查询：** Pull Query（点查物化视图）、Push Query（持续推送）、Persistent Query（结果写回 Topic）。

---

# 附录 B · 高频面试题库（分级）

> 正文各节已穿插标注 **【面试】** 题，本附录按经验层级汇总 20 道高频综合题，便于面试前突击。

## 基础篇（3 年以下）

**Q1. Kafka 为什么这么快？**
顺序写（600MB/s vs 随机写 100KB/s）+ Page Cache（避免 GC）+ 零拷贝 sendfile（2 次 DMA、0 次 CPU 拷贝）+ 稀疏索引（小可常驻内存）+ 批量 + 压缩。

**Q2. ISR、OSR、AR 的关系？**
`AR = ISR + OSR`。ISR 是与 Leader 同步的副本（含 Leader），准入条件是 `replica.lag.time.max.ms` 内持续 fetch 并追上 LEO。只有 ISR 能选新 Leader（`unclean.leader.election.enable=false`）。

**Q3. acks=0/1/all 的区别与适用场景？**
0 不等确认（可能丢，日志采集）；1 Leader 写入即确认（默认折中）；all ISR 全确认（最高可靠，配 `min.insync.replicas>=2`）。

**Q4. Producer 如何保证不丢消息？**
`acks=all` + `retries=MAX` + `enable.idempotence=true` + 回调处理失败 + 合理 `delivery.timeout.ms`。

**Q5. Rebalance 触发条件？**
消费者数量变化、分区数增加、订阅 Topic 变更、心跳超时（`session.timeout.ms`）、消费超时（`max.poll.interval.ms`）。

## 进阶篇（3-5 年）

**Q6. HW 和 LEO 是什么？HW 如何更新？**
LEO = 下一条待写入 offset；HW = ISR 全部副本都同步到的 offset，消费者只能读 HW 之前。`HW = min(ISR 所有副本 LEO)`。

**Q7. Leader Epoch 解决了什么？**
解决纯 HW 机制的数据丢失/错乱。每个 Leader 任期分配递增 epoch + 记录起始 offset，副本重启后先问 Leader 该 epoch 的最新 offset 再决定是否截断。

**Q8. 幂等 Producer 原理与局限？**
`<PID, Partition, SeqNo>` 三元组去重。局限：只单会话单分区、Producer→Broker 间、重启后 PID 变失效，跨分区需事务。

**Q9. Kafka 事务的两阶段提交？**
注册 `transactional.id` → Coordinator 分配 PID+epoch → Phase1 写消息标记未提交 + 写 `__transaction_state` → Phase2 写 COMMIT/ABORT Marker。消费端 `read_committed` 按 Marker 过滤，LSO 标记第一条未提交消息。

**Q10. 粘性分区/CooperativeSticky 的原理与优势？**
Rebalance 时尽量保留已有分配，只重分配需平衡的分区，实现增量重平衡，减少 STW 与重复消费。2.4+ 默认。

**Q11. read_committed 下卡住的事务有什么影响？**
长时间未提交事务使 LSO 不推进，阻塞消费端。`transaction.timeout.ms`（默认 60s）超时后 Coordinator 自动 abort。

## 高级篇（5 年以上 / 架构师）

**Q12. 消息不丢失需要从哪几个维度保证？**
Producer（acks=all + 幂等 + retries + 回调）、Broker（replication>=3 + min.insync>=2 + unclean=false）、Consumer（手动提交 + 先处理再提交 + 业务幂等）。注意 `acks=all` 但 `min.insync=1` 仍会丢。

**Q13. 零拷贝细节？为什么读取不用 mmap？mmap 用在哪？**
`FileChannel.transferTo` → `sendfile`，数据全程内核态。读取不用 mmap：mmap 受地址空间限制、有缺页中断抖动、未真正消除 CPU 拷贝。mmap 用于索引文件的随机读写。

**Q14. 10 Broker、5 分区、replication=3 的副本分布与 Leader 选举？**
每分区 3 副本分布在不同 Broker（有机架感知则跨机架）；AR 第一个为 Preferred Leader；Leader 宕机由 Controller 从 ISR 选新 Leader；ISR 空且 unclean=false 则分区不可用。

**Q15. 分区数过多为什么影响性能？如何规划？**
文件句柄暴涨、选举时间变长、内存开销、Leader 切换延迟（Controller 瓶颈）。规划：`Max(吞吐/单分区能力, 消费者线程数)`，单分区约 10MB/s，每 Broker 100~200 分区，取 Broker 数整数倍。

**Q16. 消息积压排查与解决？**
排查：`kafka-consumer-groups --describe` 看 Lag → 判断消费能力还是阻塞 → 查消费者资源/下游瓶颈。解决：扩消费者（≤分区数）、增大拉取量、批量/异步处理、优化业务、必要时跳过非关键消息。

**Q17. KRaft 相比 ZK 的优势与选举区别？**
架构简化、故障检测百毫秒级、元数据同步快、支持 200 万分区、运维简单。选举：ZK 临时节点+Watcher → Raft 多数派共识，避免脑裂。

**Q18. 如何设计 Exactly-Once 流处理管道（Kafka→Flink→Kafka）？**
生产端幂等+事务，消费端 read_committed+手动提交；Flink `CheckpointingMode.EXACTLY_ONCE` 或 Kafka Streams `processing.guarantee=EXACTLY_ONCE_V2`；两阶段提交 Sink。注意外部系统仍需业务幂等，EOS 有 30~50% 吞吐开销。

**Q19. 集群滚动升级的步骤与注意事项？**
关自动均衡 → 逐台关停等 Leader 切换 → 升级重启 → 确认 ISR → 重复 → 开自动均衡。注意 RPC 兼容、先 Broker 后客户端、保留回滚包、KRaft 元数据版本。

**Q20. 如何理解流表二象性？在 Kafka Streams/ksqlDB 中如何体现？**
Stream（仅追加事件序列）与 Table（可变键值视图）可互转。KStream/KTable/GlobalKTable，ksqlDB 的 `CREATE STREAM` vs `CREATE TABLE`。

## 生产踩坑 Top 10

1. 分区数拍脑袋定 → 并行度无法扩展
2. 重试未开幂等 → ACK 超时重试导致重复
3. `acks=all` 但 `min.insync.replicas=1` → ISR 只剩 Leader 仍丢
4. 自动提交 offset → Rebalance 导致重复/丢失
5. 处理时间 > `max.poll.interval.ms` → 消费超时→Rebalance 恶性循环
6. Topic 未隔离 → 实时与离线混用互相影响
7. 未监控 Lag → 积压到磁盘爆满才发现
8. 分区倾斜 → Key 分布不均致部分 Broker 过热
9. JVM 堆过大（>16G）→ GC 停顿致心跳超时被踢
10. KRaft 元数据与数据共用磁盘 → IO 争抢致性能抖动

---

# 附录 C · 参数速查表

### 生产者关键参数

```properties
bootstrap.servers=broker1:9092,broker2:9092,broker3:9092
key.serializer=org.apache.kafka.common.serialization.StringSerializer
value.serializer=org.apache.kafka.common.serialization.StringSerializer

# 可靠性（金融级）
acks=all
enable.idempotence=true
retries=2147483647
max.in.flight.requests.per.connection=5   # 幂等下仍保证单分区有序

# 吞吐
batch.size=65536            # 64KB
linger.ms=10
compression.type=lz4        # 或 zstd
buffer.memory=134217728     # 128MB

# 超时
request.timeout.ms=30000
delivery.timeout.ms=120000
```

### 消费者关键参数

```properties
bootstrap.servers=broker1:9092,broker2:9092
group.id=my-consumer-group
key.deserializer=org.apache.kafka.common.serialization.StringDeserializer
value.deserializer=org.apache.kafka.common.serialization.StringDeserializer

# 偏移量
enable.auto.commit=false
auto.offset.reset=earliest
isolation.level=read_committed   # 事务场景

# 吞吐
max.poll.records=500
fetch.min.bytes=524288           # 512KB
fetch.max.wait.ms=500

# 重平衡
session.timeout.ms=45000
heartbeat.interval.ms=15000      # ≈ session.timeout / 3
max.poll.interval.ms=300000
partition.assignment.strategy=org.apache.kafka.clients.consumer.CooperativeStickyAssignor
```

### Broker 关键参数

```properties
broker.id=1
log.dirs=/data1/kafka,/data2/kafka   # 多磁盘
num.network.threads=3
num.io.threads=8

# 副本
default.replication.factor=3
min.insync.replicas=2
unclean.leader.election.enable=false
replica.lag.time.max.ms=30000

# 存储
log.segment.bytes=1073741824         # 1GB
log.retention.hours=168              # 7 天
log.retention.bytes=-1
log.cleanup.policy=delete            # 或 compact

# 压缩
compression.type=producer            # 沿用 Producer 压缩，避免重压缩

# Controller（KRaft）
controller.quorum.voters=1@c1:9093,2@c2:9093,3@c3:9093
```

### OS / JVM 速查

| 维度 | 建议 |
|------|------|
| JVM 堆 | `-Xms6G -Xmx6G`（留内存给 Page Cache） |
| GC | `-XX:+UseG1GC -XX:MaxGCPauseMillis=20` |
| 磁盘 | SSD/NVMe，XFS，`noatime`，RAID10 |
| 内核 | `vm.swappiness=1`，增大 `vm.max_map_count` |
| 文件句柄 | `ulimit -n 100000` |

---

# 附录 D · 参考资源

### 官方资料
- [Apache Kafka 官方文档](https://kafka.apache.org/documentation/)
- [Confluent 官方文档](https://docs.confluent.io/platform/current/overview.html)
- [Kafka Improvement Proposals (KIPs)](https://cwiki.apache.org/confluence/display/KAFKA/Kafka+Improvement+Proposals)

### 推荐书籍
- 《Kafka: The Definitive Guide》（第 2 版）— Neha Narkhede 等
- 《深入理解 Kafka：核心设计与实践原理》— 朱忠华
- 《Apache Kafka 源码剖析》— 徐郡明
- 《Mastering Kafka Streams and ksqlDB》— Mitch Seymour

### 视频教程
- B 站《企业级消息队列 Kafka 教程，从入门到进阶实战》（本文目录结构参考）

### 站内关联文档
- [`deep-dive/kafka-internals-deep-dive.md`](./deep-dive/kafka-internals-deep-dive.md) — 源码级存储引擎与副本协议深度解析
- [`05-rabbitmq-advanced.md`](./05-rabbitmq-advanced.md) — RabbitMQ 对照阅读

---

> 撰写说明：本文基于 Apache Kafka 3.x 版本特性，按 B 站 Kafka 教程目录（kfk1-1 ~ kfk2-9）组织正文，服务端原理与运维内容暂置于附录 A，待目录补全后对齐章节。Kafka 迭代较快（尤其 KRaft），请以官方文档为准。
