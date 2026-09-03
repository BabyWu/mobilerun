"""
CaseExecutor: Execute a single test case using MobileAgent Python API.

Core design (from design doc):
- Agent Action + Deterministic Assertion (never trust agent self-evaluation)
- One test case = one MobileAgent.run(goal) call
- Driver/LLMs injected from SharedResources (reused, not re-created)
- setup/cleanup via shell commands, task via MobileAgent API
"""

from __future__ import annotations

import asyncio
import logging
import re
import shlex
import subprocess
import os
import time
from pathlib import Path
from typing import Any

try:
    from llama_index.core.workflow import StartEvent
    from mobilerun.agent.droid.droid_agent import MobileAgent
    from mobilerun.agent.droid.events import ResultEvent
except ImportError:
    # For standalone testing without full mobilerun installation
    StartEvent = None
    MobileAgent = None
    ResultEvent = None

from mobilerun_autotest.compiler import TestCaseCompiler
from mobilerun_autotest.models import (
    ERROR,
    EXPECTED,
    FAIL,
    FAILING,
    PASS,
    PENDING_AI,
    SKIPPED,
    CaseResult,
    RequireItem,
    TestCase,
    VerifyItem,
)
from mobilerun_autotest.shared import SharedResources

logger = logging.getLogger("mobilerun_autotest")

# Timeout constants (seconds)
_SETUP_LINE_TIMEOUT = 120
_CLEANUP_LINE_TIMEOUT = 300
_VERIFY_CMD_TIMEOUT = 180
_REQUIRES_CMD_TIMEOUT = 60

# Marker for AI vision items that need external judgment
AI_JUDGE_MARKER = "[AI-JUDGE-REQUIRED]"


class CaseExecutor:
    """
    Executes a single test case.

    Execution flow:
    1. requires  – machine-checkable preconditions (→ SKIPPED if not met)
    2. setup     – shell commands before task
    3. task      – MobileAgent.run(compiled_goal)
    4. verify    – deterministic assertions (never trust Agent self-eval)
    5. cleanup   – shell commands, always runs
    """

    def __init__(self, shared: SharedResources, compiler: TestCaseCompiler):
        self.shared = shared
        self.compiler = compiler

    async def execute(self, case: TestCase, evidence_dir: Path) -> CaseResult:
        """
        Execute one test case end-to-end.

        Args:
            case: TestCase to execute
            evidence_dir: Directory to save screenshots and artifacts

        Returns:
            CaseResult with status, details, and evidence paths
        """
        result = CaseResult(case=case)
        start = time.monotonic()

        try:
            # 1. Check requires (environment preconditions)
            if case.requires:
                skip_detail = await self._check_requires(case.requires)
                if skip_detail:
                    result.status = SKIPPED
                    result.detail = skip_detail
                    return result

            # 2. Execute setup commands
            if case.setup:
                ok, err = self._run_shell_lines(
                    case.setup.splitlines(),
                    timeout_each=_SETUP_LINE_TIMEOUT,
                )
                if not ok:
                    result.status = ERROR
                    result.detail = f"setup failed: {err}"
                    return result

            # 3. Execute task via MobileAgent (core)
            run_failed = False
            if case.task or case.steps:
                goal = self.compiler.compile_goal(case)
                result.compiled_goal = goal

                try:
                    agent_result = await self._run_agent(case, goal)
                    result.run_exit_code = 0 if agent_result.success else 1
                    result.agent_steps = agent_result.steps
                    # Extract last 300 chars of reason for detail
                    result.detail = (agent_result.reason or "")[-300:]

                    if not agent_result.success:
                        run_failed = True

                except asyncio.TimeoutError:
                    result.run_timed_out = True
                    result.run_exit_code = 124
                    result.detail = f"agent timed out after {case.timeout}s"
                    run_failed = True
                    logger.warning(f"⏱️ Case {case.id} timed out after {case.timeout}s")

                except Exception as e:
                    result.run_exit_code = 1
                    result.detail = f"agent error: {e}"
                    run_failed = True
                    logger.error(f"❌ Case {case.id} agent error: {e}")

            # 4. Verify (deterministic assertions - never trust Agent self-eval)
            captures: dict[str, str] = {}
            statuses: list[str] = []

            skip_ai_judge = result.run_timed_out

            for idx, item in enumerate(case.verify, 1):
                vr = await self._run_verify_item(
                    item, idx, case.id, evidence_dir, captures, skip_ai_judge
                )
                result.verify_results.append(vr)
                s = vr.get("status", FAIL)
                statuses.append(s)

                if s == PENDING_AI and vr.get("image"):
                    result.ai_judge_images.append(vr["image"])

            # 5. Determine overall status
            result.status = _determine_status(
                statuses=statuses,
                run_failed=run_failed,
                run_timed_out=result.run_timed_out,
                timeout=case.timeout,
                detail=result.detail,
            )
            if run_failed and result.status == FAIL:
                pass  # detail already set

            # known_limits: downgrade FAIL/ERROR to EXPECTED
            if result.status in FAILING and case.known_limits:
                haystack = " ".join(
                    [result.detail]
                    + [str(v.get("detail", "")) for v in result.verify_results]
                )
                if case.known_limits.matches(haystack):
                    result.status = EXPECTED
                    result.detail = (
                        f"known limit: {case.known_limits.describe()} | {result.detail}"
                    )

        finally:
            # cleanup always runs (never changes verdict)
            if case.cleanup:
                ok, err = self._run_shell_lines(
                    case.cleanup.splitlines(),
                    timeout_each=_CLEANUP_LINE_TIMEOUT,
                )
                if not ok:
                    logger.warning(f"⚠️ Cleanup failed for {case.id}: {err}")

            result.run_seconds = round(time.monotonic() - start, 1)

        return result

    async def _run_agent(self, case: TestCase, goal: str) -> ResultEvent:
        """
        Run MobileAgent with compiled goal, injecting shared resources.

        Args:
            case: TestCase with run_flags
            goal: Compiled natural language goal

        Returns:
            ResultEvent from MobileAgent
        """
        case_config = self.shared.merge_run_flags(case.run_flags)

        agent = MobileAgent(
            goal=goal,
            config=case_config,
            llms=self.shared.llms,                        # Reuse LLMs
            driver=self.shared.driver,                    # Reuse driver
            state_provider=self.shared.state_provider,   # Reuse state provider
            timeout=case.timeout,
        )

        # Run with timeout
        handler = agent.run(StartEvent())

        result = await asyncio.wait_for(
            handler,
            timeout=case.timeout + 10,  # small buffer beyond agent timeout
        )
        return result

    async def _check_requires(self, requires: list[RequireItem]) -> str | None:
        """
        Check machine-verifiable preconditions.

        Returns:
            None if all met, error string if any failed
        """
        for item in requires:
            code, stdout, stderr = _run_cmd(
                shlex.split(item.cmd, posix=True),
                timeout=_REQUIRES_CMD_TIMEOUT,
            )
            output = stdout or stderr

            # Check expectations
            if item.expect_contains:
                if not any(s in output for s in item.expect_contains):
                    desc = item.description or item.cmd
                    return f"requires not met: {desc} | none of {item.expect_contains!r} found"

            elif item.expect_regex:
                if not re.search(item.expect_regex, output, re.MULTILINE):
                    desc = item.description or item.cmd
                    return f"requires not met: {desc} | regex {item.expect_regex!r} not matched"

        return None

    def _run_shell_lines(
        self, lines: list[str], timeout_each: int
    ) -> tuple[bool, str]:
        """
        Execute shell command lines sequentially.

        Returns:
            (success, error_message)
        """
        for line in lines:
            line = line.strip()
            if not line or line.startswith("#"):
                continue

            argv = shlex.split(line, posix=True)
            if not argv:
                continue

            code, stdout, stderr = _run_cmd(argv, timeout=timeout_each)
            if code != 0:
                msg = (stderr.strip() or stdout.strip())[:200]
                return False, f"`{line}` exited {code}: {msg}"

        return True, ""

    async def _run_verify_item(
        self,
        item: VerifyItem,
        idx: int,
        case_id: str,
        evidence_dir: Path,
        captures: dict[str, str],
        skip_ai_judge: bool,
    ) -> dict[str, Any]:
        """
        Execute one verify item and return result dict.

        Args:
            item: VerifyItem to execute
            idx: Item index (for unique naming)
            case_id: Parent case ID
            evidence_dir: Directory for evidence files
            captures: Mutable dict for ${name} interpolation
            skip_ai_judge: Skip AI items if run timed out

        Returns:
            Dict with status, detail, and optional image/captured fields
        """
        vr: dict[str, Any] = {"description": item.description}

        # AI vision judgment
        if item.judge == "ai_vision":
            if skip_ai_judge:
                vr.update(
                    status="SKIPPED",
                    detail="run timed out — screenshot skipped",
                )
                return vr

            # Take screenshot for AI
            code, stdout, _ = _run_cmd(
                ["mobilerun", "device", "screenshot"],
                timeout=120,
            )
            shot = stdout.strip().splitlines()[-1] if stdout.strip() else ""
            saved = None

            if code == 0 and shot and Path(shot).is_file():
                dest = evidence_dir / f"{case_id}-ai-judge-{idx}.png"
                try:
                    import shutil
                    shutil.copy2(shot, dest)
                    saved = str(dest)
                except Exception as e:
                    logger.warning(f"Failed to copy screenshot: {e}")

            if saved:
                logger.info(f"  {AI_JUDGE_MARKER} case={case_id} image={saved}")
                vr.update(status=PENDING_AI, image=saved)
            else:
                vr.update(status=ERROR, detail="failed to capture screenshot")

            return vr

        # Command-based verification
        if item.cmd:
            cmd = item.cmd
            # Interpolate ${name} placeholders
            for name, value in captures.items():
                cmd = cmd.replace(f"${{{name}}}", value)

            argv = shlex.split(cmd, posix=True)
            code, stdout, stderr = _run_cmd(argv, timeout=_VERIFY_CMD_TIMEOUT)
            output = stdout or stderr

            # Handle save_to
            if item.save_to:
                last_line = output.strip().splitlines()[-1] if output.strip() else ""
                saved = None
                if last_line and Path(last_line).is_file():
                    dest = evidence_dir / item.save_to
                    try:
                        import shutil
                        shutil.copy2(last_line, dest)
                        saved = str(dest)
                    except Exception as e:
                        logger.warning(f"Failed to copy evidence: {e}")

                vr.update(
                    status=PASS,
                    detail=f"saved {saved}" if saved else "save failed",
                    save_to=saved,
                )
                return vr

            # Check expectations
            ok, why = _check_expectations(output, item)

            # Handle capture
            if item.capture:
                extracted = _extract_capture(output, item.capture_from)
                captures[item.capture] = extracted
                vr["captured"] = {item.capture: extracted[:200]}

            vr.update(status=PASS if ok else FAIL, detail=why)
            return vr

        # Neither cmd nor judge — this shouldn't happen after validation
        vr.update(status=ERROR, detail="invalid verify item: no cmd or judge")
        return vr


# ---------------------------------------------------------------------------
# Status determination
# ---------------------------------------------------------------------------

def _determine_status(
    statuses: list[str],
    run_failed: bool,
    run_timed_out: bool,
    timeout: int,
    detail: str,
) -> str:
    """Determine overall case status from component outcomes."""
    if run_timed_out:
        return FAIL

    if ERROR in statuses:
        return ERROR

    if FAIL in statuses:
        return FAIL

    pending = [s for s in statuses if s == PENDING_AI]
    if pending:
        return PENDING_AI

    if run_failed and not any(s == PASS for s in statuses):
        return FAIL

    # run non-zero but verify passed → trust independent verification
    return PASS


# ---------------------------------------------------------------------------
# Shell helpers
# ---------------------------------------------------------------------------

def _run_cmd(
    argv: list[str],
    timeout: int,
) -> tuple[int, str, str]:
    """Run a command and return (exit_code, stdout, stderr)."""
    env = os.environ.copy()
    env.setdefault("PYTHONUTF8", "1")
    try:
        proc = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            env=env,
        )
        return proc.returncode, proc.stdout, proc.stderr
    except subprocess.TimeoutExpired:
        return 124, "", f"timeout after {timeout}s"
    except FileNotFoundError as e:
        return 127, "", str(e)


def _check_expectations(output: str, item: VerifyItem) -> tuple[bool, str]:
    """Check verify item expectations against command output."""
    if item.expect_contains:
        hits = [s for s in item.expect_contains if s in output]
        if hits:
            return True, f"matched: {hits[0]!r}"
        return False, f"none of {item.expect_contains!r} found in output"

    if item.expect_regex:
        m = re.search(item.expect_regex, output, re.MULTILINE)
        if m:
            return True, f"regex matched: {m.group(0)[:80]!r}"
        return False, f"regex {item.expect_regex!r} not matched"

    return True, "save_to / capture only (no expectation)"


def _extract_capture(stdout: str, capture_from: str) -> str:
    """Extract captured value per capture_from rule."""
    if capture_from == "last_line":
        lines = stdout.strip().splitlines()
        return lines[-1] if lines else ""
    if capture_from == "first_line":
        lines = stdout.strip().splitlines()
        return lines[0] if lines else ""
    if capture_from == "all":
        return stdout
    if capture_from.startswith("regex:"):
        expr = capture_from[len("regex:"):]
        m = re.search(expr, stdout, re.MULTILINE)
        if not m:
            return ""
        return m.group(1) if m.lastindex and m.lastindex >= 1 else m.group(0)
    return ""
