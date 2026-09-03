"""
Example: Advanced test case patterns and best practices.
"""

from pathlib import Path
from mobilerun_autotest import TestRunner, load_cases, TestCaseCompiler
import asyncio


def demo_test_case_compilation():
    """Demonstrate how test cases are compiled into Agent goals."""

    compiler = TestCaseCompiler()
    cases = load_cases("./cases", "smoke")

    for case in cases:
        print(f"\n{'='*70}")
        print(f"Case: {case.id}")
        print(f"Title: {case.title}")
        print('='*70)

        # Show original structure
        if case.steps:
            print("\n📋 Original Steps:")
            for i, step in enumerate(case.steps, 1):
                print(f"  {i}. {step}")

        if case.test_data:
            print("\n📊 Test Data:")
            for k, v in case.test_data.items():
                print(f"  {k} = {v}")

        # Show compiled goal
        goal = compiler.compile_goal(case)
        print("\n🎯 Compiled Goal:")
        print('-'*70)
        print(goal)
        print('-'*70)


async def demo_custom_assertions():
    """Example: Creating custom verification logic."""

    from mobilerun_autotest import CaseExecutor, SharedResources
    from mobilerun.config_manager import MobileConfig

    # Load a test case
    cases = load_cases("./cases", "smoke")
    case = cases[0]

    # Initialize
    shared = SharedResources()
    await shared.initialize(MobileConfig())

    try:
        # Execute case
        compiler = TestCaseCompiler()
        executor = CaseExecutor(shared=shared, compiler=compiler)
        evidence_dir = Path("./evidence")
        evidence_dir.mkdir(exist_ok=True)

        result = await executor.execute(case, evidence_dir)

        # Custom post-processing
        print(f"\n📊 Test Result Analysis:")
        print(f"  Status: {result.status}")
        print(f"  Duration: {result.run_seconds}s")
        print(f"  Agent Steps: {result.agent_steps}")

        # Custom success criteria
        if result.status == "PASS":
            if result.run_seconds > 60:
                print("  ⚠️  Warning: Test took longer than 60s")
            if result.agent_steps > 20:
                print("  ⚠️  Warning: Agent needed more than 20 steps")

        # Check verify results
        for i, vr in enumerate(result.verify_results, 1):
            status = vr.get("status", "UNKNOWN")
            detail = vr.get("detail", "")
            print(f"  Verify[{i}]: {status} - {detail[:50]}")

    finally:
        await shared.close()


async def demo_dynamic_test_generation():
    """Example: Generating test cases programmatically."""

    from mobilerun_autotest.models import TestCase, VerifyItem

    # Generate tests for multiple settings screens
    settings_screens = [
        ("WiFi", "wifi|wlan"),
        ("Bluetooth", "bluetooth"),
        ("Display", "display|brightness"),
    ]

    cases = []
    for name, regex_pattern in settings_screens:
        case = TestCase(
            id=f"navigate_to_{name.lower()}",
            title=f"Navigate to {name} Settings",
            priority="smoke",
            steps=[
                "Open Settings app",
                f"Navigate to {name} section",
            ],
            run_flags={
                "vision": False,
                "reasoning": False,
                "steps": 10,
            },
            verify=[
                VerifyItem(
                    cmd="mobilerun device ui",
                    expect_regex=f"(?i){regex_pattern}",
                    description=f"{name} section visible",
                )
            ],
            timeout=180,
            cleanup="mobilerun device press back\nmobilerun device press home",
        )
        cases.append(case)

    # Run generated tests
    runner = TestRunner(report_dir=Path("./dynamic-reports"))
    await runner.initialize()

    try:
        for case in cases:
            print(f"\n🧪 Running: {case.title}")
            result = await runner.run_case(case)
            print(f"  Result: {result.status}")
    finally:
        await runner.cleanup()


async def demo_conditional_testing():
    """Example: Conditional test execution based on environment."""

    import subprocess

    def is_emulator(device_id: str | None = None) -> bool:
        """Check if device is an emulator."""
        cmd = ["adb", "devices"]
        if device_id:
            cmd = ["adb", "-s", device_id, "emu", "avd", "name"]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
            return "emulator" in result.stdout.lower() or result.returncode == 0
        except:
            return False

    # Skip certain tests on emulators
    cases = load_cases("./cases", "full")
    filtered_cases = []

    for case in cases:
        # Skip GPS/camera tests on emulators
        if is_emulator():
            if "gps" in case.id.lower() or "camera" in case.id.lower():
                print(f"⏭️  Skipping {case.id} (not supported on emulator)")
                continue

        filtered_cases.append(case)

    # Run filtered cases
    runner = TestRunner()
    await runner.initialize()
    try:
        for case in filtered_cases:
            result = await runner.run_case(case)
            print(f"{case.id}: {result.status}")
    finally:
        await runner.cleanup()


if __name__ == "__main__":
    print("Choose an example:\n")
    print("1. Test case compilation demo")
    print("2. Custom assertions demo")
    print("3. Dynamic test generation")
    print("4. Conditional testing")

    choice = input("\nEnter choice (1-4): ")

    if choice == "1":
        demo_test_case_compilation()
    elif choice == "2":
        asyncio.run(demo_custom_assertions())
    elif choice == "3":
        asyncio.run(demo_dynamic_test_generation())
    elif choice == "4":
        asyncio.run(demo_conditional_testing())
    else:
        print("Invalid choice")
