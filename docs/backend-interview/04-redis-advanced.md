# 高级 Redis 面试知识架构

> 本文面向资深后端工程师 / 架构师岗位（5-8 年经验），从源码原理到生产调优，系统梳理 Redis 核心知识体系。每个维度包含高频面试题、生产踩坑经验、最佳实践三要素。

---

## 目录

1. [数据结构深度](#1-数据结构深度)
2. [核心原理](#2-核心原理)
3. [高可用架构](#3-高可用架构)
4. [缓存设计](#4-缓存设计)
5. [分布式场景](#5-分布式场景)
6. [性能调优](#6-性能调优)
7. [生产运维](#7-生产运维)
8. [大厂真题与综合案例](#8-大厂真题与综合案例)

---

## 1. 数据结构深度

### 1.1 底层编码演进

Redis 5 种基础类型（String / Hash / List / Set / ZSet）并非总是使用固定的数据结构，而是根据元素数量和元素大小自动切换内部编码，目的是在内存占用和操作性能之间取得最佳平衡。

| 类型 | 内部编码 | 切换条件 | 版本变化 |
|------|----------|----------|----------|
| String | **int** / **embstr** (<=44B) / **raw** (>44B) | 所有元素可转为整数则用 int；长度 <=44 用 embstr（一次分配，更快） | 3.2 前阈值 39B，因 sdshdr 结构调整 |
| Hash | **ziplist** / **hashtable** (dict) | `hash-max-ziplist-entries 512` 且 `hash-max-ziplist-value 64` | 7.0 后 ziplist 被 **listpack** 替代，解决级联更新问题 |
| List | **quicklist**（ziplist 链表） | 3.2 前是 ziplist / linkedlist；3.2 引入 quicklist | 7.0 后使用 **listpack** 作为 quicklist 节点 |
| Set | **intset** / **hashtable** (dict) | 所有元素可转为整数且数量 <= `set-max-intset-entries 512` | 无重大变化 |
| ZSet | **ziplist** / **skiplist+dict** | `zset-max-ziplist-entries 128` 且 `zset-max-ziplist-value 64` | 7.0 后 ziplist -> listpack |

**面试高频题：**

- **Q：ziplist 为什么有级联更新问题？7.0 如何解决？**
  - ziplist 每个 entry 保存前一个 entry 的长度（prevlen）。当插入/删除导致某个 entry 长度变化，后续所有 entry 的 prevlen 都需要更新 —— 最坏 O(N^2)。7.0 后用 listpack 替代，每个 entry 只保存自己的长度，不依赖前驱，从根本上消除了级联更新。
- **Q：ziplist 和 listpack 的内存对比？**
  - listpack 在紧凑性上与 ziplist 相当，但取消了级联更新，写入性能更稳定。典型场景下内存开销差异小于 5%。
- **Q：skiplist 为什么用于 ZSet 而非平衡树？**
  - 跳表实现简单，区间查询效率高（`ZRANGE`），范围锁开销低。平衡树的旋转和重平衡操作复杂，跳表通过概率平衡（O(logN)）即可达到相近性能。

**生产踩坑：**

- **ziplist 过大导致写延迟突增**：曾遇到 Hash 类型单 field 不断增长超过 64B 阈值，触发 ziplist -> hashtable 转换，导致毫秒级毛刺。解决：监控 `hash-max-ziplist-value` 命中情况，对大 value 提前拆分。
- **intset 升级放大内存**：Set 中插入一个非整数元素（如字符串），intset 原地升级为 hashtable，内存膨胀 3-5 倍。生产建议对纯数字集合与字符串集合分开存储。

**最佳实践：**
- 预估数据特征，自定义编码阈值：读多写少的集合可适当放大 ziplist/listpack 阈值；高频写入场景保持小阈值以减少转换开销。
- 使用 `DEBUG OBJECT key` 或 `OBJECT ENCODING key` 检查内部编码。

---

### 1.1.1 String — 底层结构与业务优化

**底层结构：SDS（Simple Dynamic String）**

Redis 自定义字符串，不使用 C 原生字符数组。SDS 在头部记录 len（已用长度）和 alloc（分配容量），字符串操作 O(1) 获取长度，且二进制安全（允许存 `\0`）。

```
SDS 内存布局（sdshdr8 示例）:
┌──────┬────────┬─────┬───────────────────────┐
│ len  │  alloc │flags│       buf[]           │
│ uint8│  uint8 │     │  实际内容 + \0         │
└──────┴────────┴─────┴───────────────────────┘
```

**三种内部编码：**

| 编码 | 触发条件 | 内存特点 |
|------|---------|---------|
| `int` | 值为整数且 ≤ LONG_MAX | 直接用 ptr 存整数值，不分配 SDS，最省内存 |
| `embstr` | 字符串 ≤ 44B | RedisObject + SDS 一次连续分配，一次 free，缓存友好 |
| `raw` | 字符串 > 44B | RedisObject 和 SDS 分开分配，修改不受限 |

> **注意**：embstr 是只读的——任何修改操作（APPEND 等）都会先将 embstr 转换为 raw 再操作。

**业务场景与优化思路：**

```
场景                     命令                      优化要点
─────────────────────────────────────────────────────────────
缓存 JSON 对象           SET key value EX 3600     value > 10KB 用 Hash 拆分存储
计数器（PV/库存）        INCR / INCRBY             int 编码原地操作，无内存分配
分布式锁                 SET key uuid NX EX 30     uuid 防止误删，Lua 保原子释放
Session 存储             SET sid data EX 1800      滑动过期用 EXPIRE 重置
限流（固定窗口）         INCR key; EXPIRE key 1s   配合 Pipeline 减少 RTT
```

**生产注意：**
- 单个 String value 超过 10KB 开始影响网络传输和序列化耗时，超过 1MB 会阻塞主线程，建议大对象拆成 Hash 或使用 Hash 压缩存储。
- `APPEND` 命令频繁调用会触发 SDS 预分配扩容，内存浪费；日志聚合场景建议用 List/Stream 替代。

---

### 1.1.2 Hash — 底层结构与业务优化

**底层结构：ziplist/listpack → hashtable（dict）**

**ziplist/listpack（元素少时）：**
内存连续的紧凑数组，entry 顺序存储 field 和 value，遍历需线性扫描（O(N)），但内存极省，无指针开销。

```
listpack 内存布局:
┌──────────┬──────┬─────────┬──────┬─────────┬─────┐
│ total_len│ size │ entry1  │ size │ entry2  │ end │
└──────────┴──────┴─────────┴──────┴─────────┴─────┘
每个 entry 自含长度，无级联更新
```

**hashtable（dict，元素多时）：**
两个哈希表（ht[0]、ht[1]）结构，rehash 时渐进式迁移。每个 bucket 是链表（链式哈希），O(1) 查找。

**业务场景与优化思路：**

```
场景                   命令                    优化要点
─────────────────────────────────────────────────────────────
用户信息对象           HSET uid name xxx       控制 field 数 ≤ 512 保持 listpack
购物车                 HINCRBY cart pid qty    field = product_id，天然防并发
商品详情（多属性）     HMSET / HMGET           批量读写替代多次 GET
配置中心（少量KV）     HGETALL config          HGETALL 在 listpack 时极快（内存顺序读）
计数聚合（多维指标）   HINCRBY stat field 1    单 key 聚合多个计数，减少 key 数量
```

**生产注意：**
- `HGETALL` 在 hashtable 编码时返回全量，大 Hash（field > 1000）会阻塞主线程；改用 `HSCAN` 分批读取。
- 对象序列化（JSON string 存 String）vs Hash 分字段存：Hash 允许部分更新（`HSET` 单field），String 需要全量读写，高频局部更新场景优先选 Hash。

---

### 1.1.3 List — 底层结构与业务优化

**底层结构：quicklist（ziplist/listpack 节点的双向链表）**

3.2 版本引入，融合了链表和 ziplist 的优点：每个节点是一个 ziplist（7.0 后为 listpack），节点之间双向链表连接。

```
quicklist 结构:
┌───────┐     ┌───────┐     ┌───────┐
│listpk │◄───►│listpk │◄───►│listpk │
│[a,b,c]│     │[d,e,f]│     │[g,h,i]│
└───────┘     └───────┘     └───────┘
 每节点紧凑内存    ←→ 节点间双向指针
```

- `list-max-listpack-size`：每节点存的 entry 数量上限（默认 128）
- `list-compress-depth`：两端节点不压缩（热数据），中间节点 LZF 压缩（省内存）

**业务场景与优化思路：**

```
场景                    命令                      优化要点
──────────────────────────────────────────────────────────────
消息队列（简单）        LPUSH + BRPOP             BRPOP 阻塞弹出，无消息不空轮询
最近浏览记录（TopN）    LPUSH + LTRIM 0 N-1       写入后立即 LTRIM 控制长度
时间线（Feed 流）       LPUSH + LRANGE 0 9        分页用 LRANGE，避免一次返回全量
栈（LIFO）              LPUSH + LPOP              同端进出
队列（FIFO）            LPUSH + RPOP              两端分离
```

**生产注意：**
- List 不支持随机访问，`LINDEX` 是 O(N)，避免用 List 做"按下标取元素"的场景，改用 ZSet（score 为 index）。
- 消息队列场景 List 没有 ACK 机制，消费崩溃消息丢失；需要可靠消费用 `BRPOPLPUSH`（备份队列）或直接用 Stream。

---

### 1.1.4 Set — 底层结构与业务优化

**底层结构：intset → hashtable（dict）**

**intset（全整数元素且数量少时）：**
有序整数数组，二分搜索查找 O(logN)，内存极省（无 hash 开销）。升级时从 int16 → int32 → int64 自动扩展。

```
intset 结构:
┌──────────┬───────┬─────────────────────────────┐
│ encoding │ length│  contents[] (有序整数数组)   │
└──────────┴───────┴─────────────────────────────┘
```

**hashtable（dict，含字符串或元素超限时）：**
与 Hash 的 dict 相同结构，field 存 member，value 为 NULL，O(1) 查找/添加/删除。

**业务场景与优化思路：**

```
场景                     命令                         优化要点
───────────────────────────────────────────────────────────────
标签系统                 SADD / SMEMBERS              纯整数 tag_id → intset 极省内存
好友关系（共同好友）     SINTER uid1:friends uid2:fr  两个 Set 求交集
抽奖（不重复）           SRANDMEMBER count / SPOP     SRANDMEMBER 不移除，SPOP 移除
UV 去重（中小量）        SADD + SCARD                 大量 UV 用 HyperLogLog
权限集合                 SISMEMBER role:admin uid     O(1) 判断是否有权限
```

**生产注意：**
- `SMEMBERS` 返回全量集合，大 Set（> 1万）会阻塞；改用 `SSCAN` 分批。
- 插入一个非整数到 intset，立即触发升级为 hashtable，内存膨胀 3-5x；混合类型 Set 上线前确认编码。
- 集合运算（SINTER / SUNION / SDIFF）结果集很大时，用 `SINTERSTORE` 存到新 key 异步处理，避免一次性返回大结果。

---

### 1.1.5 ZSet — 底层结构与业务优化

**底层结构：ziplist/listpack → skiplist + dict**

**skiplist（跳表）原理：**
多层有序链表，底层是完整有序数据，上层是"快速通道"（概率跳过）。期望层数 O(logN)，范围查询 O(logN+M)。

```
level 3:  1 ─────────────────────────► 9
level 2:  1 ──────────► 5 ──────────► 9
level 1:  1 ──► 2 ──► 5 ──► 7 ──► 9
data:    [1]  [2]  [5]  [7]  [9]     ← 每个节点存 member + score
```

**为什么同时用 skiplist + dict 两种结构？**

| 操作 | 依赖结构 | 复杂度 |
|------|---------|--------|
| `ZRANK` / `ZSCORE`（按 member 查 score） | dict | O(1) |
| `ZRANGE` / `ZRANGEBYSCORE`（按 score 范围查） | skiplist | O(logN+M) |
| `ZADD` | 两者同时更新 | O(logN) |

> 用 dict 换取 O(1) 点查，用 skiplist 换取 O(logN) 范围查，内存多用一倍但查询全面。

**业务场景与优化思路：**

```
场景                     命令                          优化要点
────────────────────────────────────────────────────────────────
实时排行榜               ZADD + ZREVRANK + ZREVRANGE   分页：ZREVRANGE rank 0 9
延迟队列                 ZADD key timestamp task        ZRANGEBYSCORE 0 now 扫到期任务
带权重优先级队列         ZADD + ZPOPMIN（7.0+）         score 越小优先级越高
时间线分页               ZADD key time member           ZREVRANGEBYSCORE + LIMIT 游标翻页
滑动窗口限流             ZADD + ZREMRANGEBYSCORE + ZCARD 删过期成员再统计窗口内数量
```

**生产注意：**
- `ZRANGE` 在 7.0 前只能升序，降序要用 `ZREVRANGE`；7.0 后 `ZRANGE` 支持 `REV` 参数统一两者。
- 大范围 `ZRANGEBYSCORE` 返回百万条时阻塞主线程；用 `LIMIT offset count` 分页或 `ZSCAN` 遍历。
- 排行榜榜单超大（千万级成员），考虑按 score 分段存多个 ZSet，查询时先定位段再范围查。

---

**五大类型底层结构速查：**

```
┌────────┬──────────────────────┬────────────────────────────┐
│ 类型   │ 小数据量编码          │ 大数据量编码               │
├────────┼──────────────────────┼────────────────────────────┤
│ String │ int / embstr         │ raw (SDS)                  │
│ Hash   │ listpack             │ hashtable (dict)           │
│ List   │ quicklist (listpack) │ quicklist (listpack+压缩)  │
│ Set    │ intset               │ hashtable (dict)           │
│ ZSet   │ listpack             │ skiplist + dict            │
└────────┴──────────────────────┴────────────────────────────┘
切换阈值统一由 redis.conf 中 *-max-listpack-entries / *-max-listpack-value 控制
```

### 1.2 BitMap

基于 String 类型（最大 512MB）的位操作，适合海量布尔型状态存储。

**原理：** 每个 bit 表示一个二元状态，通过 `SETBIT`/`GETBIT`/`BITCOUNT`/`BITOP` 操作。

**生产案例：** 用户签到（1 亿用户年签到）、日活统计（每个 offset 为 user_id）。

**高频面试题：**

- **Q：1 亿用户的日活跃如何用 BitMap 实现？内存占用？**
  - 每个用户占 1 bit，1 亿用户 ≈ 12MB。设置第 id 位为 1，每日一个 key，`BITCOUNT` 得到日活。跨天 `BITOP OR` 得到周活/月活。
- **Q：BitMap 与 Set 存储活跃用户的优劣？**
  - BitMap 内存固定为 max_id/8 字节，适合 ID 密集（id 连续）。若 ID 稀疏（如用户 id 分布极散），Set 反而更省内存。选择依据：用户 ID 密度。

**踩坑：** `SETBIT` 对不存在的 key 自动扩容至所需长度。一次 SETBIT 操作最大 key offset 造成 Redis 分配 512MB 内存，引发内存暴增。始终对 offset 做上限校验。

### 1.3 HyperLogLog

用于海量数据去重计数，标准误差约 0.81%。本质是概率性数据结构。

**原理：** 将输入通过 hash 映射为 64 位二进制串，利用"最长前导零位数"估算基数。使用 16384 个桶（2^14）存储 max trailing zeros。

**高频面试题：**

- **Q：HyperLogLog 的误差来源？如何减少误差？**
  - 误差源于概率估算的随机性。减少方法：使用 `PFMERGE` 合并多个 HLL（分布式场景），对同一数据集分桶计数后合并。误差不会因数据量增大而变化，始终 ~0.81%。
- **Q：百万级 UV 统计，HyperLogLog vs BitMap vs Bloom Filter？**
  - HLL 内存固定 12KB，适合仅需要总数；BitMap 适合 id 密集且需要回滚（每天一个 key）；Bloom Filter 适合判断存在性而非计数。
- **Q：HyperLogLog 能否删除某个元素？**
  - 不能。HLL 是不可逆的概率结构。需要删除能力用 EXPIRE + 分段存储，或用 Redis Stream + TTL 分段统计。

### 1.4 GEO

基于 ZSet 实现，利用 GeoHash 编码将二维经纬度映射为一维 score（52 位整数编码）。

**原理：** 将地球划分为网格，对经纬度交替二分编码。geohash 长度决定精度，越长越精确。Redis 支持 `GEOADD`/`GEORADIUS`/`GEODIST` 等命令。

**高频面试题：**

- **Q：GEO 底层为什么用 ZSet？近距离查询精度如何保证？**
  - 基于 ZSet 做有序存储，score 为 geohash 编码。查询时通过 score 范围获取候选集，再通过球面距离公式精确过滤。精度取决于 geohash 长度，Redis 内部使用 52 位，误差约 0.3m。
- **Q：GEORADIUS 在大数据量下的性能瓶颈？**
  - 本质是 ZSet 的 `ZRANGEBYSCORE`，时间复杂度 O(logN+M)。当候选集 M 极大时，精确过滤成为瓶颈。优化：减少返回数量（COUNT 参数），或使用 GeoHash 前缀分片。

**生产踩坑：**
- `GEORADIUS` 在 Redis 6.2 后标记为过期，推荐使用 `GEORADIUS_RO`（只读副本不 trigger replication）。
- 超大数据集合（千万级 POI）的 GEO 查询需引入分片策略，单节点 ZSet 无法支撑高频写入。

### 1.5 Stream

Redis 5.0 引入的消息队列数据结构，弥补了 Pub/Sub 无持久化、List 消费确认不足的短板。

**核心概念：** Consumer Group、Consumer、Pending Entries List (PEL)、ACK、消费者偏移量。

**高频面试题：**

- **Q：Stream 和 Kafka 分区模型的异同？**
  - 两者都有消费者组概念，一个 partition 对应一个 Stream 内的 shard。Redis Stream 单分区单节点无法水平扩展，Kafka 可通过增加分区线性提升吞吐。Redis Stream 适合中小规模（万级 TPS）场景。
- **Q：PEL 无限增长怎么办？**
  - PEL 存储所有已投递但未 ACK 的消息。若消费者宕机，PEL 持续膨胀。设置 `MAXLEN` 上限或引入外部监控清理僵尸 PEL。生产建议配置消息 TTL 兜底。
- **Q：Stream vs Kafka / RabbitMQ 的选型？**
  - Stream 适用场景：轻量消息队列、无需持久化到磁盘（RDB/AOF 足够）、运维简单。对可靠性要求极高（Exactly Once、事务性）、海量 TPS 的场景选 Kafka。复杂路由（Topic 多交换机）选 RabbitMQ。

**最佳实践：**
- 消费者使用 `XREADGROUP` 时始终设置 BLOCK 时长，避免大量空轮询。
- 监控 `XINFO STREAM key` 中的 `groups` 和 `pel-count`。

---

## 2. 核心原理

### 2.1 单线程模型与 6.0+ 多线程 IO

**经典单线程模型：**

Redis 的核心命令处理（事件循环中执行命令）始终是**单线程**的。单线程意味着无需上下文切换和锁竞争，这也是 Redis 能在内存中达到微秒级延迟的根本原因。

**6.0 多线程 IO：**

| 版本 | 变化 |
|------|------|
| 6.0 | 引入多线程 IO，默认关闭 |
| 7.0 | 多线程 IO 默认开启（`io-threads 4`） |
| 7.2+ | 进一步优化 IO 线程调度 |

- **多线程 IO 做什么：** 网络 IO 读写操作由 IO 线程池并行处理（socket read/write），命令执行仍由主线程串行执行。
- **为什么不是多线程执行命令？** 保持单线程执行命令的简单性和一致性，消除锁、避免竞态。
- **配置建议：** `io-threads` 设置为 CPU 核数 - 2（留出主线程和后台线程资源），不建议超过 8。

**面试高频题：**

- **Q：6.0 多线程 IO 为什么无法线性提升吞吐？**
  - 瓶颈从网络 IO 转移到命令执行和内存操作。网络 IO 并行化后，主线程单线程执行命令成为新瓶颈。实测 4 核机器 2-3 倍吞吐提升，而非 4 倍。
- **Q：Redis 单线程能处理高并发的原因？**
  - (1) 内存操作，纳秒级耗时；(2) IO 多路复用 epoll（Linux）/ kqueue（macOS），非阻塞 IO；(3) 数据结构高效；(4) 无锁竞争；(5) 纯计算密集任务不受 IO 等待阻塞。

### 2.2 事件驱动与 epoll

Redis 基于 **Reactor 模式**实现事件驱动，核心为 **aeEventLoop**：

```
┌─────────────────────────────────────┐
│            aeEventLoop               │
│  ┌─────────┐  ┌──────────┐          │
│  │ 文件事件  │  │  时间事件  │         │
│  │(socket IO)│  │(定时任务) │         │
│  └─────────┘  └──────────┘          │
│  ┌──────────────────────────┐       │
│  │   api (epoll/kqueue/select)│      │
│  └──────────────────────────┘       │
└─────────────────────────────────────┘
```

**文件事件处理器：** 将 socket 关联到对应事件处理器（accept / read / write / close），全部非阻塞。
**时间事件：** 定期执行（`serverCron`），处理过期 key 清理、rehash 步进、持久化触发等。

**面试高频题：**

- **Q：epoll 相比 select/poll 的优势？**
  - select：fd 集合限制 1024，每次调用需将 fd 集合从用户态拷贝到内核态，O(N) 扫描。
  - poll：链表结构无上限，但仍是 O(N) 扫描。
  - epoll：事件驱动（回调机制），只返回活跃 fd，O(1) 复杂度。支持边缘触发（ET）和水平触发（LT），Redis 使用 LT（代码简单，不易丢事件）。
- **Q：Redis 为什么不用 epoll 的 ET 模式？**
  - ET 模式需循环读取直到 EAGAIN，逻辑复杂，容易遗漏数据。LT 模式配合非阻塞 IO，每次 read 后注册下次事件，足够高效。

### 2.3 持久化

#### RDB

**原理：** fork 子进程将全量数据写入临时 RDB 文件，完成后替换旧文件。

**核心机制：**
- `SAVE` / `BGSAVE` / 自动触发（`save 900 1 300 10 60 10000`）
- 写时复制（Copy-On-Write, COW）：fork 后父子进程共享内存页，子进程写 RDB，父进程修改数据页时触发复制。

**COW 内存踩坑：**
- fork 瞬间内存翻倍？错误认知。COW 只复制被修改的内存页，非全量复制。
- **实际风险：** 大量写入时父进程需复制大量内存页，导致 RSS 瞬时飙升到 2-3 倍。大实例（>20GB）的写密集型场景下，`BGSAVE` 可能触发 OOM。
  - 最佳实践：使用 `lfu-log-n` 调节写入频率，对 >30GB 实例使用从节点生成 RDB。

#### AOF

| 配置 | 写入时机 | 丢失量 | 性能 |
|------|----------|--------|------|
| appendfsync always | 每次写入 fsync | 1 条命令 | 最慢 |
| appendfsync everysec | 每秒 fsync | ≤1s 数据 | 推荐 |
| appendfsync no | 由 OS 决定 | 不定 | 最快 |

**AOF 重写：** 子进程读取当前内存生成最小命令集，期间增量变更写入 AOF 重写缓冲区，重写完成合并。

**高频面试题：**

- **Q：AOF 重写时父进程阻塞的场景是什么？**
  - fork 时阻塞（随实例大小增长），`dictRehash` 涉及的写时复制。极端场景：重写期间大量写入，导致 AOF 重写缓冲区暴增，`aof-rewrite-incremental-fsync` 刷盘慢。
- **Q：AOF 文件越来越大，如何处理？**
  - 配置 `auto-aof-rewrite-percentage 100`（较上次翻倍触发）和 `auto-aof-rewrite-min-size 64mb`。

#### 混合持久化（Redis 4.0+）

`aof-use-rdb-preamble yes`，AOF 重写时先将内存以 RDB 格式写入 AOF 文件头部，后续增量命令追加 AOF 格式。

**优势：** 重启加载更快（RDB 二进制比 AOF 逐条回放快 10-100 倍），数据安全性高于纯 RDB。

**生产踩坑：** 混合持久化导致重写时内存消耗比纯 AOF 更高（需构造 RDB 格式的键值快照）。大实例建议从节点承担持久化。

### 2.4 过期删除与内存淘汰

**过期删除策略（两阶段）：**
1. **惰性删除：** 访问 key 时检查是否过期，过期则删除（`expireIfNeeded`）。
2. **定时删除：** `serverCron` 每秒执行 10 次，每次随机抽取 20 个过期 key 删除。过期 key 比例 >25% 则重复。最多 16 轮（`activeExpireCycle`）。

**内存淘汰策略（maxmemory）：**

| 策略 | 含义 | 适用场景 |
|------|------|----------|
| noeviction | 不淘汰，返回 OOM 错误 | 纯缓存不可丢失场景（配合监控报警） |
| allkeys-lru | 所有 key 按 LRU 近似淘汰 | 通用缓存 |
| allkeys-lfu | 所有 key 按 LFU 近似淘汰 | 访问模式集中的缓存 |
| volatile-lru | 设置了 TTL 的 key 按 LRU 淘汰 | 仅淘汰有时效的 key |
| volatile-ttl | 淘汰 TTL 最短的 key | 需要精确控制过期时序 |

**LRU 近似实现：** Redis 不维护全量 LRU 链表（内存太大），而是每个 key 记录 24 bit 的 LRU 时间戳。淘汰时抽样 `maxmemory-samples` 个 key（默认 5），淘汰其中 LRU 最旧的。

**LFU 实现：** 使用近似计数器（Morris Counter），key 访问频率以对数方式增长。高频 key 的 counter 值增大（频率高），访问间隔长的 key 的 counter 衰减。

**面试高频题：**

- **Q：近似 LRU 与精确 LRU 差距多大？**
  - 官方基准：sample=10 时近似 LRU 非常接近理论 LRU；sample=5 时在多数场景下差异 <5%。更大 sample 收益递减。
- **Q：LFU 相比 LRU 在缓存场景的优势？**
  - LRU 只考虑最近一次访问时间，周期性批量扫描可能导致热点 key 被误淘汰。LFU 关注频率，对突发访问不敏感，更适合访问模式有明确热点的业务。

**生产踩坑：**
- `noeviction` 不是"永远不淘汰" —— 它意味着写满后**写入失败**。业务代码必须处理 OOM 异常。
- `allkeys-lru + 超大数据集` 导致每次淘汰触发写时复制，应提前预热 key 并设置合理 maxmemory。

---

## 3. 高可用架构

### 3.1 主从复制

#### 全量复制流程

```
1. Slave 发送 PSYNC ? -1（首次连接）
2. Master 开始 BGSAVE 生成 RDB
3. Master 将 RDB 传输给 Slave
4. Master 将复制缓冲区（repl_backlog）增量命令发送给 Slave
5. Slave 清空旧数据，加载 RDB
6. Slave 应用增量命令
```

**repl_backlog（复制积压缓冲区）：** 环形缓冲区，大小由 `repl-backlog-size` 控制（默认 1MB）。主节点将写命令同时写入 backlog，从节点断线重连时通过 `PSYNC <runid> <offset>` 尝试部分同步。若 offset 超出 backlog 范围，则触发全量复制。

**部分同步（partial resync）：** 从节点重连后，如果 offset 仍在 backlog 范围内，只需同步积压的增量数据，避免全量 RDB。

#### 无盘复制（diskless replication）

Redis 2.8 支持，`repl-diskless-sync yes`。主节点不写 RDB 到磁盘，直接通过网络 socket 发送给从节点。

**生产踩坑：**
- 主节点 RDB 生成阻塞：`BGSAVE` 消耗 CPU 和内存（COW），大实例（>50GB）期间主节点延迟升高。
- 多从节点同时全量复制：每个从节点触发一次 BGSAVE，或使用 diskless 复制时需序列化发送。大集群建议错开从节点同步时间。
- **全量复制避免方案：** (1) 增大 `repl-backlog-size` 到 512MB+；(2) 使用 Redis 4.0+ `repl-backlog-ttl` 设置长过期时间；(3) 从节点使用 `replica-serve-stale-data no` 在同步期间拒绝请求。

### 3.2 Sentinel 哨兵机制

**核心组件：**
- **Sentinel 节点：** 独立进程，监控 Master / Slave / 其他 Sentinel。
- **主观下线（SDOWN）：** 单个 Sentinel 认为某节点不可达（`down-after-milliseconds` 内无响应）。
- **客观下线（ODOWN）：** 多个 Sentinel（`quorum`）确认节点不可达。
- **Leader 选举：** 使用 Raft 算法在 Sentinel 中选举 Leader 执行故障转移。

**故障转移流程：**
```
1. Sentinel Leader 确认 Master ODOWN
2. 从 Slave 中选出新 Master（规则：优先级 replica-priority -> offset 最大 -> runid 最小）
3. Sentinel 发送 SLAVEOF NO ONE 给新 Master
4. 等待新 Master 生效
5. 其他 Slave 指向新 Master
6. 原 Master 恢复后降级为 Slave
```

**面试高频题：**

- **Q：Sentinel 宕机半数以上会怎样？**
  - Sentinel 集群需要大多数节点存活才能完成故障转移判定。半数以上宕机时，系统丧失故障转移能力，但正常运行的主从复制不受影响。需尽快恢复 Sentinel。
- **Q：脑裂场景下 Sentinel 如何处理？**
  - 网络分区导致 Sentinel 集群认为 Master 宕机，选举新 Master。分区恢复后旧 Master 以 Slave 身份上线，数据丢失（未同步的写入丢失）。**缓解方案：** `min-replicas-to-write 1` + `min-replicas-max-lag 10`，控制主节点写入可用副本最小数量。

### 3.3 Cluster 集群

#### 数据分片

Redis Cluster 使用**一致性哈希的变体 —— CRC16 哈希槽**：

- 总槽数：`16384`（2^14 个槽位）
- 公式：`slot = CRC16(key) % 16384`
- 每个节点负责一段连续的槽位范围（如 0-5460, 5461-10922, 10923-16383）

**为什么是 16384 个槽位？**
- 集群心跳消息（gossip）包含节点槽位信息。16384 个槽位的 bitmap 为 2KB，每个节点在心跳中携带该 bitmap（`CLUSTER SLOTS`）。若用 65535 个槽位则 bitmap 为 8KB，心跳包变大影响网络效率。16384 是带宽和查询精度的平衡选择。

**键的 hash tag：** `{xxx}` 内的部分作为 CRC16 的输入，确保相关 key 落入同一节点。例：`user:{123}:profile` 和 `user:{123}:orders` 都在同一节点，支持 `MGET` 等跨 key 操作。

#### 数据迁移

**槽位迁移流程：**
```
1. 在目标节点执行 CLUSTER SETSLOT <slot> IMPORTING <node-id>
2. 在源节点执行 CLUSTER SETSLOT <slot> MIGRATING <node-id>
3. 对源节点执行 MIGRATE 命令逐 key 迁移（原子操作）
4. 迁移完成后广播 SETSLOT <slot> NODE <target-node-id>
```

**面试高频题：**

- **Q：Redis Cluster 的 gossip 协议如何实现节点发现？**
  - 每个节点每秒向随机 5 个节点发送 PING，消息包含自身状态和随机 2-3 个其他节点信息。集群节点数 <1000 时收敛良好，>1000 需考虑分集群。
- **Q：Cluster 模式下的 `MGET` / Pipeline 怎么优化？**
  - 跨节点的 `MGET` 不可用（返回 `CROSSSLOT` 错误）。利用 hash tag 将相关 key 固定在同一个节点。业务上按 slot 分组发送，客户端（如 JedisCluster）会自动路由。
- **Q：Cluster 扩容如何平滑迁移数据？**
  - 新增节点后，用 `redis-cli --cluster rebalance` 触发重新分片。迁移过程不影响服务（目标节点设 importing，源节点设 migrating，MIGRATE 命令原子迁移每个 key）。

**生产踩坑：**
- **迁移期间性能下降：** MIGRATE 涉及序列化、网络传输、反序列化，大 key（>10MB）迁移阻塞单线程。建议拆分大 key 或预迁移。
- **Cluster 模式不支持多 DB（SELECT）：** db 0 是唯一可用数据库，`SELECT` 命令返回错误。
- **MGET 跨节点报错处理：** 客户端 SDK 应捕获 `MOVED`/`ASK` 重定向异常，自动重新路由。
- **最大集群节点数：** 官方建议 1000 节点以内，更多节点会导致 gossip 心跳开销过大。

### 3.4 rehash 渐进式重哈希

dict（字典）是 Redis 的核心数据结构。当 hashtable 的负载因子（used/size）超过阈值时触发 rehash：

- `load_factor > 1`（无 BGSAVE）或 `load_factor > 5`（有 BGSAVE）
- rehash 到原大小的 2 倍

**渐进式 rehash 机制：**
```
1. 分配 ht[1]，大小为 ht[0] 的 2 倍
2. 维护 rehashidx 索引（初始 -1，触发后置 0）
3. 每次增删改查操作时，将 ht[0] 中 rehashidx 位置的链表迁移到 ht[1]
4. 同时 serverCron 定时执行多步 rehash（每次 100 个桶）
5. 迁移完成后释放 ht[0]，互换 ht[0] 和 ht[1]
6. rehashidx 置为 -1
```

**高频面试题：**

- **Q：渐进式 rehash 期间如何保证数据一致性？**
  - 读操作优先查 ht[0]，未命中再查 ht[1]；写操作直接写入 ht[1]。确保数据不丢失、不重复。
- **Q：大字典 rehash 慢导致延迟抖动如何优化？**
  - 单步 rehash 的步长设置（`redis.conf` 中 `hz` 控制 serverCron 频率）。高频操作场景适当降低 hz 值（默认 10，可改为 100 加快 rehash 完成）。
- **Q：rehash 是否会引发 OOM？**
  - rehash 期间内存瞬时翻倍（ht[0] + ht[1] 共存）。大实例（>10GB）需预留至少 1.5 倍内存。使用 `ACTIVE_REHASH` 控制是否主动加速。

---

## 4. 缓存设计

### 4.1 缓存穿透

**定义：** 查询一个数据库和缓存都不存在的数据，大量请求直接打到数据库。

#### 解决方案

| 方案 | 原理 | 优点 | 缺点 |
|------|------|------|------|
| **布隆过滤器（Bloom Filter）** | 前置过滤器，不存在则直接拦截 | 精准拦截，内存高效 | 存在误判率，无法删除元素 |
| **缓存空值** | 查询到不存在数据，缓存一个空值（TTL 短，如 60s） | 实现简单 | 短时效内数据不一致，大量空 key 占内存 |
| **增强型布隆过滤器（Cuckoo Filter）** | 支持删除，低误判率 | 灵活度高 | 实现复杂，社区支持有限 |

**布隆过滤器原理：**
- 一个大的位数组 + k 个独立哈希函数
- 写入：对 key 做 k 次哈希，将对应 bit 置 1
- 查询：k 个 bit 全部为 1 则可能存在，任一为 0 则不存在
- 误判率公式：`(1 - e^(-kn/m))^k`，其中 m 为位数组长度，n 为元素个数

**生产实践：**

- **误判率设置标准：** 百万级数据，误判率 1% 约需 1.2MB（`m = - n * ln p / (ln 2)^2`）。建议设置为 0.1%-1%。
- **Bloom Filter 配合多级缓存：**
  ```
  请求 -> (1) Bloom Filter 过滤 -> (2) 本地缓存 Caffeine -> (3) Redis -> (4) DB
  ```
- **缓存空值 + 短 TTL + 异步回填**组合使用，覆盖 Bloom Filter 误判损失的业务场景。

**踩坑案例：**
- 布隆过滤器初始化时未考虑元素总数，误判率过高（>10%），大量无效请求穿透。**解决：** 准确预估数据量，动态扩容或定时重建。
- 布隆过滤器无法删除，数据变化后需要重建。**方案1：** 分段 + 过期重建。**方案2：** 改用 Cuckoo Filter。

### 4.2 缓存击穿

**定义：** 热点 key 过期瞬间，大量并发请求同时打到数据库。

#### 解决方案

| 方案 | 实现 | 适用场景 |
|------|------|----------|
| **互斥锁（Mutex Lock）** | 查询发现缓存失效，加分布式锁，第一个线程回填缓存，其余等待 | 高一致性要求 |
| **逻辑过期（Logical Expiration）** | 缓存不过期，value 内置过期时间字段，后台线程异步刷新 | 允许短暂不一致 |

**互斥锁实现（伪代码）：**
```go
lockKey := "lock:hotkey"
value, _ := rdb.Get(ctx, key).Result()
if value == "" {
    ok, _ := rdb.SetNX(ctx, lockKey, "1", 3*time.Second).Result()
    if ok {
        defer rdb.Del(ctx, lockKey)
        value = queryFromDB(key)
        rdb.Set(ctx, key, value, time.Hour)
    } else {
        time.Sleep(50 * time.Millisecond)
        value, _ = rdb.Get(ctx, key).Result() // 重试
    }
}
```

**逻辑过期实现：**
```go
// value 结构：{"data": {...}, "expire": 1700000000}
type CacheItem struct {
    Data   interface{} `json:"data"`
    Expire int64       `json:"expire"`
}

item := getCacheItem(key) // 反序列化
if item.Expire < time.Now().Unix() {
    go func() { // 后台异步刷新，不阻塞当前请求
        ok, _ := rdb.SetNX(ctx, lockKey, "1", 3*time.Second).Result()
        if ok {
            defer rdb.Del(ctx, lockKey)
            item.Data = queryFromDB(key)
            item.Expire = time.Now().Unix() + 3600
            rdb.Set(ctx, key, marshal(item), 0) // 不设TTL，由逻辑过期控制
        }
    }()
}
return item.Data // 返回旧数据（允许短暂不一致）
```

**最佳实践：**
- 对热点 key 设置**永不过期** + **定期更新**（定时任务 + 异步补偿更新）。
- 监控热点 key 的 QPS 分布，对 QPS > 5000 的 key 自动标记为热点保护对象。
- 逻辑过期方案适合首页推荐、排行榜等可接受短暂不一致的场景。
- 互斥锁方案适合交易、库存等强一致场景。

### 4.3 缓存雪崩

**定义：** 大量 key 在同一时刻过期失效，或 Redis 节点宕机，请求全部打崩数据库。

#### 解决方案

| 方案 | 描述 |
|------|------|
| **随机过期时间** | 基础过期时间 + 随机值（±30%~50%） |
| **多级缓存** | 本地缓存（Caffeine/Guava） + Redis + DB |
| **互斥锁** | 参考缓存击穿 |
| **限流降级** | Sentinel/Hystrix 对 DB 层限流，保护下游 |
| **提前预热** | 大促前主动加载缓存并分散过期时间 |

**随机过期实践：**
```go
baseTTL := 3600
jitter := rand.Intn(600) // 随机抖动 0-600s，避免同时过期
rdb.Set(ctx, key, value, time.Duration(baseTTL+jitter)*time.Second)
```

**多级缓存架构：**
```
┌──────────┐   ┌──────────┐   ┌──────────┐   ┌──────────┐
│  Client  │-->│ 本地缓存  │-->│  Redis   │-->│   DB     │
│          │   │ Caffeine  │   │  集群    │   │  MySQL   │
└──────────┘   └──────────┘   └──────────┘   └──────────┘
  TTL: 5s         TTL: 60s      TTL: 3600s
```

**高可用层面：**
- Redis 部署 Cluster 或 Sentinel 架构
- 多地域多机房容灾（异地多活）
- 使用 Proxy（Codis/Twemproxy）做连接管理和流量分发

**踩坑案例：**
- 大促活动开始时，所有商品详情页的缓存 TTL 设置相同，大量商品的 key 在活动开始后 1 小时同时过期失效，数据库 QPS 从 1k 暴增到 20k，触发连接池打满。**解决：** 过期时间增加随机抖动 + 本地缓存兜底 5s。
- Redis 节点宕机触发"缓存雪崩 + 连接风暴"：应用层大量创建新连接，导致 Redis 节点 CPU 飙升至 100%。**解决：** 客户端连接池设置合理的 maxTotal / maxIdle / minIdle，避免连接创建风暴。

### 4.4 缓存一致性

**核心问题：** 数据库写后，如何保证缓存与数据库的数据一致。

#### 常见方案对比

| 方案 | 一致性 | 复杂度 | 风险 |
|------|--------|--------|------|
| **延迟双删（Cache-Aside + 延迟删）** | 最终一致 | 低 | 删除失败 | 
| **Canal + MQ 异步刷新** | 最终一致 | 中 | 消息延迟/丢失 |
| **读写锁** | 强一致 | 高 | 性能损失大 |
| **版本号/时间戳校验** | 最终一致 | 中 | 侵入业务 |

#### 延迟双删

```
1. 删除缓存
2. 写入数据库
3. 休眠一段时间（如 500ms）
4. 再次删除缓存
```

**为什么要延迟再删？** 在并发场景下，线程 A 写入 DB 后，线程 B 可能已经读取旧数据写入缓存。延迟后再次删除确保缓存中不存在脏数据。

**延迟时间选型：** 主从同步延迟 + 业务读耗时。通常 500ms-1s，具体取决于数据库主从延迟时间。

#### Canal + MQ 方案

```
应用写 DB  -> Binlog -> Canal -> MQ -> 消费端删除/更新缓存
```

**优势：**
- 解耦业务代码，零入侵
- 可批量处理，通过 MQ 削峰填谷
- 支持按数据变更事件编排（双写、删除、预热等）

**踩坑：**
- Binlog 消费延迟导致缓存更新不及时，大促场景可能延迟秒级。**优化：** 低延迟业务配合延迟双删兜底。
- MQ 重复消费导致缓存误删。**方案：** 幂等改造（版本号递增，更新时比较版本）。

#### 方案选型矩阵

| 业务场景 | 推荐方案 | 原因 |
|----------|----------|------|
| 强一致（订单/库存） | 延迟双删 + 最终一致性补偿 | 实现简单，可靠性可控 |
| 最终一致（用户资料） | Canal + MQ | 零入侵，适合读多写多 |
| 弱一致（文章/评论） | Cache-Aside（先写 DB 再删缓存） | 简单高效，短暂不一致可接受 |
| 本地 + 远程多级缓存 | MQ 广播刷新 | 多级缓存一致性保证 |

**最佳实践：**
- **永远不要先更新缓存再写 DB：** 并发下缓存写入先于 DB，DB 失败后缓存已是脏数据，且难以回滚。
- **删除缓存比更新缓存更安全：** 更新缓存可能导致并发写覆盖（写-写冲突），删除缓存让下一次读取重新构建。
- **设置 TTL 兜底：** 即使方案失败，TTL 到期后自动恢复一致。
- **监控缓存删除成功率：** 记录每次删除操作结果，失败后发送 MQ 重试。

---

## 5. 分布式场景

### 5.1 分布式锁

#### 方案演进

| 方案 | 原理 | 生产可用性 |
|------|------|-----------|
| `SETNX + EXPIRE` | 简单原子操作 | 低（无法续期、不可重入） |
| `SET key value NX PX 30000` | Redis 官方推荐单节点锁 | 中（单点故障、无容错） |
| **RedLock** | 多节点法定数加锁 | 高（需 5 个独立节点） |
| **Redisson** | 客户端封装 + watch dog | 高（生产最广泛） |

#### RedLock 算法

**核心思想：** 在 N 个（通常 5 个）独立的 Redis 节点上获取锁，多数节点（N/2 + 1）成功才算加锁成功。

```
1. 获取当前时间戳 T1
2. 依次在 N 个节点上 SET key value NX PX (TTL)
3. 加锁的耗时 = T2 - T1
4. 若 (T2 - T1) >= TTL，视为获取失败（已超时）
5. 成功节点数 >= N/2 + 1 才算加锁成功
6. 失败时向所有节点发送解锁请求
```

**争议（Martin Kleppmann vs Antirez）：**
- Martin 质疑：RedLock 依赖时钟同步假设，在 GC pause、时钟漂移、网络分区下不安全。
- Antirez 回应：时钟漂移可通过 `CLOCK GETTIME`（NTP 的单调时钟）缓解；GC pause 属于应用层问题，建议客户端设置合理的锁超时和 walldock 补偿。
- **实际结论：** RedLock 在多数生产环境中足够安全，但对极高一致性场景（如金融交易），建议使用 ZooKeeper（ZAB 协议）或 etcd（Raft）。

#### Redisson watch dog

```
加锁 -> 后台定时任务（每 internalLockLeaseTime/3）自动续期 -> 解锁时取消
```

- 默认锁超时 30s，watch dog 每 10s 检查一次续期。
- 业务执行未完成时自动续期，避免锁提前释放导致并发问题。
- 宕机时 watch dog 消失，锁到期自动释放，避免死锁。

**高频面试题：**

- **Q：Redis 分布式锁和 ZooKeeper 锁的选型？**
  - Redis 锁：高吞吐（万级 TPS）、低延迟（毫秒级），适合缓存、用户态操作。ZooKeeper 锁：强一致（ZAB）、无超时释放难题，适合选举、配置发布。Redis 锁的最大风险是锁超时释放后业务还在执行。
- **Q：分布式锁如何实现可重入？**
  - Redisson 使用 `RSemaphore` + 线程 ID 作为 value 标识，同一个线程多次加锁仅递增计数器，解锁递减至 0 才真正释放。
- **Q：主从切换时锁丢失问题？**
  - Master 加锁成功但未同步到 Slave，Master 宕机后 Slave 升主，新客户端可成功加锁。**方案：** 改用 RedLock（多节点）或 Redisson 的 `RLock` + wait 机制要求写入多数 `WAIT`。

**生产踩坑：**
- **锁超时 + GC STW：** Java 应用 GC 停顿导致 Sentinel 超时，锁被释放。**解决：** (1) 增大锁超时时间；(2) 使用 ZGC / Shenandoah 降低停顿；\
(3) watch dog 续期间隔缩短。
- **大 key 加锁延迟：** `SET NX` 操作大 key 序列化耗时，竞争加剧。**方案：** 锁的 key 保持简短，value 可使用 UUID（无需序列化业务对象）。
- **解锁时误删其他线程的锁：** 必须校验 value 是否为本线程持有。每个线程生成唯一标识（UUID + 线程 ID），解锁时 LUA 脚本校验。

**最佳实践（go-redis + Lua 脚本实现分布式锁）：**
```go
// 加锁：SET NX PX + uuid 防误删
lockKey := "lock:order:" + orderId
token := uuid.New().String()
ok, _ := rdb.SetNX(ctx, lockKey, token, 30*time.Second).Result()
if !ok {
    // 获取锁失败处理
    return
}
defer func() {
    // 解锁：Lua 保证"校验+删除"原子性，防止误删他人的锁
    script := redis.NewScript(`
        if redis.call("get", KEYS[1]) == ARGV[1] then
            return redis.call("del", KEYS[1])
        end
        return 0
    `)
    script.Run(ctx, rdb, []string{lockKey}, token)
}()
// 业务逻辑（若需要 watchdog 续期，另起 goroutine 定期 EXPIRE）
```

### 5.2 分布式限流

#### 滑动窗口

**原理：** 基于 ZSet 实现，每个请求的 score 为当前时间戳（毫秒），通过 `ZREMRANGEBYSCORE` 移除窗口外的元素，`ZCARD` 统计窗口内请求数。

```go
func tryAcquire(ctx context.Context, rdb *redis.Client, key string, maxRequests int, windowMs int64) bool {
    now := time.Now().UnixMilli()
    windowStart := now - windowMs

    pipe := rdb.Pipeline()
    pipe.ZRemRangeByScore(ctx, key, "0", strconv.FormatInt(windowStart, 10))
    countCmd := pipe.ZCard(ctx, key)
    pipe.Exec(ctx)

    if countCmd.Val() >= int64(maxRequests) {
        return false
    }
    rdb.ZAdd(ctx, key, redis.Z{Score: float64(now), Member: uuid.New().String()})
    rdb.Expire(ctx, key, time.Duration(windowMs/1000+1)*time.Second)
    return true
}
```

**缺点：** 每个请求需要 `ZADD + ZREMRANGEBYSCORE`（O(logN)），ZSet 大小随窗口增大。

#### 令牌桶（LUA 脚本）

**原理：** 维护令牌桶容量、当前令牌数、上次填充时间。请求时消耗令牌，令牌按速率补充。

**LUA 脚本（生产级）：**
```lua
local key = KEYS[1]
local capacity = tonumber(ARGV[1])    -- 桶容量
local rate = tonumber(ARGV[2])        -- 每秒填充速率
local now = tonumber(ARGV[3])         -- 当前时间戳
local requested = tonumber(ARGV[4])   -- 请求令牌数

local lastRefillTime = redis.call('hget', key, 'lastRefillTime') or 0
local tokens = tonumber(redis.call('hget', key, 'tokens') or capacity)

-- 计算应补充的令牌数
local elapsed = math.max(0, now - lastRefillTime)
local refill = math.floor(elapsed * rate)
tokens = math.min(capacity, tokens + refill)

if tokens >= requested then
    tokens = tokens - requested
    redis.call('hset', key, 'tokens', tokens)
    redis.call('hset', key, 'lastRefillTime', now)
    redis.call('expire', key, 10)
    return 1
else
    return 0
end
```

**高频面试题：**

- **Q：滑动窗口 vs 令牌桶 vs 漏桶的选型？**
  - 滑动窗口：简单直观，适合全局 QPS 控制，无法应对突发流量。
  - 令牌桶：允许一定程度的突发流量（桶内预存了令牌），适合 Web 接口限流。
  - 漏桶：强制平滑请求速率（恒定输出），适合消息队列消费限速、流媒体等。
- **Q：分布式限流的精度要求？单机限流 vs 集中式限流？**
  - 集中式限流（基于 Redis）误差受网络延迟影响，极端场景偏差 10%+。
  - 单机限流（Guava RateLimiter / 本地计数器）延迟低零误差。
  - 推荐：**两层限流** —— 网关层集中式（兜底）+ 服务层本地（精准）。

**生产踩坑：**
- **Redis 限流在超大规模下成为瓶颈：** 单机 Redis 支撑 5-10 万 QPS 限流操作，超出需用本地限流兜底。
- **LUA 脚本超时：** 复杂限流 LUA 执行耗时 > 5ms 会阻塞其他命令。建议脚本控制在 10 条指令内。
- **时间回拨：** 服务器 NTP 时间回拨导致令牌桶填充异常。**方案：** 使用单调时钟代替系统时钟（`System.nanoTime()`），或客户端校验时间回拨。

### 5.3 延迟队列

#### Sorted Set 方案

**原理：** ZSet score 为执行时间戳（毫秒），轮询获取已到期的任务。

```go
// 生产者：加入延迟任务
rdb.ZAdd(ctx, "delay:queue", redis.Z{Score: float64(executeTime), Member: taskID})

// 消费者：轮询获取到期任务
for {
    now := time.Now().UnixMilli()
    tasks, _ := rdb.ZRangeByScoreWithScores(ctx, "delay:queue", &redis.ZRangeBy{
        Min: "0", Max: strconv.FormatInt(now, 10), Offset: 0, Count: 100,
    }).Result()
    for _, task := range tasks {
        if rdb.ZRem(ctx, "delay:queue", task.Member).Val() > 0 { // 抢占成功才执行
            execute(task.Member.(string))
        }
    }
    time.Sleep(100 * time.Millisecond)
}
```

**缺点：**
- 轮询效率低，空转浪费资源
- `ZREMRANGEBYSCORE` 不能保证原子消费（两个轮询可能同时获取同一元素）
- 适合小规模延迟消息（万级）

#### Stream 方案（推荐）

Redis 5.0+ 的 Stream 原生支持 `XREADGROUP` 和 `XPENDING`，更适合做可靠延迟队列。

**延迟队列实现：**
```go
// 生产者：发送到 Stream
rdb.XAdd(ctx, &redis.XAddArgs{
    Stream: "stream:orders",
    Values: map[string]interface{}{"orderId": "123", "delay": "30000"},
})

// 消费者：XREADGROUP 消费 + XACK 确认
msgs, _ := rdb.XReadGroup(ctx, &redis.XReadGroupArgs{
    Group: "order-group", Consumer: "worker-1",
    Streams: []string{"stream:orders", ">"},
    Count: 10, Block: 0,
}).Result()
// XPENDING 检查未确认消息，XCLAIM 转移超时消息
```

**生产方案对比：**

| 方案 | 吞吐 | 可靠性 | 复杂度 | 适用场景 |
|------|------|--------|--------|----------|
| ZSet 轮询 | 低 | 低 | 低 | 小规模延迟任务 |
| ZSet + LUA 脚本 | 中 | 中 | 中 | 中等规模 |
| **Stream + Consumer Group** | 高 | 高 | 中 | 推荐生产方案 |
| Redisson RDelayedQueue | 中 | 高 | 低 | Java 生态快速集成 |

**踩坑案例：**
- ZSet 延迟队列在任务积压时 score 范围查询导致 O(N) 扫描，造成 Redis CPU 飙升。**解决：** 分桶存储（按小时拆分 ZSet），到期前合并查询。改用 Stream 方案彻底解决。
- Redis 宕机导致未消费延迟消息丢失。**方案：** 开启 AOF + everysec 刷盘 + 消息消费后写 DB 做持久化。

---

## 6. 性能调优

### 6.1 Bigkey 排查与拆分

**定义：**
- String 类型 > 10KB
- 集合类型元素个数 > 5000（Hash/List/Set/ZSet）

**排查方法：**

| 方法 | 命令/工具 | 说明 |
|------|-----------|------|
| 手动检查 | `DEBUG OBJECT key` / `STRLEN key` / `HLEN key` | 依次检查，不可自动化 |
| **--bigkeys** | `redis-cli --bigkeys` | 扫描全库，输出每种类型最大 key 和整体分布 |
| **memory usage** | `MEMORY USAGE key` | 精确计算 key 内存占用（4.0+） |
| RDB 分析 | **redis-rdb-tools** | 解析 RDB 文件，离线分析所有 key 大小 |
| **redis-rdb-cli** | `rdb-cli dump --parser memory` | 开源的 RDB 分析工具，输出 CSV |

**拆分策略：**

| 类型 | 拆分方向 | 实现 |
|------|----------|------|
| String 大 value | 压缩 / 分片 | Snappy/Zstd 压缩后存储；或按业务字段拆分多个 key |
| Hash 大集合 | 哈希分片 | `key:{fieldHash % 100}` 拆分到多个 Hash |
| List/Set/ZSet | 分桶 | 按区间/分片拆分，如 `comments:post:123:page:1` |
| Sorted Set | 分时间片 | 按小时/天拆分，查询时 `ZUNIONSTORE` 合并 |

**生产案例：**
- 用户好友列表存储为单个 Sorted Set，包含 10 万+ 元素。`ZRANGE` 导致 Redis 线程阻塞 200ms。**解决：** 按活跃度 / 关系类型分桶，页层面做分页展示。
- JSON 数据直接存 String Value（50KB+），业务只更新其中 1 个字段。**解决：** Hash 结构存储，每个字段独立操作。

### 6.2 Hotkey 发现与处理

**定义：** 访问频率极高（单 key QPS > 10 万）的 key，导致对应 Redis 节点 CPU 成为瓶颈。

#### 发现方法

| 方法 | 优缺点 |
|------|--------|
| `redis-cli --hotkeys` | 基于 LFU 计数器，4.0+ 支持，扫描全库开销大 |
| `MONITOR` 命令采样 | 不推荐生产使用（高并发下放大流量 10x） |
| **客户端统计** | 拦截 Jedis/Redisson 调用，本地聚合热 key 访问频次 | 
| **代理层统计** | Twemproxy/Codis/Redis Proxy 层记录 |
| **Redis 节点 CPU 监控** | 结合 INFO commandstats 统计最耗时命令 |

**生产最佳方案：** 客户端拦截（Jedis 扩展 / Redisson Netty 拦截器）+ 本地 LRU 缓存热点 key 频率，定时上报到聚合服务。

#### 处理策略

| 场景 | 方案 | 说明 |
|------|------|------|
| 单个 key 读热点 | **本地缓存** | Caffeine/Guava 本地缓存热点 key，缩短路径 |
| 单个 key 写热点 | **key 打散** | key 加随机后缀 `hotkey_{0..N}`，分散到不同节点 |
| 列表型热点 | **分片读取** | 拆分数据，减少单次读取体积 |
| 接口级热点 | **限流熔断** | 保护下游 DB，防止热点传递 |

**踩坑案例：**
- 直播间在线人数统计使用单个 key `INCR`，QPS 20 万+ 的打散到同一个 slot 导致节点 CPU 100%。**解决：** `INCRBY` 使用多 key 聚合 + 定时汇总。
- 热搜榜 key `ZINCRBY` 千万级并发写入，skiplist 更新负载极高。**解决：** 写操作异步化（MQ 削峰），批量合并后写入。

### 6.3 慢查询监控

**慢查询配置：**
- `slowlog-log-slower-than 10000`（单位微秒，默认 10ms，建议 1ms）
- `slowlog-max-len 128`（队列长度）

**命令：**
```bash
SLOWLOG GET 10         # 查看最近 10 条慢查询
SLOWLOG LEN            # 当前慢查询总数
SLOWLOG RESET          # 清空
```

**常见慢查询类型：**

| 命令 | 原因 | 优化方案 |
|------|------|----------|
| `KEYS *` | **绝对禁止**，全量扫描 O(N) | 使用 SCAN 替代 |
| `SMEMBERS` | 大 Set 全量返回 O(N) | SSCAN 或分页 |
| `HGETALL` | Hash 元素过多 | HSCAN 或按 field 获取 |
| `ZRANGE` | 大 ZSet 全量查询 | 限制返回范围 |
| `LRANGE key 0 -1` | List 全量读取 | 限制 start/stop |
| `SORT` | 复杂排序，可能产生临时内存 | 业务层排序 |
| `FLUSHALL/FLUSHDB` | 全库清除 | 确认操作必要性 |
| `MGET` 批大量 key | 批量命令阻塞 | 控制单批数量 ≤100 |

**监控体系：**
```
慢查询日志 -> 采集（ELK/Prometheus） -> 告警 -> 归因
```
- 慢查询阈值的设置技巧：将 `slowlog-log-slower-than` 设在 1ms，配合 Grafana 看板展示慢查询分布。
- 重点监控峰值期慢查询数量突增。

### 6.4 Pipeline 批量操作

**原理：** 客户端将多条命令打包一次性发送，Redis 处理后批量返回，减少网络 RTT。

**性能提升：** 不使用 Pipeline 的 N 次请求 = N 次 RTT；Pipeline 批量发送 = 1 次 RTT + 一次处理。实测网络延迟 1ms 时，1000 条命令使用 Pipeline 提升约 80-100 倍。

**面试高频题：**

- **Q：Pipeline 和事务（MULTI/EXEC）的区别？**
  - Pipeline 只做批量发送，每条命令独立执行，不支持原子性、无回滚。
  - 事务保证原子性（全部执行或不执行），但不保证隔离性（EXEC 时才执行）。
  - Pipeline + 事务可以结合使用：`MULTI` -> Pipeline 发送 -> `EXEC`。
- **Q：Pipeline 的最佳批次大小？**
  - 建议 50-200 条命令/批。批次过小（<10）：收益不明显；批次过大（>1000）：内存占用大、单次处理时间过长阻塞其他客户端。
- **Q：Pipeline 在 Cluster 模式下的注意事项？**
  - 所有 key 必须在同一节点（hash slot）。跨节点的 Pipeline 需客户端分片器先分组，每个节点一个连接发送。

**踩坑案例：**
- Pipeline 批量插入时未控制批次大小，单次 5000+ 命令导致 Redis 输入缓冲区膨胀至 500MB，触发 `client-output-buffer-limit` 断开连接。
- Pipeline 中某个命令报错：客户端 SDK 返回结果列表顺序与请求对应，需逐一检查，发生错误需重试剩余命令。

### 6.5 内存优化

**核心原则：** 尽量使用省内存的数据结构，合理设置编码参数。

#### 关键参数

```conf
# 编码阈值
hash-max-listpack-entries 512
hash-max-listpack-value 64
zset-max-listpack-entries 128
zset-max-listpack-value 64
set-max-intset-entries 512

# 淘汰策略
maxmemory 4gb
maxmemory-policy allkeys-lfu

# 内存管理
activedefrag yes
active-defrag-threshold-lower 10
active-defrag-threshold-upper 100
active-defrag-ignore-bytes 100mb
active-defrag-cycle-min 25
active-defrag-cycle-max 75
```

#### 优化策略

| 优化方向 | 具体做法 | 收益 |
|----------|----------|------|
| **散列压缩** | 用 Hash 替代 String 存储多个字段 | 存储大量小对象时节省 30%-50% 内存 |
| **整数集合** | 尽量使用整数 ID | ZSet 的 double score、Set 的 int 自编码 |
| **共享对象** | 小整数复用（0-9999 默认共享） | 减少内存碎片 |
| **过期清理** | 及时设置 TTL，`ACTIVE_EXPIRE_CYCLE` | 防止过期 key 占用 |
| **数据压缩** | 大文本 Snappy / Zstd / LZ4 压缩后存 | 压缩比 2-5x，CPU 换内存 |
| **禁用持久化** | 缓存场景关闭 RDB/AOF | 省去 fork 和写盘内存开销 |

#### 生产内存踩坑

- **内存碎片：** 高频增删场景下内存碎片率（`INFO memory` 中 `mem_fragmentation_ratio`）>1.5。**方案：** 启用 `activedefrag`（4.0+），或在低峰期执行 `MEMORY PURGE`。
- **Hash 字段过多导致内存膨胀：** 一个 Hash 中 5000+ field 时 listpack 转 hashtable，内存翻倍。**方案：** 限制单 Hash field 数量，垂直拆分。
- **大 key 删除阻塞：** `DEL` 大 key（数百万元素）阻塞主线程秒级。**方案：** 用 `UNLINK`（4.0+）异步删除，后台线程回收内存。

**内存预算公式：**
```
total_memory = sum(all_keys_size) * (1 + replication_factor + rdb_bgsave_overhead + fragmentation)
```
- replication_factor: 从节点数（如 1 主 2 从则 factor=2）
- rdb_bgsave_overhead: 大实例 1.2-1.5x（COW）
- fragmentation: 1.1-1.3x（取决于增删频率）

**示例（不启用副本，COW 不算）：** 200GB 数据量，预留 260-300GB 物理内存。

---

## 7. 生产运维

### 7.1 数据迁移工具：redis-shake

**redis-shake** 是阿里云开源的 Redis 数据迁移/同步工具，支持多种场景。

| 功能 | 说明 |
|------|------|
| 全量同步 | RDB 文件传输 |
| 增量同步 | 基于 psync 或 scan + dump + restore |
| 双向同步 | 异地双活 |
| 数据过滤 | 按 key 前缀 / 正则过滤 |
| 类型过滤 | 只同步/不同步指定数据类型 |
| 限速 | `qps` 参数控制速率 |

**生产案例：**

- **Redis 版本升级**：3.2 -> 6.2，redis-shake 无损迁移，全量同步 100GB 耗时约 30 分钟，增量同步延迟 <100ms。**注意：** 先在灰度集群测试兼容性（`RESTORE` 命令可能因版本差异报错）。
- **异地容灾**：redis-shake 配置双向同步实现异地双活，注意冲突策略（后写入者覆盖 / 自定义冲突解决）。
- **迁移到云 Redis**：自建 -> 阿里云/腾讯云 Redis，redis-shake 配合云服务商提供的 `psync` 端口开放。

**施工流程：**
```
1. 部署 redis-shake 到与源 Redis 同机房（减少延迟）
2. 启动全量同步，观察 RDB 传输进度
3. 全量完成后自动进入增量同步
4. 监控增量延迟，确认延迟 < 1s 后切换
5. 业务切换到目标 Redis
6. 停掉 redis-shake，清理
```

### 7.2 监控指标

#### 核心指标矩阵

| 维度 | 指标 | 告警阈值 | 影响 |
|------|------|----------|------|
| **延迟** | `instantaneous_ops_per_sec` 响应时间 | avg > 5ms / p99 > 20ms | 业务感知 |
| **CPU** | 用户态 CPU 使用率 | > 80% | 命令处理瓶颈 |
| **内存** | `used_memory_rss` / `maxmemory` 使用率 | > 85% | 淘汰/OOM风险 |
| **连接** | `connected_clients` / `rejected_connections` | > maxclients - 100 | 连接池打满 |
| **持久化** | `rdb_last_bgsave_time_sec` / `aof_last_write_status` | RDB > 300s / AOF 失败 | 数据安全 |
| **复制** | `master_link_down_since_seconds` | > 0（即断连） | 数据不一致 |
| **内存碎片** | `mem_fragmentation_ratio` | > 1.5 或 < 1.0 | 内存浪费/Swap |

#### INFO 命令关键字段解析

```bash
# Server
redis_version:6.2.6
uptime_in_seconds:1234567

# Clients
connected_clients:256
client_longest_output_list:500        # 输出缓冲区过大告警

# Memory
used_memory:8589934592                # 8GB
used_memory_rss:12884901888           # 12GB (RSS)
mem_fragmentation_ratio:1.5
maxmemory:10737418240                 # 10GB

# Stats
instantaneous_ops_per_sec:50000
total_commands_processed:5000000000
instantaneous_input_kbps:1024         # 网络带宽

# Replication
role:master
connected_slaves:2
master_repl_offset:123456789

# Persistence
rdb_last_save_time:1700000000
aof_last_rewrite_time_sec:5
```

#### 监控方案

| 方案 | 部署方式 | 优势 |
|------|----------|------|
| **Redis-exporter + Prometheus + Grafana** | 开源主流 | 社区成熟，看板丰富 |
| **CacheCloud** | 京东开源 Redis 管理平台 | 全生命周期管理 |
| **阿里云 ARMS / 腾讯云 CM** | 云服务商 | 一键接入免运维 |

**Grafana 关键看板：**
- Redis Dashboard（官方 ID: 763 / 11835）
- Redis-p99-latency
- Redis-Top-Keys（需配合 redis-stat 或 redis-rdb-tools）

### 7.3 容灾方案

#### 单机房容灾

```
┌──────────────────┐
│   Redis Cluster  │
│  ┌────┐ ┌────┐  │
│  │ M1 │ │ M2 │  │  Master
│  │ S1 │ │ S2 │  │  Slave (同机房)
│  └────┘ └────┘  │
└──────────────────┘
```

- 主从同机房部署，Sentinel 自动故障转移
- 若使用 RDB/AOF 持久化，磁盘挂掉可重搭从节点

#### 异地容灾

| 方案 | 实现 | RPO | RTO |
|------|------|-----|-----|
| **redis-shake 异步同步** | 主-从异地同步 | 秒级 | 分钟级 |
| **CRDT（无冲突数据类型）** | 多活写 | 0 | 秒级 |
| **RDB 备份 + 恢复** | 定时备份到异地对象存储 | 1 小时 | 小时级 |

**异地容灾关键：**
- 定期恢复演练（至少每季度一次全流程验证）
- 网络延迟限制：异地同步延迟要求 < 50ms RTT（同城 2ms，跨省 30ms，跨国 100ms+）
- 写入冲突处理：异地双活必做 CRDT 改造，否则使用主备模式

#### 备份策略

```bash
# 1. 每日 RDB 全量备份
0 3 * * * redis-cli -h $HOST -p $PORT BGSAVE && \
  cp /data/redis/dump.rdb /backup/redis-$(date +\%Y\%m\%d).rdb

# 2. AOF 实时备份（可选）
# rsync /data/redis/appendonly.aof 到异地

# 3. 跨机房备份
aws s3 cp /backup/redis-*.rdb s3://redis-backup-bucket/
```

**备份验证（比备份本身更重要）：**
```bash
# 定期在测试环境恢复 RDB 并执行校验
redis-server --loadmodule /path/to/rdb-check.so /backup/redis-20260101.rdb
# 或直接在临时实例上恢复后执行一致性检查
```

### 7.4 大厂实践案例

#### 案例一：微博 --  Feed 流缓存

**背景：** 百万级活跃用户 Feed 流，每次刷新需读取关注用户的微博列表，合并排序后展示。

**方案：**
- 每个用户的 Feed 使用 Redis List（Timeline），新微博使用 `LPUSH`
- 使用 `SORT` / `LREM` 维护顺序
- 热门大 V 的 Feed 独立缓存（避免大 V 发送微博导致大量粉丝 Timeline 更新）

**踩坑：** 头部大 V 发一条微博，数万粉丝 Timeline `LPUSH` 操作导致 Redis CPU 毛刺。
**优化：** Feed 分桶（粉丝按活跃度分桶，仅推送给活跃粉丝 + 非活跃粉丝拉模式）。

#### 案例二：知乎 -- 赞同数计数

**背景：** 回答点赞数，要求高并发读写，数据最终一致。

**方案：** 
- 使用 Redis `HINCRBY` 维护计数
- 定时（每 15 分钟）通过 binlog 同步到 MySQL
- 展示时优先读取 Redis，Redis 不可用降级到 MySQL

**踩坑：** 大 V 回答点赞瞬间 QPS 10 万+，Redis 单节点 `HINCRBY` 成为瓶颈。
**优化：** 计数分片（multi-bucket counter）：`like:answer:{id}:{0..9}`，读取时 `MGET` 聚合。

#### 案例三：美团 -- 分布式会话管理

**背景：** 数亿用户会话状态在多个微服务间共享。

**方案：**
- Redis Cluster 存储 Session，使用 String 类型 `SETEX`，TTL 2 小时
- 配合本地缓存减少 Redis 读取次数
- 使用 Redis Sentinel 保障高可用

**踩坑：** Session 超大（用户信息含权限列表 100KB+）导致内存膨胀。
**优化：** 权限信息单独存储，Session 只存 userId，权限按需查询。Session 大小降至 2KB 以内。

#### 案例四：小红书 -- 缓存与 DB 一致性

**背景：** 笔记内容更新后需及时刷新缓存。

**方案：**
- 使用 Canal 订阅 MySQL Binlog
- 数据变更后 MQ 通知缓存服务
- 缓存服务根据 key 规则删除/更新对应 Redis key

**踩坑：** Binlog 消费延迟 + 并发读导致缓存写入脏数据（Canal + MQ 的经典"读旧数据写缓存"问题）。
**优化：** 写入缓存时加上版本号校验，Redis 使用 LUA 脚本检查版本，小于当前版本不写入。

---

## 8. 大厂真题与综合案例

### 真题解析

**题 1：** "公司使用 Redis 集群，某业务 Redis CPU 使用率持续 90%+，如何排查和优化？"

**排查思路：**
1. `INFO CPU` -> `INFO COMMANDSTATS` 分析哪些命令耗时最高
2. `redis-cli --hotkeys` 定位热点 key
3. `SLOWLOG GET 100` 分析慢查询
4. `MONITOR`（低峰期采样）捕捉实际执行命令
5. 检查客户端是否大量使用高复杂度命令（`KEYS`、`SMEMBERS`、`HGETALL` 等）

**优化方向：**
- 热点 key 本地缓存
- 降低命令复杂度（用 SCAN 代替 KEYS，限制返回数量）
- Pipeline 合并批量操作
- 升级 Redis 版本启用多线程 IO
- 若 CPU 由持久化引起：从节点执行 bgsave，调整 RDB 频率

---

**题 2：** "设计一个秒杀系统的库存扣减方案，要求不超卖、高性能。"

**方案：**

```lua
-- LUA: 乐观锁扣减库存
local key = KEYS[1]
local stock = tonumber(redis.call('GET', key) or 0)
if stock > 0 then
    redis.call('DECR', key)
    return 1  -- 扣减成功
else
    return 0  -- 库存不足
end
```

**架构：**
```
用户请求 -> 网关限流 -> Redis LUA 扣减库存（原子操作）-> MQ 异步 -> 订单落库
```

**要点：**
- 所有库存操作通过 LUA 脚本保证原子性
- Redis 只做扣数和预热，订单持久化走异步 MQ
- 大流量时 Redis 单节点瓶颈 -> 库存分片（多 key + 轮询）
- 库存预热 + 定时刷新保证不因缓存雪崩导致超卖

---

**题 3：** "Redis 分布式锁在 RedLock 争议下的选型建议。"

**答案要点：**
- 大多数业务场景，单节点 `SET NX PX` 搭配 Redisson watch dog 已足够
- RedLock 适用于：跨数据中心锁、锁持有时间长、失败损失巨大
- 对强一致性要求极高（如金融交易），使用 etcd / ZooKeeper
- 锁的可靠性不只在 Redis，客户端设计更关键：锁超时 + 业务代码幂等 + 降级补偿

---

**题 4：** "Redis Cluster 的 16384 槽位设计的数学原理。"

**答案要点：**
- CRC16 输出 16 位（65536 个值），取 14 位（16384）作为槽位
- 心跳包槽位信息用 bitmap 表示，16384 bit = 2048 字节
- 若用 65536 槽位，bitmap = 8192 字节，心跳包过大
- 16384 在典型集群规模（<1000 节点）下足够均匀
- 节点数较少时，槽位范围可通过权重设置不均等分配

---

**题 5：** "线上 Redis 内存突然飙升，mem_fragmentation_ratio 从 1.2 升到 3.0，如何排查？"

**排查步骤：**
1. 检查 `used_memory` 和 `used_memory_rss`，确定碎片增加量
2. 分析近期业务变更：是否新增了大 key / 大批过期 key
3. 使用 `MEMORY DOCTOR`（4.0+）诊断内存问题
4. 检查 `active_defrag_running` 确认碎片整理是否在工作
5. 低峰期执行 `MEMORY PURGE` 手动整理

**根因通常：**
- 大量过期 key 删除后，内存归还给 OS，但 RSS 不变
- 热 key 频繁增删导致内存碎片
- jemalloc 内存分配器与大块连续内存不匹配（部分系统 malloc 行为不同）

**解决：**
- 启用 `activedefrag yes`
- 使用 `jemalloc` 并调整 `malloc-conf`
- 低峰期重启节点（最后手段）

---

> 最后更新：2026 年 6 月 | 作者：资深 Redis 面试官
>
> 本文以 Redis 6.x / 7.x 为基准，涵盖绝大部分生产场景。Redis 8.x 引入了新的线程模型增强和新的数据过期机制，建议持续关注官方 changelog。
