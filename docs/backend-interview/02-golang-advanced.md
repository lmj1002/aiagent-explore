# 高级 Go 开发面试知识架构

> 目标受众：5-8年经验的高级后端开发 / 架构师（PHP 转 Go 路线）
> 文档定位：面试备战 + 生产实践参考 + 体系化知识图谱

---

## 目录

1. [语言核心](#1-语言核心)
2. [并发编程](#2-并发编程)
3. [运行时原理](#3-运行时原理)
4. [标准库深度](#4-标准库深度)
5. [框架与微服务](#5-框架与微服务)
6. [数据库与缓存](#6-数据库与缓存)
7. [性能调优](#7-性能调优)
8. [工程实践](#8-工程实践)
9. [消息队列集成](#9-消息队列集成)
10. [Go vs PHP 高阶对比](#10-go-vs-php-高阶对比)

---

## 1. 语言核心

### 1.1 Goroutine 与 Channel

#### 高频面试题

**Q: Goroutine 与操作系统线程的区别？**

GMP 模型是理解 Go 并发的基石。Goroutine 是用户态轻量级线程（协程），初始栈仅 2KB（Go 1.4 起），可动态扩缩至 1GB。OS 线程栈通常为 1-8MB。Go 运行时将 M 个 goroutine 多路复用到 N 个 OS 线程上（M:N 调度）。

| 维度 | Goroutine | OS 线程 |
|------|-----------|---------|
| 创建成本 | ~4KB 栈，微秒级 | ~1-8MB 栈，毫秒级 |
| 上下文切换 | 用户态，~100ns | 内核态，~1-5μs |
| 调度器 | Go runtime 自管理 | OS 内核管理 |
| 数量上限 | 百万级 | 万级（受内存限制） |

**Q: Channel 底层数据结构是怎样的？**

```go
// runtime/chan.go (简化)
type hchan struct {
    qcount   uint           // 队列中元素个数
    dataqsiz uint           // 环形队列大小
    buf      unsafe.Pointer // 指向环形队列的指针
    elemsize uint16         // 元素大小
    closed   uint32
    elemtype *_type         // 元素类型
    sendx    uint           // 发送索引
    recvx    uint           // 接收索引
    recvq    waitq          // 接收者等待队列
    sendq    waitq          // 发送者等待队列
    lock     mutex          // 互斥锁保护所有字段
}
```

Channel 本质是带锁的环形缓冲区 + 双端等待队列（发送/接收各一个）。发送时若缓冲区未满则写入环形队列；若满则挂起当前 goroutine 到 sendq。接收同理。

#### 代码示例

```go
// 无缓冲 channel：同步通信，发送/接收必须配对
func unbufferedDemo() {
    ch := make(chan int)
    go func() {
        ch <- 42 // 阻塞直到 main goroutine 接收
    }()
    val := <-ch // 阻塞直到 goroutine 发送
    fmt.Println(val)
}

// 有缓冲 channel：异步通信，缓冲区满才阻塞
func bufferedDemo() {
    ch := make(chan int, 3)
    ch <- 1 // 不阻塞
    ch <- 2
    ch <- 3
    // ch <- 4 // 缓冲区满，阻塞
    close(ch)
    for v := range ch {
        fmt.Println(v)
    }
}

// select 多路复用 + 超时
func selectTimeout(ctx context.Context) {
    ch := make(chan Result, 1)
    go func() {
        ch <- heavyCompute()
    }()
    select {
    case res := <-ch:
        handleResult(res)
    case <-ctx.Done():
        log.Println("timeout or cancelled")
    case <-time.After(5 * time.Second):
        log.Println("5s timeout")
    }
}
```

#### 生产最佳实践

- **Channel 的方向**：函数参数中尽量显式标明 `<-chan`（只读）或 `chan<-`（只写），编译器保证方向安全
- **关闭 Channel**：应由发送方关闭，接收方不应关闭。向已关闭 channel 发送会 panic
- **Channel 的零值**：未初始化的 channel（nil）会永久阻塞，可利用此特性动态开关 case 分支
- **不要泄漏 goroutine**：确保每个 goroutine 都有退出路径（context 取消、channel 关闭、超时等）

---

### 1.2 内存模型

#### 高频面试题

**Q: Go 内存模型中的 happens-before 关系是怎样的？**

Go 内存模型定义了一套规则，保证在一个 goroutine 中对变量的写操作能被另一个 goroutine 的读操作观察到。核心规则：

1. **单个 goroutine 内**：代码顺序即 happens-before 顺序（sequential consistency）
2. **Channel 发送/接收**：`ch <- v` happens-before `<-ch` 返回
3. **Close channel**：`close(ch)` happens-before 从该 channel 收到零值
4. **Mutex**：`Unlock()` happens-before 另一个 goroutine 的 `Lock()` 返回
5. **WaitGroup**：`Wait()` 返回 happens-before 所有 `Done()` 调用
6. **Once**：`Do(f)` 中的 `f()` 返回 happens-before 所有 `Do` 返回

```go
var msg string
var done bool

func setup() {
    msg = "hello"      // (1)
    done = true        // (2) — 编译器可能重排到 (1) 之前！
}

func main() {
    go setup()
    for !done {}       // 可能永远看不到 done=true
    fmt.Println(msg)   // 可能打印空字符串
}
```

**Q: 为什么需要 sync/atomic 而不是直接赋值？**

```go
// 错误：存在 data race
var counter int
go func() { counter++ }() // 读取-修改-写入 非原子
go func() { counter++ }()

// 正确：原子操作
var counter atomic.Int64
counter.Add(1) // 使用 CPU 的 CAS 指令，无锁

// 正确：互斥锁
var mu sync.Mutex
mu.Lock()
counter++
mu.Unlock()
```

`counter++` 不是原子的，它包含三条 CPU 指令：LOAD、ADD、STORE。两个 goroutine 同时执行可能导致结果少 1。

#### 生产最佳实践

- 对共享变量的访问应通过 channel（"Do not communicate by sharing memory; instead, share memory by communicating."）
- 必须使用共享内存时，用 `sync.Mutex` 或 `atomic` 保护，不要依赖非形式化的 happens-before 推理
- 使用 `-race` 标志在测试和 CI 中检测数据竞争

---

### 1.3 GMP 调度模型

#### 高频面试题

**Q: 解释 GMP 调度的完整流程以及阻塞场景的处理？**

**GMP 三要素：**
- **G (Goroutine)**：携带栈、上下文、状态
- **M (Machine)**：OS 线程，由内核管理
- **P (Processor)**：调度上下文，持有本地 goroutine 队列（runq），默认数量 = `GOMAXPROCS`

**调度循环：**
```
M 绑定 P → 从 P 的本地队列取 G → 执行 G → G 阻塞/退出/yield → 取下一 G
若本地队列空 → 从全局队列偷（加锁）→ 从其他 P 偷一半（work stealing）
```

**阻塞场景处理：**

| 阻塞类型 | GMP 行为 |
|----------|----------|
| Channel 阻塞 | G 挂起到等待队列，M 和 P 解绑，M 返回 P 队列取下一 G |
| 系统调用阻塞（如文件 IO） | G 和 M 一起阻塞，P 解绑，调度器创建或唤醒新的 M 接替 P |
| 网络 IO 阻塞 | Go 1.14 起用非阻塞 IO + epoll/kqueue 轮询，G 不阻塞 M |
| time.Sleep | G 进入 timer 队列，M 继续执行其他 G |
| 锁阻塞 (sync.Mutex) | G 进入锁的等待队列，Go 1.18 起支持基于信号量的 M 阻塞优化 |

**Q: GOMAXPROCS 应该设置多大？**

通常设置为 CPU 核心数。在容器环境中，正确做法是：

```go
// 自动识别容器 CPU 限制
import "go.uber.org/automaxprocs"

func init() {
    _ = automaxprocs.Set() // 自动读取 cgroup CPU 配额
}
```

非 CPU 密集型（IO 密集型）可适当增加 GOMAXPROCS 以提升吞吐，但超过 CPU 核心数 2-3 倍后收益递减。

#### 生产最佳实践

- 避免 goroutine 泄漏：所有 goroutine 应通过 `context.Context` 可取消
- `GOMAXPROCS` 在容器中必须通过 `automaxprocs` 自动适配，否则 Docker/K8s 限定 4 核但 Go 会检测到物理机 64 核导致 P 过多
- 控制 goroutine 总数：用 worker pool 模式限制并发数

---

### 1.4 GC 机制

#### 高频面试题

**Q: 解释 Go GC 的三色标记清除算法细节？**

Go 的 GC 是**并发三色标记-清除**（CMS 风格），**非分代、非压缩**。

**三色定义：**
- **白色**：未被 GC 访问的对象（候选清除）
- **灰色**：已被访问但子对象未被扫描
- **黑色**：已被访问且所有子对象已扫描

**流程：**
1. **标记准备（GC 开始）**：STW 开启写屏障，所有 P 标记为灰色根集合
2. **并发标记**：GC worker 灰色→黑色扫描；并发期间通过**插入写屏障**（Dijkstra）和**删除写屏障**（Yuasa）保证正确性。Go 1.8+ 使用**混合写屏障**（插入+删除）
3. **标记终止**：STW 完成标记，关闭写屏障
4. **并发清除**：后台 goroutine 逐步回收白色对象；同时新分配直接使用

**触发条件：**
- **内存阈值**：Go 1.18 起默认 100%。即当前堆大小达到上次 GC 后存活堆大小的 2 倍时触发
- **定时触发**：若 2 分钟未触发 GC，强制触发一次
- **手动触发**：`runtime.GC()`
- `GOGC` 环境变量可调节：`GOGC=50` 表示堆增长 50% 即触发

```go
// 查看 GC 详细日志
// GODEBUG=gctrace=1 ./app
// gc 1 @0.003s 2%: 0.008+0.8+0.009 ms clock, 0.064+0.20/0.35/0.20+0.075 ms cpu, 4->4->2 MB, 5 MB goal, 8 P
// 解释: gc 周期 | 耗时 | cpu 时间 | 堆大小 开始->标记后->存活 | 目标 | P 数
```

**Q: GC 调优策略有哪些？**

```go
// 1. 调整 GOGC 降低 GC 频率（适合吞吐优先）
//    GOGC=200  → 堆膨胀到 200% 才 GC，减少 GC 次数但增加内存
//    GOGC=off  → 完全关闭 GC（Go 1.19+ 实验特性）

// 2. 减少内存分配，消除指针（关键！）
//    - 复用对象（sync.Pool）
//    - 使用切片而非 map 存储小对象
//    - 预分配切片 cap 减少 reallocation

// 3. 减少跨 goroutine 指针共享（写屏障开销大）
```

**Q: GC 在 Go 中的优化演进？**

| 版本 | 改进 |
|------|------|
| Go 1.5 | 首个并发 GC，STW 约 10-100ms |
| Go 1.6 | 延迟降低至 5-20ms |
| Go 1.7 | 减少栈扫描时间 |
| Go 1.8 | 混合写屏障，STW < 1ms |
| Go 1.9 | 提升大堆场景性能 |
| Go 1.10-1.12 | 细粒度优化 |
| Go 1.13 | 重写计时器管理，减少 GC 压力 |
| Go 1.19 | 软内存限制 `GOMEMLIMIT`，平滑 OOM 行为 |
| Go 1.21 | 改进内存限制机制 |

#### 生产最佳实践

- **Go 1.19+** 设置 `GOMEMLIMIT`（软内存限制），避免 GC 在峰值前不触发导致 OOM
- 对延迟敏感的服务，保持 GC 次数合理：每秒不超过 1-2 次
- 对高吞吐服务适度提高 GOGC（如 200-400），以内存换 CPU
- 关键路径减少 `string` 拼接（产生临时对象），使用 `strings.Builder`
- 避免指针密集型数据结构

---

## 2. 并发编程

### 2.1 sync 包深度解析

#### 高频面试题

**Q: Mutex 的饥饿模式（starvation mode）与正常模式的区别？**

Go 1.9 起 Mutex 有两种模式：

**正常模式（Normal Mode）：**
- 等待者按 FIFO 排队
- 锁被释放时，在队列头的 goroutine 与新到达的 goroutine 竞争
- 新到达的 goroutine 更容易获得锁（已经在 CPU 上运行），导致队列头 goroutine 可能饥饿

**饥饿模式（Starvation Mode）：**
- 当某 goroutine 等待超过 1ms 仍未获得锁时进入
- 锁释放时直接交给队列头 goroutine，不竞争
- 当队列头 goroutine 获得锁且等待时间 < 1ms 时退出饥饿模式

```go
// RWMutex 使用：读多写少场景
type SafeCache struct {
    mu    sync.RWMutex
    store map[string]any
}

func (c *SafeCache) Get(key string) any {
    c.mu.RLock()
    defer c.mu.RUnlock()
    return c.store[key]
}

func (c *SafeCache) Set(key string, val any) {
    c.mu.Lock()
    defer c.mu.Unlock()
    c.store[key] = val
}
```

**Q: sync.WaitGroup 内部原理？**

```go
type WaitGroup struct {
    noCopy noCopy          // 禁止值拷贝
    state1 [3]uint32       // 64位对齐: [counter, waiter_count, sema]
}

// state() 返回 statep 和 semap
// counter — 未完成的 goroutine 数量
// waiter — 调用 Wait() 等待的 goroutine 数量
// semap — 信号量，用于阻塞/唤醒
```

底层用 atomic 操作 + 信号量实现。`Add(delta)` 原子增减 counter，`Wait()` 原子增加 waiter 并在 counter>0 时阻塞在信号量上，最后一个 `Done()`（counter 归零）触发 sema wake。

**Q: sync.Once 是如何保证只执行一次的？**

```go
type Once struct {
    done uint32   // 1 表示已执行
    m    Mutex    // 互斥保护临界区
}

func (o *Once) Do(f func()) {
    if atomic.LoadUint32(&o.done) == 0 {
        o.doSlow(f)
    }
}
func (o *Once) doSlow(f func()) {
    o.m.Lock()
    defer o.m.Unlock()
    if o.done == 0 {   // double-check
        defer atomic.StoreUint32(&o.done, 1)
        f()
    }
}
```

关键设计：先原子检查（fast path），再加锁确认（slow path + double-check），兼顾性能与正确性。

**Q: sync.Pool 的使用场景和注意事项？**

```go
var bufPool = sync.Pool{
    New: func() any {
        return bytes.NewBuffer(make([]byte, 0, 4096))
    },
}

func handleRequest(w http.ResponseWriter, r *http.Request) {
    buf := bufPool.Get().(*bytes.Buffer)
    buf.Reset()
    defer bufPool.Put(buf)
    // 使用 buf ...
}
```

注意事项：
- Pool 中的对象可能随时被 GC 回收（两次 GC 之间存活）
- 不能假设 Get 返回的对象一定存在
- 不适合持久化对象（如数据库连接池）
- 适合高频创建销毁的临时对象（buffer、序列化中间对象）

#### 生产最佳实践

- `sync.Mutex` 不可复制（嵌入 `noCopy` 字段，`go vet` 可检测）
- 避免在使用 Mutex 时调用可能 panic 或长时间阻塞的函数
- 使用 `sync.Map` 的场景：读远多于写、key 生命周期不重叠、不同 goroutine 操作不同 key —— 大多数场景下普通 `map + sync.RWMutex` 性能更好
- `errgroup.Group` 比 `sync.WaitGroup` 更适合多 goroutine 任务并收集首个错误

---

### 2.2 Context 包

#### 高频面试题

**Q: Context 的设计哲学与传播原则？**

Context 的核心是 goroutine 树上传递**取消信号**、**超时/截止时间**和**请求级元数据**。

```go
// 派生关系树
ctx := context.Background()          // 根节点，永不取消
// 或
ctx := context.TODO()                // 不确定用哪个时占位

ctx, cancel := context.WithCancel(ctx)         // 可取消
ctx, cancel := context.WithTimeout(ctx, 3*time.Second) // 超时取消
ctx, cancel := context.WithDeadline(ctx, deadline)     // 截止时间
ctx = context.WithValue(ctx, "key", "val")    // 附加元数据
```

**传播原则：**
- Context 应作为函数第一个参数传递（约定）
- 不应将 Context 存储在结构体中，应显式传递
- 在中间件/框架入口创建，在整个请求链中传递

**Q: context.WithValue 的查找算法与注意事项？**

```go
// context.WithValue 创建新节点
type valueCtx struct {
    Context
    key, val any
}
// 查找是链表 O(n) 遍历，从当前节点向父节点递归
func (c *valueCtx) Value(key any) any {
    if c.key == key {
        return c.val
    }
    return c.Context.Value(key)
}
```

注意事项：
- key 必须是可比较类型（`==` 可比较），推荐自定义类型而非 `string`
- 仅传递请求域数据（trace id、认证信息），不要传递可选参数
- 查找是 O(n)，大量 key 时考虑直接用 map

```go
// 推荐的 key 类型
type contextKey string
const (
    TraceIDKey contextKey = "trace_id"
    UserIDKey  contextKey = "user_id"
)
```

#### 生产最佳实践

- 任何可能阻塞或耗时的操作都应接受 context
- 使用 `select { case <-ctx.Done(): return ctx.Err(); default: }` 检测取消
- 外部库不接受 context 时，用 `done := make(chan struct{})` + `select` 包装
- 父 context 取消时，所有子 context 级联取消

---

### 2.3 并发模式 Pipeline / Fan-in / Fan-out

#### 高频面试题

**Q: 如何用 Go 实现 Pipeline 并发模式？**

Pipeline 模式将任务拆分为多个阶段，每个阶段由一组 goroutine 处理，通过 channel 连接。

```go
// 三阶段 Pipeline: generate → square → print
func main() {
    in := generate(2, 3, 5, 7, 11)
    out := square(in)  // 可并发 fan-out
    printResults(out)
}

func generate(nums ...int) <-chan int {
    out := make(chan int)
    go func() {
        for _, n := range nums {
            out <- n
        }
        close(out)
    }()
    return out
}

func square(in <-chan int) <-chan int {
    out := make(chan int)
    go func() {
        for n := range in {
            out <- n * n
        }
        close(out)
    }()
    return out
}
```

**Q: Fan-out / Fan-in 的实现？**

Fan-out：一个 channel 分发给多个 goroutine 并行处理。
Fan-in：多个 channel 合并为一个 channel。

```go
// Fan-out: 启动 N 个 worker 并行处理
func fanOut(in <-chan int, numWorkers int) []<-chan int {
    channels := make([]<-chan int, numWorkers)
    for i := 0; i < numWorkers; i++ {
        ch := make(chan int)
        channels[i] = ch
        go func(c chan int) {
            for v := range in {
                c <- heavyProcess(v)
            }
            close(c)
        }(ch)
    }
    return channels
}

// Fan-in: 合并多个 channel
func fanIn(channels ...<-chan int) <-chan int {
    out := make(chan int)
    var wg sync.WaitGroup
    wg.Add(len(channels))

    for _, ch := range channels {
        go func(c <-chan int) {
            defer wg.Done()
            for v := range c {
                out <- v
            }
        }(ch)
    }

    go func() {
        wg.Wait()
        close(out)
    }()

    return out
}
```

**Q: Or-Done channel 模式？**

```go
// 将非 context 感知的 channel 包装为可取消的 channel
func orDone(ctx context.Context, in <-chan int) <-chan int {
    out := make(chan int)
    go func() {
        defer close(out)
        for {
            select {
            case <-ctx.Done():
                return
            case v, ok := <-in:
                if !ok {
                    return
                }
                select {
                case out <- v:
                case <-ctx.Done():
                    return
                }
            }
        }
    }()
    return out
}
```

#### 生产最佳实践

- 始终由发送方关闭 channel，接收方不要关闭
- 控制 goroutine 数量（worker pool 模式），避免 goroutine 风暴
- 使用 `context.Context` 使 pipeline 可取消
- 关注 backpressure（背压）：缓冲区满时阻塞上游，自然实现限流

---

### 2.4 并发错误处理

#### 高频面试题

**Q: 如何在多个 goroutine 中收集错误？**

```go
// 方案 1: errgroup（推荐）
import "golang.org/x/sync/errgroup"

func main() {
    g, ctx := errgroup.WithContext(context.Background())

    urls := []string{"http://example.com/a", "http://example.com/b"}
    for _, url := range urls {
        url := url
        g.Go(func() error {
            req, _ := http.NewRequestWithContext(ctx, "GET", url, nil)
            _, err := http.DefaultClient.Do(req)
            return err
        })
    }

    if err := g.Wait(); err != nil {
        log.Printf("some goroutine failed: %v", err)
    }
}

// 方案 2: 自定义 error channel
func collectErrors(ctx context.Context, tasks []func() error) error {
    errCh := make(chan error, len(tasks))
    var wg sync.WaitGroup
    for _, task := range tasks {
        wg.Add(1)
        go func(fn func() error) {
            defer wg.Done()
            if err := fn(); err != nil {
                errCh <- err
            }
        }(task)
    }

    go func() {
        wg.Wait()
        close(errCh)
    }()

    // 返回第一个错误（或等待全部完成）
    select {
    case err := <-errCh:
        return err
    case <-ctx.Done():
        return ctx.Err()
    }
}
```

**Q: panic 在 goroutine 中的传播？**

```go
// goroutine 中的 panic 会导致整个进程崩溃！
// 必须在每个 goroutine 入口处用 recover 保护
func safeGo(fn func()) {
    go func() {
        defer func() {
            if r := recover(); r != nil {
                log.Printf("goroutine panicked: %v\n%s", r, debug.Stack())
            }
        }()
        fn()
    }()
}
```

#### 生产最佳实践

- goroutine 入口必加 `recover()`，记录 stack trace 后按需重启或优雅退出
- 使用 `errgroup.Group` 替代 `sync.WaitGroup` 做并发任务
- 需要限制并发数 + 错误收集时使用 `golang.org/x/sync/semaphore`
- 避免在 defer 中做复杂操作或在错误不在预期时吞掉 recover

---

## 3. 运行时原理

### 3.1 内存分配与逃逸分析

#### 高频面试题

**Q: Go 的内存分配器是如何工作的？（基于 tcmalloc）**

Go 的内存分配器基于 tcmalloc 思想，将对象按大小分为三类：

| 类别 | 大小 | 管理方式 |
|------|------|----------|
| Tiny 微对象 | < 16B | 在 mcache 的 tiny allocator 中分配 |
| Small 小对象 | 16B ~ 32KB | 按 size class 在 mcache/mcentral 中分配 |
| Large 大对象 | > 32KB | 直接从 mheap 分配 |

**分配路径：**
```
对象 → 确定 size class → mcache (per-P，无锁) → mcentral (需锁) → mheap (madvise)
```
- mcache 是 per-P 的无锁缓存，90% 以上的分配在此完成
- mcentral 是全局的每个 size class 的 central free list
- mheap 管理从 OS 申请的大块内存（heap arena）

**Q: 逃逸分析（Escape Analysis）的原理？**

编译器在编译时分析变量作用域，决定分配在栈上还是堆上。逃逸分析的核心是**变量被外部引用**。

```go
func escape() *int {
    x := 42
    return &x  // x 逃逸到堆上——因为返回后栈帧销毁，地址仍被引用
}

func noEscape() int {
    x := 42
    return x   // x 不逃逸——值拷贝
}

func interfaceEscape() {
    f := 3.14
    fmt.Printf("%v", f)  // f 逃逸：interface{} 参数导致逃逸
}

// 验证：go build -gcflags="-m -m" 查看逃逸分析结果
```

**常见逃逸场景：**
1. 返回局部变量指针
2. 变量被闭包捕获（闭包引用外部的变量）
3. 变量被赋值到 interface{} 类型（编译器无法确定具体类型，通常需堆分配）
4. 切片 `make([]T, n)` 中 n 为变量（非常量）
5. 将变量放入 map 中（map 的 value 是指针类型时 key 逃逸）
6. 栈空间不足（如超大局部数组）

```go
// 闭包逃逸示例
func closureEscape() func() int {
    x := 0            // x 逃逸到堆
    return func() int {
        x++
        return x
    }
}

// 切片长度变量逃逸
func sliceEscape(n int) []int {
    return make([]int, n)  // 逃逸：n 在编译时未知
}
func sliceNoEscape() []int {
    return make([]int, 10) // 不逃逸：常量长度
}
```

#### 生产最佳实践

- 用 `go build -gcflags="-m"` 检查逃逸，热点路径确保关键结构体不逃逸
- 小对象尽量用值传递，仅在函数间共享或修改时使用指针
- interface{} 的装箱（boxing）会触发堆分配，高频场景下避免
- `sync.Pool` 用于重用高频分配的对象
- 使用 `[]byte` 而非 `string` 做拼接（`bytes.Buffer` / `strings.Builder`）

---

### 3.2 栈 vs 堆

#### 高频面试题

**Q: 栈和堆分配的性能差异有多大？**

| 特征 | 栈 | 堆 |
|------|-----|-----|
| 分配速度 | 一条指令（SP 加减） | 复杂路径（mcache→…→mheap）|
| 回收 | 函数返回自动弹出 | GC 标记清除 |
| 并发安全 | 天然安全（per-goroutine） | 需要同步 |
| 典型耗时 | 纳秒级 | 数十纳秒到微秒级 |

栈分配几乎免费：`SUBQ $32, SP` 就完成了栈帧创建。堆分配涉及查找空闲块、写屏障、GC 标记等。

**Q: Go 的栈是固定大小还是动态可伸缩？**

动态伸缩。Go 1.4 起使用**连续栈**（Contiguous Stack）：
1. 初始栈：2KB
2. 栈满检测：在函数调用前检查 `SP - 栈帧 < 栈边界`
3. 栈扩容（Stack Copying）：将旧栈内容拷贝到新栈（通常 2x 增长），更新所有指针
4. 栈收缩（GC 时）：如果栈使用率 < 25%，收缩到一半

栈的拷贝涉及**栈重定向（stack copying）**的复杂性：
- Go 编译器在栈上变量被取地址时，会生成根指针信息（stack map）
- GC 和栈拷贝根据 stack map 更新指针值
- 因此 Go 中不用手动管理栈地址——但 `uintptr` 不是指针，不会被更新！

```go
func dangerous() {
    x := 42
    p := uintptr(unsafe.Pointer(&x)) // uintptr 是整数，不是 GC 指针！
    runtime.GC()                     // 栈可能已移动
    // p 仍然指向旧栈地址 —— 野指针！
}
```

#### 生产最佳实践

- 热点路径尽量保持变量在栈上：不逃逸、不逃 interface{}、不返回指针
- 避免 `uintptr` 保存指针值——使用 `unsafe.Pointer` 并在同一表达式内完成操作
- 递归深度应控制，否则栈扩张代价高（Go 默认栈上限 1GB，但大栈扩张有拷贝成本）

---

### 3.3 指针与值传递

#### 高频面试题

**Q: 值接收者 vs 指针接收者？**

```go
type User struct {
    Name string
    Age  int
}

// 值接收者：操作副本
func (u User) String() string {
    return fmt.Sprintf("%s (%d)", u.Name, u.Age) // 拷贝 User
}

// 指针接收者：可修改原值
func (u *User) Birthday() {
    u.Age++ // 修改原对象
}

// 选择原则：
// - 需要修改接收者 → 指针接收者
// - 大型结构体（> 几十字节） → 指针接收者（避免拷贝）
// - 小型不可变结构体 → 值接收者（可被内联优化）
// - 保持一致性：同一类型的方法要么全用值接收者，要么全用指针接收者
```

**Q: Go 中 slice 是引用类型吗？**

```go
// slice 包含三个字段：指针 + 长度 + 容量 —— 实际上是结构体
type slice struct {
    array unsafe.Pointer // 底层数组指针
    len   int
    cap   int
}

// 传 slice 是值拷贝，但拷贝的是 slice 结构体（包含指向同一底层数组的指针）
func modifySlice(s []int) {
    s[0] = 100          // 修改底层数组，反映到调用方
    s = append(s, 200)  // 新切片赋值给局部变量，调用方不可见
    // 除非用指针 *[]int 或返回新切片
}
```

**Q: map 是引用类型吗？**

```go
// map 指针：make(map[string]int) 返回的是 *hmap
// 传递时永远不会触发 hmap 结构体拷贝——只拷贝指针
func modifyMap(m map[string]int) {
    m["key"] = 100 // 修改源 map
    // 但 m = make(map[string]int) 不影响调用方（参数是副本）
}
```

#### 生产最佳实践

- 方法集规则：`*T` 包含 `T` 和 `*T` 的全部方法；`T` 只包含 `T` 的方法
- 接口实现时注意方法接收者一致性问题，否则类型不满足接口
- 大结构体（> 64 字节）优先用指针传递
- 并发安全方面：传值天然隔离，传指针需注意竞争条件

---

## 4. 标准库深度

### 4.1 net/http

#### 高频面试题

**Q: Go HTTP 服务处理模型（Goroutine-per-connection）？**

```go
func main() {
    server := &http.Server{
        Addr:         ":8080",
        ReadTimeout:  5 * time.Second,
        WriteTimeout: 10 * time.Second,
        IdleTimeout:  120 * time.Second,
    }
    log.Fatal(server.ListenAndServe())
}
```

Go 1.22 路由增强：

```go
// Go 1.22+ 支持 pattern-based 路由
mux := http.NewServeMux()
mux.HandleFunc("GET /api/users/{id}", getUserHandler)
mux.HandleFunc("POST /api/users", createUserHandler)
mux.HandleFunc("DELETE /api/users/{id}", deleteUserHandler)
// {id} 通过 r.PathValue("id") 获取
```

**Q: HTTP 中间件模式实现？**

```go
// 中间件：函数式组合
type Middleware func(http.Handler) http.Handler

func Chain(handler http.Handler, middlewares ...Middleware) http.Handler {
    for i := len(middlewares) - 1; i >= 0; i-- {
        handler = middlewares[i](handler)
    }
    return handler
}

// 示例中间件
func Logging(logger *log.Logger) Middleware {
    return func(next http.Handler) http.Handler {
        return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
            start := time.Now()
            next.ServeHTTP(w, r)
            logger.Printf("%s %s %v", r.Method, r.URL.Path, time.Since(start))
        })
    }
}

func Recovery(next http.Handler) http.Handler {
    return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
        defer func() {
            if err := recover(); err != nil {
                http.Error(w, http.StatusText(http.StatusInternalServerError), 500)
            }
        }()
        next.ServeHTTP(w, r)
    })
}
```

**Q: HTTP 连接池与超时配置？**

```go
// 生产级 HTTP 客户端配置
client := &http.Client{
    Timeout: 30 * time.Second, // 总超时（包含连接、请求、响应体读取）
    Transport: &http.Transport{
        MaxIdleConns:        100,              // 连接池最大空闲连接数
        MaxIdleConnsPerHost: 10,               // 每主机最大空闲连接数
        MaxConnsPerHost:     0,                // 每主机最大连接数（0 不限）
        IdleConnTimeout:     90 * time.Second, // 空闲连接超时关闭
        DisableCompression:  false,            // 启用 gzip
        ForceAttemptHTTP2:   true,             // 尝试 HTTP/2
    },
}
```

#### 生产最佳实践

- 设置 `ReadTimeout` / `WriteTimeout` / `IdleTimeout` 防止慢客户端占用
- 使用 `http.Transport` 的连接池减少 TCP 握手开销
- HTTP/2 多路复用下注意并发与 race
- Go 1.22 的路由 pattern 已足够多数服务，不必依赖第三方路由库

---

### 4.2 encoding/json

#### 高频面试题

**Q: json.Marshal/Unmarshal 的性能瓶颈与优化？**

```go
// 标准库 JSON 序列化使用反射，性能有 O(字段数) 的开销
type User struct {
    Name string `json:"name"`
    Age  int    `json:"age,omitempty"` // 零值忽略
}

// 优化方案 1: 使用 json.RawMessage 延迟解析
type Response struct {
    Code int              `json:"code"`
    Data json.RawMessage  `json:"data"` // 保留原始 bytes，延迟 Unmarshal
}

// 优化方案 2: 使用 bytes.Buffer 预分配
func marshalFast(v any) ([]byte, error) {
    buf := bytes.NewBuffer(make([]byte, 0, 1024)) // 预分配
    enc := json.NewEncoder(buf)
    enc.SetEscapeHTML(false)  // 禁用 HTML 转义，显著提升
    if err := enc.Encode(v); err != nil {
        return nil, err
    }
    return buf.Bytes(), nil
}

// 优化方案 3: 第三方库（高性能场景）
// - easyjson: 代码生成，零反射
// - ffjson: 
// - sonic (bytedance): JIT 编译，3-10x 加速
```

**Q: json.Unmarshal 如何解析未知结构？**

```go
// 方法 1: map[string]any
func parseDynamic(data []byte) (map[string]any, error) {
    var result map[string]any
    if err := json.Unmarshal(data, &result); err != nil {
        return nil, err
    }
    // 数字默认解析为 float64
    return result, nil
}

// 方法 2: json.Decoder + json.RawMessage + type switch
func decodeFlexible(r io.Reader) error {
    dec := json.NewDecoder(r)
    dec.UseNumber() // 将数字解析为 json.Number（保留精度）
    var v any
    return dec.Decode(&v)
}
```

**Q: json.Marshal/Unmarshal 中 struct tag 的忽略规则？**

```go
type Config struct {
    Name     string `json:"name,omitempty"`           // 零值忽略（空字符串、0、false）
    Password string `json:"-"`                         // 永远忽略
    Internal struct{} `json:",omitempty"`              // struct{} 零值不序列化（空 struct 神奇特性）
    Tags     []string `json:"tags,omitzero"`           // Go 1.24+：新增 omitzero
}
```

#### 生产最佳实践

- 高频序列化使用 `sonic` 或代码生成（`easyjson`）
- 不要在热点路径使用 `map[string]any` + `json.Unmarshal`——反射开销极大
- 使用 `json.Encoder` 写流式 JSON（日志、SSE），而非 `Marshal` 整个对象
- 注意 `json.RawMessage` 的正确使用：它保留了原始 JSON 字节，不会做二次格式化

---

### 4.3 reflect 与 unsafe

#### 高频面试题

**Q: reflect 包的核心实现原理？**

```go
// reflect.Value 和 reflect.Type 的底层结构（简化）
type Value struct {
    typ  *rtype      // 类型元信息
    ptr  unsafe.Pointer // 指向数据的指针
    flag uintptr     // 标志位（地址/只读/方法等）
}

type rtype struct {
    size       uintptr     // 类型大小
    ptrdata    uintptr     // 指针数据大小（GC 用）
    hash       uint32      // 类型哈希
    tflag      tflag
    align      uint8
    fieldAlign uint8
    kind       uint8
    // ...
}
```

**Q: unsafe.Pointer 的四大规则？**

```go
// 规则 1: 任意类型指针 ↔ unsafe.Pointer 可转换
var x int32 = 42
p := unsafe.Pointer(&x)

// 规则 2: uintptr ↔ unsafe.Pointer 可转换（用于指针运算）
// 注意：uintptr 不是指针，GC 不跟踪！必须在一个表达式内完成
ptr := (*int32)(unsafe.Pointer(uintptr(p) + 4))

// 规则 3: unsafe.Pointer ↔ Syscall 指针
// 用于与 C 库交互时传递内存地址

// 规则 4（后加）: 转换必须是安全的（不越界、类型对齐正确）

// 安全用法示例：高效类型转换（不拷贝内存）
func StrToBytes(s string) []byte {
    sp := (*reflect.StringHeader)(unsafe.Pointer(&s))
    bh := reflect.SliceHeader{
        Data: sp.Data,
        Len:  sp.Len,
        Cap:  sp.Len,
    }
    return *(*[]byte)(unsafe.Pointer(&bh))
}

// Go 1.17+ 有更安全的方式：unsafe.Slice
func StrToBytesSafe(s string) []byte {
    return unsafe.Slice(unsafe.StringData(s), len(s))
}

// 注意：修改返回的 []byte 会导致未定义行为（修改了 string 底层内存）
```

**Q: reflect.DeepEqual 的原理与陷阱？**

```go
// DeepEqual 递归比较两个值的每个字段
// 陷阱 1: 空 struct{} 与不为空的 struct{} 比较
var a, b struct{}
fmt.Println(reflect.DeepEqual(a, b)) // true

// 陷阱 2: 函数类型只能比较 nil
var fn1, fn2 func()
fmt.Println(reflect.DeepEqual(fn1, fn2)) // true (都是 nil)

// 陷阱 3: time.Time 的 monotonic clock 问题
t1 := time.Now()
t2 := t1.Round(0)
fmt.Println(reflect.DeepEqual(t1, t2)) // false! 因为 Round 移除了 monotonic clock 信息
// 解决方法: 使用 t.Equal() 而非 DeepEqual
fmt.Println(t1.Equal(t2)) // true
```

#### 生产最佳实践

- reflect 在生产代码中应极度谨慎使用——它破坏类型安全、影响内联、阻止逃逸优化
- `unsafe` 在应用层代码中几乎不应使用，仅限标准库或极致性能场景
- 对已知类型的字段操作永远比反射快数个数量级
- 使用 `encoding/gob`、`protobuf` 等方式替代需要反射的通用序列化

---

## 5. 框架与微服务

### 5.1 Gin / Echo / Kratos

#### 高频面试题

**Q: Gin 的路由树（Radix Tree / 压缩前缀树）内部实现？**

```go
// Gin 使用压缩前缀树（Radix Tree）存储路由

// 注册路由：
r := gin.New()
r.GET("/", handler1)
r.GET("/user", handler2)
r.GET("/user/:id", handler3)
r.GET("/user/:id/profile", handler4)

// 路由树结构（简化）：
// /
// └── user/
//     ├── :id/
//     │   └── /profile
//     └── (GET 精确匹配)

// 路由匹配时，从根节点按字符遍历，冲突时分裂节点
// 优先级: 静态路由 > 参数路由(:id) > 通配符(*path)
```

**Q: Gin/echo 中间件执行顺序？**

```go
// 洋葱模型（中间件链）
// 注册顺序: A → B → C → Handler
// 执行顺序: A_before → B_before → C_before → Handler → C_after → B_after → A_after
// 通过 c.Next() 控制

func middlewareA() gin.HandlerFunc {
    return func(c *gin.Context) {
        fmt.Println("A before")
        c.Next()              // 调用下一个中间件
        fmt.Println("A after")
    }
}

// 如果某个中间件不调用 c.Next()，后续中间件和 handler 都不会执行
// 可用于认证失败提前中止
```

**Q: Gin 与 Echo 的核心差异？**

| 维度 | Gin | Echo |
|------|-----|------|
| 路由 | Radix Tree（更快） | Radix Tree |
| 中间件 | gin.HandlerFunc | echo.MiddlewareFunc |
| 上下文 | c *gin.Context（自动 JSON/XML 渲染）| c echo.Context |
| 验证 | binding 标签 + validator | echo.Validator 接口 + go-playground/validator |
| 错误处理 | 全局 Recovery | 统一 HTTPErrorHandler |
| 性能 | 极优 | 极优 |
| 社区 | 最大 | 较大 |

**Q: Kratos（B站微服务框架）的核心分层？**

```go
// Kratos 采用整洁架构（Clean Architecture）：
// transport  →  biz (业务逻辑)  →  data (数据访问)
//      ↓            ↓                  ↓
//   HTTP/gRPC     domain entity      repo 实现

// 示例：biz 层定义接口
type UserRepo interface {
    GetUser(ctx context.Context, id int64) (*User, error)
}

// data 层实现
type userRepo struct {
    data *Data
    log  *log.Helper
}

func NewUserRepo(data *Data, logger log.Logger) UserRepo {
    return &userRepo{data: data, log: log.NewHelper(logger)}
}

// biz 层使用依赖注入
type UserUsecase struct {
    repo UserRepo
    log  *log.Helper
}

func NewUserUsecase(repo UserRepo, logger log.Logger) *UserUsecase {
    return &UserUsecase{repo: repo, log: log.NewHelper(logger)}
}
```

#### 生产最佳实践

- Gin/Echo 默认配置需调优：ReleaseMode、TrustedProxies、MaxMultipartMemory
- 定义统一的错误码 + 错误处理中间件，避免散落 `c.JSON(500, ...)`
- Kratos 适合中大型微服务项目（内置服务发现、配置中心、链路追踪）
- 日志使用结构化的 `slog`（Go 1.21+）或 `zap`，禁用框架默认日志

---

### 5.2 gRPC / Protobuf

#### 高频面试题

**Q: Protobuf 编码原理（Varint 与 TLV 结构）？**

```go
// Protobuf 使用 TLV（Tag-Length-Value）编码
// Tag = field_number << 3 | wire_type

// Wire Types:
// 0: Varint (int32, int64, uint32, uint64, bool, enum)
// 1: 64-bit (fixed64, sfixed64, double)
// 2: Length-delimited (string, bytes, embedded messages, repeated)
// 3: Start group (deprecated)
// 4: End group (deprecated)
// 5: 32-bit (fixed32, sfixed32, float)

// Varint 编码: 小端序，每个字节 MSB 表示是否还有后续字节
// 数字 300: 1010 1100 0000 0010 → 0xAC 0x02 (2字节)

// 相比 JSON/XML 的优势：
// - 二进制紧凑，无冗余{}、"":等
// - 整数使用 Varint，小数字更省空间
// - 无解析开销，直接映射为 struct
```

**Q: gRPC 四种通信模式？**

```go
// 模式 1: Unary RPC (一元)
rpc GetUser(GetUserRequest) returns (User);

// 模式 2: Server Streaming RPC (服务端流)
rpc ListUsers(ListUsersRequest) returns (stream User);

// 模式 3: Client Streaming RPC (客户端流)
rpc UploadFile(stream FileChunk) returns (UploadResponse);

// 模式 4: Bidirectional Streaming RPC (双向流)
rpc Chat(stream ChatMessage) returns (stream ChatMessage);
```

**Q: gRPC 拦截器（Interceptor）实现？**

```go
// 一元拦截器（类似 HTTP 中间件）
func loggingUnaryInterceptor(ctx context.Context, req any,
    info *grpc.UnaryServerInfo, handler grpc.UnaryHandler) (any, error) {
    log.Printf("gRPC call: %s", info.FullMethod)
    start := time.Now()
    resp, err := handler(ctx, req)
    log.Printf("%s took %v, err=%v", info.FullMethod, time.Since(start), err)
    return resp, err
}

// 流拦截器
type wrappedStream struct {
    grpc.ServerStream
}

func (w *wrappedStream) RecvMsg(m any) error {
    log.Printf("receive: %T", m)
    return w.ServerStream.RecvMsg(m)
}

// gRPC 连接管理：连接池与复用
conn, err := grpc.Dial(
    target,
    grpc.WithInsecure(),
    grpc.WithDefaultCallOptions(
        grpc.MaxCallRecvMsgSize(10*1024*1024), // 10MB
        grpc.WaitForReady(true),                // 等待连接就绪
    ),
)
```

**Q: gRPC 的 Name Resolution 与 Load Balancing？**

```go
// gRPC 内置 DNS 解析 + 客户端负载均衡
// 服务端不需要反向代理

// 方式 1: DNS 轮询（dns:/// 前缀）
conn, _ := grpc.Dial("dns:///service.example.com:8080",
    grpc.WithDefaultServiceConfig(`{"loadBalancingPolicy":"round_robin"}`))

// 方式 2: 使用 etcd/Consul 服务发现（Kratos 方案）
// resolver.Register(new(etcd.Builder))
```

#### 生产最佳实践

- **消息大小限制**：gRPC 默认 4MB，超限需调整 `MaxCallRecvMsgSize`
- **长连接保活**：设置 `KeepaliveParams` 和 `KeepaliveEnforcementPolicy` 防止连接断开
- **优雅关闭**：`GracefulStop()` 等待正在处理的请求完成后再关闭
- **错误处理**：使用标准 gRPC 错误码（`codes.NotFound`、`codes.Internal`）而非自定义
- **Protocol Buffer 版本**：使用 proto3（Go 1.21+ 使用 google.golang.org/protobuf）

---

## 6. 数据库与缓存

### 6.1 GORM / sqlx

#### 高频面试题

**Q: GORM 的 Callbacks 与 Hook 机制？**

```go
// GORM 生命周期钩子
type User struct {
    ID        uint
    CreatedAt time.Time
    UpdatedAt time.Time
}

func (u *User) BeforeCreate(tx *gorm.DB) error {
    if u.ID == 0 {
        u.ID = generateSnowflakeID()
    }
    return nil
}

func (u *User) AfterFind(tx *gorm.DB) error {
    u.Name = maskName(u.Name) // 查询后处理
    return nil
}
```

**Q: GORM 的 N+1 问题与预加载（Preload/Joins）？**

```go
type Order struct {
    ID      uint
    UserID  uint
    User    User    `gorm:"foreignKey:UserID"`
    Items   []Item  `gorm:"foreignKey:OrderID"`
}

// 错误：N+1 查询
var orders []Order
db.Find(&orders)                    // 1 次
for _, o := range orders {
    db.Model(&o).Association("User").Find(&o.User) // N 次
}

// 正确：预加载
db.Preload("User").Preload("Items").Find(&orders)

// Go 1.20+ GORM v2 支持 Joins 预加载
db.Joins("User").Joins("Items").Find(&orders)
```

**Q: sqlx 与 database/sql 的关系？**

```go
// sqlx 是对 database/sql 的扩展，非 ORM

// database/sql：手动扫描
rows, _ := db.Query("SELECT id, name FROM users WHERE id = ?", id)
for rows.Next() {
    var u User
    rows.Scan(&u.ID, &u.Name)  // 逐字段映射
}

// sqlx：自动结构体映射
rows, _ := db.Queryx("SELECT * FROM users WHERE id = ?", id)
for rows.Next() {
    var u User
    rows.StructScan(&u) // 自动按 tag 映射
}
```

#### 生产最佳实践

- GORM 适合基本 CRUD + 少量复杂查询，复杂 SQL 操作用原生 SQL 或 sqlx
- 始终设置 `db.SetMaxOpenConns`、`db.SetMaxIdleConns`、`db.SetConnMaxLifetime`
- GORM 的 `AutoMigrate` 仅用于开发，生产环境使用版本化迁移（golang-migrate / goose）
- 关注 GORM 的 `TableName()` 方法和 `-` tag 使用

---

### 6.2 连接池

#### 高频面试题

**Q: database/sql 连接池的配置参数？**

```go
// 连接池原理
type DB struct {
    connector driver.Connector
    // ...
    maxOpen        int           // 最大打开连接数（默认 0 = 无限）
    maxIdle        int           // 最大空闲连接数（默认 2）
    connMaxLifetime time.Duration // 连接最大存活时间
    connMaxIdleTime time.Duration // 空闲连接超时
    freeConn       []*driverConn // 空闲连接列表
    connRequests   map[uint64]chan connRequest // 等待连接的 goroutine
}

// 生产配置
db, _ := sql.Open("mysql", dsn)
db.SetMaxOpenConns(25)              // 根据数据库规格配置
db.SetMaxIdleConns(10)              // 通常为 maxOpen 的 30-50%
db.SetConnMaxLifetime(30 * time.Minute) // 确保 IP 变动等场景连接刷新
db.SetConnMaxIdleTime(5 * time.Minute)  // 空闲连接超时回收
```

**Q: 连接泄漏（Connection Leak）如何排查？**

```go
// 泄漏场景：查询后未关闭 rows
rows, _ := db.Query("SELECT * FROM users")
// 忘记 rows.Close() → 连接无法回池

// 正确方式：defer 关闭
rows, _ := db.Query("SELECT * FROM users")
defer rows.Close()

// 排查工具：
// 1. 通过 expvar 或 metrics 暴露 db.Stats()
fmt.Printf("Open: %d, InUse: %d, Idle: %d, WaitCount: %d\n",
    stats.OpenConnections, stats.InUse, stats.Idle, stats.WaitCount)
// 如果 InUse 持续等于 maxOpen，说明存在泄漏
```

#### 生产最佳实践

- 连接池大小不是越大越好：`maxOpen = (CPU核数 * 2) + 有效磁盘数`（经验公式）
- `SetConnMaxLifetime` 必须设置，避免连接过久被中间件（如 MySQL 的 wait_timeout）关闭
- 监控 `WaitCount > 0` 表示等待连接，可能需要增大 maxOpen
- 每个 `*sql.Rows` / `*sql.Stmt` 必须 Close

---

### 6.3 Redis 客户端 go-redis

#### 高频面试题

**Q: go-redis 的连接池设计与流水线（Pipeline）？**

```go
// 连接池配置
rdb := redis.NewClient(&redis.Options{
    Addr:         "localhost:6379",
    Password:     "",
    DB:           0,
    PoolSize:     10,                    // 连接池大小（默认 10 * runtime.GOMAXPROCS）
    MinIdleConns: 3,                     // 最小空闲连接
    MaxIdleConns: 5,
    ConnMaxLifetime: 30 * time.Minute,
    ConnMaxIdleTime: 5 * time.Minute,
    PoolTimeout:  4 * time.Second,       // 获取连接超时
})

// Pipeline：批量命令，减少 RTT
pipe := rdb.Pipeline()
incr := pipe.Incr(ctx, "counter")
pipe.Expire(ctx, "counter", time.Hour)
_, err := pipe.Exec(ctx)  // 一次性发送所有命令
fmt.Println(incr.Val())    // 结果在 Exec 后可用
```

**Q: Redis Cluster 模式下的节点发现与自动重连？**

```go
// go-redis 自动处理 Cluster 的 MOVED/ASK 重定向
rdb := redis.NewClusterClient(&redis.ClusterOptions{
    Addrs: []string{":7000", ":7001", ":7002"},
})

// 分布式锁示例
func acquireLock(ctx context.Context, rdb *redis.Client, key string, ttl time.Duration) (bool, error) {
    ok, err := rdb.SetNX(ctx, key, "locked", ttl).Result()
    if err != nil {
        return false, err
    }
    return ok, nil
}

// Lua 脚本：原子操作（锁释放 + 安全删除）
const releaseScript = `
if redis.call("GET", KEYS[1]) == ARGV[1] then
    return redis.call("DEL", KEYS[1])
end
return 0
`
```

#### 生产最佳实践

- Redis Pipeline / Cluster Pipeline 可减少 10-100 倍 RTT
- 使用 `go-redis` 的 `Hook` 机制实现日志、慢查询、链路追踪
- 分布式锁用 Redlock 或 etcd 实现，注意锁的自动续期
- 避免 `KEYS *` 在生产环境使用（O(N) 阻塞），改用 `SCAN`
- 连接池大小：Redis 单机通常 50-100，Cluster 模式更少

---

## 7. 性能调优

### 7.1 pprof 使用

#### 高频面试题

**Q: 如何用 pprof 定位 CPU 热点？**

```go
import _ "net/http/pprof" // 通过 /debug/pprof/ 暴露

func main() {
    go func() {
        log.Println(http.ListenAndServe("localhost:6060", nil))
    }()
    // 业务代码...
}

// 采集分析命令：
// go tool pprof -http=:8080 http://localhost:6060/debug/pprof/profile?seconds=30
// 浏览器打开 Flame Graph（火焰图）定位最宽的栈帧
```

**Q: 如何用 pprof 定位内存泄漏？**

```go
// 1. heap profile（当前分配）
// go tool pprof -http=:8080 http://localhost:6060/debug/pprof/heap

// 2. 对比（取两次快照的 diff）
// curl -o heap1.pprof http://localhost:6060/debug/pprof/heap
// 等待一段时间
// curl -o heap2.pprof http://localhost:6060/debug/pprof/heap
// go tool pprof -base heap1.pprof heap2.pprof

// 3. 用 alloc_objects 和 inuse_objects 区分问题
// alloc_objects: 累计分配次数 → 谁在大量分配
// inuse_objects: 当前存活对象 → 谁在泄漏

// pprof 的 Type 说明：
// alloc_objects  — 累计分配的对象数
// alloc_space    — 累计分配的内存大小
// inuse_objects  — 当前仍在使用的对象数
// inuse_space    — 当前仍在使用的内存大小

// goroutine profile
// http://localhost:6060/debug/pprof/goroutine?debug=2
// 查看所有 goroutine 栈，定位泄漏的 goroutine
```

**Q: pprof 的 sampler 原理（采样频率与精度）？**

```go
// CPU profiling: 默认 100 Hz（每 10ms 采样一次）
// 通过 SIGPROF 信号触发
// 运行时检查当前 goroutine 的 PC 和栈信息并记录

// Heap profiling: 每 512KB 分配采样一次
// 通过 runtime.MemProfileRate 控制（默认 512*1024）
// 设 runtime.MemProfileRate = 1 时采样所有分配（性能开销大）

// Block profiling: 默认关闭，通过 runtime.SetBlockProfileRate 开启
// 记录 goroutine 在 channel/mutex/sleep 上的阻塞时间

// Mutex profiling: 默认关闭，通过 runtime.SetMutexProfileFraction 开启
// 记录竞争锁的 goroutine
```

#### 生产最佳实践

- **pprof 安全**：生产环境不要直接暴露 `/debug/pprof/`，通过内部端口或认证限制
- **持续 profiling**：使用 `pyroscope`、`parca` 或 Google Cloud Profiler 做持续性能采样
- **基准线**：每次优化前记录 profile，优化后对比
- **火焰图阅读**：横轴越宽的函数消耗越多 CPU/内存，优先优化
- **不要优化未测量的代码**：profile 数据为主观猜测的替代

---

### 7.2 Race Detector

#### 高频面试题

**Q: Go Race Detector 的原理？**

```go
// Race Detector 基于 C/C++ ThreadSanitizer (TSan)
// 编译时插入代码 + 运行时检测

// 使用方式：
// go test -race ./...
// go build -race ./

// 检测原理：
// 1. 编译器在每次内存访问时插入 4 字节的 "影子内存" (shadow memory)
// 2. 影子内存记录每个位置的访问历史和 goroutine ID
// 3. 当检测到同一地址、至少一次写、无 happens-before 关系 → 报告 race

// 性能影响：
// - CPU: 5-10 倍
// - 内存: 5-10 倍
// 因此仅测试和 CI 中使用，生产环境不用
```

**Q: 典型的 race 模式与修复？**

```go
// 模式 1: 并发写 map（map 非线程安全，并发写直接 panic）
cache := make(map[string]int)
go func() { cache["a"] = 1 }()
go func() { cache["b"] = 2 }() // fatal error: concurrent map writes

// 修复: sync.Map 或 sync.RWMutex

// 模式 2: 闭包捕获循环变量
for i := 0; i < 10; i++ {
    go func() { fmt.Println(i) }() // i 在 goroutine 执行时已变化
}
// 修复: go func(i int) { fmt.Println(i) }(i)

// 模式 3: 未加锁的计数器
var counter int
wg.Add(2)
go func() { counter++; wg.Done() }()
go func() { counter++; wg.Done() }()
// 修复: atomic.AddInt64 或 sync.Mutex

// 模式 4: slice 并发 append（可能导致底层数组被覆盖）
// 修复: 加锁或每个 goroutine 使用独立切片后合并
```

#### 生产最佳实践

- CI 流水线中 `go test -race ./...` 必须通过
- Race Detector 检测到 race 后，即使业务逻辑正确也要修复（消除 undefined behavior）
- 注意 `-race` 有性能开销，但远低于排查数据竞争的时间成本
- 简单规则：共享变量通过 channel 传递，而非共享内存

---

### 7.3 Benchmark 与逃逸分析

#### 高频面试题

**Q: 正确编写 Go Benchmark 的注意事项？**

```go
// 基本结构
func BenchmarkFoo(b *testing.B) {
    // 初始化（不计入计时器）
    b.StopTimer()
    data := expensiveInit()
    b.StartTimer()

    // b.N 由框架自动调整
    for i := 0; i < b.N; i++ {
        Foo(data)
    }
}

// 防止编译器消除无副作用的调用
var result []byte

func BenchmarkMarshal(b *testing.B) {
    u := User{Name: "test", Age: 18}
    var r []byte
    for i := 0; i < b.N; i++ {
        r, _ = json.Marshal(u)
    }
    result = r // 赋值给包级变量阻止优化消除
}

// 子 benchmark
func BenchmarkStringConcat(b *testing.B) {
    b.Run("plus", func(b *testing.B) {
        for i := 0; i < b.N; i++ {
            s := ""
            s += "hello"
            s += "world"
        }
    })
    b.Run("builder", func(b *testing.B) {
        for i := 0; i < b.N; i++ {
            var sb strings.Builder
            sb.WriteString("hello")
            sb.WriteString("world")
        }
    })
}

// 运行测试：
// go test -bench=. -benchmem -count=5 -benchtime=5s
```

**Q: 逃逸分析在生产性能排查中的实际应用？**

```go
// 场景：高并发 HTTP handler 中的额外堆分配
func handleUser(c *gin.Context) {
    name := c.Query("name")
    // 以下写法触发 User 结构体逃逸
    c.JSON(200, &User{Name: name}) // User 指针逃逸 → 堆分配
    // 优选用值传递（如果 User 不大）
    c.JSON(200, User{Name: name})  // 可能栈分配
}

// 场景：接口参数导致的隐式逃逸
func writeTo(w io.Writer, data []byte) {
    w.Write(data) // w 是 interface，data 可能因 interface 装箱逃逸
}

// 排查步骤：
// 1. go build -gcflags="-m" 查看哪些变量逃逸
// 2. 对热点路径，尝试减少指针传递
// 3. 使用 sync.Pool 缓存频繁分配的对象
// 4. pprof 确认 alloc_space 是否有改善
```

#### 生产最佳实践

- benchmark 必须设置 `-benchmem` 观察每次操作的分配次数（最关键指标之一）
- 禁用编译器优化干扰：`go test -bench=. -gcflags="-N -l"` 但结果仅供参考
- 每次 benchmark 至少运行 5 次取均值（`-count=5`），排除 GC/调度干扰
- pprof 定位到热点后，用 benchmark + 逃逸分析确认优化效果
- `testing.B.Cleanup()` 注册清理函数

---

## 8. 工程实践

### 8.1 项目布局

#### 高频面试题

**Q: 标准的 Go 项目布局（Standard Go Project Layout）？**

```
/go-backend-service/
├── cmd/
│   └── server/
│       └── main.go           # 入口：解析配置、初始化依赖、启动服务
├── internal/
│   ├── biz/                  # 业务逻辑层 (domain logic)
│   │   ├── user.go           # User 实体 + UseCase
│   │   └── user_test.go
│   ├── data/                 # 数据访问层
│   │   ├── user_repo.go
│   │   └── mysql.go
│   ├── service/              # 传输层（proto 定义接口的实现）
│   │   └── user_service.go
│   └── pkg/                  # 内部共享包
│       ├── middleware/
│       └── errors/
├── api/                      # API 定义
│   └── proto/
│       └── v1/
│           └── user.proto
├── configs/                  # 配置文件
│   └── config.yaml
├── pkg/                      # 可对外发布的外部包
│   └── auth/
├── scripts/
│   └── migrate.sh
├── go.mod
├── go.sum
├── Makefile
└── Dockerfile
```

**关键原则：**
- `internal` 目录下的包不被外部导入（Go 编译器强制）
- `cmd` 只做启动组装，不包含业务逻辑
- 业务逻辑放在 `internal/biz`（UseCase 层），不依赖具体框架
- 依赖反转：`biz` 定义接口，`data` 实现接口

#### 生产最佳实践

- 避免过早抽象，团队规模 < 10 人时不需要严格分层架构
- 保持 `internal/pkg` 精简：只提取被 3 个以上模块使用的公共代码
- 使用 `go.uber.org/fx` 或 `wire` 做依赖注入，手动组装在大项目里不可维护
- 配置管理：`viper` 读取 + 版本化配置文件 + 环境变量覆盖

---

### 8.2 依赖注入 Wire

#### 高频面试题

**Q: Wire 的原理（代码生成 vs 运行时反射）？**

```go
// Wire 是编译期依赖注入工具，通过代码生成而非反射

// wire.go — 声明依赖关系（仅用于 wire 生成）
// +build wireinject

func InitializeServer() (*Server, func(), error) {
    wire.Build(
        NewConfig,
        NewLogger,
        NewDatabase,
        NewUserRepo,
        NewUserService,
        NewServer,
    )
    return nil, nil, nil
}

// wire_gen.go — wire 自动生成的代码（无需手写）
func InitializeServer() (*Server, func(), error) {
    config := NewConfig()
    logger := NewLogger(config)
    db := NewDatabase(config)
    userRepo := NewUserRepo(db, logger)
    userService := NewUserService(userRepo, logger)
    server := NewServer(config, userService)
    return server, func() {
        // cleanup 函数
        db.Close()
    }, nil
}

// 生成命令：wire ./internal/cmd/server/
```

**优势：**
- 编译期检查依赖缺失或循环依赖
- 无反射开销，不影响运行时性能
- 生成的代码清晰可读，可调试

#### 生产最佳实践

- Wire 不适合小型项目，手动组装更简单
- Wire 的 `ProviderSet` 用于组织相关的 provider 集合
- `wire.Bind` 用于接口绑定：`wire.Bind(new(UserRepo), new(*userRepoImpl))`
- 每个 provider 的 `cleanup` 函数必须正确处理（关闭连接、释放资源）
- Wire 调试：`wire check` 检查依赖，`wire diff` 查看与生成的差异

---

### 8.3 错误处理最佳实践

#### 高频面试题

**Q: Go 1.13+ 的错误处理（errors.Is / errors.As）？**

```go
// Go 1.13 引入 error wrapping
type UserNotFoundError struct {
    UserID int64
}

func (e *UserNotFoundError) Error() string {
    return fmt.Sprintf("user %d not found", e.UserID)
}

// 定义 Sentinel Error
var ErrNotFound = errors.New("not found")
var ErrPermissionDenied = errors.New("permission denied")

// wrapping（使用 %w）
func GetUser(ctx context.Context, id int64) (*User, error) {
    user, err := repo.FindByID(ctx, id)
    if err != nil {
        return nil, fmt.Errorf("get user %d: %w", id, ErrNotFound)
    }
    return user, nil
}

// 解包判断
func main() {
    _, err := GetUser(ctx, 42)
    if errors.Is(err, ErrNotFound) {
        // handle not found
    }

    // errors.As 用于包装的错误类型
    var notFound *UserNotFoundError
    if errors.As(err, &notFound) {
        fmt.Printf("User %d not found\n", notFound.UserID)
    }
}
```

**Q: Go 的错误检查与 PHP 异常处理对比？**

```go
// PHP 用 try-catch 处理异常 (Exception)
// Go 用多返回值 + if err != nil 检查

// 问题：Go 的错误处理显得冗长
file, err := os.Open("file.txt")
if err != nil {
    return err
}
data, err := io.ReadAll(file)
if err != nil {
    file.Close()
    return err
}

// 改进方案 1: 使用 validation 函数或 slicer 包装
// 改进方案 2: 使用 golang.org/x/sync/errgroup 做并发错误管理
// 改进方案 3: 使用内部 error 分类 + 统一错误处理中间件

// 统一错误码
type ErrorCode struct {
    HTTPStatus int
    Code       string
    Message    string
}

var (
    ErrInvalidParams   = &ErrorCode{400, "INVALID_PARAMS", "请求参数错误"}
    ErrNotFound        = &ErrorCode{404, "NOT_FOUND", "资源不存在"}
    ErrInternal        = &ErrorCode{500, "INTERNAL_ERROR", "服务器内部错误"}
)
```

#### 生产最佳实践

- 每个函数的错误应被处理：记录日志、返回包装错误或优雅降级
- 不要滥用 `errors.Wrap`——只在跨层传递时包装，本层内部使用原始错误
- 使用结构化的 `slog` 记录错误（携带 trace id、错误码、stack 等字段）
- 定义错误码而非裸字符串判断
- 不要使用 panic 替代常规错误处理

---

### 8.4 测试与 Mock

#### 高频面试题

**Q: Go 的 table-driven test 模式？**

```go
func TestAdd(t *testing.T) {
    tests := []struct {
        name string
        a, b int
        want int
    }{
        {"positive", 1, 2, 3},
        {"negative", -1, -2, -3},
        {"zero", 0, 0, 0},
        {"large", 1000000, 2000000, 3000000},
    }

    for _, tt := range tests {
        t.Run(tt.name, func(t *testing.T) {
            got := Add(tt.a, tt.b)
            assert.Equal(t, tt.want, got)
        })
    }
}
```

**Q: 如何用 mock 进行接口测试？**

```go
// 方案 1: 官方 mocking（手动实现接口）
type UserRepo interface {
    GetUser(ctx context.Context, id int64) (*User, error)
}

type mockUserRepo struct {
    mock.Mock
}

func (m *mockUserRepo) GetUser(ctx context.Context, id int64) (*User, error) {
    args := m.Called(ctx, id)
    return args.Get(0).(*User), args.Error(1)
}

func TestGetUser(t *testing.T) {
    repo := new(mockUserRepo)
    repo.On("GetUser", mock.Anything, int64(1)).Return(&User{Name: "Alice"}, nil)

    svc := NewUserService(repo)
    user, err := svc.GetUser(ctx, 1)
    assert.NoError(t, err)
    assert.Equal(t, "Alice", user.Name)
    repo.AssertExpectations(t)
}

// 方案 2: 使用 testify/suite 组织测试套件
type UserServiceSuite struct {
    suite.Suite
    repo *mockUserRepo
    svc  *UserService
}

func (s *UserServiceSuite) SetupTest() {
    s.repo = new(mockUserRepo)
    s.svc = NewUserService(s.repo)
}

func (s *UserServiceSuite) TestGetUser() {
    s.repo.On("GetUser", mock.Anything, int64(1)).Return(&User{Name: "Alice"}, nil)
    user, err := s.svc.GetUser(context.Background(), 1)
    s.NoError(err)
    s.Equal("Alice", user.Name)
}

func TestUserService(t *testing.T) {
    suite.Run(t, new(UserServiceSuite))
}
```

**Q: 测试夹具（test fixtures）的管理？**

```go
// 方案 1: testdata 目录
// testdata/
// ├── fixtures/
// │   └── user.json
// └── golden/
//     └── expected_response.json

// 方案 2: golden file 测试（快照测试）
func TestUserHandler(t *testing.T) {
    handler := NewUserHandler()
    req := httptest.NewRequest("GET", "/api/user/1", nil)
    rec := httptest.NewRecorder()
    handler.ServeHTTP(rec, req)

    got := rec.Body.Bytes()
    golden := filepath.Join("testdata", "golden", "user_response.json")
    if *update {
        os.WriteFile(golden, got, 0644)
    }
    expected, _ := os.ReadFile(golden)
    assert.JSONEq(t, string(expected), string(got))
}
```

**Q: Fuzzing 测试（Go 1.18+）？**

```go
func FuzzParsePhone(f *testing.F) {
    // seed corpus（初始输入）
    f.Add("13800138000")
    f.Add("010-12345678")

    f.Fuzz(func(t *testing.T, input string) {
        phone, err := ParsePhone(input)
        // fuzzer 会生成各种随机输入，确保不 panic
        if err == nil {
            // 如果解析成功，验证逆向操作
            assert.Equal(t, input, phone.String())
        }
    })
}
```

#### 生产最佳实践

- 测试金字塔：70% 单元测试 + 20% 集成测试 + 10% E2E 测试
- 使用 `testcontainers-go` 管理集成测试所需的数据库/Redis 容器
- 不要在测试中使用 `time.Sleep` 等待异步操作——使用 `assert.Eventually`
- 对 HTTP handler 测试使用 `httptest.NewServer` + `httptest.NewRecorder`
- 持续集成中 `go test -race -count=1 ./...` 必跑

---

## 9. 消息队列集成

### 9.1 Kafka Go 客户端

#### 高频面试题

**Q: Sarama（主流 Kafka Go 客户端）生产者和消费者配置？**

```go
import "github.com/IBM/sarama"

// 生产者配置
func newProducer(brokers []string) (sarama.SyncProducer, error) {
    config := sarama.NewConfig()
    config.Producer.RequiredAcks = sarama.WaitForAll       // 等待 ISR 全部确认
    config.Producer.Retry.Max = 5                          // 重试次数
    config.Producer.Return.Successes = true                // 同步模式必须
    config.Producer.Compression = sarama.CompressionSnappy // 压缩
    config.Producer.Flush.Frequency = 500 * time.Millisecond // 批量发送
    config.Producer.Flush.Bytes = 1024 * 1024              // 1MB 批次

    return sarama.NewSyncProducer(brokers, config)
}

// AsyncProducer（高性能异步模式）
func newAsyncProducer(brokers []string) sarama.AsyncProducer {
    config := sarama.NewConfig()
    config.Producer.RequiredAcks = sarama.WaitForLocal
    config.Producer.Return.Successes = true
    config.Producer.Return.Errors = true

    producer, err := sarama.NewAsyncProducer(brokers, config)

    // 异步处理成功/失败回调
    go func() {
        for {
            select {
            case msg := <-producer.Successes():
                log.Printf("msg %s sent to partition %d offset %d",
                    msg.Value, msg.Partition, msg.Offset)
            case err := <-producer.Errors():
                log.Printf("failed to send msg: %v", err)
            }
        }
    }()
    return producer
}
```

**Q: Kafka 消费组（Consumer Group）与位移提交？**

```go
func newConsumerGroup(brokers []string, groupID string) {
    config := sarama.NewConfig()
    config.Consumer.Group.Rebalance.Strategy = sarama.BalanceStrategySticky
    config.Consumer.Offsets.Initial = sarama.OffsetOldest // 从最早开始消费
    config.Consumer.Offsets.AutoCommit.Enable = false     // 手动提交
    config.Consumer.Offsets.AutoCommit.Interval = time.Second

    client, _ := sarama.NewConsumerGroup(brokers, groupID, config)

    // 消费循环
    for {
        err := client.Consume(ctx, []string{"my-topic"}, &handler{})
        if err != nil {
            log.Printf("consume error: %v", err)
        }
    }
}

type handler struct{}

func (h *handler) Setup(s sarama.ConsumerGroupSession) error {
    log.Printf("rebalance: assigned partitions %v", s.Claims())
    return nil
}

func (h *handler) Cleanup(s sarama.ConsumerGroupSession) error {
    log.Println("rebalance: revoking partitions")
    return nil
}

func (h *handler) ConsumeClaim(s sarama.ConsumerGroupSession, claim sarama.ConsumerGroupClaim) error {
    for msg := range claim.Messages() {
        processMessage(msg)
        s.MarkMessage(msg, "") // 标记消费
    }
    return nil // 返回错误会触发 rebalance
}
```

#### 生产最佳实践

- Kafka 生产确认级别：`WaitForAll`（最高可靠性）vs `WaitForLocal`（高吞吐）
- 位移提交：手动提交 + 业务处理完成后提交，确保 at-least-once 语义
- 消费组 rebalance 时调用 `Setup`/`Cleanup`，需在此过程中重置状态
- Sarama 是纯 Go 实现，无需安装 librdkafka，但 `confluent-kafka-go` 在吞吐上更优（C 绑定）
- 合理设置分区数：消费者并发度 ≤ 分区数

---

### 9.2 RabbitMQ Go 客户端

#### 高频面试题

**Q: amqp（RabbitMQ Go 客户端）的 Connection / Channel 模型？**

```go
import amqp "github.com/rabbitmq/amqp091-go"

// RabbitMQ 的连接模型（AMQP 0-9-1）
// Connection → 多个 Channel（轻量级连接复用）
// Channel → 操作的基础（publish/consume/bind）

type RabbitMQ struct {
    conn    *amqp.Connection
    channel *amqp.Channel
    done    chan struct{}
}

func NewRabbitMQ(url string) (*RabbitMQ, error) {
    conn, err := amqp.DialConfig(url, amqp.Config{
        Heartbeat: 10 * time.Second,
        Locale:    "en_US",
    })
    if err != nil {
        return nil, err
    }

    ch, err := conn.Channel()
    if err != nil {
        return nil, err
    }

    // 设置 QoS（prefetch）
    ch.Qos(
        10,     // prefetch count（未确认最大消息数）
        0,      // prefetch size
        false,  // global
    )

    rmq := &RabbitMQ{conn: conn, channel: ch, done: make(chan struct{})}

    // 自动重连
    go rmq.handleReconnect()

    return rmq, nil
}

// 生产消息
func (r *RabbitMQ) Publish(ctx context.Context, exchange, routingKey string, body []byte) error {
    return r.channel.PublishWithContext(ctx,
        exchange,   // exchange
        routingKey, // routing key
        true,       // mandatory
        false,      // immediate
        amqp.Publishing{
            ContentType:  "application/json",
            DeliveryMode: amqp.Persistent, // 持久化
            Body:         body,
            Timestamp:    time.Now(),
        },
    )
}
```

**Q: 消息的确认、重试与死信队列？**

```go
// 消费者 + 手动确认
func (r *RabbitMQ) Consume(ctx context.Context) (<-chan amqp.Delivery, error) {
    // 声明死信交换机和队列
    dlx := "dlx.exchange"
    dlq := "dlq.queue"

    r.channel.ExchangeDeclare(dlx, "direct", true, false, false, false, nil)
    r.channel.QueueDeclare(dlq, true, false, false, false, nil)
    r.channel.QueueBind(dlq, "dlx.key", dlx, false, nil)

    // 声明主队列并向 DLX 发送死信
    r.channel.QueueDeclare("task.queue", true, false, false, false, amqp.Table{
        "x-dead-letter-exchange":    dlx,
        "x-dead-letter-routing-key": "dlx.key",
        "x-message-ttl":             int32(60000), // 消息 TTL 60s
    })

    msgs, err := r.channel.ConsumeWithContext(ctx,
        "task.queue",
        "consumer.tag",
        false, // auto-ack = false（手动确认）
        false,
        false,
        false,
        nil,
    )

    for msg := range msgs {
        err := processMessage(msg.Body)
        if err != nil {
            // 重试逻辑：重试次数通过 header 记录
            retryCount := getRetryCount(msg.Headers)
            if retryCount < 3 {
                msg.Nack(false, false) // 不 requeue，直接发死信
            } else {
                msg.Nack(false, false) // 超过重试次数，发死信
            }
            continue
        }
        msg.Ack(false) // 确认
    }

    return msgs, nil
}
```

#### 生产最佳实践

- **Connection 与 Channel**：Connection 是 TCP 连接，Channel 是轻量级多路复用——一个 Connection 用多个 Channel
- **自动重连**：RabbitMQ 连接在高可用模式下可能中断，必须实现自动重连逻辑
- **Prefetch**：合理设置 QoS（prefetch count），防止消费者积压大量消息
- **持久化**：`DeliveryMode: Persistent` + 队列 `durable: true` + 交换机 `durable: true`
- **死信队列**：必须配置，处理消费失败的消息
- **幂等性**：消息消费务必幂等（at-least-once 语义下消息可能重复）

---

## 10. Go vs PHP 高阶对比

### 10.1 并发模型对比

| 维度 | Go | PHP (传统/FPM) |
|------|-----|----------------|
| 并发单元 | Goroutine (2KB 栈) | 进程/线程（通常数十 MB）|
| 调度 | Go 运行时 M:N 调度 | OS 调度 / FPM 进程池 |
| 每请求资源 | 4-10 KB 内存 | 10-50 MB 内存（FPM）|
| 并发上限 | 百万级 goroutine | 千级连接 |
| 通信 | Channel（CSP） | 共享内存 + 锁 |
| 适合场景 | IO 密集型 + CPU 密集型 | 同步 IO（传统 Web）|

**面试高频题 Q: PHP-FPM 的瓶颈是什么？Go 如何解决？**

PHP-FPM 的进程模型决定了每个连接需要一个 OS 进程，内存占用高（基础 15MB+）。Go 用 goroutine（2KB 栈）替代进程，一个 8GB 机器可轻松处理 50 万并发连接。PHP 8.x 的 JIT 改善了 CPU 密集型场景，但内存模型和并发模型的限制是架构性的。

### 10.2 内存管理对比

| 维度 | Go | PHP |
|------|-----|-----|
| GC 算法 | 并发三色标记-清除（低延迟 < 1ms STW）| 引用计数 + 写时复制（PHP 7+）|
| 内存模型 | 栈 + 堆，显式逃逸分析 | zval 结构体，隐式引用计数 |
| 性能特点 | 低延迟 GC，内存稳定 | 引用计数及时释放，但循环引用需处理 |
| 占用特性 | 内存占用可预测 | 每个请求释放，但峰值高 |

**关键洞察：** PHP 的引用计数释放及时，但循环引用导致泄漏。Go 的 GC 虽有小停顿，但内存布局更可控（栈分配、值类型），可处理更高并发下的内存压力。

### 10.3 类型系统对比

| 维度 | Go | PHP |
|------|-----|-----|
| 类型系统 | 静态类型 + 类型推断 | 动态类型 → 渐进类型（PHP 8+）|
| 泛型 | Go 1.18+ 支持泛型 | PHP 无泛型（可用 PHPDoc）|
| 接口 | 隐式实现（Duck Typing）| 显式 implements（PHP 8 支持 Union Types）|
| 零值 | 类型零值初始化 | null / undefined |
| 错误处理 | 多返回值 + error | try-catch Exception |

**面试 Q: 从 PHP 转型到 Go，最大的思维转变是什么？**

1. **类型思维**：PHP 中类型模糊、灵活多变，Go 要求精确类型设计 —— 转换时有阵痛期
2. **错误是值**：Go 的 `error` 是普通返回值，不是异常，需主动检查而非抛到上层
3. **并发是工具**：PHP 中并发通常是额外依赖（Swoole、pthreads），Go 中并发是语言一等公民
4. **组合而非继承**：Go 用嵌入（embedding）和接口组合，与 PHP 的类继承体系完全不同
5. **显式错误处理**：Go 鼓励检查每个错误，PHP 更容易用 try-catch 忽略

### 10.4 性能场景对比

**Go 显著优势的场景：**
- **高并发微服务**：单机 10 万+ 连接，如 API Gateway、消息推送
- **IO 密集型中间件**：代理、网关、缓存代理
- **流处理**：日志流水线、CDC（Change Data Capture）
- **CLI 工具**：跨平台二进制分发（对比 PHP 依赖 php 运行时）
- **实时通信**：WebSocket、gRPC 流

**PHP 仍有优势的场景：**
- **传统 CMS/CRM**：WordPress、Shopware 等成熟生态
- **快速原型**：开发迭代速度（零构建、热重载）
- **Web UI 渲染**：模板引擎天然集成（Blade、Twig）
- **低并发 Admin 系统**：开发效率优先时

### 10.5 架构设计理念对比

```go
// Go 架构特点：分层明确、显式错误、编译安全
type UserService struct {
    repo   UserRepo
    logger *slog.Logger
}

func (s *UserService) GetUser(ctx context.Context, id int64) (*User, error) {
    user, err := s.repo.FindByID(ctx, id)
    if err != nil {
        if errors.Is(err, ErrNotFound) {
            return nil, fmt.Errorf("user service: %w", ErrNotFound)
        }
        s.logger.ErrorContext(ctx, "failed to get user",
            "id", id, "error", err)
        return nil, fmt.Errorf("user service: get user: %w", ErrInternal)
    }
    return user, nil
}
```

```php
// PHP 架构特点：动态灵活、MVC 惯用
class UserService {
    public function getUser(int $id): ?User {
        try {
            $user = $this->repo->findById($id);
            return $user;
        } catch (UserNotFoundException $e) {
            return null;
        } catch (Throwable $e) {
            $this->logger->error('get user failed', ['id' => $id]);
            throw $e;
        }
    }
}
```

**转型建议路线图：**
1. **第 1-2 月**：掌握基础语法、HTTP 服务、简单并发（goroutine + channel）
2. **第 3-4 月**：理解 GMP、GC、逃逸分析，编写可用生产代码
3. **第 5-6 月**：深入学习接口设计、依赖注入、单元测试、pprof 调优
4. **第 7-12 月**：掌握分布式模式（gRPC、消息队列、服务发现、链路追踪）

---

## 附录：常见面试速查表

### 高频八股文速查

| 问题 | 一句话答案 |
|------|-----------|
| GMP 是什么 | Goroutine + OS 线程(M) + 逻辑处理器(P)，M:N 调度 |
| GC 触发条件 | 堆增长 100%（GOGC）、2 分钟未触发、手动调用 |
| channel 关闭规则 | 发送方关闭，向已关闭 channel 发送 panic |
| map 并发安全吗 | 不，并发读写 panic，用 sync.Map 或 RWMutex |
| defer 执行顺序 | LIFO（后进先出），return 前执行 |
| make vs new | make 用于 slice/map/channel 返回初始化值；new 返回指针 |
| string 可修改吗 | 不可变，修改会分配新的 string |
| panic 恢复规则 | recover 仅在 defer 中有效 |
| interface{} 底层 | iface（有方法）或 eface（空接口），包含类型+值指针 |
| select 随机选择 | 多个 case 就绪时随机公平选择 |

### pprof 常用命令速查

```bash
# CPU：采集 30s
go tool pprof -http=:8080 http://localhost:6060/debug/pprof/profile?seconds=30

# 内存：当前堆
go tool pprof -http=:8080 http://localhost:6060/debug/pprof/heap

# goroutine 栈
go tool pprof -http=:8080 http://localhost:6060/debug/pprof/goroutine

# 阻塞分析
go tool pprof -http=:8080 http://localhost:6060/debug/pprof/block

# 两堆 diff
go tool pprof -base heap1.pprof heap2.pprof
```

### Go 版本特性演进（关键里程碑）

| 版本 | 关键特性 | 面试注意 |
|------|----------|----------|
| 1.5 | 首个并发 GC、首个纯 Go 实现 | GC 延迟大幅降低 |
| 1.8 | 混合写屏障、插件支持 | STW < 1ms |
| 1.11 | Go Modules（`go mod`）| 替代 GOPATH |
| 1.13 | Error Wrapping（`%w`）| `errors.Is` / `errors.As` |
| 1.14 | 重叠 goroutine 抢占 | 解决 goroutine 死循环不释放 P 问题 |
| 1.16 | `io/fs` 接口 | 文件系统抽象 |
| 1.18 | 泛型 (Generics)、Fuzzing | `[T any]` 类型参数 |
| 1.19 | 软内存限制 `GOMEMLIMIT` | 容器化部署优化 |
| 1.20 | 多错误合并 (`errors.Join`)| 多个 goroutine 错误合并 |
| 1.21 | `slog` 结构化日志、`maps`/`slices` 包 | 标准库日志升级 |
| 1.22 | HTTP 路由增强（pattern）、`for range` 整数 | `mux.HandleFunc("GET /path/{id}", h)` |
| 1.23 | 迭代器（iter）、`unique` 包 | 内置 range-over-func 支持 |

---

> **本文档持续更新**。建议读者结合 `go doc` 命令、Go 官方 blog（go.dev/blog）以及标准库源码进行扩展阅读。
> 面试准备的最高效方法：对每道面试题，用 1-2 行回答核心要点 + 写出可运行的代码示例。
