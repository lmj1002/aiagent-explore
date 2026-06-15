# Laravel 原理深度解析：从生命周期到 Redis 队列

> 本文从源码级深度剖析 Laravel 框架的核心机制：请求生命周期、IoC 容器与依赖注入、Facade 门面模式、ServiceProvider 服务提供者、以及 Redis 队列的 Lua 脚本与事务实现。适用于需要深入理解 Laravel 内核的高级 PHP 开发工程师。

---

## 目录

1. [请求生命周期](#1-请求生命周期)
2. [IoC 容器与依赖注入](#2-ioc-容器与依赖注入)
3. [Facade 门面模式](#3-facade-门面模式)
4. [ServiceProvider 服务提供者](#4-serviceprovider-服务提供者)
5. [Redis 队列深度解析](#5-redis-队列深度解析)
6. [Lua 脚本与事务](#6-lua-脚本与事务)

---

## 1. 请求生命周期

### 1.1 完整请求链路

```
┌──────────────────────────────────────────────────────────────────────┐
│                    Laravel Request Lifecycle                           │
│                                                                        │
│  HTTP Request (GET /api/users)                                        │
│       │                                                                │
│       ▼                                                                │
│  ┌──────────────────┐                                                │
│  │ public/index.php │ 入口文件                                        │
│  │ - 加载 Composer   │                                                │
│  │   autoloader     │                                                │
│  │ - 启动 Application│                                               │
│  └────────┬─────────┘                                                │
│           │                                                            │
│           ▼                                                            │
│  ┌──────────────────────────────────────────────────────────────┐    │
│  │ ① Bootstrap (内核启动)                                         │    │
│  │                                                               │    │
│  │  Application::bootstrapWith()                                 │    │
│  │  ┌───────────────────────────────────────────────────────┐   │    │
│  │  │ 顺序执行 8 个 Bootstrapper:                            │   │    │
│  │  │                                                        │   │    │
│  │  │ 1. LoadEnvironmentVariables  (.env → $_ENV)            │   │    │
│  │  │ 2. LoadConfiguration         (config/*.php → config()) │   │    │
│  │  │ 3. HandleExceptions          (异常处理器注册)          │   │    │
│  │  │ 4. RegisterFacades           (Facade 别名注册)         │   │    │
│  │  │ 5. RegisterProviders         (所有 ServiceProvider)    │   │    │
│  │  │    └→ 每个 Provider 的 register() 被调用              │   │    │
│  │  │    └→ 所有 Provider 的 boot() 被调用                  │   │    │
│  │  │ 6. BootProviders             (触发 booting/booted 事件)│   │    │
│  │  └───────────────────────────────────────────────────────┘   │    │
│  └──────────────────────────┬───────────────────────────────────┘    │
│                             │                                          │
│                             ▼                                          │
│  ┌──────────────────────────────────────────────────────────────┐    │
│  │ ② Kernel::handle() (请求处理)                                  │    │
│  │                                                               │    │
│  │  HttpKernel extends Kernel (Illuminate\Foundation\Http\Kernel)│    │
│  │                                                               │    │
│  │  handle($request) {                                           │    │
│  │    ┌──────────────────────────────────────────────────┐      │    │
│  │    │ 发送请求到 Router → 中间件 Pipeline → Controller │      │    │
│  │    │                                                   │      │    │
│  │    │  sendRequestThroughRouter()                      │      │    │
│  │    │   │                                               │      │    │
│  │    │   ▼                                               │      │    │
│  │    │  Pipeline (中间件管道)                            │      │    │
│  │    │  ┌──────────────────────────────────────────┐   │      │    │
│  │    │  │ Global Middleware                         │   │      │    │
│  │    │  │  - TrustProxies                          │   │      │    │
│  │    │  │  - CORS                                   │   │      │    │
│  │    │  │  - MaintenanceMode                        │   │      │    │
│  │    │  │  - ValidatePostSize                       │   │      │    │
│  │    │  │  - TrimStrings / ConvertEmptyStrings      │   │      │    │
│  │    │  └──────────────┬───────────────────────────┘   │      │    │
│  │    │                 ▼                                │      │    │
│  │    │  ┌──────────────────────────────────────────┐   │      │    │
│  │    │  │ Route Middleware Group                    │   │      │    │
│  │    │  │  - auth / throttle / bindings            │   │      │    │
│  │    │  └──────────────┬───────────────────────────┘   │      │    │
│  │    │                 ▼                                │      │    │
│  │    │  ┌──────────────────────────────────────────┐   │      │    │
│  │    │  │ Controller Dispatcher                     │   │      │    │
│  │    │  │ → 执行 Controller 方法                   │   │      │    │
│  │    │  │ → Controller 构造函数可依赖注入          │   │      │    │
│  │    │  │ → 方法参数可依赖注入 + 路由参数绑定      │   │      │    │
│  │    │  └──────────────────────────────────────────┘   │      │    │
│  │    └──────────────────────────────────────────────────┘      │    │
│  │    return $response;                                          │    │
│  │  }                                                            │    │
│  └──────────────────────────┬───────────────────────────────────┘    │
│                             │                                          │
│                             ▼                                          │
│  ┌──────────────────────────────────────────────────────────────┐    │
│  │ ③ Response 发送                                               │    │
│  │                                                               │    │
│  │  Kernel::terminate()                                          │    │
│  │   - 发送响应头 + 响应体                                       │    │
│  │   - 执行终止中间件 (terminateMiddleware)                      │    │
│  │   - 触发 terminable 事件                                      │    │
│  └──────────────────────────────────────────────────────────────┘    │
└──────────────────────────────────────────────────────────────────────┘
```

### 1.2 Pipeline (中间件管道) 实现原理

```
┌──────────────────────────────────────────────────────────────────┐
│                  Pipeline (洋葱模型) 执行流程                       │
│                                                                   │
│  Request → Middleware1 → Middleware2 → Controller                 │
│      ←       │    ↑         │    ↑         │                       │
│      └───────┘    └─────────┘    └─────────┘                       │
│                                                                   │
│  源码: Illuminate\Pipeline\Pipeline                               │
│                                                                   │
│  Pipeline 的本质: array_reduce + 闭包嵌套                          │
│                                                                   │
│  $pipeline = array_reduce(                                        │
│      array_reverse($middlewares),  // 中间件倒序                   │
│      function ($stack, $pipe) {                                   │
│          return function ($passable) use ($stack, $pipe) {         │
│              // $pipe 是中间件, $stack 是内层的闭包                │
│              return $pipe->handle($passable, $stack);              │
│          };                                                       │
│      },                                                           │
│      $destination  // 最终的闭包: Controller                       │
│  );                                                               │
│                                                                   │
│  展开等价于:                                                        │
│  Middleware1::handle(                                             │
│      $request,                                                    │
│      function($req) {                                             │
│          return Middleware2::handle(                              │
│              $req,                                                │
│              function($req) { return $controller($req); }         │
│          );                                                       │
│      }                                                            │
│  );                                                               │
│                                                                   │
│  每个中间件有两个阶段:                                              │
│  - 进入阶段: $request = doSomething($request)                     │
│  - 退出阶段: $response = $next($request);                         │
│              return modifyResponse($response)                     │
└──────────────────────────────────────────────────────────────────┘
```

### 🔥 高频面试题

**Q1: 描述 Laravel 的完整请求生命周期。**

> A: HTTP Request → public/index.php(入口) → Bootstrap(8个Bootstrapper: 加载.env/Config/异常处理/Facade注册/ServiceProvider) → Kernel::handle() → Pipeline(Global Middleware → Route Middleware → Controller) → Response 返回 → Kernel::terminate(终止中间件)。核心：应用启动时通过 ServiceProvider 将所有服务注册到 IoC 容器，Controller 通过依赖注入获取所需服务，Middleware 以洋葱模型包裹请求处理。

**Q2: Laravel 中间件的执行顺序是怎样的？全局中间件和路由中间件的区别？**

> A: 执行顺序：Global Middleware(最外层) → Route Group Middleware → Route Specific Middleware。Global 在 `Kernel::$middleware` 中定义，对所有请求生效（如 CORS、TrimStrings）。路由中间件在 `Kernel::$routeMiddleware` 中注册后按需使用。中间件以洋葱模型执行：进入时从外到内，返回时从内到外。通过 `array_reduce` + 闭包嵌套实现，每个中间件的 `handle($request, $next)` 可以在 `$next($request)` 前后执行逻辑。

---

## 2. IoC 容器与依赖注入

### 2.1 IoC 容器核心架构

```
┌──────────────────────────────────────────────────────────────────┐
│               Laravel IoC Container (Illuminate\Container)         │
│                                                                   │
│  Application extends Container                                     │
│                                                                   │
│  Container 核心数据结构:                                            │
│                                                                   │
│  ┌──────────────────────────────────────────────────────────┐    │
│  │  bindings[]       : 绑定字典 (抽象→具体 映射)             │    │
│  │    "app" → Concrete: "App\SomeClass", shared: true        │    │
│  │                                                           │    │
│  │  instances[]      : 已解析的单例实例 (shared=true)        │    │
│  │    "app" → App\SomeClass 实例对象                        │    │
│  │                                                           │    │
│  │  aliases[]        : 别名映射                             │    │
│  │    "log" → "Psr\Log\LoggerInterface"                    │    │
│  │                                                           │    │
│  │  resolved[]       : 标记已解析过的绑定                   │    │
│  │    "app" → true   (不管是否单例, 标记已经 resolve 过)    │    │
│  │                                                           │    │
│  │  contextual[]     : 上下文绑定 (同一接口不同实现的场景)  │    │
│  │    "App\Jobs\SendEmail" → ["mailer" → "ses"]             │    │
│  └──────────────────────────────────────────────────────────┘    │
│                                                                   │
│  核心方法:                                                         │
│                                                                   │
│  ┌───────────────────┐                                           │
│  │ bind(abstract, concrete)  → 注册绑定, 不实例化                 │
│  │ singleton(abstract, concrete) → bind + shared=true             │
│  │ instance(abstract, instance) → 直接存实例到 instances[]       │
│  │ make(abstract) → resolve(abstract)                            │
│  │   → 反射解析构造函数 → 递归解析依赖 → 实例化                   │
│  └───────────────────┘                                           │
└──────────────────────────────────────────────────────────────────┘
```

### 2.2 依赖注入解析全流程

```
┌──────────────────────────────────────────────────────────────────┐
│               Container::make() / resolve() 全流程                 │
│                                                                   │
│  app(UserController::class)                                       │
│       │                                                            │
│       ▼                                                            │
│  ┌──────────────────────────────────────────────────────────┐    │
│  │ ① getConcrete($abstract)                                 │    │
│  │    检查 bindings[] → 找到 concrete 类名                   │    │
│  │    检查 instances[] → 单例直接返回                       │    │
│  │    检查 aliases[] → 解析别名                             │    │
│  └──────────────────────────┬───────────────────────────────┘    │
│                             │                                      │
│                             ▼                                      │
│  ┌──────────────────────────────────────────────────────────┐    │
│  │ ② build($concrete)                                       │    │
│  │                                                           │    │
│  │  ReflectionClass($concrete)                                │    │
│  │       │                                                    │    │
│  │       ▼                                                    │    │
│  │  检查构造函数:                                              │    │
│  │       │                                                    │    │
│  │  ┌────┴────┐                                              │    │
│  │  │ 无构造函数│  ─→ new $concrete (简单实例化)              │    │
│  │  │          │                                              │    │
│  │  ├─────────┤                                              │    │
│  │  │ 有构造函数│                                             │    │
│  │  │   │                                                    │    │
│  │  │   ▼                                                    │    │
│  │  │  ReflectionParameter[] 解析构造函数参数                  │    │
│  │  │       │                                                │    │
│  │  │       ▼                                                │    │
│  │  │  对每个参数:                                            │    │
│  │  │    if (有类型提示 && 是类名):                           │    │
│  │  │        → $this->make(参数类型) ← 递归解析!              │    │
│  │  │    elif (有默认值):                                     │    │
│  │  │        → 使用默认值                                     │    │
│  │  │    elif (Primitive 且无默认值):                        │    │
│  │  │        → 需要上下文绑定 / 传入参数                      │    │
│  │  │    elif (接口类型提示):                                 │    │
│  │  │        → 从 bindings[] 找具体实现                      │    │
│  │  │        → 检查 contextual[] 上下文绑定                  │    │
│  │  │                                                         │    │
│  │  │  收集所有解析出来的参数 → new $concrete($args)          │    │
│  │  └────────────────────────────────────────────────────┘    │    │
│  └──────────────────────────────────────────────────────────┘    │
│                                                                   │
│  示例: 解析 UserController                                        │
│  ┌──────────────────────────────────────────────────────────┐    │
│  │  class UserController {                                   │    │
│  │      public function __construct(                         │    │
│  │          UserService $userService,  // → make(UserService)│    │
│  │          LoggerInterface $log,       // → 找接口绑定      │    │
│  │      ) {}                         │    │
│  │  }                              │    │
│  │                                 │    │
│  │  解析链路:                       │    │
│  │  UserController                 │    │
│  │    → UserService                │    │
│  │        → UserRepository         │    │
│  │            → DatabaseManager    │    │
│  │    → LoggerInterface            │    │
│  │        → bindings["log"] = Monolog  │    │
│  │            → Monolog            │    │
│  └──────────────────────────────────────────────────────────┘    │
└──────────────────────────────────────────────────────────────────┘
```

### 2.3 上下文绑定 (Contextual Binding)

```
┌──────────────────────────────────────────────────────────────────┐
│                    上下文绑定 (Contextual Binding)                  │
│                                                                   │
│  场景: 同一个接口在不同地方需要不同的实现                            │
│                                                                   │
│  ┌──────────────────────────────────────────────────────────┐    │
│  │  // AppServiceProvider::register()                        │    │
│  │                                                           │    │
│  │  // 普通绑定: 所有地方用同一个实现                         │    │
│  │  $this->app->bind(FileSystem::class, LocalStorage::class);│    │
│  │                                                           │    │
│  │  // 上下文绑定: 不同消费者用不同实现                       │    │
│  │  $this->app->when(PhotoController::class)                 │    │
│  │      ->needs(FileSystem::class)                           │    │
│  │      ->give(S3Storage::class);    // Photo 用 S3          │    │
│  │                                                           │    │
│  │  $this->app->when(VideoController::class)                 │    │
│  │      ->needs(FileSystem::class)                           │    │
│  │      ->give(CloudFrontStorage::class); // Video 用 CDN    │    │
│  └──────────────────────────────────────────────────────────┘    │
│                                                                   │
│  实现原理:                                                        │
│  ┌──────────────────────────────────────────────────────────┐    │
│  │  contextual[] = [                                         │    │
│  │    "PhotoController" => [                                │    │
│  │      "FileSystem" → Closure { return new S3Storage() }   │    │
│  │    ],                                                     │    │
│  │  ]                                                        │    │
│  │                                                           │    │
│  │  解析时: 先检查 contextual[当前正在构建的类][参数抽象名]  │    │
│  │          → 有 → 使用上下文绑定的具体实现                   │    │
│  │          → 无 → 使用全局 bindings[]                       │    │
│  └──────────────────────────────────────────────────────────┘    │
└──────────────────────────────────────────────────────────────────┘
```

### 2.4 方法注入 vs 构造函数注入

```
┌──────────────────────────────────────────────────────────────────┐
│                 方法注入 (Method Injection)                        │
│                                                                   │
│  Container::call() 可以自动解析方法参数:                           │
│                                                                   │
│  class ReportGenerator {                                          │
│      public function generate(                                    │
│          Request $request,              // → app(Request::class)   │
│          UserRepository $users,         // → app(UserRepo::class) │
│          $format = 'pdf'               // → 使用默认值           │
│      ) { ... }                              │    │
│  }                              │    │
│                                 │    │
│  // Controller 方法自动获得方法注入:                              │
│  Route::get('/report', [ReportGenerator::class, 'generate']);     │
│                                                                   │
│  // 手动调用:                                                 │    │
│  app()->call([ReportGenerator::class, 'generate']);               │
│  app()->call([$reportGenerator, 'generate'], ['format'=>'xlsx']);│
│                                                                   │
│  解析流程:                                                         │
│  ① ReflectionMethod($class, $method)                             │
│  ② 遍历参数 → 类类型: make() / 普通值: 从传入参数或默认值        │
│  ③ 调用 $method->invokeArgs($object, $resolvedArgs)             │
└──────────────────────────────────────────────────────────────────┘
```

### 🔥 高频面试题

**Q1: Laravel 的依赖注入是如何实现的？和"控制反转(IoC)"有什么关系？**

> A: Laravel 通过 IoC 容器 + 反射实现自动依赖注入。控制反转 (IoC) 是一种设计原则，传统的"控制权"在调用方(new 自己需要的依赖)，而 IoC 将"控制权"反转给容器——调用方声明需要什么，容器负责创建和注入。依赖注入 (DI) 是实现 IoC 的一种手段。Laravel 的 Container::make() 利用 PHP 反射读取构造函数参数的类型提示 (ReflectionClass → getConstructor → getParameters)，递归解析每个参数的类型 → 实例化并注入，形成完整的依赖链。

**Q2: Laravel 中 bind / singleton / instance 的区别？**

> A: `bind(抽象, 具体)` 每次 make 都会重新创建实例。`singleton(抽象, 具体)` 等价于 `bind + shared=true`，第一次 make 后存入 instances[]，后续返回同一实例。`instance(抽象, 实例)` 直接将已有对象存入 instances[]，跳过反射构建过程，通常用于绑定已实例化的对象（如 `$app->instance('path.base', '/var/www')`）。

**Q3: 什么是反向注入(Reverse Injection)？在 Laravel 中如何体现？**

> A: 反向注入指不是在调用方主动获取依赖，而是由框架/容器主动将依赖"推"给调用方，也叫"控制反转"。Laravel 中体现在：① 构造函数注入：Controller 声明 `__construct(UserService $service)`，框架自动注入；② 方法注入：Controller 方法参数如 `show(Request $request, User $user)`，框架解析路由模型绑定和 Request 对象；③ 事件监听器的 `handle()` 方法参数；④ Queue Job 的 `handle()` 方法参数。开发者只需声明需要什么的"造型"(Type Hint)，容器自动完成实例化与注入。

---

## 3. Facade 门面模式

### 3.1 Facade 实现原理

```
┌──────────────────────────────────────────────────────────────────┐
│                  Facade 原理图解                                    │
│                                                                   │
│  Cache::get('key')  你的代码                                       │
│       │                                                            │
│       ▼                                                            │
│  ┌──────────────────────────────────────────────────────────┐    │
│  │  Illuminate\Support\Facades\Cache (Facade 类)              │    │
│  │                                                           │    │
│  │  class Cache extends Facade {                             │    │
│  │      protected static function getFacadeAccessor() {       │    │
│  │          return 'cache';  ← 服务的"抽象名"   │    │
│  │      }                                         │    │
│  │  }                                             │    │
│  └────────────────────┬──────────────────────────┘    │
│                       │                                    │    │
│                       ▼                                    │    │
│  ┌──────────────────────────────────────────────────────────┐    │
│  │  Facade 基类 __callStatic() 魔术方法                      │    │
│  │                                                           │    │
│  │  public static function __callStatic($method, $args) {    │    │
│  │      $instance = static::resolveFacadeInstance(           │    │
│  │          static::getFacadeAccessor()  // → "cache"       │    │
│  │      );                                                   │    │
│  │      return $instance->$method(...$args);                 │    │
│  │  }                                                        │    │
│  │                                                           │    │
│  │  resolveFacadeInstance:                                   │    │
│  │    → app('cache')  ← 从 IoC 容器中取出!                  │    │
│  │    → 即 Illuminate\Cache\CacheManager 实例               │    │
│  └──────────────────────────────────────────────────────────┘    │
│                                                                   │
│  Facade 本质: 静态代理 + __callStatic + IoC 容器 = 语法糖          │
└──────────────────────────────────────────────────────────────────┘
```

### 3.2 Facade 别名注册流程

```
┌──────────────────────────────────────────────────────────────────┐
│                  Facade 别名注册                                    │
│                                                                   │
│  ① config/app.php:                                                │
│  ┌──────────────────────────────────────────────────────────┐    │
│  │  'aliases' => [                                          │    │
│  │      'Cache' => Illuminate\Support\Facades\Cache::class,  │    │
│  │      'DB'    => Illuminate\Support\Facades\DB::class,    │    │
│  │      'Log'   => Illuminate\Support\Facades\Log::class,   │    │
│  │      ...                                                 │    │
│  │  ]                                                        │    │
│  └──────────────────────────────────────────────────────────┘    │
│                                                                   │
│  ② RegisterFacades Bootstrapper:                                  │
│  ┌──────────────────────────────────────────────────────────┐    │
│  │  AliasLoader::getInstance(array $aliases)                 │    │
│  │      → spl_autoload_register(AliasLoader::load(...))     │    │
│  │                                                           │    │
│  │  AliasLoader::load($alias):                               │    │
│  │      if (isset(aliases[$alias])) {                       │    │
│  │          class_alias(aliases[$alias], $alias);  ← PHP原生│    │
│  │      }                                                    │    │
│  └──────────────────────────────────────────────────────────┘    │
│                                                                   │
│  ③ 实际效果: class_alias() 让 Cache 成为完整类名的别名            │
│     使用 Cache::get() 时 PHP autoload → 加载 Facade 类            │
│     → __callStatic → app('cache')->get()                         │
└──────────────────────────────────────────────────────────────────┘
```

### 3.3 实时 Facade (Real-Time Facade)

```
┌──────────────────────────────────────────────────────────────────┐
│             Real-Time Facade (Laravel 5.4+)                        │
│                                                                   │
│  普通 Facade: 需要创建 Facade 子类                                 │
│  实时 Facade: 无需创建, 直接在 use 时加 Facades\ 前缀              │
│                                                                   │
│  ┌──────────────────────────────────────────────────────────┐    │
│  │  use Facades\App\Services\PaymentGateway;                 │    │
│  │                                                           │    │
│  │  PaymentGateway::charge(100);                             │    │
│  │  // 等价于: app(PaymentGateway::class)->charge(100);      │    │
│  └──────────────────────────────────────────────────────────┘    │
│                                                                   │
│  原理: 编译时替换                                                  │
│  ┌──────────────────────────────────────────────────────────┐    │
│  │  Composer autoload 找不到 Facades\App\Services\...       │    │
│  │  → Laravel 注册的 autoloader 拦截                         │    │
│  │  → 动态生成一个继承 Facade 的临时类                        │    │
│  │  → getFacadeAccessor() 返回原始类名                       │    │
│  └──────────────────────────────────────────────────────────┘    │
└──────────────────────────────────────────────────────────────────┘
```

### 🔥 高频面试题

**Q1: Facade 模式的实现原理是什么？它的优缺点？**

> A: 核心原理：① Facade 子类定义 `getFacadeAccessor()` 返回服务名 → ② `__callStatic` 魔术方法拦截静态调用 → ③ 从 IoC 容器 `app($accessor)` 获取实际服务实例 → ④ 委托 `$instance->$method(...)`。优点：简洁的静态风格 API、可测试(可 mock 底层服务)、IDE 友好。缺点：过度使用会导致"Service Locator"反模式、隐藏了真正的依赖关系、静态调用难以追踪依赖链路。

**Q2: 如何对 Facade 进行单元测试？**

> A: `Cache::shouldReceive('get')->with('key')->andReturn('value')`。底层原理：Laravel 的 Facade 提供了 `shouldReceive()` 方法(facade mock 机制)，它会用 Mockery 创建一个 mock 对象，通过 `app()->instance($accessor, $mock)` 替换容器中的实际服务。测试后调用 `Facade::clearResolvedInstances()` 恢复。也可直接通过构造函数注入来代替 Facade，使测试更简单。

---

## 4. ServiceProvider 服务提供者

### 4.1 ServiceProvider 注册流程

```
┌──────────────────────────────────────────────────────────────────┐
│             ServiceProvider 生命周期与注册流程                      │
│                                                                   │
│  Bootstrap 阶段:                                                   │
│  ┌──────────────────────────────────────────────────────────┐    │
│  │                                                           │    │
│  │  ① 收集所有 ServiceProvider:                              │    │
│  │     config/app.php → providers[]                          │    │
│  │     核心 Provider (框架自带, 在 Foundation\Application)    │    │
│  │     应用 Provider (config/app.php 中配置)                 │    │
│  │     延迟 Provider (DeferrableProvider)                    │    │
│  │                                                           │    │
│  │  ② 遍历所有 Provider, 调用 register():                    │    │
│  │     Provider::register()                                  │    │
│  │       ├── $this->app->bind(...)          ← 注册绑定      │    │
│  │       ├── $this->app->singleton(...)     ← 注册单例       │    │
│  │       ├── $this->app->instance(...)      ← 注册实例       │    │
│  │       ├── $this->mergeConfigFrom(...)    ← 合并配置       │    │
│  │       └── $this->loadRoutesFrom(...)     ← 加载路由       │    │
│  │                                                           │    │
│  │  ③ 所有 register() 执行完后, 遍历调用 boot():             │    │
│  │     Provider::boot()                                      │    │
│  │       ├── 可以使用其他 Provider 的服务 (都已注册)         │    │
│  │       ├── 注册视图组件 / Blade 指令                       │    │
│  │       ├── 注册事件监听器                                  │    │
│  │       └── 发布配置文件/迁移文件                           │    │
│  │                                                           │    │
│  └──────────────────────────────────────────────────────────┘    │
│                                                                   │
│  时序保证: register() 按序执行 → 全部完成后 → boot() 按序执行     │
│  register() 中不要依赖其他 Provider 的服务! (可能还没注册)        │
│  boot() 中可以安全使用任何已注册的服务                             │
└──────────────────────────────────────────────────────────────────┘
```

### 4.2 延迟加载 Provider (DeferrableProvider)

```
┌──────────────────────────────────────────────────────────────────┐
│              延迟加载 ServiceProvider                               │
│                                                                   │
│  class RedisQueueServiceProvider extends ServiceProvider           │
│      implements DeferrableProvider                                 │
│  {                                                                │
│      public function provides() {                                 │
│          return ['redis.queue', RedisQueue::class];               │
│      }                                                            │
│  }                                                                │
│                                                                   │
│  延迟加载流程:                                                     │
│  ┌──────────────────────────────────────────────────────────┐    │
│  │                                                           │    │
│  │  ① 启动时: Provider 被记录, 但不执行 register()/boot()    │    │
│  │  ② 第一次 app('redis.queue') 时:                          │    │
│  │     → 检查延迟 Provider 注册表                            │    │
│  │     → 找到 RedisQueueServiceProvider                     │    │
│  │     → 立即执行 register()                                 │    │
│  │     → 解析返回                                           │    │
│  │  ③ 后续请求 app('redis.queue'): 从 instances[] 直接返回   │    │
│  │                                                           │    │
│  │  注意: 延迟 Provider 的 boot() 在首次使用服务时也会执行    │    │
│  └──────────────────────────────────────────────────────────┘    │
│                                                                   │
│  优势: 减少应用启动时的内存和 CPU 开销                            │
│  适用: 不是每个请求都需要的服务 (如 PDF 生成、Excel 导出等)       │
└──────────────────────────────────────────────────────────────────┘
```

### 4.3 自定义 ServiceProvider 最佳实践

```
┌──────────────────────────────────────────────────────────────────┐
│              自定义 ServiceProvider 模板                            │
│                                                                   │
│  class PaymentServiceProvider extends ServiceProvider {           │
│                                                                   │
│      // register(): 只做绑定, 不做其他事                          │
│      public function register() {                                 │
│          $this->app->singleton(PaymentGateway::class, function() { │
│              return new StripeGateway(config('payment.stripe'));  │
│          });                                                      │
│                                                                   │
│          // 上下文绑定: 不同场景用不同实现                        │
│          $this->app->when(OrderController::class)                  │
│              ->needs(PaymentGateway::class)                        │
│              ->give(AlipayGateway::class);                        │
│      }                                                            │
│                                                                   │
│      // boot(): 在全部服务都注册之后才执行                        │
│      public function boot() {                                     │
│          // 使用 Event Facade (已注册)                             │
│          Event::listen(OrderPaid::class, SendInvoice::class);     │
│                                                                   │
│          // 发布配置文件                                           │
│          $this->publishes([                                       │
│              __DIR__.'/config/payment.php' => config_path(...),   │
│          ], 'payment-config');                                    │
│                                                                   │
│          // 注册自定义验证规则                                     │
│          Validator::extend('credit_card', ...);                   │
│      }                                                            │
│  }                                                                │
└──────────────────────────────────────────────────────────────────┘
```

### 🔥 高频面试题

**Q1: ServiceProvider 的 register() 和 boot() 有什么区别？为什么有这种区分？**

> A: `register()` 只做服务绑定(bind/singleton/instance)，**不能**使用其他 Provider 的服务，因为框架保证所有 register() 执行完后才执行 boot()。`boot()` 在所有 Provider 注册完成后执行，可以安全使用框架的任何服务(路由、事件、视图等)。这种两阶段设计确保了 Provider 之间的依赖顺序问题——你在 register() 中不需要关心其他 Provider 是否已存在，在 boot() 中可以安全使用它们。

**Q2: 延迟加载 ServiceProvider 的应用场景？实现原理？**

> A: 实现 `DeferrableProvider` 接口并定义 `provides()` 返回该 Provider 提供的服务列表。应用场景：不是每个请求都需要的重型服务(如 PDF 生成 DomPDFProvider、图片处理 InterventionImageProvider、Excel 导出等)。实现原理：启动时不执行 register()，首次 `app($service)` 时触发 `loadDeferredProvider()` → 执行 register() → 返回实例。

---

## 5. Redis 队列深度解析

### 5.1 Laravel 队列整体架构

```
┌──────────────────────────────────────────────────────────────────┐
│                Laravel Queue 架构                                   │
│                                                                   │
│  ┌──────────────────────────────────────────────────────────┐    │
│  │                    Job (任务)                              │    │
│  │  class SendEmail implements ShouldQueue {                 │    │
│  │      use Dispatchable, InteractsWithQueue,                │    │
│  │          Queueable, SerializesModels;                     │    │
│  │                                                           │    │
│  │      public function handle() { ... }                     │    │
│  │  }                                                        │    │
│  └─────────────────────┬────────────────────────────────────┘    │
│                        │ dispatch(new SendEmail($user))           │
│                        ▼                                          │
│  ┌──────────────────────────────────────────────────────────┐    │
│  │           Dispatcher / PendingDispatch                    │    │
│  │   Jobs\SendEmail::dispatch($user)                        │    │
│  │     → PendingDispatch → Dispatcher::dispatch()           │    │
│  │       → QueueManager::push()                             │    │
│  │         → RedisQueue::push()                             │    │
│  └─────────────────────┬────────────────────────────────────┘    │
│                        │                                          │
│                        ▼                                          │
│  ┌──────────────────────────────────────────────────────────┐    │
│  │                  Redis 存储层                              │    │
│  │                                                           │    │
│  │  queues:default          (List) ← 待执行任务              │    │
│  │  queues:default:delayed  (ZSet) ← 延迟任务 (score=时间戳)│    │
│  │  queues:default:reserved (ZSet) ← 执行中任务              │    │
│  └─────────────────────┬────────────────────────────────────┘    │
│                        │                                          │
│                        ▼                                          │
│  ┌──────────────────────────────────────────────────────────┐    │
│  │                Worker (消费者)                             │    │
│  │  php artisan queue:work redis                             │    │
│  │                                                           │    │
│  │  while (true) {                                           │    │
│  │      $job = pop next job from queues:default             │    │
│  │      → 调用 Job::handle()                                 │    │
│  │      → 成功: 删除 job                                     │    │
│  │      → 失败: 重试 / 放入 failed 队列                     │    │
│  │  }                                                        │    │
│  └──────────────────────────────────────────────────────────┘    │
└──────────────────────────────────────────────────────────────────┘
```

### 5.2 Redis 队列数据存储结构

```
┌──────────────────────────────────────────────────────────────────┐
│            Laravel Redis Queue 底层 Key 与数据结构                 │
│                                                                   │
│  Queue: "default"                                                 │
│  ┌──────────────────────────────────────────────────────────┐    │
│  │                                                           │    │
│  │  KEY                          TYPE    说明                │    │
│  │  ─────────────────────────── ─────── ──────────────────  │    │
│  │  queues:default               LIST    待执行队列         │    │
│  │    格式: JSON {                                               │    │
│  │      "uuid": "xxx",                                          │    │
│  │      "displayName": "App\\Jobs\\SendEmail",                  │    │
│  │      "job": "Illuminate\\Queue\\CallQueuedHandler@call",     │    │
│  │      "data": { "command": "O:34:\"App\\Jobs\\SendEmail\"..." },│   │
│  │      "attempts": 0,                                          │    │
│  │      "maxTries": 3,                                          │    │
│  │      "timeout": 60,                                          │    │
│  │      "backoff": null                                         │    │
│  │    }                                                         │    │
│  │                                                           │    │
│  │  queues:default:delayed       ZSET    延迟任务            │    │
│  │    member: JSON payload                                  │    │
│  │    score:  Unix timestamp (执行时间)                      │    │
│  │                                                           │    │
│  │  queues:default:reserved       ZSET    执行中任务 (/reserved)│  │
│  │    member: JSON payload                                       │    │
│  │    score:  Unix timestamp (retry time)                        │    │
│  │                                                               │    │
│  │  queues:notify                 LIST    通知队列 (/notify)     │    │
│  │    用于唤醒阻塞等待的 Worker                                   │    │
│  └──────────────────────────────────────────────────────────┘    │
└──────────────────────────────────────────────────────────────────┘
```

### 5.3 Worker 消费流程 (包含 Lua 脚本)

```
┌──────────────────────────────────────────────────────────────────┐
│              Worker 消费一条 Job 的完整流程                         │
│                                                                   │
│  php artisan queue:work redis → Worker::daemon()                  │
│       │                                                            │
│       ▼  (每次循环)                                                │
│  ┌──────────────────────────────────────────────────────────┐    │
│  │ ① 处理延迟任务到期                                          │    │
│  │                                                           │    │
│  │  Worker 调用 RedisQueue::migrate() 时执行 Lua 脚本:        │    │
│  │  ┌────────────────────────────────────────────────────┐   │    │
│  │  │  Lua Script: migrateExpiredJobs                    │   │    │
│  │  │                                                    │   │    │
│  │  │  local val = redis.call('zrangebyscore',           │   │    │
│  │  │      KEYS[1], '-inf', ARGV[1])  -- 获取到期任务    │   │    │
│  │  │                                                    │   │    │
│  │  │  if #val > 0 then                                  │   │    │
│  │  │      redis.call('zremrangebyscore',                │   │    │
│  │  │          KEYS[1], '-inf', ARGV[1]) -- 移除到期任务 │   │    │
│  │  │                                                    │   │    │
│  │  │      for i, v in pairs(val) do                     │   │    │
│  │  │          redis.call('rpush', KEYS[2], v)           │   │    │
│  │  │          -- LPUSH 到主队列                         │   │    │
│  │  │      end                                           │   │    │
│  │  │  end                                               │   │    │
│  │  │  return #val                                       │   │    │
│  │  │                                                    │   │    │
│  │  │  KEYS[1] = queues:default:delayed  (ZSet)          │   │    │
│  │  │  KEYS[2] = queues:default          (List)          │   │    │
│  │  │  ARGV[1] = current_timestamp                       │   │    │
│  │  └────────────────────────────────────────────────────┘   │    │
│  └──────────────────────────┬───────────────────────────────┘    │
│                             │                                      │
│                             ▼                                      │
│  ┌──────────────────────────────────────────────────────────┐    │
│  │ ② 从主队列 + 重试任务获取一个 Job                          │    │
│  │                                                           │    │
│  │  Lua Script: popFromQueue                                │    │
│  │  ┌────────────────────────────────────────────────────┐   │    │
│  │  │  -- 先处理 reserved 中到期的重试任务 (/reserved)      │   │    │
│  │  │  local job = redis.call('zrangebyscore',            │   │    │
│  │  │      KEYS[2], '-inf', ARGV[1], 'LIMIT', 0, 1)      │   │    │
│  │  │  if #job > 0 then                                   │   │    │
│  │  │      redis.call('zrem', KEYS[2], job[1])             │   │    │
│  │  │  else                                               │   │    │
│  │  │      -- reserved 中没有, 从主队列 LPOP               │   │    │
│  │  │      local jobs = redis.call('lpop', KEYS[1])       │   │    │
│  │  │      if jobs then                                    │   │    │
│  │  │          job = { jobs }                             │   │    │
│  │  │      end                                             │   │    │
│  │  │  end                                                 │   │    │
│  │  │  return job                                          │   │    │
│  │  │                                                    │   │    │
│  │  │  KEYS[1] = queues:default          (主队列 list)    │   │    │
│  │  │  KEYS[2] = queues:default:reserved (保留ZSet)       │   │    │
│  │  └────────────────────────────────────────────────────┘   │    │
│  └──────────────────────────┬───────────────────────────────┘    │
│                             │                                      │
│                             ▼                                      │
│  ┌──────────────────────────────────────────────────────────┐    │
│  │ ③ 将 Job 标记为 reserved (ZADD 到 reserved ZSet)         │    │
│  │                                                           │    │
│  │  redis.zadd('queues:default:reserved',                    │    │
│  │      now_unix_timestamp, job_payload)                      │    │
│  └──────────────────────────┬───────────────────────────────┘    │
│                             │                                      │
│                             ▼                                      │
│  ┌──────────────────────────────────────────────────────────┐    │
│  │ ④ 执行 Job::handle()                                      │    │
│  │    成功: ZREM from reserved → 完成!                      │    │
│  │    失败:                                                    │    │
│  │      - 还有重试次数 → ZADD 到 delayed (delay秒后重试)     │    │
│  │      - 重试耗尽 → 放入 failed_jobs 表 / 触发 failed 事件 │    │
│  │      - job 异常 → Worker 捕获, 记录日志, 继续下一个       │    │
│  └──────────────────────────────────────────────────────────┘    │
└──────────────────────────────────────────────────────────────────┘
```

### 5.4 Pop Job 的核心 Lua 脚本详解

```
┌──────────────────────────────────────────────────────────────────┐
│         RedisQueue::pop() 中执行的 Lua 脚本 (核心)                  │
│                                                                   │
│  源码: Illuminate\Queue\RedisQueue::pop()                         │
│                                                                   │
│  ┌──────────────────────────────────────────────────────────┐    │
│  │                                                           │    │
│  │  // 完整的 Pop Lua 脚本 (简化但保留核心逻辑)               │    │
│  │                                                           │    │
│  │  -- Step 1: 迁移到期的 delayed 任务到主队列               │    │
│  │  local delayed = redis.call('zrangebyscore',              │    │
│  │      KEYS[2], '-inf', ARGV[2], 'LIMIT', 0, ARGV[4])     │    │
│  │  if #delayed > 0 then                                     │    │
│  │      redis.call('zremrangebyscore',                       │    │
│  │          KEYS[2], '-inf', ARGV[2])                        │    │
│  │      for i, v in pairs(delayed) do                        │    │
│  │          redis.call('rpush', KEYS[1], v) --> migrate      │    │
│  │      end                                                  │    │
│  │  end                                                      │    │
│  │                                                           │    │
│  │  -- Step 2: 处理到期的 reserved 任务 (重试)               │    │
│  │  local reserved = redis.call('zrangebyscore',             │    │
│  │      KEYS[3], '-inf', ARGV[2], 'LIMIT', 0, ARGV[4])     │    │
│  │  if #reserved > 0 then                                    │    │
│  │      redis.call('zrem', KEYS[3], reserved[1])             │    │
│  │      return reserved                                      │    │
│  │  end                                                      │    │
│  │                                                           │    │
│  │  -- Step 3: 从主队列 LPOP                                 │    │
│  │  local job = redis.call('lpop', KEYS[1])                  │    │
│  │  if job then                                              │    │
│  │      -- 标记为 reserved (关键!)                           │    │
│  │      redis.call('zadd', KEYS[3], ARGV[1], job)           │    │
│  │      return { job, reserved } -- 返回两个值               │    │
│  │  end                                                      │    │
│  │                                                           │    │
│  │  return nil  -- 无任务                                    │    │
│  │                                                           │    │
│  │  KEYS[1] = "queues:default"            (LIST, 主队列)     │    │
│  │  KEYS[2] = "queues:default:delayed"   (ZSET, 延迟任务)   │    │
│  │  KEYS[3] = "queues:default:reserved"  (ZSET, 执行中)     │    │
│  │  ARGV[1] = now_timestamp               (reserved score)   │    │
│  │  ARGV[2] = now_timestamp               (迁移截止时间)     │    │
│  │  ARGV[3] = 'default'                   (queue name)       │    │
│  │  ARGV[4] = batch_size                  (批处理数量)       │    │
│  └──────────────────────────────────────────────────────────┘    │
│                                                                   │
│  核心思想:                                                         │
│  1. 延迟任务到期 → 迁移到主队列                                    │
│  2. 重试任务到期 → 直接返回执行                                    │
│  3. 从主队列 LPOP → 立即 ZADD reserved (防止丢失!)                │
│  4. Worker crash 后, reserved 中的任务超时 → Step 2 重试          │
└──────────────────────────────────────────────────────────────────┘
```

### 5.5 Lua 脚本的原子性保证

```
┌──────────────────────────────────────────────────────────────────┐
│              Redis Lua 脚本的原子性原理                             │
│                                                                   │
│  为什么用 Lua 脚本?                                                │
│  ┌──────────────────────────────────────────────────────────┐    │
│  │                                                           │    │
│  │  问题: 如果不用 Lua, 需要分步执行:                         │    │
│  │    Step 1: LPOP queues:default → 取出 job                │    │
│  │    Step 2: ZADD queues:default:reserved → 标记执行中     │    │
│  │                                                           │    │
│  │  风险: Worker 在 Step1 和 Step2 之间 crash                │    │
│  │    → Job 已从主队列移除, 但未标记 reserved               │    │
│  │    → Job 丢失!                                            │    │
│  │                                                           │    │
│  │  解决方案: Lua 脚本原子执行                                │    │
│  │    EVAL "lpop+ zadd" → Redis 单线程保证原子性             │    │
│  │    → LPOP 和 ZADD 要么都执行, 要么都不执行                │    │
│  │    → 不会出现"取出了但没标记"的中间状态                   │    │
│  └──────────────────────────────────────────────────────────┘    │
│                                                                   │
│  Redis Lua 原子性保证:                                             │
│  ┌──────────────────────────────────────────────────────────┐    │
│  │  ① Redis 单线程执行命令                                   │    │
│  │  ② EVAL 执行期间, 其他客户端命令排队等待                  │    │
│  │  ③ 整个 Lua 脚本作为一个原子操作执行                      │    │
│  │  ④ 脚本中所有命令要么全成功, 要么脚本某处出错全回滚      │    │
│  │  ⑤ 脚本中不允许有阻塞操作 (如 BLPOP)                     │    │
│  └──────────────────────────────────────────────────────────┘    │
│                                                                   │
│  Laravel 的 EVALSHA 优化:                                          │
│  ┌──────────────────────────────────────────────────────────┘    │
│  │  首次执行: EVAL script 0 (发送完整脚本)                   │    │
│  │  生成 SHA1 摘要: script load → SHA1                       │    │
│  │  后续执行: EVALSHA sha1 0 (只发送 40 字节 SHA1)          │    │
│  │  节省网络带宽, 提高性能                                   │    │
│  │  Redis 重启后 SHA1 失效 → NOSCRIPT 错误 → 自动回退 EVAL  │    │
│  └──────────────────────────────────────────────────────────┘    │
└──────────────────────────────────────────────────────────────────┘
```

### 🔥 高频面试题

**Q1: Laravel Redis 队列中, 如果 Worker 在处理 Job 时 crash 了, 这个 Job 会丢失吗? 为什么?**

> A: 不会丢失。原因在于 Redis 队列的"reserved 机制"：
> ① 弹出 Job 时通过 Lua 脚本原子执行 `LPOP + ZADD reserved`，将 Job 从主队列取出同时存入 reserved ZSet（score=取出的时间戳）；
> ② Worker crash 后 reserved 中的 Job 不会被删除；
> ③ 新的 Worker 循环时，Lua 脚本先检查 `zrangebyscore reserved -inf now`，如果有到期的 reserved job（即前一个 Worker 处理超时），则取出重试；
> ④ 超时判断：Job 的 `retry_after` 配置（默认 90s）vs reserved score。这套机制保证了即使 Worker crash，Job 也能被重新处理。

**Q2: Laravel 的 dispatched/queued 事件和 Job 中间件是如何工作的?**

> A: ① Dispatcher 在 push job 前后触发 `MessageLogged` / `JobQueued` 事件；② 队列中间件（Job Middleware）：Job 类中定义 `middleware()` 方法返回中间件数组，类似 HTTP 中间件但作用于 Job 执行。例如 `new RateLimited('emails')` 限制 throttle。③ 原理：Worker 在执行 Job 前，先将 Job 包装进中间件管道 Pipeline，`$pipeline->send($job)->through($middleware)->then(function($job) { $job->handle(); })`。

---

## 6. Lua 脚本与事务

### 6.1 Redis 事务 (MULTI/EXEC) vs Lua 脚本

```
┌──────────────────────────────────────────────────────────────────┐
│            Redis MULTI/EXEC 事务 vs Lua 脚本 对比                  │
│                                                                   │
│  MULTI/EXEC (传统事务):                                             │
│  ┌──────────────────────────────────────────────────────────┐    │
│  │  MULTI                ← 开启事务                          │    │
│  │  SET key1 value1      ← 命令入队 (不执行)                │    │
│  │  INCR counter          ← 命令入队                         │    │
│  │  EXEC                 ← 批量执行所有入队命令              │    │
│  │                                                           │    │
│  │  特点:                                                    │    │
│  │  ✓ 命令批量执行, 不会被其他客户端打断                     │    │
│  │  ✓ 事务内所有命令按顺序执行                               │    │
│  │  ✗ 不支持条件逻辑 (if/else/for)                          │    │
│  │  ✗ 无法根据前一条命令的结果决定下一条命令                 │    │
│  │  ✗ 事务内错误不会回滚已执行的命令 (语法错全回滚)         │    │
│  └──────────────────────────────────────────────────────────┘    │
│                                                                   │
│  Lua Script (脚本事务):                                            │
│  ┌──────────────────────────────────────────────────────────┐    │
│  │  EVAL "                                                  │    │
│  │      local val = redis.call('GET', KEYS[1])              │    │
│  │      if val > ARGV[1] then                               │    │
│  │          redis.call('DECR', KEYS[1])                     │    │
│  │          return 1                                        │    │
│  │      end                                                  │    │
│  │      return 0                                            │    │
│  │  " 1 mykey 10                                            │    │
│  │                                                           │    │
│  │  特点:                                                    │    │
│  │  ✓ 原子执行 (整个脚本不会被中断)                          │    │
│  │  ✓ 支持复杂条件逻辑 (if/else/for)                        │    │
│  │  ✓ 减少网络往返 (一次 EVAL 替代多次命令)                 │    │
│  │  ✓ 支持根据中间结果做决策                                 │    │
│  │  ✗ 脚本过长会影响 Redis 吞吐 (长时间阻塞命令队列)        │    │
│  └──────────────────────────────────────────────────────────┘    │
└──────────────────────────────────────────────────────────────────┘
```

### 6.2 Laravel Redis 队列中的三步 Lua 原子操作

```
┌──────────────────────────────────────────────────────────────────┐
│            Laravel Redis Queue Lua 脚本三大原子操作                 │
│                                                                   │
│  ① migrateExpiredJobs (迁移到期延迟任务):                          │
│  ┌──────────────────────────────────────────────────────────┐    │
│  │  local val = redis.call('zrangebyscore', KEYS[2],        │    │
│  │      '-inf', ARGV[2], 'LIMIT', 0, ARGV[4])              │    │
│  │  for k, v in pairs(val) do                               │    │
│  │      redis.call('rpush', KEYS[1], v)                     │    │
│  │  end                                                     │    │
│  │  redis.call('zremrangebyscore', KEYS[2], '-inf', ARGV[2])│   │
│  └──────────────────────────────────────────────────────────┘    │
│                                                                   │
│  ② popFromQueue (弹出并标记 reserved):                             │
│  ┌──────────────────────────────────────────────────────────┐    │
│  │  local job = redis.call('lpop', KEYS[1])                 │    │
│  │  redis.call('zadd', KEYS[2], ARGV[1], job)              │    │
│  │  return job                                               │    │
│  │                                                           │    │
│  │  LPOP + ZADD 必须原子: 防止 Worker crash 丢消息           │    │
│  └──────────────────────────────────────────────────────────┘    │
│                                                                   │
│  ③ deleteReserved (完成 Job 后删除):                               │
│  ┌──────────────────────────────────────────────────────────┐    │
│  │  redis.call('zrem', KEYS[1], ARGV[1])                    │    │
│  └──────────────────────────────────────────────────────────┘    │
└──────────────────────────────────────────────────────────────────┘
```

### 6.3 Redis + Laravel 队列中的事务使用场景

```
┌──────────────────────────────────────────────────────────────────┐
│          Laravel Redis 事务实战场景                                 │
│                                                                   │
│  场景 1: 秒杀库存扣减                                              │
│  ┌──────────────────────────────────────────────────────────┐    │
│  │  // 使用 Lua 脚本保证库存检查+扣减原子性                  │    │
│  │  $script = <<<'LUA'                                      │    │
│  │  local stock = redis.call('GET', KEYS[1])                │    │
│  │  if tonumber(stock) <= 0 then                            │    │
│  │      return 0  -- 库存不足                               │    │
│  │  end                                                     │    │
│  │  redis.call('DECR', KEYS[1])                             │    │
│  │  return 1  -- 扣减成功                                   │    │
│  │  LUA;                                                    │    │
│  │                                                           │    │
│  │  Redis::eval($script, 1, 'product:123:stock');           │    │
│  └──────────────────────────────────────────────────────────┘    │
│                                                                   │
│  场景 2: 分布式锁                                                  │
│  ┌──────────────────────────────────────────────────────────┐    │
│  │  $script = <<<'LUA'                                      │    │
│  │  if redis.call('GET', KEYS[1]) == ARGV[1] then           │    │
│  │      return redis.call('DEL', KEYS[1])                   │    │
│  │  else                                                    │    │
│  │      return 0                                            │    │
│  │  end                                                     │    │
│  │  LUA;                                                    │    │
│  │                                                           │    │
│  │  // 释放锁: 只有持有者才能释放, 保证安全                  │    │
│  │  Redis::eval($script, 1, 'lock:order:123', $token);      │    │
│  └──────────────────────────────────────────────────────────┘    │
│                                                                   │
│  场景 3: 队列批量迁移                                              │
│  ┌──────────────────────────────────────────────────────────┐    │
│  │  // 失败 Job 批量重试                                     │    │
│  │  $script = <<<'LUA'                                      │    │
│  │  local failed = redis.call('lrange', KEYS[1], 0, -1)    │    │
│  │  redis.call('del', KEYS[1])                              │    │
│  │  for i, job in pairs(failed) do                          │    │
│  │      redis.call('rpush', KEYS[2], job)                  │    │
│  │  end                                                     │    │
│  │  return #failed                                          │    │
│  │  LUA;                                                    │    │
│  └──────────────────────────────────────────────────────────┘    │
└──────────────────────────────────────────────────────────────────┘
```

### 6.4 Job 的序列化与反序列化

```
┌──────────────────────────────────────────────────────────────────┐
│            Laravel Queue Job 序列化机制                             │
│                                                                   │
│  Job 存储时:                                                       │
│  ┌──────────────────────────────────────────────────────────┐    │
│  │  class SendEmail implements ShouldQueue {                 │    │
│  │      use SerializesModels;  ← 关键 Trait!               │    │
│  │  }                                                        │    │
│  │                                                           │    │
│  │  SerializesModels 的作用:                                  │    │
│  │  ① __sleep(): 将 Eloquent Model 替换为 ModelIdentifier   │    │
│  │     {class: User, id: 42, relations: [], connection:...}  │    │
│  │     不序列化整个 Model! (避免数据过期/stale)              │    │
│  │                                                           │    │
│  │  ② __wakeup(): 从 ModelIdentifier 重新获取数据库中的记录  │    │
│  │     User::findOrFail(42) → 最新数据!                      │    │
│  │                                                           │    │
│  │  ③ 非 Model 属性正常 PHP serialize/unserialize            │    │
│  └──────────────────────────────────────────────────────────┘    │
│                                                                   │
│  Redis 中存储的 Payload:                                           │
│  ┌──────────────────────────────────────────────────────────┐    │
│  │  {                                                        │    │
│  │    "uuid": "a1b2c3-...",                                 │    │
│  │    "displayName": "App\\Jobs\\SendEmail",                 │    │
│  │    "job": "Illuminate\\Queue\\CallQueuedHandler@call",    │    │
│  │    "maxTries": 3,                                         │    │
│  │    "maxExceptions": null,                                 │    │
│  │    "failOnTimeout": false,                                │    │
│  │    "backoff": null,                                       │    │
│  │    "timeout": 60,                                         │    │
│  │    "retryUntil": null,                                    │    │
│  │    "data": {                                              │    │
│  │      "commandName": "App\\Jobs\\SendEmail",              │    │
│  │      "command": "O:23:\"App\\Jobs\\SendEmail\":1:        │    │
│  │          {s:4:\"user\";O:45:\"...ModelIdentifier\":...}"  │    │
│  │    }                                                      │    │
│  │  }                                                        │    │
│  └──────────────────────────────────────────────────────────┘    │
└──────────────────────────────────────────────────────────────────┘
```

### 🔥 高频面试题

**Q1: Laravel Redis 队列中为什么要使用 Lua 脚本？不用会有什么问题？**

> A: 核心原因：需要保证多个 Redis 命令的原子性执行。如果不使用 Lua 脚本分步执行：
> ① `LPOP` 取出 Job → Worker crash → Job 丢失（从主队列移除了但未标记 reserved）；
> ② 延迟任务迁移 `zrangebyscore` + `zrem` + `rpush` 分步执行 → 中间有其他命令插入 → 可能重复迁移或遗漏；
> ③ `EVAL` 保证整个脚本在 Redis 单线程下原子执行，消除了竞态条件。Laravel 还使用 `EVALSHA` 减少网络传输开销，只在脚本未缓存时回退到 `EVAL`。

**Q2: Redis 的 MULTI/EXEC 事务和 Lua 脚本有什么区别？各自适用场景？**

> A: MULTI/EXEC 适合简单的批量命令执行（如 MSET 替代品），不支持条件判断。Lua 脚本适合需要条件逻辑的原子操作（如库存检查后扣减、分布式锁释放前验证持有者）。Laravel 队列选择 Lua 脚本是因为需要"先检查再操作"的逻辑（如延迟任务时间判断、reserved 超时判断），MULTI/EXEC 无法实现这种条件分支。

**Q3: Laravel Job 中为什么使用 SerializesModels Trait？不用的后果？**

> A: `SerializesModels` 在序列化时将 Eloquent Model 替换为 `ModelIdentifier`（只存 class + id），反序列化时重新 `findOrFail(id)` 从数据库获取。优点：① 减少 Redis 中存储的数据大小；② 保证 Job 执行时拿到的是最新数据（而非入队时的过时数据）；③ 如果记录被删除则 Job 失败（finder fail），避免处理已不存在的记录。后果：不使用的话，整个 Model 及其关系被 `serialize()` 存入 Redis，数据量巨大且可能过时。

---

> 本文基于 Laravel 10.x/11.x 源码编写。核心源码路径：
> `Illuminate/Foundation/Application.php` (IoC 容器 + 启动)
> `Illuminate/Foundation/Http/Kernel.php` (请求处理管道)
> `Illuminate/Container/Container.php` (依赖注入实现)
> `Illuminate/Support/Facades/Facade.php` (门面基类)
> `Illuminate/Queue/RedisQueue.php` (Redis 队列 + Lua 脚本)
> `Illuminate/Queue/Worker.php` (Worker 消费者)
> `Illuminate/Contracts/Queue/ShouldQueue.php` (队列 Job 接口)
