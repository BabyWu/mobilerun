"""
Example: Batch testing multiple apps with parallel execution.

This demonstrates how to test multiple apps efficiently using
resource reuse and optional parallel execution.
"""

import asyncio
from pathlib import Path
from mobilerun_autotest import TestRunner, load_cases
from mobilerun.config_manager import MobileConfig, AgentConfig


async def test_app_suite(app_name: str, suite: str = "smoke"):
    """
    Test a single app's test suite.

    Args:
        app_name: App identifier (e.g., "app1", "app2")
        suite: Test suite name

    Returns:
        Exit code (0 = pass, 1 = fail)
    """
    print(f"\n{'='*60}")
    print(f"Testing {app_name.upper()} - {suite} suite")
    print('='*60)

    # Custom config per app if needed
    config = MobileConfig(
        agent=AgentConfig(
            provider="anthropic",
            model="claude-3-5-sonnet-20241022",
            reasoning=False,
        ),
    )

    runner = TestRunner(
        config=config,
        cases_dir=Path(f"./projects/{app_name}/cases"),
        report_dir=Path(f"./batch-reports/{app_name}"),
    )

    return await runner.run_suite(suite)


async def batch_test_sequential():
    """Test multiple apps sequentially."""
    apps = ["app1", "app2", "app3"]

    results = {}
    for app in apps:
        try:
            exit_code = await test_app_suite(app, "smoke")
            results[app] = "PASS" if exit_code == 0 else "FAIL"
        except Exception as e:
            print(f"Error testing {app}: {e}")
            results[app] = "ERROR"

    # Summary
    print("\n" + "="*60)
    print("BATCH TEST SUMMARY")
    print("="*60)
    for app, status in results.items():
        icon = "✅" if status == "PASS" else "❌"
        print(f"{icon} {app}: {status}")


async def batch_test_parallel_devices():
    """
    Test multiple apps in parallel using different devices.

    Requires: Multiple connected devices or emulators
    """
    # Define app-to-device mapping
    test_configs = [
        {"app": "app1", "device": "emulator-5554"},
        {"app": "app2", "device": "emulator-5556"},
        {"app": "app3", "device": "192.168.1.100:5555"},  # WiFi device
    ]

    async def run_on_device(app: str, device: str):
        config = MobileConfig(agent=AgentConfig(reasoning=False))
        runner = TestRunner(
            config=config,
            device_id=device,
            cases_dir=Path(f"./projects/{app}/cases"),
            report_dir=Path(f"./parallel-reports/{app}_{device}"),
        )
        return await runner.run_suite("smoke")

    # Run all in parallel
    tasks = [
        run_on_device(cfg["app"], cfg["device"])
        for cfg in test_configs
    ]

    results = await asyncio.gather(*tasks, return_exceptions=True)

    # Summary
    print("\n" + "="*60)
    print("PARALLEL TEST SUMMARY")
    print("="*60)
    for i, cfg in enumerate(test_configs):
        result = results[i]
        if isinstance(result, Exception):
            print(f"❌ {cfg['app']} on {cfg['device']}: ERROR - {result}")
        else:
            status = "PASS" if result == 0 else "FAIL"
            icon = "✅" if result == 0 else "❌"
            print(f"{icon} {cfg['app']} on {cfg['device']}: {status}")


async def continuous_testing():
    """
    Example: Continuous testing with intervals.

    Useful for monitoring app stability over time.
    """
    app_name = "app1"
    interval_minutes = 30
    max_iterations = 10

    for i in range(max_iterations):
        print(f"\n{'='*60}")
        print(f"Continuous Test Round {i+1}/{max_iterations}")
        print('='*60)

        exit_code = await test_app_suite(app_name, "smoke")

        if exit_code != 0:
            print(f"⚠️  Test failed in round {i+1}")
            # Optional: send alert, log to monitoring system

        if i < max_iterations - 1:
            print(f"\n⏳ Waiting {interval_minutes} minutes until next round...")
            await asyncio.sleep(interval_minutes * 60)


if __name__ == "__main__":
    # Choose one example to run:

    # Sequential testing
    asyncio.run(batch_test_sequential())

    # Parallel testing (requires multiple devices)
    # asyncio.run(batch_test_parallel_devices())

    # Continuous monitoring
    # asyncio.run(continuous_testing())
