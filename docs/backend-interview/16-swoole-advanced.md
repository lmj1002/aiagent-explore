# Swoole 协程通信引擎高级面试知识架构

> 目标受众：5-8 年经验的高级 PHP 开发 / 架构师
> 本文档聚焦 Swoole 作为常驻内存网络通信引擎的核心：进程模型、协程原理与调度、协程编程陷阱与上下文隔离、Channel/WaitGroup/Process 通信原语、生产实践。
> 关联文档：[PHP 高级面试知识架构](./01-php-advanced.md) · [Hyperf 框架](./15-hyperf-advanced.md) · [Laravel 框架](./14-laravel-advanced.md)

---

## 目录

1. [概述](#1-概述)
2. [Swoole 进程模型](#2-swoole-进程模型)
3. [协程（Coroutine）原理](#3-协程coroutine原理)
4. [协程编程的「坑」与上下文隔离](#4-协程编程的坑与上下文隔离)
5. [Channel / WaitGroup / Process 通信](#5-channel--waitgroup--process-通信)
6. [生产实践要点](#6-生产实践要点)

---

## 1. 概述

Swoole 是常驻内存的 PHP 网络通信引擎，以 C/C++ 编写的 PHP 扩展形式提供异步、协程、多进程能力。它把 PHP 从「PHP-FPM 请求即销毁」的短生命周期模型，变成「进程常驻 + 协程并发」的高性能服务模型，是 Hyperf、Laravel Octane 等高性能框架的底层引擎。

```
PHP 运行模式对比
┌─────────────┬─────────────────┬──────────────────────┐
│   PHP-FPM   │    Swoole       │       Swow           │
│  (进程模型)  │  (进程+协程)    │   (事件驱动协程)       │
├─────────────┼─────────────────┼──────────────────────┤
│ 每个请求=    │ 常驻内存进程,     │ 基于事件循环,          │
│ 独立进程     │ 按需创建协程     │ 全部协程化             │
│ 进程隔离     │ 协程共享内存     │ Actor 模型通信         │
│ 无状态       │ 有状态(需注意)   │ 内置 Channel          │
│ 冷启动       │ 热启动           │ 热启动                │
└─────────────┴─────────────────┴──────────────────────┘
```

**性能基准对比（Nginx + 压测，量级参考）：**

| 场景 | PHP-FPM | Swoole HTTP Server | Swow |
|------|---------|-------------------|------|
| 空路由 (qps) | ~10k | ~80k | ~90k |
| 简单 DB 查询 | ~3k | ~25k | ~28k |
| 内存占用/连接 | ~15 MB | ~2 MB | ~1.5 MB |

---

## 2. Swoole 进程模型

Swoole 启动后形成多层进程结构，区别于 PHP-FPM「请求即销毁」的短生命周期模型。

```
Swoole Server 进程模型
┌──────────────────────────────────────────────────────────┐
│ Master 进程                                                 │
│  └── Reactor 线程 (多线程, EventLoop)                       │
│       - 负责 TCP 连接的建立/收发, 协议解析                   │
│       - 不执行任何业务 PHP 代码                              │
├──────────────────────────────────────────────────────────┤
│ Manager 进程                                                │
│  └── 管理 Worker / Task Worker 的创建、回收、重启           │
├──────────────────────────────────────────────────────────┤
│ Worker 进程 (业务进程, 数量 = worker_num)                   │
│  └── 执行 onRequest / onReceive 等业务回调                  │
│       - 每个 Worker 内部用协程并发处理大量请求               │
├──────────────────────────────────────────────────────────┤
│ Task Worker 进程 (task_worker_num)                          │
│  └── 处理 task() 投递的异步耗时任务 (默认同步阻塞)           │
└──────────────────────────────────────────────────────────┘
```

**各进程职责对照：**

| 进程/线程 | 数量建议 | 职责 | 是否跑业务代码 |
|-----------|---------|------|---------------|
| Master | 1 | 总控、信号处理 | 否 |
| Reactor 线程 | CPU 核数 | I/O 收发、协议解析 | 否 |
| Manager | 1 | 进程守护、平滑重启 | 否（仅 onManagerStart） |
| Worker | CPU 核数 ~ 4×核数 | 业务逻辑、协程调度 | 是 |
| Task Worker | 按异步任务量 | 耗时同步任务（发邮件、生成报表） | 是 |

**面试 Q：Swoole 为什么比 PHP-FPM 快？**

核心在于消除了 PHP-FPM「每请求重建一切」的开销，并用协程把进程的并发能力放大了几个数量级。具体有四点：

1. **常驻内存**：框架引导（容器初始化、路由注册、配置加载）只在 `onWorkerStart` 执行一次，请求间复用，省去每次重建的开销
2. **协程化 I/O**：单个 Worker 用协程并发处理成千上万请求，I/O 等待时自动让出 CPU，无需多进程堆叠
3. **连接池复用**：MySQL/Redis 连接常驻，避免每请求建连/断连的 TCP 三次握手
4. **事件驱动**：Reactor 多路复用（epoll）取代 FPM 的「进程数 = 并发数」模型

---

## 3. 协程（Coroutine）原理

Swoole 协程是**用户态线程**，由引擎内置调度器在单线程内协作式调度，遇到 I/O 自动挂起（yield）并切换到其他协程，I/O 完成后再恢复（resume）。

```
协程调度模型 (单 Worker 进程内)
┌────────────────────────────────────────────────┐
│  Worker 进程 (单线程)                             │
│                                                  │
│  Coroutine Scheduler (调度器)                    │
│   ┌──────┐  yield   ┌──────┐  yield   ┌──────┐  │
│   │ Co#1 │ ───────► │ Co#2 │ ───────► │ Co#3 │  │
│   │ MySQL│  挂起     │ Redis│  挂起     │ HTTP │  │
│   └──┬───┘          └──┬───┘          └──┬───┘  │
│      │ I/O 完成        │ I/O 完成        │        │
│      └────── resume ───┴────── resume ──┘        │
│                                                  │
│  底层: epoll 事件循环 + ucontext/boost 上下文切换 │
└────────────────────────────────────────────────┘
```

**一键协程化（运行时 Hook）：**

```php
// 开启所有 I/O 函数的协程化 (Swoole 4.4+)
Swoole\Runtime::enableCoroutine(SWOOLE_HOOK_ALL);

Co\run(function () {
    // 这两个请求并发执行, 总耗时 ≈ max(t1, t2) 而非 t1 + t2
    $wg = new Swoole\Coroutine\WaitGroup();

    $results = [];
    foreach (['api1', 'api2'] as $api) {
        $wg->add();
        Coroutine::create(function () use ($wg, $api, &$results) {
            $results[$api] = file_get_contents("https://{$api}.example.com");
            $wg->done();
        });
    }
    $wg->wait();  // 等待所有子协程完成
});
```

**面试 Q：协程、线程、进程的区别？**

三者是不同粒度的「并发执行单元」。进程是操作系统资源分配的最小单位，拥有独立地址空间，隔离性最好但创建和切换开销最大；线程是 CPU 调度的最小单位，共享所属进程的内存，切换比进程轻，但仍由操作系统抢占式调度、需要加锁保护共享数据。协程则是「用户态线程」——调度完全发生在应用层，由协程库（如 Swoole 调度器）在单个线程内协作式切换：遇到 I/O 主动让出，无需陷入内核，所以切换成本极低、单进程可承载数十万并发。代价是协作式调度要求代码不能长时间阻塞（否则饿死同线程其他协程），且同线程内共享变量虽不用加锁，却必须做协程上下文隔离以防数据串号。

| 维度 | 进程 | 线程 | 协程 |
|------|------|------|------|
| 调度者 | 操作系统 | 操作系统 | 用户态调度器（应用自己） |
| 切换成本 | 高（页表、上下文） | 中（共享内存） | 极低（仅保存寄存器/栈） |
| 并发量级 | 数百 | 数千 | 数十万 |
| 抢占 | 抢占式 | 抢占式 | 协作式（主动让出） |
| 数据共享 | IPC | 共享内存（需锁） | 同线程内共享（无需锁，但需上下文隔离） |

---

## 4. 协程编程的「坑」与上下文隔离

常驻内存 + 协程并发，最大的陷阱是**全局/静态变量被多个协程共享**，导致数据串号。

```php
// 反模式: 类静态属性在协程间共享, 请求 A 的用户可能读到请求 B 的数据
class UserContext
{
    public static int $userId = 0;  // 危险! 多协程共享同一份
}

// 正确做法: 使用基于协程 ID 隔离的上下文
use Hyperf\Context\Context;

Context::set('user_id', $userId);   // 仅当前协程可见
$uid = Context::get('user_id');     // 协程切换/销毁后自动清理

// Swoole 原生方式
$cid = Swoole\Coroutine::getCid();          // 当前协程 ID
$context = Swoole\Coroutine::getContext();  // 协程级 ArrayObject, 协程结束自动 GC
$context['user_id'] = $userId;
```

**协程陷阱清单：**

| 陷阱 | 后果 | 解决方案 |
|------|------|---------|
| 全局/静态变量共享 | 数据串号、越权 | 改用 `Context`（协程 ID 隔离） |
| 单例持有连接 | 多协程复用同一连接导致数据错乱 | 连接池 + 每协程借还 |
| 在协程外使用协程 API | 报错 `must be called in the coroutine` | 用 `Co\run()` 包裹入口 |
| 协程中使用阻塞函数 | `sleep()`/原生 curl 阻塞整个 Worker | 开启 Hook 或用协程版 API |
| 协程死循环不让出 | 调度饥饿，其他协程无法执行 | 循环中插入 `Coroutine::sleep(0)` 或保证有 I/O |
| `defer` 资源未释放 | 连接泄露 | 用 `Coroutine\defer()` 注册协程结束回调 |

**连接池模型（生产必备）：**

```php
use Swoole\Coroutine\Channel;

class MysqlPool
{
    private Channel $pool;

    public function __construct(int $size = 64)
    {
        $this->pool = new Channel($size);  // Channel 作为协程安全队列
        for ($i = 0; $i < $size; $i++) {
            $this->pool->push($this->createConnection());
        }
    }

    public function get(): \PDO
    {
        return $this->pool->pop();   // 池空时协程挂起等待
    }

    public function put(\PDO $conn): void
    {
        $this->pool->push($conn);    // 用完归还, 而非关闭
    }
}
```

---

## 5. Channel / WaitGroup / Process 通信

Swoole 提供协程安全的通信原语，类似 Go 的 CSP（Communicating Sequential Processes）模型。

| 原语 | 用途 | 类比 |
|------|------|------|
| `Coroutine\Channel` | 协程间数据传递、连接池、生产者消费者 | Go channel |
| `Coroutine\WaitGroup` | 等待一组协程全部完成 | Go sync.WaitGroup |
| `Coroutine\Barrier` | 基于引用计数的协程屏障（更现代） | — |
| `Atomic` / `Atomic\Long` | 进程间共享原子计数器（基于共享内存） | 原子变量 |
| `Table` | 进程间共享内存表（高性能 KV） | 共享内存 + 自旋锁 |
| `Process` / `Process\Pool` | 多进程通信（管道/消息队列） | — |
| `Lock` | 互斥锁（Mutex/读写锁/自旋锁） | — |

```php
// Channel 实现生产者-消费者
$chan = new Swoole\Coroutine\Channel(10);

Coroutine::create(function () use ($chan) {   // 生产者
    foreach (range(1, 100) as $i) {
        $chan->push($i);
    }
    $chan->push(null);  // 结束信号
});

Coroutine::create(function () use ($chan) {   // 消费者
    while (($data = $chan->pop()) !== null) {
        process($data);
    }
});
```

> **进程间共享 vs 协程间共享：** `Table`/`Atomic` 用于**多 Worker 进程**间共享数据（基于共享内存，需在 Server 启动前创建）；`Channel`/`Context` 仅在**单进程内的协程**间有效。跨进程统计（如全局计数器）必须用 `Atomic`，用普通变量会因进程隔离而失效。

---

## 6. 生产实践要点

| 场景 | 实践 |
|------|------|
| 内存泄露 | Worker 设置 `max_request`（处理 N 个请求后重启），兜底内存增长 |
| 平滑重启 | `Server::reload()` 重载 Worker，配合发布灰度 |
| 长连接保活 | MySQL 连接池设置 `heartbeat`，防 `gone away` |
| 阻塞排查 | 避免在协程中调用未 Hook 的扩展（如某些加密/图像库 C 扩展） |
| 异常处理 | 协程内异常不会冒泡到其他协程，需在协程入口 `try/catch` 兜底 |
| CPU 密集任务 | 投递到 Task Worker 或独立进程，避免阻塞协程调度 |
| 调试 | `Swoole\Coroutine::stats()` 查看协程数量；`Co::list()` 列出活跃协程 |

**面试 Q：什么业务适合用 Swoole，什么不适合？**

判断的核心是「是不是 I/O 密集 + 高并发」。Swoole 的优势全部来自协程对 I/O 等待的高效复用，所以高并发 API、长连接推送、网关聚合这类 I/O 密集场景收益最大；而纯 CPU 密集计算协程帮不上忙（CPU 没有等待可让出），反而徒增协程编程的复杂度。另一个关键约束是生态——重度依赖非协程安全 C 扩展的遗留系统迁移成本高，团队若无协程经验，踩「数据串号」「连接泄露」的坑代价也不小。

| 适合 | 不适合 |
|------|--------|
| 高并发 API / 微服务（I/O 密集） | 团队无协程经验、维护成本敏感的小项目 |
| WebSocket 长连接、IM、推送 | 重度依赖非协程安全 C 扩展的遗留系统 |
| 网关、BFF 聚合层 | 纯 CPU 密集计算（协程无优势，反增复杂度） |
| 实时性要求高的内部 RPC 服务 | 快速验证的原型（Laravel 开发效率更高） |

---

> **维护说明：**
> - 最新更新：2026-06 | Swoole 版本覆盖 5.x
> - 关联文档：[01-PHP](./01-php-advanced.md) · [14-Laravel](./14-laravel-advanced.md) · [15-Hyperf](./15-hyperf-advanced.md)
