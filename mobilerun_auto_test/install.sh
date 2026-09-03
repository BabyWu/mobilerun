#!/bin/bash
# MobileRun AutoTest v3.0 安装和验证脚本

set -e

echo "================================================"
echo "MobileRun AutoTest v3.0 - Installation & Verification"
echo "================================================"
echo ""

# 检查Python版本
echo "✓ Checking Python version..."
python_version=$(python -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
echo "  Python version: $python_version"

if [ "$(echo "$python_version < 3.10" | bc)" -eq 1 ]; then
    echo "  ❌ Error: Python 3.10+ required, found $python_version"
    exit 1
fi
echo ""

# 检查mobilerun是否已安装
echo "✓ Checking mobilerun installation..."
if command -v mobilerun &> /dev/null; then
    mobilerun_version=$(mobilerun --version 2>&1 | head -1 || echo "unknown")
    echo "  mobilerun found: $mobilerun_version"
else
    echo "  ⚠️  Warning: mobilerun not found in PATH"
    echo "     Install with: pip install mobilerun"
fi
echo ""

# 安装mobilerun-autotest
echo "✓ Installing mobilerun-autotest..."
pip install -e . -q
echo "  Installation complete"
echo ""

# 验证安装
echo "✓ Verifying installation..."
if command -v mobilerun-autotest &> /dev/null; then
    version=$(mobilerun-autotest --version 2>&1)
    echo "  $version"
else
    echo "  ❌ Error: mobilerun-autotest command not found"
    exit 1
fi
echo ""

# 检查Python导入
echo "✓ Checking Python imports..."
python -c "
from mobilerun_autotest import (
    TestRunner, TestCaseCompiler, CaseExecutor,
    SharedResources, load_cases
)
print('  All imports successful')
" || { echo "  ❌ Error: Import failed"; exit 1; }
echo ""

# 验证目录结构
echo "✓ Checking directory structure..."
required_dirs=("cases/smoke" "cases/full" "config/app_cards" "src/mobilerun_autotest")
for dir in "${required_dirs[@]}"; do
    if [ -d "$dir" ]; then
        echo "  ✓ $dir"
    else
        echo "  ❌ Missing: $dir"
    fi
done
echo ""

# 验证测试用例
echo "✓ Checking test cases..."
smoke_count=$(find cases/smoke -name "*.yaml" 2>/dev/null | wc -l)
full_count=$(find cases/full -name "*.yaml" 2>/dev/null | wc -l)
echo "  Smoke cases: $smoke_count"
echo "  Full cases: $full_count"
echo ""

# 运行单元测试（如果pytest可用）
if command -v pytest &> /dev/null; then
    echo "✓ Running unit tests..."
    pytest tests/ -v --tb=short -q 2>&1 | tail -10 || true
    echo ""
else
    echo "⚠️  pytest not found, skipping unit tests"
    echo "   Install with: pip install pytest pytest-asyncio"
    echo ""
fi

# 测试编译器
echo "✓ Testing compiler..."
python -c "
from mobilerun_autotest import TestCaseCompiler, load_cases
from pathlib import Path

try:
    cases = load_cases(Path('cases'), 'smoke')
    compiler = TestCaseCompiler()
    case = cases[0]
    goal = compiler.compile_goal(case)
    print(f'  Compiled {case.id}: {len(goal)} chars')
except Exception as e:
    print(f'  ⚠️  Compiler test error: {e}')
" 2>&1
echo ""

# 检查设备连接（可选）
echo "✓ Checking device connection (optional)..."
if command -v adb &> /dev/null; then
    device_count=$(adb devices | grep -v "List" | grep "device$" | wc -l)
    if [ "$device_count" -gt 0 ]; then
        echo "  ✓ $device_count Android device(s) connected"
    else
        echo "  ⚠️  No Android devices connected"
        echo "     Connect device and run: adb devices"
    fi
else
    echo "  ⚠️  adb not found in PATH"
fi
echo ""

# 显示快速入门命令
echo "================================================"
echo "✅ Installation Complete!"
echo "================================================"
echo ""
echo "Quick Start Commands:"
echo ""
echo "  # Show compiled goals (no execution)"
echo "  mobilerun-autotest --suite smoke --show-goals"
echo ""
echo "  # Run smoke tests"
echo "  mobilerun-autotest --suite smoke"
echo ""
echo "  # Run specific test"
echo "  mobilerun-autotest --suite smoke --only portal_ping"
echo ""
echo "  # Debug mode"
echo "  mobilerun-autotest --suite smoke --debug"
echo ""
echo "Documentation:"
echo "  - README.md          - Full documentation"
echo "  - QUICKSTART.md      - 5-minute tutorial"
echo "  - examples/          - Code examples"
echo ""
echo "Next Steps:"
echo "  1. Read QUICKSTART.md"
echo "  2. Review cases/smoke/*.yaml examples"
echo "  3. Run: mobilerun-autotest --suite smoke --show-goals"
echo ""
