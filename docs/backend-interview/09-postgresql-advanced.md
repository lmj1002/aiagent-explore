# 高级 PostgreSQL 面试知识架构

> 目标受众：5-8 年经验的高级后端开发工程师
> 文档定位：面试深度准备 / 生产架构设计参考
> 更新时间：2026-06

---

## 目录

1. [核心特性](#1-核心特性)
2. [索引体系](#2-索引体系)
3. [SQL 高级特性](#3-sql-高级特性)
4. [数据类型与扩展](#4-数据类型与扩展)
5. [锁机制](#5-锁机制)
6. [高可用与复制](#6-高可用与复制)
7. [性能调优](#7-性能调优)
8. [与 MySQL 全面对比](#8-与-mysql-全面对比)

---

## 1. 核心特性

### 1.1 MVCC 实现机制

PostgreSQL 的 MVCC（Multi-Version Concurrency Control）通过**元组级多版本存储**实现，与 MySQL InnoDB 的 **Undo Log 回滚段**方案有本质区别。

**PostgreSQL 实现方式：**

- 每个表行（tuple）隐藏系统列：`xmin`（创建事务 ID）、`xmax`（删除/更新事务 ID）、`ctid`（物理位置）
- UPDATE = 标记旧行 xmax + 插入新行；DELETE = 标记 xmax
- 每个事务启动时获取 `snapshot`（当前活跃事务列表 `pg_active`），可见性规则：
  - `xmin < txid_current` 且 `xmin NOT IN snap_xip` → 可见
  - `xmax IS NULL` 或 `xmax >= txid_current` 或 `xmax IN snap_xip` → 可见
- 无回滚段，无 Undo Log — 死元组由 Vacuum 物理回收

**与 MySQL InnoDB 的关键差异：**

| 维度 | PostgreSQL | MySQL InnoDB |
|------|-----------|-------------|
| 存储方式 | 死元组留在数据页，Vacuum 清理 | Undo Log 回滚段，purge 线程回收 |
| 事务 ID | 32-bit，环绕时需 freeze（`vacuum_freeze_min_age`） | 6-byte，ROLLBACK 段复用 |
| 可见性判断 | 元组头 xmin/xmax | Undo Log 构造 Previous Version |
| UPDATE 行为 | 新版本插入同/异页，索引新增条目 | 聚集索引原地更新（如果页内有空间），二级索引可能不变 |
| 写放大 | 死元组 + 索引条目均重复 | 主要体现为 Undo Log 增长 |
| 回滚速度 | 极快（标记 xmax 即可） | 需要回放 Undo 构建前镜像 |

**高频面试题：**

> **Q：为什么 PostgreSQL 的 UPDATE 比 MySQL InnoDB 慢？如何优化？**

A：PostgreSQL UPDATE 写放大更明显 — 每行每次 UPDATE 产生一个死元组，且该行上所有索引都新增一条索引条目。优化手段：
- 减少索引数量（尤其是非必要二级索引）
- 使用 `HOT (Heap-Only Tuple)` 更新 — 当被更新列不在任何索引中且页内有空闲空间时，仅堆更新，不新增索引条目（通过 `pg_stat_user_tables.n_tup_hot_upd` 监控）
- 调整 `fillfactor`（默认 100，为 HOT 预留空间建议设为 85-90）
- 使用 `REPLICA IDENTITY FULL` 或逻辑复制减少主键索引开销

> **Q：什么是 Tuple Freeze？为什么重要？**

A：PG 事务 ID 是 32-bit 循环使用的。约 20 亿事务后，旧事务 ID 会卷回变成未来事务，导致数据不可见。Freeze 将元组 xmin 标记为 `FrozenTransactionId`（2），使其对所有正常事务始终可见。Autovacuum 根据 `autovacuum_freeze_max_age`（默认 2 亿）自动触发 Anti-wraparound Vacuum。**未及时 Freeze 会导致数据库强制关闭**（`ERROR: database is not accepting commands to avoid wraparound data loss`）。

---

### 1.2 WAL（Write Ahead Log）

PostgreSQL 的 REDO 日志，位于 `pg_wal/`，默认每个 16MB。

**关键配置：**

| 参数 | 说明 | 推荐值 |
|------|------|--------|
| `wal_level` | WAL 记录级别 | `replica` 或 `logical` |
| `wal_buffers` | WAL 缓冲内存 | `16MB`（`-1` = shared_buffers 的 1/32） |
| `wal_sync_method` | 刷盘策略 | Linux: `fdatasync`，小心 `open_sync` 性能陷阱 |
| `synchronous_commit` | 同步提交等待级别 | `on` / `remote_apply` / `off` |
| `wal_compression` | WAL 压缩（lz4/pglz） | `lz4`（PG 15+） |
| `wal_log_hints` | 页级校验，pg_rewind 需要 | `on`（高可用环境） |

**生产最佳实践：**

- WAL 存放在独立磁盘（IO 隔离），强烈推荐 SSD/NVMe
- `wal_compression = lz4` 几乎无 CPU 开销，可节省 40-60% WAL 空间
- 监控 `pg_wal/` 大小：异常增长通常是长事务或流复制延迟导致
- 使用 `pg_switch_wal()` 强制切换，`pg_walfile_name()` 获取当前位置

**高频面试题：**

> **Q：WAL 写入流程是怎样的？checkpoint 的作用？**

A：事务提交 → WAL 写入 WAL Buffer → `wal_writer` 刷盘（`wal_sync_method`）→ 事务返回成功。Checkpoint 将 Buffer Pool 中所有脏页刷盘，推进 `redo point`，以便崩溃恢复时只需重放 checkpoint 之后的 WAL。`checkpoint_completion_target`（默认 0.9）控制刷盘平摊时长。

> **Q：什么是 Full Page Write？什么情况需要关闭？**

A：Checkpoint 后第一次修改某数据页时，WAL 记录整页（默认 `on`），防止部分写导致页损坏。仅在文件系统保证原子写（如 ZFS、PowerSafe 模式）时可关闭。**生产环境原则上保持开启。**

---

### 1.3 Vacuum 机制与 Autovacuum 调优

**Vacuum 分类：**

| 类型 | 命令 | 行为 |
|------|------|------|
| 普通 Vacuum | `VACUUM tab` | 回收死元组空间（不锁表，不释放空间给 OS） |
| Full Vacuum | `VACUUM FULL tab` | 重写表，释放空间给 OS（**排他锁**） |
| Analyze | `ANALYZE tab` | 更新统计信息（`pg_statistic`） |
| AutoVacuum | 自动触发 | 守护进程按阈值触发 VACUUM + ANALYZE |

**Autovacuum 核心参数：**

```
autovacuum = on                          # 默认开启
autovacuum_max_workers = 3               # 最多 3 个 worker（建议 CPU 核数 * 0.5）
autovacuum_naptime = 60s                 # 每 60s 检查一次
autovacuum_vacuum_threshold = 50         # 死元组超过 (50 + 0.2 * reltuples) 触发
autovacuum_vacuum_scale_factor = 0.2     # 上述比例
autovacuum_vacuum_cost_limit = -1        # 默认 200（继承 vacuum_cost_limit）
autovacuum_vacuum_cost_delay = 20ms      # 每 200 cost 延迟 20ms
```

**生产调优模板：**

```sql
-- 对高频更新的大表单独设置（覆盖全局参数）
ALTER TABLE orders SET (
  autovacuum_vacuum_scale_factor = 0.05,
  autovacuum_vacuum_threshold = 10000,
  autovacuum_vacuum_cost_limit = 1000,
  autovacuum_naptime = '30s'
);

-- 防止长事务导致 vacuum 无法回收
-- 监控 longest running transaction
SELECT pid, xact_start, now() - xact_start AS duration, query
FROM pg_stat_activity
WHERE state = 'idle in transaction'
  AND xact_start IS NOT NULL
ORDER BY xact_start
LIMIT 5;
```

---

### 1.4 表膨胀处理

**膨胀原因：**

1. Autovacuum 不及时追上更新频率
2. 长事务/空闲事务阻止 vacuum 回收死元组
3. 大事务（`old_snapshot_threshold` 超时）
4. `VACUUM FULL` 长期不做

**诊断 SQL：**

```sql
SELECT
  schemaname,
  relname,
  n_live_tup,
  n_dead_tup,
  ROUND(n_dead_tup * 100.0 / GREATEST(n_live_tup + n_dead_tup, 1), 2) AS dead_pct,
  last_autovacuum,
  last_manual_vacuum
FROM pg_stat_user_tables
ORDER BY n_dead_tup DESC
LIMIT 20;
```

```sql
-- 查看表实际物理大小 vs 估算逻辑大小
SELECT
  pg_size_pretty(pg_total_relation_size(relid)) AS total_size,
  pg_size_pretty(pg_relation_size(relid)) AS heap_size,
  ROUND(100 * pg_relation_size(relid) / NULLIF(pg_total_relation_size(relid), 0), 1) AS heap_pct
FROM pg_catalog.pg_statio_user_tables
ORDER BY pg_total_relation_size(relid) DESC;
```

**膨胀处理方案：**

| 方案 | 锁 | 适用场景 |
|------|----|---------|
| `VACUUM` | 无排他锁 | 轻度膨胀 |
| `VACUUM FULL` | AccessExclusiveLock | 重度膨胀（可接受停机窗口） |
| `pg_repack` | 仅最后阶段短暂锁 | 在线处理，**推荐** |
| `pg_squeeze` | 轻量锁 | 比较新，社区评价好 |

```bash
# pg_repack 使用示例（需预先安装 extension）
pg_repack -h localhost -d mydb -t orders --no-order
```

**高频面试题：**

> **Q：表膨胀到多大必须处理？如何建立监控和报警阈值？**

A：没有绝对数字，但普遍经验规则：
- 死元组占比 > 30% 且持续增长 → 关注
- 死元组占比 > 50% → 触发告警
- 单个表膨胀超过 10GB → 评估 pg_repack
- 监控指标：`n_dead_tup`、`last_autovacuum` 距今时间、`idx_scan` 效率下降
- 建议集成到 Prometheus + Grafana（通过 `postgres_exporter`）

---

## 2. 索引体系

### 2.1 索引类型总览

| 类型 | 支持操作 | 适用场景 | 存储方式 |
|------|---------|---------|---------|
| **B-Tree** | `=`, `<`, `<=`, `>`, `>=`, `BETWEEN`, `IN`, `LIKE('abc%')`, `IS NULL` | 通用目的，排序和等值/范围查询 | 平衡树，叶节点双向链接 |
| **Hash** | `=` | 等值查询，且索引列无排序需求 | 哈希桶，无顺序 |
| **GiST** | 全文检索、几何、范围重叠 `&&`、最近邻 `ORDER BY` | 地理/几何/模糊搜索 | 通用搜索树，可扩展 |
| **GIN** | `@>`, `?`, `?|`, `&&`（数组/jsonb/全文检索） | 包含/存在查询，组合搜索 | 倒排索引 |
| **SP-GiST** | 类似 GiST，但适用非平衡结构 | 四叉树、k-d 树、前缀搜索 | 空间分区树 |
| **BRIN** | `=`（选择性低）、范围扫描 | 时序/日志数据，物理顺序与逻辑顺序一致 | 块范围摘要（min/max） |
| **Bloom** | `=` 多列等值组合 | 多列任意组合等值查询（扩展模块） | 布隆过滤器 |

**面试重点：**

> **Q：什么情况下 BRIN 比 B-Tree 更好？能省多少空间？**

A：数据天然按时间顺序插入（如订单表 `created_at`），且查询以时间范围为主。BRIN 在 1GB 的表上可能只占几 MB（B-Tree 通常占表大小的 20-30%）。检索时通过 `page ranges`（默认每 128 页）预过滤数据页。**关键约束**：数据写入顺序必须接近物理顺序（`ORDER BY` 相同列），否则 BRIN 精度急剧下降。PG 16+ 支持 `BRIN bloom` 模式以缓解低相关性场景。

**空间对比示例：**
```sql
-- B-Tree: ~220MB (1GB 表)
CREATE INDEX idx_btime ON orders USING btree (created_at);
-- BRIN: ~2.4MB，查询速度在时序场景与 B-Tree 接近
CREATE INDEX idx_brin_time ON orders USING brin (created_at) WITH (pages_per_range = 32);
```

> **Q：GiST 和 GIN 在全文检索场景如何选择？**

A：GIN 更适合**静态/低频更新**的全文搜索（构建慢但查询快），GiST 更适合**高频插入**的全文搜索（构建快但查询慢且有误报风险）。生产通常选 GIN 做 FTS。

---

### 2.2 部分索引 / 表达式索引 / 覆盖索引

**部分索引（Partial Index）：**

```sql
-- 仅索引活跃订单，极大减小索引体积
CREATE INDEX idx_active_orders ON orders (created_at)
  WHERE status IN ('pending', 'processing');
```

**表达式索引（Expression Index）：**

```sql
-- 对 LOWER(email) 做等值查询
CREATE INDEX idx_lower_email ON users (LOWER(email));
-- 注意：查询时必须用同样的表达式 LOWER(email) = 'user@example.com'
```

**覆盖索引（INCLUDE 子句，PG 11+）：**

```sql
-- 索引 key: user_id（用于过滤）
-- 附带 payload: amount, created_at（避免回表）
CREATE INDEX idx_order_user ON orders (user_id) INCLUDE (amount, created_at);

-- 查询只需索引扫描
SELECT user_id, amount, created_at FROM orders WHERE user_id = 42;
```

**关键差异：**

| 特性 | 表达式索引 | 部分索引 | INCLUDE 索引 |
|------|-----------|---------|-------------|
| 目的 | 索引函数/表达式结果 | 减少索引大小 | Index-Only Scan |
| 查询要求 | 表达式必须完全一致 | WHERE 条件匹配 | index 包含所有 SELECT 列 |
| 代价 | 写时计算表达式 | 写时检查条件 | 增大叶节点宽度 |
| 适用版本 | 所有版本 | 所有版本 | PG 11+ |

**高频面试题：**

> **Q：Index-Only Scan 需要什么条件？Visibility Map 的作用是什么？**

A：Index-Only Scan 要求查询的列全部在索引中，且元组对当前事务可见。Visibility Map（VM）存储每个数据页的可见性位：当 VM 标记该页所有元组均可见时，跳过回表检查。若 VM 未标记，仍需回表验证（变成 Bitmap Heap Scan）。每 `vacuum` 后 VM 更新。这是为什么定期 vacuum 能提升 Index-Only Scan 效率的原因之一。

---

### 2.3 索引扫描算法

| 扫描方式 | 触发条件 | 特点 |
|---------|---------|------|
| **Index Scan** | 返回行数少（通常 < 5% 表） | 随机 IO，但定位精准 |
| **Bitmap Index Scan** | 返回行数中等（5%-20%） | 先建位图再顺序扫堆，减少随机 IO |
| **Index Only Scan** | 全部所需列在索引中且 VM 可见 | 最快，完全避免堆访问 |
| **Bitmap Heap Scan** | Bitmap Index Scan 的堆访问阶段 | 顺序 IO + 少量随机 |
| **Seq Scan** | 返回行数多（> 20-30%） | 全表顺序扫描，大表避免 |

**理解查询计划：**

```sql
EXPLAIN (ANALYZE, BUFFERS, COSTS)
SELECT order_id, amount FROM orders
WHERE user_id = 42 AND created_at >= '2026-01-01';
```

```
Bitmap Heap Scan on orders  (cost=12.34..56.78 rows=50 width=36)
  Recheck Cond: ((user_id = 42) AND (created_at >= '2026-01-01'::date))
  ->  BitmapAnd
        ->  Bitmap Index Scan on idx_order_user  (cost=0.00..4.56 rows=100)
              Index Cond: (user_id = 42)
        ->  Bitmap Index Scan on idx_orders_created  (cost=0.00..7.89 rows=500)
              Index Cond: (created_at >= '2026-01-01'::date)
```

**生产经验：** BitmapAnd/BitmapOr 是 PG 多索引组合的核心优势之一。MySQL 通常一个查询只能用一个索引（Index Merge 限制较多）。

---

### 2.4 并发创建索引（CONCURRENTLY）

**核心语法：**

```sql
-- 不阻塞 DML（读/写正常，但 DDL 期间稍慢）
CREATE INDEX CONCURRENTLY idx_name ON orders (user_id);
-- 清理：如果创建失败需 DROP INDEX 再重试
```

**原理（三阶段）：**

1. 第一阶段（`ShareLock`）：构建索引数据（不阻塞读写）
2. 第二阶段（等待所有已有事务结束）：将索引标记为 `VALID` 的第一部分
3. 第三阶段（再次等待所有事务结束）：最终标记 `VALID`

**注意事项：**

- 总时间比非并发模式 **长 2-3 倍**
- 会等待所有已有事务结束两次（可能被长事务阻塞）
- 创建过程中出错，索引标记为 `INVALID`，必须 DROP 重建
- 不能在一个事务块内执行
- 主索引（Primary Key）不能直接 CONCURRENTLY，需要两步：`CREATE UNIQUE INDEX CONCURRENTLY ...` 然后 `ALTER TABLE ... ADD PRIMARY KEY USING INDEX ...`

**生产最佳实践：**

```sql
-- 在低峰期创建，设置超时防止死锁
SET statement_timeout = '30min';
CREATE INDEX CONCURRENTLY idx_orders_payment ON orders (payment_id)
  WHERE payment_id IS NOT NULL;
-- 监控进度
SELECT phase, round(100.0 * blocks_done / nullif(blocks_total, 0), 1) AS pct
FROM pg_stat_progress_create_index;
```

> **Q：在线环境加唯一索引如何避免重复数据导致失败？**

A：先创建非唯一索引 `CONCURRENTLY`，然后清理数据，最后通过 `ALTER TABLE ... ADD CONSTRAINT ... UNIQUE USING INDEX ...` 将已有索引提升为唯一约束（该操作时间极短，仅需 `ShareLock`）。

---

## 3. SQL 高级特性

### 3.1 窗口函数（Window Functions）

**四大类窗口函数：**

| 类别 | 函数 | 用途 |
|------|------|------|
| 排名 | `ROW_NUMBER()`, `RANK()`, `DENSE_RANK()`, `NTILE()` | 分组内排序 |
| 聚合 | `SUM() OVER`, `AVG() OVER`, `COUNT() OVER` | 运行总计/移动平均 |
| 偏移 | `LAG()`, `LEAD()`, `FIRST_VALUE()`, `LAST_VALUE()` | 前后行引用 |
| 统计 | `PERCENT_RANK()`, `CUME_DIST()` | 分布分析 |

**高频 SQL 示例：**

```sql
-- 1. 分组取 Top-N：每个用户最近 3 笔订单
WITH ranked AS (
  SELECT *,
    ROW_NUMBER() OVER (PARTITION BY user_id ORDER BY created_at DESC) AS rn
  FROM orders
)
SELECT * FROM ranked WHERE rn <= 3;

-- 2. 同比增长计算
SELECT
  date_trunc('month', created_at) AS month,
  COUNT(*) AS orders,
  LAG(COUNT(*)) OVER (ORDER BY date_trunc('month', created_at)) AS prev_month,
  ROUND(
    (COUNT(*) - LAG(COUNT(*)) OVER (ORDER BY date_trunc('month', created_at)))
    * 100.0 / NULLIF(LAG(COUNT(*)) OVER (ORDER BY date_trunc('month', created_at)), 0),
    2
  ) AS growth_pct
FROM orders
GROUP BY 1
ORDER BY 1;

-- 3. 累计占比（Pareto 分析）
SELECT
  product_id,
  amount,
  SUM(amount) OVER (ORDER BY amount DESC) AS running_total,
  SUM(amount) OVER () AS grand_total,
  ROUND(
    100.0 * SUM(amount) OVER (ORDER BY amount DESC ROWS UNBOUNDED PRECEDING)
    / SUM(amount) OVER (),
    2
  ) AS cumulative_pct
FROM sales
ORDER BY amount DESC;
```

**窗口帧（Frame）定义：**

```sql
-- 默认帧：RANGE BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
SUM(amount) OVER (ORDER BY created_at)
-- 移动平均（最近 7 条）
AVG(amount) OVER (ORDER BY created_at ROWS BETWEEN 6 PRECEDING AND CURRENT ROW)
-- 分组全部行
SUM(amount) OVER (PARTITION BY user_id ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING)
```

**高频面试题：**

> **Q：RANK() 与 DENSE_RANK() 有什么区别？执行计划有何异同？**

A：RANK() 在并列值时跳过后续序号（如 1,1,3），DENSE_RANK() 不跳过（如 1,1,2）。执行计划层面二者无差异，计算逻辑完全由窗口排序实现，性能开销相同。

> **Q：ROW_NUMBER() 翻页相比 LIMIT/OFFSET 的优势？**

A：LIMIT/OFFSET 每次翻页仍要扫描并丢弃前 N 行；ROW_NUMBER() + 子查询可基于索引键分页，保证每次翻页固定扫描少量行。但实际生产常见 Keyset Pagination（WHERE cursor > last_value LIMIT N）性能最佳。

---

### 3.2 CTE 与递归查询（WITH RECURSIVE）

**非递归 CTE（物化屏障）：**

```sql
-- PG 12+：WITH 默认不再自动物化
-- 使用 MATERIALIZED 强制物化（只计算一次，引用多次时有用）
WITH regional_sales AS MATERIALIZED (
  SELECT region, SUM(amount) AS total
  FROM orders
  GROUP BY region
)
SELECT * FROM regional_sales
UNION ALL
SELECT 'Total', SUM(total) FROM regional_sales;
```

**递归 CTE（通用表表达式递归）：**

```sql
-- 组织树：查询某个部门及其所有子部门
WITH RECURSIVE dept_tree AS (
  -- 锚点：根节点
  SELECT id, name, parent_id, 1 AS level
  FROM departments
  WHERE id = 10

  UNION ALL

  -- 递归：子部门
  SELECT d.id, d.name, d.parent_id, dt.level + 1
  FROM departments d
  INNER JOIN dept_tree dt ON d.parent_id = dt.id
)
SELECT * FROM dept_tree;
```

```sql
-- 图遍历：全部上游依赖链（防止环路）
WITH RECURSIVE deps AS (
  SELECT task_id, dep_task_id, ARRAY[task_id] AS path
  FROM task_dependencies
  WHERE task_id = 'T-1000'

  UNION ALL

  SELECT d.task_id, d.dep_task_id, path || d.dep_task_id
  FROM task_dependencies d
  INNER JOIN deps ON deps.dep_task_id = d.task_id
  WHERE NOT d.dep_task_id = ANY(deps.path)  -- 防环路
)
SELECT DISTINCT unnest(path) AS all_dependent_tasks FROM deps;
```

**高频面试题：**

> **Q：递归 CTE 的深度限制是多少？如何处理超深递归？**

A：默认 `max_recursive_iterations`（未设置时受 `max_stack_depth` 约束）。PG 14+ 可设置 `search_depth` 和 `min_search_depth`。生产建议在递归中加 `level` 计数器并在 `WHERE` 中限制（如 `level <= 10`）。**环路检测**必须通过路径数组 `NOT path @> ARRAY[id]` 实现。

---

### 3.3 LATERAL JOIN

LATERAL 允许子查询引用前面表的列，常用于"对每行执行子查询"场景。

```sql
-- 每个用户最近 1 笔订单（比 ROW_NUMBER() 子查询更高效）
SELECT u.id, u.name, o.amount, o.created_at
FROM users u
LEFT JOIN LATERAL (
  SELECT amount, created_at
  FROM orders
  WHERE user_id = u.id
  ORDER BY created_at DESC
  LIMIT 1
) o ON true;

-- 等价于 ROW_NUMBER() 方案，但 LATERAL 通常有计划优势（Nested Loop）
```

**LATERAL + 聚合函数：**

```sql
-- 每个分类 Top 2 产品
SELECT c.name, p.name, p.price
FROM categories c
CROSS JOIN LATERAL (
  SELECT name, price
  FROM products
  WHERE category_id = c.id
  ORDER BY price DESC
  LIMIT 2
) p;
```

> **Q：LATERAL JOIN 与相关子查询的执行计划差异？**

A：相关子查询通常被优化器重写为 Apply 算子，而 LATERAL 明确表达 Nested Loop 语义。在 PG 中 LATERAL 更可控，常用于组合外部函数（如 `generate_series()`）或地理位置查询。

---

### 3.4 JSONB 查询与索引

**JSONB 索引类型：**

```sql
-- 1. GIN 索引（最常用）：支持 @>, ?, ?|, ?&
CREATE INDEX idx_gin ON products USING gin (attrs jsonb_path_ops);

-- 2. B-Tree 索引：仅支持 -> 'key' 提取的等值查询
CREATE INDEX idx_btree ON products USING btree ((attrs->>'category'));

-- 3. 表达式索引：JSON 内特定字段
CREATE INDEX idx_price ON products USING btree (((attrs->>'price')::numeric));
```

**查询示例：**

```sql
-- GIN 索引触发：包含查询
SELECT * FROM products WHERE attrs @> '{"brand": "Apple", "color": "black"}';

-- GIN 索引触发：存在查询（key 是否存在）
SELECT * FROM products WHERE attrs ? 'warranty';

-- 表达式索引触发：特定字段范围查询
SELECT * FROM products
WHERE (attrs->>'price')::numeric BETWEEN 100 AND 500;

-- JSONB 取路径（PG 14+ 下标语法）
SELECT attrs['specs']['weight'] FROM products;
```

**JSONB vs JSON 差异（见第 4 章）。**

**高频面试题：**

> **Q：JSONB @> 操作符的左/右操作数大小是否影响性能？**

A：有显著影响。**右操作数（待匹配子集）越小越快**。GIN 索引在 `@>` 中右操作数用作匹配键。建议将更具体的条件放在右边。同样，在 `?|`（任何一个存在）时，优先使用高频 top-key。

---

### 3.5 全文检索（Full-Text Search）

**核心概念：**

- **tsvector**：文本 → 词素（lexeme）+ 位置 + 权重
- **tsquery**：查询条件，支持 `&`（AND）、`|`（OR）、`!`（NOT）、`<->`（短语）
- **分词器（Text Search Configuration）**：`english`、`simple`、`chinese（需 zhparser/zhcon 扩展）`

```sql
-- 创建 tsvector 索引
ALTER TABLE articles ADD COLUMN fts tsvector
  GENERATED ALWAYS AS (
    setweight(to_tsvector('english', title), 'A') ||
    setweight(to_tsvector('english', body), 'B')
  ) STORED;

CREATE INDEX idx_fts ON articles USING GIN (fts);

-- 查询
SELECT title,
  ts_rank(fts, query) AS rank,
  ts_headline('english', body, query, 'MaxWords=50')
FROM articles, plainto_tsquery('english', 'database optimization') query
WHERE fts @@ query
ORDER BY rank DESC
LIMIT 10;
```

**中文全文检索（需要扩展）：**

```bash
# 安装 zhparser（需先安装 SCWS）
git clone https://github.com/amutu/zhparser.git
cd zhparser && make && make install
```

```sql
CREATE TEXT SEARCH CONFIGURATION chinese (PARSER = zhparser);
ALTER TEXT SEARCH CONFIGURATION chinese ADD MAPPING FOR n,v,a,i,e,l WITH simple;

CREATE INDEX idx_fts_zh ON articles USING GIN (to_tsvector('chinese', body));
```

> **Q：PostgreSQL 的 LIKE '%keyword%' 能用索引吗？**

A：B-Tree 索引**不支持**左侧模糊。方案：
1. `trigram` 索引（`pg_trgm` 扩展）—— `CREATE INDEX idx_trgm ON tab USING GIN (col gin_trgm_ops);` 支持 `ILIKE '%keyword%'`
2. 全文检索（适用场景不同，不支持子串匹配）
3. 外部搜索（Elasticsearch）

---

## 4. 数据类型与扩展

### 4.1 JSONB vs JSON

| 维度 | JSON | JSONB |
|------|------|-------|
| 存储格式 | 原文复制 | 分解后内部二进制 |
| 写入速度 | 更快（无转换） | 较慢（解析 + 排序） |
| 读取速度 | 较慢（每访问解析） | 更快（直接二进制读取） |
| 索引支持 | 不支持 | GIN / B-Tree |
| 键值顺序 | 保留原始顺序 | 按 key 排序 |
| 重复 key | 保留 | 只保留最后一个 |
| 操作符 | `->`, `->>`, `#>` | 同上 + `@>`, `?`, `?|`, `?&`, `##` |
| 空格 | 保留 | 去除 |

**生产决策：** **始终使用 JSONB**，除非写入吞吐极高且从不进行查询过滤。JSONB 的额外写入开销通常小于 10%，而查询性能提升数十倍。

---

### 4.2 数组类型

```sql
-- 定义
CREATE TABLE article_tags (
  article_id BIGINT PRIMARY KEY,
  tags TEXT[],
  votes INTEGER[]
);

-- 插入
INSERT INTO article_tags VALUES (1, ARRAY['postgres', 'sql', 'database'], '{5,10,3}');

-- 查询
SELECT * FROM article_tags WHERE tags @> ARRAY['postgres'];           -- 包含
SELECT * FROM article_tags WHERE tags && ARRAY['postgres', 'mysql'];   -- 重叠
SELECT unnest(tags) FROM article_tags WHERE article_id = 1;            -- 展开

-- 索引
CREATE INDEX idx_tags ON article_tags USING GIN (tags);
```

**注意：** 数组相比 JSONB 更紧凑（无 key 开销），适用于纯值列表。如需键值对，用 JSONB。

---

### 4.3 范围类型

```sql
-- 内置范围类型：int4range, int8range, numrange, tsrange, tstzrange, daterange

-- 会议室预订场景
CREATE TABLE room_booking (
  room_id INT,
  booking_range TSTZRANGE,
  EXCLUDE USING GIST (room_id WITH =, booking_range WITH &&)
);

-- 插入
INSERT INTO room_booking VALUES (1, '[2026-06-15 10:00, 2026-06-15 12:00)');

-- 查询重叠
SELECT * FROM room_booking
WHERE booking_range && '[2026-06-15 11:00, 2026-06-15 13:00)';


-- 范围操作符
@>          -- 包含
&&          -- 重叠
<< / >>     -- 严格左/右
-|-         -- 相邻
```

**高频面试题：**

> **Q：排他约束（Exclusion Constraint）与唯一约束的区别？**

A：唯一约束只能做 `=` 比较。排他约束可自定义比较操作符，如使用 `&&`（重叠）检测时间冲突。底层依赖 GiST 索引。PG 是少数原生支持排他约束的 RDBMS 之一。

---

### 4.4 PostGIS 地理空间

```sql
-- 安装（需要操作系统安装 libgeos）
CREATE EXTENSION postgis;

-- 创建空间表
CREATE TABLE locations (
  id BIGSERIAL PRIMARY KEY,
  name TEXT,
  geom GEOMETRY(Point, 4326)  -- WGS84 经纬度
);
CREATE INDEX idx_geom ON locations USING GIST (geom);

-- 查询附近 1km 内的点
SELECT id, name, ST_DistanceSphere(geom, ST_SetSRID(ST_MakePoint(116.4, 39.9), 4326)) AS dist
FROM locations
WHERE ST_DWithin(
  geom::geography,
  ST_SetSRID(ST_MakePoint(116.4, 39.9), 4326)::geography,
  1000
)
ORDER BY geom <-> ST_SetSRID(ST_MakePoint(116.4, 39.9), 4326)  -- 最近邻排序
LIMIT 20;
```

**高频面试题：**

> **Q：GIS 查询中 geography vs geometry 的区别？**

A：`geography` 使用球面计算（精确但较慢，距离用米），`geometry` 使用平面计算（快速但需注意投影）。长距离（>1000km）推荐 `geography`，短距离用 `geometry` 加适当投影（如 `ST_Transform`）。索引均用 GiST。

---

### 4.5 pg_partman 分区管理

```sql
-- 安装
CREATE EXTENSION pg_partman;

-- 创建分区表模板（按时间分区）
CREATE TABLE measurement (
  log_time TIMESTAMPTZ NOT NULL,
  value FLOAT
) PARTITION BY RANGE (log_time);

-- 通过 pg_partman 自动创建和维护子分区
SELECT partman.create_parent(
  p_parent_table := 'public.measurement',
  p_control := 'log_time',
  p_type := 'native',
  p_interval := '1 day',
  p_premake := 7
);

-- 自动维护（需 pg_cron 或外部调度）
-- 每小时运行一次
SELECT partman.run_maintenance();
```

**分区局限与陷阱：**

- **分区键必须包含在主键中**（PG 11 放宽，但仍有约束）
- 分区数建议不超过 1000-2000（过多影响计划器性能）
- 跨分区 UPDATE 性能差（如果 UPDATE 改变了分区键）
- 分区裁剪（Partition Pruning）依赖查询参数化，prepare statement 需 `EXECUTE`

---

### 4.6 Citus 分布式扩展

Citus 将 PG 转换为分布式数据库，采用 **shared-nothing** 架构。

```sql
-- 定义分布表
SELECT create_distributed_table('orders', 'user_id');

-- 定义参考表（全节点复制，小表）
SELECT create_reference_table('payment_methods');

-- 分布式聚合查询（Citus 自动下推）
SELECT user_id, COUNT(*) AS order_count
FROM orders
WHERE created_at >= now() - interval '30 days'
GROUP BY user_id;
```

**进阶特性：**

| 特性 | 说明 |
|------|------|
| 共置 Join（Co-located Join） | 同分布键的表在相同节点 Join，无网络开销 |
| 分布式 DDL | DDL 自动传播到所有 worker |
| 流式 CTE | 避免物化中间结果 |
| 引用表 | 全节点复制，适合字典表 |

**适用场景：** 多租户 SaaS、实时分析、时序数据。**不适用：** 单行高频点查（引入网络延迟）、复杂递归 CTE。

---

## 5. 锁机制

### 5.1 锁类型与层次

**表级锁（8 种，强度递增）：**

| 锁模式 | 命名 | 与哪些锁冲突 |
|--------|------|-------------|
| 1. AccessShare | `SELECT` | 仅与 AccessExclusive 冲突 |
| 2. RowShare | `SELECT FOR UPDATE/FOR SHARE` | Exclusive, AccessExclusive |
| 3. RowExclusive | `INSERT, UPDATE, DELETE` | Share, ShareRowExclusive, Exclusive, AccessExclusive |
| 4. ShareUpdateExclusive | `VACUUM` | ShareUpdateExclusive, Share, ... |
| 5. Share | `CREATE INDEX` | RowExclusive, ShareUpdateExclusive, ... |
| 6. ShareRowExclusive | 少见 | 除 AccessShare 外的几乎所有 |
| 7. Exclusive | `REFRESH MATERIALIZED VIEW CONCURRENTLY` | 几乎所有 |
| 8. AccessExclusive | `ALTER TABLE, DROP TABLE, VACUUM FULL` | 所有 |

**行级锁：**

| 模式 | SQL | 冲突 |
|------|-----|------|
| FOR UPDATE | `SELECT ... FOR UPDATE` | 与 FOR UPDATE/FOR NO KEY UPDATE/FOR SHARE 冲突 |
| FOR NO KEY UPDATE | UPDATE 或 `SELECT ... FOR NO KEY UPDATE` | 同上，但不与 FOR KEY SHARE 冲突 |
| FOR SHARE | `SELECT ... FOR SHARE` | 与 FOR UPDATE/FOR NO KEY UPDATE 冲突 |
| FOR KEY SHARE | FK 检查读取 | 仅与 FOR UPDATE 冲突 |

**锁冲突实战查询：**

```sql
-- 查看当前等待锁和被阻塞的会话
SELECT
  blocked.pid AS blocked_pid,
  blocked.query AS blocked_query,
  blocking.pid AS blocking_pid,
  blocking.query AS blocking_query
FROM pg_locks blocked
JOIN pg_locks blocking
  ON blocked.locktype = blocking.locktype
  AND blocked.database IS NOT DISTINCT FROM blocking.database
  AND blocked.relation IS NOT DISTINCT FROM blocking.relation
  AND blocked.page IS NOT DISTINCT FROM blocking.page
  AND blocked.tuple IS NOT DISTINCT FROM blocking.tuple
  AND blocked.virtualxid IS NOT DISTINCT FROM blocking.virtualxid
  AND blocked.transactionid IS NOT DISTINCT FROM blocking.transactionid
  AND blocked.classid IS NOT DISTINCT FROM blocking.classid
  AND blocked.objid IS NOT DISTINCT FROM blocking.objid
  AND blocked.objsubid IS NOT DISTINCT FROM blocking.objsubid
  AND blocked.pid != blocking.pid
WHERE blocked.granted = false;
```

---

### 5.2 咨询锁（Advisory Lock）

应用程序级协同锁，不依赖任何数据库行或表。

```sql
-- 会话级别（自动释放或显式释放）
SELECT pg_advisory_lock(12345);        -- 阻塞等待
SELECT pg_advisory_unlock(12345);

SELECT pg_try_advisory_lock(12345);    -- 立即返回 true/false

-- 行级别（推荐：按锁名 + id 区分）
SELECT pg_advisory_xact_lock(hashtext('order_lock'), order_id)
FROM orders WHERE id = 100;            -- 事务结束时自动释放
```

**应用场景：**

- 分布式定时任务互斥（每节点抢占锁再执行）
- 轻量级队列的消费者互斥（比 SKIP LOCKED 更灵活）
- 批量操作（如 ETL）的并发节流

**高频面试题：**

> **Q：咨询锁和行锁 FOR UPDATE 的区别？何时用咨询锁？**

A：行锁用锁行本身，受 MVCC 影响（并发事务看到的是已提交版本的锁状态）。咨询锁是纯逻辑锁，不与任何数据绑定，适合跨表、跨行、甚至跨应用的协调场景。**性能**：咨询锁开销远小于行锁（不涉及元组可见性检查），但对偶发死锁不提供自动检测（需自己用 `pg_try_advisory_lock` + 重试模式）。

---

### 5.3 死锁检测与处理

```sql
-- 查看死锁日志（默认日志记录 deadlock detected）
-- 自动检测间隔：deadlock_timeout（默认 1s），检测到时选一个受害者回滚

-- 模拟死锁（Session A）
BEGIN;
UPDATE orders SET amount = 100 WHERE order_id = 1;
UPDATE orders SET amount = 200 WHERE order_id = 2;

-- 模拟死锁（Session B）
BEGIN;
UPDATE orders SET amount = 100 WHERE order_id = 2;
UPDATE orders SET amount = 200 WHERE order_id = 1;  -- 这里检测到死锁，B 回滚
```

**生产实战：**

- 所有事务按同一顺序锁定资源（如按 `order_id` 升序）
- 设置 `lock_timeout`（如 `5s`），避免长等待
- 监控 `pg_stat_activity.wait_event_type = 'Lock'` 和 `pg_locks`
- 短事务原则：锁持有时间越短，死锁概率越低

---

### 5.4 SKIP LOCKED / NOWAIT

```sql
-- 工作队列消费者：跳过已被其他会话锁定的行
BEGIN;
SELECT * FROM job_queue
WHERE status = 'pending'
ORDER BY created_at
LIMIT 10
FOR UPDATE SKIP LOCKED;  -- PG 9.5+

-- 处理获取到的行...
UPDATE job_queue SET status = 'processing' WHERE id IN (...);
COMMIT;

-- NOWAIT：获取不到锁立即报错，不等待
SELECT * FROM orders WHERE id = 100 FOR UPDATE NOWAIT;
```

**生产实践：**

`SKIP LOCKED` 是实现**可靠工作队列**的首选方案。相比传统方案（如 `UPDATE ... WHERE id = (SELECT ...)` + 状态标记），SKIP LOCKED 天然解决以下问题：

- 无竞态条件（无需 `updated_at + WHERE status = 'pending'` 重试）
- 高并发消费者无需轮询
- 不会因锁等待互相阻塞

---

### 5.5 并发控制最佳实践

| 场景 | 推荐方案 |
|------|---------|
| 读多写少、接受最终一致性 | READ COMMITTED + 乐观锁（版本号） |
| 写敏感（库存扣减） | `UPDATE ... WHERE id = X AND stock >= qty` + 行锁 |
| 高并发队列 | SKIP LOCKED |
| 跨表一致性 | SERIALIZABLE 隔离级别 + Retry 逻辑 |
| 批量数据加载 | `COPY` + `TRUNCATE`（排除锁） |
| 长事务 | 拆分，避免事务内业务逻辑耗时 |

**乐观锁实现（版本号）：**

```sql
-- 表加版本号列
ALTER TABLE products ADD COLUMN version INT DEFAULT 1;

-- 更新时检查版本
UPDATE products
SET stock = stock - 5, version = version + 1
WHERE id = 100 AND version = 3;

-- 影响行数 = 0 表示版本变了，重试
```

---

## 6. 高可用与复制

### 6.1 流复制（Streaming Replication）

**架构模式：**

```
异步流复制（默认）：
  Primary → WAL Sender → WAL Receiver → Standby（apply wal）

同步流复制：
  Primary → WAL Sender → WAL Receiver → Standby（flush WAL → ACK → 事务提交）
```

**配置示例：**

```ini
# primary: postgresql.conf
wal_level = replica
max_wal_senders = 10
wal_keep_size = 1024          # MB, PG 13+ 替代 wal_keep_segments
synchronous_commit = on       # 同步模式

# primary: pg_hba.conf
host replication replicator <standby_ip>/32 md5

# standby: postgresql.conf
primary_conninfo = 'host=<primary_ip> port=5432 user=replicator password=xxx'
primary_slot_name = 'standby_slot'
hot_standby = on
```

**同步复制级别（PG 支持 4 种）：**

| `synchronous_commit` | 含义 | 性能 |
|----------------------|------|------|
| `off` | 不等待 WAL 刷盘 | 最快，crash 可能丢数据 |
| `local` | 等待本地 WAL 刷盘 | 默认 |
| `remote_write` | 等待备机接收 WAL（未刷盘） | 折中 |
| `on` | 等待备机刷盘 | 保证不丢，延迟增加 |
| `remote_apply` | 等待备机 apply 完成 | 延迟最大，保证备机可读最新 |

**高频面试题：**

> **Q：流复制延迟的常见原因和排查方法？**

A：
1. 网络带宽/延迟（`pg_stat_replication.write_lag`）
2. 备机 I/O 瓶颈（WAL apply 跟不上）
3. 主库大事务（如批量 UPDATE，产生大量 WAL）
4. `max_standby_archive_delay` / `max_standby_streaming_delay` 导致备机查询冲突
5. 复制槽未使用导致 WAL 堆积

排查命令：
```sql
-- 主库
SELECT * FROM pg_stat_replication;

-- 备库
SELECT * FROM pg_stat_wal_receiver;
SELECT pg_last_wal_receive_lsn(), pg_last_wal_replay_lsn();
```

---

### 6.2 逻辑复制（Logical Replication）

PG 10 引入，基于 WAL 的发布-订阅模式。

**配置：**

```sql
-- 发布端（Publisher）
CREATE PUBLICATION my_pub FOR TABLE orders, users;
-- 可过滤行
CREATE PUBLICATION my_pub_filtered FOR TABLE orders WHERE (status = 'paid');

-- 订阅端（Subscriber）
CREATE SUBSCRIPTION my_sub
CONNECTION 'host=<publisher_ip> port=5432 dbname=mydb user=repl password=xxx'
PUBLICATION my_pub;
```

**逻辑复制 vs 流复制：**

| 维度 | 流复制 | 逻辑复制 |
|------|--------|---------|
| 粒度 | 整个实例 | 表级/行级过滤 |
| 版本兼容 | 必须大版本一致 | 可跨大版本 |
| 写双向 | 不允许备库写 | 可双向（需解决冲突） |
| DDL 复制 | 自动 | 不支持（需单独同步） |
| 数据类型 | 完全一致 | 可不同（有限制） |
| 延迟 | 低 | 稍高（逻辑解码开销） |
| Sequence | 同步 | 不同步 |

**生产陷阱：**

- DDL 需在两端单独执行，不一致会导致复制中断
- 主键/REPLICA IDENTITY 必须存在（否则 UPDATE/DELETE 不支持）
- 大事务会在订阅端一次性 apply，可能产生 IO 尖峰
- 网络中断后自动重连，但堆积 WAL 可能撑爆磁盘

---

### 6.3 Patroni + etcd 自动故障切换

**架构：**

```
         +-----------+
         |   etcd    |  (分布式配置存储/选主)
         +-----+-----+
               |
   +-----------+-----------+
   |         |             |
[Patroni] [Patroni]   [Patroni]
   |         |             |
 PG Primary  PG Replica   PG Replica
```

**核心概念：**

- DCS（Distributed Configuration Store）：etcd / Consul / Zookeeper
- **共识选主**：Patroni 通过 DCS 的 lease 机制决定 primary
- **自动切换**：primary 故障 → DCS lease 超时 → 其他 replica 竞选 → 提升新 primary → 配置旧 primary 为 follower
- **回调脚本**：`on_role_change` 事件（如更新 VIP、通知负载均衡器）

**配置要点：**

```yaml
# patroni.yml 关键配置
scope: pg_cluster
namespace: /service
name: pg-0

restapi:
  listen: 0.0.0.0:8008
  connect_address: 10.0.0.1:8008

etcd:
  host: 10.0.0.100:2379

bootstrap:
  dcs:
    ttl: 30            # lease 超时
    loop_wait: 10
    retry_timeout: 10
    maximum_lag_on_failover: 1048576  # 允许的最大复制延迟（bytes）
    postgresql:
      use_pg_rewind: true
      use_slots: true
      parameters:
        wal_level: replica
        hot_standby: "on"

postgresql:
  listen: 0.0.0.0:5432
  connect_address: 10.0.0.1:5432
  data_dir: /data/pg
  pg_hba:
    - host replication replicator 10.0.0.0/8 md5
  authentication:
    replication:
      username: replicator
      password: secret
```

> **Q：Patroni 故障切换的 RTO 和 RPO 大概多少？如何降低？**

A：
- RTO（Recovery Time Objective）：典型 10-30s（含 DCS 租约超时 + 选主 + 元数据更新 + VIP 漂移）。优化：缩短 `ttl`（不要小于 15s），提前预热 replica buffer cache。
- RPO（Recovery Point Objective）：异步复制下取决于延迟（典型 < 1s），同步复制下 RPO = 0。生产推荐**同步复制 + 至少 2 个副本**。

---

### 6.4 连接池（PgBouncer / Pgpool-II）

**PgBouncer（轻量级，推荐）：**

```ini
[databases]
mydb = host=127.0.0.1 port=5432 dbname=mydb

[pgbouncer]
listen_addr = 0.0.0.0
listen_port = 6432
pool_mode = transaction          # transaction/session/statement
max_client_conn = 1000
default_pool_size = 50           # 后端连接数
reserve_pool_size = 10
reserve_pool_timeout = 5.0
server_idle_timeout = 300
```

**Pool 模式选择：**

| 模式 | 说明 | 适用场景 |
|------|------|---------|
| `session` | 一个客户端对应一个后端连接 | 需要会话级变量（SET） |
| `transaction` | 事务结束释放后端连接 | **生产推荐**，高并发 WEB 应用 |
| `statement` | 每条语句后释放 | 极少用 |

**高频面试题：**

> **Q：为什么高并发 PG 场景必须用连接池？**

A：PG 是进程模型（每个连接一个进程），连接数过多导致：
1. 上下文切换开销飙升（`max_connections` 每增 100 个，上下文切换成本非线性增长）
2. 共享内存竞争（如 `shared_buffers` 锁）
3. 每个进程占用内存（约 5-10MB）
4. `max_connections` 建议不超过 500（即使硬件充裕）

PgBouncer 在应用层用**数千连接**聚合到后端**数十连接**，是 PG 高并发的最佳实践。

---

## 7. 性能调优

### 7.1 EXPLAIN ANALYZE 深度解读

**执行计划节点术语速查：**

| 节点 | 含义 | 关注点 |
|------|------|--------|
| Seq Scan | 全表顺序扫描 | 是否因为缺少索引？ |
| Index Scan | 索引定位 + 回表 | 实际行数 vs 预估行数 |
| Index Only Scan | 仅索引扫描（最优） | `Heap Fetches: 0` 最理想 |
| Bitmap Index + Heap Scan | 位图联合扫描 | `Recheck Cond:` 是否必要 |
| Nested Loop | 内外循环 | 外层小内层有索引 |
| Hash Join | 哈希连接 | 内表构建哈希表（适于等值） |
| Merge Join | 排序合并 | 两表已排序 |
| Sort | 排序操作 | `Sort Method: quicksort` vs `external merge` |
| Materialize | 物化中间结果 | 是否导致内存溢出到磁盘 |
| SubqueryScan | 子查询 | 能否改写为 JOIN 或 LATERAL |

**实战解读流程：**

```sql
-- 开启执行计划
EXPLAIN (ANALYZE, BUFFERS, COSTS, TIMING) SQL_STATEMENT;
```

**关键复盘清单：**

1. **实际行数 vs 预估行数差距 > 10x** → 统计信息过时，执行 `ANALYZE`
2. **出现 `Sort Method: external merge Disk:`** → `work_mem` 不足，排序溢出到磁盘
3. **`Buffers: shared hit=... read=...`** → `read` 高表示缓存命中率低，需增大 `shared_buffers` 或优化查询
4. **`Rows Removed by Filter` 比例过高** → 索引选择不当或缺失
5. **`actual time` 在 Nested Loop 内层很高** → 内表缺少索引
6. **`Planning Time` 过长（>100ms）** → 表结构复杂（多分区、多继承）或 GEQO 触发器

**高频面试题：**

> **Q：`EXPLAIN` 中 `actual time` 的单位是什么？为什么有时显示 `0.000`？**

A：微秒。`0.000` 表示该节点执行时间 < 1μs（通常出现在排序后取前 N 行的 Limit 节点）。但如果大量节点显示 `0.000` 且 `ANALYZE` 总耗时很低，说明 `TIMING` 默认的采样的精度不够（PG 12+ 可用 `EXPLAIN (ANALYZE, TIMING OFF)` 减少开销）。

---

### 7.2 关键参数调优

**内存参数（写入 postgresql.conf）：**

```ini
# --- 共享内存 ---
shared_buffers = 4GB                    # RAM 的 25%（不超过 8GB 时，更高需测试）
                                        # 超过 8GB 后收益递减
wal_buffers = 64MB                      # 设 -1 自动 = shared_buffers 的 1/32
                                        # 大写入量场景可手动设为 32-64MB
huge_pages = try                        # 使用大页减少 TLB miss，Linux 需配置 vm.nr_hugepages

# --- 工作内存 ---
work_mem = 64MB                         # 每个排序/哈希操作的内存
                                        # 注意：每个连接 × 每个操作，谨慎调大
                                        # 监控临时文件 size 判断是否不足
maintenance_work_mem = 1GB              # VACUUM、CREATE INDEX 等维护用
autovacuum_work_mem = -1                # 默认继承 maintenance_work_mem，建议独立设置

# --- 查询计划器 ---
effective_cache_size = 12GB             # OS 层文件缓存大小估算，影响计划器对索引扫描的选择
random_page_cost = 1.1                  # SSD 设 1.1，HDD 默认 4.0
                                        # 错误设置过高 → 计划器倾向 Seq Scan
seq_page_cost = 1.0                     # 很少修改
effective_io_concurrency = 200          # SSD 适合 200，HDD 设 2
```

**调优 Golden Rule：**

```
shared_buffers   = RAM × 25%        (一般不超过 8GB，极高 RAM 可测试 30-40%)
effective_cache_size = RAM × 75%    (减去 PG 自身消耗)
work_mem         = 基础 64MB，根据 connections × 最大并行排序调整
maintenance_work_mem = RAM × 5%     (但不要超过 2GB，VACUUM 等可用)
```

**参数影响速查：**

| 参数 | 主要影响 | 调大风险 |
|------|---------|---------|
| `shared_buffers` | Buffer Cache 命中率 | 过大导致 OS 双缓存、检查点 IO 风暴 |
| `work_mem` | 排序/哈希速度 | 连接数多时内存 OOM |
| `maintenance_work_mem` | VACUUM/索引创建速度 | 并行维护操作数有限，风险较小 |
| `random_page_cost` | 索引扫描选择 | 设太大 → 不使用索引；太小 → 过多索引扫描 |
| `effective_cache_size` | 计划器行为 | 设太小 → 倾向 Seq Scan |
| `max_worker_processes` | 并行查询 | 过多 → 上下文切换 |
| `max_parallel_workers_per_gather` | 单查询并行 | 影响 OLTP 小查询延迟 |

---

### 7.3 查询计划缓存

**PG 的查询计划缓存机制（与 SQL Server / Oracle 差异很大）：**

- **Prepared Statement**：PG 的 `PREPARE` 和 `EXECUTE` 默认使用**通用计划**（generic plan），不考虑参数值，适合参数化查询
- **JDBC 驱动**：`prepareThreshold`（默认 5）次执行后才切换为通用计划
- **无全局计划缓存**：PG 没有像 SQL Server 那样的 Plan Cache。每个会话独立维护自己的 prepared plan
- **PG 12+ 的 `pg_stat_statements`**：可以跟踪查询和参数化后的统计信息

```sql
-- 使用 prepared statement
PREPARE user_orders (INT) AS
SELECT * FROM orders WHERE user_id = $1;

EXECUTE user_orders(42);
DEALLOCATE user_orders;

-- 查看查询统计
SELECT queryid, query, calls, total_exec_time / calls AS avg_ms,
  rows, shared_blks_hit, shared_blks_read
FROM pg_stat_statements
ORDER BY total_exec_time DESC
LIMIT 10;
```

**生产经验：**

- ORM 框架（如 Django ORM、Rails ActiveRecord）通常不自动使用 prepared statement，导致每次解析 SQL 的 planning overhead
- 高 TPS 场景建议使用 `pgbouncer` 的 pool 模式加 `PREPARE` + `EXECUTE`
- **通用计划可能不是最优的**：对于有数据倾斜的列（如 `status` 大部分为 'completed'，仅少量为 'pending'），`PREPARE` 可能生成低效的通用计划。处理手段：
  1. 在查询中使用 `/* comment */` 让 pg_stat_statements 区分
  2. 使用动态 SQL 或 ORM 直接构建（略过 PREPARE）

---

### 7.4 分区表（Partitioned Table）

**声明式分区（PG 10+，推荐替代继承式分区）：**

```sql
-- 创建父表
CREATE TABLE orders_part (
  id BIGSERIAL,
  created_at TIMESTAMPTZ NOT NULL,
  amount NUMERIC(10,2),
  status TEXT
) PARTITION BY RANGE (created_at);

-- 创建子分区
CREATE TABLE orders_202606 PARTITION OF orders_part
  FOR VALUES FROM ('2026-06-01') TO ('2026-07-01');

CREATE TABLE orders_202607 PARTITION OF orders_part
  FOR VALUES FROM ('2026-07-01') TO ('2026-08-01');

-- 创建子分区索引（PG 11+ 支持父表索引自动传播到子分区）
CREATE INDEX ON orders_part (created_at);
CREATE INDEX ON orders_part (user_id);

-- 分区裁剪验证
EXPLAIN SELECT * FROM orders_part
WHERE created_at >= '2026-06-15' AND created_at < '2026-06-16';
-- 应只扫描 orders_202606 分区
```

**分区策略：**

```sql
-- 按列表分区
CREATE TABLE orders_list PARTITION BY LIST (status);
CREATE TABLE orders_pending PARTITION OF orders_list FOR VALUES IN ('pending');
CREATE TABLE orders_done PARTITION OF orders_list FOR VALUES IN ('completed', 'cancelled');

-- 哈希分区（PG 11+）
CREATE TABLE users_hash PARTITION BY HASH (user_id);
CREATE TABLE users_0 PARTITION OF users_hash FOR VALUES WITH (MODULUS 4, REMAINDER 0);
CREATE TABLE users_1 PARTITION OF users_hash FOR VALUES WITH (MODULUS 4, REMAINDER 1);
```

**高频面试题：**

> **Q：分区表的查询性能一定比非分区表好？**

A：**不一定**。分区的主要收益不是查询加速，而是：

1. **管理方面**：`DROP` 分区代替 `DELETE` 大表（秒级 vs 小时级）、归档方便
2. **维护方面**：单分区可独立 VACUUM、REINDEX。减少 VACUUM 压力（每个分区死元组更少）
3. **查询方面**：通过分区裁剪减少扫描量（适合扫描大范围数据的时间序列场景）

**以下场景分区反而更慢：**
- 点查（`WHERE id = 42`）无分区裁剪，需扫描所有分区
- 频繁跨分区 UPDATE 改变分区键（性能极差）
- 分区数过多（>2000 个）导致计划器变慢

> **Q：分区表的主键必须包含分区键吗？**

A：PG 11+ 不强制要求**唯一索引**包含分区键，但**主键**仍必须包含分区键。因为 PG 目前不支持跨分区唯一性约束。如需全局唯一 ID，使用全局序列或 UUID。

---

## 8. 与 MySQL 全面对比

### 8.1 架构与存储引擎

| 维度 | PostgreSQL | MySQL |
|------|-----------|-------|
| 架构 | 进程模型（每个连接 fork 一个进程） | 线程模型（一个进程内多个线程） |
| 存储引擎 | 内置堆存储，无插件 | 插件式引擎（InnoDB / MyISAM / ...） |
| 进程/线程隔离 | 进程级强隔离，一个崩溃不影响其他 | 线程共享内存，一个线程可影响全局 |
| 连接管理 | 每个连接约 5-10MB 内存 | 每个连接约 200KB-2MB |
| 最大连接数 | 建议 ≤ 500（进程模型限制） | 轻松上千（线程模型） |
| MVCC 实现 | 元组头 xmin/xmax + 死元组 | Undo Log 回滚段 |
| 存储结构 | 堆表（Heap），无聚集索引强制要求 | 聚集索引组织表 (IOT) |

### 8.2 事务与 SQL 标准

| 维度 | PostgreSQL | MySQL |
|------|-----------|-------|
| ACID 实现 | 原生完整 ACID | InnoDB 完整 ACID，MyISAM 无事务 |
| 隔离级别 | 4 种（含 SERIALIZABLE 为真串行化，SSI 实现） | 4 种（SERIALIZABLE 实为快照隔离 + 锁） |
| DDL 事务 | 支持（DDL 可 ROLLBACK） | 不支持（DDL 隐含 COMMIT） |
| 窗口函数 | 完整支持（2003 标准） | PG 8.0+ 逐步支持（缺少部分可选帧） |
| CTE 递归 | 完整支持 | 8.0+ 支持（`WITH RECURSIVE`） |
| FULL OUTER JOIN | 支持 | 不支持（需 UNION 模拟） |
| MERGE/UPSERT | `ON CONFLICT DO UPDATE/DO NOTHING`（PG 9.5+） | `ON DUPLICATE KEY UPDATE` |
| RETURNING | 支持 | 不支持 |
| 数组/JSON/范围 | 原生支持 | JSON（非二进制），数组/范围无 |
| 多版本并发（MVCC） | 死元组清理依赖 VACUUM | Undo Log 自动回收（较少人工干预） |

### 8.3 复制机制

| 维度 | PostgreSQL | MySQL |
|------|-----------|-------|
| 内置复制 | 物理流复制 + 逻辑复制 | 异步复制 / 半同步 / Group Replication |
| 复制拓扑 | 一主多从、级联 | 一主多从、多主（Group Replication） |
| 同步复制 | 可配置至少 N 个备机确认 | 半同步（至少 1 个备机） |
| 逻辑复制粒度 | 表级，可过滤行 | 库级/表级（Group Replication 库级） |
| DDL 复制 | 物理复制自动，逻辑复制不支持 | 部分自动（有些需 GTID 模式） |
| 延迟监控 | `pg_stat_replication` 丰富指标 | `SHOW SLAVE STATUS` 基础指标 |
| 自动故障切换 | Patroni / repmgr（第三方案件成熟） | MySQL InnoDB Cluster / Orchestrator |

### 8.4 扩展能力

| 维度 | PostgreSQL | MySQL |
|------|-----------|-------|
| 自定义函数 | PL/pgSQL、PL/Python、PL/Java、PL/R | 存储过程（SQL/PSM） |
| 自定义类型 | CREATE TYPE 完整支持 | 不支持 |
| 自定义操作符 | 支持 | 不支持 |
| 索引扩展 | GiST、GIN、BRIN、Bloom 等可插拔 | InnoDB 仅 B-Tree；全文索引 MyISAM/InnoDB |
| 外部数据包装器（FDW） | 完整（访问 MySQL、MongoDB、CSV 等） | FEDERATED 引擎（功能弱） |
| 表空间 | 支持 | 不支持 |
| 部分索引 | 支持 | 不支持（虚拟列 + 索引变通） |
| 覆盖索引 | INCLUDE 子句（PG 11+） | 覆盖索引自动（按需） |

### 8.5 场景选择指南

**选 PostgreSQL 的场景：**

1. **复杂查询 / 分析型负载**：涉及多表 JOIN、窗口函数、递归 CTE
2. **数据完整性要求高**：ACID 严格一致性、强大约束（排他约束、CHECK）
3. **地理空间处理**：PostGIS 是行业标准
4. **JSON 文档 + 关系查询混合**：JSONB 索引查询能力远超 MySQL
5. **需要自定义类型/操作符**：金融、科学计算等特殊领域
6. **开源合规 / 避免 Oracle 生态依赖**
7. **DDL 事务安全和回滚能力**

**选 MySQL 的场景：**

1. **高并发简单读写（CRUD）**：线程模型 + InnoDB 高效处理大量短连接
2. **读写分离生态成熟**：MySQL 中间件（ProxySQL、MyCat）较成熟
3. **PHP 传统基建**：LAMP 生态深厚，运维人员多
4. **需要 Group Replication 多主写入**
5. **已有大规模 MySQL 运维体系（Aliyun RDS、TDSQL）**
6. **存储过程简单且需要大量 DBA 人力支持**
7. **云上托管服务**：RDS for MySQL 是云上最成熟的托管数据库之一

**技术选型红线：**

- **绝对不要因为「熟悉 MySQL」在需要 JSONB、PostGIS、递归 CTE、窗口函数深度使用的场景强行用 MySQL**
- **不要在预期承载极大量短连接的系统上裸用 PG（必须配 PgBouncer）**
- **不要忽视 PG 的 VACUUM 运维成本** — 表膨胀是 PG 的"原罪"，需持续监控

---

## 附录

### A. 速查 SQL 脚本

```sql
-- 数据库基本信息
SELECT version();
-- 查看运行时参数
SELECT name, setting, unit, context FROM pg_settings WHERE name IN (
  'shared_buffers', 'work_mem', 'maintenance_work_mem',
  'effective_cache_size', 'wal_buffers', 'max_connections',
  'random_page_cost', 'seq_page_cost', 'wal_level',
  'synchronous_commit', 'autovacuum'
);
-- 检查死元组和膨胀
SELECT schemaname, relname, n_live_tup, n_dead_tup,
  ROUND(100 * n_dead_tup / NULLIF(n_live_tup + n_dead_tup, 0), 2) AS dead_pct
FROM pg_stat_user_tables ORDER BY n_dead_tup DESC;
-- 检查长事务
SELECT pid, state, age(now(), xact_start) AS txn_duration, query
FROM pg_stat_activity WHERE state NOT IN ('idle', 'fastpath function call')
ORDER BY txn_duration DESC;
-- 检查索引使用情况
SELECT schemaname, tablename, indexname, idx_scan, idx_tup_read, idx_tup_fetch
FROM pg_stat_user_indexes ORDER BY idx_scan;
-- 未使用的索引
SELECT schemaname, tablename, indexname, idx_scan
FROM pg_stat_user_indexes WHERE idx_scan = 0;
```

### B. 面试高频问答拓扑

```
MVCC 实现差异 (PG vs MySQL)
  └─ Tuple freezing 与 wraparound 防护
索引体系
  ├─ 何时选择 BRIN 而非 B-Tree
  ├─ GIN vs GiST 全文检索选择
  ├─ Index-Only Scan 条件与 VM
  └─ CONCURRENTLY 创建索引的三阶段
SQL 高级
  ├─ 窗口函数 ROW_NUMBER 翻页 vs Keyset Pagination
  ├─ LATERAL JOIN 应用场景
  ├─ JSONB 索引优化：@> 操作数的性能影响
  └─ 递归 CTE 深度限制与环路检测
性能调优
  ├─ EXPLAIN ANALYZE 复盘清单（6 类信号）
  ├─ shared_buffers / work_mem 设定公式
  ├─ 分区表何时不提升性能
  └─ PG 查询计划缓存的独特设计
高可用
  ├─ 同步复制 RPO=0 的代价
  ├─ 逻辑复制 vs 物理复制选型
  └─ Patroni 选主原理与 RTO 优化
锁
  ├─ 行锁 vs 咨询锁的应用边界
  ├─ SKIP LOCKED 实现可靠队列
  └─ 死锁预防：锁顺序 + lock_timeout
MySQL 对比
  ├─ 进程 vs 线程模型的实际影响
  ├─ Vacuum 运维成本
  └─ 场景选型决策树
```

---

> **写在最后：** PostgreSQL 正在经历黄金时期 — 从 OLTP 传统场景向 HTAP、GIS、文档数据库、分布式扩展全面渗透。对于一位面试高级后端开发的候选人，理解 PG 的设计哲学（进程模型、堆表、MVCC 无 Undo、可扩展性内核）比死记硬背参数更有价值。**PG 的面试不仅仅是知识考察，更是对数据库底层原理理解深度的试金石。**
