# 高级MySQL面试知识架构

> 目标受众：5-8年经验高级后端开发
> 定位：深度原理 + 生产实战 + 面试高频题

---

## 目录

1. [架构原理](#1-架构原理)
2. [索引优化](#2-索引优化)
3. [SQL 优化](#3-sql-优化)
4. [锁机制](#4-锁机制)
5. [事务与隔离级别](#5-事务与隔离级别)
6. [高可用架构](#6-高可用架构)
7. [生产运维](#7-生产运维)
8. [与 PostgreSQL 对比分析](#8-与-postgresql-对比分析)

---

## 1. 架构原理

### 1.1 InnoDB 存储引擎

InnoDB 是 MySQL 默认的存储引擎，核心特性：行级锁、MVCC、外键约束、ACID 事务、聚簇索引。

**架构分层：**

```
客户端连接 → 连接池/线程池 → SQL接口 → 解析器 → 优化器 → 执行器
                                                              ↓
                                                      InnoDB 存储引擎
                                              ┌──────────────────────┐
                                              │   Buffer Pool        │
                                              │   Change Buffer      │
                                              │   Adaptive Hash Index│
                                              │   Log Buffer         │
                                              └──────────────────────┘
                                              ┌──────────────────────┐
                                              │   磁盘文件            │
                                              │  .ibd (表空间)        │
                                              │  .ibdata (系统表空间)  │
                                              │  Redo Log            │
                                              │  Undo Log            │
                                              └──────────────────────┘
```

**表空间(Tablespace)架构：**

- **系统表空间** (`ibdata1`)：存储数据字典、Undo Log 等。5.7+ 支持将 Undo Log 独立到单独表空间。
- **独立表空间** (`xxx.ibd`)：每个表独立表空间，默认开启 (`innodb_file_per_table=ON`)。DROP TABLE 时可立即回收磁盘空间。
- **通用表空间**：共享表空间，可存放多个表的数据。
- **临时表空间**：`ibtmp1`，存放临时表数据。

**面试高频题：**

> **Q: InnoDB 和 MyISAM 的核心区别？**
>
> A: InnoDB 支持事务(ACID)、行级锁、外键、MVCC、崩溃恢复(redo log)；MyISAM 仅支持表级锁、不支持事务、崩溃后需要 repair。InnoDB 使用聚簇索引，MyISAM 使用堆表 + 非聚簇索引。InnoDB 在 5.7+ 是默认引擎。

> **Q: InnoDB 的 Doublewrite Buffer 解决了什么问题？**
>
> A: 解决部分写失效(Partial Page Write)问题。当 MySQL 写入 16KB 数据页时，OS 可能只写了前 4KB 后崩溃，导致页数据损坏。Doublewrite Buffer 在写入数据文件前，先将页面写入连续的 2MB 共享表空间区域(每次 1MB，最多 128 页)，保证原子写入；崩溃恢复时若发现页损坏，可从 Doublewrite 恢复。

**Doublewrite Buffer 详解：**

**问题背景 — Partial Page Write（部分页写失效）：**

InnoDB 数据页大小为 16KB，但操作系统 I/O 的原子单位通常为 4KB（或 512B 扇区）。MySQL 刷写一个 16KB 脏页时，若写到第 4KB 时系统崩溃，该页处于"写了一半"的损坏状态。**此时 redo log 无法修复**——redo log 是幂等的物理逻辑日志，应用 redo 的前提是页本身完整，损坏页无法被正确重放。

**写入流程（"两次写"名称由来）：**

```
脏页刷新 (Flush Dirty Pages from Buffer Pool)
        │
        ▼
① 顺序写入 Doublewrite Buffer 区域          ← 第一次写
  ├─ 位置：ibdata1 中连续 2MB 区域（128 个 16KB 页，分两个 1MB 块）
  ├─ 顺序 I/O，开销极低
  └─ fsync() 确保落盘完成
        │
        ▼
② 分散写入各 .ibd 表空间的实际目标位置      ← 第二次写
  └─ 随机 I/O，写入真实位置
```

**存储位置演进：**

| 版本 | 存储位置 | 说明 |
|------|----------|------|
| ≤ 8.0.19 | `ibdata1` 系统表空间 | 连续 2MB 区域，与系统表空间耦合 |
| ≥ 8.0.20 | 独立文件 `#ib_16384_0.dblwr` | 与系统表空间分离，可通过 `innodb_doublewrite_dir` 指定目录（建议放高速存储） |

**崩溃恢复流程：**

```
实例启动 → 扫描所有 .ibd 页，验证 checksum
                    │
          ┌─────────┴──────────┐
          │ checksum 正常       │ checksum 损坏（部分写失效）
          ▼                    ▼
   直接应用 redo log      从 Doublewrite Buffer 取出该页完整副本
                          覆盖损坏页 → 再应用 redo log
```

**性能影响：**

- 写入放大系数理论上 2×，但 Doublewrite 第一次写是**顺序 I/O**，实测额外开销通常在 **5%~10%**。
- HDD 上开销较明显；NVMe SSD 上几乎可忽略。
- MySQL 8.0.20+ 支持多实例并行（`innodb_doublewrite_files`），高并发刷脏时可减少争用。

**关键配置：**

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `innodb_doublewrite` | 是否启用 | `ON` |
| `innodb_doublewrite_dir` | 8.0.20+ 独立文件存放目录 | 与数据目录同位置 |
| `innodb_doublewrite_files` | 8.0.20+ 并行文件数 | `2` |
| `innodb_doublewrite_pages` | 每批写入页数上限 | 等于 `innodb_write_io_threads` |

**何时可以关闭：**

底层存储原生支持 16KB 原子写入时可关闭以节省开销：Fusion-io (NVMFS)、ZFS（`recordsize=16K` + `sync=always`）。命令：`innodb_doublewrite=OFF`。**生产环境几乎不建议关闭**，除非有明确的硬件原子写入保证。

> **面试追问：Doublewrite Buffer 和 redo log 分别防什么？**
>
> - **redo log**：防"已提交事务的数据还在内存未落盘"——实例崩溃后重放日志恢复已提交的修改。
> - **Doublewrite Buffer**：防"正在落盘过程中崩溃导致页损坏"——为 redo log 的应用提供完整、可信的页作为基础。两者互补，缺一不可。

**生产踩坑：**

- `ibdata1` 文件只增不减！除非重建实例。建议早期就设置 `innodb_file_per_table=ON`，并将 Undo Log 独立。
- 5.6 及之前版本 `ALTER TABLE` 会重建表，5.6+ 支持 `ALGORITHM=INPLACE` 在线 DDL，但 `INPLACE` 仍可能锁表（取决于具体操作类型）。

### 1.2 B+Tree 索引结构

B+Tree 是 InnoDB 默认索引结构，所有数据都存储在 B+Tree 中。

**结构特点：**

```
           [非叶子节点 - 目录项]
          /        |          \
   [页10]     [页20]        [页30]
   (key ≤ 5)  (5<key≤10)  (key>10)
      |           |            |
   [叶子节点 - 数据页] ←—— 双向链表
   (key:1,2,3,4,5) ↔ (6,7,8,9,10) ↔ (11,12,13...)
```

- **非叶子节点**：仅存储键值和指向子节点的指针，不存数据。节点大小默认 16KB，一个节点约可存几百到上千个 key。
- **叶子节点**：存储完整行数据(聚簇索引)或主键值(二级索引)。叶子节点之间通过双向链表连接，形成有序链表。
- **高度**：B+Tree 通常 2-4 层。以 16KB 页、8B 主键 + 6B 指针为例，每节点约可存 1170 个 key，三层可存 1170*1170*16 = ~2190 万行。

**面试高频题：**

> **Q: 为什么 InnoDB 用 B+Tree 而不是 B-Tree、红黑树或哈希表？**
>
> A: 见下方详解。

**各数据结构介绍与对比：**

**① 哈希表（Hash Table）**

将 key 经哈希函数映射到桶，O(1) 直接定位。

```
key → hash(key) → bucket[i] → value
冲突时通过链表 / 开放寻址解决
```

- ✅ 等值查找极快 O(1)
- ❌ 不支持范围查询（哈希后顺序被打乱）
- ❌ 不支持排序、前缀匹配
- ❌ 哈希冲突严重时退化为 O(N)
- ❌ 无法利用磁盘顺序 I/O

> InnoDB 的 **Adaptive Hash Index** 是 Buffer Pool 热点页上的内存哈希索引，仅加速等值，底层存储仍是 B+Tree。

---

**② 红黑树（Red-Black Tree）**

自平衡二叉搜索树，通过颜色标记 + 旋转维持树高 ≤ 2·log₂N。

```
        [黑:50]
       /        \
   [红:30]    [黑:70]
   /    \     /    \
[黑:20][黑:40][红:60][黑:80]
```

- ✅ 支持范围查询（中序遍历有序）
- ✅ 增删改 O(log N)
- ❌ **树高太高**：100 万行 ≈ 40 层 → 40 次磁盘 I/O（每次 ≈ 10ms）
- ❌ 每节点仅 1 个 key，磁盘页利用率极低
- ❌ 未为块设备 I/O 优化

> 红黑树适合**内存**中的有序集合（Java TreeMap、Linux CFS 调度），不适合磁盘存储。

---

**③ B-Tree（多路平衡搜索树）**

每个节点存 key + data（完整数据或行指针），m 阶 B-Tree 每节点最多 m-1 个 key。

```
              [20 | 50]
             ↙    ↓    ↘
     [10|15] [30|40] [60|70|80]
    (data)   (data)    (data)
```

- ✅ 树高远低于二叉树，磁盘 I/O 少
- ✅ 支持范围查询
- ❌ 非叶子节点存 data，**每节点 key 数少，树更高**
  （16KB 页若每条数据 1KB，只存 ~16 个 key）
- ❌ 范围查询需中序遍历，要跨层回溯，效率低
- ❌ 相邻叶子节点无链表，顺序扫描要反复从根出发

---

**④ B+Tree（InnoDB 选择）**

非叶子节点**只存 key + 指针**，所有数据存叶子节点，叶子之间用双向链表串联。

```
      非叶子（仅 key + 子节点指针，不存 data）
              [20 | 50]
             ↙    ↓    ↘
     [10|15] [30|40] [60|70|80]
      ↓↓↓     ↓↓↓      ↓↓↓
   [data] ←→ [data] ←→ [data]   ← 双向链表（范围扫描）
```

- ✅ **非叶子节点极宽**：16KB 页存 ~1170 个 key，3 层支撑 2000 万行
- ✅ **范围查询高效**：找到下界后沿链表顺序扫描，无需回溯
- ✅ **稳定 I/O 次数**：所有查询都到达叶子节点，深度固定
- ✅ **顺序 I/O 友好**：叶子链表配合磁盘预读，性能接近顺序读

---

**综合对比表：**

```
┌──────────────┬──────────┬──────────┬──────────┬──────────────┐
│   特性        │  哈希表  │  红黑树  │  B-Tree  │   B+Tree     │
├──────────────┼──────────┼──────────┼──────────┼──────────────┤
│ 等值查询      │ ⭐⭐⭐  │  ⭐⭐   │  ⭐⭐   │    ⭐⭐      │
│ 范围查询      │    ✗    │   ⭐    │  ⭐⭐   │   ⭐⭐⭐     │
│ 排序/ORDER BY │    ✗    │   ⭐⭐  │  ⭐⭐   │   ⭐⭐⭐     │
│ 前缀匹配      │    ✗    │    ✗    │    ✗    │   ⭐⭐⭐     │
│ 树高(百万行)  │    -    │  ~40 层  │  ~10 层  │    2-4 层    │
│ 单节点 key 数 │   高    │    1    │   中    │    极高       │
│ 磁盘 I/O 效率 │   低    │   极低  │   中    │     高        │
│ 顺序扫描      │    ✗    │  需遍历 │  需回溯 │  链表直接扫   │
│ 适合磁盘存储  │    ✗    │    ✗    │  ⭐⭐  │   ⭐⭐⭐     │
└──────────────┴──────────┴──────────┴──────────┴──────────────┘
```

**结论**：InnoDB 面对的核心挑战是**磁盘 I/O 延迟**，必须用最少 I/O 次数覆盖最多数据，同时支持等值 + 范围 + 排序。B+Tree「非叶子不存 data → 节点极宽 → 树极矮 → I/O 极少」+「叶子链表 → 范围高效」完美满足。

> **Q: B+Tree 通常 2-4 层，单表能支撑多少数据？**
>
> A: 以主键 8 字节、页大小 16KB、指针 6 字节为例：每节点约存 16KB/(8+6) ≈ 1170 个 key。三层 B+Tree：1170×1170×16 ≈ 2190 万行。四层：1170³×16 ≈ 256 亿行。实际有页填充因子和碎片，通常 3 层应对千万级数据。

> **Q: 为什么 B+Tree 的范围查询效率高？**
>
> A: 叶子节点通过双向链表连接，找到下界后顺序扫描即可，无需回溯上层节点。而 B-Tree 需要中序遍历。

### 1.3 缓冲池 Buffer Pool

Buffer Pool 是 InnoDB 访问数据和缓存数据的核心区域，直接影响数据库性能。

**核心参数：**

- `innodb_buffer_pool_size`：通常设置为物理内存的 60%-80%。
- `innodb_buffer_pool_instances`：5.7+ 推荐设置为 8-16，以减少锁争用。
- `innodb_old_blocks_time`：保护缓冲池不被全表扫描污染。
- `innodb_buffer_pool_chunk_size`：动态调整 Pool 大小的最小单位。

**LRU 算法改进：**

InnoDB 使用改进的 LRU(Least Recently Used)算法，将 LRU 链表分为 Young 区和 Old 区（默认 5/8 为 Young，3/8 为 Old）：

```
[Young Sub-list] ←→ [Old Sub-list]
  热数据 (5/8)        冷数据 (3/8)
```

流程：
1. 新读取的页面先插入 Old 区头部。
2. 若页面在 Old 区存活超过 `innodb_old_blocks_time`（默认 1000ms）后被再次访问，则晋升到 Young 区头部。
3. 防止全表扫描或大查询"冲垮"热数据。

**生产踩坑：**

- **Buffer Pool 命中率过低**
  - 🔍 **触发信号**：慢查询突然增多、监控上磁盘 I/O（`iostat`）持续打高、`Innodb_buffer_pool_reads` 增速明显、查询响应 P99 升高但 CPU 不高（说明在等 I/O）。
  - 排查：`show engine innodb status` 查看 `Buffer pool hit rate`，低于 95% 需处理。
  ```sql
  SHOW GLOBAL STATUS LIKE 'Innodb_buffer_pool_reads';         -- 从磁盘读次数
  SHOW GLOBAL STATUS LIKE 'Innodb_buffer_pool_read_requests'; -- 总读次数
  -- 命中率 = (read_requests - reads) / read_requests
  ```
  - 处理方向：内存不足 → 扩 `innodb_buffer_pool_size`；SQL 全表扫描污染热数据 → 排查慢查询补索引或调大 `innodb_old_blocks_time`。

- **实例重启后 Buffer Pool 预热冷启动**
  - 🔍 **触发信号**：数据库重启（版本升级、主从切换、故障恢复）后，前 10-30 分钟 QPS 明显低于平时，慢查询集中出现，磁盘 I/O 居高不下，随时间自然恢复。
  - 处理方向：开启自动 dump/load，重启后自动热身。
  ```ini
  innodb_buffer_pool_dump_at_shutdown = ON
  innodb_buffer_pool_load_at_startup  = ON
  innodb_buffer_pool_dump_pct = 25   # 只 dump 最热的 25% 页，速度更快
  ```

- **大事务导致脏页刷盘慢（写延迟抖动）**
  - 🔍 **触发信号**：写入延迟毛刺（P99/P999 周期性尖刺）、主从延迟莫名增大、`Innodb_buffer_pool_wait_free` 计数上涨、IOPS 周期性打满但平均写入量不大。
  - 排查：`SHOW GLOBAL STATUS LIKE 'Innodb_buffer_pool_dirty_pages'` 监控脏页比例，超过 `innodb_max_dirty_pages_pct`（默认 90%）会触发激进刷盘。
  - 处理方向：调高 `innodb_io_capacity` / `innodb_io_capacity_max` 让后台线程刷得更快；减少大事务持有时间；SSD 环境可设 `innodb_io_capacity=2000`，`innodb_io_capacity_max=4000`。

### 1.4 Redo Log 与 Undo Log

**Redo Log（重做日志）—— 保证持久性与崩溃恢复：**

- 记录"物理变化"：页号 + 偏移量 + 修改值。
- **WAL(Write-Ahead Logging)** 原则：事务提交前必须先写 Redo Log（顺序 IO），再写数据页（随机 IO）。
- Redo Log 由 `ib_logfile0`、`ib_logfile1` 等文件构成，循环写入。
- `innodb_flush_log_at_trx_commit` 控制刷盘策略：
  - **1**（默认）：每次提交事务都刷盘，保证 ACID，性能最差。
  - **0**：每秒刷盘一次，写入性能最好，但崩溃可能丢失 1 秒数据。
  - **2**：每次提交只写入 OS Cache，每秒刷盘。
- **LSN(Log Sequence Number)**：日志序列号，唯一标识 Redo Log 中的位置，用于崩溃恢复时确定需要重做的部分。

**Undo Log（回滚日志）—— 支持回滚和 MVCC：**

- 记录"逻辑变化"的反向操作：INSERT 记录 PK 值（反向 DELETE），DELETE 记录行内容（反向 INSERT），UPDATE 记录旧版本行。
- 存储在系统表空间或独立 Undo 表空间（5.7+）。
- **MVCC 依赖**：Undo Log 中的旧版本数据构成回滚段(Rollback Segment)，供一致性读取使用。
- Undo Log 不会无限增长，Purge 线程会清理已提交且无事务需要的 Undo Log。
- 长事务 + 频繁更新 = Undo Log 暴涨，导致 `ibdata1` 膨胀。

**生产踩坑：**

- **Redo Log 太小**：`SHOW GLOBAL STATUS LIKE 'Innodb_log_waits'` 不为 0，说明 Redo Log 太小，写入速度跟不上。建议设置 `innodb_log_file_size` 为 512MB - 4GB（取决于写入量）。
- **长事务风险**：长事务的 Undo Log 无法被 Purge，导致磁盘暴涨，且阻塞 `DDL` 操作。务必设置 `max_execution_time` 和事务超时监控。
- **崩溃恢复时间过长**：Redo Log 越大，崩溃恢复可能越慢。建议监控 `SHOW GLOBAL STATUS LIKE 'Innodb_os_log_pending_fsyncs'`。

### 1.5 MVCC（多版本并发控制）

MVCC 是 InnoDB 实现高并发读的核心机制，读写相互不阻塞。

**核心组件：**

- **隐藏字段**：每行数据包含 `DB_TRX_ID`（最后修改该行的事务 ID）、`DB_ROLL_PTR`（指向 Undo Log 中前一个版本的指针）、`DB_ROW_ID`（自增行 ID）。
- **Undo Log**：保存数据的历史版本，构成版本链。
- **Read View**：事务执行快照读时生成的一致性视图，决定当前事务能看到哪些版本。

**Read View 结构：**

```
Read View = { m_ids: [活跃事务ID列表], min_trx_id: 最小活跃ID,
              max_trx_id: 下一个待分配ID, creator_trx_id: 当前事务ID }
```

**可见性判断规则（以 RR 级别为例）：**

遍历版本链，对每个版本的事务ID `trx_id`：
1. `trx_id == creator_trx_id` → 可见（自己的修改当然能看到）。
2. `trx_id < min_trx_id` → 可见（该版本在当前 Read View 创建前已提交）。
3. `trx_id >= max_trx_id` → 不可见（该版本在当前 Read View 创建后才开始）。
4. `trx_id ∈ [min_trx_id, max_trx_id)` 且不在 m_ids 中 → 可见（事务已提交）。
5. 否则 → 不可见，继续沿 Undo Log 版本链找更早版本。

**当前读 vs 快照读：**

| 类型 | 操作 | 加锁 |
|------|------|------|
| 快照读 | 普通 `SELECT` | 不加锁（通过 MVCC 实现） |
| 当前读 | `SELECT ... FOR UPDATE`、`SELECT ... LOCK IN SHARE MODE`、`UPDATE`、`DELETE`、`INSERT` | 加锁 |

**RC 与 RR 下 Read View 生成时机：**

- **RC（Read Committed）**：每次语句执行前都生成新的 Read View。
- **RR（Repeatable Read）**：事务中第一个快照读时生成 Read View，整个事务复用它。

**面试高频题：**

> **Q: MVCC 解决了什么问题？**
>
> A: 让读操作不阻塞写操作，写操作不阻塞读操作。在 RC 和 RR 隔离级别下，快照读无需加锁即可读到一致的数据，显著提升并发性能。

> **Q: RR 级别如何避免幻读？**
>
> A: 通过 MVCC 快照读（一致性读）和 Gap/Next-Key Lock（锁定读取/更新/删除时的间隙）。快照读靠 Read View 保证只看到事务开始时的数据快照；当前读靠 Gap Lock 阻止其他事务在范围内插入新行。但严格来说，RR 不能完全避免幻读——如果事务中途执行当前读，可能读到新插入的行（即 Phantom Read）。

> **Q: MVCC 下 Undo Log 何时被清理？**
>
> A: 当系统确定该 Undo Log 不再被任何活跃事务的 Read View 需要时，由 Purge 线程清理。如果有长事务一直不提交，对应版本链上的所有旧版本都不能清理。

**生产踩坑：**

- RR 级别下大事务导致 Undo Log 无法清理，影响空间和性能。建议业务中控制事务粒度，避免在一个事务中做大量查询操作。
- 高并发热点行更新时，MVCC 版本链会很长，导致回滚段膨胀和读取性能下降。

### 1.6 SQL 执行全流程

一条 SQL 从客户端到结果返回，经历以下阶段：

```
客户端
  │
  ▼
连接器 (Connector)
  ├─ TCP 握手 + 身份认证（用户名/密码/Host 校验）
  ├─ 读取权限信息缓存到连接上下文（之后修改权限需重连才生效）
  └─ 长连接 / 短连接管理，空闲超过 wait_timeout 自动断开
  │
  ▼
查询缓存 (Query Cache) ← 8.0 已彻底移除
  ├─ 命中：直接返回缓存结果
  └─ 未命中：继续往下走（任意写操作导致整张表的缓存失效，弊大于利）
  │
  ▼
解析器 (Parser)
  ├─ 词法分析：识别关键字、表名、列名、字面量等 Token
  └─ 语法分析：按 SQL 语法规则构建 AST（抽象语法树）
  │
  ▼
预处理器 (Preprocessor)
  ├─ 语义检查：表/列是否存在，别名是否有歧义
  └─ 权限验证：当前用户是否有权访问对应表和列
  │
  ▼
优化器 (Optimizer) — CBO 基于代价的优化
  ├─ 选择索引：根据统计信息估算各执行路径的 cost，选最优
  ├─ Join 顺序：小表驱动大表，调整多表 Join 顺序
  ├─ 子查询改写：将部分子查询优化为 Join 或 Semi-Join
  └─ 生成执行计划（可通过 EXPLAIN 查看）
  │
  ▼
执行器 (Executor)
  ├─ 再次校验权限
  ├─ 调用存储引擎 Handler API（逐行/批量获取数据）
  └─ 将结果集返回给客户端（流式返回）
  │
  ▼
InnoDB 存储引擎
  ├─ Buffer Pool 查找：命中直接返回内存中的数据页
  ├─ 未命中：从磁盘 .ibd 文件加载数据页到 Buffer Pool
  ├─ 写操作额外流程：
  │   ├─ 记录 Undo Log（回滚段，保证原子性和 MVCC）
  │   ├─ 修改 Buffer Pool 中的数据页（脏页）
  │   ├─ 写 Redo Log Buffer → 根据 innodb_flush_log_at_trx_commit 策略刷盘
  │   └─ 写 Binlog（事务提交时，Server 层负责写）
  └─ 2PC（两阶段提交）：Redo Log prepare → Binlog write → Redo Log commit
```

**关键面试题：**

> **Q: 为什么需要 Redo Log 和 Binlog 两阶段提交？**
>
> A: 防止两个日志不一致。若先写 Binlog 再崩溃，从库多了这条数据但主库没有；若先提交 Redo 再崩溃，主库有但 Binlog 没有，从库缺这条。2PC 保证两个日志要么都有要么都没有，主从数据一致。

> **Q: MySQL 8.0 删除查询缓存的原因？**
>
> A: 查询缓存以 SQL 文本为 key，任何一次对该表的写操作都会让表相关的所有缓存失效。对于写多读少或数据频繁变更的场景，缓存命中率极低，还带来额外的加锁开销（缓存操作需要加全局锁）。实践中收益远小于维护成本，8.0 彻底移除。

---

## 2. 索引优化

### 2.1 聚集索引 vs 二级索引

**聚集索引(Clustered Index)：**

- InnoDB 表中必有一个聚集索引，通常是主键。
- 叶子节点直接存放整行数据。
- 数据按主键顺序物理存储（逻辑有序，不保证物理完全连续）。
- 主键查找只需一次 B+Tree 搜索即可定位数据。

**二级索引(Secondary Index / 辅助索引)：**

- 叶子节点存放的是主键值，而非行数据。
- 需要通过主键值回表查询完整行数据（称为**回表查询**）。
- 二级索引可以有多个。

```sql
-- 创建测试表
CREATE TABLE `user` (
  `id` int NOT NULL AUTO_INCREMENT,
  `name` varchar(50) NOT NULL,
  `age` int NOT NULL,
  `city` varchar(50) NOT NULL,
  PRIMARY KEY (`id`),
  KEY `idx_age` (`age`),
  KEY `idx_city_name` (`city`, `name`)
) ENGINE=InnoDB;

-- 流程示例：
-- SELECT * FROM user WHERE age = 25;
-- Step 1: 搜索 idx_age 二级索引的 B+Tree，找到 age=25 的叶子节点，获取主键值 id
-- Step 2: 根据主键 id 回表搜索聚集索引，获取完整行数据（一次回表）
```

**面试高频题：**

> **Q: 为什么二级索引叶子节点存的是主键值而非行指针？**
>
> A: 减少数据移动。当数据页发生分裂或重组织时，只需更新聚集索引。如果二级索引存物理地址，每次数据移动都需要更新所有二级索引，代价太大。存主键值+通过主键回表是一种空间换稳定的设计。

> **Q: 没有主键的表，InnoDB 如何组织数据？**
>
> A: InnoDB 优先使用用户定义的主键。若没有主键，选择第一个非空的 UNIQUE 索引作为聚集索引。若都没有，InnoDB 隐式生成一个 6 字节的 `ROW_ID` 作为聚集索引。

> **Q: 为什么强烈建议用自增主键？**
>
> A:
> - **写入性能**：自增主键顺序插入，新数据追加到 B+Tree 最后一页，页分裂少。UUID 或业务主键写入随机，频繁页分裂，写入性能差 3-10 倍。
> - **空间效率**：页分裂产生碎片，降低空间利用率。
> - **二级索引**：二级索引叶子存主键值，自增主键 INT(4B)/BIGINT(8B) 比 UUID(16B/36B) 占用空间小，二级索引更紧凑。

### 2.2 覆盖索引

**定义：** 查询所需的所有列都包含在索引中，无需回表，直接通过索引即可获取结果。

```sql
-- 表结构：联合索引 idx_city_name(city, name)
-- 回表查询（需要额外访问主键索引）
EXPLAIN SELECT * FROM user WHERE city = '北京';  -- Extra: Using index condition

-- 覆盖索引查询
EXPLAIN SELECT city, name FROM user WHERE city = '北京';  -- Extra: Using index
-- Using index 表示使用了覆盖索引，无需回表
```

**面试高频题：**

> **Q: 覆盖索引性能提升的原理？**
>
> A:
> 1. 减少回表的随机 IO（二级索引可能指向多个不同页的主键数据）。
> 2. 索引通常比数据行小，相同 IO 操作可读取更多索引页。
> 3. 减少数据页的 Buffer Pool 竞争。

> **Q: 什么场景下覆盖索引提升特别明显？**
>
> A: 大表上返回大量行的查询。例如业务中只查 ID 和状态字段的统计查询，覆盖索引可减少数十倍 IO。

### 2.3 索引下推 (ICP - Index Condition Pushdown)

ICP 是 MySQL 5.6 引入的优化，将 WHERE 条件中部分过滤下推到存储引擎层，减少回表次数。

**原理对比：**

```sql
-- 联合索引 idx_city_name(city, name)
-- 没有 ICP 时（5.6 之前）：
SELECT * FROM user WHERE city = '北京' AND name LIKE '%三%';
-- Step 1: 引擎层用 `city='北京'` 找到所有匹配的二级索引条目
-- Step 2: 每一条都回表取完整行
-- Step 3: Server 层对回表结果用 `name LIKE '%三%'` 过滤

-- 有 ICP 时：
-- Step 1: 引擎层用 `city='北京'` 找到匹配的二级索引条目
-- Step 2: 引擎层直接用索引中的 name 字段过滤 `name LIKE '%三%'`（不下推聚合函数、不支持子查询）
-- Step 3: 仅对过滤后的条目回表
```

**验证：**

```sql
EXPLAIN SELECT * FROM user WHERE city = '北京' AND name LIKE '%三%';
-- Extra: Using index condition  ← 表示使用了 ICP
```

**注意：** ICP 适用于二级索引，不适用于聚集索引（聚集索引叶子已包含完整行数据）。

**生产踩坑：**

- ICP 只下推给 InnoDB/MyISAM 存储引擎，且只适用于 `WHERE` 条件中能被索引覆盖的列。
- ICP 并不总是正向收益。如果过滤率很低（过滤掉的行很少），ICP 增加的开销可能超过收益。优化器会自己判断。
- 通过 `SET optimizer_switch = 'index_condition_pushdown=off'` 可以关闭 ICP，用于调试。

### 2.4 MRR (Multi-Range Read)

MRR 是 MySQL 5.6 引入的优化，目的：减少回表时的随机 IO。

**原理：**

```sql
-- 没有 MRR：
-- SELECT * FROM user WHERE age BETWEEN 20 AND 30;
-- 二级索引 age 返回的主键值是无序的（按 age 排序，不按 id 排序）
-- 回表时随机访问各个数据页，大量随机 IO

-- 有 MRR：
-- Step 1: 根据二级索引获取一批主键值
-- Step 2: 将主键值在内存中排序（按 id 排序）
-- Step 3: 按排好序的主键值顺序回表
-- 将随机 IO 转化为顺序 IO，提升磁盘读取效率
```

**验证：**

```sql
EXPLAIN SELECT * FROM user WHERE age BETWEEN 20 AND 30;
-- Extra: Using index condition; Using MRR
```

**MRR 适用场景：**

- 范围查询返回大量行且需要回表。
- 二级索引有较好的过滤率（不是全表级别）。
- SSD 受益略小但仍有收益（顺序读比随机读快）。

**控制参数：**

```sql
SET optimizer_switch = 'mrr=on,mrr_cost_based=on';
-- mrr_cost_based=on: 优化器基于成本判断是否使用 MRR
```

### 2.5 索引选择原则

**核心原则：**

1. **高选择性列优先**：区分度越高，索引效率越好。
   ```sql
   -- 计算列的区分度
   SELECT COUNT(DISTINCT column_name) / COUNT(*) AS selectivity FROM table_name;
   -- 选择性 > 20% 通常值得建索引
   ```

2. **最左前缀原则**：联合索引 `(a, b, c)` 有效利用了：
   - `WHERE a=?` ✓
   - `WHERE a=? AND b=?` ✓
   - `WHERE a=? AND b=? AND c=?` ✓
   - `WHERE a=? ORDER BY b` ✓
   - `WHERE b=?` ✗（无法使用）
   - `WHERE a=? AND c=?` ✓（只用 a，c 在索引过滤后回表再过滤，或 ICP）
   - `WHERE a=? ORDER BY c` ✗（c 上无法有序扫描，可能 filesort）

3. **尽量减少索引数**：索引不是越多越好，写放大（更新索引开销）、空间占用。

4. **冗余索引清理**：联合索引 `(a, b)` 已经覆盖了 `(a)` 的功能，单独 `(a)` 可删除。
   ```sql
   -- 查找冗余索引
   SELECT * FROM sys.schema_redundant_indexes;
   ```

5. **前缀索引**：对大字符串列（如 VARCHAR(255)），使用前缀索引节省空间。
   ```sql
   -- 建前缀索引，选择性接近完整列即可
   ALTER TABLE user ADD KEY idx_email(email(10));
   SELECT COUNT(DISTINCT email(10)) / COUNT(*) AS selectivity FROM user;
   ```

6. **索引 vs 排序**：ORDER BY 列尽量利用索引排序避免 filesort。
   ```sql
   EXPLAIN SELECT * FROM user WHERE city = '北京' ORDER BY name;
   -- Extra 中出现 "Using filesort" 表示未利用索引排序
   ```

### 2.6 EXPLAIN 深度解读

**输出字段逐项解析：**

| 字段 | 含义 | 重要值 |
|------|------|--------|
| `id` | 查询中 SELECT 的标识符，id 越大越先执行，id 相同从上到下 | 数字 |
| `select_type` | SELECT 类型 | `SIMPLE`, `PRIMARY`, `SUBQUERY`, `DERIVED`, `UNION`, `UNION RESULT` |
| `table` | 访问的表 | 表名或别名 |
| `partitions` | 分区匹配情况 | 分区名或 NULL |
| **`type`** | **访问类型（关键指标）** | 见下 |
| `possible_keys` | 可能使用的索引 | 索引名或 NULL |
| **`key`** | **实际使用的索引** | 索引名 |
| `key_len` | 使用的索引长度（字节） | 数字 |
| `ref` | 索引匹配的列或常量 | 列名或 const |
| **`rows`** | **预估扫描行数** | 数字（越少越好） |
| **`filtered`** | **过滤后占比** | 百分比 |
| **`Extra`** | **额外信息（重点）** | 见下 |

**type 访问类型（性能从好到差）：**

| 类型 | 说明 | 何时出现 |
|------|------|----------|
| `system` | 表只有一行（const 的特殊情况） | 系统表 |
| `const` | 主键/唯一索引等值查询，最多一条匹配 | `WHERE id=1` |
| `eq_ref` | 联表时，每次只匹配一行，使用主键/唯一索引 | JOIN 时驱动表 |
| `ref` | 非唯一索引等值查询，可能匹配多行 | `WHERE city='北京'` |
| `fulltext` | 全文索引匹配 | MATCH AGAINST |
| `ref_or_null` | ref 扫描 + NULL 值搜索 | `WHERE city='北京' OR city IS NULL` |
| `index_merge` | 多个索引合并使用（交集/并集） | OR 条件跨索引 |
| `unique_subquery` | IN 子查询使用唯一索引优化 | `WHERE id IN (SELECT ...)` |
| `index_subquery` | IN 子查询使用普通索引 | `WHERE col IN (SELECT ...)` |
| **`range`** | **范围扫描** | `>`, `<`, `BETWEEN`, `IN`, `LIKE 'abc%'` |
| `index` | 扫描整个索引树，但比 ALL 好（索引比数据小） | 覆盖索引但扫描全索引 |
| **`ALL`** | **全表扫描（最差）** | 无索引或优化器认为不如全表 |

**Extra 字段重点值：**

| Extra 值 | 含义 | 是否需要优化 |
|----------|------|-------------|
| `Using index` | 覆盖索引，无需回表 | 好 |
| `Using index condition` | 索引条件下推 ICP | 好 |
| `Using where` | Server 层额外过滤 | 合理即可 |
| `Using MRR` | 使用 MRR 优化 | 好 |
| `Using filesort` | 无法利用索引排序，需要额外排序 | 需优化 |
| `Using temporary` | 使用了临时表 | 需优化（GROUP BY/ORDER BY 未用索引） |
| `Using join buffer` | 联表未用索引，使用 Join Buffer | 需优化（缺少索引） |
| `Using index for group-by` | 利用索引做 GROUP BY | 好 |

**实战分析范例：**

```sql
-- 场景：分页查询排序
EXPLAIN SELECT * FROM user WHERE city = '北京' ORDER BY age LIMIT 10000, 20;
-- +------+------+-------------+-------+------+----------+-----------------------+
-- | type | key | rows | Extra                         |
-- +------+------+------+-------+-----------------------------+
-- | ref  | idx_city | 50000 | Using index condition; Using filesort |
-- +------+------+------+-------+-----------------------------+
-- 问题：50万行通过 city 找到5万行，然后在内存排序再偏移10000
-- 优化方案1：建立 (city, age) 联合索引，消除 filesort
-- 优化方案2：延迟关联 SELECT * FROM user INNER JOIN
--           (SELECT id FROM user WHERE city='北京' ORDER BY age LIMIT 10000,20) tmp
--           USING(id);
```

**获取更准确的执行计划：**

```sql
-- 显示 JSON 格式执行计划（含成本信息）
EXPLAIN FORMAT=JSON SELECT * FROM user WHERE age > 25;
-- 输出：read_cost, eval_cost, prefix_cost, 等

-- 查看实际执行情况（5.7+ 的 sys.session）
SELECT * FROM sys.statement_analysis WHERE digest_text LIKE '%user%'\G

-- 使用 optimizer trace 查看优化器决策过程（调试用）
SET optimizer_trace='enabled=on';
SELECT * FROM user WHERE age > 25;
SELECT * FROM information_schema.OPTIMIZER_TRACE;
SET optimizer_trace='enabled=off';
```

**生产踩坑：**

- **EXPLAIN 的 rows 是估计值，不准确。** 数据分布不均时差距可能很大。`SHOW INDEX FROM table` 的 `Cardinality` 也是近似值，`ANALYZE TABLE` 可更新。
- **"Using temporary; Using filesort" 同时出现通常是大坑。** GROUP BY 或 ORDER BY 没利用索引，在磁盘建临时表排序。建议优化 SQL 或建联合索引。
- **索引选择错误时**，可用 `USE INDEX` / `FORCE INDEX` 强制指定索引（慎用于生产，数据变化后可能变差），或者重写 SQL 引导优化器。终极手段是删掉效果不好的索引。
- **limit 大偏移量问题**：`LIMIT 100000, 20` 实际扫描 100020 行再丢弃前 100000 行。用延迟关联或游标翻页（WHERE id > ? LIMIT 20）。

---

## 3. SQL 优化

### 3.1 慢查询分析

**慢查询配置：**

```sql
-- 开启慢查询日志
SET GLOBAL slow_query_log = ON;
SET GLOBAL long_query_time = 1;          -- 超过 1 秒的 SQL 记录
SET GLOBAL log_queries_not_using_indexes = ON; -- 未使用索引的 SQL 也记录
SET GLOBAL min_examined_row_limit = 1000; -- 扫描行数超过 1000 才记录
-- 5.7 后默认记录到 mysql.slow_log 表，也支持文件

-- 查看慢查询日志位置
SHOW VARIABLES LIKE 'slow_query_log_file';
```

**慢查询分析工具：**

- **mysqldumpslow**：MySQL 自带的慢查询汇总工具。
  ```bash
  # 按查询时间排序，查看前 10 条
  mysqldumpslow -s t -t 10 /var/lib/mysql/slow.log

  # 按平均查询时间排序
  mysqldumpslow -s at -t 10 /var/lib/mysql/slow.log
  ```
- **pt-query-digest** (Percona Toolkit)：更强大的分析工具。
  ```bash
  pt-query-digest /var/lib/mysql/slow.log > slow_analysis.txt
  ```
- **sys 库**：MySQL 5.7+ 自带 `sys` 库。
  ```sql
  -- 查看最慢的前 10 条 SQL
  SELECT * FROM sys.statement_analysis ORDER BY avg_latency DESC LIMIT 10;

  -- 查看全表扫描的查询
  SELECT * FROM sys.statements_with_full_table_scans;

  -- 查看临时表使用过多的查询
  SELECT * FROM sys.statements_with_temp_tables;
  ```

**慢查询排查 checklist：**

| 优先级 | 检查点 | 典型问题 |
|--------|--------|----------|
| P0 | 是否全表扫描？`type=ALL` | 缺索引 |
| P0 | 扫描行数是否过大？`rows` | 索引选择性差 |
| P1 | 是否 filesort？ | ORDER BY 未用索引 |
| P1 | 是否使用临时表？ | GROUP BY/UNION 未用索引 |
| P2 | 回表过多？ | 考虑覆盖索引 |
| P2 | 是否使用 Join Buffer？ | JOIN 缺索引 |
| P3 | 查询是否取多余列？ | `SELECT *` 代替明确列名 |

### 3.2 SQL 执行顺序

```sql
SELECT DISTINCT column, AGG_FUNC(column_or_expression)
FROM table1
    JOIN table2 ON table1.column = table2.column
WHERE constraint_expression
GROUP BY column
HAVING constraint_expression
ORDER BY column ASC/DESC
LIMIT count OFFSET COUNT;
```

**逻辑执行顺序：**

```
 1. FROM         确定数据源，包括 JOIN 的笛卡尔积
 2. ON           过滤 JOIN 结果（仅对 JOIN 有效）
 3. JOIN         添加外部行（LEFT/RIGHT JOIN 的 NULL 补全）
 4. WHERE        行级过滤（不能用聚合函数）
 5. GROUP BY     分组
 6. HAVING       分组后过滤（可用聚合函数）
 7. WINDOW       窗口函数计算
 8. SELECT       投影，计算表达式
 9. DISTINCT     去重
10. UNION        合并多个查询结果
11. ORDER BY     排序
12. LIMIT/OFFSET 分页截断
```

**关键理解：**

- `WHERE` 不能过滤聚合结果，`HAVING` 可以。但 `HAVING` 中的条件如果能移到 `WHERE` 中，应尽量提前，减少分组数据量。
- 别名的限制：`SELECT` 中定义的别名，`WHERE` 不可用（因为 `WHERE` 在 `SELECT` 之前执行），但 `ORDER BY` 可用。`FROM` 子查询中的别名在外部整个查询中才可用。
- `DISTINCT` 和 `ORDER BY` 结合使用时，必须保证 `ORDER BY` 的列在 `SELECT` 中，否则结果可能不符合预期。

### 3.3 Join 算法

MySQL 8.0 支持三种 Join 算法：Nested Loop Join（NLJ）、Block Nested Loop Join（BNL）、Hash Join（8.0.20+）。

#### Nested Loop Join (NLJ)

**原理：** 遍历驱动表，对驱动表的每一行去被驱动表索引中查找匹配行。

```sql
SELECT * FROM orders o JOIN users u ON o.user_id = u.id;
-- 执行过程：
-- 驱动表（通常是 orders）：全表扫描或索引扫描
-- 被驱动表（users）：对每个 o.user_id 在 u.id 上做等值匹配
```

- 时间复杂度：O(N * logM)（被驱动表有索引）或 O(N * M)（无索引）。
- 最优场景：驱动表小 + 被驱动表有索引。
- **被驱动表的连接条件必须有索引，否则 NLJ 退化为全表遍历。**

#### Block Nested Loop Join (BNL)

当被驱动表的连接条件没有索引时，MySQL 使用 BNL。

**原理：** 一次将驱动表的多个行缓存在 Join Buffer 中，批量与被驱动表匹配。

```sql
EXPLAIN SELECT * FROM orders o JOIN users u ON o.user_email = u.email;
-- Extra: Using join buffer (Block Nested Loop) ← 表示使用了 BNL
```

- Join Buffer 大小由 `join_buffer_size` 控制（默认 256KB，可调至 1-4MB）。
- BNL 减少被驱动表的全表扫描次数：扫描次数 = 驱动表行数 / Join Buffer 容量。
- 优化方向：给被驱动表连接列建索引，让 BNL 变成 NLJ；或增大 `join_buffer_size`。

#### Hash Join (MySQL 8.0.20+)

8.0.18 引入（默认 BNL），8.0.20 起替代 BNL 用于等值连接。

**原理：** 将驱动表数据构建哈希表，被驱动表逐行哈希探测匹配。

```sql
EXPLAIN FORMAT=TREE SELECT * FROM orders o JOIN users u ON o.user_email = u.email;
-- -> Inner hash join (o.user_email = u.email)
--     -> Table scan on u
--     -> Hash
--         -> Table scan on o
```

- Hash Join 只适用于等值连接（`=`）。
- 不需要索引，适合大表无索引连接的场景（如 ETL、数仓查询）。
- 性能优势：复杂度 O(N + M)（构建哈希表 + 探测），远优于 BNL 的 O(N * M) 在最差情况下。
- 内存不足时溢出到磁盘（`HashJoin: graceful degradation`），但性能下降不大。

**Join 优化原则：**

1. **小表驱动大表**：驱动表应尽量小，减少匹配次数。
2. **连接列建索引**：被驱动表的 JOIN 列必须有索引，这是最有效的优化。
3. **控制驱动表行数**：WHERE 条件应尽可能过滤驱动表。
4. **避免 SELECT * **：只取需要的列，减少 Join Buffer 和网络传输。
5. **考虑用 Straight Join 强制驱动表顺序**（仅用于调试）。
   ```sql
   SELECT * FROM small_table STRAIGHT_JOIN big_table ON ...;
   ```

**面试高频题：**

> **Q: MySQL 中的 NLJ、BNL、Hash Join 分别在什么场景使用？**
>
> A: 被驱动表有索引 → NLJ；无索引且 8.0.20 之前 → BNL；无索引且 8.0.20+ 等值连接 → Hash Join。Hash Join 通常优于 BNL，但不适用非等值连接（如 `<`, `>`）。

> **Q: 为什么 MySQL 8.0 引入了 Hash Join？**
>
> A: 应对 OLAP 场景：大表关联大表、数仓查询、ETL 任务。在无索引场景下，Hash Join 比 BNL 高效得多（O(N+M) vs O(N*M)）。这是 MySQL 向 HTAP 演进的重要一步。

### 3.4 子查询优化

**子查询的性能陷阱：**

早期 MySQL（5.6 之前）对子查询的优化非常差，尤其是 `IN (SELECT ...)` 会导致外层表逐行执行子查询（相关性执行）。5.6+ 引入了半连接(Semi-join)和物化(Materialization)优化。

```sql
-- 低效写法（早期版本）
SELECT * FROM user WHERE id IN (SELECT user_id FROM order WHERE amount > 1000);
-- 5.6 之前：对每个 user 执行一次子查询 —— O(N*M)

-- 高效写法
SELECT u.* FROM user u
INNER JOIN (SELECT DISTINCT user_id FROM order WHERE amount > 1000) tmp ON u.id = tmp.user_id;
```

**半连接优化（5.6+）：**

优化器自动将 `IN (SELECT ...) / EXISTS` 子查询转换为半连接，避免逐行执行。

```sql
EXPLAIN SELECT * FROM user WHERE id IN (SELECT user_id FROM order WHERE amount > 1000);
-- 注意 select_type 显示为 'SIMPLE' 而不是 'SUBQUERY'
-- 说明已经转化为半连接执行
```

**子查询优化策略：**

| 优化类型 | 说明 | 适用场景 |
|----------|------|----------|
| `Materialize` | 物化子查询结果到临时表，加索引 | IN 子查询数据量不大 |
| `Duplicate Weedout` | 半连接结果去重 | 外层表可能有重复匹配 |
| `First Match` | 找到第一个匹配就停止 | EXISTS 优化 |
| `Loose Scan` | 用索引分组扫描减少匹配 | 分组聚合类子查询 |
| `Semi-join` | 半连接优化 | IN/EXISTS |

**NOT IN 的陷阱：**

```sql
-- NOT IN 遇到 NULL 时整个结果为空！
SELECT * FROM user WHERE id NOT IN (SELECT user_id FROM order);
-- 如果 order.user_id 包含 NULL，结果永远为空行（因为 NULL 比较未定义）

-- 安全写法：
SELECT * FROM user WHERE id NOT IN (SELECT user_id FROM order WHERE user_id IS NOT NULL);
-- 或改为 NOT EXISTS
SELECT * FROM user WHERE NOT EXISTS (SELECT 1 FROM order WHERE user_id = user.id);
```

**面试高频题：**

> **Q: EXISTS vs IN 哪个性能更好？**
>
> A: 关键看数据量分布：
> - 子查询结果集小（如过滤后 < 几千行）：`IN` 通常更好（物化后走索引）。
> - 外层表小、子查询量大：`EXISTS` 通常更好（外层驱动，逐行探测子查询索引）。
> - 5.6+ 优化器会自动做半连接转换，二者差异已不大。建议优先考虑逻辑清晰度，再关注执行计划。

> **Q: 关联子查询为什么不推荐？**
>
> A: 关联子查询对外层每一行都执行一次子查询，复杂度 O(N*M)。特别是子查询涉及的表很大时，性能灾难。常见于 `SELECT *, (SELECT ... FROM t2 WHERE t2.id = t1.id)`。通常可以用 JOIN 或窗口函数替代。

**生产踩坑：**

- **`WHERE IN (SELECT ...)` 子查询结果集过大**导致临时表很大，耗尽临时表空间。监控 `SHOW GLOBAL STATUS LIKE 'Created_tmp_disk_tables'`。
- **`NOT IN` 碰上 NULL 返回空结果集**——这是新手最常踩的坑。优先用 `NOT EXISTS` 或 `LEFT JOIN ... IS NULL`。
- **衍生表(Derived Table)无法利用外部 WHERE 下推**（5.6 前）。5.6+ 的 Derived Condition Pushdown 解决了一部分。但复杂子查询仍建议手工拆分。

---

## 4. 锁机制

### 4.1 行锁类型

InnoDB 支持三种行锁类型，它们的粒度不同：

#### Record Lock（记录锁）

- 锁住索引记录本身。
- 即使表没有索引，InnoDB 也会使用隐式聚集索引来加 Record Lock。

```sql
-- 对主键等值查询且命中唯一索引 → Record Lock
BEGIN;
SELECT * FROM user WHERE id = 10 FOR UPDATE;
-- 仅在 id=10 的记录上加锁
```

#### Gap Lock（间隙锁）

- 锁住索引记录之间的间隙，防止其他事务在该间隙插入新记录。
- 仅在 RR（Repeatable Read）隔离级别下生效。
- 解决了幻读问题。

```sql
-- 对不存在的数据加 Gap Lock
BEGIN;
SELECT * FROM user WHERE id = 15 FOR UPDATE;  -- 假设 id=15 不存在
-- 在 (10, 20) 范围内加 Gap Lock，阻止插入 id=15 的新记录

-- 范围查询也会产生 Gap Lock
SELECT * FROM user WHERE id BETWEEN 10 AND 20 FOR UPDATE;
-- 对 (10,20] 即 (10,20) 间隙和 id=20 记录都加锁
```

#### Next-Key Lock（临键锁）

- `Record Lock + Gap Lock` 的组合。
- 锁住记录本身及记录之前的间隙。
- **InnoDB RR 级别下的默认行锁算法。**
- 范围：`(前一个索引值, 当前索引值]`。

```sql
-- 假设表中有 id: 5, 10, 20
BEGIN;
SELECT * FROM user WHERE id > 10 FOR UPDATE;
-- 加锁范围：
-- - id=10 的 Next-Key Lock: (5, 10]
-- - id=20 的 Next-Key Lock: (10, 20]
-- - supremum 伪记录的 Next-Key Lock: (20, +∞)
--
-- 实际效果：锁定 (-∞, +∞) 所有区间，阻止任何插入和修改
```

**加锁规则总结（基于 MySQL 8.0）：**

1. **等值查询命中唯一索引**：退化为 Record Lock（仅锁命中行）。
2. **等值查询命中二级索引**：二级索引上的 Next-Key Lock + 对应主键上的 Record Lock + 二级索引上的 Gap Lock（防止其他事务在间隙插入导致幻读）。
3. **等值查询未命中**：加 Gap Lock。
4. **范围查询**：全部加上 Next-Key Lock。
5. **唯一索引的等值非唯一（不存在的值）**：加 Gap Lock。
6. **`UPDATE`/`DELETE`** 使用当前读，加锁规则同 `SELECT ... FOR UPDATE`。

**验证锁信息：**

```sql
-- 查看当前锁等待
SELECT * FROM performance_schema.data_lock_waits\G
-- 或 8.0+
SELECT * FROM performance_schema.data_locks\G
-- MySQL 5.x 旧版本
SELECT * FROM information_schema.INNODB_LOCK_WAITS;
SELECT * FROM information_schema.INNODB_LOCKS;
```

### 4.2 死锁检测与解决

**死锁产生的四个必要条件：**

1. 互斥：资源一次只能被一个事务使用（行锁天然互斥）。
2. 持有并等待：事务持有锁的同时等待其他锁。
3. 不可剥夺：已获得的锁不能被强制回收。
4. 循环等待：两个或多个事务互相等待对方释放锁。

**典型死锁场景：**

```sql
-- 事务 A:
BEGIN;
UPDATE user SET name = 'a' WHERE id = 1;  -- 锁住 id=1
UPDATE user SET name = 'b' WHERE id = 2;  -- 等待 id=2 的锁

-- 事务 B:
BEGIN;
UPDATE user SET name = 'b' WHERE id = 2;  -- 锁住 id=2
UPDATE user SET name = 'a' WHERE id = 1;  -- 等待 id=1 的锁 → 死锁
```

**二级索引死锁场景：**

```sql
-- 表结构：idx_city(city)
-- 事务 A:
DELETE FROM user WHERE city = '北京' AND id = 10;
-- Step 1: 在二级索引 idx_city 上对 '北京' 加 Next-Key Lock
-- Step 2: 在聚集索引上加 Record Lock (id=10)

-- 事务 B:
DELETE FROM user WHERE city = '北京' AND id = 20;
-- Step 1: 尝试在二级索引 idx_city 上加 Next-Key Lock
-- → 等 A 释放 → 死锁
```

**InnoDB 死锁处理机制：**

1. **死锁检测**：InnoDB 使用等待图(Wait-For Graph)算法检测循环等待。`innodb_deadlock_detect=ON`（默认开启）。
2. **回滚代价最小的事务**：回滚修改行数最少的事务，释放其持有的锁。
3. **死锁信息**：`SHOW ENGINE INNODB STATUS` 查看 `LATEST DETECTED DEADLOCK` 部分。

```sql
SHOW ENGINE INNODB STATUS\G
-- 输出 LATEST DETECTED DEADLOCK 段：
-- *** (1) TRANSACTION: ...
-- *** (1) HOLDS THE LOCK(S): ...
-- *** (1) WAITING FOR THIS LOCK TO BE GRANTED: ...
-- *** (2) TRANSACTION: ...
-- *** (2) HOLDS THE LOCK(S): ...
-- *** (2) WAITING FOR THIS LOCK TO BE GRANTED: ...
-- *** WE ROLL BACK TRANSACTION (2)
```

**死锁避免策略：**

| 策略 | 说明 |
|------|------|
| 统一访问顺序 | 所有事务按相同顺序访问资源（如先 id 小→大） |
| 缩小事务范围 | 尽可能短的事务持有锁的时间 |
| 降低隔离级别 | RC 级别无 Gap Lock，死锁概率大幅降低 |
| 使用索引 | 不加索引的行锁退化为表锁，增加死锁概率 |
| 热点行拆分 | 减少对同一行的并发更新（如库存拆多条记录） |
| 减少锁竞争 | 考虑乐观锁（版本号）替代悲观锁 |

**生产踩坑：**

- **死锁不要一味靠超时等待**：`innodb_lock_wait_timeout`（默认 50s）等待太慢影响用户体验。建议结合业务重试机制，捕获死锁异常（MySQL 错误码 1213）后自动重试。
- **禁掉死锁检测来提升并发**：`innodb_deadlock_detect=OFF` 在高并发热点更新场景下可以减少检测开销，但死锁不检测时会锁等待超时。适用于确定不会死锁的场景（如单行更新）。
- **RC 下也有死锁**：虽然 RC 没有 Gap Lock，但 Record Lock 仍然可能死锁。
- **`SELECT ... FOR UPDATE` 和 `UPDATE` 在二级索引上的加锁范围可能不同**，容易引起死锁。建议多用 `FOR UPDATE` 同一锁。

### 4.3 乐观锁 vs 悲观锁

**悲观锁（Pessimistic Locking）：**

- 默认认为冲突会发生，操作数据前先加锁。
- MySQL 实现：`SELECT ... FOR UPDATE`、`SELECT ... LOCK IN SHARE MODE`。
- 适用：写冲突频繁的场景（如库存扣减）。

```sql
-- 悲观锁扣库存
BEGIN;
SELECT stock FROM product WHERE id = 1 FOR UPDATE;  -- 锁定该行
-- 业务检查: stock > 0
UPDATE product SET stock = stock - 1 WHERE id = 1;
COMMIT;
```

**乐观锁（Optimistic Locking）：**

- 默认认为冲突不会发生，提交时检查版本号。
- 实现：版本号（version）或时间戳（timestamp）。
- 适用：写冲突少的场景（如配置更新）。

```sql
-- 乐观锁扣库存（version 版本号）
-- Step 1: 读取数据
SELECT id, stock, version FROM product WHERE id = 1;
-- 假设: stock=5, version=3

-- Step 2: 更新时检查版本号
UPDATE product SET stock = stock - 1, version = version + 1
WHERE id = 1 AND version = 3;
-- 受影响行数为 0 → 冲突，重试
```

**选择策略：**

```text
写冲突频率高  → 悲观锁（减少重试开销）
写冲突频率低  → 乐观锁（减少锁开销）
并发要求高    → 乐观锁（无锁等待）
一致性要求严格 → 悲观锁（可串行化保证）

典型场景：
- 秒杀/库存扣减 → 悲观锁（或 Redis 分布式锁 + MySQL 兜底）
- 表单提交/配置更新 → 乐观锁（版本号）
- 金融转账 → 悲观锁（一致性优先）
```

### 4.4 意向锁（Intention Lock）

**定义：** InnoDB 在加行锁前，自动在表级别加的锁。用于快速判断表是否已被行锁锁定，无需逐行检查。

- **意向共享锁 (IS)**：事务准备给某些行加共享锁（如 `SELECT ... LOCK IN SHARE MODE`）。
- **意向排他锁 (IX)**：事务准备给某些行加排他锁（如 `SELECT ... FOR UPDATE`、`UPDATE`、`DELETE`）。

**锁定兼容性矩阵：**

| 当前锁\请求锁 | X | IX | S | IS |
|:---:|:---:|:---:|:---:|:---:|
| X | 冲突 | 冲突 | 冲突 | 冲突 |
| IX | 冲突 | 兼容 | 冲突 | 兼容 |
| S | 冲突 | 冲突 | 兼容 | 兼容 |
| IS | 冲突 | 兼容 | 兼容 | 兼容 |

- X/S 是表级锁（如 `LOCK TABLES ... WRITE`）。
- IX/IS 是意向锁，只表明"正在准备加行锁"。
- **意向锁不阻塞全表扫描**，只阻塞表级 `LOCK TABLES` 命令。

**面试高频题：**

> **Q: 没有意向锁会有什么问题？**
>
> A: 假如事务 A 要锁住表做 `LOCK TABLES user WRITE`，需要判断是否已有行锁。没有意向锁时，需逐行扫描所有行锁，效率极低。有意向锁，只需检查表的 IX/IS 锁即可快速判断。这是表级锁与行级锁协作的关键设计。

---

## 5. 事务与隔离级别

### 5.0 ACID 事务属性

ACID 是事务的四个核心保证，InnoDB 通过不同机制分别实现：

| 属性 | 含义 | InnoDB 实现机制 |
|------|------|----------------|
| **Atomicity 原子性** | 事务内所有操作要么全部成功，要么全部回滚 | **Undo Log**：记录每步操作的逆操作，失败时逐条回滚 |
| **Consistency 一致性** | 事务执行前后数据库从一个合法状态到另一个合法状态 | 业务约束 + 其他三个特性共同保证（唯一键、外键、Check 约束） |
| **Isolation 隔离性** | 并发事务之间互不干扰 | **MVCC**（快照读）+ **锁机制**（当前读） |
| **Durability 持久性** | 提交后的事务永久生效，即使崩溃也不丢失 | **Redo Log** + `fsync()`：WAL 机制保证已提交修改落盘 |

**各属性对应的 InnoDB 组件：**

```
Atomicity   ←── Undo Log（回滚段）
Consistency ←── 约束检查 + A、I、D 三者共同维护
Isolation   ←── MVCC Read View + Gap Lock / Next-Key Lock
Durability  ←── Redo Log (WAL) + innodb_flush_log_at_trx_commit=1
```

**面试高频题：**

> **Q: 一致性(C)和其他三个属性是什么关系？**
>
> A: 一致性是**目的**，原子性、隔离性、持久性是**手段**。A/I/D 从不同角度保护数据不被破坏，最终使数据库始终满足业务定义的约束（合法状态）。即使 AID 都满足，如果业务逻辑本身有漏洞，一致性仍可能被破坏。

> **Q: Undo Log 同时支持原子性和 MVCC，两个用途有什么区别？**
>
> A: 原子性场景下，事务回滚时按照 Undo Log 链逐步撤销已执行的操作；MVCC 场景下，Undo Log 中的历史版本**不会被删除**（只要还有事务需要），供一致性读取旧版本数据。Purge 线程负责清理不再被任何活跃事务引用的旧版本。

### 5.1 四种隔离级别实现原理

| 隔离级别 | 脏读 | 不可重复读 | 幻读 |
|:---:|:---:|:---:|:---:|
| READ UNCOMMITTED (RU) | 可能 | 可能 | 可能 |
| READ COMMITTED (RC) | 避免 | 可能 | 可能 |
| REPEATABLE READ (RR) | 避免 | 避免 | 可能（InnoDB 可避免） |
| SERIALIZABLE | 避免 | 避免 | 避免 |

**InnoDB 各隔离级别实现：**

- **RU**：不使用 MVCC，直接读最新版本。不使用锁。
- **RC**：每个语句执行前生成新的 Read View。写加 Record Lock（无 Gap Lock）。
- **RR**：事务第一个快照读时生成 Read View，复用整个事务。写加 Next-Key Lock（含 Gap Lock）。
- **SERIALIZABLE**：隐式将普通 `SELECT` 转为 `SELECT ... LOCK IN SHARE MODE`，所有读都是当前读。

**设置与查看：**

```sql
-- 查看当前隔离级别
SELECT @@transaction_isolation;  -- 8.0+
SELECT @@tx_isolation;          -- 5.7-

-- 设置隔离级别
SET SESSION TRANSACTION ISOLATION LEVEL READ COMMITTED;
SET GLOBAL TRANSACTION ISOLATION LEVEL READ COMMITTED;
```

**面试高频题：**

> **Q: MySQL 的 RR 级别能完全避免幻读吗？**
>
> A: 不能完全保证。快照读通过 MVCC（Read View）看到事务开始时的数据快照，不会看到新插入的行。但如果事务中途执行当前读（`SELECT ... FOR UPDATE`、`UPDATE`、`DELETE`），Gap Lock 防止其他事务插入新行，但不一定覆盖所有条件——如果 INSERT 插入的行不在锁的间隙内，当前读仍可能看到新行。理论上 InnoDB RR + 当前读的组合能避免幻读，但严格来说，"完全避免幻读"需要 SERIALIZABLE 级别。

> **Q: 为什么大多数公司将隔离级别设为 RC 而不是 RR？**
>
> A:
> 1. 无 Gap Lock，死锁概率低。
> 2. 更高的并发性能。
> 3. 主从复制在 RC 下支持基于行的 binlog，避免 RR 下某些 SQL 导致主从不一致。
> 4. 大多数业务能接受"不可重复读"（大不了再查一次），但不能接受数据不一致或死锁。
> 5. **阿里等一线互联网公司普遍使用 RC。**

> **Q: 隔离级别实现原理中，SERIALIZABLE 和 RR 的本质区别？**
>
> A: RR 的普通 SELECT 是快照读（不加锁），SERIALIZABLE 的普通 SELECT 也是当前读（隐式加共享锁）。SERIALIZABLE 将所有读操作转化为 `LOCK IN SHARE MODE`，写操作阻塞所有读操作，所以完全没有并发问题，但并发极低。

### 5.2 脏读、幻读、不可重复读

**脏读（Dirty Read）：**

一个事务读到另一个事务未提交的数据。

```sql
-- 事务 A                          -- 事务 B
-- SET SESSION tx_isolation='READ-UNCOMMITTED';
BEGIN;                            BEGIN;
UPDATE account SET balance = 1000 WHERE id = 1;  -- 未提交
SELECT balance FROM account WHERE id = 1;
-- 读到 1000（脏数据！A 可能回滚）
                                  ROLLBACK;  -- 事务 B 回滚
-- 实际余额还是 0，但 A 已经读到 1000
COMMIT;
```

**不可重复读（Non-Repeatable Read）：**

同一事务内，两次读取同一条记录，结果不同。

```sql
-- 事务 A（RC 级别）                -- 事务 B
BEGIN;
SELECT balance FROM account WHERE id = 1;
-- 读到 500
                                  UPDATE account SET balance = 1000 WHERE id = 1;
                                  COMMIT;
SELECT balance FROM account WHERE id = 1;
-- 读到 1000（同一事务两次读结果不同！）
COMMIT;
```

**幻读（Phantom Read）：**

同一事务内，两次范围查询，结果集的行数不同（有其他事务插入了新行）。

```sql
-- 事务 A（RR 级别，快照读不会有幻读）
BEGIN;
SELECT * FROM account WHERE balance > 500;
-- 返回 2 行
                                  INSERT INTO account (id, balance) VALUES (3, 800);
                                  COMMIT;
SELECT * FROM account WHERE balance > 500;
-- RR 级别快照读仍返回 2 行（MVCC）
-- 但如果执行当前读：
SELECT * FROM account WHERE balance > 500 FOR UPDATE;
-- 返回 3 行（幻读！）—— Gap Lock 未能阻止
```

### 5.3 分布式事务 XA

MySQL 支持 XA 分布式事务协议，允许一个事务跨越多个数据库实例。

**XA 事务两阶段提交（2PC）：**

```
                     ┌─────────────┐
                     │  TM (应用)    │
                     └──────┬──────┘
                            │
               ┌───────────────────┐
               │      第一阶段      │
               │  PREPARE (就绪)    │
               └───────────────────┘
              /                    \
       ┌─────┴──────┐        ┌────┴──────┐
       │  RM1 (MySQL)│        │ RM2 (MySQL)│
       │  PREPARE OK │        │ PREPARE OK │
       └──────┬──────┘        └──────┬─────┘
              \                     /
               └───────────────────┘
               │      第二阶段      │
               │  COMMIT (提交)     │
               └───────────────────┘
              /                    \
       ┌─────┴──────┐        ┌────┴──────┐
       │  RM1 (MySQL)│        │ RM2 (MySQL)│
       │  COMMIT OK  │        │ COMMIT OK  │
       └────────────┘        └────────────┘
```

**XA SQL 语法：**

```sql
-- XA 开始
XA START 'xid1';

-- 执行 SQL
UPDATE account SET balance = balance - 100 WHERE id = 1;
UPDATE account SET balance = balance + 100 WHERE id = 2;

-- 第一阶段：PREPARE
XA PREPARE 'xid1';

-- 第二阶段：COMMIT
XA COMMIT 'xid1';

-- 或 ROLLBACK
XA ROLLBACK 'xid1';

-- 查看未决的 XA 事务
XA RECOVER;
```

**面试高频题：**

> **Q: XA 事务的优缺点？**
>
> A:
> - 优点：强一致性，所有节点要么全部成功要么全部失败，跨多个数据库的 ACID 保证。
> - 缺点：
>   - **性能开销大**：2PC 需要多次网络往返，准备阶段锁定资源直到提交，锁持有时间长。
>   - **单点阻塞**：TM 崩溃时，RM 一直持有锁，无法释放（需要人工介入 `XA RECOVER` + `XA COMMIT`/`XA ROLLBACK`）。
>   - **扩展性差**：不能应对微服务架构下大量分布式事务。
>   - **不适用于高并发**：生产环境高并发场景下很少使用 XA。

> **Q: 生产中分布式事务的主流方案是？**
>
> A: 微服务架构下更常用的方案：
> - **TCC (Try-Confirm-Cancel)**：业务层面的两阶段提交。
> - **Saga**：长事务拆分多个本地事务 + 补偿。
> - **Seata**：阿里开源的分布式事务框架（AT 模式 + TCC 模式）。
> - **最终一致性 + 消息队列**：本地消息表 + MQ 异步确保。
> XA 更多用于跨数据库的强一致性场景（如跨 MySQL 实例的转账）。

---

## 6. 高可用架构

### 6.1 主从复制

**复制原理：**

```
主库 (Source)                   从库 (Replica)
    │                               │
    ├── 写入 Binlog ───────→ 拉取 Relay Log
    │   (Binary Log)         (I/O Thread)
    │                               │
    │                          ┌─────┴─────┐
    │                          │ I/O Thread │
    │                          │ 写入 Relay │
    │                          │ Log        │
    │                          └────────────┘
    │                               │
    │                          ┌─────┴─────┐
    │                          │ SQL Thread │
    │                          │ 回放 Relay │
    │                          │ Log        │
    │                          └────────────┘
    │                               │
    │                          ┌─────┴─────┐
    │                          │ 数据同步完毕│
    │                          └───────────┘
```

**三个线程：**

- **主库 Dump Thread**：读取 Binlog 并发送给从库。
- **从库 I/O Thread**：接收主库的 Binlog 事件并写入 Relay Log。
- **从库 SQL Thread**：读取 Relay Log 并在从库上回放。

**完整搭建流程（异步复制，8.0 语法）：**

```
Step 1 主库 my.cnf
Step 2 主库创建复制账号
Step 3 获取主库位点（或开启 GTID）
Step 4 从库 my.cnf
Step 5 从库执行 CHANGE REPLICATION SOURCE TO
Step 6 启动从库复制线程并验证
```

```ini
# ── Step 1：主库 my.cnf ──────────────────────────────────────
[mysqld]
server-id          = 1            # 集群内唯一，主库一般设 1
log_bin            = /var/log/mysql/binlog   # 开启 Binlog
binlog_format      = ROW          # 生产必选 ROW
sync_binlog        = 1            # 每次提交刷盘，防丢失
binlog_expire_logs_seconds = 604800  # Binlog 保留 7 天（8.0+）
gtid_mode          = ON           # 推荐开启 GTID（可选，但强烈建议）
enforce_gtid_consistency = ON
```

```sql
-- Step 2：主库创建复制账号
CREATE USER 'repl'@'%' IDENTIFIED WITH mysql_native_password BY 'StrongPass!';
GRANT REPLICATION SLAVE ON *.* TO 'repl'@'%';
FLUSH PRIVILEGES;
```

```sql
-- Step 3a：基于 Binlog 位点（非 GTID）
-- 主库执行，记录 File 和 Position
FLUSH TABLES WITH READ LOCK;      -- 短暂锁表获取一致性位点
SHOW MASTER STATUS;               -- 记录 File / Position
-- 此时做全量备份（mysqldump / Xtrabackup）
UNLOCK TABLES;

-- Step 3b：开启 GTID 时不需要记录位点，GTID 自动对齐
```

```ini
# ── Step 4：从库 my.cnf ──────────────────────────────────────
[mysqld]
server-id          = 2            # 与主库不同，多从库各自唯一
relay_log          = /var/log/mysql/relay-bin
log_bin            = ON           # 从库也建议开启，便于级联复制
read_only          = ON           # 从库只读保护
super_read_only    = ON           # 防止 super 用户误写（8.0 强烈建议）
gtid_mode          = ON
enforce_gtid_consistency = ON
replica_parallel_workers   = 4   # 并行回放线程数（5.7+ 推荐）
replica_parallel_type      = LOGICAL_CLOCK
```

```sql
-- Step 5：从库执行（8.0 语法，5.7 用 CHANGE MASTER TO / SLAVE）
-- 基于 GTID（推荐）
CHANGE REPLICATION SOURCE TO
  SOURCE_HOST     = '主库IP',
  SOURCE_PORT     = 3306,
  SOURCE_USER     = 'repl',
  SOURCE_PASSWORD = 'StrongPass!',
  SOURCE_AUTO_POSITION = 1;     -- GTID 自动对齐，无需指定位点

-- 基于 Binlog 位点（非 GTID）
CHANGE REPLICATION SOURCE TO
  SOURCE_HOST     = '主库IP',
  SOURCE_PORT     = 3306,
  SOURCE_USER     = 'repl',
  SOURCE_PASSWORD = 'StrongPass!',
  SOURCE_LOG_FILE = 'binlog.000003',   -- Step 3a 记录的值
  SOURCE_LOG_POS  = 1234;
```

```sql
-- Step 6：启动并验证
START REPLICA;                    -- 8.0（5.7 用 START SLAVE）
SHOW REPLICA STATUS\G             -- 8.0（5.7 用 SHOW SLAVE STATUS）
-- 关键字段：
--   Replica_IO_Running:  Yes    ← I/O 线程正常
--   Replica_SQL_Running: Yes    ← SQL 线程正常
--   Seconds_Behind_Source: 0    ← 无延迟（5.7 是 Seconds_Behind_Master）
--   Last_IO_Error / Last_SQL_Error: 无报错
```

> **GTID vs 位点复制选哪个？**  生产优先 GTID。GTID 全局唯一标识每个事务，Failover 换主库时无需手动计算位点，`SOURCE_AUTO_POSITION=1` 自动对齐，极大降低运维复杂度。

**复制模式：**

| 模式 | 说明 | 一致性 | 性能影响 |
|------|------|--------|----------|
| 异步复制 | 默认模式，主库提交后不等从库确认 | 最终一致性（主库崩溃可能丢数据） | 无影响 |
| 半同步复制 | 至少一个从库收到并写入 Relay Log 后主库才返回提交成功 | 不丢数据（但可能延迟） | 有影响（需等待从库 ACK） |
| 组复制 MGR | 基于 Paxos 的组内自动选主，多点写入 | 强一致性(组内) | 网络开销大 |

**半同步复制配置：**

```sql
-- 主库
INSTALL PLUGIN rpl_semi_sync_source SONAME 'semisync_source.so';  -- 8.0+
SET GLOBAL rpl_semi_sync_source_enabled = 1;

-- 从库
INSTALL PLUGIN rpl_semi_sync_replica SONAME 'semisync_replica.so'; -- 8.0+
SET GLOBAL rpl_semi_sync_replica_enabled = 1;

-- 主库设置等待超时（超时后降级为异步）
SET GLOBAL rpl_semi_sync_source_timeout = 10000; -- 10秒
```

**面试高频题：**

> **Q: 主从延迟的原因有哪些？如何处理？**
>
> A:
> **原因：**
> 1. 主库有大量写入并发，从库单线程回放（5.6 前）。
> 2. 从库 SQL Thread 单线程执行（即使 5.6+ 的并行复制，仍有局限）。
> 3. 从库硬件配置差（CPU/IO/网络）。
> 4. 大事务（如 `DELETE` 大量行）导致 Binlog 巨大。
> 5. 从库还在执行 `ANALYZE TABLE`、备份等操作。
>
> **解决方案：**
> 1. 5.7+ 启用并行复制（`slave_parallel_workers > 0`，`slave_parallel_type = LOGICAL_CLOCK`）。
> 2. 拆分大事务为小批量提交。
> 3. 增强从库硬件配置。
> 4. 监控延迟：`SHOW SLAVE STATUS` 中的 `Seconds_Behind_Master`。
> 5. 读写分离中读从库时，强制走主库返回实时数据（或延迟读控制）。

> **Q: 主库宕机后如何选新主（Failover）？**
>
> A:
> - **手动切换**：确认数据差异（`pt-heartbeat`）、补传缺失 Binlog、`STOP SLAVE`、`RESET SLAVE ALL`、提升为独立主库、切换应用连接。
> - **MHA (Master High Availability)**：自动监控、选新主、补传日志、VIP 切换。但 MHA 已停止维护，建议 MGR 或 Orchestrator。
> - **Orchestrator**：现代化 MySQL HA 管理工具，支持 Failover、拓扑管理、Web UI。
> - **MGR**：使用 MySQL Group Replication，组内自动选主，无需手动干预。

### 6.2 读写分离

**架构模式：**

```
            ┌─────────────────────────────────┐
            │        Proxy (ProxySQL/MyCat)    │
            │  解析 SQL 请求，区分读写          │
            └────┬─────────────────┬───────────┘
                 │                 │
         ┌───────┴───────┐ ┌──────┴────────┐
         │   Write Node   │ │  Read Nodes    │
         │   (主库)       │ │  (从库1,2,3...)│
         │   写入请求      │ │   只读请求      │
         └───────────────┘ └───────────────┘
```

**实现方案：**

| 方案 | 优点 | 缺点 |
|------|------|------|
| 应用层配置多数据源（ShardingSphere-JDBC） | 无额外组件，性能好 | 业务侵入，配置分散 |
| 中间件代理（ProxySQL、MyCat） | 配置灵活，对应用透明 | 增加网络跳数和延迟 |
| MySQL 8.0 Router | 官方方案，简单 | 功能有限 |

**ProxySQL 配置要点：**

```ini
# 读写分离规则示例
mysql_servers = (
    { address="10.0.0.1", port=3306, hostgroup=10, comment="主库" },
    { address="10.0.0.2", port=3306, hostgroup=20, comment="从库1" },
    { address="10.0.0.3", port=3306, hostgroup=20, comment="从库2" }
)

mysql_query_rules = (
    # SELECT 走从库
    { rule_id=1, active=1, match_pattern="^SELECT", destination_hostgroup=20 },
    # 其余走主库
    { rule_id=2, active=1, match_pattern=".*", destination_hostgroup=10 }
)
```

**生产踩坑：**

- **主从延迟导致的"读不到刚写入的数据"**：在 ProxySQL 中设置 `SELECT` 走主库的规则（如 session 级别 cookie 或特定表）。
- **事务内的读必须走主库**：事务中读取数据应使用主库，避免"自己写的数据读不到"。ShardingSphere-JDBC 会自动处理（事务内不走从库）。
- **从库多时的负载均衡**：在高并发下，从库间的负载不均衡需关注，ProxySQL 支持多种均衡算法（Least Connections、First Available 等）。

### 6.3 分库分表

**分库分表策略：**

| 策略 | 说明 | 适用场景 |
|------|------|----------|
| 垂直分库 | 按业务拆分到不同数据库（用户库、订单库） | 微服务架构 |
| 水平分表 | 同一个表拆成多个物理表（user_0~user_127） | 单表数据量过大 |
| 分库分表 | 同时拆库和拆表 | 超大规模 |

**分片键选择：**

```text
原则：
1. 业务高频查询的字段作为分片键。
2. 尽量保证数据均匀分布（避免热点）。
3. 跨分片查询尽量避免。

典型的错误选法：用时间戳做主分片键 → 数据倾斜（写集中在最新分片）。
推荐选法：用户 ID、订单 ID 做 Hash 分片。
```

**分片算法：**

| 算法 | 说明 | 优点 | 缺点 |
|------|------|------|------|
| 取模 | `user_id % 128` | 简单，分布均匀 | 扩缩容困难 |
| 范围 | `user_id in [1-1000000] → 分片1` | 扩容简单 | 数据分布不均 |
| 一致性哈希 | 环形 Hash | 扩容影响小 | 实现复杂 |
| 时间分片 | `202501` → 分片1 | 方便归档 | 热点问题 |

**跨分片问题：**

| 问题 | 说明 | 解决方案 |
|------|------|----------|
| 跨分片 Join | 分片间无法做 Join | 应用层做数据拼装（多次查询）或冗余表 |
| 跨分片聚合 | COUNT/SUM/SORT 需要在各分片聚合 | 中间件自动处理（ShardingSphere） |
| 全局主键 | 各分片自增 ID 会重复 | Snowflake、Leaf（美团）、TinyID（百度） |
| 分布式事务 | 跨分片写入的事务一致性 | Seata AT/TCC、本地消息表 |
| 跨分片分页 | `LIMIT 10 OFFSET 1000` 在各分片取 1010 行再聚合 | 合理设计分页，避免深翻页；用"游标翻页"替代 |

**ShardingSphere-JDBC 示例（YAML）：**

```yaml
rules:
  - !SHARDING
    tables:
      order:
        actualDataNodes: ds${0..3}.order_${0..31}
        tableStrategy:
          standard:
            shardingColumn: user_id
            shardingAlgorithmName: order_table_inline
        databaseStrategy:
          standard:
            shardingColumn: user_id
            shardingAlgorithmName: order_database_inline
    shardingAlgorithms:
      order_table_inline:
        type: INLINE
        props:
          algorithm-expression: order_${user_id % 32}
      order_database_inline:
        type: INLINE
        props:
          algorithm-expression: ds${user_id % 4}
    keyGenerators:
      snowflake:
        type: SNOWFLAKE
```

**生产踩坑：**

- **不要过早分库分表**：先优化慢查询、加索引、引入缓存、分区表（Partition）。数据量达到千万级且持续增长时再考虑。分库分表带来的复杂度远高于收益。
- **分片后的查询模式重构**：业务查询必须带分片键，否则就是"全分片广播查询"——性能灾难。
- **不停机扩容**：原取模 32 扩到 64 需要迁移数据。方案：（1）新老分片双写；（2）在线迁移工具；（3）一致性哈希减少影响。
- **去中心化 ID 生成器的时钟回拨问题**：Snowflake 依赖服务器时间，时钟回拨会导致 ID 冲突。美团 Leaf、百度 TinyID 有对应的解决方案。

---

## 7. 生产运维

### 7.1 备份恢复

**备份策略推荐：**

```text
日常备份：全量(每周日) + 增量(每天) + Binlog 实时备份(每 5 分钟)
保留周期：最近 7 天每日备份 + 最近 4 周每周备份 + 最近 12 月每月备份
```

**Xtrabackup（Percona XtraBackup）：**

物理备份工具，支持 InnoDB 热备（不锁表）。

```bash
# 全量备份
xtrabackup --backup --target-dir=/backup/full/20250601 \
  --datadir=/var/lib/mysql \
  --user=backup --password=xxx

# 全量恢复
xtrabackup --prepare --target-dir=/backup/full/20250601
xtrabackup --copy-back --target-dir=/backup/full/20250601 \
  --datadir=/var/lib/mysql

# 增量备份
xtrabackup --backup --target-dir=/backup/inc/20250602 \
  --incremental-basedir=/backup/full/20250601

# 增量恢复（先 prepare 基础备份，再 apply 增量）
xtrabackup --prepare --apply-log-only --target-dir=/backup/full/20250601
xtrabackup --prepare --apply-log-only \
  --target-dir=/backup/full/20250601 \
  --incremental-dir=/backup/inc/20250602
```

**mydumper / myloader（多线程逻辑备份）：**

```bash
# 多线程导出（压缩 + 并行加速）
mydumper -h localhost -u backup -p xxx -B mydb \
  --outputdir=/backup/mydb_20250601 \
  --threads=4 --compress

# 多线程导入
myloader -h localhost -u root -p xxx \
  --directory=/backup/mydb_20250601 \
  --threads=4 --overwrite-tables
```

**备份策略选择：**

| 备份类型 | 工具 | 优点 | 缺点 |
|----------|------|------|------|
| 物理备份 | Xtrabackup | 速度快，支持全部 InnoDB 引擎 | 文件体积大，跨版本兼容差 |
| 逻辑备份 | mysqldump / mydumper | 跨版本兼容，可选择性恢复 | 导出慢，恢复更慢 |
| Binlog 备份 | `mysqlbinlog` | 细粒度时间点恢复（PITR） | 必须保证 Binlog 持续可用 |

**生产踩坑：**

- **备份验证不可少**：备份后不验证 = 没备份。定期从备份恢复到一个测试实例并执行完整性检查。
- **`mysqldump --single-transaction`**：对 InnoDB 做一致性快照，不影响业务写入。但不要用 `--lock-all-tables`。
- **Xtrabackup 对大表的** `--prepare` 阶段需要大量内存和 IO。生产恢复时预留足够时间。
- **PITR (Point-In-Time Recovery)**：
  ```bash
  # 恢复到指定时间点
  # 1. 恢复最近的全量备份
  xtrabackup --prepare --target-dir=/backup/full/20250601
  # 2. 应用增量备份（如果有）
  # 3. 应用 Binlog
  mysqlbinlog --start-datetime="2025-06-01 00:00:00" \
    --stop-datetime="2025-06-01 10:23:59" \
    mysql-bin.000001 mysql-bin.000002 | mysql -h localhost
  ```

### 7.2 监控指标

**关键监控指标（黄金指标）：**

| 指标 | 重要性 | 阈值 |
|------|--------|------|
| **QPS (Queries Per Second)** | 吞吐量 | 对比基线，突增 50% 报警 |
| **TPS (Transactions Per Second)** | 事务吞吐量 | 对比基线 |
| **活跃连接数** `Threads_running` | 并发压力 | < CPU核数×2，> 50 需关注 |
| **缓存命中率** | 内存效率 | > 99% 优，< 95% 需增加 Buffer Pool |
| **慢查询数** `Slow_queries` | 性能问题 | 长期 > 0 需排查 |
| **主从延迟** `Seconds_Behind_Master` | 复制健康 | < 10s 正常，> 30s 报警 |
| **磁盘空间** | 容量 | < 20% 需扩容或清理 |
| **IOPS / IO 延迟** | 磁盘健康 | fio 测试确认基线 |

**监控采集 SQL：**

```sql
-- 吞吐量
SHOW GLOBAL STATUS LIKE 'Queries';       -- 总查询数
SHOW GLOBAL STATUS LIKE 'Innodb_rows_read';
SHOW GLOBAL STATUS LIKE 'Innodb_rows_inserted';
SHOW GLOBAL STATUS LIKE 'Innodb_rows_updated';
SHOW GLOBAL STATUS LIKE 'Innodb_rows_deleted';

-- 连接数
SHOW GLOBAL STATUS LIKE 'Threads_connected';  -- 当前连接数
SHOW GLOBAL STATUS LIKE 'Threads_running';    -- 运行中连接数
SHOW GLOBAL VARIABLES LIKE 'max_connections'; -- 最大连接数

-- 缓冲池
SHOW GLOBAL STATUS LIKE 'Innodb_buffer_pool_read_requests';
SHOW GLOBAL STATUS LIKE 'Innodb_buffer_pool_reads';
-- 命中率 = (read_requests - reads) / read_requests * 100%

-- 临时表
SHOW GLOBAL STATUS LIKE 'Created_tmp_tables';
SHOW GLOBAL STATUS LIKE 'Created_tmp_disk_tables';
-- 磁盘临时表比例 = Created_tmp_disk_tables / Created_tmp_tables
-- > 10% 需优化 SQL

-- 锁等待
SHOW GLOBAL STATUS LIKE 'Innodb_row_lock_current_waits';
SHOW GLOBAL STATUS LIKE 'Innodb_row_lock_time_avg';

-- 慢查询
SHOW GLOBAL STATUS LIKE 'Slow_queries';

-- 复制状态
SHOW SLAVE STATUS\G
-- Slave_IO_Running: Yes
-- Slave_SQL_Running: Yes
-- Seconds_Behind_Master: 0
```

**Prometheus + Grafana 监控方案：**

```yaml
# mysqld_exporter 配置 (.my.cnf)
[client]
host=localhost
port=3306
user=exporter
password=xxx
```

```yaml
# prometheus target
- job_name: 'mysql'
  static_configs:
    - targets: ['10.0.0.1:9104']
      labels:
        alias: 'db-master'
```

**面试高频题：**

> **Q: 100% 的 Buffer Pool 命中率就一定好吗？**
>
> A: 不一定。100% 可能意味着：
> - Buffer Pool 过大，浪费内存。
> - 数据量太小，全量都在内存中。
> - 长期不变的冷数据占满 Buffer Pool，真正的热数据没有足够空间。
> 需要结合 `Innodb_buffer_pool_wait_free`（等待空闲页次数）和 `Innodb_buffer_pool_dirty_pages`（脏页数量）综合评估。

> **Q: 线上 MySQL 突然变慢，怎么排查？**
>
> A:
> 1. **先看系统指标**：CPU/IO/网络/内存 —— `top`、`iostat`、`vmstat`。
> 2. **看 MySQL 状态**：
>    - `SHOW FULL PROCESSLIST` 查长时间运行的 Query。
>    - `SHOW ENGINE INNODB STATUS` 查锁等待和事务。
>    - `SHOW GLOBAL STATUS` 查 QPS/慢查询等指标突变。
> 3. **查慢查询日志**：是否出现了新的慢查询模式。
> 4. **查 IO 压力和 Buffer Pool**：是否 Buffer Pool 过低导致频繁磁盘读取。
> 5. **查后台任务**：`ANALYZE TABLE`、`OPTIMIZE TABLE`、备份进程。
> 6. **查锁等待和死锁**：`SHOW PROCESSLIST` 中看到大量 `Waiting for table level lock` 或 `Lock wait timeout`。

### 7.3 参数调优

**8G 内存典型配置（仅供参考，需结合具体业务调整）：**

```ini
[mysqld]
# 基础设置
port = 3306
datadir = /var/lib/mysql
socket = /var/lib/mysql/mysql.sock
pid-file = /var/run/mysqld/mysqld.pid

# 字符集
character-set-server = utf8mb4
collation-server = utf8mb4_unicode_ci

# 连接
max_connections = 500
max_connect_errors = 1000
wait_timeout = 600
interactive_timeout = 600

# 内存
innodb_buffer_pool_size = 5G          # 物理内存的 60-70%
innodb_buffer_pool_instances = 8       # 减少锁争用
innodb_log_file_size = 1G              # Redo Log 大小
innodb_log_buffer_size = 64M           # 日志缓冲
join_buffer_size = 2M                  # Join Buffer (每连接)
sort_buffer_size = 2M                  # 排序 Buffer (每连接)

# IO 与刷盘
innodb_io_capacity = 2000              # 磁盘 IOPS 能力
innodb_io_capacity_max = 4000
innodb_flush_log_at_trx_commit = 1     # 重要数据必须为 1
innodb_flush_method = O_DIRECT         # 绕过 OS Cache
innodb_adaptive_flushing = ON          # 自适应刷脏页

# 事务隔离级别（一线互联网普遍使用 RC）
transaction_isolation = READ-COMMITTED

# Binlog
log_bin = mysql-bin
binlog_format = ROW                    # 推荐 ROW 模式
binlog_row_image = minimal             # 减少 binlog 体积
expire_logs_days = 7                   # 7 天自动清理
sync_binlog = 1                        # 事务提交时同步刷 binlog

# 慢查询
slow_query_log = ON
long_query_time = 1
min_examined_row_limit = 1000

# 临时表
tmp_table_size = 64M
max_heap_table_size = 64M

# 复制 (从库配置)
# replica_parallel_workers = 4          # 并行回放线程数 (5.7+)
# replica_parallel_type = LOGICAL_CLOCK

# 其他
table_open_cache = 4000
thread_cache_size = 128
max_allowed_packet = 64M
sql_mode = STRICT_TRANS_TABLES,NO_ENGINE_SUBSTITUTION,ONLY_FULL_GROUP_BY
```

**参数调优原则：**

```text
1. 先改最需要的：Buffer Pool 大小 > Redo Log 大小 > IO 参数 > 连接数
2. 每次只改一个：分批调整，确认效果
3. 基于监控数据：调优前必须记录基线
4. 结合硬件配置：不同硬件（HDD/SSD/NVMe）参数差异大
5. 结合业务模式：OLTP（高并发小事务）和 OLAP（大查询）配置不同
```

**特定问题调优：**

| 问题 | 相关参数 | 调整方向 |
|------|----------|----------|
| 高并发连接数暴增 | `max_connections`、`max_connect_errors` | 增大 + 配合连接池 |
| 大量排序查询 | `sort_buffer_size` | 增大（但注意每连接独享） |
| 大查询临时表溢出 | `tmp_table_size`、`max_heap_table_size` | 增大或优化 SQL |
| 写入性能差 | `innodb_log_file_size`、`innodb_flush_log_at_trx_commit` | 调大 Redo Log |
| 死锁频繁 | `transaction_isolation` | 改为 RC |
| 主从延迟 | `slave_parallel_workers` | 开启并行复制 |

**生产踩坑：**

- **`sort_buffer_size` 和 `join_buffer_size` 不要设太大**：这两个是每连接独享的，500 连接乘 4M = 2G 内存瞬间耗尽。设为 2-4M 即可。
- **`innodb_flush_log_at_trx_commit=1` 和 `sync_binlog=1`** 是数据安全黄金组合，但写入性能最差。可以接受丢失 1 秒数据且性能敏感时，调整为 `2` 和 `0`。
- **`sql_mode` 不要默认**：生产建议用 `STRICT_TRANS_TABLES,NO_ENGINE_SUBSTITUTION,ONLY_FULL_GROUP_BY`，避免隐式类型转换和 GROUP BY 歧义。
- **`binlog_format=ROW` 是必须的**：`STATEMENT` 模式下，不安全 SQL（`UUID()`、`RAND()`）在从库回放结果不同于主库。但也注意 ROW 模式 binlog 可能很大，配合 `binlog_row_image=minimal` 减轻压力。

---

## 8. 与 PostgreSQL 对比分析

### 8.1 架构对比

| 维度 | MySQL (InnoDB) | PostgreSQL |
|------|----------------|------------|
| 许可证 | GPL / 双许可 | PostgreSQL License（类 MIT） |
| 进程模型 | 单进程多线程（一个线程处理一个连接） | 多进程（一个进程处理一个连接） |
| 存储引擎 | 插件式（InnoDB/MyISAM/...） | 内置堆表存储（无存储引擎概念） |
| 索引默认 | B+Tree | B-Tree |
| 支持索引类型 | B+Tree、Hash（Memory）、全文索引 | B-Tree、Hash、GiST、GIN、SP-GiST、BRIN、Bloom |
| 事务隔离 | RU / RC / RR / Serializable | RC / RR / Serializable（无 RU） |
| MVCC 实现 | Undo Log + 隐藏字段 | 存储在系统表中（同一行保留多个版本） |
| 并发控制 | 行锁 + MVCC | 行锁 + MVCC（快照过旧时需清理） |
| 复制 | 异步/半同步/组复制(MGR) | 流复制(同步/异步)、逻辑复制 |
| 全文搜索 | 内置全文索引（InnoDB 5.6+） | 内置 tsvector/tsquery，功能强大 |
| JSON 支持 | JSON 类型 (5.7+) | JSON/JSONB 类型，支持索引(GIN) |
| 扩展性 | 存储引擎接口 | 插件扩展（EXTENSION），社区强大 |

### 8.2 功能对比

**PostgreSQL 优势场景：**

| 场景 | 说明 |
|------|------|
| 复杂查询/OLAP | PG 查询优化器更强，支持 Merge Join、Hash Join 更成熟；支持 CTE、窗口函数、递归查询更完善 |
| 地理空间/GIS | PostGIS 扩展是业界标准，MySQL 的 GIS 支持较弱 |
| 自定义类型 | PG 支持 CREATE TYPE（枚举、复合类型、范围类型、域类型） |
| 全文搜索 | PG 内置高级全文搜索引擎（tsvector、tsquery、ranking），远胜 MySQL |
| 数组/JSONB | PG 原生支持数组类型、JSONB 类型支持 GIN 索引和 JSON 路径查询 |
| 并行查询 | PG 9.6+ 支持并行顺序扫描、并行 JOIN、并行聚合，效果好 |
| 临时表性能 | PG 临时表写入比 MySQL 快（临时表不写 WAL） |

**MySQL 优势场景：**

| 场景 | 说明 |
|------|------|
| 高并发 OLTP | MySQL InnoDB 在简单 CRUD 场景中吞吐量更高 |
| 读写分离/主从 | MySQL 主从生态成熟，ProxySQL/Orchestrator 等工具完善 |
| 存储过程/触发器语法 | 更接近开发者习惯（类 SQL 语法） |
| 在线 DDL | MySQL 8.0 的 INPLACE DDL 支持比 PG 好 |
| 运维工具生态 | Percona Toolkit、MySQL Shell、云数据库（RDS for MySQL）更成熟 |
| 迁移成本 | 从 SQL Server/Oracle 迁移到 MySQL 较容易 |

### 8.3 面试高频对比题

> **Q: MySQL 和 PostgreSQL 如何选择？**
>
> A:
> **选 MySQL 的场景：**
> - 纯 OLTP 业务，高并发简单 CRUD（电商、社交、SaaS）。
> - 团队更熟悉 MySQL 生态（运维、监控、备份）。
> - 需要用云数据库（RDS/阿里云/腾讯云对 MySQL 支持最好）。
> - 读写分离、分库分表需求明确（ShardingSphere/MyCat 生态成熟）。
>
> **选 PostgreSQL 的场景：**
> - OLAP 复杂分析查询、BI 报表。
> - 地理空间数据（PostGIS）、时序数据（TimescaleDB）。
> - JSON 数据查询量大（JSONB 索引和搜索能力）。
> - 需要高级自定义类型和函数。
> - 数据完整性要求极高（检查约束、排除约束）。

> **Q: MySQL 8.0 和 PostgreSQL 15+ 在 MVCC 方面的差异？**
>
> A: MySQL InnoDB 的 MVCC 版本链存储在 Undo Log 中，通过行上 `DB_ROLL_PTR` 指针串联。问题是长事务导致 Undo Log 膨胀，清理不及时影响性能。PG 的 MVCC 将新旧版本都存储在表中（同一行的不同 tuple），通过 `VACUUM` 清理旧版本。PG 的优势是没有 Undo Log 的概念和回滚段膨胀问题，但代价是 `VACUUM` 压力——如果更新频繁，表膨胀和 `VACUUM` 跟不上会导致性能急剧下降。

> **Q: 生产上哪个更容易出现表膨胀问题？**
>
> A: PG 更容易出现表膨胀。PG 的 MVCC 机制决定每次 UPDATE 都写入新行，旧行标记为死元组。如果更新频繁且 autovacuum 跟不上，表会急剧膨胀（一个 10GB 的表可能膨胀到 50GB+）。MySQL 的 InnoDB 是原地更新（Undo Log 存旧版本），表空间膨胀不如 PG 严重，但 Undo Log 膨胀也是问题。本质上两者在各层面有不同的 trade-off。

### 8.4 从 MySQL 迁往 PG 的踩坑点

```text
1. MySQL 的 "group by 可以选非聚合列"   → PG 必须严格按标准（所有非聚合列必须在 group by 中）。
2. MySQL 的 "隐式类型转换"               → PG 类型严格，不会自动转（'1' = 1 在 MySQL 为真，PG 报错）。
3. MySQL 的 "limit a,b" 分页             → PG 使用 "LIMIT b OFFSET a"。
4. MySQL 的 "`" 反引号引用标识符            → PG 使用双引号 ""。
5. MySQL 的 "show create table / show processlist" → PG 用 \d+ / SELECT * FROM pg_stat_activity。
6. MySQL 的 "replace into" "on duplicate key update" → PG 用 "INSERT ... ON CONFLICT DO UPDATE" (UPSERT)。
7. MySQL 的 "auto_increment"               → PG 用 "SERIAL" 或 "IDENTITY" (10+ 标准)。
8. MySQL 的 "explain 输出简单"              → PG 的 "explain (analyze, buffers, timing)" 详尽但复杂。
9. MySQL 的 "analyze table 快速"            → PG 的 "vacuum analyze" 可能耗时较长。
10. MySQL 全文搜索简单                      → PG 全文搜索需要建 tsvector 列和 GIN 索引。
```

---

## 附录

### A. 常用诊断 SQL 快速参考

```sql
-- 1. 查看当前运行中的查询
SELECT * FROM information_schema.PROCESSLIST WHERE COMMAND != 'Sleep';

-- 2. 查看当前所有事务（含锁等待）
SELECT * FROM information_schema.INNODB_TRX\G

-- 3. 查看事务锁等待
SELECT * FROM performance_schema.data_lock_waits\G  -- 8.0+

-- 4. 查看表大小
SELECT table_schema, table_name,
       ROUND(((data_length + index_length) / 1024 / 1024), 2) AS size_mb
FROM information_schema.tables
WHERE table_schema = 'your_db'
ORDER BY size_mb DESC;

-- 5. 查看索引使用情况（哪些索引未被使用）
SELECT * FROM sys.schema_unused_indexes;

-- 6. 查看全表扫描的查询
SELECT * FROM sys.statements_with_full_table_scans;

-- 7. 查看冗余索引
SELECT * FROM sys.schema_redundant_indexes;

-- 8. 查看 InnoDB 状态
SHOW ENGINE INNODB STATUS\G
```

### B. 推荐学习资源

- **《高性能 MySQL》(High Performance MySQL)**：第 3 版 / 即将第 4 版，MySQL 圣经。
- **MySQL 官方文档**：https://dev.mysql.com/doc/refman/8.0/en/
- **Percona Blog**：https://www.percona.com/blog/
- **《PostgreSQL 实战》**：彭煜玮，适合 PG 入门。
- **《数据库系统概念》**：Database System Concepts 第 7 版，理论基石。

### C. 面试经典 50 题（进阶）

```text
索引类：
1. B+Tree 索引在磁盘上是如何存储的？聚簇索引和非聚簇索引在物理存储上有什么区别？
2. 联合索引 (a, b, c) 在 B+Tree 中是如何排序的？为什么最左前缀？
3. ICP 条件下推到存储引擎层，具体下推了什么条件？所有 WHERE 条件都能下推吗？
4. MySQL 什么时候会选择全表扫描而不是索引扫描？优化器的 cost 模型是如何计算的？
5. 大翻页查询 LIMIT 100000, 20 如何优化？延迟关联到底层优化了什么？

锁与事务类：
6. Gap Lock 在唯一索引和非唯一索引上的加锁范围分别是什么？
7. Next-Key Lock 如何解决幻读？举例说明。
8. 一条 UPDATE 语句的加锁过程是怎样的？（分析 WHERE 条件、索引情况对加锁的影响）
9. RR 级别下 SELECT ... FOR UPDATE 和 UPDATE 的加锁范围一致吗？
10. MVCC 和 Gap Lock 在避免幻读上各自负责什么场景？
11. 长事务有什么危害？从 MVCC、Undo Log、Buffer Pool、DDL 四个维度分析。
12. MySQL 死锁检测的底层实现（Wait-For Graph）是怎样的？

架构与高可用类：
13. Binlog 三种格式的区别？为什么生产推荐 ROW 格式？
14. 主从延迟的本质原因？并行复制原理（LOGICAL_CLOCK 是如何确定并行的）？
15. MGR 与传统主从复制相比的优缺点？MGR 的 Paxos 实现细节？
16. 读写分离实现中，如何处理主从延迟导致的"写后读不到"？

优化与运维类：
17. 一条查询 SQL 从客户端发送到服务器返回结果，经历了哪些步骤？
18. MySQL 的 Join 是如何执行的？NLJ、BNL、Hash Join 的底层实现差异？
19. Hash Join 什么时候会优于 B+Tree 索引的 NLJ（即使有索引）？
20. 大表 ALTER TABLE 如何在线执行？pt-online-schema-change 的原理？
21. Buffer Pool 命中率 99% 但数据库仍然慢，可能的原因是什么？

对比类：
22. MySQL 和 PG 在 MVCC 实现上的本质区别（Undo Log vs 死元组）？
23. 什么场景下 PG 的表膨胀会比 MySQL 严重？如何处理？
24. PG 的 B-Tree 索引和 MySQL 的 B+Tree 索引在磁盘存储上的差异？
25. 从 OLTP 角度看，MySQL 和 PG 在并发控制上的优劣？
```

### D. 数据库三范式（3NF）

范式是关系型数据库设计的规范化标准，用于消除数据冗余和更新异常。

**第一范式 1NF — 原子性（列不可再分）**

每个列的值必须是不可分割的原子值，不允许出现"集合"或"重复列"。

```
❌ 违反 1NF：
orders(id, customer, phones)
phones 列存 "138xxx,139xxx" → 多值列

✅ 符合 1NF：
orders(id, customer)
customer_phones(order_id, phone)  ← 拆成独立行
```

**第二范式 2NF — 消除部分依赖（非主键列必须完全依赖主键）**

在满足 1NF 的基础上，非主键属性必须**完全依赖**于主键，不能只依赖联合主键的一部分。

```
❌ 违反 2NF（联合主键: order_id + product_id）：
order_items(order_id, product_id, product_name, quantity)
                                   ↑
                        product_name 只依赖 product_id，部分依赖

✅ 符合 2NF：
order_items(order_id, product_id, quantity)   ← 只放完全依赖主键的属性
products(product_id, product_name)            ← product_name 移到 products 表
```

**第三范式 3NF — 消除传递依赖（非主键列之间不能有依赖）**

在满足 2NF 的基础上，非主键属性之间不存在传递依赖（A → B → C，C 传递依赖 A）。

```
❌ 违反 3NF：
employees(emp_id, emp_name, dept_id, dept_name)
                             ↑         ↑
               dept_name 依赖 dept_id，dept_id 依赖 emp_id → 传递依赖

✅ 符合 3NF：
employees(emp_id, emp_name, dept_id)
departments(dept_id, dept_name)      ← dept_name 移到 departments 表
```

**三范式总结：**

| 范式 | 消除的问题 | 关键判断 |
|------|-----------|----------|
| 1NF | 多值列、重复列 | 每列是否原子值 |
| 2NF | 部分依赖 | 非主键是否完全依赖主键（联合主键时才存在此问题） |
| 3NF | 传递依赖 | 非主键列之间是否有依赖关系 |

**反范式化（Denormalization）：**

生产中并非越规范越好。当查询性能是瓶颈时，常主动引入冗余：

- 订单表冗余商品名称（避免 JOIN products 表，快照历史价格）
- 评论表冗余用户昵称（避免高频 JOIN users 表）
- 统计表冗余 count 字段（避免每次 COUNT 全表）

> **面试答法**：先说三范式定义，再说实际工程中常在 3NF 和反范式化之间权衡：**读多写少 + 对历史快照有要求的字段适当冗余**，用业务可接受的"更新时多写一个字段"换取"读时少一次 JOIN"。

---

> **文档维护说明**：本文档基于 MySQL 8.0 / InnoDB 编写，部分内容适用于 MySQL 5.7。PostgreSQL 对比基于 PG 15+。数据库技术和版本更新较快，建议结合实际环境的版本确认细节。
