"""
TestRunner: Batch test suite runner with resource reuse.

Key design goals:
- Initialize shared resources ONCE for all test cases
- Sequential execution (safe for single device)
- Optional parallel execution for device pools
- Rate limiting to avoid LLM quota exhaustion
- Real-time progress reporting
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from pathlib import Path
from typing import Callable

try:
    from mobilerun.config_manager import MobileConfig
except ImportError:
    # mobilerun may not be installed yet; bootstrap installs it in __init__.
    MobileConfig = None


def _load_mobilerun_config(config_path: Path | str | None, print_fn=None):
    """
    Load a MobileConfig, installing mobilerun first if it is missing.

    Falls back to an all-defaults MobileConfig when no config file exists yet,
    which is the normal state for a tester who has not run `mobilerun configure`.
    """
    global MobileConfig

    from mobilerun_autotest.bootstrap import ensure_mobilerun

    ensure_mobilerun(need_cli=True, need_library=True, print_fn=print_fn)

    from mobilerun.config_manager import MobileConfig as _MobileConfig

    MobileConfig = _MobileConfig

    try:
        from mobilerun.config_manager.loader import ConfigLoader

        return ConfigLoader().load(config_path)
    except Exception as exc:  # noqa: BLE001 - any load failure falls back to defaults
        logger.debug("Config load failed (%s); using defaults", exc)
        from mobilerun.config_manager import (
            AgentConfig,
            DeviceConfig,
            LoggingConfig,
            ToolsConfig,
            TracingConfig,
        )

        return _MobileConfig(
            agent=AgentConfig(),
            device=DeviceConfig(),
            tools=ToolsConfig(),
            logging=LoggingConfig(),
            tracing=TracingConfig(),
        )

from mobilerun_autotest.compiler import TestCaseCompiler
from mobilerun_autotest.executor import CaseExecutor
from mobilerun_autotest.loader import load_cases
from mobilerun_autotest.models import (
    FAIL,
    FAILING,
    PASS,
    PENDING_AI,
    CaseResult,
    TestCase,
)
from mobilerun_autotest.report import ReportWriter
from mobilerun_autotest.shared import SharedResources

logger = logging.getLogger("mobilerun_autotest")

DEFAULT_REPORT_DIR = Path.cwd() / "autotest-reports"


class TestRunner:
    """
    Batch test suite runner.

    Resource lifecycle:
    - initialize() creates one SharedResources for entire suite
    - run_suite() / run_cases() execute cases reusing those resources
    - cleanup() closes driver and connections

    Example (CLI):
        runner = TestRunner(config=config)
        exit_code = asyncio.run(runner.run_suite("smoke"))

    Example (API):
        runner = TestRunner(config=config)
        await runner.initialize()
        result = await runner.run_case(case)
        await runner.cleanup()
    """

    def __init__(
        self,
        config: MobileConfig | None = None,
        config_path: Path | str | None = None,
        device_id: str | None = None,
        cases_dir: Path | str = "./cases",
        report_dir: Path | str | None = None,
        rate_limit: float | None = None,
        print_fn: Callable[[str], None] = print,
    ):
        """
        Create TestRunner.

        Args:
            config: MobileConfig instance (mutually exclusive with config_path)
            config_path: Path to mobilerun config.yaml (auto-detect if None)
            device_id: Device serial (auto-detect if None)
            cases_dir: Directory containing suite folders
            report_dir: Directory for reports (default: ./autotest-reports)
            rate_limit: Max agent executions per second (None = unlimited)
            print_fn: Output function for progress messages
        """
        self._config = config
        self._config_path = config_path
        self.device_id = device_id
        self.cases_dir = Path(cases_dir)
        self.report_dir = Path(report_dir) if report_dir else DEFAULT_REPORT_DIR
        self.rate_limit = rate_limit
        self.print_fn = print_fn

        self._shared: SharedResources | None = None
        self._compiler = TestCaseCompiler()
        self._last_run_time: float = 0.0

    @property
    def config(self) -> MobileConfig:
        """
        MobileConfig for this run, loaded on first use.

        Loading is deferred so offline commands (e.g. --show-goals) work without
        mobilerun installed; the first real access installs it if necessary.
        """
        if self._config is None:
            self._config = _load_mobilerun_config(self._config_path, print_fn=self.print_fn)
        return self._config

    @config.setter
    def config(self, value: MobileConfig) -> None:
        self._config = value

    async def initialize(self):
        """
        Initialize shared resources (driver, LLMs, etc.).

        Call once before running cases. Called automatically by run_suite().
        """
        self._shared = SharedResources()
        await self._shared.initialize(self.config, self.device_id)

    async def cleanup(self):
        """Close shared resources. Call after all cases complete."""
        if self._shared:
            await self._shared.close()
            self._shared = None

    async def run_suite(
        self,
        suite: str = "smoke",
        only: list[str] | None = None,
        stop_on_error: bool = False,
    ) -> int:
        """
        Load and run an entire test suite.

        Args:
            suite: Suite name ("smoke", "full", or "all")
            only: If given, run only these case IDs
            stop_on_error: Stop on first FAIL/ERROR

        Returns:
            0 if all cases passed, 1 if any failed
        """
        # Load cases
        suites = ["smoke", "full"] if suite == "all" else [suite]
        all_cases: list[TestCase] = []
        for s in suites:
            try:
                all_cases.extend(load_cases(self.cases_dir, s))
            except FileNotFoundError:
                if suite == "all":
                    # Skip missing suite directories in "all" mode
                    logger.debug(f"Suite '{s}' not found, skipping")
                    continue
                raise

        if not all_cases:
            self.print_fn(f"❌ No test cases found in {self.cases_dir}/{suite}")
            return 2

        if only:
            wanted = set(only)
            all_cases = [c for c in all_cases if c.id in wanted]
            if not all_cases:
                self.print_fn(f"❌ No cases matched --only {sorted(wanted)}")
                return 2

        return await self.run_cases(all_cases, suite=suite, stop_on_error=stop_on_error)

    async def run_cases(
        self,
        cases: list[TestCase],
        suite: str = "custom",
        stop_on_error: bool = False,
    ) -> int:
        """
        Run a list of test cases.

        Handles initialization, execution, reporting, and cleanup.

        Args:
            cases: List of TestCase to execute
            suite: Suite name for report naming
            stop_on_error: Stop on first FAIL/ERROR

        Returns:
            0 if all passed, 1 if any failed
        """
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        report_dir = self.report_dir / f"{stamp}_{suite}"
        report_dir.mkdir(parents=True, exist_ok=True)
        evidence_dir = report_dir / "evidence"
        evidence_dir.mkdir()

        writer = ReportWriter(report_dir, suite)

        # Initialize shared resources
        self.print_fn(f"\n🚀 MobileRun AutoTest v3.0")
        self.print_fn(f"📦 Suite: {suite} ({len(cases)} cases)")

        await self.initialize()

        try:
            for i, case in enumerate(cases, 1):
                # Rate limiting between cases
                if self.rate_limit and i > 1:
                    await self._enforce_rate_limit()

                # Print case header
                sep = "━" * 60
                self.print_fn(f"\n{sep}")
                self.print_fn(f"📦 [{i}/{len(cases)}] {case.id}")
                self.print_fn(f"📝 {case.title}")
                if case.pass_criteria:
                    self.print_fn(f"✓  {case.pass_criteria}")
                self.print_fn(sep)

                # Execute case
                try:
                    result = await self._execute_with_repeat(case, evidence_dir)
                except KeyboardInterrupt:
                    self.print_fn("⏹️ Interrupted — partial report saved")
                    break

                # Print result
                icon = _STATUS_ICON.get(result.status, "")
                self.print_fn(
                    f"\n  {icon} {result.status} ({result.run_seconds}s"
                    + (f", {result.agent_steps} agent steps" if result.agent_steps else "")
                    + ")"
                )
                if result.detail:
                    self.print_fn(f"  💬 {result.detail[:200]}")
                if result.trajectory_path:
                    self.print_fn(f"  📁 Trajectory: {result.trajectory_path}")

                writer.add(result)

                if stop_on_error and result.status in FAILING:
                    self.print_fn("⛔ --stop-on-error: aborting")
                    break

        finally:
            await self.cleanup()

        # Summary
        counts: dict[str, int] = {}
        for r in writer.results:
            counts[r.status] = counts.get(r.status, 0) + 1

        total = len(writer.results)
        failing = sum(counts.get(s, 0) for s in FAILING)
        pass_count = counts.get(PASS, 0)
        pending = counts.get(PENDING_AI, 0)

        self.print_fn("\n" + "═" * 60)
        self.print_fn(
            f"Summary: {total} run — "
            + "  ".join(f"{k}={v}" for k, v in sorted(counts.items()))
        )
        self.print_fn(f"📄 Report: {report_dir / 'report.md'}")
        self.print_fn(f"🧾 JSON:   {report_dir / 'report.json'}")

        if pending:
            self.print_fn(f"🤖 {pending} item(s) awaiting AI judgement")

        # Warn if zero PASS (all PENDING_AI or EXPECTED)
        if total > 0 and pass_count == 0:
            self.print_fn(
                "⚠️  WARNING: Zero cases PASSED. "
                "Check device connection and LLM config."
            )

        return 1 if failing else 0

    async def run_case(self, case: TestCase) -> CaseResult:
        """
        Execute a single test case (requires initialize() first).

        Args:
            case: TestCase to execute

        Returns:
            CaseResult with status and details
        """
        if self._shared is None:
            raise RuntimeError("call initialize() before run_case()")

        evidence_dir = Path.cwd() / "evidence"
        evidence_dir.mkdir(exist_ok=True)

        executor = CaseExecutor(shared=self._shared, compiler=self._compiler)
        return await executor.execute(case, evidence_dir)

    async def _execute_with_repeat(
        self, case: TestCase, evidence_dir: Path
    ) -> CaseResult:
        """Handle repeat>1 by running case multiple times and aggregating."""
        if case.repeat == 1:
            executor = CaseExecutor(shared=self._shared, compiler=self._compiler)
            return await executor.execute(case, evidence_dir)

        results: list[CaseResult] = []
        for attempt in range(case.repeat):
            self.print_fn(f"  🔁 Attempt {attempt + 1}/{case.repeat}")
            executor = CaseExecutor(shared=self._shared, compiler=self._compiler)
            r = await executor.execute(case, evidence_dir)
            results.append(r)

        # Aggregate: most common status, ties go to FAIL > ERROR > PASS
        from collections import Counter
        counts = Counter(r.status for r in results)
        priority = [FAIL, "ERROR", PENDING_AI, "EXPECTED", PASS, "SKIPPED"]
        final_status = max(
            counts.keys(),
            key=lambda s: (counts[s], -priority.index(s) if s in priority else 999),
        )

        attempts = [{"status": r.status, "detail": r.detail[:150]} for r in results]
        agg = CaseResult(case=case, status=final_status, attempts=attempts)
        agg.detail = f"repeat {case.repeat}: {dict(counts)}"
        agg.run_seconds = sum(r.run_seconds for r in results) / len(results)
        agg.verify_results = results[-1].verify_results
        agg.ai_judge_images = results[-1].ai_judge_images
        return agg

    async def _enforce_rate_limit(self):
        """Wait to respect rate_limit (executions per second)."""
        if not self.rate_limit:
            return
        min_interval = 1.0 / self.rate_limit
        elapsed = asyncio.get_event_loop().time() - self._last_run_time
        if elapsed < min_interval:
            await asyncio.sleep(min_interval - elapsed)
        self._last_run_time = asyncio.get_event_loop().time()

    def show_goals(self, suite: str = "smoke") -> None:
        """
        Print compiled goals without executing (for debugging).

        Args:
            suite: Suite name to load cases from
        """
        cases = load_cases(self.cases_dir, suite)
        for case in cases:
            print(self._compiler.format_for_debug(case))


# Status display icons
_STATUS_ICON = {
    PASS: "✅",
    FAIL: "❌",
    "ERROR": "💥",
    PENDING_AI: "🤖",
    "EXPECTED": "⚠️",
    "SKIPPED": "⏭️",
}
