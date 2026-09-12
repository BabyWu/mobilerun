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

# mobilerun 要求 >=3.11,<3.14
if ! python -c 'import sys; sys.exit(0 if (3,11) <= sys.version_info[:2] < (3,14) else 1)'; then
    echo "  ❌ Error: mobilerun requires Python >=3.11,<3.14, found $python_version"
    exit 1
fi
echo ""

# 安装 mobilerun-autotest（bootstrap 依赖它来检测/安装 mobilerun）
echo "✓ Installing mobilerun-autotest..."
pip install -e . -q
echo "  Installation complete"
echo ""

# 检查并安装 mobilerun（公共环境，所有被测应用共用）
# 参考: https://github.com/droidrun/mobilerun
echo "✓ Checking / installing mobilerun (public environment)..."
if ! mobilerun-autotest --check-env; then
    echo "  ❌ Error: mobilerun environment not ready"
    exit 1
fi
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
echo "  - examples/          - Code examples"
echo ""
echo "Next Steps:"
echo "  1. Read README.md"
echo "  2. Review cases/smoke/*.yaml examples"
echo "  3. Run: mobilerun-autotest --suite smoke --show-goals"
echo ""
