# 用例字段说明

本文档描述 `cases/<suite>/*.yaml` 测试用例中每个字段的含义、取值与执行语义。
字段定义见 `src/mobilerun_testkit/_lib.py`（`TestCase` / `VerifyItem`），
执行逻辑见 `src/mobilerun_testkit/runner.py`。

## 一条用例的执行流程

```
preflight (mobilerun devices)
  └─ setup 逐行执行(每行 120s 超时,失败 → 整条 ERROR)
      └─ task → mobilerun run "<task>" (受 timeout 约束,可省略)
          └─ verify 逐条执行(每条 180s 超时)
              └─ 判定总状态
                  └─ cleanup 逐行执行(每行 300s,尽力而为,失败不影响判定)
```

---

## 顶层字段

| 字段 | 类型 / 默认值 | 含义 |
|---|---|---|
| `id` | str,**必填** | 用例唯一标识。`--only <id>` 过滤、报告表格、AI 判读标记(`[AI-JUDGE-REQUIRED] case=<id>`)都用它。 |
| `title` | str,默认取 `id` | 人类可读标题,写进报告。 |
| `priority` | str,默认 `smoke` | 套件层级:`smoke` = 冒烟(快速、核心链路);`full` = 完整回归(更慢、覆盖视觉/推理/macro/iOS/应用卡片)。应与所在目录一致。 |
| `preconditions` | str 列表,默认空 | 运行前提条件的**文字描述**。runner 不会自动检查,靠人/AI 判断环境是否满足;不满足时用例通常记 ERROR(如 iOS 用例在纯 Android 环境)。 |
| `setup` | 多行块,默认空 | 用例开始前逐行执行的 shell 命令。以 `mobilerun` 开头的行会重写为实际二进制并自动注入 `--device`。任意一行失败 → 整条用例直接 ERROR,不再执行后续步骤。常见用法:`mobilerun device press home` 固定起点。 |
| `task` | str,可省略 | 交给 agent 的自然语言任务,runner 拼成 `mobilerun run "<task>" ...`。**没有 `task` 的用例是纯确定性用例**(如 `portal-ping`、`device-actions`),只跑 setup/verify,不经过 LLM。`task` 和 `verify` 至少要有其一。 |
| `run_flags` | dict,默认空 | 传给 `mobilerun run` 的 CLI 参数,见下表。出现未知键会在加载期报错(fail fast)。 |
| `verify` | 列表 | 独立验证步骤。核心设计:**永远不信 agent 自己说的"完成了"**,断言一律通过 `mobilerun device ui` / `screenshot` 等独立命令做。三种形式见下节。 |
| `timeout` | int,默认 600 | `mobilerun run` 这一步的超时秒数,超时退出码 124。注意:setup 每行 120s、verify 每条 180s、cleanup 每行 300s 是 runner 硬编码的,不受此字段控制。 |
| `pass_criteria` | str,默认空 | 判定标准的文字描述,展示在报告表格里,供 AI/人工做最终判定(尤其配合 `judge: ai_vision`)。 |
| `cleanup` | 多行块,默认空 | 用例结束后逐行执行,**总会执行**(哪怕 setup/verify 失败),失败只打警告、不影响判定。用于恢复设备状态(回桌面、关飞行模式等)。 |
| `known_limits` | str,默认空 | 已知局限描述。**作用**:当用例结果为 FAIL/ERROR 且此字段非空,状态降级为 `EXPECTED`(⚠️ 已知问题,不算回归失败)。 |

## `run_flags` 可用键

布尔键写 `true`/`false`,分别映射为 `--xxx` / `--no-xxx`;其余键映射为 `--xxx <value>`。
完整映射见 `_lib.py` 的 `_RUN_FLAG_KEYS`。

| 键 | CLI 旗标 | 含义 |
|---|---|---|
| `steps` | `--steps` | agent 最大执行步数。越复杂给越多(现有用例 10~25)。 |
| `vision` | `--vision` / `--no-vision` | 是否给 agent 截图。`false` = 只用 a11y 树(更快更便宜)。 |
| `reasoning` | `--reasoning` / `--no-reasoning` | 是否启用 Manager/Executor 规划循环(多一层"计划→执行→检查")。 |
| `vision_only` | `--vision-only` | 纯视觉模式。 |
| `ios` | `--ios` | 走 iOS Portal 驱动。 |
| `save_trajectory` | `--save-trajectory` | 保存动作轨迹;值 `action` 产出宏文件 + 截图(macro 用例靠它录制)。取值见下方「`save_trajectory` 取值详解」。 |
| `stream` / `tracing` / `debug` / `tcp` | 同名布尔旗标 | 透传给 mobilerun run。 |
| `provider` / `model` | `--provider` / `--model` | 覆盖 LLM 提供商/模型;也可在命令行用 `--provider`/`--model` 对整次运行统一覆盖(命令行优先)。 |
| `temperature` / `base_url` / `api_base` / `control_backend` / `device_id` | 同名旗标 | 透传。 |

### `save_trajectory` 取值详解

CLI 定义(`mobilerun/cli/main.py`):

```python
type=click.Choice(["none", "step", "action"])
# help: none (no saving), step (save per step), action (save per action)
```

| 值 | 含义 |
|---|---|
| `none` | 完全不保存轨迹(CLI 不传时回落到 config.yaml 的 `logging.save_trajectory`,默认 `none`) |
| `step` | 按步保存 |
| `action` | 按动作保存,产出宏文件(macro 用例靠它录制) |

**与 `vision` 的关系:两者正交。** `vision: false` 时仍可开轨迹保存:

- 截图条件是 `vision or stream_screenshots or save_trajectory != "none"`,开轨迹时每步依然截图,只是截图**不发给 LLM**(省视觉 token,多一次设备截图 I/O);
- 宏录制来自 `MacroRecorder` 在动作执行层记录,不依赖看图。

**注意:** 当前代码里所有分支都只判断 `!= "none"`,没有 `== "step"` / `== "action"` 的区分,因此 step 和 action 实际保存的产物相同(`trajectory.json` + `macro.json` + `screenshots/*.png` + 可选 GIF),差别只在文档语义。

## `verify` 条目的三种形式(互斥)

每条是一个 mapping,都建议带 `description` 说明验证什么。

### 1. 命令断言:`cmd` + `expect_contains` / `expect_regex`

```yaml
- cmd: "mobilerun device ui"
  expect_regex: "(?i)settings|com\\.android\\.settings"
```

- 执行 `cmd`(按空格切分),对 **stdout(为空则 stderr)** 做匹配。
- `expect_contains`:子串列表,**OR 语义**,命中任意一个即过。
- `expect_regex`:单个正则(默认 MULTILINE)。
- 两者都没有 → 校验期报错。匹配成功记 PASS,失败记 FAIL。

### 2. 存证:`cmd` + `save_to`

```yaml
- cmd: "mobilerun device screenshot"
  save_to: device-actions-shot.png
```

- 执行命令,取 stdout **最后一行**作为文件路径,复制到 `reports/.../evidence/` 下。
- 无断言,只存证;文件不存在时 detail 记 "save failed"。

### 3. AI 判读:`judge: ai_vision`

```yaml
- judge: ai_vision
  description: "直播间的公屏有内容"
```

- runner 调 `mobilerun device screenshot` 截图,复制到 evidence 目录,
  打印 `[AI-JUDGE-REQUIRED] case=<id> image=<path>`,该条记 `PENDING_AI`。
- PASS/FAIL 由 AI(按 `SKILL.md` 协议)或人工看图后填入报告。
- 适用于无法用固定 a11y 文本断言的场景:直播间画面、Gmail 搜索结果页、
  飞行模式图标状态等。
- 截图失败记 ERROR。

## 结果状态值

| 状态 | 图标 | 含义 |
|---|---|---|
| `PASS` | ✅ | verify 全部通过。注意:即使 `run` 退出码非零,只要有 verify 断言通过仍判 PASS —— 信独立验证,不信 agent 自评。 |
| `FAIL` | ❌ | 某条 verify 断言不匹配。 |
| `ERROR` | 💥 | 环境级问题:setup 失败、AI 判读截图失败等(非用例本身断言失败)。 |
| `PENDING_AI` | 🤖 | 只含 AI 判读项且 run 未失败,等 AI/人工看截图下结论。 |
| `EXPECTED` | ⚠️ | FAIL/ERROR 但命中 `known_limits`,视为已知局限而非回归。 |
| `SKIPPED` | ⏭️ | 未执行的初始态。 |

总状态判定顺序(见 `runner.py` `execute_case`):

1. run 失败且没有任何 verify PASS → `FAIL`
2. verify 中有 ERROR → `ERROR`
3. verify 中有 FAIL → `FAIL`
4. 全部 verify 为 PENDING_AI 且 run 成功 → `PENDING_AI`
5. run 退出码非零但有 verify 通过 → `PASS`(detail 追加说明)
6. 其余 → `PASS`
7. 若最终为 FAIL/ERROR 且写了 `known_limits` → 改判 `EXPECTED`

## 报告产出

每次运行写入 `mobilerun-testkit-reports/<时间戳>_<suite>/`(可用 `--report-dir` 覆盖):

- `report.json` — 机器可读,含每条 verify 的 status/detail/截图路径;
- `report.md` — 结果表格 + "AI 判读 (PENDING_AI)" 待填区;
- `evidence/` — 截图与存证文件。

运行结束后打印汇总:总数、各状态计数,若有 PENDING_AI 会提示去 report.md 填判定。
进程退出码:存在 FAIL/ERROR 为 `1`,否则 `0`(CI 友好)。

## 现有用例速览

| 用例 | 套件 | 有无 task | 验证方式 |
|---|---|---|---|
| `portal-ping` | smoke | 无 | 命令断言(`mobilerun ping`) |
| `run-open-settings` | smoke | 有(非 vision) | 命令正则(`device ui` 前台包名) |
| `device-actions` | smoke | 无 | 命令断言 + 截图存证 |
| `vision-read-state` | smoke | 有(vision) | AI 判读(电池页截图) |
| `dreamlike-enter-liveroom` | smoke | 有(真实业务 App) | AI 判读(直播间公屏) |
| `reasoning-multi-step` | full | 有(reasoning+vision) | AI 判读 + 轨迹检查 |
| `macro-record-replay` | full | 有(录制) | 命令断言(`macro list` / `replay --dry-run`) |
| `ios-basic` | full | 有(ios) | AI 判读(iOS Settings 截图) |
| `app-card-gmail` | full | 有(app cards) | AI 判读(Gmail 搜索结果页) |
