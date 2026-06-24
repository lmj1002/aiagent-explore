# 高级 RabbitMQ 面试知识架构

> 目标受众：5-8 年经验高级后端开发  
> 最后更新：2026-06-15

---

## 目录

1. [核心概念](#1-核心概念)
2. [消息可靠性](#2-消息可靠性)
3. [高级特性](#3-高级特性)
4. [集群与高可用](#4-集群与高可用)
5. [性能调优](#5-性能调优)
6. [生产实践](#6-生产实践)
7. [与 Kafka 对比](#7-与-kafka-对比)

---

## 1. 核心概念

### 1.1 Exchange 类型详解

#### Direct Exchange

**路由规则**：routing key 精确匹配 binding key。

```
         ┌─────────────────┐
         │   Direct        │
         │   Exchange      │
         └────────┬────────┘
                  │
        routing_key="error"
                  │
          ┌───────┴───────┐
          ▼               ▼
    ┌──────────┐   ┌──────────┐
    │ Queue A  │   │ Queue B  │
    │binding:  │   │binding:  │
    │"error"   │   │"warn"    │
    │"info"    │   │"error"   │
    └──────────┘   └──────────┘
```

**实战场景**：日志分级路由——error 日志进告警队列，info 日志进归档队列。

**面试题**：Direct Exchange 的 routing key 和 binding key 是否支持通配符？  
答：不支持。通配符是 Topic Exchange 的特性。Direct 要求精确匹配。

---

#### Topic Exchange

**路由规则**：routing key 按 `.` 分割，支持通配符 `*`（匹配一个单词）和 `#`（匹配零或多个单词）。

```
         ┌─────────────────┐
         │   Topic         │
         │   Exchange      │
         └────────┬────────┘
                  │
       "cn.beijing.weather"
                  │
          ┌───────┴───────┐
          ▼               ▼
    ┌──────────┐   ┌──────────┐
    │ Queue A  │   │ Queue B  │
    │binding:  │   │binding:  │
    │"cn.*.weather"│ │"#.weather"│
    └──────────┘   └──────────┘
```

**实战场景**：地理位置路由、日志分类、事件总线。

**高频面试题**：

- Q: `#` 和 `*` 的区别是什么？  
  A: `*` 匹配恰好一个单词，`#` 匹配零个或多个单词（如 `cn.#` 可匹配 `cn`、`cn.beijing`、`cn.beijing.chaoyang`）。

- Q: Topic Exchange 的 routing key 最大长度是多少？  
  A: 255 bytes（AMQP 0-9-1 规范），建议不要超过 100 字符。

---

#### Fanout Exchange

**路由规则**：将消息广播到所有绑定的队列，忽略 routing key。

```
         ┌─────────────────┐
         │   Fanout        │
         │   Exchange      │
         └────────┬────────┘
                  │
                  │ 消息副本
          ┌───────┼───────┐
          ▼       ▼       ▼
    ┌────────┐┌────────┐┌────────┐
    │Queue A ││Queue B ││Queue C │
    └────────┘└────────┘└────────┘
```

**实战场景**：广播通知、配置中心变更推送、分布式缓存刷新。

**面试题**：Fanout Exchange 的性能瓶颈在哪里？  
A: 瓶颈在 Exchange 到 Queue 的扇出过程。如果有数百个队列绑定到同一个 Fanout Exchange，每个消息都需要复制数百份，内存和网络开销大。解决方案：用数据流拓扑拆分或使用消费端自行拉取。

---

#### Headers Exchange

**路由规则**：根据消息的 headers 属性匹配 binding arguments，忽略 routing key。

```yaml
# Binding arguments
binding_arguments:
  x-match: all          # 所有 header 匹配（类似 AND）
  format: "pdf"
  year: 2024

# 或
binding_arguments:
  x-match: any          # 任一 header 匹配（类似 OR）
  format: "pdf"
```

**实战场景**：多条件路由（如根据消息的多个元数据字段决定目标队列）。

**面试题**：Headers Exchange 的生产使用率较低，原因是什么？  
A: (1) 性能较差，每次路由需匹配 headers 字典；(2) 配置复杂，binding arguments 维护成本高；(3) Topic Exchange 结合多个 Queue 可以覆盖绝大多数场景。

---

### 1.2 Channel vs Connection

```
┌─────────────────────────────────────────┐
│           TCP Connection                │
│  ┌──────┐ ┌──────┐ ┌──────┐ ┌──────┐  │
│  │Chn 1 │ │Chn 2 │ │Chn 3 │ │Chn N │  │
│  │      │ │      │ │      │ │      │  │
│  └──────┘ └──────┘ └──────┘ └──────┘  │
└─────────────────────────────────────────┘
```

| 维度 | Connection | Channel |
|------|-----------|---------|
| 层级 | TCP 连接 | 虚拟连接（多路复用） |
| 资源开销 | 高（TCP 握手、TLS） | 低（轻量级，进程内） |
| 数量建议 | 每个应用 1-2 个 | 每个 Connection 数十到数百 |
| 线程安全 | 否 | 否（需按 Channel 分配） |

**实战经验**：

- 每个线程使用独立的 Channel，不要跨线程共享一个 Channel（非线程安全）。
- 不要在单个 Connection 上创建数千个 Channel——AMQP 协议中 Channel 数量有最大值（默认 2047，可通过 `channel_max` 配置）。
- 遇到 `channel.error` 或 connection 断开时，需要重建整个 Connection+Channel 栈。

**高频面试题**：

Q: Channel 关闭后是否能复⽤？  
A: 不能。Channel 关闭后必须创建新 Channel。注意捕获 `ShutdownSignalException`。

Q: 为什么推荐使用 Connection 池而不是 Channel 池？  
A: 创建 Connection 开销高（TCP 三次握手+TLS），而 Channel 是轻量级的。通常做法：维护少量 Connection（1-2 个），每个 Connection 下按需创建 Channel，用完即关。

---

### 1.3 Virtual Host（vhost）

- 作用：租户隔离。不同业务线用不同 vhost，Exchange/Queue 名称空间隔离。
- 权限控制：vhost 级别配置用户权限（read/configure/write）。
- 默认 vhost：`/`，生产环境建议为每个业务线创建独立 vhost。

**面试题**：vhost 和 namespace 的概念区别？  
A: vhost 是 RabbitMQ 的隔离单元（Exchange/Queue/Binding 的逻辑分组），不同 vhost 间完全隔离。与 Kafka 的 topic 命名空间不同，vhost 在 AMQP 协议中属于协议层概念，Kafka 没有对应概念。

---

## 2. 消息可靠性

### 2.1 生产者确认（Publisher Confirm）

```
Producer ──publish──► RabbitMQ ──persist──► Disk
    │                                         │
    └─────────────── ack ────────────────────┘
```

**三种确认模式**：

| 模式 | 说明 | 性能影响 |
|------|------|---------|
| 普通 Confirm | 每发一条等一次 ack | 低 |
| 批量 Confirm | 累积 N 条或间隔时间批量确认 | 中 |
| 异步 Confirm | 回调监听 ack/nack，高并发推荐 | 高 |

**核心代码模式（Go amqp091）**：

```go
conn, _ := amqp.Dial("amqp://guest:guest@localhost:5672/")
ch, _ := conn.Channel()

// 开启 Publisher Confirm 模式
ch.Confirm(false)
confirms := ch.NotifyPublish(make(chan amqp.Confirmation, 1))

ch.Publish("order.exchange", "order.created", false, false, amqp.Publishing{
    ContentType:  "application/json",
    DeliveryMode: amqp.Persistent,
    Body:         body,
})

// 异步监听 ack/nack
go func() {
    for confirm := range confirms {
        if confirm.Ack {
            // 确认成功，移除本地缓存
        } else {
            // nack：记录日志 + 重试
        }
    }
}()
```

**实战踩坑**：

1. **QPS 高时不要单条同步 Confirm**：每条消息等 ack 会将 QPS 限制在几百，必须使用异步 Confirm + 批量策略。
2. **ReturnCallback 处理**：消息已到 Exchange 但路由不到 Queue（mandatory=true 时必须处理）。
3. **Confirm 超时**：默认 30s，超时未确认需要走重试逻辑（可能网络抖动或 Broker 繁忙）。

**面试题**：

Q: Confirm 模式的 ack 是在消息写入磁盘前还是后？  
A: 取决于 `persistent` 配置和 `queue.declare` 的持久化设置。默认持久化消息在写入磁盘后才 ack（同步刷盘），性能版可通过 `spring.rabbitmq.publisher-confirm-type=simple` + 异步批量来平衡。

Q: 如果 Confirm ack 丢失怎么办？  
A: 生产者侧维护一个未确认消息的本地缓存（Map + 定时扫描），超时未确认则重发。配合幂等消费端实现"至少一次"语义。完整实现链路如下。

#### 可靠生产者完整实现（At-Least-Once）

**整体链路：**

```
生产者                    RabbitMQ Broker              消费者
  │                              │                        │
  ├─ Publish(msg, corrID) ──────►│                        │
  ├─ pending[corrID] = {msg,now} │                        │
  │                              ├─ 落盘/路由 ───────────►│
  │  ◄── ack(corrID) ────────────┤                        ├─ 幂等检查
  ├─ delete pending[corrID]      │                        ├─ 业务处理
  │                              │                        └─ ack
  │  ◄── nack(corrID) ───────────┤ （broker 拒绝）
  ├─ 立即重发
  │
  │ [定时扫描 goroutine：每 5s]
  ├─ age > 30s → 重发
  └─ retryCount > 3 → 告警/写死信
```

**数据结构：**

```go
// 待确认消息条目
type pendingMsg struct {
    exchange   string
    routingKey string
    body       []byte
    publishAt  time.Time // 发布时间，用于超时判断
    retryCount int
}

// 可靠生产者
type ReliableProducer struct {
    ch          *amqp.Channel
    confirms    <-chan amqp.Confirmation
    pending     sync.Map // corrID(string) → *pendingMsg
    tagToCorrID sync.Map // deliveryTag(uint64) → corrID(string)
    seq         uint64   // 镜像 channel 的 deliveryTag 计数器
    mu          sync.Mutex
    timeout     time.Duration // 超时阈值，默认 30s
    maxRetry    int           // 最大重试次数
}
```

**初始化 + 发布：**

```go
func NewReliableProducer(ch *amqp.Channel) *ReliableProducer {
    ch.Confirm(false) // 开启 Confirm 模式
    p := &ReliableProducer{
        ch:       ch,
        confirms: ch.NotifyPublish(make(chan amqp.Confirmation, 256)),
        timeout:  30 * time.Second,
        maxRetry: 3,
    }
    go p.listenConfirms() // 监听 broker 的 ack/nack（实时路径）
    go p.scanExpired()    // 定时扫描超时消息（兜底路径）
    return p
}

func (p *ReliableProducer) Publish(exchange, routingKey string, body []byte) {
    corrID := uuid.New().String()

    // 记录 deliveryTag → corrID 的映射（channel 内单调递增）
    p.mu.Lock()
    p.seq++
    tag := p.seq
    p.mu.Unlock()

    p.tagToCorrID.Store(tag, corrID)
    p.pending.Store(corrID, &pendingMsg{
        exchange: exchange, routingKey: routingKey,
        body: body, publishAt: time.Now(),
    })
    p.ch.Publish(exchange, routingKey, false, false, amqp.Publishing{
        DeliveryMode:  amqp.Persistent,
        CorrelationId: corrID, // 传给消费者，用于幂等去重
        Body:          body,
    })
}
```

> **为什么需要 `tagToCorrID`？**  
> `amqp.Confirmation` 只携带单调递增的 `DeliveryTag`，没有 `CorrelationId`。必须维护一张 `deliveryTag → corrID` 的映射才能反查到原始消息。

**确认监听（实时路径）：**

```go
func (p *ReliableProducer) listenConfirms() {
    for confirm := range p.confirms {
        raw, ok := p.tagToCorrID.LoadAndDelete(confirm.DeliveryTag)
        if !ok {
            continue
        }
        corrID := raw.(string)
        if confirm.Ack {
            p.pending.Delete(corrID) // ✅ 正常确认，清除缓存
        } else {
            p.retryByCorrID(corrID) // ❌ nack，立即重发
        }
    }
}
```

**定时扫描（兜底路径）：**

```go
func (p *ReliableProducer) scanExpired() {
    ticker := time.NewTicker(5 * time.Second)
    defer ticker.Stop()
    for range ticker.C {
        p.pending.Range(func(k, v any) bool {
            corrID, msg := k.(string), v.(*pendingMsg)
            if time.Since(msg.publishAt) < p.timeout {
                return true // 未超时，继续遍历
            }
            if msg.retryCount >= p.maxRetry {
                // 超过最大重试：告警 + 落库死信，人工介入
                log.Printf("[WARN] msg %s dropped after %d retries", corrID, msg.retryCount)
                p.pending.Delete(corrID)
                return true
            }
            p.retryByCorrID(corrID)
            return true
        })
    }
}

func (p *ReliableProducer) retryByCorrID(corrID string) {
    raw, ok := p.pending.Load(corrID)
    if !ok {
        return
    }
    msg := raw.(*pendingMsg)
    msg.retryCount++
    p.pending.Delete(corrID)          // 删除旧条目
    p.Publish(msg.exchange, msg.routingKey, msg.body) // 重发（生成新 corrID）
}
```

**消费者幂等闭环：**

```go
// CorrelationId 写入去重表，唯一索引冲突 = 重复消息
func handleMessage(msg amqp.Delivery, db *sql.DB) {
    result, err := db.Exec(
        "INSERT IGNORE INTO msg_dedup(corr_id, created_at) VALUES(?, NOW())",
        msg.CorrelationId,
    )
    if err != nil || mustInt(result.RowsAffected()) == 0 {
        msg.Ack(false) // 重复消息，ack 丢弃
        return
    }
    if err := processBusiness(msg.Body); err != nil {
        msg.Nack(false, true) // 业务失败，requeue 重试
        return
    }
    msg.Ack(false)
}
```

**各环节职责说明：**

| 组件 | 职责 |
|------|------|
| `listenConfirms()` | 处理 broker 实时 ack/nack，正常路径，延迟最低 |
| `scanExpired()` | 兜底路径，处理 ack 丢失/网络抖动/broker 重启等异常场景 |
| `retryByCorrID()` | 统一重发逻辑，两条路径共用，避免重复代码 |
| `msg_dedup` 表 | 消费端幂等，用 DB 唯一索引承接重复投递，去重+业务在同一事务内 |

> **At-Least-Once 语义的完整保证**：  
> 生产侧 — 未确认消息一定重发（实时 nack + 超时扫描双保险）；  
> 消费侧 — 重复消息通过幂等去重，业务只执行一次。

---

### 2.2 消费者确认（Consumer ACK）

**三种确认模式**：

```
┌─────────────────────────────────────────┐
│  auto   │  自动 ack（可能丢消息）        │
│─────────┼───────────────────────────────│
│  manual │  手动 ack（推荐）              │
│─────────┼───────────────────────────────│
│  none   │  无确认（Channel 关闭时重发）  │
└─────────────────────────────────────────┘
```

```yaml
spring.rabbitmq.listener.simple.acknowledge-mode=manual
```

```go
msgs, _ := ch.Consume("order.queue", "", false, false, false, false, nil)
for msg := range msgs {
    if err := process(msg.Body); err == nil {
        msg.Ack(false)                    // 单条确认
    } else if isBusinessErr(err) {
        msg.Nack(false, false)            // 永久故障 requeue=false，进死信
    } else {
        msg.Nack(false, true)             // 临时故障 requeue=true，放回队列
    }
}
```

**高频面试题**：

Q: 手动 ACK 时忘记 ack 会怎样？  
A: 消息变成"Unacked"状态，消费者不再收到新消息（受 prefetch 限制），连接断开后消息重新入队。注意监控 Unacked 指标。

Q: `basicNack` 的 `requeue` 参数如何选？  
A:  
- 临时故障（DB 连接超时等）：`requeue=true`，配合重试间隔  
- 永久故障（消息格式错误）：`requeue=false`，进死信队列（防止循环消费打空 DB）  
- 未捕获异常：默认 `requeue=true`，需通过 `default-requeue-rejected` 配置

Q: 如何防止消费者处理异常时不断 requeue 导致死循环？  
A: (1) 带重试间隔的 Spring Retry 机制；(2) 重试达上限后自动进入 DLQ；(3) 消费者侧做幂等去重。

---

### 2.3 消息持久化

**三层次持久化**：

```
Exchange 持久化  +  Queue 持久化  +  消息持久化(PERSISTENT)
                                │
                          ┌─────┴─────┐
                          ▼           ▼
                      Transient    Persistent
                      (重启丢失)     (重启恢复)
```

| 维度 | 声明方式 | 说明 |
|------|---------|------|
| Exchange | `durable=true` | Exchange 元数据持久化 |
| Queue | `durable=true` | Queue 元数据持久化 |
| Message | `deliveryMode=2` | 消息体持久化（PERSISTENT_TEXT_PLAIN） |

**实战注意**：即使三条都设置，RabbitMQ 在 message 写入磁盘前崩溃仍可能丢数据。如需极致可靠，组合使用 Publisher Confirm + Quorum Queue。

**面试题**：

Q: 持久化消息的性能开销有多大？  
A: RabbitMQ 的持久化机制是 append-only 文件写入，顺序 I/O 下性能尚可。对比非持久化，单机 QPS 从数十万降至数万（视磁盘性能），但仍是 AMQP 阵营最快的之一。如果对可靠性要求不高（如日志聚合），使用 transient 消息获得吞吐量。

Q: RabbitMQ 的消息文件什么时候清理？  
A: 消息被所有消费者确认后标记为可回收，但不会立即删除。通过垃圾回收（GC）机制在磁盘使用率高时执行。可通过 `rabbitmqctl set_policy` 控制。

---

### 2.4 镜像队列（Mirror Queue）— 经典版

> 注意：RabbitMQ 3.8+ 推荐使用 Quorum Queue 替代 Mirror Queue。

```
┌──────────────┐    ┌──────────────┐    ┌──────────────┐
│  Node 1      │    │  Node 2      │    │  Node 3      │
│  ┌────────┐  │    │  ┌────────┐  │    │  ┌────────┐  │
│  │Master  │──┼────┼─►│Mirror  │──┼────┼─►│Mirror  │  │
│  │Queue A │  │    │  │Queue A │  │    │  │Queue A │  │
│  └────────┘  │    │  └────────┘  │    │  └────────┘  │
└──────────────┘    └──────────────┘    └──────────────┘
       ▲                                        │
       │                                        │
       │         ha-mode: all                    │
       │    ha-sync-mode: automatic              │
       └────────────────────────────────────────┘
```

**策略配置**：

```bash
# 全节点镜像
rabbitmqctl set_policy ha-all ".*" '{"ha-mode":"all","ha-sync-mode":"automatic"}'

# 指定节点数镜像
rabbitmqctl set_policy ha-two "order\..*" '{"ha-mode":"exactly","ha-params":2,"ha-sync-mode":"automatic"}'
```

**面试题**：

Q: Mirror Queue 的写性能瓶颈在哪？  
A: 所有镜像由 master 同步。master 需要将每条消息复制到所有 mirror 才算完成（confirm 返回）。节点越多，写放大越严重。推荐 `ha-mode=exactly` 限制副本数。

Q: Mirror Queue 和 Quorum Queue 的核心区别？  
A:  
- Mirror Queue 是 master-slave 模式（一主多从），Quorum Queue 是 Raft 共识（多主写多数）
- Mirror Queue 故障切换有脑裂风险，Quorum Queue 天然解决
- Quorum Queue 只支持非独占、非自动删除、持久化队列，且支持 exactly-once 交付

---

### 2.5 惰性队列（Lazy Queue）— 3.6+

```
┌────────────────────────────────────────────┐
│           经典队列（Default）                  │
│  Producer ──► Memory (RAM) ──► Disk (lazy) │
│  消息优先存内存，内存阈满后换入磁盘           │
├────────────────────────────────────────────┤
│           惰性队列（Lazy）                    │
│  Producer ──► Disk (always)                  │
│  消息直接写入磁盘，消费者读取时才加载到内存    │
└────────────────────────────────────────────┘
```

**场景**：
- 消费者处理慢，队列堆积严重
- 队列需要存储大量消息（百万级以上）
- 内存敏感型服务

**注意**：RabbitMQ 3.12+ 废弃了惰性队列概念，所有队列默认变更为 lazy 行为（消息优先写入磁盘）。

**面试题**：

Q: Lazy Queue 的读取性能如何？  
A: 读路径多了磁盘 I/O，延迟比内存队列高一个数量级。适合"积压场景"而非"高性能场景"。

---

## 3. 高级特性

### 3.1 死信队列（DLX — Dead Letter Exchange）

**死信来源**：

```
                ┌──────────────────┐
                │   Original Queue │
                │   order.queue    │
                └────────┬─────────┘
                         │
              ┌──────────┼──────────┐
              ▼          ▼          ▼
          TTL 过期    队列满    消费者 Nack
         (x-message-ttl)  (x-max-length) (requeue=false)
              │          │          │
              └──────────┼──────────┘
                         ▼
              ┌──────────────────────┐
              │  DLX Exchange        │
              │  order.dlx.exchange  │
              └──────────┬───────────┘
                         │
                         ▼
              ┌──────────────────────┐
              │  DLQ                 │
              │  order.dlq.queue     │
              └──────────────────────┘
```

**工作流程说明**：

1. **声明阶段**：在原始队列（`order.queue`）上配置两个关键参数：`x-dead-letter-exchange`（指定死信去哪个 Exchange）和 `x-dead-letter-routing-key`（死信的路由键）。DLX 本身是一个普通的 Exchange，DLQ 也是一个普通的 Queue，只是在业务上专门用于接收"失败消息"。

2. **消息变成死信的三种触发条件**：
   - **TTL 过期**：消息在队列中停留时间超过 `x-message-ttl` 设置的毫秒数；
   - **队列满**：队列中消息数量达到 `x-max-length` 上限，队头消息被挤出；
   - **消费者主动拒绝**：消费者调用 `Nack` 或 `Reject`，且 `requeue=false`。

3. **路由阶段**：消息变成死信后，RabbitMQ 自动将其投递到原队列配置的 DLX，并附上 `x-death` header（记录死亡原因、原队列名、死亡时间、死亡次数）。DLX 按照 `x-dead-letter-routing-key` 将消息路由到 DLQ。

4. **处理阶段**：DLQ 的消费者负责集中处理失败消息——可以人工审查、记录日志、发告警，或按业务逻辑决定是否重新投递回原队列（注意避免死循环）。

**配置示例**：

```go
// 声明带死信参数的队列
ch.QueueDeclare("order.queue", true, false, false, false, amqp.Table{
    "x-dead-letter-exchange":    "order.dlx.exchange",
    "x-dead-letter-routing-key": "order.dead",
    "x-message-ttl":             int32(60000),
    "x-max-length":              int32(10000),
})
// 声明死信队列
ch.QueueDeclare("order.dlq.queue", true, false, false, false, nil)
```

**实战经验**：

1. **死信循环陷阱**：DLQ 里的消息如果又被设置 DLX，且路由回原队列，会形成死循环。务必监控 DLQ 堆积。
2. **死信原因追踪**：RabbitMQ 3.7+ 支持在死信消息 header 中添加 `x-death` 数组，记录死亡原因（time/reason/queue/exchange/routing-keys/count）。
3. **死信监控**：对 DLQ 设置告警，任何 DLQ 有消息就发出告警。

**高频面试题**：

Q: 死信消息的 header 中 `x-death` 结构是怎样的？  
A: 包含 `reason`（rejected/expired/maxlen）、`queue`（原队列名）、`time`（死亡时间）、`count`（死亡次数）。注意 count 只在 RabbitMQ 3.7+ 可靠。

Q: 如何避免死信消息重复消费？  
A: 死信消息重新投递到原始队列时，会保留原有 header 和 delivery count。可以在消费端检查 `x-death` 数组控制重试次数阈值。

---

### 3.2 延迟队列

#### 方案一：TTL + DLX（原生方案）

```
消息设置 TTL ──到期──► 死信 Exchange ──► 延迟队列
   order.queue.wait          order.dlx         order.queue.process
```

**缺点**：不精确（队列首条 TTL 到期才判断后续消息、死信时间精度为秒级）、不灵活（每档延迟需独立队列）。

```go
// 声明多档延迟等级队列（TTL + DLX 方案）
for _, ttl := range []struct{ name string; ms int32 }{
    {"delay.5s", 5000}, {"delay.30s", 30000},
} {
    ch.QueueDeclare(ttl.name, true, false, false, false, amqp.Table{
        "x-message-ttl":          ttl.ms,
        "x-dead-letter-exchange": "process.exchange",
    })
}
```

#### 方案二：rabbitmq_delayed_message_exchange（官方插件）

```
Producer ──► Delayed Exchange ──hold──► Timer ──► Consumer Queue
             (插件实现)        (x-delay 到期)
```

```go
// 消息头设置延迟（rabbitmq_delayed_message_exchange 插件）
ch.Publish("delayed.exchange", "routing.key", false, false, amqp.Publishing{
    ContentType:  "application/json",
    DeliveryMode: amqp.Persistent,
    Headers:      amqp.Table{"x-delay": int32(5000)}, // 延迟 5000ms
    Body:         payload,
})
```

**优势**：单 Exchange 支持任意延迟时间（1ms 以上），精确度高。  
**劣势**：插件维护成本，性能稍差于原生 TTL+DLX（基于内存存储延迟消息）。

**面试题**：

Q: 延迟队列在分布式系统中的时间同步问题？  
A: RabbitMQ 延迟是基于 Broker 本地时间。若集群各节点时钟偏差大，延迟精度受影响。生产方案：使用 NTP 同步集群时钟 + 设延迟容忍窗口（如 200ms 以内）。

Q: 延迟消息在 Broker 重启后还能恢复吗？  
A: 使用 `rabbitmq_delayed_message_exchange` 插件时，延迟消息保存在 Mnesia 数据库中，重启后恢复延迟计时。TTL+DLX 方案依赖原队列 TTL，重启后时间重新计算，可能导致消息比预期延迟。

Q: 订单支付超时取消场景怎么设计？  
A: 推荐双层延迟方案：

```
用户下单 ──► TTL=30min ──► DLX ──► 状态查询队列
                               │
                          ┌────┴────┐
                          ▼         ▼
                       已支付    未支付
                       （消费丢弃） （取消订单）
```

TTL 消息一旦入队无法撤回，30 分钟后必然到达消费者。若用户提前支付，需在消费者侧判断"该订单是否已支付"，有两种方案。

#### 方案一：发送取消信号到状态查询队列

**思路**：支付成功后，主动往状态查询队列投一条 `PAID` 信号消息，消费者处理两种消息类型，用 Redis 做状态协调。

```
用户下单 ──► order.wait（TTL=30min）──► DLX ──► order.check.queue ──► 消费者
                                                        ▲
用户支付 ──► payment service ──────────────────────────┘
                              （发一条 type=PAID 的信号消息）
```

```go
type CheckMsg struct {
    OrderID string `json:"order_id"`
    Type    string `json:"type"` // "TIMEOUT" 或 "PAID"
}

func handleCheckQueue(msg amqp.Delivery) {
    var m CheckMsg
    json.Unmarshal(msg.Body, &m)

    switch m.Type {
    case "PAID":
        // 支付信号：写 Redis 标记，供后续 TIMEOUT 消息查询
        rdb.Set(ctx, "order:paid:"+m.OrderID, "1", 2*time.Hour)
        msg.Ack(false)
    case "TIMEOUT":
        val, _ := rdb.Get(ctx, "order:paid:"+m.OrderID).Result()
        if val == "1" {
            msg.Ack(false)
            return
        }
        // Redis 无标记，降级查 DB（防止 PAID 信号延迟或 Redis 故障）
        if db.QueryOrder(m.OrderID).Status == "PAID" {
            msg.Ack(false)
            return
        }
        cancelOrder(m.OrderID)
        msg.Ack(false)
    }
}
```

**风险点**：极端场景下 `PAID` 信号可能晚于 `TIMEOUT` 到达（MQ 延迟），因此 `TIMEOUT` 分支必须降级查 DB 兜底。

#### 方案二：Redis 原子标记（推荐）

**思路**：支付成功时直接写 Redis 标记，消费者处理 TIMEOUT 消息时查 Redis 即可，无需额外 MQ 消息。

```
用户下单 ──► order.wait（TTL=30min）──► DLX ──► order.check.queue ──► 消费者
                                                                        │查
用户支付 ──► payment service ──► Redis SET order:paid:{orderId}  ◄──────┘
```

```go
// 支付成功回调
func onPaymentSuccess(orderID string) {
    rdb.Set(ctx, "order:paid:"+orderID, "1", 2*time.Hour) // TTL 略大于订单 30min
    updateOrderStatus(orderID, "PAID")
}

// 消费者只处理 TIMEOUT 消息
func handleTimeout(msg amqp.Delivery) {
    orderID := extractOrderID(msg.Body)
    paid, _ := rdb.Exists(ctx, "order:paid:"+orderID).Result()
    if paid > 0 {
        msg.Ack(false)
        return
    }
    cancelOrder(orderID)
    msg.Ack(false)
}
```

#### 两种方案对比

| 维度 | 方案一（取消信号） | 方案二（Redis 标记） |
|------|-------------------|---------------------|
| 实现复杂度 | 高（两种消息类型） | 低（逻辑简单） |
| Redis 依赖 | 用于状态协调，可降级查 DB | 强依赖，需降级兜底 |
| 时序风险 | PAID 信号可能晚于 TIMEOUT | 几乎无（写标记在支付时同步完成） |
| 额外 MQ 流量 | 每笔支付多一条信号消息 | 无 |

**生产推荐方案二**，配合 `Redis + 降级查 DB` 双重兜底覆盖 Redis 故障场景。方案一适合希望通过 MQ 解耦、消费者不直接操作 Redis 的架构。

---

### 3.3 优先级队列

```go
// 声明优先级队列
ch.QueueDeclare("order.priority", true, false, false, false, amqp.Table{
    "x-max-priority": int32(10), // 0-255，推荐 ≤10
})
// 发送时设置优先级
ch.Publish("", "order.priority", false, false, amqp.Publishing{
    Priority: 5,
    Body:     body,
})
```

**使用限制**：
1. 优先级只在队列堆积时生效（消费者空闲时无意义）
2. 优先级越高，内部排序开销越大。推荐 max-priority 不超过 10
3. 优先级队列不支持镜像队列（mirror queue）— 3.8+ 的 Quorum Queue 支持优先级

**面试题**：

Q: 优先级队列和延迟队列能一起用吗？  
A: 可以，但需要注意优先级生效需要队列中有堆积。延迟消息到期投递时，如果消费速度快到不堆积，优先级设置不会产生效果。

---

### 3.4 RPC 模式

```
 ┌──────────┐                    ┌──────────┐
 │  Client  │                    │  Server  │
 │          │                    │          │
 │  request ┼─── rpc.queue ────►┼  consume │
 │          │                    │          │
 │  consume │◄── reply.queue ───┼  publish │
 └──────────┘                    └──────────┘
```

**核心机制**：

- 客户端设置 `replyTo` 为临时队列名
- 客户端设置 `correlationId` 唯一标识请求
- 服务端处理后在 `replyTo` 队列中发布响应，携带相同的 `correlationId`
- 客户端根据 `correlationId` 匹配响应（实现异步转同步）

**实战考量**：

- RPC 的同步等待会占用 Channel 和 Connection，推荐设置超时时间
- 每个请求创建独立临时队列开销大，改用 Direct reply-to（`amq.rabbitmq.reply-to`）特性
- 使用 RPC 前评估是否真需要——HTTP/gRPC 往往更适合同步调用

**面试题**：

Q: RabbitMQ RPC 适合什么场景？  
A: 适合处理耗时长、服务端需弹性伸缩的后端处理（如图片压缩、视频转码）。不适合低延迟的简单查询（HTTP 更优）。

---

## 4. 集群与高可用

### 4.1 集群模式

#### 普通集群（Classic Cluster）

```
          ┌──────────────┐
          │  Load Balancer│
          └──┬───────┬───┘
             │       │
        ┌────┴────┐ ┌┴────────┐
        │ Node 1  │ │ Node 2  │
        │         │ │         │
        │ Queue A │ │ Queue B │
        │ (Master)│ │ (Master)│
        │ Queue B◄─┼─┤(Mirror) │
        │ (Mirror)│ │ Queue A │
        └─────────┘ └─────────┘
```

**核心原理**：
- 每个节点保存自己的元数据（Exchange、Queue、Binding）
- Queue 的所有者节点（Master）存储完整数据，其他节点只存元数据和指针
- 跨节点访问需要内部 Erlang 通信

**主要问题**：
- 节点宕机后，该节点的 Queue 不可访问（直到重新加入）
- 普通集群不提供高可用（需要使用镜像队列或 Quorum Queue）

#### Quorum Queue（3.8+）

```
         ┌────────────────────────────┐
         │   Raft Consensus Group    │
         │   Node 1 (Leader)         │
         │   Node 2 (Follower)       │
         │   Node 3 (Follower)       │
         └────────────────────────────┘
```

**特性**：
- 基于 Raft 协议，多数节点写入即返回
- 比镜像队列更安全（无脑裂）
- 只支持持久化队列（排除独占/自动删除/临时场景）
- 性能略低于镜像队列（Raft 写入多个节点需要同步多数）

**配置**：

```bash
rabbitmqctl set_policy quorum "order\..*" '{"queue-type":"quorum","delivery-limit":5}'
```

**实战经验**：
- 建议集群节点数为奇数（3 或 5），偶数节点多数派完全无优势
- 3 节点集群容忍 1 节点故障，5 节点集群容忍 2 节点故障
- Quorum Queue 有 `delivery-limit` 概念（类似消费重试上限），防止消息无限重试

**面试题**：

Q: 为什么 Quorum Queue 要求奇数节点？  
A: Raft 需要多数（majority）达成共识。3 节点多数是 2，5 节点多数是 3。4 节点多数是 3，容忍 1 节点故障，与 3 节点相同，但多了一个节点的资源开销。

Q: RabbitMQ 3.8+ 的流式队列（Stream）和 Quorum Queue 的区别？  
A: Stream 是追加写入的日志结构，支持多次消费、时间回溯（类似 Kafka 的分区），适用于大数据量、日志场景；Quorum Queue 是传统 AMQP 队列模型，适用于消息点对点消费。

---

### 4.2 Federation / Shovel（跨集群）

```
  ┌─────────┐         ┌─────────┐
  │ DC-A    │         │ DC-B    │
  │         │─Federation─►      │
  │ Queue A │         │ Queue B │
  └─────────┘         └─────────┘
```

| 特性 | Federation | Shovel |
|------|-----------|--------|
| 粒度 | Exchange 或 Queue 级别 | 从一个点到另一个点 |
| 拓扑 | 星形（一上游多下游） | 任意（链式、树形、星形） |
| 延迟 | 实时转发 | 可配置轮询间隔 |
| 过滤 | 支持 binding 级别过滤 | 转发全部消息 |
| 可靠 | 异步 AMQP | 事务式转发 |

**实战场景**：
- Federated Exchange：跨境多 Region 读分发（北京生产 → 上海/深圳/香港消费）
- Shovel：数据迁移，或两个没有直连网络的 RabbitMQ 集群间同步

**面试题**：

Q: Federation 会不会导致消息循环？  
A: Federation 在消息 header 中加入 `x-received-from` 防止循环。但应避免双向 Federation（A→B, B→A 死循环）。

---

### 4.3 负载均衡（HAProxy / Keepalived）

```haproxy
# haproxy.cfg 核心配置
frontend rabbitmq_front
    bind *:5672
    mode tcp
    option tcplog
    default_backend rabbitmq_back

backend rabbitmq_back
    mode tcp
    balance roundrobin
    option tcp-check
    server node1 192.168.1.1:5672 check inter 5000 rise 2 fall 3
    server node2 192.168.1.2:5672 check inter 5000 rise 2 fall 3
    server node3 192.168.1.3:5672 check inter 5000 rise 2 fall 3

# 管理 UI
frontend rabbitmq_mgmt
    bind *:15672
    mode http
    default_backend mgmt_back

backend mgmt_back
    mode http
    server node1 192.168.1.1:15672 check
```

**注意**：AMQP 0-9-1 是有状态的协议（Channel/Confirm 有状态），单纯的 TCP 负载均衡可能导致连接到节点的队列数据不在本节点。通常的解法：
1. **Pound** / **HAProxy** + 客户端自动重连
2. **客户端感知集群**（Spring AMQP 的 `CachingConnectionFactory` 配置多个地址）
3. **K8s Headless Service** + StatefulSet 部署

---

## 5. 性能调优

### 5.1 连接池

```yaml
# Spring Boot 配置
spring.rabbitmq:
  host: 192.168.1.1
  port: 5672
  cache:
    channel:
      size: 25         # 每个 Connection 缓存的 Channel 数
      checkout-timeout: 10000  # 获取 Channel 超时
    connection:
      mode: channel     # channel 级别缓存
```

**实战建议**：
- Connection 稳定很重要，不要频繁创建/销毁。每个微服务保持 1-2 个 Connection
- Channel 是主要复用对象，根据 QPS 调整缓存大小（压测找到最优值）
- Channel 缓存耗尽时，不要无限等待，设置 checkout-timeout

---

### 5.2 批量发送

```go
// 批量发送：在同一 Channel 内连续 Publish，最后等待所有 Confirm
ch.Confirm(false)
confirms := ch.NotifyPublish(make(chan amqp.Confirmation, len(batch)))

for _, msg := range batch {
    ch.Publish(exchange, routingKey, false, false, amqp.Publishing{
        DeliveryMode: amqp.Persistent,
        Body:         msg,
    })
}
// 等待全部 ack（超时 5s）
for i := 0; i < len(batch); i++ {
    select {
    case c := <-confirms:
        if !c.Ack { /* 处理 nack */ }
    case <-time.After(5 * time.Second):
        // 超时重发
    }
}
```

**注意**：批量发送会增加延迟，适合时序敏感度低的批处理场景。

---

### 5.3 Prefetch Count

```
Consumer 1  prefetch=100
Consumer 2  prefetch=100
Consumer 3  prefetch=100

┌──────────────────────────────────────┐
│          RabbitMQ Queue              │
│  [m1][m2][m3][m4][m5][m6]...[m300]  │
└──────────────────────────────────────┘
        │      │      │
        ▼      ▼      ▼
     C1(100) C2(100) C3(100)
```

**配置原则**：

| 场景 | Prefetch | 原因 |
|------|---------|------|
| 每个消息处理快 + 均匀 | 100-300 | 高吞吐 |
| 每个消息处理时间差异大 | 1-10 | 防止慢消息独占 |
| 顺序消费 | 1 | 确保单线程按序处理 |
| 自动 ACK | 0（不限制） | 无需控制 |
| 手动 ACK + 重试 | 1-50 | 防止重试风暴 |

**面试题**：

Q: Prefetch 设太大会有什么问题？  
A: (1) 消费者崩溃导致大量消息需重新入队；(2) Client 端内存飙升；(3) 若各消费者处理速度不均，会出现某些消费者忙碌、某些空闲。推荐压测后设定合理值。

---

### 5.4 内存 / 磁盘水位线

```bash
# 内存阈值（默认 0.4，即 40% 物理内存）
rabbitmqctl set_vm_memory_high_watermark 0.6

# 磁盘可用空间（默认 50MB）
rabbitmqctl set_disk_free_limit 2GB

# 相对内存的阈值
rabbitmqctl set_vm_memory_high_watermark_relative 0.6
```

**触发流控后的表现**：
- 生产者 publish 被阻塞（Connection.blocked）
- 所有 Connection 的状态变为 `blocked`
- 管理后台显示 Memory 或 Disk 告警

**实战建议**：
- 内存水位线不要超过 0.7（保留足够内存给 Erlang VM 和 OS）
- 磁盘水位线建议设为 1GB 以上（内存触发可能来不及，磁盘满了更严重）
- 配置 `vm_memory_high_watermark_paging_ratio` 让 RabbitMQ 在到达水位线之前就开始换页

---

### 5.5 Flow Control（流控）

```
              Credit-based Flow
Producer ──► Channel ──► Queue ──► Consumer
   │                                      │
   └── Credit (available) ◄──────────────┘
```

**流控机制**：
- **Credit-based**：Channel 级别，消费者处理能力通知生产者
- **Connection Blocked**：内存/磁盘到达水位线时触发，阻塞所有 Connection
- **内部流控**：Erlang VM 进程邮箱积压时自动节流

**面试题**：

Q: 如何排查 RabbitMQ 突然阻塞的问题？  
A: 检查顺序：
1. `rabbitmqctl status` 检查 memory 和 disk 使用
2. `rabbitmqctl list_connections` 查看 blocked 状态
3. `rabbitmqctl list_queues name messages_ready messages_unacknowledged` 查看堆积情况
4. 管理后台查看是否有 Queue 绑定了 message TTL 但消费慢导致内存积压

---

## 6. 生产实践

### 6.1 消息幂等

**为何需要幂等**：
- RabbitMQ 确保"至少一次"（at-least-once），不保证"恰好一次"
- 网络抖动导致生产者重发 + 重复 ack 失败 → 重复消息
- 消费者处理成功但 ack 网络丢失 → 消息重新投递

**常见幂等方案**：

```
┌────────────────────────────────────────────┐
│       幂等方案对比                          │
├────────────┬──────────────────────────────┤
│ 方案       │ 适用场景                      │
├────────────┼──────────────────────────────┤
│ 唯一键去重  │ 数据库插入 / 订单号           │
│ 业务去重表  │ MySQL 唯一索引 + 事务        │
│ 状态机判重  │ 订单状态流转（已支付不可再付） │
│ Redis 布隆  │ 高吞吐去重（允许小概率误判）  │
│ 版本号      │ 乐观锁更新（CAS）            │
└────────────┴──────────────────────────────┘
```

**核心做法**：

```go
// 方案：业务唯一 ID + 去重表（伪代码）
// 1. 消息体携带全局唯一 ID（如 orderId + eventType + timestamp）
// 2. 消费时 INSERT INTO msg_dedup(msg_id) ON CONFLICT DO NOTHING
// 3. 受影响行数为 0 则视为重复，跳过处理
// 4. 去重表与业务操作在同一事务中执行
func handleMessage(msgID string, body []byte) error {
    return db.Transaction(func(tx *gorm.DB) error {
        result := tx.Exec("INSERT INTO msg_dedup(msg_id) VALUES(?) ON DUPLICATE KEY UPDATE msg_id=msg_id", msgID)
        if result.RowsAffected == 0 {
            return nil // 重复消息，跳过
        }
        return processBusiness(tx, body)
    })
}
```

**面试题**：

Q: 如果去重表和业务操作不在一个事务中，会有什么问题？  
A: 可能出现"去重记录已写入，业务操作失败回滚"，下次消费时被去重拦截。解决方案：
- 将去重记录写入与业务操作放在同一事务中
- 或使用 TCC 模式预留去重资源
- 或接受"最多一次"语义，允许少量丢失

---

### 6.2 顺序消息

**问题背景**：  
RabbitMQ 的 Queue 内消息是有序的（FIFO），但多消费者、Confirm 重发、DLQ 重投都会破坏顺序。

**实现方案**：

```
┌──────────────────────────────────────────────────┐
│              顺序消息方案                          │
├──────────────────────────────────────────────────┤
│ 1. 单一 Queue + 单一 Consumer（顺序最强，吞吐最低） │
│ 2. 分片 Queue + 一致性 Hash 路由（折中）            │
│ 3. 同一个业务 key 路由到同一个 Queue                │
│ 4. 消费者端本地排序（缓冲区排序后再处理）             │
└──────────────────────────────────────────────────┘
```

**实战方案**（推荐）：

```go
// 声明一致性 Hash Exchange（需启用 rabbitmq_consistent_hash_exchange 插件）
ch.ExchangeDeclare("order.hash.exchange", "x-consistent-hash", true, false, false, false, nil)

// 发布时以 orderId 作为 routing key，插件按 hash 路由到对应 Queue
ch.Publish("order.hash.exchange", orderId, false, false, amqp.Publishing{Body: body})

// 单 Queue + 单 Consumer 保证顺序（并发=1）
msgs, _ := ch.Consume("order.sequence.queue", "", false, false, false, false, nil)
// 只启动一个消费 goroutine，天然有序
go func() {
    for msg := range msgs {
        handleOrder(msg.Body)
        msg.Ack(false)
    }
}()
```

**面试题**：

Q: 是否真的需要全局有序？  
A: 绝大多数业务只需要"局部有序"（同一订单、同一用户的消息有序）。全局有序会严重牺牲吞吐，通常不推荐。

Q: 什么情况下顺序消息的吞吐量最低点在哪里？  
A: 单队列消费是所有队列中最慢消费者的速度，且无法水平扩容。解决方案：预分片 + 分区数扩容（迁移数据）。

---

### 6.3 消息积压处理

**积压原因**：
1. 消费者异常（慢 SQL、死锁、OOM）
2. 下游服务限流（DB 连接池满、第三方 API 限流）
3. 流量洪峰（促销活动、秒杀）
4. 消费者故障（崩溃、重启、发布失败）

**应对策略**：

```
积压级别            措施                   恢复时间
────────  ──────────────────────────  ───────────
轻度(＜1万)  手动扩容消费者                 秒级
中度(1-10万) 临时关闭非核心消费者            分钟级
重度(10万+） 紧急扩容 + 消息迁移             十分钟级
灾难(百万+） 丢弃非重要消息 + 限流降级        小时级
```

**实操步骤**：

1. **排查根因**：
   ```bash
   rabbitmqctl list_queues name messages_ready consumers
   rabbitmqctl list_consumers  # 确认消费者是否在线
   ```

2. **紧急扩容**：
   - 水平：增加消费者实例（注意下游 DB 连接数上限）
   - 垂直：调整 `prefetch` 值加速消费

3. **消息迁移**（积压严重时）：
   - 创建新队列（`order.queue.fast`）
   - 临时绑定到同一个 Exchange
   - 新消费者消费新队列
   - 积压消费者继续消费旧队列直到清空

4. **兜底策略**：
   - 丢弃非核心消息（设置 TTL + DLX 直接丢弃）
   - 降级：返回降级响应，积压消息延时处理

**面试题**：

Q: 消息积压千万级怎么处理？  
A: 如果 MQ 无法承载千万级消息堆积：
1. 启用惰性队列（Lazy Queue）将消息落盘
2. 如果仍不够，将消息导出到文件 / 对象存储，消费侧删队列重建
3. 长期方案：评估是否该换 Kafka（百万级/秒吞吐，天然磁盘顺序读写，适合大堆积）

---

### 6.4 运维监控

#### 核心指标（Prometheus + Grafana）

```yaml
# rabbitmq-prometheus 插件（3.8+）
rabbitmq-plugins enable rabbitmq_prometheus

# 抓取配置 prometheus.yml
scrape_configs:
  - job_name: 'rabbitmq'
    static_configs:
      - targets: ['192.168.1.1:15692', '192.168.1.2:15692', '192.168.1.3:15692']
```

**关键指标面板**：

| 指标 | PromQL | 说明 |
|------|--------|------|
| 待消费数 | `rabbitmq_queue_messages_ready` | 积压预警 |
| 未确认数 | `rabbitmq_queue_messages_unacked` | 消费者处理力 |
| 消费速率 | `rate(rabbitmq_queue_messages_delivered_total[1m])` | 吞吐监控 |
| 生产速率 | `rate(rabbitmq_queue_messages_published_total[1m])` | 流量监控 |
| 连接数 | `rabbitmq_connections` | 异常连接泄露 |
| 通道数 | `rabbitmq_channels` | 通道泄漏 |
| 内存使用 | `rabbitmq_process_resident_memory_bytes` | 内存水位 |
| 磁盘可用 | `rabbitmq_disk_space_available_bytes` | 磁盘预警 |
| Unroutable | `rate(rabbitmq_channel_messages_unroutable_returned_total[1m])` | 路由失败 |

**告警规则**：

```yaml
groups:
  - name: rabbitmq_alerts
    rules:
      - alert: RabbitMQQueueBacklog
        expr: rabbitmq_queue_messages_ready > 10000
        for: 5m
        labels: { severity: warning }
      - alert: RabbitMQNoConsumer
        expr: rabbitmq_queue_consumers == 0
        for: 1m
        labels: { severity: critical }
      - alert: RabbitMQMemoryHigh
        expr: rabbitmq_process_resident_memory_bytes / rabbitmq_resident_memory_limit_bytes > 0.8
        for: 2m
        labels: { severity: critical }
      - alert: RabbitMQDiskLow
        expr: rabbitmq_disk_space_available_bytes < 1e9
        labels: { severity: critical }
```

---

### 6.5 常见故障排查

| 故障 | 原因 | 排查命令 | 解决方案 |
|------|------|---------|---------|
| 消费者连接失败 | 连接数超限 | `rabbitmqctl list_connections` | 调大 `connection_max` |
| 消息频繁 requeue | 消费者异常 | `rabbitmqctl list_channels name` 查看 unacked | 修复消费者代码 |
| 生产者 blocked | 内存达阈值 | `rabbitmqctl status` 看 memory | 调大水位 / 扩容节点 |
| 管理后台超时 | Erlang VM 卡顿 | `rabbitmqctl eval "process_info(...)"` | 检查 GC / 大消息 |
| 镜像同步慢 | 大队列 + 网络差 | `rabbitmqctl list_queues name sync_status` | 分批同步 / 增加带宽 |
| 消息重复消费 | ack 超时 | 查看 `redelivered` 标记 | 加幂等逻辑 |

---

## 7. 与 Kafka 对比

### 7.1 场景选择指南

```
                 RabbitMQ 优势区                    Kafka 优势区
                ┌────────────────────────┐ ┌────────────────────────┐
                │                        │ │                        │
  低延迟          │  RPC/微服务调用          │ │                         │
  (ms级)         │  复杂路由               │ │                         │
                │  事务消息               │ │                         │
                │  点对点通信             │ │                         │
                │                        │ │                         │
  中延迟          │  异步任务队列            │ │  日志聚合               │
  (秒级)         │  延迟/定时任务          │ │  指标收集               │
                │  多消费者广播           │ │  用户行为追踪           │
                │                        │ │                         │
  高吞吐          │                        │ │  数仓 ETL               │
  (百万/s)       │                        │ │  流计算（Flink 源）      │
                │                        │ │  日志归档               │
                │                        │ │  CDC 事件流             │
                └────────────────────────┘ └────────────────────────┘
```

### 7.2 架构差异

| 维度 | RabbitMQ | Kafka |
|------|---------|-------|
| 协议 | AMQP 0-9-1（标准协议） | 自定义 TCP 协议 |
| 消息模型 | Exchange → Binding → Queue | Topic → Partition |
| 消费语义 | 队列消费（消息确认后删除） | 日志消费（按 offset 保留） |
| 消息存储 | 确认删除，内存+磁盘 | 追加日志，基于时间/大小保留 |
| 消费方式 | Push（Broker 推送） | Pull（Consumer 拉取） |
| 顺序性 | 单 Queue 内有序 | 单 Partition 内有序 |
| 重试机制 | 内建（requeue/DLX） | 自己实现（seek offset） |
| 延迟消息 | TTL+DLX 或插件 | 无原生支持（时间戳 + 轮询） |
| 路由灵活性 | 四种 Exchange + Binding | 仅按 key 路由到 partition |
| 消息回溯 | 不支持（消费即删） | 支持（offset 重置） |
| 吞吐量 | 万级/秒 | 百万级/秒 |
| 延迟 | 微秒级 | 毫秒级（受批量缓冲影响） |

### 7.3 消息可靠性对比

```
                        at-most-once
                     ┌── 最多一次
         发送不重试  │
                    │            at-least-once
                  ┌─┼─────────── 至少一次 (RabbitMQ 默认)
    发送重试 ─────┤ │
    消费去重      │ │            exactly-once
                  └─┼─────────── 恰好一次（Kafka 事务 + 幂等）
                       └── 事务 + 幂等
```

| 层面 | RabbitMQ | Kafka |
|------|---------|-------|
| 生产者确认 | Publisher Confirm | acks=all |
| 副本同步 | Mirror/Quorum（多数确认） | ISR 副本同步 |
| 消费者语义 | autoAck/manualAck | enable.auto.commit=false + 手动提交 |
| 幂等保证 | 需业务层实现 | 内建幂等生产者 + 事务 |

### 7.4 性能对比数据（参考）

```
场景：3节点集群，持久化消息，单条512字节
                        RabbitMQ        Kafka
              ┌──────────────────────────────────
    吞吐量(生产) │  80,000/s       1,200,000/s
    吞吐量(消费) │ 120,000/s       2,000,000/s
    P99 延迟    │    5ms             15ms
    堆积百万恢复 │   3 min             20 sec
    队列/主题数 │  10-1,000       1,000-100,000
```

> 注：以上数据基于社区基准测试，不同硬件/配置差异很大。生产环境务必以真实压测为准。

### 7.5 选型决策树

```
你的系统需要消息队列吗？
├── 需要复杂路由（Topic/Headers）？
│   ├── 是 → RabbitMQ
│   └── 否 → 继续
├── 需要延时/死信/优先级等高级特性？
│   ├── 是 → RabbitMQ
│   └── 否 → 继续
├── 吞吐要求 > 50万/秒？
│   ├── 是 → Kafka
│   └── 否 → 继续
├── 需要消息回溯/重放？
│   ├── 是 → Kafka
│   └── 否 → 继续
├── 主要用于异步解耦 + 任务队列？
│   ├── 是 → RabbitMQ
│   └── 否 → 继续
└── 流计算/日志聚合/大数据管道？
    └── 是 → Kafka
```

---

## 附录

### A. 高频面试题速览

| 编号 | 题目 | 考察点 | 难度 |
|------|------|--------|------|
| 1 | Direct vs Topic Exchange 区别？ | 路由原理 | ⭐ |
| 2 | 如何保证消息不丢失？ | 三端可靠性（生产/存储/消费） | ⭐⭐ |
| 3 | 消息重复消费如何解决？ | 幂等设计 | ⭐⭐ |
| 4 | 死信队列的几种触发方式？ | 死信机制 | ⭐⭐ |
| 5 | 如何实现延迟消息？优缺点？ | TTL+DLX vs 插件 | ⭐⭐⭐ |
| 6 | 顺序消息如何实现？ | 分区排序设计 | ⭐⭐⭐ |
| 7 | RabbitMQ 集群脑裂怎么处理？ | 集群容错 | ⭐⭐⭐ |
| 8 | 消息积压千万级怎么办？ | 故障处理 | ⭐⭐⭐⭐ |
| 9 | Confirm 的 ack/nack 机制？ | 生产者确认 | ⭐⭐ |
| 10 | Prefetch 参数调优依据？ | 消费端流控 | ⭐⭐⭐ |
| 11 | Quorum Queue 和 Mirror Queue 区别？ | Raft vs Master-Slave | ⭐⭐⭐⭐ |
| 12 | RabbitMQ vs Kafka 选型？ | 场景判断 | ⭐⭐⭐ |
| 13 | RabbitMQ 的流控机制有哪些？ | 系统调优 | ⭐⭐⭐⭐ |
| 14 | Channel 和 Connection 的区别？ | AMQP 协议理解 | ⭐ |
| 15 | 如何监控 RabbitMQ 集群？ | 运维能力 | ⭐⭐ |

### B. 参考资源

- [RabbitMQ 官方文档](https://www.rabbitmq.com/documentation.html)
- [Spring AMQP 官方指南](https://spring.io/projects/spring-amqp)
- [RabbitMQ Prometheus/Grafana 监控](https://www.rabbitmq.com/prometheus.html)
- [The RabbitMQ Simulator（延迟可视化）](https://www.cloudamqp.com/blog/rabbitmq-simulator.html)
- [Kafka vs RabbitMQ - 架构差异分析 (Confluent)](https://www.confluent.io/kafka-vs-rabbitmq/)

---

> 本文档持续更新中。如有修正或补充建议，欢迎提交 PR。
