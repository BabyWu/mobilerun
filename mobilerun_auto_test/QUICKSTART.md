# MobileRun AutoTest v3.0 - Quick Start Guide

This guide helps you get started with MobileRun AutoTest in 5 minutes.

## Prerequisites

1. **MobileRun installed and configured**
   ```bash
   pip install mobilerun
   mobilerun setup
   ```

2. **Device connected**
   ```bash
   adb devices
   # or for iOS
   mobilerun devices
   ```

## Installation

```bash
# From source
cd mobilerun_auto_test
pip install -e .

# Verify installation
mobilerun-autotest --version
```

## Project Structure

```
your-project/
├── cases/                    # Test cases
│   ├── smoke/               # Fast, essential tests
│   │   ├── 01_basic.yaml
│   │   └── 02_login.yaml
│   └── full/                # Comprehensive tests
│       ├── 01_feature_a.yaml
│       └── 02_feature_b.yaml
├── config/                   # Optional configs
│   └── app_cards/           # App documentation for AI
│       ├── app_cards.json
│       └── myapp.md
└── autotest-reports/        # Generated reports (gitignore)
```

## Step 1: Create Your First Test

Create `cases/smoke/01_hello.yaml`:

```yaml
id: hello_test
title: Basic Device Check
priority: smoke

verify:
  - cmd: "mobilerun ping"
    expect_regex: "pong|ok"
    description: "Device responds to ping"

timeout: 30
```

## Step 2: Run Tests

```bash
# Run smoke suite
mobilerun-autotest --suite smoke

# Run specific test
mobilerun-autotest --suite smoke --only hello_test

# Debug mode
mobilerun-autotest --suite smoke --debug
```

## Step 3: View Results

Reports are in `./autotest-reports/<timestamp>_<suite>/`:

- `report.md` - Human-readable markdown
- `report.json` - Machine-readable JSON
- `evidence/` - Screenshots and artifacts

## Step 4: Add Real Test

Create `cases/smoke/02_open_app.yaml`:

```yaml
id: open_settings
title: Open Android Settings
priority: smoke

setup: |
  mobilerun device press home

steps:
  - Open the Settings app

run_flags:
  vision: false
  reasoning: false
  steps: 10

verify:
  - cmd: "mobilerun device ui"
    expect_regex: "(?i)settings"
    description: "Settings app opened"

timeout: 120

cleanup: |
  mobilerun device press home
```

Run it:

```bash
mobilerun-autotest --suite smoke --only open_settings
```

## Step 5: Add Test Data

For tests needing variables:

```yaml
id: send_message
title: Send Test Message
priority: smoke

test_data:
  username: "test_user"
  message: "Hello World"

steps:
  - Login with username
  - Navigate to messages
  - Send the test message

run_flags:
  vision: true
  steps: 15

verify:
  - cmd: "mobilerun device ui"
    expect_contains: ["Hello World"]
```

## Common Patterns

### Pattern 1: Simple Verification

```yaml
verify:
  - cmd: "mobilerun device ui"
    expect_contains: ["ExpectedText"]
  - cmd: "mobilerun device screenshot"
    save_to: evidence.png
```

### Pattern 2: AI Vision Check

```yaml
verify:
  - judge: ai_vision
    description: "Screenshot shows login success"
```

### Pattern 3: Multi-Step with Data

```yaml
test_data:
  email: "test@example.com"
  password: "Test123"

steps:
  - Open login screen
  - Enter email
  - Enter password
  - Tap login button
```

### Pattern 4: Cleanup Always Runs

```yaml
cleanup: |
  mobilerun device press back
  mobilerun device press back
  mobilerun device press home
```

## Tips

1. **Start small**: Begin with simple ping/UI tests
2. **Use --show-goals**: Debug compilation without running
   ```bash
   mobilerun-autotest --suite smoke --show-goals
   ```

3. **Test incrementally**: Run single cases during development
   ```bash
   mobilerun-autotest --suite smoke --only my_test
   ```

4. **Check device first**:
   ```bash
   mobilerun ping
   mobilerun device ui
   ```

5. **Read reports**: Check `report.md` for human-friendly results

## Troubleshooting

### "No connected devices"
```bash
adb devices
mobilerun setup
```

### "No test cases found"
- Check `cases/smoke/` directory exists
- Ensure `.yaml` files are valid
- Use `--cases-dir` if in different location

### "Agent timeout"
- Increase `timeout` in YAML
- Reduce `steps` in `run_flags`
- Check device responsiveness

### "LLM error"
- Verify mobilerun config: `cat ~/.config/mobilerun/config.yaml`
- Check API keys
- Try with `reasoning: false` first

## Next Steps

1. **Read full README.md** for advanced features
2. **Check examples/** for patterns
3. **Browse cases/** for reference tests
4. **See design doc** for architecture details

## Getting Help

- GitHub Issues: https://github.com/droidrun/mobilerun/issues
- Documentation: https://github.com/droidrun/mobilerun
- Examples: `./examples/` directory

---

**Ready to test! 🚀**
