# Example: Using MobileRun AutoTest Programmatically

from pathlib import Path
from mobilerun_autotest import TestRunner, load_cases
from mobilerun.config_manager import MobileConfig, AgentConfig, DeviceConfig
import asyncio


async def run_custom_tests():
    """Example: Run tests with custom configuration."""

    # Create custom config
    config = MobileConfig(
        agent=AgentConfig(
            provider="anthropic",
            model="claude-3-5-sonnet-20241022",
            reasoning=False,
            max_steps=15,
        ),
        device=DeviceConfig(
            platform="android",
            serial=None,  # auto-detect
        ),
    )

    # Initialize runner
    runner = TestRunner(
        config=config,
        cases_dir="./cases",
        report_dir="./my-reports",
    )

    # Option 1: Run entire suite
    exit_code = await runner.run_suite("smoke")
    print(f"Suite exit code: {exit_code}")

    # Option 2: Run specific cases
    # await runner.initialize()
    # cases = load_cases("./cases", "smoke")
    # for case in cases:
    #     if case.id in ["open_settings", "portal_ping"]:
    #         result = await runner.run_case(case)
    #         print(f"{case.id}: {result.status}")
    # await runner.cleanup()


async def run_with_rate_limiting():
    """Example: Run tests with rate limiting."""

    runner = TestRunner(
        cases_dir="./cases",
        rate_limit=2.0,  # Max 2 agent executions per second
    )

    exit_code = await runner.run_suite("full")
    return exit_code


async def custom_test_flow():
    """Example: Custom test flow with manual control."""

    from mobilerun_autotest import TestCaseCompiler, SharedResources, CaseExecutor

    # Load test case
    cases = load_cases("./cases", "smoke")
    case = cases[0]

    # Initialize shared resources once
    shared = SharedResources()
    config = MobileConfig()
    await shared.initialize(config)

    try:
        # Compile goal
        compiler = TestCaseCompiler()
        goal = compiler.compile_goal(case)
        print(f"Compiled goal:\n{goal}\n")

        # Execute case
        executor = CaseExecutor(shared=shared, compiler=compiler)
        evidence_dir = Path("./evidence")
        evidence_dir.mkdir(exist_ok=True)

        result = await executor.execute(case, evidence_dir)

        print(f"Result: {result.status}")
        print(f"Detail: {result.detail}")
        print(f"Steps: {result.agent_steps}")

    finally:
        await shared.close()


if __name__ == "__main__":
    # Run one of the examples
    asyncio.run(run_custom_tests())
    # asyncio.run(run_with_rate_limiting())
    # asyncio.run(custom_test_flow())
