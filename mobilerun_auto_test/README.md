# MobileRun AutoTest v3.0

基于 MobileAgent Python API 的 AI 驱动移动端自动化测试框架。

## 特性

✅ **资源复用** - Driver / LLM 只初始化一次，所有用例共享
✅ **执行更快** - 相比 subprocess 方案提速 90% 以上
✅ **用例编译器** - 将 YAML 步骤编译为自然语言 Agent goal
✅ **App Card 支持** - 本地模式 App Card，让 AI 规划更准确
✅ **确定性断言** - 永远不信 Agent 自评
✅ **向后兼容** - 完整支持既有 YAML 格式
✅ **批量测试** - 一次初始化跑完整个测试套件

## 安装

`mobilerun_auto_test` 可以直接交给**没有 mobilerun 源码**的测试同学。它会自动检测
`mobilerun` 是否已安装，如果没有，就装到**公共（用户全局）环境**里，这样一份
mobilerun 就能服务所有项目和所有被测应用。

```bash
# 1. 安装本框架
pip install -e mobilerun_auto_test/     # 或：uv pip install -e mobilerun_auto_test/

# 2. 检查（并自动安装）mobilerun 依赖
mobilerun-autotest --check-env

# 3. 准备设备（每台设备只需做一次）
mobilerun setup
mobilerun ping
```

或者直接运行自带脚本，上面几步会一并完成：

```bash
cd mobilerun_auto_test && ./install.sh
```

### mobilerun 依赖说明

需要 Python `>=3.11,<3.14`（mobilerun 支持的版本范围）。

`--check-env` 会分别检查两件互不相关的事，只补齐缺失的那部分：

| 依赖项 | 用途 | 安装方式 |
|---|---|---|
| PATH 上的 `mobilerun` CLI | YAML 用例里的 `setup:` / `verify:` shell 步骤 | `uv tool install mobilerun`（失败则退回 `pipx install`） |
| `import mobilerun` | driver、LLM 加载、`MobileAgent` | `pip install --user mobilerun`（失败则退回 `uv pip install`） |

每次跑套件之前都会自动执行同样的检查，所以在一台干净的机器上直接执行
`mobilerun-autotest --suite smoke` 也能跑起来，不需要单独的安装步骤。

相关参数：

```bash
mobilerun-autotest --check-env                       # 检查 + 安装后退出
mobilerun-autotest --check-env --no-auto-install     # 只报告，绝不安装
mobilerun-autotest --suite smoke --no-auto-install   # 缺依赖时给出安装提示并失败，而不是自动安装
mobilerun-autotest --check-env --mobilerun-extras anthropic
mobilerun-autotest --check-env --mobilerun-version 0.6.17
```

在 Python 中调用：

```python
from mobilerun_autotest import detect_mobilerun, ensure_mobilerun

print(detect_mobilerun().summary())   # 只探测，不做任何改动
ensure_mobilerun()                    # 缺失时安装到公共环境
```

参考：https://github.com/droidrun/mobilerun

## 快速开始

### 1. 准备测试用例

创建 `cases/smoke/test_example.yaml`：

```yaml
id: open_settings
title: 打开设置应用
priority: smoke

setup: |
  mobilerun device press home

steps:
  - 打开设置应用
  - 确认设置界面已显示

run_flags:
  vision: false
  reasoning: false
  steps: 10

verify:
  - cmd: "mobilerun device ui"
    expect_contains: ["Settings"]
    description: "设置应用处于前台"

timeout: 300
```

### 2. 运行测试

```bash
# 跑冒烟套件
mobilerun-autotest --suite smoke

# 跑指定用例
mobilerun-autotest --suite smoke --only open_settings

# 指定设备
mobilerun-autotest --suite smoke --device emulator-5554

# 调试：只打印编译后的 goal，不真正执行
mobilerun-autotest --suite smoke --show-goals
```

### 3. 查看报告

报告输出到 `./autotest-reports/<时间戳>_<套件名>/`：

- `report.json` - 机器可读的结果
- `report.md` - 给人看的 Markdown 报告
- `evidence/` - 截图和其他产物

## 测试用例格式

### 基本结构

```yaml
id: test_id                    # 必填：唯一标识
title: 用例标题                # 必填：给人看的标题
priority: smoke                # smoke | full

# 可选：机器可判定的前置条件
requires:
  - cmd: "mobilerun device ui"
    expect_contains: ["com.example.app"]

# 可选：准备命令
setup: |
  mobilerun device press home

# 新增：注入到 Agent goal 上下文的测试数据
test_data:
  username: "test_user"
  message: "Hello World"

# 新增：自然语言步骤（推荐）
steps:
  - 打开应用
  - 进入主界面
  - 执行操作

# 备选：单条 task 字符串（旧格式）
task: "打开设置并进入 WiFi 页面"

# Agent 执行参数
run_flags:
  vision: true
  reasoning: true
  steps: 20

# 确定性断言（永远不信 Agent 自评）
verify:
  - cmd: "mobilerun device ui"
    expect_contains: ["Success"]
  - cmd: "mobilerun device screenshot"
    save_to: evidence.png
  - judge: ai_vision
    description: "截图显示了预期状态"

timeout: 600

# 可选：cleanup 一定会执行
cleanup: |
  mobilerun device press back
  mobilerun device press home
```

### v3.0 新增字段

| 字段 | 类型 | 作用 |
|-------|------|---------|
| `test_data` | dict | 注入到 Agent goal 上下文的键值对 |
| `steps` | list[str] | 自然语言步骤，编译成单个 goal |

## App Card 集成

### 1. 创建 App Card

`config/app_cards/app_cards.json`：

```json
{
  "com.example.app": "myapp.md"
}
```

`config/app_cards/myapp.md`：

```markdown
# MyApp 指南

## 概述
MyApp 是一个示例应用，包含以下功能：
- 用户登录
- 浏览商品
- 加入购物车

## 导航
主标签页：首页 | 浏览 | 我的

## 重要规则
- 购物车操作需要先登录
- 浏览页加载需要 2-3 秒
- 使用无障碍标签定位，不要用坐标
```

### 2. 在配置中启用

`config/config.yaml`：

```yaml
agent:
  app_cards:
    enabled: true
    mode: local
    app_cards_dir: config/app_cards
```

### 3. 在用例中使用

```yaml
run_flags:
  reasoning: true    # App Card 必须开启 Manager 模式
  vision: true
  steps: 20
```

## 架构

```
测试用例 (YAML)
       ↓
TestCaseCompiler（steps → Agent goal）
       ↓
TestRunner
  ├── SharedResources（只初始化一次）
  │   ├── AndroidDriver
  │   ├── StateProvider
  │   └── LLMs
  └── 逐个用例执行：
      ├── Setup（shell）
      ├── MobileAgent.run(goal)  ← 复用 driver / LLM
      ├── Verify（确定性断言）
      └── Cleanup（shell）
       ↓
报告（JSON / Markdown）
```

## CLI 参数

```bash
mobilerun-autotest [OPTIONS]

Options:
  --suite TEXT          测试套件：smoke | full | all（默认：smoke）
  --device TEXT         设备序列号（默认：自动检测）
  --only TEXT           只跑指定用例 ID（可重复传入）
  --cases-dir PATH      自定义用例目录（默认：./cases）
  --report-dir PATH     自定义报告目录（默认：./autotest-reports）
  --config PATH         MobileRun 配置文件（默认：自动检测）
  --show-goals          只打印编译后的 goal，不执行
  --stop-on-error       首次失败即停止整个套件
  --parallel INT        并行执行（需要设备池）
  --rate-limit FLOAT    每秒最大请求数（LLM 限流）
  --help                显示帮助信息
```

## 性能

| 指标 | v1.0（CLI subprocess） | v3.0（Python API） | 提升 |
|--------|----------------------|-------------------|-------------|
| 单用例初始化 | 5-8s | 0.1s | **97%** |
| 10 用例 driver 开销 | 60s | 5s | **92%** |
| LLM 首次请求 | 2s | 0.3s | **85%** |
| 内存（10 用例） | 10 个进程 | 1 个进程 | **90%** |

## 输出示例

```
🚀 MobileRun AutoTest v3.0
📦 Suite: smoke (3 cases)
🔧 Initializing shared resources...
✅ Driver: AndroidDriver (emulator-5554)
✅ LLMs: manager, executor, fast_agent
✅ App Cards: 2 loaded

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📦 [1/3] open_settings
📝 Open Settings App
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  📋 Setup: mobilerun device press home
     ✅ Setup completed
  🎯 Task: Open the Settings app...
     ✅ Task completed (3.2s, 5 steps)
  🔍 Verify: (1 checks)
     [1] Settings app is in foreground
         ✅ matched: 'Settings'
  ✅ PASS (4.1s)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📦 [2/3] send_message
...

═══════════════════════════════════════════════
Summary: 3 run — PASS=2  FAIL=1
📄 Report: ./autotest-reports/20260902_143022_smoke/report.md
```

## 进阶用法

### 自定义配置

```python
from mobilerun_autotest import TestRunner
from mobilerun.config_manager import MobileConfig, AgentConfig

config = MobileConfig(
    agent=AgentConfig(
        provider="anthropic",
        model="claude-3-5-sonnet-20241022",
        reasoning=True,
    ),
)

runner = TestRunner(config=config)
exit_code = await runner.run_suite("smoke")
```

### 编程式 API

```python
from mobilerun_autotest import TestRunner, load_cases

# 加载用例
cases = load_cases("./cases", "smoke")

# 跑指定用例
runner = TestRunner()
await runner.initialize()

for case in cases:
    result = await runner.run_case(case)
    print(f"{case.id}: {result.status}")

await runner.cleanup()
```

## 从 v1.0 迁移

v3.0 完全向后兼容。要用上新特性，按需添加即可：

1. **加 `steps` 字段**（可选，推荐）：
   ```yaml
   steps:
     - 打开应用
     - 进入目标页面
   ```

2. **加 `test_data`**（可选）：
   ```yaml
   test_data:
     username: "test"
   ```

3. **启用 App Card**（可选）：
   ```yaml
   run_flags:
     reasoning: true  # App Card 必需
   ```

旧的 `task` 字段依然可用，不需要改任何代码。

## 故障排查

### 没有连接的设备

```bash
adb devices
mobilerun setup
```

### 找不到测试用例

确认 `cases/smoke/` 存在且里面是合法的 `.yaml` 文件，或者用 `--cases-dir`
指向别的目录。

### Agent 超时

调大 YAML 里的 `timeout`，或减小 `run_flags` 里的 `steps`，也检查一下设备是否还有响应
（`mobilerun ping`）。

### LLM 报错

检查 mobilerun 配置（`~/.config/mobilerun/config.yaml`）和 API 密钥。可以先用
`reasoning: false` 跑一遍，排除 Manager 模式的问题。

### App Card 不生效

确认 `run_flags` 里开了 `reasoning: true`：

```yaml
run_flags:
  reasoning: true    # App Card 需要 Manager 模式
  vision: true
```

### LLM 限流

用 `--rate-limit` 限速：

```bash
mobilerun-autotest --suite full --rate-limit 2.0
```

### 设备状态被污染

补充完整的 `cleanup` 命令：

```yaml
cleanup: |
  mobilerun device press back
  mobilerun device press back
  mobilerun device press home
```

## 许可证

MIT License，详见 LICENSE 文件。
