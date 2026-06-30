# Hyperf 高级面试知识架构

> 目标受众：使用 Hyperf 构建高并发 PHP 微服务的高级开发 / 架构师
> 本文档聚焦 Hyperf 框架核心：注解驱动、编译期依赖注入、AOP 切面、生命周期、协程安全与生产实践。
>
> **关联文档：**
> - 运行底座（进程模型、协程、Channel/连接池）见 [Swoole 协程通信引擎](./16-swoole-advanced.md)
> - 对照框架（PHP-FPM、服务容器、门面、依赖注入）见 [Laravel 高级面试知识架构](./14-laravel-advanced.md)
> - PHP 语言与运行原理见 [PHP 高级面试知识架构](./01-php-advanced.md)

---

## 目录

1. [框架核心](#1-框架核心)
2. [Hyperf 生命周期](#2-hyperf-生命周期)
3. [AOP 切面深入](#3-aop-切面深入)
4. [协程安全](#4-协程安全)
5. [生产实践要点](#5-生产实践要点)

---

## 1. 框架核心

Hyperf 是基于 Swoole 协程的高性能 PHP 框架，主打**注解 + 依赖注入 + AOP + 协程组件**，定位类似「PHP 版 Spring」。

```
Hyperf 核心架构
┌─────────────────────────────────────────────────────────┐
│  注解驱动 (Annotation / PHP 8 Attributes)                  │
│   #[Controller] #[Inject] #[Aspect] #[Listener] #[Crontab]│
├─────────────────────────────────────────────────────────┤
│  依赖注入容器 (hyperf/di)                                   │
│   - 编译期扫描注解 → 生成代理类 (runtime/container)         │
│   - 启动时一次性构建, 协程间复用                            │
├─────────────────────────────────────────────────────────┤
│  AOP 切面 (基于 DI 代理类织入)                              │
├─────────────────────────────────────────────────────────┤
│  协程组件池 (连接池/Guzzle/Redis/DB 全协程化)               │
├─────────────────────────────────────────────────────────┤
│  事件机制 / 注解路由 / 配置中心 / 服务治理                  │
└─────────────────────────────────────────────────────────┘
```

**Hyperf 关键特性：**

| 特性 | 说明 | 对应组件 |
|------|------|---------|
| 注解路由 | `#[GetMapping]` 编译期收集 | hyperf/http-server |
| 依赖注入 | 编译期生成代理类，零反射开销 | hyperf/di |
| AOP | 切面织入，无侵入增强 | hyperf/di |
| 连接池 | DB/Redis 协程连接池 | hyperf/pool |
| 注解缓存 | `#[Cacheable]` 自动缓存方法结果 | hyperf/cache |
| 服务治理 | 限流、熔断、降级 | hyperf/circuit-breaker, hyperf/rate-limit |
| RPC | JSON-RPC / gRPC 服务 | hyperf/rpc-server |
| 配置中心 | Apollo/Nacos/Etcd 动态配置 | hyperf/config-center |
| 异步队列 | 基于 Redis 的协程消费 | hyperf/async-queue |
| Crontab | 秒级定时任务 | hyperf/crontab |

```php
// 典型 Hyperf Controller
#[Controller(prefix: '/user')]
class UserController
{
    #[Inject]
    private UserService $service;

    #[GetMapping(path: '{id:\d+}')]
    #[RateLimit(create: 100, capacity: 100)]   // 令牌桶限流
    public function show(int $id): array
    {
        return $this->service->find($id);
    }
}

// AOP 切面: 自动记录方法耗时
#[Aspect]
class TimerAspect extends AbstractAspect
{
    public array $annotations = [Timer::class];

    public function process(ProceedingJoinPoint $point)
    {
        $start = microtime(true);
        $result = $point->process();
        $cost = microtime(true) - $start;
        // 上报 metric
        return $result;
    }
}

// Cacheable: 方法结果自动缓存, 协程安全
#[Cacheable(prefix: 'user', ttl: 3600)]
public function getUserInfo(int $id): array
{
    return Db::table('users')->where('id', $id)->first();
}
```

**面试 Q：Hyperf 的 DI 与 Laravel 的容器有什么本质区别？**

两者都实现了 IoC，但解析时机和生命周期完全不同。Laravel 容器是「运行时反射」型：每次请求重建容器，解析类时通过 `ReflectionClass` 读取构造器签名，递归解析依赖——灵活，但反射有运行时开销，且无法在 FPM 模型里跨请求复用。Hyperf 走的是「编译期生成代理类」路线：启动时扫描所有 `#[Inject]`、`#[Aspect]` 注解，提前生成代理类并落盘到 `runtime/container`，运行时直接 `new` 代理类、零反射；容器本身是进程级单例，所有协程共享同一份对象图。这也是为什么 Hyperf 能原生支持 AOP（代理类是织入切面的天然载体），而 Laravel 需要靠中间件或第三方包变相实现。

| 维度 | Laravel 容器 | Hyperf DI |
|------|-------------|-----------|
| 解析时机 | 运行时反射解析 | 编译期扫描注解 + 生成代理类 |
| 性能 | 每次请求反射，有开销 | 启动时构建一次，运行时零反射 |
| 生命周期 | 请求级（FPM 重建） | 进程级（常驻，协程复用） |
| AOP | 需第三方包 | 原生支持（基于代理类） |
| 注入方式 | 构造器/方法 | `#[Inject]` 属性注入 + 构造器 |

---

## 2. Hyperf 生命周期

Hyperf 的生命周期分三段：**框架启动期（进程级，只跑一次）→ 请求处理期（协程级，每请求一次）→ 进程/请求销毁期**。理解「哪些在启动期、哪些在请求期」是常驻内存编程的关键。

```
Hyperf 生命周期全景
┌──────────────────────────────────────────────────────────────┐
│ 阶段一：框架启动期（进程内只执行一次）                          │
│  bin/hyperf.php start                                          │
│   │                                                            │
│   ├─ 加载 .env / config/*.php                                  │
│   ├─ 扫描注解 → 编译生成代理类（runtime/container/proxy）       │
│   │   （首次启动或 BootApplication 时，后续读缓存）             │
│   ├─ 实例化 DI 容器（进程级单例，协程间复用）                  │
│   ├─ 触发 BootApplication 事件（监听器在此注册路由/中间件）     │
│   ├─ 启动 Swoole Server                                        │
│   │                                                            │
│   ├─ onWorkerStart  ← 每个 Worker 启动时（连接池预热在此）      │
│   └─ onStart        ← Master 启动                              │
├──────────────────────────────────────────────────────────────┤
│ 阶段二：请求处理期（每个请求 = 一个协程，自动隔离）             │
│   onRequest 回调 → 创建协程                                    │
│   │                                                            │
│   ├─ CoreMiddleware：路由匹配（注解路由表查找）                │
│   ├─ 全局中间件 → 路由中间件（洋葱模型，PSR-15）               │
│   ├─ ExceptionHandler 链（异常拦截，按优先级匹配）             │
│   ├─ Controller 方法（依赖通过 #[Inject]/参数解析注入）        │
│   │    └─ AOP 切面在此织入（环绕 Controller/Service 方法）     │
│   ├─ 返回 PSR-7 Response                                       │
│   └─ defer() 回调执行 → 协程上下文（Context）自动销毁          │
├──────────────────────────────────────────────────────────────┤
│ 阶段三：销毁期                                                 │
│   ├─ 每请求：Context 随协程结束自动 GC                         │
│   ├─ Worker：达到 max_request 后退出 → onWorkerExit → 重建      │
│   └─ Server：收到信号 → onWorkerStop → onShutdown             │
└──────────────────────────────────────────────────────────────┘
```

**关键事件回调与执行时机：**

| 事件 | 触发时机 | 频率 | 典型用途 |
|------|---------|------|---------|
| `BootApplication` | 框架启动、Server 创建前 | 1 次/进程 | 注册命令、初始化全局配置 |
| `BeforeMainServerStart` | 主 Server 启动前 | 1 次 | 修改 Server 配置、注册自定义进程 |
| `onStart` | Master 进程启动 | 1 次 | 写 PID、初始化监控 |
| `onWorkerStart` | 每个 Worker 启动 | worker_num 次 | **连接池预热、单例初始化**（最常用） |
| `onRequest` | 每个 HTTP 请求 | 每请求 | 进入请求处理协程 |
| `onWorkerStop/Exit` | Worker 退出 | 每次重启 | 释放资源、关闭连接 |
| `onShutdown` | Server 关闭 | 1 次 | 优雅停机清理 |

**面试 Q：Hyperf 请求生命周期和 Laravel 最本质的区别？**

本质区别在于「框架引导的时机」。Laravel 跑在 PHP-FPM 上，每个请求都要从 `index.php` 重新 bootstrap 一遍：新建 `Application` 容器、注册全部 ServiceProvider、加载路由，请求结束进程销毁、内存连同所有状态一起回收——所以天然请求隔离，几乎不存在状态污染。Hyperf 跑在常驻内存的 Swoole 上，框架引导只在 `onWorkerStart` 阶段执行一次，容器是进程级单例，请求之间复用同一份对象图；每个请求只是在 Worker 里开一个协程，靠 `Context`（协程 ID 隔离）来承载请求级数据，请求结束仅回收 Context 而非整个进程。性能因此大幅提升，但代价是：任何写在静态属性、单例可变成员上的状态都会跨请求共享，处理不当就会数据串号。

| 维度 | Laravel (FPM) | Hyperf (Swoole 协程) |
|------|--------------|---------------------|
| 框架引导 | 每请求重新 bootstrap | 启动期一次，请求间复用 |
| 容器 | 每请求 `new Application` | 进程级单例 |
| 请求隔离 | 进程天然隔离 | 协程 + Context 隔离 |
| 请求结束 | 进程销毁、内存全回收 | 仅 Context GC，进程常驻 |
| 状态风险 | 几乎没有 | 静态/单例可变状态会串号 |

**面试 Q：为什么连接池、单例初始化要放在 `onWorkerStart` 而不是请求里？**

因为 Worker 是常驻进程，`onWorkerStart` 每个 Worker 只跑一次。连接池、配置、路由表这类「进程级共享、请求间复用」的资源在此初始化一次即可，避免每请求重建。而请求级数据（登录用户、TraceId）必须放进 `Context`，随协程销毁，否则会被后续请求看到。

---

## 3. AOP 切面深入

Hyperf 的 AOP **不依赖运行时反射或魔术方法**，而是在**编译期扫描切点注解 → 生成代理类（Proxy）→ 用代理类替换原类**，把切面逻辑织入方法调用链。这与 Spring 的 CGLIB 动态代理思路一致，但发生在编译期，运行时零额外开销。

```
AOP 织入原理（编译期代理类生成）
┌─────────────────────────────────────────────────────────┐
│ 编译期（首次启动 / di:init-proxy）                        │
│                                                           │
│  扫描 #[Aspect] → 收集 classes / annotations 切点         │
│         │                                                 │
│         ▼                                                 │
│  匹配到目标方法 UserService::createUser()                 │
│         │                                                 │
│         ▼                                                 │
│  生成代理类 UserService（覆盖原方法）                     │
│   原方法体 → 包装进 ProceedingJoinPoint                   │
│         │                                                 │
│         ▼                                                 │
│  容器注入时返回 Proxy 实例而非原始类                      │
├─────────────────────────────────────────────────────────┤
│ 运行时                                                    │
│  调用 createUser()                                        │
│   → Aspect1::process($point)                              │
│       → Aspect2::process($point)                          │
│           → $point->process()  // 真正执行原方法体        │
│       ← 返回                                              │
│   ← 返回                                                  │
└─────────────────────────────────────────────────────────┘
```

**切点定义的两种方式：**

```php
#[Aspect]
class LogAspect extends AbstractAspect
{
    // 方式一：按「类::方法」精确匹配（支持通配符 *）
    public array $classes = [
        UserService::class . '::createUser',
        'App\Service\Order*::*',      // Order 开头的类的所有方法
    ];

    // 方式二：按注解匹配 —— 所有标了 #[Log] 的方法都会被织入
    public array $annotations = [
        Log::class,
    ];

    // 优先级：数字越大越靠外层（越先执行 before、越后执行 after）
    public int $priority = 100;

    public function process(ProceedingJoinPoint $point)
    {
        // 1. 前置：可读取/修改入参
        $args = $point->getArguments();
        $class = $point->className;
        $method = $point->methodName;

        // 2. 执行原方法（或被下一个切面/原方法接管）
        $result = $point->process();

        // 3. 后置：可改写返回值
        return $result;
    }
}
```

**`ProceedingJoinPoint` 关键能力：**

| 成员/方法 | 作用 |
|-----------|------|
| `$point->process()` | 执行下一个切面或原方法体（不调用 = 短路，原方法不执行） |
| `$point->getArguments()` | 获取入参数组 |
| `$point->getInstance()` | 获取被代理对象实例 |
| `$point->className` / `methodName` | 当前切点的类名 / 方法名 |
| `$point->getAnnotationMetadata()` | 取方法/类上的注解元数据（如 `#[Cacheable]` 的 ttl） |

**多切面执行顺序（洋葱模型）：**

```
priority 高 → 低 包裹执行（高 priority 在最外层）

  Aspect(priority=99)  before ─┐
    Aspect(priority=1) before ─┐│
      原方法 createUser()      ││
    Aspect(priority=1) after  ─┘│
  Aspect(priority=99)  after  ──┘
```

**面试 Q：Hyperf AOP 和 Laravel/传统 PHP 的 AOP 实现有什么不同？**

核心差异是「织入时机」和「实现机制」。Hyperf 在编译期就把切面织好：扫描切点注解后生成代理类落盘，运行时直接用代理类，没有反射、没有魔术方法拦截，开销近乎为零。Laravel 没有原生 AOP，要做类似「环绕方法」的事只能借助中间件、Pipeline、事件监听或 `__call` 魔术方法，覆盖面有限且魔术方法本身有性能成本。纯 PHP 的 Go-AOP 库走的是运行时字节码改写 / stream wrapper 拦截，能力强但较重、调试困难。Java Spring 则是运行时用 JDK 动态代理或 CGLIB 字节码增强——思路和 Hyperf 的代理类一致，只是 Spring 发生在运行时、Hyperf 提前到了编译期。

| 方案 | 织入时机 | 实现机制 | 开销 |
|------|---------|---------|------|
| Hyperf AOP | 编译期 | 扫描注解生成代理类替换原类 | 运行时零反射 |
| Laravel（无原生 AOP） | — | 多靠中间件 / Pipeline / 事件 / `__call` | 魔术方法有开销 |
| Go-AOP（PHP 库） | 运行时/加载期 | 字节码改写 / stream wrapper 拦截 | 较重，调试困难 |
| Java Spring | 运行时 | JDK 动态代理 / CGLIB 字节码增强 | 运行时反射 |

**面试 Q：AOP 代理类为什么对 `final` 方法和 `private` 方法不生效？**

代理类通过**继承被代理类并覆盖方法**来织入切面。`final` 方法无法被子类覆盖，`private` 方法子类不可见，因此都无法被代理。同理，**类内部 `$this->method()` 的自调用也不会触发切面**（绕过了代理类入口），这是和 Spring 一样的经典坑——需要通过容器拿到代理实例再调用。

**AOP 典型应用场景：**

| 场景 | 切面做的事 | 配套注解 |
|------|-----------|---------|
| 方法缓存 | 命中缓存直接返回，不执行原方法 | `#[Cacheable]` |
| 声明式事务 | 环绕方法开启/提交/回滚事务 | `#[Transactional]` |
| 限流熔断 | 超阈值短路返回降级结果 | `#[RateLimit]` / `#[CircuitBreaker]` |
| 日志/审计 | 记录入参、返回值、耗时 | 自定义 `#[Log]` |
| 重试 | 异常时按策略重试 `$point->process()` | `#[Retry]` |

---

## 4. 协程安全

常驻内存 + 协程并发，最大的陷阱是**全局/静态可变状态被多个协程共享**导致数据串号。协程原理与 `Context`/连接池的底层机制见 [Swoole 协程通信引擎](./16-swoole-advanced.md)。

**面试 Q：Hyperf 中如何保证协程安全？**

协程安全的核心是「请求级状态绝不落在进程级共享的位置」。Hyperf 在常驻内存里跑，容器、单例、静态属性都是进程级、跨协程共享的，一旦把当前登录用户、请求参数这类请求级数据写进去，并发请求就会互相覆盖。正确做法是把请求级状态统一交给 `Hyperf\Context\Context`（基于协程 ID 隔离，请求结束自动清理），连接这类资源从连接池借取、用完归还而非常驻单例持有，并对第三方 SDK 保持警惕——很多老 SDK 内部用了 curl 阻塞或静态缓存，在协程下既会阻塞调度又会污染状态。

1. **禁用全局/静态可变状态**，改用 `Hyperf\Context\Context`（协程 ID 隔离，请求结束自动清理）
2. **连接从连接池借取**，请求结束归还，不在协程间共享同一连接
3. **请求级数据**（如当前登录用户、TraceId）存入 Context，而非类属性
4. **第三方 SDK 谨慎使用**：检查内部是否用了 curl 阻塞、静态缓存等非协程安全写法

---

## 5. 生产实践要点

| 场景 | 实践 |
|------|------|
| 内存泄露 | Worker 设置 `max_request`（处理 N 个请求后重启），兜底内存增长 |
| 平滑重启 | `Server::reload()` 重载 Worker，配合发布灰度 |
| 长连接保活 | MySQL 连接池设置 `heartbeat`，防 `gone away` |
| 阻塞排查 | 避免在协程中调用未 Hook 的扩展（如某些加密/图像库 C 扩展） |
| 异常处理 | 协程内异常不会冒泡到其他协程，需在协程入口 `try/catch` 兜底 |
| CPU 密集任务 | 投递到 Task Worker 或独立进程，避免阻塞协程调度 |
| 调试 | `Swoole\Coroutine::stats()` 查看协程数量；`Co::list()` 列出活跃协程 |

**面试 Q：什么业务适合用 Swoole/Hyperf，什么不适合？**

判断标准是「瓶颈在 I/O 还是在 CPU，以及团队能否驾驭协程」。Swoole/Hyperf 的优势全部来自协程化 I/O 和常驻内存——I/O 等待时自动让出 CPU，单 Worker 扛起海量并发，所以 I/O 密集型的高并发 API、微服务、WebSocket 长连接、网关/BFF 聚合层是它的主场。反过来，纯 CPU 密集计算里协程没有用武之地（CPU 一直忙，没有 I/O 可让出），反而引入协程复杂度；重度依赖非协程安全 C 扩展的遗留系统容易踩阻塞和数据污染的坑；而对快速验证的原型或缺乏协程经验的小团队，Laravel 的开发效率和心智成本更划算。一句话：用它换并发吞吐，但要先付出协程安全的认知成本。

| 适合 | 不适合 |
|------|--------|
| 高并发 API / 微服务（I/O 密集） | 团队无协程经验、维护成本敏感的小项目 |
| WebSocket 长连接、IM、推送 | 重度依赖非协程安全 C 扩展的遗留系统 |
| 网关、BFF 聚合层 | 纯 CPU 密集计算（协程无优势，反增复杂度） |
| 实时性要求高的内部 RPC 服务 | 快速验证的原型（Laravel 开发效率更高） |

---

> **维护说明：**
> - 本文档由 PHP 文档（`01-php-advanced.md`）的 Swoole/Hyperf 模块拆分独立而来
> - 最新更新：2026-06 | Hyperf 3.x / Swoole 5.x
> - 关联：[Swoole 协程通信引擎](./16-swoole-advanced.md) · [Laravel](./14-laravel-advanced.md) · [PHP](./01-php-advanced.md)
