# MobileRun 自动化测试框架重新设计方案

> 版本: v3.0 | 日期: 2026-09-02 | 基于文档: 11.docx / 22.docx / 33.docx / 44.docx

---

## 1. 设计背景与问题分析

### 1.1 三个文档揭示的核心原则

从 11.docx、22.docx、33.docx 提炼出以下核心原则，它们是本设计的基础约束：

| 原则 | 来源 | 具体含义 |
|------|------|---------|
| Agent Action + Deterministic Assertion | 11.docx | AI 负责找到并执行 UI 操作，断言由确定性代码完成 |
| 一个 Test Case = 一个 Agent Task | 22.docx | 5 步测试用例合并为一个 goal 传入，不是 5 次 API 调用 |
| Test Case Step ≠ Mobilerun Execution Step | 22.docx | 测试步骤描述意图，Agent 内部自行产生更多实际动作 |
| Python API 而非 CLI | 33.docx | 正式框架使用 `MobileAgent(goal=..., config=...)` 而不是 `os.system()` |
| App Card 在 reasoning 模式下生效 | 44.docx | App Card 需配合 `--reasoning` 才参与 Manager planning |

### 1.2 现有实现的不足（v1.0 CLI 模式）

```
当前 v1.0 问题：
  每条用例 → subprocess.run("mobilerun run ...") → 全新进程
                                                       ↑
  ① 进程冷启动 5–8s × N 用例 = 浪费                    │
  ② 上下文断裂：每步都重新规划                          │
  ③ 只能拿 exit code + stdout，没有轨迹/事件            │
  ④ 无法复用 LLM 连接、驱动、App Card 缓存             │
  ⑤ CI 上 10 个用例 = 10 次驱动初始化                  │
```

### 1.3 目标

- 切换到 `MobileAgent` Python API（33.docx 明确推荐）
- 实现驱动/LLM 跨用例复用
- 支持 App Card local 模式（44.docx）
- 保持 YAML 用例格式 100% 向后兼容
- 提供 Test Case Compiler 层（22.docx 推荐）

---

## 2. 整体架构

```
┌──────────────────────────────────────────────────────────────────┐
│                       Test Repository                            │
│                                                                  │
│  cases/smoke/*.yaml          cases/full/*.yaml                   │
│  App Cards: config/app_cards/                                    │
└────────────────────────────┬─────────────────────────────────────┘
                             │ load_cases()
                             ▼
┌──────────────────────────────────────────────────────────────────┐
│                    Test Case Compiler                            │
│                                                                  │
│  YAML TestCase  →  Agent Goal String                            │
│  run_flags      →  MobileConfig overrides                       │
│  fixture/setup  →  pre-task shell commands                      │
│  assertions     →  post-task Validator calls                    │
└────────────────────────────┬─────────────────────────────────────┘
                             │ compile()
                             ▼
┌──────────────────────────────────────────────────────────────────┐
│                       TestRunner (v3)                            │
│                                                                  │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │  SharedResources (单次初始化，所有用例复用)               │    │
│  │  • AndroidDriver / IOSDriver                            │    │
│  │  • AndroidStateProvider                                 │    │
│  │  • LLMs dict {manager, executor, fast_agent, ...}      │    │
│  │  • App Card (local mode, config/app_cards/)             │    │
│  │  • MCPClientManager (if configured)                     │    │
│  └─────────────────────────────────────────────────────────┘    │
│                             │                                    │
│         for each TestCase   │                                    │
│                             ▼                                    │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │  CaseExecutor                                           │    │
│  │                                                         │    │
│  │  1. requires 检查 (shell)                               │    │
│  │  2. setup 执行 (shell)                                  │    │
│  │  3. task → MobileAgent.run(goal)  ← 核心               │    │
│  │  4. verify → Validator            ← 确定性断言          │    │
│  │  5. cleanup (shell, always)                             │    │
│  └─────────────────────────────────────────────────────────┘    │
│                             │                                    │
│                             ▼                                    │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │  ReportWriter  →  report.json / report.md / evidence/  │    │
│  └─────────────────────────────────────────────────────────┘    │
└──────────────────────────────────────────────────────────────────┘
                             │
                             ▼
┌──────────────────────────────────────────────────────────────────┐
│                    MobileAgent (mobilerun 核心)                   │
│                                                                  │
│  reasoning=False:  FastAgent                                     │
│  reasoning=True:   Manager (规划) → Executor (执行)             │
│                    ↑ App Card 在此处生效                         │
│                                                                  │
│  输入: goal (string, 合并的自然语言任务)                          │
│  输出: ResultEvent { success, reason, steps }                    │
│  副产物: trajectory.json, screenshots, events stream             │
└──────────────────────────────────────────────────────────────────┘
                             │
                             ▼
                    Android / iOS Device
```

---

## 3. 核心设计决策

### 3.1 Test Case Compiler：YAML → Agent Goal

来自 22.docx 的关键洞察：测试用例 YAML 不是直接给 LLM 的 Prompt，需要一个编译层。

```
输入 YAML:                          编译后 Agent Goal:
─────────────────────────────       ──────────────────────────────────────
id: LIVE_CHAT_001                   "请完成以下测试任务：
title: 直播间发送评论                 
test_data:                           背景信息：
  message: "Hello"                   - message = "Hello"
steps:                               
  - 打开直播 Tab                     步骤：
  - 进入任意直播间                    1. 打开直播 Tab
  - 打开评论输入框                    2. 进入任意一个正在直播的直播间
  - 输入消息                         3. 打开评论输入框
  - 发送评论                         4. 输入 "Hello"
                                     5. 发送评论
                                     
                                     完成后停止，不要自行判断是否成功。"
```

编译器不使用 LLM，是纯 Python 字符串拼接：

```python
class TestCaseCompiler:
    def compile_goal(self, case: TestCase) -> str:
        """将 TestCase 编译为 Agent Goal 字符串。"""
        parts = ["请完成以下测试任务："]
        
        # 注入 test_data（如果有）
        if case.test_data:
            parts.append("\n背景信息：")
            for k, v in case.test_data.items():
                parts.append(f"- {k} = {v!r}")
        
        # 注入步骤（自然语言，不加坐标）
        if case.steps:
            parts.append("\n步骤：")
            for i, step in enumerate(case.steps, 1):
                parts.append(f"{i}. {step}")
        elif case.task:
            # 兼容旧格式：task 字段直接使用
            parts.append(f"\n任务：{case.task}")
        
        parts.append("\n完成后停止，不要自行判断是否成功。")
        return "\n".join(parts)
```

**关键原则（来自 22.docx）：**
- 步骤描述意图（"进入直播间"），不描述坐标（"click(100, 200)"）
- 整个测试用例的所有步骤合并为一个 goal，**不做 N 次 agent.run()**
- test_data 注入到 goal 上下文，让 Agent 在执行时使用

### 3.2 Agent Action + Deterministic Assertion（来自 11.docx）

```
               ┌─────────────────────────────┐
               │  MobileAgent.run(goal)       │
               │                             │
               │  "进入直播间并发送 Hello"    │
               │                             │
               │  Agent 自行决定：           │
               │  → observe screen           │
               │  → find live tab            │
               │  → tap                      │
               │  → observe                  │
               │  → find room card           │
               │  → tap                      │
               │  → find chat input          │
               │  → type "Hello"             │
               │  → tap send                 │
               └──────────────┬──────────────┘
                              │
                              │ ResultEvent{success, reason}
                              │  ↑ 不信这里的 success！
                              ▼
               ┌─────────────────────────────┐
               │      Deterministic          │
               │       Assertion             │
               │                             │
               │  mobilerun device ui        │
               │  → 检查 a11y tree           │
               │  → 确认 "Hello" 存在        │
               │                             │
               │  截图存证                    │
               └─────────────────────────────┘
```

**永远不信 Agent 自己说的"完成了"**，断言由独立的确定性命令完成（与 v1.0 保持一致）。

### 3.3 资源复用策略

```python
class SharedResources:
    """跨所有用例共享的资源，单次初始化。"""
    
    driver: DeviceDriver          # AndroidDriver / IOSDriver
    state_provider: StateProvider # AndroidStateProvider
    llms: dict[str, LLM]          # {manager, executor, fast_agent, ...}
    config: MobileConfig          # 基础配置
    
    async def initialize(self, config: MobileConfig, device_id: str | None):
        """一次性初始化，所有用例共用。"""
        # 1. 建立设备连接
        self.driver = await _create_driver(config, device_id)
        
        # 2. 初始化状态提供者
        self.state_provider = AndroidStateProvider(
            self.driver,
            tree_filter=ConciseFilter(),
            tree_formatter=IndexedFormatter(),
        )
        
        # 3. 预加载 LLMs（避免每个用例重新加载）
        self.llms = load_agent_llms(config)
        
        # 4. MCP 客户端（如有配置）
        if config.mcp and config.mcp.enabled:
            self.mcp_manager = MCPClientManager(config.mcp)
            await self.mcp_manager.connect_all()
    
    async def close(self):
        await self.driver.disconnect()
        if self.mcp_manager:
            await self.mcp_manager.disconnect_all()
```

每个用例的 `MobileAgent` 实例通过 `driver=` 和 `state_provider=` 注入共享资源，避免重复初始化：

```python
agent = MobileAgent(
    goal=compiled_goal,
    config=case_config,          # 用例级覆盖
    llms=shared.llms,            # ✅ 复用
    driver=shared.driver,        # ✅ 复用
    state_provider=shared.state_provider,  # ✅ 复用
    timeout=case.timeout,
)
```

---

## 4. YAML 用例格式扩展（向后兼容）

现有 v1.0 的 YAML 格式**完全保留**，增加可选的新字段：

```yaml
id: LIVE_CHAT_001
title: 直播间发送公屏评论
priority: smoke                  # smoke | full

# ── 前置条件 ──────────────────────────────────────────────────
preconditions:
  - 用户已登录
  - 推荐直播间存在

requires:                        # 机器可检查的前置条件
  - cmd: "mobilerun device ui"
    expect_contains: ["com.mf.plus"]
    description: "App 已在前台"

# ── 准备 ──────────────────────────────────────────────────────
setup: |
  mobilerun device press home
  mobilerun macro replay login --dry-run

# ── 测试数据（新增，由 Compiler 注入到 Agent Goal）─────────────
test_data:                       # ← 新字段，可选
  message: "Hello Mobilerun"
  username: "test_user_01"

# ── 任务步骤（新增，替代或补充 task 字段）─────────────────────
steps:                           # ← 新字段，推荐使用
  - 打开直播 Tab
  - 进入任意一个正在直播的直播间
  - 打开评论输入框
  - 输入消息
  - 发送评论

# ── 兼容旧格式：task 字段仍然支持 ─────────────────────────────
# task: "打开直播间并发送 Hello"   # 与 steps 二选一或共存

# ── Agent 执行参数 ─────────────────────────────────────────────
run_flags:
  vision: true
  reasoning: true               # App Card 需要此项
  steps: 20

# ── 确定性断言（不信 Agent 自评）────────────────────────────────
verify:
  - cmd: "mobilerun device ui"
    expect_contains: ["Hello Mobilerun"]
    description: "评论出现在公屏"
  - cmd: "mobilerun device screenshot"
    save_to: live-chat-evidence.png
  - judge: ai_vision
    description: "截图显示评论 Hello Mobilerun 出现在公屏"

timeout: 600
pass_criteria: "评论 Hello Mobilerun 出现在公屏 a11y tree 中"

cleanup: |
  mobilerun device press back
  mobilerun device press home

known_limits:
  pattern: "chat input not found"
  reason: "部分直播间关闭了评论，已知限制"
```

### 新字段说明

| 字段 | 类型 | 用途 |
|------|------|------|
| `test_data` | dict | 键值对，由 Compiler 注入到 Agent Goal 的上下文 |
| `steps` | list[str] | 自然语言步骤列表，Compiler 拼接为一个 goal |

`steps` 与 `task` 同时存在时，优先用 `steps`（Compiler 展开）；仅有 `task` 时保留原有行为。

---

## 5. App Card 集成（来自 44.docx）

### 5.1 目录结构

```
<project>/
└── config/
    └── app_cards/
        ├── app_cards.json          # package → markdown 映射
        ├── novialive.md            # 主 App Card
        └── partner/
            └── gift.md            # 子功能 Card
```

### 5.2 app_cards.json

```json
{
  "com.mf.plus": "novialive.md",
  "com.mf.plus.partner": "partner/gift.md"
}
```

### 5.3 config.yaml 中启用

```yaml
agent:
  app_cards:
    enabled: true
    mode: local                 # local | server | composite
    app_cards_dir: config/app_cards
```

### 5.4 关键注意事项（来自 44.docx）

> **App Card 只在 `reasoning=True` + Manager 模式下生效。**
> 
> 因此，用到 App Card 的用例**必须**在 `run_flags` 中设置 `reasoning: true`，否则 App Card 不会参与规划。

```yaml
# App Card 用例的 run_flags 必须包含：
run_flags:
  reasoning: true
  vision: true
  steps: 20
```

### 5.5 App Card 模板（novialive.md 参考）

```markdown
# NoviaLive App Guide

## Overview
NoviaLive 是直播平台，用户可以：
- 观看直播
- 发送公屏评论
- 发送虚拟礼物
- 参与 PK

## Main Navigation
主页面包含：Home / Live / Following
Live Tab 打开直播推荐流。

## Live Room
直播间常见操作：Follow / Chat / Gift / Share / PK / Mic

## Public Chat
发送公屏评论步骤：
1. 打开评论输入框
2. 输入消息
3. 点击发送

评论输入框初始可能不可见，需要点击底部区域展开。

## Important Rules
- 不要依赖固定坐标
- 优先使用可见文字和 a11y 语义
- 直播间控件可能被隐藏
- 礼物面板可能以底部弹出形式出现
- 不要假设每个直播间都有相同的控件
```

---

## 6. 详细实现设计

### 6.1 TestRunner v3 主流程

```python
class TestRunnerV3:
    """
    使用 MobileAgent Python API 的测试运行器。
    
    与 v1.0 的关键区别：
    - 资源（Driver、LLM）跨用例复用
    - task 通过 TestCaseCompiler 转换为 Agent Goal
    - MobileAgent 实例注入共享驱动，不重新建立连接
    """
    
    def __init__(
        self,
        config: MobileConfig,
        device_id: str | None = None,
        cases_dir: Path = None,
        report_dir: Path = None,
    ):
        self.config = config
        self.device_id = device_id
        self.cases_dir = cases_dir
        self.report_dir = report_dir or Path.cwd() / "mobilerun-testkit-reports"
        self.shared: SharedResources | None = None
        self.compiler = TestCaseCompiler()
    
    async def run_suite(self, suite: str, only: list[str] = None) -> int:
        """运行完整套件，返回 exit code（0=全过，1=有失败）。"""
        cases = load_cases(self.cases_dir, suite)
        if only:
            cases = [c for c in cases if c.id in set(only)]
        
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        report_dir = self.report_dir / f"{stamp}_{suite}"
        report_dir.mkdir(parents=True, exist_ok=True)
        evidence_dir = report_dir / "evidence"
        evidence_dir.mkdir()
        writer = ReportWriter(report_dir, suite)
        
        # 单次初始化共享资源
        self.shared = SharedResources()
        await self.shared.initialize(self.config, self.device_id)
        
        try:
            for case in cases:
                result = await self._run_case(case, evidence_dir)
                writer.add(result)
        finally:
            await self.shared.close()
        
        # 统计
        failing = sum(1 for r in writer.results if r.status in {"FAIL", "ERROR"})
        return 1 if failing else 0
    
    async def _run_case(
        self,
        case: TestCase,
        evidence_dir: Path,
    ) -> CaseResult:
        """执行单个用例（requires → setup → task → verify → cleanup）。"""
        executor = CaseExecutor(
            shared=self.shared,
            compiler=self.compiler,
        )
        return await executor.execute(case, evidence_dir)
```

### 6.2 CaseExecutor 执行流

```python
class CaseExecutor:
    """单个用例的执行逻辑。"""
    
    async def execute(self, case: TestCase, evidence_dir: Path) -> CaseResult:
        result = CaseResult(case=case)
        start = time.monotonic()
        
        try:
            # ── 1. requires 检查 ────────────────────────────────────
            if case.requires:
                for item in case.requires:
                    met, detail = await self._check_requires(item)
                    if not met:
                        result.status = SKIPPED
                        result.detail = f"requires not met: {detail}"
                        return result
            
            # ── 2. setup ─────────────────────────────────────────────
            if case.setup:
                ok, err = self._run_shell(case.setup.splitlines(), timeout_each=120)
                if not ok:
                    result.status = ERROR
                    result.detail = f"setup failed: {err}"
                    return result
            
            # ── 3. task（MobileAgent API）────────────────────────────
            if case.task or case.steps:
                goal = self.compiler.compile_goal(case)
                case_config = self._merge_run_flags(self.shared.config, case.run_flags)
                
                agent = MobileAgent(
                    goal=goal,
                    config=case_config,
                    llms=self.shared.llms,             # 复用
                    driver=self.shared.driver,          # 复用
                    state_provider=self.shared.state_provider,  # 复用
                    timeout=case.timeout,
                )
                
                handler = agent.run(StartEvent())
                
                # 收集事件（供 evidence 使用）
                events = []
                async for ev in handler.stream_events():
                    events.append(ev)
                
                agent_result: ResultEvent = await handler
                result.run_exit_code = 0 if agent_result.success else 1
                result.detail = agent_result.reason[:300]
                result.agent_steps = agent_result.steps
                
                # 保存轨迹路径（如有）
                if agent.trajectory and agent.trajectory.trajectory_folder:
                    result.trajectory_path = str(agent.trajectory.trajectory_folder)
            
            # ── 4. verify（确定性断言，永远不信 Agent 自评）──────────
            captures: dict[str, str] = {}
            statuses: list[str] = []
            for idx, item in enumerate(case.verify, 1):
                vr = await self._run_verify_item(
                    item, idx, case.id, evidence_dir, captures
                )
                result.verify_results.append(vr)
                statuses.append(vr.get("status", FAIL))
            
            # ── 5. 判定总状态 ─────────────────────────────────────────
            result.status = self._determine_status(result, statuses)
            
            # known_limits 降级
            if result.status in {FAIL, ERROR} and case.known_limits:
                haystack = result.detail + " ".join(
                    str(v.get("detail", "")) for v in result.verify_results
                )
                if case.known_limits.matches(haystack):
                    result.status = EXPECTED
                    result.detail = f"known limit: {case.known_limits.describe()} | {result.detail}"
        
        finally:
            # ── 6. cleanup（始终执行）────────────────────────────────
            if case.cleanup:
                ok, err = self._run_shell(case.cleanup.splitlines(), timeout_each=300)
                if not ok:
                    print(f"  ⚠️ Cleanup failed: {err}")
            result.run_seconds = round(time.monotonic() - start, 1)
        
        return result
```

### 6.3 run_flags → MobileConfig 映射

```python
def merge_run_flags(base_config: MobileConfig, run_flags: dict) -> MobileConfig:
    """将 YAML run_flags 合并到 MobileConfig 副本。"""
    config = base_config.model_copy(deep=True)
    
    for key, value in run_flags.items():
        if key == "steps":
            config.agent.max_steps = int(value)
        elif key == "vision":
            v = bool(value)
            config.agent.manager.vision = v
            config.agent.executor.vision = v
            config.agent.fast_agent.vision = v
        elif key == "vision_only":
            config.agent.vision_only = bool(value)
        elif key == "reasoning":
            config.agent.reasoning = bool(value)
        elif key == "provider":
            config.agent.provider = str(value)
        elif key == "model":
            config.agent.model = str(value)
        elif key == "temperature":
            config.agent.temperature = float(value)
        elif key == "stream":
            config.agent.streaming = bool(value)
        elif key == "tracing":
            config.tracing.enabled = bool(value)
        elif key == "debug":
            config.logging.debug = bool(value)
        elif key == "ios":
            if bool(value):
                config.device.platform = "ios"
        elif key == "tcp":
            config.device.use_tcp = bool(value)
        elif key == "save_trajectory":
            config.logging.save_trajectory = str(value)
        elif key == "control_backend":
            config.device.control_backend = str(value)
        elif key == "device_id":
            config.device.device_id = str(value)
    
    return config
```

---

## 7. 扩展的 CaseResult 数据模型

```python
@dataclass
class CaseResult:
    """测试用例结果（v3 扩展）。"""
    
    case: TestCase
    status: str = "SKIPPED"
    detail: str = ""
    run_exit_code: int | None = None
    run_seconds: float = 0.0
    run_timed_out: bool = False
    verify_results: list[dict] = field(default_factory=list)
    ai_judge_images: list[str] = field(default_factory=list)
    attempts: list[dict] = field(default_factory=list)
    
    # v3 新增
    agent_steps: int = 0               # MobileAgent 实际执行步数
    trajectory_path: str | None = None # 轨迹目录路径
    compiled_goal: str = ""            # Compiler 生成的 goal（便于调试）
```

---

## 8. CLI 接口（向后兼容）

```bash
# 完全兼容 v1.0 命令
mobilerun-test --suite smoke --device emulator-5554
mobilerun-test --suite full --device emulator-5554
mobilerun-test --suite all --only LIVE_CHAT_001

# v3 新增选项
mobilerun-test --suite smoke --api-mode      # 强制使用 Python API（默认）
mobilerun-test --suite smoke --cli-mode      # 降级回 v1.0 CLI 模式（调试用）
mobilerun-test --suite smoke --show-goals    # 打印 Compiler 输出的 goal，不执行
```

`--show-goals` 是调试利器：可以在不连设备的情况下检查 Compiler 是否正确把 YAML 转换为 Agent Goal。

---

## 9. 实施计划

### 阶段 1：TestCaseCompiler + 新字段支持（3 天）

- [ ] 在 `_lib.py` 中添加 `test_data`、`steps` 字段到 `TestCase`
- [ ] 实现 `TestCaseCompiler.compile_goal()` 纯 Python 逻辑
- [ ] 为 `steps`/`test_data` 添加 YAML 验证
- [ ] 单元测试：各种 YAML 组合 → 正确的 goal 字符串

### 阶段 2：SharedResources + MobileAgent 集成（1 周）

- [ ] 实现 `SharedResources` 类（driver/LLM 复用）
- [ ] 实现 `CaseExecutor`（替换 `_execute_once`）
- [ ] 实现 `merge_run_flags()` MobileConfig 映射
- [ ] 集成测试：单条用例走通 API 路径

### 阶段 3：TestRunner v3 主控制器（3 天）

- [ ] 实现 `TestRunnerV3` 套件执行流
- [ ] 更新 `main()` CLI 入口，保持参数兼容
- [ ] 添加 `--cli-mode` 降级开关（保留 v1.0 作为 fallback）

### 阶段 4：App Card 集成（2 天）

- [ ] 验证 `config/app_cards/` 结构在 MobileConfig 中正确加载
- [ ] 为 novialive 编写 App Card 模板
- [ ] 添加 `app-card-novialive` 全套用例（full 套件）

### 阶段 5：验证与文档（3 天）

- [ ] 使用现有 smoke 套件对比 v1.0 vs v3 结果
- [ ] 性能基准测试（初始化时间、总耗时）
- [ ] 更新 README、CASE-FIELDS.md
- [ ] 迁移指南（主要变化：`steps` 字段用法）

---

## 10. 风险与缓解

| 风险 | 可能性 | 影响 | 缓解措施 |
|------|--------|------|---------|
| MobileAgent 内部 API 变更 | 中 | 高 | 保留 `--cli-mode` fallback，隔离在 `CaseExecutor._run_task()` |
| 驱动跨用例状态污染 | 中 | 中 | `cleanup` 严格执行；提供 `--isolate` 选项重置驱动 |
| LLM 限流（批量执行） | 中 | 中 | `--rate-limit <rps>` 选项；`known_limits` 匹配限流错误 |
| App Card 未加载（忘记 reasoning） | 高 | 低 | Compiler 检测：`reasoning=True` 时才追加 App Card 提示 |
| reasoning 模式速度慢 | 高 | 低 | 文档注明；`--suite smoke` 默认不开 reasoning |

---

## 11. 性能预期

| 指标 | v1.0（CLI 子进程） | v3.0（Python API 资源复用） | 提升 |
|------|-------------------|----------------------------|------|
| 单用例驱动初始化 | ~5–8s | ~0.1s（复用） | **97%** |
| 10 用例总驱动开销 | ~60s | ~5s | **92%** |
| LLM 首次请求延迟 | ~2s（新连接） | ~0.3s（复用连接） | **85%** |
| 内存占用（10 用例） | ~10x 进程 | ~1x 进程 | **90%** |
| 轨迹数据完整性 | 仅文件输出 | 实时事件流 + 文件 | ✅ |

---

## 12. 与文档原则的对应关系

| 设计决策 | 来源文档 | 验证方式 |
|----------|---------|---------|
| steps → 合并为一个 Agent Goal | 22.docx §3 | `--show-goals` 打印 |
| AI 执行 + 确定性断言 | 11.docx §四 | verify 层始终通过独立命令 |
| Python API，不用 `os.system()` | 33.docx §5 | `CaseExecutor._run_task()` |
| App Card = local mode + reasoning | 44.docx §5 | `run_flags: reasoning: true` |
| Test Case Compiler 轻量 Python | 22.docx §4 | 纯字符串拼接，无 LLM |
| 资源跨用例复用 | 33.docx §6 | `SharedResources.initialize()` 只调用一次 |

---

*生成于: 2026-09-02 | 基于分析: mobilerun_auto_test/11.docx, 22.docx, 33.docx, 44.docx*
