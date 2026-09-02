---
name: mobilerun-test
description: Run and analyze Mobilerun device regression tests with the mobilerun-testkit runner. Use when the user asks to 跑设备测试 / regression test / run smoke or full suite / analyze mobilerun test failures, or before a release to verify the framework still works on a real device.
---

# Mobilerun 设备回归测试（mobilerun-testkit）

你负责三件事：**跑批**、**AI 判读**、**失败归因**。确定性执行全部由
`mobilerun-test` 命令（或 `python -m mobilerun_testkit.runner`）完成——
不要绕过 runner 手动逐条执行用例；你自己的操作保持只读优先，物理设备上
禁止破坏性/付费操作。

## 1. 跑批

前置检查（没有设备时先补齐）：

```bash
mobilerun devices        # 有设备输出才继续；没有则先 mobilerun setup
```

跑批命令：

```bash
# 快速冒烟（~15 分钟，默认档）
mobilerun-test --suite smoke --device <serial>

# 发版前全量（可数小时；含 iOS 用例，Android-only 环境下该条会 ERROR，属预期）
mobilerun-test --suite full --device <serial>

# 单跑某几条 / 全部 / 指定用例目录
mobilerun-test --suite all --only portal-ping --only vision-read-state
mobilerun-test --suite all
mobilerun-test --suite smoke --cases-dir ./cases   # 用户自定义用例
```

约定：默认 smoke；用户说"完整回归/发版前检查"才用 full。模型/供应商覆盖用
`--provider X --model Y`。runner 的退出码：有 FAIL/ERROR → 1，否则 0。

## 2. AI 判读协议（judge: ai_vision）

runner 不做视觉判断。它的 stdout 会对每个需要判读的项输出：

```
[AI-JUDGE-REQUIRED] case=<case-id> image=<绝对路径>
```

你的职责：

1. 扫描 runner 输出，收集所有 `[AI-JUDGE-REQUIRED]` 行。
2. 用 Read 工具打开每个 `image=` 路径的截图。
3. 对照该用例的 `description`（见 report.md 的 AI 判读表或用例 YAML）判定：
   - **PASS**：截图显示的内容满足 description。
   - **FAIL**：不满足，写明截图里实际是什么。
4. 在报告目录（`reports/<run>/`）新建 `ai-judgements.md`：先复制 report.md
   中「AI 判读 (PENDING_AI)」表，再把"待填写"替换为你的判定。用例 id、
   截图路径从 `[AI-JUDGE-REQUIRED]` 行抄。

判读时遵循独立验证原则：**不轻信 Agent 自述的 done**；截图模糊/未加载就判
FAIL 并注明，不要猜。

## 3. 失败归因

对报告中每个 FAIL / ERROR：

1. 打开 `reports/<run>/report.json`，读该用例的 `detail`、`verify` 结果、
   `run_exit_code`。
2. 打开 `reports/<run>/evidence/` 里的截图；`save_trajectory: action`
   的用例可读 mobilerun 轨迹目录（每步动作 + 截图）。
3. 在 `ai-judgements.md` 末尾追加"失败归因"小节：每个失败用例一段，
   写明**根因类别**（驱动/Portal 问题 | Agent 决策错误 | prompt/模型能力 |
   环境前置不满足 | 已知限制）+ 证据 + 建议动作。
4. 区分：
   - `run` 退出码非零但 verify 断言通过 → 实际是好的（runner 已记 PASS）。
   - `known_limits` 命中 → 状态 EXPECTED，不算失败。
   - 环境类失败（无 Gmail、无 iOS、无 provider key）→ 建议改 preconditions
     或用 `--only` 挑选，不要当产品 bug 上报。

## 4. 汇报

跑完（含判读、归因后）向用户总结：总用例数、各状态计数、失败根因清单、
报告路径（report.md / report.json / ai-judgements.md）。发版回归可对比
上一次 `reports/` 里的结果表，标注新增失败与已恢复项。
