# MobileRun TestKit v2.0 设计方案

## 1. 背景与目标

### 1.1 当前问题

mobilerun-testkit v1.0 通过 CLI 方式调用 `mobilerun run ...` 执行测试：

```python
# 当前实现
argv = [MOBILERUN_BIN, "run", case.task]
proc = subprocess.run(argv, capture_output=True, timeout=timeout)
```

**存在的问题：**

1. **批量测试效率低下** - 每个测试用例都需要启动新进程，包含完整的初始化开销
2. **资源浪费** - 无法复用 LLM 连接、设备驱动等资源
3. **控制力不足** - 无法访问中间状态、轨迹数据、事件流
4. **调试困难** - 只能通过退出码和 stdout/stderr 判断结果
5. **扩展性差** - 难以注入自定义工具、状态提供者或钩子

### 1.2 目标

使用 `MobileAgent(goal=..., config=...)` API 重新实现测试框架，实现：

- ✅ **资源复用** - 单次初始化，批量执行多个测试用例
- ✅ **细粒度控制** - 访问执行轨迹、中间状态、事件流
- ✅ **更好的性能** - 避免进程启动开销
- ✅ **可扩展性** - 支持自定义工具、状态提供者、观察者
- ✅ **向后兼容** - 保持现有 YAML 用例格式不变

---

## 2. 架构设计

### 2.1 核心类图

```
┌─────────────────────────────────────────────────────────────┐
│                    TestRunner (主控制器)                      │
│  - 管理设备连接生命周期                                        │
│  - 批量加载和执行测试用例                                      │
│  - 生成报告                                                   │
└─────────────────────────────────────────────────────────────┘
                            │
                            │ 使用
                            ▼
┌─────────────────────────────────────────────────────────────┐
│               MobileAgentExecutor (执行器)                    │
│  - 封装 MobileAgent API                                       │
│  - 管理单个测试用例的执行                                      │
│  - 收集轨迹、事件、截图                                        │
└─────────────────────────────────────────────────────────────┘
                            │
                            │ 使用
                            ▼
┌─────────────────────────────────────────────────────────────┐
│                   MobileAgent (核心)                          │
│  - mobilerun 提供的核心 Agent API                             │
│  - 执行 goal 任务                                             │
└─────────────────────────────────────────────────────────────┘
```

### 2.2 执行流程

```
┌─────────────┐
│ 加载用例     │
│ (YAML)      │
└──────┬──────┘
       │
       ▼
┌─────────────┐
│ 初始化设备   │
│ 和资源      │
└──────┬──────┘
       │
       ▼
┌─────────────────────────────────────────┐
│  批量执行循环 (for each case)            │
│  ┌─────────────────────────────────┐   │
│  │ 1. 检查 requires (前置条件)      │   │
│  │ 2. 执行 setup (shell 命令)       │   │
│  │ 3. 执行 task (MobileAgent)       │   │
│  │ 4. 执行 verify (断言)            │   │
│  │ 5. 执行 cleanup (清理)           │   │
│  └─────────────────────────────────┘   │
└─────────────────────────────────────────┘
       │
       ▼
┌─────────────┐
│ 生成报告     │
│ (JSON/MD)   │
└─────────────┘
```

---

## 3. 详细设计

### 3.1 TestRunner (主控制器)

**职责:**
- 管理整个测试会话的生命周期
- 初始化设备驱动、LLM 配置
- 批量执行测试用例
- 生成报告

**关键方法:**

```python
class TestRunner:
    def __init__(
        self,
        config: MobileConfig,
        device_id: str | None = None,
        llms: dict[str, LLM] | None = None,
    ):
        """初始化 TestRunner
        
        Args:
            config: MobileConfig 配置对象
            device_id: 设备 ID (可选)
            llms: 预加载的 LLM 字典 (可选,用于复用)
        """
        self.config = config
        self.device_id = device_id
        self.llms = llms
        self.driver = None  # 延迟初始化
        self.state_provider = None
        
    async def initialize(self):
        """初始化设备和资源 (异步)"""
        # 初始化设备驱动
        self.driver = await self._create_driver()
        self.state_provider = await self._create_state_provider()
        
        # 预加载 LLMs (如果未提供)
        if self.llms is None:
            self.llms = load_agent_llms(self.config)
    
    async def run_suite(
        self,
        cases: list[TestCase],
        evidence_dir: Path,
    ) -> list[CaseResult]:
        """批量执行测试用例"""
        results = []
        for case in cases:
            result = await self.run_case(case, evidence_dir)
            results.append(result)
        return results
    
    async def run_case(
        self,
        case: TestCase,
        evidence_dir: Path,
    ) -> CaseResult:
        """执行单个测试用例"""
        executor = MobileAgentExecutor(
            driver=self.driver,
            state_provider=self.state_provider,
            config=self.config,
            llms=self.llms,
        )
        return await executor.execute(case, evidence_dir)
    
    async def cleanup(self):
        """清理资源"""
        if self.driver:
            await self.driver.close()
```

### 3.2 MobileAgentExecutor (执行器)

**职责:**
- 封装 `MobileAgent` API
- 处理单个测试用例的执行逻辑
- 收集执行结果、轨迹、事件

**关键方法:**

```python
class MobileAgentExecutor:
    def __init__(
        self,
        driver: DeviceDriver,
        state_provider: StateProvider,
        config: MobileConfig,
        llms: dict[str, LLM],
    ):
        """初始化执行器
        
        Args:
            driver: 设备驱动实例 (复用)
            state_provider: 状态提供者实例 (复用)
            config: MobileConfig 配置
            llms: LLM 字典 (复用)
        """
        self.driver = driver
        self.state_provider = state_provider
        self.config = config
        self.llms = llms
        
    async def execute(
        self,
        case: TestCase,
        evidence_dir: Path,
    ) -> CaseResult:
        """执行测试用例
        
        Returns:
            CaseResult: 包含状态、详情、轨迹等
        """
        result = CaseResult(case=case)
        start = time.monotonic()
        
        try:
            # 1. 检查 requires
            if not await self._check_requires(case):
                result.status = SKIPPED
                result.detail = "requires not met"
                return result
            
            # 2. 执行 setup
            if case.setup:
                ok, err = await self._run_setup(case.setup)
                if not ok:
                    result.status = ERROR
                    result.detail = f"setup failed: {err}"
                    return result
            
            # 3. 执行 task (MobileAgent)
            if case.task:
                task_result = await self._run_task(case)
                result.run_exit_code = 0 if task_result.success else 1
                result.run_seconds = time.monotonic() - start
                result.detail = task_result.detail
                
                # 保存轨迹
                if task_result.trajectory:
                    self._save_trajectory(task_result.trajectory, evidence_dir, case.id)
            
            # 4. 执行 verify
            if case.verify:
                verify_results = await self._run_verify(case.verify, evidence_dir)
                result.verify_results = verify_results
            
            # 5. 判定总体状态
            result.status = self._determine_status(result, case)
            
        finally:
            # 6. 执行 cleanup (总是执行)
            if case.cleanup:
                await self._run_cleanup(case.cleanup)
            
            result.run_seconds = time.monotonic() - start
        
        return result
    
    async def _run_task(self, case: TestCase) -> TaskResult:
        """使用 MobileAgent 执行 task"""
        # 合并用例级别的 run_flags 到 config
        task_config = self._merge_run_flags(self.config, case.run_flags)
        
        # 创建 MobileAgent 实例
        agent = MobileAgent(
            goal=case.task,
            config=task_config,
            llms=self.llms,  # 复用 LLMs
            driver=self.driver,  # 复用驱动
            state_provider=self.state_provider,  # 复用状态提供者
            timeout=case.timeout,
        )
        
        # 收集事件和轨迹
        events = []
        trajectory = []
        
        # 注册事件监听器
        def on_event(event):
            events.append(event)
            if isinstance(event, ResultEvent):
                trajectory.append(event.to_dict())
        
        # 执行
        try:
            result = await agent.run(start_event=StartEvent())
            
            # 从 result 提取信息
            success = isinstance(result, StopEvent) and not result.error
            detail = self._extract_detail(result, events)
            
            return TaskResult(
                success=success,
                detail=detail,
                events=events,
                trajectory=trajectory,
            )
        except Exception as e:
            return TaskResult(
                success=False,
                detail=f"agent error: {str(e)}",
                events=events,
                trajectory=trajectory,
            )
```

### 3.3 数据结构

```python
@dataclass
class TaskResult:
    """MobileAgent 执行结果"""
    success: bool
    detail: str
    events: list  # 事件流
    trajectory: list  # 轨迹数据
    error: Exception | None = None

@dataclass
class CaseResult:
    """测试用例结果 (扩展现有结构)"""
    case: TestCase
    status: str = "SKIPPED"
    detail: str = ""
    run_exit_code: int | None = None
    run_seconds: float = 0.0
    run_timed_out: bool = False
    verify_results: list[dict] = field(default_factory=list)
    ai_judge_images: list[str] = field(default_factory=list)
    attempts: list[dict] = field(default_factory=list)
    
    # 新增字段
    trajectory_path: str | None = None  # 轨迹文件路径
    events: list = field(default_factory=list)  # 事件列表
```

---

## 4. 配置映射

### 4.1 run_flags 到 MobileConfig 的映射

YAML 用例中的 `run_flags` 需要映射到 `MobileConfig`:

```python
def merge_run_flags(base_config: MobileConfig, run_flags: dict) -> MobileConfig:
    """将 run_flags 合并到 MobileConfig"""
    config = base_config.model_copy(deep=True)
    
    # 映射表
    mapping = {
        "provider": lambda v: setattr(config.agent, "provider", v),
        "model": lambda v: setattr(config.agent, "model", v),
        "steps": lambda v: setattr(config.agent, "max_steps", int(v)),
        "vision": lambda v: setattr(config.agent, "vision_mode", "vision" if v else "text"),
        "vision_only": lambda v: setattr(config.agent, "vision_only", bool(v)),
        "reasoning": lambda v: setattr(config.agent, "reasoning", bool(v)),
        "stream": lambda v: setattr(config.agent, "stream", bool(v)),
        "tracing": lambda v: setattr(config.tracing, "enabled", bool(v)),
        "debug": lambda v: setattr(config.logging, "debug", bool(v)),
        "tcp": lambda v: setattr(config.device, "use_tcp", bool(v)),
        "ios": lambda v: setattr(config.device, "platform", "ios" if v else "android"),
        "temperature": lambda v: setattr(config.agent, "temperature", float(v)),
        "save_trajectory": lambda v: setattr(config.agent, "save_trajectory", v),
        "control_backend": lambda v: setattr(config.device, "control_backend", v),
        "device_id": lambda v: setattr(config.device, "device_id", v),
    }
    
    for key, value in run_flags.items():
        if key in mapping:
            mapping[key](value)
    
    return config
```

### 4.2 配置示例

```python
# 基础配置
base_config = MobileConfig(
    agent=AgentConfig(
        provider="anthropic",
        model="claude-3-5-sonnet-20241022",
        vision_mode="vision",
        reasoning=False,
        max_steps=15,
    ),
    device=DeviceConfig(
        device_id="emulator-5554",
        platform="android",
    ),
    tools=ToolsConfig(),
    logging=LoggingConfig(debug=False),
    tracing=TracingConfig(enabled=False),
)

# 用例级别覆盖
case_config = merge_run_flags(base_config, {
    "vision": False,
    "steps": 20,
    "reasoning": True,
})
```

---

## 5. 关键优化

### 5.1 资源复用

**问题:** 每个测试用例都创建新的 `MobileAgent` 会导致重复初始化。

**解决方案:**

```python
class TestRunner:
    async def initialize(self):
        """一次性初始化共享资源"""
        # 1. 初始化设备驱动 (复用)
        self.driver = await self._create_driver()
        
        # 2. 初始化状态提供者 (复用)
        self.state_provider = AndroidStateProvider(self.driver)
        
        # 3. 预加载 LLMs (复用)
        self.llms = load_agent_llms(self.config)
        
        # 4. 初始化 MCP 客户端 (复用)
        if self.config.mcp.servers:
            self.mcp_manager = MCPClientManager(self.config.mcp)
            await self.mcp_manager.connect_all()
    
    async def run_case(self, case: TestCase, evidence_dir: Path):
        """每个用例注入共享资源"""
        agent = MobileAgent(
            goal=case.task,
            config=self.config,
            llms=self.llms,           # ✅ 复用
            driver=self.driver,         # ✅ 复用
            state_provider=self.state_provider,  # ✅ 复用
        )
        result = await agent.run()
        return result
```

**预期收益:**
- 🚀 减少 80%+ 的初始化时间
- 💰 降低 LLM API 延迟 (复用连接)
- 📉 减少设备驱动重连开销

### 5.2 并行执行 (可选)

对于独立的测试用例，可以并行执行：

```python
async def run_suite_parallel(
    self,
    cases: list[TestCase],
    evidence_dir: Path,
    max_concurrency: int = 3,
) -> list[CaseResult]:
    """并行执行测试用例 (需要多设备或设备池)"""
    semaphore = asyncio.Semaphore(max_concurrency)
    
    async def run_with_semaphore(case):
        async with semaphore:
            return await self.run_case(case, evidence_dir)
    
    tasks = [run_with_semaphore(case) for case in cases]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    return results
```

### 5.3 事件流采集

通过订阅 `MobileAgent` 的事件流，可以获得更细粒度的执行信息：

```python
class EventCollector:
    """收集 MobileAgent 执行过程中的事件"""
    
    def __init__(self):
        self.events = []
        self.screenshots = []
        self.actions = []
    
    def on_event(self, event):
        """事件回调"""
        self.events.append(event)
        
        if isinstance(event, ScreenshotEvent):
            self.screenshots.append(event.screenshot_path)
        elif isinstance(event, ResultEvent):
            self.actions.append({
                "action": event.action,
                "result": event.result,
                "timestamp": time.time(),
            })

# 使用
collector = EventCollector()
agent = MobileAgent(goal=case.task, config=config)
agent.register_event_handler(collector.on_event)
result = await agent.run()
```

---

## 6. 向后兼容性

### 6.1 保持 YAML 格式不变

✅ 现有的 YAML 用例格式**完全兼容**，无需修改。

### 6.2 保持 CLI 接口不变

```bash
# 用户命令保持不变
mobilerun-test --suite smoke --device emulator-5554

# 内部实现从 CLI 切换到 MobileAgent API
```

### 6.3 保持报告格式不变

- `report.json` 和 `report.md` 格式保持不变
- 新增字段向后兼容 (例如 `trajectory_path`)

---

## 7. 实施计划

### 阶段 1: 核心重构 (1-2 周)

- [ ] 实现 `TestRunner` 类
- [ ] 实现 `MobileAgentExecutor` 类
- [ ] 实现 `run_flags` 到 `MobileConfig` 的映射
- [ ] 实现资源复用逻辑

### 阶段 2: 功能完善 (1 周)

- [ ] 支持 `repeat` (重复执行)
- [ ] 支持 `requires` (前置条件检查)
- [ ] 支持 `capture` (变量捕获和插值)
- [ ] 支持 `known_limits` (已知限制匹配)

### 阶段 3: 验证与测试 (1 周)

- [ ] 使用现有 smoke 套件验证
- [ ] 性能对比测试 (v1 vs v2)
- [ ] 回归测试

### 阶段 4: 文档与发布 (3 天)

- [ ] 更新 README
- [ ] 编写迁移指南
- [ ] 发布 v2.0.0

---

## 8. 风险与挑战

### 8.1 异步化改造

**风险:** 现有的 v1.0 是同步代码，v2.0 需要全面异步化。

**缓解措施:**
- 提供 `asyncio.run()` 包装器用于同步调用
- 保持 CLI 入口点同步

### 8.2 设备状态管理

**风险:** 批量执行时，前一个用例可能影响后续用例 (未清理干净)。

**缓解措施:**
- 强制执行 `cleanup` 逻辑
- 每个用例前执行设备状态重置 (可选)
- 提供 `--isolate` 选项 (完全隔离执行)

### 8.3 LLM 配额管理

**风险:** 批量执行可能触发 API 限流。

**缓解措施:**
- 实现重试逻辑 (带指数退避)
- 提供 `--rate-limit` 选项
- 监控 API 使用量

---

## 9. 性能预期

### 9.1 基准对比

| 指标 | v1.0 (CLI) | v2.0 (API) | 改善 |
|------|-----------|-----------|------|
| 单用例初始化时间 | ~5-8s | ~0.1-0.3s | **95%+** |
| 10 用例总耗时 | ~600s | ~120s | **80%** |
| 内存占用 | 10x 进程 | 1x 进程 | **90%** |
| 轨迹数据完整性 | 部分 | 完整 | ✅ |

### 9.2 可扩展性

- ✅ 支持自定义工具注入
- ✅ 支持自定义状态提供者
- ✅ 支持事件流订阅
- ✅ 支持并行执行 (多设备)

---

## 10. 参考资料

### 10.1 相关文件

- `mobilerun/agent/droid/droid_agent.py` - MobileAgent 实现
- `mobilerun/config_manager/config_manager.py` - MobileConfig 定义
- `mobilerun-testkit/src/mobilerun_testkit/runner.py` - v1.0 runner 实现
- `mobilerun-testkit/src/mobilerun_testkit/_lib.py` - 数据模型定义

### 10.2 API 示例

```python
from mobilerun.agent import MobileAgent
from mobilerun.config_manager import MobileConfig, AgentConfig, DeviceConfig

# 基础用法
agent = MobileAgent(
    goal="打开设置应用",
    config=MobileConfig(
        agent=AgentConfig(provider="anthropic", model="claude-3-5-sonnet-20241022"),
        device=DeviceConfig(device_id="emulator-5554"),
    ),
)
result = await agent.run()

# 高级用法 (资源复用)
config = MobileConfig(...)
llms = load_agent_llms(config)
driver = await create_driver(config)

agent1 = MobileAgent(goal="task 1", config=config, llms=llms, driver=driver)
result1 = await agent1.run()

agent2 = MobileAgent(goal="task 2", config=config, llms=llms, driver=driver)
result2 = await agent2.run()
```

---

## 11. 总结

通过使用 `MobileAgent` API 重构测试框架，我们可以实现：

1. **🚀 显著的性能提升** - 通过资源复用减少初始化开销
2. **🔍 更细粒度的控制** - 访问事件流、轨迹、中间状态
3. **🛠️ 更好的可扩展性** - 支持自定义工具、观察者、钩子
4. **✅ 完全向后兼容** - 现有用例和 CLI 无需修改

这是一次架构升级，为未来的功能扩展 (并行执行、实时监控、智能重试等) 奠定了基础。
