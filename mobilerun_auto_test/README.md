# MobileRun AutoTest v3.0

AI-powered mobile automation testing framework using MobileAgent Python API.

## Features

✅ **Resource Reuse** - Driver/LLM initialized once, shared across all test cases  
✅ **Fast Execution** - 90%+ faster than subprocess-based approach  
✅ **Test Case Compiler** - Convert YAML steps to natural language Agent goals  
✅ **App Card Support** - Local mode App Cards for better AI planning  
✅ **Deterministic Assertions** - Never trust Agent self-evaluation  
✅ **Backward Compatible** - Existing YAML format fully supported  
✅ **Batch Testing** - Run entire test suites with single initialization  

## Installation

```bash
# From source
pip install -e mobilerun_auto_test/

# Or with uv
uv pip install -e mobilerun_auto_test/
```

## Quick Start

### 1. Prepare Test Cases

Create `cases/smoke/test_example.yaml`:

```yaml
id: open_settings
title: Open Settings App
priority: smoke

setup: |
  mobilerun device press home

steps:
  - Open the Settings app
  - Verify Settings screen is visible

run_flags:
  vision: false
  reasoning: false
  steps: 10

verify:
  - cmd: "mobilerun device ui"
    expect_contains: ["Settings"]
    description: "Settings app is in foreground"

timeout: 300
```

### 2. Run Tests

```bash
# Run smoke suite
mobilerun-autotest --suite smoke

# Run specific test cases
mobilerun-autotest --suite smoke --only open_settings

# Run with custom device
mobilerun-autotest --suite smoke --device emulator-5554

# Debug: show compiled goals without execution
mobilerun-autotest --suite smoke --show-goals
```

### 3. View Reports

Reports are saved to `./autotest-reports/<timestamp>_<suite>/`:

- `report.json` - Machine-readable results
- `report.md` - Human-readable markdown report
- `evidence/` - Screenshots and artifacts

## Test Case Format

### Basic Structure

```yaml
id: test_id                    # Required: unique identifier
title: Test Title              # Required: human-readable title
priority: smoke                # smoke | full

# Optional: machine-checkable preconditions
requires:
  - cmd: "mobilerun device ui"
    expect_contains: ["com.example.app"]

# Optional: setup commands
setup: |
  mobilerun device press home

# NEW: test data injected into Agent goal context
test_data:
  username: "test_user"
  message: "Hello World"

# NEW: natural language steps (preferred)
steps:
  - Open the app
  - Navigate to main screen
  - Perform action

# Alternative: single task string (legacy)
task: "Open Settings and navigate to WiFi"

# Agent execution flags
run_flags:
  vision: true
  reasoning: true
  steps: 20

# Deterministic assertions (NEVER trust Agent self-evaluation)
verify:
  - cmd: "mobilerun device ui"
    expect_contains: ["Success"]
  - cmd: "mobilerun device screenshot"
    save_to: evidence.png
  - judge: ai_vision
    description: "Screenshot shows expected state"

timeout: 600

# Optional: cleanup always runs
cleanup: |
  mobilerun device press back
  mobilerun device press home
```

### New Fields in v3.0

| Field | Type | Purpose |
|-------|------|---------|
| `test_data` | dict | Key-value pairs injected into Agent goal context |
| `steps` | list[str] | Natural language steps compiled into single goal |

## App Card Integration

### 1. Create App Card

`config/app_cards/app_cards.json`:

```json
{
  "com.example.app": "myapp.md"
}
```

`config/app_cards/myapp.md`:

```markdown
# MyApp Guide

## Overview
MyApp is a demo application with the following features:
- User login
- Browse items
- Add to cart

## Navigation
Main tabs: Home | Browse | Profile

## Important Rules
- Login required for cart operations
- Browse tab may take 2-3 seconds to load
- Use accessibility labels instead of coordinates
```

### 2. Enable in Config

`config/config.yaml`:

```yaml
agent:
  app_cards:
    enabled: true
    mode: local
    app_cards_dir: config/app_cards
```

### 3. Use in Test Cases

```yaml
run_flags:
  reasoning: true    # Required for App Card
  vision: true
  steps: 20
```

## Architecture

```
Test Cases (YAML)
       ↓
TestCaseCompiler (steps → Agent goal)
       ↓
TestRunner
  ├── SharedResources (init once)
  │   ├── AndroidDriver
  │   ├── StateProvider
  │   └── LLMs
  └── For each case:
      ├── Setup (shell)
      ├── MobileAgent.run(goal)  ← Reuses driver/LLMs
      ├── Verify (deterministic)
      └── Cleanup (shell)
       ↓
Reports (JSON/Markdown)
```

## CLI Options

```bash
mobilerun-autotest [OPTIONS]

Options:
  --suite TEXT          Test suite: smoke | full | all (default: smoke)
  --device TEXT         Device serial (default: auto-detect)
  --only TEXT           Run specific test case IDs (repeatable)
  --cases-dir PATH      Custom cases directory (default: ./cases)
  --report-dir PATH     Custom report directory (default: ./autotest-reports)
  --config PATH         MobileRun config file (default: auto-detect)
  --show-goals          Print compiled goals without execution
  --stop-on-error       Stop suite on first failure
  --parallel INT        Parallel execution (requires device pool)
  --rate-limit FLOAT    Max requests per second (LLM rate limiting)
  --help                Show this message and exit
```

## Performance

| Metric | v1.0 (CLI subprocess) | v3.0 (Python API) | Improvement |
|--------|----------------------|-------------------|-------------|
| Per-case initialization | 5-8s | 0.1s | **97%** |
| 10-case driver overhead | 60s | 5s | **92%** |
| LLM first request | 2s | 0.3s | **85%** |
| Memory (10 cases) | 10x processes | 1x process | **90%** |

## Example Output

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

## Advanced Usage

### Custom Config

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

### Programmatic API

```python
from mobilerun_autotest import TestRunner, load_cases

# Load cases
cases = load_cases("./cases", "smoke")

# Run specific cases
runner = TestRunner()
await runner.initialize()

for case in cases:
    result = await runner.run_case(case)
    print(f"{case.id}: {result.status}")

await runner.cleanup()
```

## Migration from v1.0

v3.0 is fully backward compatible. To use new features:

1. **Add `steps` field** (optional, recommended):
   ```yaml
   steps:
     - Open app
     - Navigate to screen
   ```

2. **Add `test_data`** (optional):
   ```yaml
   test_data:
     username: "test"
   ```

3. **Enable App Cards** (optional):
   ```yaml
   run_flags:
     reasoning: true  # Required for App Card
   ```

Old `task` field still works. No code changes required.

## Troubleshooting

### App Card not working

Ensure `reasoning: true` in `run_flags`:

```yaml
run_flags:
  reasoning: true    # App Card requires Manager mode
  vision: true
```

### LLM rate limiting

Use `--rate-limit` to throttle:

```bash
mobilerun-autotest --suite full --rate-limit 2.0
```

### Device state pollution

Add thorough `cleanup` commands:

```yaml
cleanup: |
  mobilerun device press back
  mobilerun device press back
  mobilerun device press home
```

## License

MIT License - See LICENSE file for details
