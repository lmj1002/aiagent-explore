# RabbitMQ 原理深度解析：从 AMQP 协议到集群共识

> 目标受众：高级后端开发 / 架构师  
> 前置知识：熟悉消息队列基本概念，了解分布式系统基础  
> 本文深度：源码级 / 协议级，覆盖 RabbitMQ 3.8+ (包含 Quorum Queue 和 Stream)

---

## 目录

1. [AMQP 协议深度](#1-amqp-协议深度)
2. [消息生命周期全流程](#2-消息生命周期全流程)
3. [可靠性机制深度](#3-可靠性机制深度)
4. [流控(Flow Control)机制](#4-流控flow-control机制)
5. [集群架构深度](#5-集群架构深度)
6. [跨集群方案](#6-跨集群方案)
7. [性能调优](#7-性能调优)
8. [生产运维](#8-生产运维)

---

## 1. AMQP 协议深度

### 1.1 AMQP 0-9-1 模型全景图

AMQP (Advanced Message Queuing Protocol) 0-9-1 是一个**线级协议**(wire-level protocol)，定义了客户端与消息代理之间的通信格式。其核心模型包含以下组件：

```
                            ┌─────────────────────────────────────────────┐
                            │              RabbitMQ Broker                │
                            │                                             │
                            │  ┌──────────┐     ┌──────────────┐         │
                            │  │ Exchange  │────▶│   Binding     │         │
                            │  │  (路由表)  │     │  (绑定关系)    │         │
                            │  └────┬─────┘     └──────┬───────┘         │
                            │       │                  │                  │
  ┌──────────┐              │       │   ┌──────────────┘                  │
  │ Producer │───Publish────┼───────┘   │                                 │
  │          │   Message    │           ▼                                 │
  └──────────┘              │  ┌──────────────────┐     ┌────────────┐    │
                            │  │      Queue       │────▶│  Consumer  │    │
                            │  │  (消息存储队列)    │     │  (消费者)   │    │
                            │  └──────────────────┘     └────────────┘    │
                            │                                             │
  ┌────────────────┐        │                                             │
  │   Connection   │────────┼─── TCP 连接 (端口 5672)                       │
  │    (一个TCP)    │        │                                             │
  └───────┬────────┘        └─────────────────────────────────────────────┘
          │
  ┌───────┴────────┐
  │   Channel 1    │  ─── 每个 Channel 是独立的"会话"(Session)
  ├────────────────┤
  │   Channel 2    │  ─── 复用同一 TCP 连接
  ├────────────────┤
  │   Channel 3    │  ─── Channel N ...
  └────────────────┘
```

**组件职责：**

| 组件 | 角色 | 说明 |
|------|------|------|
| **Connection** | 传输层 | 一个 TCP 连接，负责底层字节传输 |
| **Channel** | 会话层 | 多路复用通道，每个 Channel 是独立的"会话"上下文 |
| **Exchange** | 路由器 | 接收消息并根据路由规则分发到 Queue |
| **Binding** | 绑定关系 | Exchange 与 Queue 之间的路由规则 |
| **Queue** | 存储 | 消息的存储和消费单元 |
| **Consumer** | 消费者 | 订阅 Queue 并处理消息的客户端 |

### 1.2 Channel 的本质：多路复用模型

**为什么需要 Channel？**

如果没有 Channel，每建立一个"会话"都需要创建一个 TCP 连接。TCP 连接的建立成本包括三次握手、TLS 协商(如果启用)、内核资源分配(fd、socket buffer)等。对于需要频繁创建/销毁会话的应用场景（如 Web 应用处理每个请求），代价过高。

```
┌───────────────────────────────────────────────────────────────────────┐
│                       无 Channel 模型 (每条会话一个 TCP)               │
│                                                                       │
│  App 1 ────TCP 1────┐                                                 │
│  App 2 ────TCP 2────┤                                                 │
│  App 3 ────TCP 3────┼─── 问题: 大量 TCP 连接消耗系统资源                │
│  App 4 ────TCP 4────┤        每个连接需要 3 次握手开销                  │
│  App 5 ────TCP 5────┘        fd 资源有限 (ulimit -n)                  │
└───────────────────────────────────────────────────────────────────────┘

┌───────────────────────────────────────────────────────────────────────┐
│                       有 Channel 模型 (多路复用)                       │
│                                                                       │
│  App 1 ────┐                                                          │
│  App 2 ────┤                                                          │
│  App 3 ────┼──── TCP 1 ──── 一个物理连接承载多个逻辑会话                │
│  App 4 ────┤                                                          │
│  App 5 ────┘     ┌───────┬───────┬───────┬───────┐                    │
│                  │ Chan1 │ Chan2 │ Chan3 │ Chan4 │                    │
│                  └───┬───┴───┬───┴───┬───┴───┬───┘                    │
│                      │       │       │       │                        │
│                   Ch1帧   Ch2帧   Ch3帧   Ch4帧  ← 帧级多路复用        │
└───────────────────────────────────────────────────────────────────────┘
```

**Channel 的开销对比：**

| 维度 | 单独 TCP 连接 | Channel 复用 |
|------|-------------|-------------|
| 建立成本 | 3 次握手 + 资源分配 | 轻量级帧交互 |
| 内存占用 | 每个连接约 10-100KB | 每个 Channel 约几 KB |
| FD 消耗 | 每个连接 1 个 fd | 共享 1 个 fd |
| 关闭成本 | 4 次挥手 | 发送 Close 帧 |
| 最大数量 | 由 OS 限制 (通常 1024/65535) | 通常数千个 |

**Channel 的命名规范：** Channel ID 是 1-65535 的整数，通常在客户端库中管理。每个 Channel 拥有独立的状态机：

```
Channel 状态机:

  ┌──────────┐      Open 帧      ┌──────────┐
  │  Closed   │─────────────────▶│  Opened  │
  │           │◄─────────────────│          │
  └──────────┘    Close 帧       └────┬─────┘
                                      │
                                ┌─────▼─────┐
                                │   Flow    │── 流控状态 (credit flow)
                                │  Control  │
                                └───────────┘
```

### 1.3 帧(Frame)结构解析

AMQP 是二进制协议，所有通信都以**帧(Frame)**为单位。帧由三个部分组成：

```
┌─────────────────────────────────────────────────────────────────────┐
│                        AMQP Frame 结构                               │
│                                                                     │
│  ┌──────────┬──────────┬──────────────┬──────────────┬──────────┐  │
│  │  Frame   │ Channel  │   Payload    │   Payload    │ Frame    │  │
│  │  Type    │   ID     │    Size      │   (body)     │  End     │  │
│  │ (1 byte) │ (2 bytes)│  (4 bytes)   │ (N bytes)    │ (1 byte) │  │
│  ├──────────┼──────────┼──────────────┼──────────────┼──────────┤  │
│  │   0x01   │   N/A    │   0x0000     │              │  0xCE    │  │
│  └──────────┴──────────┴──────────────┴──────────────┴──────────┘  │
│                                                                     │
│  Frame Type:                                                        │
│  0x01 = METHOD (方法帧)   ─── 核心控制帧                             │
│  0x02 = HEADER (内容头帧)  ─── 消息属性                              │
│  0x03 = BODY (内容体帧)    ─── 消息体                                │
│  0x08 = HEARTBEAT (心跳帧) ─── 心跳                                  │
│                                                                     │
│  Frame End: 0xCE (十进制 206) ─── Frame 结束标记                     │
└─────────────────────────────────────────────────────────────────────┘
```

**Method Frame (0x01) 详细结构：**

```
┌─────────────────────────────────────────────────────────────────────┐
│                    Method Frame Payload 结构                         │
│                                                                     │
│  ┌────────────────────────┬────────────────────────────────────┐    │
│  │   Method Header        │   Method Body                     │    │
│  │   (12 bytes)           │   (N bytes)                      │    │
│  ├────────────┬───────────┤                                    │    │
│  │ Class ID   │ Method ID │  参数 (取决于具体方法)               │    │
│  │ (2 bytes)  │ (2 bytes) │                                    │    │
│  ├────────────┼───────────┼────────────────────────────────────┤    │
│  │   0x003C   │  0x0028   │  exchange="test", routing_key="a"  │    │
│  │ (60=Basic) │(40=Publish)│  mandatory=true, ...             │    │
│  └────────────┴───────────┴────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────────┘
```

**关键方法帧的 Class ID / Method ID：**

| 方法 | Class ID | Method ID | 说明 |
|------|---------|-----------|------|
| Connection.Start | 10 (Connection) | 10 | 连接开始 |
| Connection.Tune | 10 | 30 | 参数协商(帧大小/心跳/Channel数) |
| Channel.Open | 20 (Channel) | 10 | 打开通道 |
| Exchange.Declare | 40 (Exchange) | 10 | 声明交换机 |
| Queue.Declare | 50 (Queue) | 10 | 声明队列 |
| Queue.Bind | 50 | 20 | 绑定队列到交换机 |
| Basic.Publish | 60 (Basic) | 40 | 发布消息 |
| Basic.Deliver | 60 | 60 | 投递消息到消费者 |
| Basic.Ack | 60 | 80 | 确认消息 |
| Confirm.Select | 85 (Confirm) | 10 | 启用发布确认 |

**消息发布的完整帧序列：**

```
Producer                              RabbitMQ
   │                                      │
   │  ┌──────────────────────────────┐    │
   │  │ Frame 1: Basic.Publish(Method)│    │
   │  │   Class=60, Method=40        │    │
   │  │   exchange="", routing_key="q"│    │
   │  └─────────────┬────────────────┘    │
   │                │                      │
   │  ┌─────────────▼────────────────┐    │
   │  │ Frame 2: Header (Content)    │    │
   │  │   body_size=128, properties  │    │
   │  │   content_type, delivery_mode│    │
   │  └─────────────┬────────────────┘    │
   │                │                      │
   │  ┌─────────────▼────────────────┐    │
   │  │ Frame 3: Body (Content)      │    │
   │  │   [message payload bytes]    │    │
   │  └─────────────┬────────────────┘    │
   │                │────────────────────►│
   │                │                      │
```

### 1.4 三张核心状态表

RabbitMQ 进程内部维护三张核心状态表，理解它们是理解整个消息路由的关键。

#### Exchange 路由表

```
┌──────────────────────────────────────────────────────────────┐
│                    Exchange 路由表                             │
│                                                              │
│  Exchange Name     Type   Bindings List                      │
│  ─────────────────────────────────────────                   │
│  "" (default)     direct ───▶ queue_a (routing_key="a")      │
│                              queue_b (routing_key="b")       │
│  "my_exchange"    topic  ───▶ queue_c (routing_key="a.#")    │
│                              queue_d (routing_key="b.*")     │
│  "fanout_ex"      fanout ───▶ queue_e                        │
│                              queue_f                         │
│  "headers_ex"     headers───▶ queue_g (args: x-match=all,    │
│                                          name=foo, age=30)   │
└──────────────────────────────────────────────────────────────┘
```

**内部结构 (Erlang Records 级别)：**

```erlang
%% rabbit_exchange:record
-record(exchange, {
    name :: rabbit_binding:name(),      %% 交换机名称
    type :: 'direct' | 'topic' | 'fanout' | 'headers',
    durable :: boolean(),                %% 持久化
    auto_delete :: boolean(),            %% 自动删除
    arguments :: rabbit_framing:amqp_property_table(),
    table :: any()                       %% 路由表 (ETS 表引用)
}).

%% 路由表实际存储在 ETS (Erlang Term Storage) 中
%% rabbit_binding:list_for_source/1 查询实现
```

#### Queue 绑定表

```
┌──────────────────────────────────────────────────────────────┐
│                    Queue 绑定表                                │
│                                                              │
│  Queue Name    Exchange       Routing Key / Args             │
│  ────────────────────────────────────────────────────         │
│  queue_a       ""             "a"                            │
│  queue_b       ""             "b"                            │
│  queue_c       my_exchange    "a.#"                          │
│  queue_d       my_exchange    "b.*"                          │
│  queue_e       fanout_ex      (none)                         │
│  queue_f       fanout_ex      (none)                         │
│  queue_g       headers_ex     x-match=all, name=foo, age=30  │
│                                                              │
│  存储位置: rabbit_queue 进程的 ETS 表                           │
│  查询方式: exchange 名称 + routing key 双索引                   │
└──────────────────────────────────────────────────────────────┘
```

#### Channel 消费者表

```
┌──────────────────────────────────────────────────────────────┐
│                    Channel 消费者表 (Consumer Manager)         │
│                                                              │
│  Channel ID    Consumer Tag    Queue    Ack Mode   Args      │
│  ─────────────────────────────────────────────────────        │
│  Channel-1     ctag-1          q1        auto      {}        │
│  Channel-1     ctag-2          q2        manual    {}        │
│  Channel-2     ctag-3          q1        manual    {}        │
│  Channel-3     ctag-4          q3        manual    {x-pri}   │
│                                                              │
│  关键字段说明:                                                │
│  - Consumer Tag: 全局唯一消费者标识 (由客户端或服务端生成)      │
│  - Ack Mode: auto=自动确认, manual=手动确认                   │
│  - Prefetch: Channel 级未确认消息上限                          │
│  - Args: 消费者参数 (优先级、x-cancel-on-ha-failover 等)      │
│                                                              │
│  存储: rabbit_channel 进程字典 (process dictionary)            │
│  查询: #consumer 列表, 按 queue 分组                          │
└──────────────────────────────────────────────────────────────┘
```

**消费者注册流程：**

```
Client                        rabbit_channel                    rabbit_amqqueue
  │                              │                                  │
  │  Basic.Consume               │                                  │
  │─────────────────────────────►│                                  │
  │                              │  检查 Queue 是否存在              │
  │                              │  生成 Consumer Tag               │
  │                              │  注册到消费者表                   │
  │                              │─────────────────────────────────►│
  │                              │                                  │
  │                              │  注册消费者到 Queue 进程          │
  │                              │◄─────────────────────────────────│
  │                              │                                  │
  │  Basic.Consume-Ok            │                                  │
  │◄─────────────────────────────│                                  │
  │  (consumer_tag="ctag-1")     │                                  │
  │                              │                                  │
```

### 高频面试题 (Section 1)

**Q: Channel 和 Connection 的区别是什么？为什么使用 Channel 而不是直接在 Connection 上操作？**

A: Connection 是 TCP 级的物理连接，建立成本高（三次握手、TLS 协商、内核资源分配）。Channel 是 Connection 内的轻量级逻辑"会话"，每个 Channel 有独立的状态机、消费者列表和未确认消息集合。使用 Channel 可以在一个 TCP 连接上承载数千个独立会话，显著降低连接数。

**Q: AMQP Frame 中 Frame End (0xCE) 的作用是什么？**

A: 0xCE 作为帧结束标记 (Frame End)，有两个作用：(1) 帧边界检测，帮助接收方识别帧的完整结束位置；(2) 协议完整性校验，如果中间的字节中出现 0xCE，需要做转义处理（类似 PPP 协议的 0x7E）。实际上这是早期 AMQP 设计对帧同步的增强，现代网络环境下极少出现字节损坏。

**Q: AMQP 为什么选择二进制协议而非文本协议（如 HTTP/STOMP）？**

A: (1) 帧解析效率高，不需要字符串解析；(2) 固定头部长度便于零拷贝；(3) 协议开销小，Method Header 固定 12 字节；(4) 二进制编码更紧凑，减少网络带宽消耗；(5) 便于位级别的标志位操作（如 mandatory、immediate 等标志位）。

---

## 2. 消息生命周期全流程

### 2.1 消息从 Producer 到 Consumer 的完整链路

```
时间线 ────────────────────────────────────────────────────────────────►

Producer           Exchange           Queue             Consumer
  │                   │                 │                  │
  │ ① Publish         │                 │                  │
  │──────────────────►│                 │                  │
  │                   │                 │                  │
  │             ② Bindings 匹配          │                  │
  │             路由决策                │                  │
  │                   │                 │                  │
  │            ┌──────┴──────┐         │                  │
  │            │ 匹配成功?    │         │                  │
  │            │ Direct: RK=?│         │                  │
  │            │ Topic: ?    │         │                  │
  │            │ Fanout: ALL │         │                  │
  │            │ Headers: ?  │         │                  │
  │            └──────┬──────┘         │                  │
  │                   │                 │                  │
  │             ③ 无匹配时:             │                  │
  │               mandatory=false ──── 丢弃 (沉默丢弃)     │
  │               mandatory=true  ──── Return message      │
  │                   │                 │                  │
  │                   │ ④ 路由到 Queue   │                  │
  │                   │────────────────►│                  │
  │                   │                 │                  │
  │                   │           ⑤ 消息入队               │
  │                   │           内存/磁盘存储             │
  │                   │                 │                  │
  │                   │           ⑥ Consumer 拉取/推送     │
  │                   │                 │────────────────►│
  │                   │                 │                  │
  │                   │                 │           ⑦ 投递  │
  │                   │                 │◄────────────────│
  │                   │                 │                  │
  │                   │           ⑧ ACK 确认              │
  │                   │                 │◄────────────────│
  │                   │                 │                  │
  │             ⑨ 消息删除              │                  │
  │                   │◄────────────────│                  │
  │                   │                 │                  │
  │ ⑩ Confirm 回调    │                 │                  │
  │◄──────────────────│                 │                  │
```

### 2.2 Exchange 四种类型的路由算法详解

#### Direct Exchange

```
  ┌────────────┐
  │ Producer   │  routing_key="error"
  │            │       │
  └────────────┘       │
                       │
                ┌──────▼──────┐
                │  Direct     │
                │  Exchange   │
                └───┬─────┬───┘
                    │     │
           RK="error"│     │RK="error"
                    │     │
              ┌─────▼┐ ┌──▼────┐
              │ Q1   │ │  Q2   │
              │(error)│ │(error)│
              └──────┘ │(info) │
                       └───────┘

  算法: routing_key == queue_binding_key (精确相等)
  复杂度: O(1) hash 查找
```

**源码级实现 (Erlang)：**

```erlang
%% rabbit_exchange_type_direct:route/2
route(#exchange{name = Name, table = Table},
      #delivery{routing_keys = RKs}) ->
    %% 对每个 routing key 做 ETS 查找
    lists:flatmap(fun(RK) ->
        case ets:lookup(Table, {Name, RK}) of
            [{_, Targets}] -> Targets;
            [] -> []
        end
    end, RKs).
```

#### Topic Exchange

```
  ┌────────────┐
  │ Producer   │  routing_key="a.b.c"
  │            │       │
  └────────────┘       │
                       │
                ┌──────▼──────┐
                │  Topic      │
                │  Exchange   │
                └───┬─────┬───┘
                    │     │
          绑定模式:  │     │
         "a.#" ─────┤     ├──── "b.*"
         (匹配一切  │     │    (匹配 b.xxx)
          a.开头)   │     │
              ┌─────▼┐ ┌──▼────┐
              │ Q1   │ │  Q2   │ ← 不匹配 ("a.b.c" ≠ "b.*")
              │ ✓    │ │  ✗    │
              └──────┘ └───────┘

  通配符规则:
    * (星号)  ─── 匹配一个 . 分隔的单词
    # (井号)  ─── 匹配零个或多个单词

  示例:
    routing_key="a.b.c"
    pattern "a.#"   → 匹配 (a.b.c)
    pattern "a.*"   → 不匹配 (a.* 只能匹配一个单词, 如 "a.b")
    pattern "a.*.c" → 匹配
    pattern "*.b.*" → 匹配
```

**Topic 匹配算法 (Erlang 源码)：**

```erlang
%% rabbit_exchange_type_topic:route/2
route(#exchange{name = Name, table = Table},
      #delivery{routing_keys = RKs}) ->
    [match_rk(RK, Table) || RK <- RKs].

match_rk(RK, Table) ->
    Parts = string:tokens(RK, "."),
    %% 遍历所有绑定模式进行匹配
    ets:foldl(fun({{_, Pattern}, Targets}, Acc) ->
        case topic_match(Pattern, Parts) of
            true -> Targets ++ Acc;
            false -> Acc
        end
    end, [], Table).

%% 递归匹配
topic_match([], []) -> true;
topic_match(['#'], _) -> true;        %% # 匹配剩余所有
topic_match([Word | Pt], [W | Ps]) ->
    (Word == "*" orelse Word == W) andalso topic_match(Pt, Ps);
topic_match(_, _) -> false.
```

#### Fanout Exchange

```
  ┌────────────┐
  │ Producer   │  routing_key 被忽略
  │            │       │
  └────────────┘       │
                       │
                ┌──────▼──────┐
                │  Fanout     │
                │  Exchange   │
                └──┬────┬────┬┘
                   │    │    │
                   │    │    │
              ┌────▼┐ ┌▼───┐ ┌▼───┐
              │ Q1  │ │ Q2 │ │ Q3 │
              └─────┘ └────┘ └────┘

  算法: 广播到所有绑定的 Queue
  复杂度: O(N), N = 绑定 Queue 数
```

#### Headers Exchange

```
  ┌────────────┐
  │ Producer   │  headers: {name:"foo", age:30, city:"bj"}
  │            │       │
  └────────────┘       │
                       │
                ┌──────▼──────┐
                │  Headers    │
                │  Exchange   │
                └──┬──────────┘
                   │
         ┌─────────┼─────────┐
         │         │         │
  x-match=all  x-match=any  x-match=all
  name=foo     name=foo     name=foo
  age=30       age=30       age=25
         │         │         │
    ┌───▼──┐  ┌───▼──┐  ┌───▼──┐
    │ Q1   │  │ Q2   │  │ Q3   │
    │ ✓    │  │ ✓    │  │ ✗    │
    └──────┘  └──────┘  └──────┘
    (全部匹配)  (任一匹配)  (age不匹配)

  x-match=all: 所有列出的 header 必须匹配 (AND)
  x-match=any: 任一列出的 header 匹配即可 (OR)
  匹配时忽略 x-match 自身
```

#### 路由决策树图

```
                    收到消息
                       │
                       ▼
            ┌──────────────────┐
            │   Exchange 类型   │
            └────────┬─────────┘
                     │
          ┌──────────┼──────────┐
          │          │          │
          ▼          ▼          ▼
       Direct      Topic     Fanout
          │          │          │
     ┌────┴────┐  ┌──┴───┐    ┌┴─────┐
     │RK精确匹配│  │通配符│    │广播到│
     │  ETS查  │  │匹配  │    │所有  │
     │  找     │  │递归  │    │绑定  │
     └────┬────┘  │扫描  │    │队列  │
          │       └──┬───┘    └──┬───┘
          │          │           │
          └──────────┼───────────┘
                     │
                     ▼
            ┌──────────────────┐
            │    匹配到队列?    │
            └────────┬─────────┘
                     │
           ┌─────────┴─────────┐
           │                   │
           ▼                   ▼
       ┌────────┐       ┌──────────┐
       │ 入队   │       │mandatory?│
       └────────┘       └────┬─────┘
                           /    \
                        Yes      No
                         │        │
                         ▼        ▼
                    ┌────────┐ ┌──────┐
                    │Return  │ │丢弃  │
                    │消息    │ │消息  │
                    └────────┘ └──────┘
```

### 2.3 Queue 内部存储结构

RabbitMQ 的 Queue 存储采用**消息索引 + 消息存储分离设计**，这是理解其性能和资源使用的关键。

```
┌──────────────────────────────────────────────────────────────┐
│                    Queue 内部存储结构                          │
│                                                              │
│  ┌──────────────────────────────────────────────────────┐    │
│  │  Queue Index (队列索引)                               │    │
│  │  ┌────────────────────────────────────────────────┐  │    │
│  │  │  Segments (分段存储)                            │  │    │
│  │  │  ┌──────┬──────┬──────┬──────┬──────┬──────┐  │  │    │
│  │  │  │ Seq#1│ Seq#2│ Seq#3│ ...  │ Seq#N│      │  │  │    │
│  │  │  ├──────┼──────┼──────┼──────┼──────┤      │  │  │    │
│  │  │  │ Position in Message Store / Memory           │  │  │    │
│  │  │  │ Message ID / Delivery Tag / Status           │  │  │    │
│  │  │  └──────────────────────────────────────────────┘  │  │    │
│  │  │  存储: 内存 + 磁盘 (index journal)                 │  │    │
│  │  └────────────────────────────────────────────────┘  │    │
│  └──────────────────────────────────────────────────────┘    │
│                                                              │
│  ┌──────────────────────────────────────────────────────┐    │
│  │  Message Store (消息存储)                             │    │
│  │                                                      │    │
│  │  ┌───────────────────┐  ┌───────────────────┐       │    │
│  │  │   Segment 1       │  │   Segment 2       │       │    │
│  │  │   msg_001 [bin]   │  │   msg_005 [bin]   │       │    │
│  │  │   msg_002 [bin]   │  │   msg_006 [bin]   │       │    │
│  │  │   msg_003 [bin]   │  │       ...         │       │    │
│  │  │   msg_004 [bin]   │  │                   │       │    │
│  │  └───────────────────┘  └───────────────────┘       │    │
│  │                                                      │    │
│  │  存储: 文件 (持久化消息) / 内存 (非持久化消息)         │    │
│  │  写入策略: 追加写 (append-only)                      │    │
│  │  清理策略: 引用计数归零后 GC                         │    │
│  └──────────────────────────────────────────────────────┘    │
│                                                              │
│  ┌──────────────────────────────────────────────────────┐    │
│  │  Alpha / Beta / Gamma / Delta 状态分级               │    │
│  │                                                      │    │
│  │  Alpha: 消息同时在内存和索引中                        │    │
│  │  Beta:  消息仅在内存 (尚未写入磁盘)                    │    │
│  │  Gamma: 消息已写磁盘, 但索引在内存                    │    │
│  │  Delta: 消息和索引都在磁盘 (流控时)                   │    │
│  └──────────────────────────────────────────────────────┘    │
└──────────────────────────────────────────────────────────────┘
```

**消息写入路径：**

```
消息到达
   │
   ▼
┌───────────────┐    ┌─────────────────┐
│  Queue Index  │───▶│ 写入 Index      │
│  (进程字典)    │    │  Journal        │
└───────────────┘    └────────┬────────┘
                              │
                     ┌────────▼────────┐
                     │  消息是否持久化?  │
                     └────────┬────────┘
                              │
                     ┌────────┴─────────┐
                     │                  │
                     ▼                  ▼
              ┌────────────┐   ┌──────────────┐
              │ 写入内存    │   │  Message     │
              │ (Alpha状态)  │   │  Store       │
              └────────────┘   │  (文件)       │
                               └──────────────┘
```

### 2.4 消息的生命周期状态机

```
                        Producer 发布
                             │
                             ▼
                    ┌─────────────────┐
                    │     Pending     │── 初始状态，尚未入队
                    │  (未分配SeqID)   │
                    └─────────────────┘
                             │
                       Queue 分配 Seq ID
                             │
                             ▼
                    ┌─────────────────┐
                    │      Ready      │── 消息在队列中，等待消费
                    │  (可被消费)      │
                    └─────────────────┘
                             │
                    Consumer 投递消息
                             │
                             ▼
                    ┌─────────────────┐
                    │     Unacked     │── 已投递，等待 ACK
                    │  (未确认)        │
                    └─────────────────┘
                        /          \
                  手动 ACK       自动 ACK/异常
                      │              │
                      ▼              ▼
              ┌────────────┐  ┌────────────┐
              │ Acked      │  │ Requeued   │
              │ (确认完成)  │  │ (重新入队)  │
              └─────┬──────┘  └─────┬──────┘
                    │               │
                    ▼               └──────▶ Ready
            ┌──────────────┐
            │   Deleted    │
            │  (从存储移除)  │
            └──────────────┘
                             │
              ┌──────────────┼──────────────┐
              │              │              │
              ▼              ▼              ▼
       ┌──────────┐  ┌──────────┐  ┌──────────────┐
       │ 按ACK    │  │ TTL过期  │  │ 队列满(拒绝)  │
       │ 正常删除  │  │ → DLX    │  │ → DLX        │
       └──────────┘  └──────────┘  └──────────────┘
```

**持久化标记 (Delivery Mode)：**

```
Delivery Mode:
  1 = non-persistent (仅内存)
  2 = persistent (磁盘 + 内存)

  对于 persistent 消息:
    Ready ───▶ 同步写入 Message Store ───▶ 可安全消费
    Unacked ──▶ 等待 ACK (消息仍在磁盘)
    Ack ──────▶ 标记为可删除 (引用计数减 1)
```

### 高频面试题 (Section 2)

**Q: RabbitMQ 的 Queue 为什么采用索引和存储分离设计？**

A: 分离设计的好处：(1) 索引可以完全驻留内存，实现 O(1) 的消息定位；(2) 消息体存储在 append-only 日志中，顺序 IO 性能远超随机 IO；(3) 当消息积压时，可以将索引分页到磁盘（Delta 状态），避免 OOM；(4) 消息删除通过引用计数实现，不触发实际 IO，只在后台 GC 时回收磁盘空间。

**Q: Topic Exchange 的 `#` 和 `*` 匹配效率如何？当绑定数量极大时有什么性能问题？**

A: 每次匹配需要遍历所有绑定模式（ETS 全表扫描），复杂度 O(N * K)，N=绑定数，K=routing key 段数。绑定数少时性能良好，但绑定数达到数万时性能显著下降。生产建议：Topic Exchange 的绑定数控制在数千以内，大量绑定考虑用多个 Direct Exchange + 自定义路由逻辑。

**Q: RabbitMQ 是如何处理消息的 exactly-once 语义的？**

A: 严格来说，RabbitMQ 不保证 exactly-once。在生产者侧，Publisher Confirm 保证 at-least-once（消息确认可能丢失导致重发）。在消费者侧，手动 ACK + 去重机制（幂等消费者）可以近似实现 exactly-once。RabbitMQ Stream (3.9+) 通过 offset tracking 提供了更强的 exactly-once 保证。

---

## 3. 可靠性机制深度

### 3.1 生产者确认 (Publisher Confirm)

Publisher Confirm 是 RabbitMQ 提供的一种轻量级确认机制，让生产者知道消息是否被服务端成功接收。

**独立确认模式：**

```
Producer                        RabbitMQ
   │                               │
   │  ① Channel.Confirm.Select     │
   │──────────────────────────────►│
   │                               │
   │  ② Confirm.Select-Ok          │
   │◄──────────────────────────────│
   │                               │
   │  ③ Basic.Publish (msg_A)      │
   │  delivery_tag=1               │
   │──────────────────────────────►│
   │                               │  ④ 路由、持久化
   │                               │
   │  ⑤ Basic.Ack (delivery_tag=1) │
   │◄──────────────────────────────│  (等待上一条确认)
   │                               │
   │  ⑥ Basic.Publish (msg_B)      │
   │  delivery_tag=2               │
   │──────────────────────────────►│
   │                               │
   │  ⑦ Basic.Ack (delivery_tag=2) │
   │◄──────────────────────────────│
   │                               │
   │  等待 ==== 每个消息都要等确认 ==== 延迟高 ⏳
   │                               │
```

**批量确认模式：**

```
Producer                        RabbitMQ
   │                               │
   │  ① Channel.Confirm.Select     │
   │──────────────────────────────►│
   │  ② Confirm.Select-Ok          │
   │◄──────────────────────────────│
   │                               │
   │  ③ Publish msg_1 (tag=1)      │
   │  ④ Publish msg_2 (tag=2)      │  ← 连续发布，不等待
   │  ⑤ Publish msg_3 (tag=3)      │
   │  ⑥ Publish msg_4 (tag=4)      │
   │  ⑦ Publish msg_5 (tag=5)      │
   │──────────────────────────────►│
   │                               │
   │  ⑧ Basic.Ack (tag=5, multi=1) │  ← 批量确认 tag ≤ 5 的所有消息
   │◄──────────────────────────────│
   │                               │
   │  ⑨ Publish msg_6...           │
   │                               │
   │  吞吐量 ✅ 更高 (减少了 ACK 帧)  │
   │  风险: 批量中某个消息失败       │
   │       需要重发整个批量           │
   │                               │
```

**两种模式对比：**

| 特性 | 独立确认 | 批量确认 |
|------|---------|---------|
| ACK 帧数 | N 个消息 = N 个 ACK | N 个消息 ≈ N/batch_size 个 ACK |
| 吞吐量 | 较低 (每消息等待) | 较高 (批量聚合) |
| 延迟 | 每消息确认后才知道结果 | 批量最后一个确认后才知 |
| 失败重发粒度 | 单个消息 | 整个批量 |
| 适用场景 | 低延迟敏感 | 高吞吐批量导入 |

**确认时序的两种可能性 (源码层面)：**

```erlang
%% rabbit_confirm:handle_channel_confirm/2
%% 消息确认可能在以下时机触发:
%%
%% 1. 消息路由到所有匹配队列后
%%    - 对于 direct/topic/fanout: 找到绑定队列即确认
%%    - 对于 mandatory=true: 确认不可路由消息时会返回 Basic.Return
%%
%% 2. 消息持久化到磁盘后 (仅 persistent 消息)
%%    - 队列进程收到消息后写入 message store
%%    - 等待 msg_store_write_complete 回调
%%    - 只有磁盘 fsync 完成后才会发送 ACK
```

### 3.2 Mandatory 标志 + ReturnListener

当消息设置 `mandatory=true` 但无法路由到任何队列时，服务端不会静默丢弃，而是通过 ReturnListener 机制通知生产者。

```
Producer                                    RabbitMQ
   │                                           │
   │  Basic.Publish (mandatory=true)            │
   │  routing_key="nonexistent"                  │
   │───────────────────────────────────────────►│
   │                                           │
   │  ┌─────────────────────────────────────┐  │
   │  │ Exchange 无法匹配任何 Queue         │  │
   │  │ return_to_sender(Ch, Msg, Reply)    │  │
   │  └──────────────────┬──────────────────┘  │
   │                      │                     │
   │  Basic.Return        │                     │
   │  reply_code=312      │                     │
   │  reply_text=         │                     │
   │  "NO_ROUTE"          │                     │
   │◄─────────────────────│─────────────────────│
   │                      │                     │
   │  ReturnListener       │                     │
   │  .handleReturn()     │                     │
   │  回调处理            │                     │
   │                      │                     │
```

**Return 回复码：**

| reply_code | reply_text | 含义 |
|-----------|------------|------|
| 312 | NO_ROUTE | 无可路由队列 (mandatory) |
| 313 | NO_CONSUMERS | 队列无消费者 (immediate, 已废弃) |

**源码路径：**

```erlang
%% rabbit_channel:do_flow/4
do_flow(Method, Msg, Channel, Confirm) ->
    %% ... 路由处理后 ...
    case Queues of
        [] ->
            %% 无匹配队列
            case is_mandatory(Method) of
                true  -> send_return(Channel, Msg, 312, "NO_ROUTE");
                false -> ok  %% 静默丢弃
            end;
        _ ->
            %% 有匹配队列，投递
            deliver_to_queues(Queues, Msg, Channel, Confirm)
    end.
```

### 3.3 消费者 ACK 机制

**autoAck vs manualAck：**

```
autoAck=true (自动确认):
  ┌──────────┐     Basic.Deliver     ┌──────────┐
  │  Queue   │─────────────────────►│ Consumer │
  │          │   (消息已投递)         │          │
  │          │                      │ 处理消息  │
  │          │   ← 没有 ACK 帧       │          │
  │          │                      │          │
  │  消息立即标记为已删除              │          │
  └──────────┘                      └──────────┘
  风险: 消费者崩溃 → 消息丢失

manualAck=false (手动确认):
  ┌──────────┐     Basic.Deliver     ┌──────────┐
  │  Queue   │─────────────────────►│ Consumer │
  │          │   (消息标记为 Unacked) │          │
  │          │                      │ 处理消息  │
  │          │                      │    ...    │
  │          │   Basic.Ack          │ 处理完成  │
  │          │◄─────────────────────│          │
  │          │                      │          │
  │  消息标记为可删除                  │          │
  └──────────┘                      └──────────┘
  优势: 崩溃后消息自动 requeue
```

**Multiple Ack 批量确认原理：**

```
┌──────────────────────────────────────────────────────┐
│                  Channel Unacked Set                  │
│                                                      │
│  delivery_tag:  1    2    3    4    5    6    7      │
│  status:       [ack] [unack] [unack] [unack] [ack] [unack] [unack]
│                                                      │
│  Basic.Ack(delivery_tag=6, multiple=true):            │
│    ──▶ 确认 delivery_tag ≤ 6 的所有未确认消息          │
│        即 tag 2,3,4,6 全部确认                         │
│                                                      │
│  Basic.Ack(delivery_tag=6, multiple=false):           │
│    ──▶ 仅确认 delivery_tag=6                          │
│        如果 tag=5 还未确认，则 tag=6 也不能确认         │
│        (RabbitMQ 要求顺序确认)                         │
│                                                      │
│  注意: delivery_tag 是 Channel 级别的单调递增序列      │
│        范围: 1-65535 (channel 级别)                   │
└──────────────────────────────────────────────────────┘
```

**ACK 确认的内部实现 (Erlang 源码)：**

```erlang
%% rabbit_channel:handle_method/3 - Basic.Ack 处理
handle_method(#'basic.ack'{delivery_tag = Tag,
                           multiple     = Multiple},
              Channel, _Sender) ->
    %% 检查 delivery_tag 合法性
    case Multiple of
        true  -> ack_multiple(Channel, Tag);
        false -> ack_single(Channel, Tag)
    end.

ack_single(Channel, Tag) ->
    %% 从 unacked 字典中取出消息
    case erlang:get({delivery_tag, Tag}) of
        undefined -> {error, unknown_tag};
        Msg ->
            erlang:erase({delivery_tag, Tag}),
            %% 通知 Queue 进程标记消息为可删除
            gen_server:cast(QueuePid, {ack, SeqId})
    end.
```

### 3.4 消息持久化的实际写入路径

当消息标记为 `delivery_mode=2` (persistent) 时，RabbitMQ 确保消息在写入磁盘后才返回确认。这是理解 RabbitMQ 可靠性的核心路径。

```
  Producer                    rabbit_channel               rabbit_amqqueue              msg_store
     │                           │                            │                          │
     │  Basic.Publish            │                            │                          │
     │  (persistent)             │                            │                          │
     │──────────────────────────►│                            │                          │
     │                           │  ① 路由到 Queue            │                          │
     │                           │───────────────────────────►│                          │
     │                           │                            │                          │
     │                           │               ┌────────────┴────────────┐             │
     │                           │               │ Queue Index 写入        │             │
     │                           │               │ 追加到 journal 文件      │             │
     │                           │               │ (journal 在内存批量刷盘)  │             │
     │                           │               └─────────────────────────┘             │
     │                           │                            │                          │
     │                           │               ┌────────────┴────────────┐             │
     │                           │               │ 消息投递给 Consumer?     │             │
     │                           │               │ 是 → 改为 Unacked 状态   │             │
     │                           │               │ 否 → 保持 Ready 状态     │             │
     │                           │               └─────────────────────────┘             │
     │                           │                            │                          │
     │                           │               ┌────────────┴────────────┐             │
     │                           │               │ ② 持久化消息体          │             │
     │                           │               │──────────────────────────────────────►│
     │                           │               │                            │          │
     │                           │               │                  ┌─────────┴─────────┐│
     │                           │               │                  │ 写入 Segment 文件  ││
     │                           │               │                  │ (追加写, 顺序 IO)  ││
     │                           │               │                  │ 写入后 fsync       ││
     │                           │               │                  └───────────────────┘│
     │                           │               │◄──────────────────────────────────────│
     │                           │               │    ③ msg_store_write_complete        │
     │                           │               │                            │          │
     │                           │               │  (此时消息在磁盘上安全)      │          │
     │                           │               │                            │          │
     │                           │◄──────────────│                            │          │
     │                           │    ④ queue_callback_complete               │          │
     │                           │                            │                          │
     │ ⑤ Basic.Ack (delivery_tag)│                            │                          │
     │◄──────────────────────────│                            │                          │
     │                           │                            │                          │
```

**关键细节：**

1. **Journal 写入：** Queue Index 的 journal 是顺序写，先写内存再批量刷盘。默认每 200ms 或积攒到一定数据量后刷盘。
2. **Message Store 写入：** 真正的消息体写入 Segment 文件。Segment 文件是只追加的，文件大小达到上限 (默认 16MB) 后创建新文件。
3. **fsync 时机：** 由 `rabbit_msg_store` 控制，默认每次写入后调用 `file:sync/1`。可以通过 `msg_store_file_size_limit` 和 `msg_store_credit_disc_bound` 调节。
4. **写入确认的返回：** 只有消息体成功写入 Segment 文件并 fsync 后，才会向 Producer 发送 Basic.Ack (如果启用了 Publisher Confirm)。

### 3.5 死信队列 (DLX / Dead Letter Exchange)

当消息满足特定条件时，RabbitMQ 会将其转发到指定的 Dead Letter Exchange (DLX)，而不是简单丢弃。

```
死信触发流程图:

  消息进入队列
       │
       ▼
  ┌─────────────┐
  │ 正常消费?    │─── 是 ──▶ 正常 Ack，流程结束
  └──────┬──────┘
         │ 否
         │
  ┌──────┴──────┐
  │ 触发条件判断  │
  └──────┬──────┘
         │
         ├──── TTL 过期 ──────▶ ┌──────────┐
         │          死信原因:expired  │          │
         ├──── 队列长度超限 ─────▶ │ Dead     │
         │          死信原因:maxlen   │ Letter   │
         ├──── 消息被 Nack ──────▶ │ Exchange │
         │          死信原因:rejected  │          │
         ├──── 消息被 Reject ────▶ └────┬─────┘
         │          死信原因:rejected    │
         └──── 优先级被挤出 ──▶         │
                          死信原因:max_priority
                                        │
                                        ▼
                                ┌────────────────┐
                                │  重新路由      │
                                │  绑定到 DLX    │
                                │  可被消费/再次过期│
                                └────────────────┘
```

**完整场景示例：**

```
  ┌──────────┐
  │ Producer │──── Publish ────▶ ┌──────────────────┐
  └──────────┘                   │  main_exchange   │
                                 │  (direct)        │
                                 └────────┬─────────┘
                                          │
                                    routing_key="task"
                                          │
                                          ▼
                                  ┌───────────────┐
                                  │  work_queue    │
                                  │  x-dead-letter-│
                                  │  exchange=dlx_ex│
                                  │  x-message-ttl=│
                                  │  60000         │
                                  └───────┬───────┘
                                          │
                          ┌───────────────┼───────────────┐
                          │               │               │
                          │          TTL 过期             │
                          │               │               │
                          │               ▼               │
                          │       ┌──────────────┐        │
                          │       │   dlx_ex      │        │
                          │       │  (fanout)     │        │
                          │       └──────┬───────┘        │
                          │              │                │
                          │              ▼                │
                          │       ┌──────────────┐        │
                          │       │  dead_queue   │        │
                          │       │  (死信消息)    │        │
                          └───────┴──────────────┘        │
                                                          │
                                死信消息附加属性:               │
                                x-death[0].reason = expired │
                                x-death[0].queue = work_queue
                                x-death[0].time = 1688213045
                                x-death[0].exchange = main_exchange
                                x-death[0].routing-keys = ["task"]
```

**源码实现 (TTL 过期判断)：**

```erlang
%% rabbit_amqqueue_process:handle_info/2 - TTL 检测
handle_info({check_ttl, QPid, _}, State) ->
    case State#state.ttl of
        infinity ->
            ok;
        TTL when is_integer(TTL) ->
            %% 扫描队列头部的消息 TTL
            check_head_ttl(State, os:system_time(millisecond))
    end.

check_head_ttl(State, Now) ->
    case rabbit_queue_index:out(State#state.qid, State#state.index_state) of
        {empty, _} -> ok;
        {value, Msg, NewIndexState} ->
            Age = Now - Msg#basic_message.timestamp,
            if Age >= State#state.ttl ->
                %% TTL 过期，发送到 DLX
                dead_letter(State, Msg, <<"expired">>);
               true ->
                %% 未过期，重新放入队列
                ok
            end
    end.
```

### 高频面试题 (Section 3)

**Q: Publisher Confirm 中独立确认和批量确认各自的最佳实践是什么？**

A: 独立确认适合对单个消息的可靠性要求极高且延迟敏感的场景（如交易系统）；批量确认适合高吞吐场景（如日志收集），通常每 100-1000 条消息或每 100ms 确认一次。生产实践中常用组合方案：批量确认 + 定时 flush，既保证吞吐又控制最大确认延迟。

**Q: 消费者 ACK 时出现 unknown delivery tag 是什么原因？**

A: (1) 同一个 Channel 收到了重复的 ACK（消息已被确认过一次）；(2) Channel 关闭后尝试 ACK（此时 channel 状态已清理）；(3) 多线程/多协程共享同一个 Channel 进行 ACK 操作导致竞争条件。最佳实践：每个 Channel 只被一个线程/协程使用，ACK 只在消费者回调线程中执行。

**Q: 消息持久化到磁盘后，RabbitMQ 故障恢复时消息一定不丢吗？**

A: 不完全是。正常关闭时数据安全；异常崩溃时：(1) Queue Index journal 可能丢失最后几毫秒的写入（默认 200ms 刷盘间隔），导致少量消息丢失（但消息体在 Message Store 中）；(2) 如果同时配置了 `durable=true` + `persistent=true` + `Publisher Confirm`，可以确保消息不丢。单点故障还需要镜像队列或 Quorum Queue 提供高可用。

---

## 4. 流控(Flow Control)机制

### 4.1 信贷(Credit)流控模型

RabbitMQ 的核心流控机制基于 Erlang 进程间的**信贷(Credit)**模型。每个消息的传递都需要预先获得"信贷"凭证，这是一种**反压**实现。

```
Credit 流控原理:

  ┌────────────────────┐                     ┌────────────────────┐
  │  rabbit_channel    │                     │  rabbit_amqqueue   │
  │  (Channel 进程)     │                     │  (Queue 进程)      │
  │                    │    Credit Grant      │                    │
  │  Initial Credit    │◄────────────────────│                    │
  │  = 200 (默认)       │                     │  Available = 200   │
  │                    │                     │                    │
  │                    │  ① 发送消息 (消费1)  │                    │
  │  Available = 199   │────────────────────►│  Received          │
  │                    │                     │                    │
  │                    │  ② 发送消息 (消费2)  │                    │
  │  Available = 198   │────────────────────►│  Processing        │
  │                    │                     │                    │
  │        ...         │        ...          │        ...         │
  │                    │                     │                    │
  │  Available = 0     │  ③ 无 Credit 可用    │                    │
  │                    │  ╔═══════════╗      │                    │
  │                    │  ║ 发送阻塞!  ║      │                    │
  │                    │  ╚═══════════╝      │                    │
  │                    │                     │                    │
  │                    │  ④ Credit 补充      │                    │
  │  Available += 100  │◄────────────────────│  处理完一批消息     │
  │                    │                     │  Credit Return      │
  │                    │  ⑤ 继续发送          │                    │
  │                    │────────────────────►│                    │
  └────────────────────┘                     └────────────────────┘
```

**Credit 流控的关键参数：**

```erlang
%% rabbit_framing_amqp_0_9_1:credit_flow_settings
%% 硬编码在 rabbit_framing_amqp_0_9_1.erl 中
-define(CREDIT_MINIMUM, 20).         %% 信用最低阈值
-define(CREDIT_INITIAL, 200).        %% 初始信用量
-define(CREDIT_RETURN_SIZE, 100).    %% 批量返还信用量
```

**Credit 流控的 Erlang 实现：**

```erlang
%% rabbit_credit_flow:send/1 - 发送消息时消耗 credit
send(Pid) ->
    case erlang:get({credit, Pid}) of
        undefined ->
            %% ETS 表查找初始 credit
            case rabbit_credit_flow:init(Pid) of
                {ok, Credits} when Credits > 0 ->
                    erlang:put({credit, Pid}, Credits - 1);
                {ok, 0} ->
                    %% credit 耗尽，阻塞当前进程
                    block(Pid),
                    erlang:put({credit, Pid}, 0)
            end;
        Credits when Credits > 0 ->
            erlang:put({credit, Pid}, Credits - 1);
        0 ->
            %% 已经阻塞，继续等待
            block(Pid)
    end.

%% rabbit_credit_flow:return/1 - 处理完消息后返还 credit
return(Pid) ->
    case erlang:get({credit, Pid}) of
        undefined -> ok;
        Credits when Credits >= ?CREDIT_RETURN_SIZE ->
            %% 批量返还到目标进程
            Pid ! {credit, erlang:self(), Credits},
            erlang:put({credit, Pid}, 0);
        Credits ->
            erlang:put({credit, Pid}, Credits + 1)
    end.
```

### 4.2 内存水位线 (Memory Watermark)

RabbitMQ 会监控 Erlang VM 的内存使用，当超过阈值时主动阻塞生产者。

```
内存水位触发流程:

  内存使用率上升
       │
       ▼
  ┌───────────────────────┐
  │ vm_memory_high_watermark │
  │ 默认: 0.4 (物理内存40%) │
  └───────────┬───────────┘
              │
      检测到内存超过阈值
              │
              ▼
  ┌───────────────────────┐
  │  触发 Memory Alarm    │
  │  alarm: {resource_limit, memory, NodeName} │
  └───────────┬───────────┘
              │
     ┌────────┴────────┐
     │                  │
     ▼                  ▼
  ┌────────────┐   ┌──────────────┐
  │ Block       │   │ Page to Disk │
  │ Publisher   │   │ (分页到磁盘)  │
  │ 所有 Channel │   │              │
  │ 的生产者暂停 │   │ Queue Index  │
  └────────────┘   │ 从内存写入磁盘 │
                    │ Alpha→Delta   │
                    │ 状态迁移       │
                    └──────────────┘
                        │
                    ┌───┴────┐
                    │        │
                    ▼        ▼
              ┌────────┐ ┌────────┐
              │页面逐出 │ │ 消息体 │
              │完成     │ │ 写入   │
              └────────┘ │ Segment │
                         └────────┘
                        │
                        ▼
                 ┌──────────────┐
                 │ 内存使用下降   │
                 │ 低于水位线?    │
                 └──────┬───────┘
                        │
                    达到阈值
                        │
                        ▼
                 ┌──────────────┐
                 │ 释放 Memory  │
                 │ Alarm       │
                 │ 解除生产者阻塞│
                 └──────────────┘
```

**配置参数：**

```ini
# rabbitmq.conf
# 内存阈值：物理内存的 40%
vm_memory_high_watermark = 0.4

# 相对阈值：相对于上次 GC 后的内存
vm_memory_high_watermark.relative = 0.4

# 绝对阈值：直接指定字节数
# vm_memory_high_watermark.absolute = 2GB

# 设置内存计算方式
vm_memory_calculation_strategy = rss
# 可选: rss, allocated, erlang
```

**源码实现 (rabbit_alarm)：**

```erlang
%% rabbit_alarm:handle_info/2 - 内存监控
handle_info({set_alarm, Alarm}, State) ->
    case lists:keymember(memory, 1, State#state.alarms) of
        false ->
            %% 新警报，设置阻塞
            rabbit_alarm:set_or_clear_alarm(memory),
            %% 广播给所有连接
            [Pid ! alarm || Pid <- rabbit_connection:list()],
            {noreply, State#state{alarms = [{memory, Node} | State#state.alarms]}};
        true ->
            {noreply, State}
    end;
```

### 4.3 磁盘水位线 (Disk Watermark)

```
磁盘水位触发流程:

  磁盘可用空间下降
       │
       ▼
  ┌──────────────────────────┐
  │ disk_free_limit          │
  │ 默认: 50MB               │
  └───────────┬──────────────┘
              │
      检测到磁盘剩余 < 阈值
              │
              ▼
  ┌──────────────────────────┐
  │  触发 Disk Alarm         │
  │  (所有生产者阻塞)         │
  └───────────┬──────────────┘
              │
     ┌────────┴────────┐
     │                  │
     ▼                  ▼
  ┌────────────────┐  ┌──────────────────┐
  │ 阻塞所有        │  │ 减少磁盘写入     │
  │ Publisher      │  │ 暂停 GC、刷盘    │
  └────────────────┘  └──────────────────┘
              │
              │
      磁盘空间恢复 > 阈值
              │
              ▼
  ┌──────────────────┐
  │ 解除 Disk Alarm  │
  │ 恢复正常发布     │
  └──────────────────┘
```

**配置：**

```ini
# 绝对阈值
disk_free_limit = 2GB

# 相对阈值 (内存的倍数, 3.x 以上支持)
# disk_free_limit.relative = 2.0
```

### 4.4 流控对性能的影响与监控

**流控状态对系统的影响：**

```
正常状态:
  ┌──────┐    ┌──────┐    ┌──────┐
  │Producer│──▶│Exchange│──▶│Queue │──▶│Consumer│
  └──────┘    └──────┘    └──────┘    └──────┘
  吞吐量: 100% ✅

Memory Alarm 触发:
  ┌──────┐   BLOCKED   ┌──────┐    ┌──────┐
  │Producer│───✗───▶│Exchange│──▶│Queue │──▶│Consumer│
  └──────┘            └──────┘    └──────┘    └──────┘
  生产者被阻塞，消费继续
  吞吐量: Producer 0%, Consumer 100%
  积压: 逐渐下降

Disk Alarm 触发:
  ┌──────┐   BLOCKED   ┌──────┐    ┌──────┐
  │Producer│───✗───▶│Exchange│──▶│Queue │──▶│Consumer│
  └──────┘            └──────┘    └──────┘    └──────┘
  全部阻塞，系统 0 吞吐
```

**监控命令：**

```bash
# 查看 alarm 状态
rabbitmqctl list_connections name channels state
# 输出中 state=blocking 或 blocked 表示流控中

# 查看内存使用
rabbitmqctl status | findstr memory

# 查看磁盘状态
rabbitmqctl list_queues name messages messages_ready messages_unacknowledged

# 通过管理 API
# GET /api/nodes/{node}/memory
# GET /api/aliveness-test/%2f
```

### 高频面试题 (Section 4)

**Q: RabbitMQ 的内存流控和 Kafka 的流控有什么本质区别？**

A: RabbitMQ 的流控是**进程级信用(Credit)机制**，每个 Channel 和 Queue 之间逐消息进行信用交换，粒度高但实现复杂。Kafka 的流控是**请求级别的配额(Quota)**，在 Broker 和 Client 之间基于字节数限流，粒度较粗但实现简单。RabbitMQ 流控优势在于细粒度反压（能精确阻塞到单个 Channel），劣势在于吞吐量下降时延迟增加明显。

**Q: 生产环境中如何避免频繁触发 Memory Alarm？**

A: (1) 合理估算业务流量，设置合适的 `vm_memory_high_watermark`（通常在 0.4-0.6）；(2) 使用 Lazy Queue 减少内存中消息量；(3) 设置合理的 `max_length` 和 `max_length_bytes` 限制队列容量；(4) 监控消费者处理能力，确保消费速度 > 生产速度；(5) 使用 `rabbitmqctl set_vm_memory_high_watermark` 动态调整阈值。

**Q: Credit 流控中 `block/1` 进程阻塞的原理是什么？**

A: Erlang 进程的 `block/1` 实现基于进程消息队列。当 credit 耗尽时，发送方进程调用 `erlang:process_flag(sensitive, true)` 配合 `receive` 进入等待状态，等待目标进程发送 credit 归还消息。这种阻塞是 Erlang 进程级别的，不会阻塞操作系统线程。

---

## 5. 集群架构深度

### 5.1 普通集群 (Non-Mirrored)

RabbitMQ **普通集群**只同步元数据（Exchange、Binding、User、Vhost），消息数据存储在声明该 Queue 的节点本地。

```
                        RabbitMQ Cluster (3 nodes)
  ┌────────────────────┐  ┌────────────────────┐  ┌────────────────────┐
  │    Node A (master) │  │    Node B          │  │    Node C          │
  │                    │  │                    │  │                    │
  │  Exchange 表 ──────┼──┼──► Exchange 表     │  │  Exchange 表       │
  │  Binding 表  ──────┼──┼──► Binding 表      │  │  Binding 表        │
  │  User/Vhost ──────┼──┼──► User/Vhost      │  │  User/Vhost        │
  │                    │  │                    │  │                    │
  │  ┌──────────┐      │  │                    │  │  ┌──────────┐      │
  │  │ Queue Q1 │──────┼──┼─── 元数据同步 ──────┼──┼──┤ Queue Q1 │      │
  │  │ (拥有者)  │      │  │                    │  │  │ (引用)    │      │
  │  │          │      │  │                    │  │  │          │      │
  │  │ msg_1   │      │  │                    │  │  │ (无消息)  │      │
  │  │ msg_2   │      │  │                    │  │  │          │      │
  │  │ msg_3   │      │  │  ┌──────────┐      │  │  └──────────┘      │
  │  └──────────┘      │  │  │ Queue Q2 │      │  │                    │
  │                    │  │  │ (拥有者)  │      │  │                    │
  │                    │  │  └──────────┘      │  │                    │
  └────────────────────┘  └────────────────────┘  └────────────────────┘

  节点间：Erlang 内部节点通信 (EPMD / 25672 端口)
  
  消息流:
  Producer → Node B → 路由到 Q1 (在 Node A) → 转发到 Node A 存储
                                                      │
                                                      │
  Consumer → Node C → 路由到 Q1 (在 Node A) ← 转发消息到消费者
```

**关键特性：**

1. **队列的所有者节点**：Queue Q1 声明在 Node A，所有消息存储、消费、确认都在 Node A 进行。
2. **跨节点访问**：从 Node B 或 Node C 连接的生产者/消费者，访问 Q1 时会通过 Erlang 内部通信转发到 Node A。
3. **单点风险**：Node A 宕机后，Q1 不可用（消息丢失或暂时不可访问，取决于队列是否 durable）。
4. **网络开销**：跨节点访问额外增加一次 Erlang 消息传递延迟。

**源码中的元数据同步 (rabbit_table)：**

```erlang
%% rabbit_table:ensure_mnesia_table/1
%% RabbitMQ 使用 Mnesia (Erlang 分布式数据库) 同步集群元数据
ensure_mnesia_table(Tab) ->
    case mnesia:create_table(Tab, [
        {disc_copies, [node() | nodes()]},
        {attributes, record_info(fields, Tab)}
    ]) of
        {atomic, ok} -> ok;
        {aborted, {already_exists, _}} -> ok;
        {aborted, Reason} -> {error, Reason}
    end.
```

### 5.2 镜像队列 (Mirrored Queue) - 同步复制协议

镜像队列 (Mirrored Queue) 在 RabbitMQ 3.8 之前是高可用的解决方案。它基于 **GM (Guaranteed Multicast)** 协议实现消息的同步复制。

**GM 协议原理：**

```
GM (Guaranteed Multicast) 是一个全序可靠的组播协议。

┌─────────────────────────────────────────────────────────┐
│                    GM 组播架构                           │
│                                                         │
│  ┌─────────┐    ┌─────────┐    ┌─────────┐             │
│  │ Node A  │    │ Node B  │    │ Node C  │             │
│  │ (Master)│    │ (Slave) │    │ (Slave) │             │
│  │         │    │         │    │         │             │
│  │ ┌─────┐ │    │ ┌─────┐ │    │ ┌─────┐ │             │
│  │ │ GM  │ │    │ │ GM  │ │    │ │ GM  │ │             │
│  │ │Group│ │    │ │Group│ │    │ │Group│ │             │
│  │ └──┬──┘ │    │ └──┬──┘ │    │ └──┬──┘ │             │
│  └────┼────┘    └────┼────┘    └────┼────┘             │
│       │              │              │                   │
│       └──────────────┼──────────────┘                   │
│                      │                                  │
│           全序消息广播 (Total Order)                     │
│           每个节点按相同顺序处理消息                       │
└─────────────────────────────────────────────────────────┘
```

**GM 的消息结构：**

```erlang
%% gm.erl - GM 消息格式
-record(msg, {
    id      :: {non_neg_integer(), node()},  %% {序列号, 发送节点}
    header  :: term(),                        %% 元数据
    body    :: term(),                        %% 消息体
    kind    :: 'lambda' | 'regular',         %% 消息类型
    prev    :: term(),                        %% 前一个消息的 ID
    members :: [node()]                       %% 组成员列表
}).
```

### 5.3 镜像队列消息发布流程

```
  Publisher                      Master Node                       Slave Node 1                    Slave Node 2
     │                               │                                  │                              │
     │  Basic.Publish                │                                  │                              │
     │──────────────────────────────►│                                  │                              │
     │                               │                                  │                              │
     │                         ① Exchange 路由                         │                              │
     │                               │                                  │                              │
     │                         ② 写入 Message Store                     │                              │
     │                         ③ Queue Index 更新                      │                              │
     │                               │                                  │                              │
     │                         ④ GM 组播开始                             │                              │
     │                               │─────────────────────────────────►│                              │
     │                               │   msg: {seq, body}              │                              │
     │                               │◄─────────────────────────────────│                              │
     │                               │      ⑤ 接收到确认                │                              │
     │                               │─────────────────────────────────►│─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─►│
     │                               │                                  │   ⑥ GM 传播到 Slave 2         │
     │                               │                                  │◄─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─│
     │                               │                                  │                              │
     │                         ⑦ GM 达到多数派确认                       │                              │
     │                               │                                  │                              │
     │                         ⑧ 发送 Basic.Ack                        │                              │
     │◄──────────────────────────────│                                  │                              │
     │                               │                                  │                              │
     │         时延 = T_write_master + T_gm_multicast + T_gm_confirm    │                              │
     │                               │                                  │                              │
```

### 5.4 镜像队列 Master 故障迁移流程

```
           故障前                           Master  Node A 宕机
  ┌─────────┐  ┌─────────┐  ┌─────────┐        │
  │ Node A  │  │ Node B  │  │ Node C  │        │
  │ (Master)│  │ (Slave) │  │ (Slave) │        │
  │         │  │         │  │         │        │
  │ msg_1-3 │  │ msg_1-3 │  │ msg_1-3 │        │
  │ msg_4-5 │  │ msg_4   │  │ msg_4-5 │        │
  │ msg_6   │  │ msg_5   │  │ msg_6   │        │
  │         │  │ msg_6   │  │         │        │
  └─────────┘  └─────────┘  └─────────┘        │
                                               │
           ┌───────────────────────────────────┘
           │
           ▼
    执行故障检测 (Net Tick Time: 默认 60s)
           │
           ▼
  ┌─────────────────────────────────────────────┐
  │  从存活的 Slave 中选择最老的作为新 Master    │
  │  判定标准: GM 序列号最大的 Slave             │
  └──────────────┬──────────────────────────────┘
                 │
                 ▼
      ┌──────────────────────┐
      │ 谁拥有最新的消息?     │
      │                      │
      │  Node C: msg_1-6     │  ← 最大 seq 号
      │  Node B: msg_1-5     │
      └──────────┬───────────┘
                 │
                 ▼
  ┌──────────────────────────────┐
  │  Node C 升为新 Master       │
  │                              │
  │  ① 确认所有权转移            │
  │  ② 广播集群节点               │
  │  ③ 解除旧 Master 的 GM 组   │
  │  ④ 重建与剩余 Slave 的 GM   │
  │  ⑤ 恢复生产者和消费者连接    │
  └──────────────────────────────┘
                 │
                 ▼
  ┌─────────┐  ┌─────────┐
  │ Node C  │  │ Node B  │
  │ (Master)│  │ (Slave) │
  │         │  │         │
  │ msg_1-6 │  │ msg_1-5 │
  │         │  │         │
  │         │  │ 同步丢失 │
  │         │  │ 的消息   │
  └─────────┘  │ msg_6   │
               └─────────┘
```

**故障迁移的源码关键路径 (rabbit_mirror_queue_master)：**

```erlang
%% rabbit_mirror_queue_master:handle_down/2
handle_down({DOWN, _Ref, process, _Pid, _Reason}, State) ->
    case State#state.policy of
        {_, Nodes} ->
            %% 过滤存活的节点
            LiveNodes = [N || N <- Nodes, lists:member(N, rabbit_mnesia:cluster_nodes(running))],
            case LiveNodes of
                [] -> %% 没有存活节点，结束
                    {stop, normal, State};
                [NewMaster|_] ->
                    %% 选择 GM 序列号最大的节点作为新 Master
                    %% 发送 takeover 指令
                    [N ! {takeover, Self} || N <- LiveNodes],
            end
    end.
```

### 5.5 Quorum Queue (3.8+) - Raft 协议实现

Quorum Queue 是 RabbitMQ 3.8 引入的基于 **Raft 共识算法** 的队列类型，是镜像队列的现代替代方案。

**Raft 在 RabbitMQ 中的适配：**

```
Quorum Queue 的 Raft 实现:

  ┌─────────┐     ┌─────────┐     ┌─────────┐
  │ Node A  │     │ Node B  │     │ Node C  │
  │ (Leader)│     │(Follower)│    │(Follower)│
  │         │     │         │     │         │
  │ ┌─────┐ │     │ ┌─────┐ │     │ ┌─────┐ │
  │ │Raft │ │     │ │Raft │ │     │ │Raft │ │
  │ │Log  │ │     │ │Log  │ │     │ │Log  │ │
  │ ├─────┤ │     │ ├─────┤ │     │ ├─────┤ │
  │ │Term:3│ │     │ │Term:3│ │     │ │Term:3│ │
  │ │Idx:10│ │     │ │Idx:9 │ │     │ │Idx:10│ │
  │ └─────┘ │     │ └─────┘ │     │ └─────┘ │
  └─────────┘     └─────────┘     └─────────┘

  Raft Log Entry:
  ┌─────┬──────┬────────┬──────────┐
  │Index│ Term │  Type  │   Data   │
  ├─────┼──────┼────────┼──────────┤
  │  1  │  1   │command │publish   │
  │  2  │  1   │command │ack       │
  │  3  │  2   │command │publish   │
  │ ... │ ...  │  ...   │   ...    │
  │  10 │  3   │command │publish   │
  └─────┴──────┴────────┴──────────┘
```

**Quorum Queue 的完整消息发布流程：**

```
  Publisher                      Raft Leader (Node A)            Raft Follower (Node B)     Raft Follower (Node C)
     │                                  │                              │                          │
     │  Basic.Publish                    │                              │                          │
     │─────────────────────────────────►│                              │                          │
     │                                  │                              │                          │
     │                            ① Append Entry                        │                          │
     │                            创建 Raft Log Entry                   │                          │
     │                                  │                              │                          │
     │                            ② 并行复制到 Follower                  │                          │
     │                                  │─────────────────────────────►│                          │
     │                                  │  AppendEntries RPC            │                          │
     │                                  │─────────────────────────────►│─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─►│
     │                                  │                              │                          │
     │                            ③ Follower 写入本地日志                 │                          │
     │                                  │                              │                          │
     │                                  │◄─────────────────────────────│                          │
     │                                  │     AppendEntries Response    │                          │
     │                                  │◄─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─│─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─│
     │                                  │                              │                          │
     │                            ④ 统计确认数                             │                          │
     │                            多数派 = N/2 + 1                      │                          │
     │                            3节点 -> 2确认 (Leader自身+1个Follower) │                          │
     │                                  │                              │                          │
     │                            ⑤ Commit 日志                        │                          │
     │                             应用到状态机                          │                          │
     │                             消息入 Queue                         │                          │
     │                                  │                              │                          │
     │                            ⑥ 通知 Follower Commit                 │                          │
     │                                  │─────────────────────────────►│                          │
     │                                  │  (下一个 AppendEntries 携带    │                          │
     │                                  │   commitIndex)               │                          │
     │                                  │                              │                          │
     │                            ⑦ 发送 Basic.Ack                     │                          │
     │◄─────────────────────────────────│                              │                          │
     │                                  │                              │                          │
```

**Raft Leader 选举流程：**

```
          Node A                       Node B                       Node C
        (Candidate)                  (Follower)                   (Follower)
            │                            │                            │
            │  ① Election Timeout         │                            │
            │  (T~150-300ms)              │                            │
            │                            │                            │
            │  ② Term += 1 (Term=4)       │                            │
            │  ③ 自我投票                  │                            │
            │                            │                            │
            │  ④ RequestVote RPC          │                            │
            │───────────────────────────►│                            │
            │  (term, lastLogIndex,       │                            │
            │   lastLogTerm)             │                            │
            │───────────────────────────►│─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─►│
            │                            │                            │
            │  ⑤ 检查: Vote for me?       │                            │
            │     条件:                    │                            │
            │      - 任期 >= 我的任期       │                            │
            │      - 日志至少和我一样新     │                            │
            │      - 当前任期未投票         │                            │
            │                            │                            │
            │◄───────────────────────────│                            │
            │  Vote granted              │                            │
            │◄─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─│─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─│
            │                            │                            │
            │  ⑥ 获得多数派投票: ✓       │                            │
            │  成为 Leader                │                            │
            │                            │                            │
            │  ⑦ 发送心跳                 │                            │
            │  (AppendEntries, term=4,    │                            │
            │   entries=[])              │                            │
            │───────────────────────────►│                            │
            │───────────────────────────►│─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─►│
            │                            │                            │
            │  ⑧ Follower 收到心跳:       │                            │
            │     重置 Election Timer     │                            │
            │     承认 Node A 为 Leader   │                            │
            │                            │                            │
```

**Quorum Queue 的 Raft 实现关键源码 (ra 库)：**

```erlang
%% ra:leader/1 - Leader 处理一致性写入
leader(State) ->
    #state{log = Log, cluster = Cluster, current_term = Term} = State,
    %% 创建日志条目
    Entry = #log_entry{term = Term, index = Log.last_index + 1,
                       type = command, data = Data},
    %% 追加到本地日志
    Log2 = ra_log:append(Log, Entry),
    %% 并发发送 AppendEntries 到所有 Follower
    {ok, Quorum} = quorum(Cluster),
    AckCount = 1, %% 自己的一票
    %% 收集响应...
    case AckCount >= Quorum of
        true ->
            %% 达到多数派，提交
            State2 = commit(State, Entry),
            {ok, State2};
        false ->
            %% 未达到多数派，等待
            {noreply, State}
    end.
```

### 5.6 Quorum Queue vs 镜像队列对比

| 维度 | 镜像队列 (Mirrored Queue) | Quorum Queue (Raft) |
|------|--------------------------|---------------------|
| **一致性协议** | GM 组播 (Guaranteed Multicast) | Raft 共识算法 |
| **一致性保证** | 最终一致性 (Async Replication) | 强一致性 (Linearizable) |
| **确认方式** | Master 确认 (可能未到所有 Slave) | 多数派确认 (Majority Commit) |
| **写入延迟** | 低 (Master 本地确认) | 较高 (至少 2/3 节点确认) |
| **读取一致性** | 可能读到过期 Slave | Leader 读取 (强一致) |
| **自动故障转移** | 支持 (最旧 Slave 升 Master) | 支持 (Raft Leader 选举) |
| **网络分区容忍** | 可能脑裂 (Split-Brain) | 分区容忍 (Majority 原则) |
| **消息顺序** | 全序 (GM 保证) | 全序 (Raft Log) |
| **配置变更** | 手动 | 支持动态成员变更 (Raft Joint Consensus) |
| **内存占用** | 所有节点存储全量消息 | 所有节点存储全量消息 |
| **推荐使用** | RabbitMQ 3.7 及以下 | RabbitMQ 3.8+ (默认推荐) |
| **生产建议** | 不建议在新项目中使用 | 推荐用于生产环境 |

**网络分区对两种架构的影响：**

```
镜像队列网络分区:
  ┌──────────┐     Network      ┌──────────┐
  │ Node A    │◄─── Partition ──►│ Node B    │
  │ (Master)  │                  │ (Slave)   │
  │           │                  │           │
  │ 检测到分区 │                  │ 检测不到  │
  │ 降级为只读  │                 │ Master(??)│
  │ (或停止)  │                  │ 自己升为  │
  │           │                  │ Master(!!)│
  └──────────┘                  └──────────┘

  结果: 两个 Master → 脑裂 → 数据不一致

Quorum Queue 网络分区:
  ┌──────────┐     Network      ┌──────────┐
  │ Node A    │◄─── Partition ──►│ Node B    │
  │ (Leader)  │                  │(Follower) │
  │ Node C    │                  │           │
  │ (Follower)│                  │           │
  │           │                  │           │
  │ 多数派 = 2 │                  │ 少数派 = 1 │
  │ 正常工作  │                  │ 不可写入   │
  │           │                  │ (只读)     │
  └──────────┘                  └──────────┘

  结果: 只少数派不能写入 → 分区恢复后自动同步
```

### 高频面试题 (Section 5)

**Q: RabbitMQ 普通集群中，Queue 的所有者节点宕机后会发生什么？**

A: (1) 如果 Queue 是 durable 的且节点可以重启（非永久故障），消息不会丢失，节点恢复后 Queue 恢复；(2) 如果节点永久故障，queue 和其上的消息丢失，但其他节点上的 Exchange、Binding 元数据不受影响；(3) 连接到其他节点的生产者可以继续发布到 Exchange，但目标 Queue 不可用，消息会被丢弃或返回（取决于 mandatory）；(4) 这是为什么生产环境必须使用镜像队列或 Quorum Queue。

**Q: Quorum Queue 为什么比镜像队列更可靠？**

A: (1) Raft 提供强一致性保证，消息在多数派节点确认后才算写入成功，不会出现"Master 认为写入成功但 Slave 未同步"的情况；(2) Leader 选举过程有严格的安全保证（只会选举日志最新的节点），不会出现脑裂；(3) 自动成员变更 (Joint Consensus) 支持动态扩缩容而不中断服务。

**Q: Quorum Queue 的适用场景和限制？**

A: 适用场景：(1) 对数据一致性要求高的场景（交易、支付、订单）；(2) 需要自动故障转移和 Leader 选举的场景。限制：(1) 写入延迟比镜像队列高（需要多数派确认）；(2) 不支持队列独占或临时队列（auto-delete）；(3) 不支持优先级或延迟队列等高级特性；(4) Raft 组通常建议 3-5 个成员，不推荐超过 7 个。

---

## 6. 跨集群方案

### 6.1 Federation 联邦插件

Federation 实现的是**拉模型 (Pull Model)**，下游集群主动拉取上游集群的消息。

```
Federation 架构:

  上游集群 (Upstream)                       下游集群 (Downstream)
  ┌─────────────────────┐                    ┌─────────────────────┐
  │   ┌───────────┐     │    AMQP 0-9-1      │   ┌───────────┐     │
  │   │ Exchange A │─────┼────────────────────┼──▶│ Exchange B │     │
  │   └───────────┘     │    (Federation      │   └───────────┘     │
  │                     │     Link)           │                     │
  │   ┌───────────┐     │                    │   ┌───────────┐     │
  │   │ Queue X   │─────┼────────────────────┼──▶│ Queue Y   │     │
  │   └───────────┘     │                    │   └───────────┘     │
  │                     │                    │                     │
  └─────────────────────┘                    └─────────────────────┘
         │                                            │
         │  Federation Link (AMQP 连接)                │
         │   - 在上游声明 Exchange/Queue                │
         │   - 消费上游消息                             │
         │   - 发布到下游                               │
         │                                            │
         └────────────────────────────────────────────┘

  数据流:
    消息 → Upstream Exchange → (Federation Link 消费) → Downstream Exchange
        → Downstream Queue → 下游消费者

  重点: Federation 是松散耦合的
       - 上游宕机不影响下游 (下游仍可服务)
       - 消息会有延迟 (取决于 Poll 间隔)
       - 不保证全局一致顺序
```

**Federation 配置示例：**

```bash
# 定义上游
rabbitmqctl set_parameter federation-upstream my-upstream \
  '{"uri":"amqp://user:pass@upstream-host:5672","expires":100000}'

# 定义上游策略 - 自动 Federation
rabbitmqctl set_policy federation-policy \
  "^fed\." '{"federation-upstream-set":"all"}' \
  --priority 10 --apply-to exchanges

# 上下游集群需要安装 rabbitmq_federation 和 rabbitmq_federation_management
```

**Federation 的工作原理 (源码级)：**

```erlang
%% rabbit_federation_link:start_link/6 - Federation Link 进程
start_link(Upstream, ExchangeName, ...) ->
    %% 1. 创建到上游集群的 AMQP 连接
    {ok, Conn} = amqp_connection:start(Upstream#upstream.uri),
    %% 2. 在上游声明 Exchange (被动声明)
    {ok, Ch} = amqp_connection:open_channel(Conn),
    amqp_channel:call(Ch, #'exchange.declare'{
        exchange = ExchangeName,
        passive  = true     %% 只检查是否存在，不创建
    }),
    %% 3. 创建匿名 Queue + Bind 到 Exchange
    #'queue.declare_ok'{queue = Q} =
        amqp_channel:call(Ch, #'queue.declare'{exclusive = true}),
    amqp_channel:call(Ch, #'queue.bind'{
        queue      = Q,
        exchange   = ExchangeName,
        routing_key = <<"#">>
    }),
    %% 4. 开始消费 (basic.consume)
    amqp_channel:subscribe(Ch, #'basic.consume'{queue = Q}, self()),
    %% 5. 消息转发
    loop(Ch, DownstreamExchange, State).
```

### 6.2 Shovel 插件

Shovel 实现的是**推/拉转发模型**，在集群之间建立一对一的消费者/生产者关系。

```
静态 Shovel:

  ┌──────────────┐               ┌──────────────┐
  │ Source       │               │ Destination  │
  │ Cluster      │               │ Cluster      │
  │              │    AMQP       │              │
  │ ┌──────────┐ │   连接        │ ┌──────────┐ │
  │ │Queue A   │─┼──────────────┼▶│Exchange B│ │
  │ └──────────┘ │               │ └────┬─────┘ │
  │              │               │      │       │
  │ Shovel 在     │               │      ▼       │
  │ 运行时创建:   │               │ ┌──────────┐ │
  │ consume Q_A │               │ │Queue B   │ │
  │ → publish   │               │ └──────────┘ │
  │   到 Exchange B              │              │
  └──────────────┘               └──────────────┘

动态 Shovel (可运行时配置):

  ┌─────┐                                                  ┌─────┐
  │RMQ  │                                                  │RMQ  │
  │ DC1 │   Shovel 定义可热加载，无需重启                     │ DC2 │
  │     │   rabbitmqctl set_parameter shovel my-shovel      │     │
  │     │   '{"src-protocol": "amqp091",                    │     │
  │     │     "src-uri": "amqp://...",                      │     │
  │     │     "src-queue": "q_in",                          │     │
  │     │     "dest-protocol": "amqp091",                   │     │
  │     │     "dest-uri": "amqp://...",                     │     │
  │     │     "dest-exchange": "ex_out"}'                   │     │
  └─────┘                                                  └─────┘
```

**Shovel 的工作流程：**

```
Shovel 进程内部逻辑:

  启动
    │
    ▼
  ┌──────────────────────┐
  │ 建立到 Source 的连接  │
  └──────────┬───────────┘
             │
             ▼
  ┌──────────────────────┐
  │ 建立到 Dest 的连接    │
  └──────────┬───────────┘
             │
             ▼
  ┌──────────────────────┐
  │ 打开 Source Channel  │
  │ 声明源 Queue         │
  └──────────┬───────────┘
             │
             ▼
  ┌───────────────────────────┐
  │ Basic.Consume 源 Queue    │
  │ prefetch=N, autoAck=false │
  └──────────┬────────────────┘
             │
       ┌─────┴─────┐            ← 收到消息投递
       │           │
       ▼           ▼
  ┌──────────┐  ┌──────────────────┐
  │ 打开     │  │ Confirm.Select   │
  │ Dest     │  │ (启用发布确认)    │
  │ Channel  │  └────────┬─────────┘
  └────┬─────┘           │
       │                 │
       ▼                 ▼
  ┌──────────────────────────┐
  │ Basic.Publish 到 Dest    │
  │ (保留原始消息属性)        │
  └──────────┬───────────────┘
             │
             ▼
  ┌─────────────────────┐
  │ 等待 Dest 确认       │
  │ 成功 → Basic.Ack 源  │
  │ 失败 → Basic.Nack 源 │
  │        (消息 requeue)│
  └─────────────────────┘
             │
             ▼
  ┌─────────────────────┐
  │ 继续消费下一条消息    │
  │ (循环)              │
  └─────────────────────┘
```

### 6.3 两种方案的选择决策树

```
          需要跨集群消息同步?
                   │
           ┌───────┴───────┐
           │               │
        单向同步          双向同步
           │               │
           ▼               ├─────────────┐
   ┌───────────────┐      │             │
   │ 需要过滤/转换?  │    双向同步      双向同步
   └───────┬───────┘     + 全局有序    + 松耦合
           │               │             │
     ┌─────┴─────┐        ▼             ▼
     │           │     ┌────────┐  ┌────────────┐
     ▼           ▼     │ 不推荐 │  │ 各自独立   │
  ┌──────┐  ┌──────┐   │ 用 MQ  │  │ Federation │
  │是    │  │否    │   │ 跨集群 │  │ (不同业务) │
  │Shovel│  │Fed   │   │ 同步   │  │            │
  │      │  │eration│  │ 考虑   │  │            │
  └──────┘  └──────┘   │  Kafka │  └────────────┘
                       │ Mirrormaker│
                       └────────┘

  详细决策因素:

  1. 拓扑结构:
     - 一对多广播 → Federation
     - 一对一转发 → Shovel
     - 多对多 → 一般不推荐 (需要仲裁)

  2. 消息语义:
     - 需要确认转发 → Shovel (自带 Confirm)
     - 允许延迟 → Federation (拉模型延迟较高)
     - 需要保序 → Shovel (单链路顺序性强)

  3. 运维复杂度:
     - 配置多路由 → Federation (策略统一管理)
     - 简单点对点 → Shovel (配置直观)
```

### 高频面试题 (Section 6)

**Q: Federation 和 Shovel 的核心区别是什么？**

A: (1) **模型不同**：Federation 是拉模型（下游主动拉取），Shovel 是 push-pull 模型（消费源然后发布到目标）；(2) **配置粒度**：Federation 以策略(Policy)方式批量匹配，Shovel 逐一定义；(3) **可靠性保证**：Shovel 内置发布确认机制，Federation 依赖于标准 AMQP 消费；(4) **适用场景**：Federation 适合松散耦合的多数据中心复制（多个下游同时订阅上游），Shovel 适合精确的、可审计的单链路数据迁移或聚合。

**Q: 多数据中心场景下，RabbitMQ 如何保证跨 DC 的消息不丢？**

A: (1) 使用 Federation/Shovel + Publisher Confirm (保证跨 DC 链路可靠性)；(2) 生产者使用 at-least-once 语义 + 幂等消费者 (在消费端去重)；(3) 考虑使用 RabbitMQ Stream (3.9+) 配合 offset tracking 实现 exactly-once；(4) 网络层面使用高可靠链路（BGP/专线），避免跨公网传输。

---

## 7. 性能调优

### 7.1 连接/Channel 池化策略

**连接数与吞吐量的关系：**

```
吞吐量 (msg/s)
    ▲
    │                                    ·
    │                               ·
    │                          ·
    │                     ·
    │                ·               ← 拐点: 单个连接 Channel 数 200-500
    │           ·                       超过后 Erlang 进程调度开销上升
    │      ·                        内存占用增加 (每个 Channel ~几 KB)
    │  ·
    │·
    └──────────────────────────────────────────────► 连接/Channel 数
```

**最佳实践：**

```java
// Java 客户端连接池化示例
ConnectionFactory factory = new ConnectionFactory();
factory.setUri("amqp://host:5672");

// 使用连接池 (一个应用维护少量连接)
Connection conn = factory.newConnection(); // 通常 1-2 个连接

// Channel 池 (每个线程/请求从池中获取 Channel)
public class ChannelPool {
    private final Connection connection;
    private final BlockingQueue<Channel> pool = new LinkedBlockingQueue<>(100);

    public ChannelPool(Connection conn, int maxChannels) {
        this.connection = conn;
        for (int i = 0; i < maxChannels; i++) {
            pool.offer(conn.createChannel());
        }
    }

    public Channel borrow() throws InterruptedException {
        return pool.poll(5, TimeUnit.SECONDS);
    }

    public void return_(Channel ch) {
        if (ch.isOpen()) {
            pool.offer(ch);
        } // 关闭的 Channel 不回收
    }
}

// 使用建议:
// - 每个应用: 1-2 个 Connection
// - 每个 Connection: 50-300 个 Channel
// - 避免每个请求创建/关闭 Channel
```

**连接数推荐：**

| 场景 | Connection 数 | Channel 数 | 说明 |
|------|-------------|-----------|------|
| 微服务 (低吞吐) | 1 | 5-10 | 单连接，少量通道 |
| Web 应用 (中等) | 1-2 | 50-200 | 按需获取 |
| 高吞吐数据管道 | 2-4 | 200-500 | 分担不同用途 (发布/消费/管理) |
| 极端高吞吐 | 4-8 | 500-1000+ | 需监控 Erlang 进程数 |

### 7.2 Prefetch Count 的作用原理

Prefetch Count (QoS) 控制了未被 ACK 的最大消息数量，是**消费者端削峰**的核心参数。

```
prefetch=1  (逐个处理):
  Queue                    Consumer
  ┌────┐                    ┌────┐
  │ m1 │── deliver(m1) ──▶│    │
  │ m2 │   ...处理中...    │    │
  │ m3 │                  │    │
  │ m4 │   ack(m1)        │    │
  │ m5 │◄─────────────────│    │
  │ m6 │── deliver(m2) ──▶│    │
  └────┘                  └────┘
  特性: 逐个取, 逐个 ACK
  吞吐: 低 (网络往返多)
  公平性: 完美 (不会分配不均)

prefetch=10 (批量预取):
  Queue                    Consumer
  ┌────┐                    ┌────┐
  │ m1 │── deliver(1-10)──▶│    │
  │ m2 │   ...             │    │
  │ ...│   处理消费中...    │    │← buf: m1~m10 在消费者
  │ m10│                  │    │   处理完一个 ack 一个
  │ m11│── deliver(11) ───▶│    │
  │ ...│   (补充新消息)    │    │← buf: 始终维持 10 个
  └────┘                  └────┘
  特性: 批量预取, 滑动补充
  吞吐: 高 (减少网络往返)
  公平性: 需合理设置 (太大可能导致"饥饿消费者")

prefetch=0 (无限):
  Queue                    Consumer
  ┌────┐                    ┌────┐
  │ m1 │── deliver(all)───▶│    │
  │ ...│   ...             │    │
  │ mN │   全部推给消费者   │    │← buf: 所有消息
  └────┘   (高风险)        └────┘
  特性: 全量推送
  风险: 消费者 OOM, 内存耗尽
```

**Prefetch 对吞吐的影响实验规律：**

```
吞吐量
  ▲
  │                                  ┌──────────────────────┐
  │                                  │ 最佳区域              │
  │                                  │ prefetch = 30-300    │
  │                              ┌───┴───┐                  │
  │                         ┌────│       │─────┐            │
  │                    ┌────│    │       │     │────┐       │
  │               ┌────│    │    │       │     │    │──┐    │
  │          ┌────│    │    │    │       │     │    │  │    │
  │     ┌────│    │    │    │    │       │     │    │  │    │
  │  ┌──│    │    │    │    │    │       │     │    │  │    │
  │──│    │    │    │    │    │       │     │    │  │    │
  └──┴────┴────┴────┴────┴───────────────────────────────►
     1   3   10   30  100  300  1000  3000  prefetch

  关键 insight:
  - prefetch=1: 网络往返成为瓶颈
  - prefetch=30-300: 饱和吞吐
  - prefetch>1000: 不会有更多提升反而增加风险
```

### 7.3 消息积压的加速消费方案

```
消息积压场景:

  ┌──────────┐    ┌──────────┐    ┌──────────┐
  │ Producer │───▶│  Queue   │───▶│Consumer 1│
  │ 10k/s    │    │ 积压50万条│    │  2k/s    │
  └──────────┘    └──────────┘    └──────────┘
                              问题: 生产 >> 消费

解决方案树:
                    ┌────────────────────────────┐
                    │     消息积压处理            │
                    └────────────┬───────────────┘
                                 │
              ┌──────────────────┼──────────────────┐
              │                  │                   │
              ▼                  ▼                   ▼
    ┌─────────────────┐  ┌──────────────┐  ┌──────────────────┐
    │ 增加消费者 (水平) │  │ 批量 ACK     │  │ 调整 Prefetch   │
    └────────┬────────┘  └──────┬───────┘  └────────┬─────────┘
             │                  │                    │
             ▼                  ▼                    ▼
    ┌─────────────────┐  ┌──────────────┐  ┌──────────────────┐
    │ Consumer 1      │  │ manualAck    │  │ prefetch=300     │
    │ Consumer 2      │  │ multiple=true │  │ (充分利用网络)   │
    │ Consumer 3      │  │ ack 100条/次  │  │                  │
    │ ...             │  │ 减少 ACK 帧  │  │                  │
    │ 注意: 并行消费需 │  │ 开销         │  │                  │
    │ 关注有序性要求   │  └──────────────┘  └──────────────────┘
    └─────────────────┘

高级方案:
  ┌─────────────────────────────────────────────────────┐
  │ 临时方案 (不丢消息):                                 │
  │ 1. 创建新 Queue 并分流部分消费者                      │
  │ 2. Shovel 到新集群处理积压                            │
  │ 3. 暂停非关键消费者                                  │
  │                                                      │
  │ 永久方案:                                            │
  │ 1. 确认消费者效率（是否 I/O 瓶颈/CPU 瓶颈）            │
  │ 2. 评估是否需要 Batch Consumer                       │
  │ 3. 考虑使用 RabbitMQ Stream (3.9+)                   │
  └─────────────────────────────────────────────────────┘
```

### 7.4 Lazy Queue (3.6+)

Lazy Queue 将消息**直接写入磁盘**，只在必要时加载到内存，适用于消息积压场景。

```
普通 Queue (默认):
  消息 ──▶ 内存 ──▶ 磁盘 (后台刷盘)
  优点: 低延迟, 高吞吐
  缺点: 消息积压时消耗大量内存

Lazy Queue:
  消息 ──▶ 磁盘 ──▶ 内存 (消费时加载)
  优点: 内存可控, 可处理海量积压
  缺点: 写入延迟高, 吞吐较低
```

**配置方式：**

```bash
# 方式 1: Policy 声明
rabbitmqctl set_policy lazy-queue "^lazy\." \
  '{"queue-mode":"lazy"}' --apply-to queues

# 方式 2: 声明队列时指定 Arguments
Map<String, Object> args = new HashMap<>();
args.put("x-queue-mode", "lazy");
channel.queueDeclare("lazy.queue", true, false, false, args);
```

**适用场景对比：**

| 场景 | 普通 Queue | Lazy Queue |
|------|-----------|------------|
| 正常吞吐 (< 10k msg/s) | ✅ | ✅ |
| 高吞吐 (> 50k msg/s) | ✅ 推荐 | ⚠️ 延迟可能不满足 |
| 消息积压 (百万级) | ⚠️ 内存不足 | ✅ 推荐 |
| 低延迟 (< 1ms) | ✅ 推荐 | ⚠️ 磁盘延迟 |
| 消费者不稳定 (频繁断连) | ⚠️ 内存积压 | ✅ 推积到磁盘 |
| IoT/日志收集 | ❌ 可能 OOM | ✅ 推荐 |

### 高频面试题 (Section 7)

**Q: Prefetch count 设置过大或过小分别有什么问题？**

A: 过小 (`prefetch=1`)：(1) 网络往返成为瓶颈，每次只发送一条消息；(2) 消费者处理时间短时 CPU 利用率低（等待消息）。过大 (`prefetch>1000`)：(1) 消息分布不均，一个消费者拿到大量消息，其他消费者空闲；(2) 消费者崩溃时大量消息需要 requeue；(3) 消费者内存占用高。建议从 `prefetch=prefetch=2*n+1`（n 为消费者数）开始，逐步调优。

**Q: RabbitMQ 中如何优雅处理消息积压？**

A: (1) 区分积压原因：是消费者故障、消费者处理慢、还是生产者突然爆发；(2) 消费者故障：监控告警 + 自动恢复（重连/重新订阅）；(3) 消费者慢：增加消费者 + 优化处理逻辑 + 适当增大 prefetch；(4) 生产者爆发：限流生产者 + 临时扩容消费者；(5) 短期方案：使用 Lazy Queue 避免 OOM，积压后再逐步消费；(6) 长期方案：评估是否需要分区（如使用 Sharding 插件）或换用更适合的 MQ（如 Kafka）。

**Q: Channel 数量过多（上千个）为什么会引起性能问题？**

A: (1) 每个 Channel 是一个独立的 Erlang 进程，大量进程意味着 Erlang 调度器负担加重，上下文切换开销增大；(2) 每个 Channel 维护独立的状态（消费者表、未确认消息集），内存占用累积显著；(3) 消息在 Channel 间分发时竞争加剧，单连接瓶颈从网络层转移到 Erlang 进程间通信。建议监控 Channel 数量，过万时需要扩集群或优化客户端连接策略。

---

## 8. 生产运维

### 8.1 集群监控指标体系

**核心指标矩阵：**

| 分类 | 指标 | 告警阈值 | 说明 |
|------|------|---------|------|
| **队列** | messages_ready | 取决于容量 | 等待消费的消息数 |
| | messages_unacknowledged | 高于 prefetch 总和 | 未确认消息数，异常升高表示消费者卡住 |
| | messages_total | 根据业务 | 总消息数 (ready + unack) |
| | queue_length_limit | 接近上限 | 队列是否接近 max_length |
| **速率** | publish_rate | 突增/突降 | 发布速率 |
| | deliver_rate | 突降 | 投递速率 |
| | ack_rate | 低于 deliver | 确认速率，不匹配说明消费者问题 |
| | redeliver_rate | 升高 | 重新投递次数，可能的死循环 |
| **内存** | memory_used | > 90% 水位线 | 内存使用量 |
| | memory_alarm | 触发告警 | 内存告警状态 |
| | binary_heap | 异常升高 | Erlang 二进制堆，大消息时关注 |
| **磁盘** | disk_free | < 2x disk_free_limit | 磁盘剩余空间 |
| | disk_alarm | 触发告警 | 磁盘告警状态 |
| **连接** | connections | 突增/突降 | 连接数 |
| | channels | 异常升高 | Channel 数 (数千正常, 数万需关注) |
| | consumers | 突降 | 消费者数量 |
| **GC** | run_queue | > CPU 核心数 x2 | Erlang 调度运行队列 |
| | context_switches | 异常波动 | 上下文切换 |
| | gc_runs | 频繁告警 | GC 频率过高表示内存压力 |

**监控命令：**

```bash
# 快速检查集群健康
rabbitmqctl cluster_status
rabbitmqctl eval 'rabbit_alarm:is_system_alarm_raised().'

# 队列深度概览
rabbitmqctl list_queues name messages messages_ready \
  messages_unacknowledged consumers memory

# 连接状态
rabbitmqctl list_connections name peer_host channels state

# 节点内存分析
rabbitmqctl status | grep -A 20 memory

# 管理 API (REST)
curl -s http://localhost:15672/api/queues/%2F/ | python -m json.tool
```

**推荐监控架构：**

```
  ┌───────────────────────────────────────────┐
  │           Prometheus + Grafana            │
  │                                           │
  │  rabbitmq_queues_messages                 │
  │  rabbitmq_queues_memory                   │
  │  rabbitmq_node_memory_used               │
  │  rabbitmq_disk_free_alarm                │
  │  rabbitmq_connections                    │
  └───────────────────────────────────────────┘
                      │
        rabbitmq_prometheus 插件 (3.8+)
                      │
              ┌───────┴───────┐
              │               │
          ┌───▼───┐      ┌───▼───┐
          │ Node A│      │ Node B│
          │:15692 │      │:15692 │
          └───────┘      └───────┘
```

### 8.2 常见故障排查

#### 故障一：脑裂 (Split-Brain)

```
症状:
  rabbitmqctl cluster_status 显示部分节点看不到对方
  部分 Queue 在主节点不可访问
  镜像队列出现多个 Master

诊断:
  # 检查 Erlang cookie 一致性
  # 检查节点间网络连通性
  rabbitmqctl cluster_status

  # 查看网络分区信息 (3.8+)
  rabbitmqctl eval 'maps:keys(ra_system:clusters()).'

  # 检查 Net tick time
  rabbitmqctl eval 'net_kernel:get_net_ticktime().'

  # 查看日志
  # %AppData%/RabbitMQ/log/ - Windows
  # /var/log/rabbitmq/ - Linux

恢复:
  # 方案 1: 重启分区节点自动恢复 (如果启用了 autoheal)
  rabbitmqctl stop_app
  rabbitmqctl reset       # 警告: 会清除数据!
  rabbitmqctl start_app

  # 方案 2: 停止所有节点，选择数据最新的节点启动
  # 然后逐个加入

预防:
  # 启用 partition handling
  # rabbitmq.conf:
  cluster_partition_handling = autoheal
  # 或 pause_minority / pause_if_all_down
```

#### 故障二：消息积压

```
症状:
  队列深度持续增长
  消费者延迟显著
  可能触发内存告警

诊断步骤:
  Step 1: 确认积压规模和增长趋势
    rabbitmqctl list_queues name messages messages_ready \
      messages_unacknowledged consumers memory

  Step 2: 检查消费者状态
    rabbitmqctl list_consumers queue_name channel consumer_tag ack_required

  Step 3: 确认消费者处理能力
    查看 deliver_get_rate vs ack_rate
    如果 ack_rate < deliver_rate → 消费者处理慢
    如果 deliver_rate = 0 → 消费者未连接

  Step 4: 检查是否有消息被 requeue
    redeliver_rate 高 → 消费者可能 nack 或异常断连

处理:
  # 紧急: 启用 Lazy Queue 临时策略
  rabbitmqctl set_policy urgent-lazy ".*" '{"queue-mode":"lazy"}' --priority 100

  # 扩容消费者

  # 检查消费者逻辑 (是否有死循环、慢 SQL、I/O 瓶颈)
```

#### 故障三：内存水位告警

```
症状:
  生产者连接状态显示 "blocked"
  管理界面显示 Memory Alarm
  新消息发布被阻塞

诊断:
  # 查看内存使用分布
  rabbitmqctl status | grep -A 50 memory

  # 输出示例:
  # total: 1.2GB
  # connection_readers: 200MB
  # connection_writers: 150MB
  # connection_channels: 300MB
  # connection_other: 50MB
  # queue_procs: 400MB   ← 队列进程内存
  # queue_slave_procs: 0
  # plugins: 10MB
  # other_proc: 50MB
  # metrics: 5MB
  # mgmt_db: 15MB
  # mnesia: 20MB
  # other_ets: 10MB
  # binary: 80MB
  # code: 50MB
  # atom: 5MB
  # other_system: 20MB
  # allocated_unused: 50MB
  # reserved_unallocated: 100MB

  # 检查队列级别内存
  rabbitmqctl list_queues name messages memory

处理:
  # 1. 增加消费者加快消费
  # 2. 动态提升水位线 (临时方案, 不推荐长期)
  rabbitmqctl set_vm_memory_high_watermark 0.6

  # 3. 如果有大量短连接: 检查连接配置
  # 4. 如果 binary 内存高: 检查大消息
  # 5. 长期: 扩容节点 / 使用 Lazy Queue / 评估是否需优化架构
```

### 8.3 优雅升级与滚动重启策略

```
RabbitMQ 集群滚动升级流程:

  ┌──────────────────────────────────────────────────────┐
  │           3-node Cluster Rolling Upgrade             │
  │                                                      │
  │  Step 1: 停止 Node C                                 │
  │  ┌─────────┐  ┌─────────┐  ┌─────────┐              │
  │  │ Node A  │  │ Node B  │  │ Node C  │ (offline)    │
  │  │ (Master)│  │ (Master)│  │         │              │
  │  └─────────┘  └─────────┘  └─────────┘              │
  │                                                      │
  │  Step 2: 升级 Node C 软件                            │
  │  Step 3: 启动 Node C (自动加入集群)                    │
  │                                                      │
  │  Step 4: 等待 Node C 同步完成                         │
  │  Step 5: 重复 Step 1-4 对 Node B                     │
  │  Step 6: 重复 Step 1-4 对 Node A                     │
  │                                                      │
  │  总时长: (stop + upgrade + start + sync) × 3        │
  └──────────────────────────────────────────────────────┘

停止节点的操作:

  # 第 1 步: 暂停客户端连接
  rabbitmqctl eval 'rabbit_connection:block_all().'

  # 第 2 步: 等待正在处理的消息完成
  # (观察队列深度归零或预估值)

  # 第 3 步: 优雅关闭
  rabbitmqctl stop_app

升级后的验证:

  # 1. 检查集群状态
  rabbitmqctl cluster_status

  # 2. 确认所有 Queue 状态正常
  rabbitmqctl list_queues name node pid

  # 3. 执行功能性验证
  rabbitmqctl eval 'rabbitmq:alarm_test().'

  # 4. 恢复客户端连接
```

**升级注意事项：**

| 阶段 | 注意事项 |
|------|---------|
| **升级前** | 确认当前版本和目标版本的元数据兼容性；备份数据库 (`rabbitmqctl backup /tmp/backup`)；确认所有节点磁盘足够 |
| **升级中** | 保持多数节点存活（Quorum Queue 需要多数派）；避免跨大版本升级（建议逐版本升级） |
| **升级后** | 检查插件兼容性；验证 Federation/Shovel 连接；监控 GC 和内存使用变化 |

### 高频面试题 (Section 8)

**Q: RabbitMQ 集群出现网络分区后，应该如何处理？**

A: 处理策略：(1) 配置 `cluster_partition_handling = autoheal` 让集群自动恢复（推荐默认配置）；(2) 如果配置了 `pause_minority`，少数派节点会自动暂停，分区恢复后自动启动；(3) 如果已出现脑裂且无法自愈，手动恢复步骤：停止所有节点 → 选择数据最新的节点启动 → 其他节点 `reset` 后加入。关键是确保 `reset` 前确认选择正确的主节点，避免数据丢失。

**Q: RabbitMQ 节点内存持续升高不下降，但消息量不大，可能是什么原因？**

A: (1) **未确认消息**：消费者卡住导致 unacked 消息积压，检查 consumer 是否 ack；(2) **Erlang 内存碎片**：长时间运行后 Erlang VM 虚拟内存碎片化，重启可释放；(3) **binary 引用泄漏**：大消息处理不当导致二进制引用无法释放，检查是否在消息处理中持有引用；(4) **指标收集内存**：`rabbitmq_management` 插件缓存的指标数据（默认保留最近的所有指标），可通过 `management_metrics_sample_retention_time` 限制。

**Q: 如何在不重启 RabbitMQ 的情况下动态调整内存水位？**

A: 使用 `rabbitmqctl set_vm_memory_high_watermark <fraction>` 动态调整。示例：`rabbitmqctl set_vm_memory_high_watermark 0.6` 将阈值从 40% 提升到 60%。注意：阈值提升会增加 OOM 风险，因为 Erlang VM 的 GC 策略依赖此阈值。需要结合业务实际情况权衡。更好的长期方案是优化消费者能力和减少积压。

---

## 附录

### A. 核心 Erlang 模块速查

| 模块 | 职责 | 关键函数 |
|------|------|---------|
| `rabbit_channel` | Channel 进程 | `handle_method/3`, `do_flow/4` |
| `rabbit_amqqueue_process` | Queue 进程 | `handle_cast/2`, `handle_info/2` |
| `rabbit_exchange_type_direct` | Direct 路由 | `route/2` |
| `rabbit_exchange_type_topic` | Topic 路由 | `route/2`, `topic_match/2` |
| `rabbit_exchange_type_fanout` | Fanout 路由 | `route/2` |
| `rabbit_credit_flow` | Credit 流控 | `send/1`, `return/1`, `block/1` |
| `rabbit_alarm` | 内存/磁盘告警 | `set_or_clear_alarm/1` |
| `rabbit_mirror_queue_master` | 镜像队列 Master | `handle_down/2` |
| `rabbit_federation_link` | Federation 连接 | `start_link/6` |
| `rabbit_msg_store` | 消息存储 | `write/2`, `read/2`, `sync/1` |
| `rabbit_queue_index` | 队列索引 | `publish/3`, `ack/2`, `out/2` |

### B. 常用诊断命令速查

```bash
# 集群状态
rabbitmqctl cluster_status

# 队列详情
rabbitmqctl list_queues name messages messages_ready messages_unacknowledged consumers memory slave_nodes

# 连接详情
rabbitmqctl list_connections name peer_host channels state user

# Channel 详情
rabbitmqctl list_channels connection consumer_count messages_unconfirmed

# 内存分析
rabbitmqctl status | grep -A 50 memory

# 环境变量
rabbitmqctl environment

# 评估 Erlang 表达式
rabbitmqctl eval 'rabbitmq:alarm_test().'
rabbitmqctl eval 'rabbit_amqqueue:list("").'

# 动态设置
rabbitmqctl set_vm_memory_high_watermark 0.5
rabbitmqctl set_disk_free_limit 2GB
```

### C. RabbitMQ 版本特性时间线

| 版本 | 发布时间 | 关键特性 |
|------|---------|---------|
| 3.0 | 2012 | 完全重写消息存储, 分离索引和消息体 |
| 3.3 | 2013 | 镜像队列 GM 协议优化 |
| 3.6 | 2015 | Lazy Queue, 延迟交换机插件 |
| 3.7 | 2017 | 新版内部架构, 插件系统重构 |
| 3.8 | 2019 | **Quorum Queue** (Raft), 新版磁盘使用告警 |
| 3.9 | 2021 | **RabbitMQ Stream** (不同于 AMQP 的新协议) |
| 3.10 | 2022 | 流过滤, Super Stream (分区) |
| 3.12 | 2023 | 默认激活 Quorum Queue, 镜像队列弃用警告 |
| 3.13 | 2024 | 更多 Stream 增强, 经典队列进一步弃用 |
| 4.0 | 待发布 | 计划移除经典队列镜像模块 |

---

> **本文深入程度说明：** 本文涉及的源码路径基于 RabbitMQ 3.8-3.12 版本。RabbitMQ 版本迭代频繁，部分源码细节可能随版本变化，核心概念和协议层保持不变。建议配合实际版本的源码阅读以获取最新实现细节。
