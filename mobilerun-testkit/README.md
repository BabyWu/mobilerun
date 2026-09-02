# mobilerun-testkit

面向 [mobilerun](https://github.com/droidrun/mobilerun) 的独立批量回归测试工具箱。
它把 mobilerun 当作**黑盒 CLI** —— 唯一的契约是公开的 `mobilerun` 命令
(`run` / `device` / `ping` / `macro` / `devices`) 及其退出码 —— 因此可以配合任何
mobilerun 安装使用,并且**不会给 mobilerun 包本身添加任何依赖**。

## 安装

前提条件:mobilerun 已安装并完成配置(`uv tool install mobilerun`,然后 `mobilerun setup`)。

```bash
# 从本目录(仓库检出)安装:
uv tool install ./mobilerun-testkit
# ...或使用 pip:
pip install ./mobilerun-testkit

# 发布后可直接安装:
uv tool install mobilerun-testkit
```

这会安装 `mobilerun-test` 命令。无需也不会改动你的 mobilerun 安装。

## 用法

```bash
# 快速冒烟测试(~15 分钟,单个便宜模型,核心检查项)
mobilerun-test --suite smoke --device <serial>

# 发版前的完整回归(数小时;覆盖视觉/推理、macro、iOS、应用卡片)。
# iOS 用例在仅支持 Android 的环境会报 ERROR —— 属于预期行为。
mobilerun-test --suite full --device <serial>

# 全部 / 选定用例
mobilerun-test --suite all
mobilerun-test --suite all --only portal-ping --only vision-read-state

# 为整次运行覆盖模型/提供商
mobilerun-test --suite smoke --provider GoogleGenAI --model gemini-3.7-flash
```

退出码:任一用例以 FAIL/ERROR 结束则为 `1`,否则为 `0`(对 CI 友好)。

## 产出内容

`reports/<timestamp>_<suite>/`(位于当前工作目录下):

- `report.json` — 机器可读的结果(CI / AI 分析用)
- `report.md` — 人类可读的结果表格
- `evidence/` — 截图和保存的产物
- AI 视觉断言会记录为 `PENDING_AI`;运行器会打印
  `[AI-JUDGE-REQUIRED] case=<id> image=<path>`,由人类或 AI(参见
  `SKILL.md`)将判定结果填入报告。

## 用例文件

用例是 `cases/<suite>/*.yaml` 下的 YAML 文件。已安装的包自带内置用例;
传入 `--cases-dir`(或在你的工作目录旁放一个 `cases/` 文件夹)即可使用自己的用例:

```yaml
id: run-open-settings         # 必填
title: 打开 Settings           # 必填
priority: smoke               # smoke | full
preconditions:                # 可选,给人/AI 看的说明
  - "设备已 setup 且 ping 通过"
setup: |                      # 可选,shell 逐行执行;失败 → ERROR
  mobilerun device press home
task: "Open the Settings app" # 传给 `mobilerun run`;纯确定性用例可省略
run_flags:                    # 可选的 `mobilerun run` 参数
  vision: false
  reasoning: true
  steps: 15
verify:                       # 独立断言(永远不要相信 agent 自己说的"完成了")
  - cmd: "mobilerun device ui"
    expect_contains: ["Settings"]   # 列表内为 OR 关系;或使用 expect_regex / save_to
  - cmd: "mobilerun device screenshot"
    save_to: shot.png               # stdout 是文件路径 → 复制到 evidence/
  - judge: ai_vision                # 已截图,交给 AI/人工判定 PASS/FAIL
    description: "截图显示电池页面"
timeout: 600                  # 整个用例的秒数
pass_criteria: "..."
cleanup: |                    # 总会执行;失败不影响判定结果
  mobilerun device press home
known_limits: "..."           # 匹配到此描述的 FAIL 会记为 EXPECTED,而非回归
```

没有 `task` 的用例只运行 `setup`/`verify`(例如 `mobilerun ping`)。

> 各字段的完整含义、`verify` 三种形式与结果状态判定规则详见
> [CASE-FIELDS.md](./CASE-FIELDS.md)。

## AI agent 用法

`SKILL.md`(本目录下)教会 AI agent(Claude Code、Codex 等)运行测试套件、
判定 `ai_vision` 截图、归因失败原因。把你的 agent 指向这个目录并说
"运行 smoke 套件"即可。

## 设计原则

1. **Mobilerun 是黑盒** —— 只通过子进程调用公开 CLI 命令;
   不从 `mobilerun` Python 包导入任何内容。
2. **永远不要相信 agent 自己说的"完成了"** —— 每条断言都通过
   `mobilerun device ui` / `screenshot` 独立运行。
3. **只读优先** —— 对物理设备:不做破坏性或付费操作;
   会改变状态的用例必须带 `cleanup` 并恢复之前的状态。
4. **已知限制记为 EXPECTED,而非失败** —— 通过 `known_limits` 记录。
