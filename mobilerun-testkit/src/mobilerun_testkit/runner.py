#!/usr/bin/env python3
"""Deterministic batch runner for mobilerun regression cases.

Reads YAML case files from cases/<suite>/, executes each one
(setup -> mobilerun run -> verify -> cleanup), and writes incremental
JSON + Markdown reports under reports/<timestamp>_<suite>/.

Mobilerun is treated as a black-box CLI: the only contract is the public
``mobilerun`` command (run / device / ping / macro / devices) and its exit
codes, so this testkit works with any mobilerun install and can be
distributed independently.

The heavy lifting (command execution, ordering, evidence collection) is
deterministic here. Judgement calls that need vision are emitted as
``[AI-JUDGE-REQUIRED]`` marker lines — see SKILL.md (next to this package)
for the AI-side protocol.

Usage:
    mobilerun-test --suite smoke
    mobilerun-test --suite full --device emulator-5554
    mobilerun-test --suite all --only ping --only vision
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

try:
    from mobilerun_testkit._lib import (
        CaseResult,
        TestCase,
        VerifyItem,
        _RUN_FLAG_KEYS,
        _BOOL_FLAGS,
        _ON_OFF_FLAGS,
        load_cases,
    )
except ImportError:  # running as a plain script from src/mobilerun_testkit/
    from _lib import (  # type: ignore
        CaseResult,
        TestCase,
        VerifyItem,
        _RUN_FLAG_KEYS,
        _BOOL_FLAGS,
        _ON_OFF_FLAGS,
        load_cases,
    )

# Cases ship inside the installed package; a sibling ./cases (e.g. a cloned
# repo checkout) takes precedence so users can edit/add cases without
# reinstalling.
_PKG_DIR = Path(__file__).resolve().parent
_DEFAULT_CASES = next(
    (
        p
        for p in [
            _PKG_DIR.parents[1] / "cases",  # <repo>/mobilerun-testkit/cases
            _PKG_DIR.parent / "cases",  # src layout sibling
            _PKG_DIR / "cases",  # flat layout
            Path(__import__("sys").prefix) / "share" / "mobilerun-testkit" / "cases",
        ]
        if p.is_dir()
    ),
    _PKG_DIR / "cases",
)
DEFAULT_REPORT_DIR = Path.cwd() / "mobilerun-testkit-reports"

AI_JUDGE_MARKER = "[AI-JUDGE-REQUIRED]"

# The mobilerun CLI to invoke. Overridable with --mobilerun-bin / MOBILERUN_BIN
# (e.g. a wrapper script or a non-PATH install).
MOBILERUN_BIN = os.environ.get("MOBILERUN_BIN", "mobilerun")

# Case statuses
PASS = "PASS"
FAIL = "FAIL"
ERROR = "ERROR"
PENDING_AI = "PENDING_AI"
EXPECTED = "EXPECTED"
SKIPPED = "SKIPPED"

_FAILING = {FAIL, ERROR}

# Exit code run_cmd synthesises for a subprocess timeout (mirrors `timeout(1)`).
TIMEOUT_EXIT = 124


# ---------------------------------------------------------------------------
# subprocess helpers
# ---------------------------------------------------------------------------


def _force_utf8_stdio() -> None:
    """Reconfigure stdout/stderr to UTF-8 so emoji / Chinese text survive on a
    GBK console (Chinese Windows defaults cp936). errors="replace" guarantees
    print() can never raise UnicodeEncodeError — which used to crash the
    runner itself before the preflight even started."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError):
            pass  # not a TextIOWrapper (e.g. captured); nothing to fix


def run_cmd(
    cmd: list[str] | str,
    timeout: int,
    shell: bool = False,
) -> tuple[int, str, str]:
    """Run a command, return (exit_code, stdout, stderr). Never raises for
    non-zero exit; raises only for launch failures (handled by caller)."""
    env = os.environ.copy()
    # mobilerun is a Python CLI: on a GBK console (Chinese Windows) rich
    # crashes printing "•", truncating output like `mobilerun devices` so a
    # connected device looks absent. PYTHONUTF8=1 fixes it at the source, so
    # the user never needs to "retry with PYTHONUTF8=1" manually. Non-Python
    # subprocesses simply ignore the variable.
    env.setdefault("PYTHONUTF8", "1")
    try:
        proc = subprocess.run(
            cmd,
            shell=shell,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            env=env,
        )
        return proc.returncode, proc.stdout, proc.stderr
    except subprocess.TimeoutExpired:
        return TIMEOUT_EXIT, "", f"timeout after {timeout}s"
    except FileNotFoundError as e:
        return 127, "", str(e)


# Subcommands that declare a --device/-d option. `--device` belongs to the
# leaf subcommand, not the top-level group (`mobilerun --device ...` is an
# error), so it is appended after the subcommand path — and only for these.
# Verified against mobilerun/cli/main.py, cli/device_commands.py, macro/cli.py.
_DEVICE_AWARE = frozenset(
    {
        ("run",),
        ("ping",),
        ("setup",),
        ("doctor",),
        ("macro", "replay"),
    }
)
# Every `mobilerun device <x>` leaf takes --device via the device_options decorator.
_DEVICE_GROUP = "device"


def _accepts_device(argv: list[str]) -> bool:
    """True when this mobilerun subcommand declares --device."""
    words = tuple(a for a in argv[1:] if not a.startswith("-"))
    if not words:
        return False
    if words[0] == _DEVICE_GROUP:
        return True
    return words[:1] in _DEVICE_AWARE or words[:2] in _DEVICE_AWARE


def build_mobilerun_argv(cmd: str | list[str], device: str | None) -> list[str]:
    """Normalise a case-authored command into an argv for subprocess.

    Shared by setup / task / verify / cleanup / screenshot so every path
    behaves identically:
    - a leading ``mobilerun`` is rewritten to MOBILERUN_BIN (honours
      --mobilerun-bin / MOBILERUN_BIN);
    - ``--device`` is appended for subcommands that accept it, unless the
      case already passed one, so verify asserts against the *same* device
      the task ran on;
    - strings are split with shlex so quoted arguments survive.
    """
    # posix=True even on Windows: it strips quote chars from tokens, and
    # subprocess.list2cmdline re-quotes them for the Win32 command line.
    # posix=False would leave literal quote characters inside tokens.
    argv = list(cmd) if isinstance(cmd, list) else shlex.split(cmd, posix=True)
    if not argv:
        return argv
    if argv[0] == "mobilerun":
        argv[0] = MOBILERUN_BIN
    if argv[0] == MOBILERUN_BIN and device and _accepts_device(argv):
        if not any(a in ("-d", "--device") for a in argv):
            argv += ["--device", device]
    return argv


def build_run_command(case: TestCase, device: str | None, overrides: dict) -> list[str]:
    """Assemble the ``mobilerun run ...`` argv for a case's task."""
    argv = [MOBILERUN_BIN, "run", case.task]
    flags = dict(case.run_flags)
    flags.update(overrides)
    for key in sorted(_RUN_FLAG_KEYS):
        if key not in flags:
            continue
        flag = _RUN_FLAG_KEYS[key]
        value = flags[key]
        if key in _BOOL_FLAGS:
            # click declares these as --vision/--no-vision style pairs
            argv.append(flag if value else "--no-" + flag[2:])
        elif key in _ON_OFF_FLAGS:
            # click declares these as is_flag=True — there is no --no-x form
            if value:
                argv.append(flag)
        else:
            argv += [flag, str(value)]
    if device:
        argv += ["--device", device]
    return argv


def screenshot_argv(device: str | None) -> list[str]:
    """argv for a device screenshot (stdout = saved file path)."""
    return build_mobilerun_argv([MOBILERUN_BIN, "device", "screenshot"], device)


# ---------------------------------------------------------------------------
# Execution of a single case
# ---------------------------------------------------------------------------


def _run_shell_lines(lines: list[str], device: str | None, timeout_each: int) -> tuple[bool, str]:
    """Run setup/cleanup lines; returns (all_ok, first_error_or_empty).

    Uses the shared argv builder so setup/cleanup resolve the binary and
    --device exactly like verify and the task do."""
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        argv = build_mobilerun_argv(line, device)
        if not argv:
            continue
        code, out, err = run_cmd(argv, timeout=timeout_each)
        if code != 0:
            return False, f"`{line}` exited {code}: {err.strip() or out.strip()[:200]}"
    return True, ""


def _copy_evidence(src: Path, evidence_dir: Path, name: str) -> str | None:
    if not src.is_file():
        return None
    dest = evidence_dir / name
    shutil.copy2(src, dest)
    return str(dest)


def _check_expectations(stdout: str, item: VerifyItem) -> tuple[bool, str]:
    if item.expect_contains:
        hits = [s for s in item.expect_contains if s in stdout]
        if hits:
            return True, f"matched: {hits[0]!r}"
        return False, "none of expect_contains found in output"
    if item.expect_regex:
        m = re.search(item.expect_regex, stdout, re.MULTILINE)
        if m:
            return True, f"regex matched: {m.group(0)[:80]!r}"
        return False, f"regex {item.expect_regex!r} not matched"
    return True, "save_to / capture only (no expectation)"


def _check_requires(item, device: str | None) -> tuple[bool, str]:
    """Check one requires item. Returns (met, detail)."""
    from mobilerun_testkit._lib import RequireItem
    code, out, err = run_cmd(build_mobilerun_argv(item.cmd, device), timeout=60)
    output = out or err
    if item.expect_contains:
        hits = [s for s in item.expect_contains if s in output]
        if hits:
            return True, f"matched: {hits[0]!r}"
        return False, f"none of {item.expect_contains!r} found"
    if item.expect_regex:
        m = re.search(item.expect_regex, output, re.MULTILINE)
        if m:
            return True, f"regex matched: {m.group(0)[:60]!r}"
        return False, f"regex {item.expect_regex!r} not matched"
    return True, "no assertion"


def _extract_capture(stdout: str, capture_from: str) -> str:
    """Extract the captured substring per the capture_from rule."""
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


def _execute_once(
    case: TestCase,
    device: str | None,
    overrides: dict,
    evidence_dir: Path,
    captures: dict[str, str],
    print_fn=print,
) -> CaseResult:
    """Execute a case once. ``captures`` holds ${name} interpolation state and
    is mutated when a verify item declares ``capture: name``."""
    result = CaseResult(case=case)
    start = time.monotonic()

    try:
        # --- setup -----------------------------------------------------
        if case.setup:
            print_fn(f"  📋 Setup:")
            for line in case.setup.splitlines():
                line = line.strip()
                if line and not line.startswith("#"):
                    print_fn(f"     → {line}")
            ok, err = _run_shell_lines(case.setup.splitlines(), device, timeout_each=120)
            if not ok:
                result.status = ERROR
                result.detail = f"setup failed: {err}"
                print_fn(f"     ❌ Setup failed: {err}")
                return result
            print_fn(f"     ✅ Setup completed")

        # --- task (mobilerun run) -------------------------------------
        run_failed = False
        if case.task:
            argv = build_run_command(case, device, overrides)
            print_fn(f"  🎯 Task: {case.task}")
            print_fn(f"     → {' '.join(argv)}")
            code, out, err = run_cmd(argv, timeout=case.timeout)
            result.run_exit_code = code
            result.run_seconds = round(time.monotonic() - start, 1)
            tail = (out or err).strip().splitlines()[-3:]
            result.detail = " | ".join(tail)[-300:]
            if code != 0:
                run_failed = True
                print_fn(f"     ❌ Task exited with code {code}")
            else:
                print_fn(f"     ✅ Task completed (exit code 0)")
            if code == TIMEOUT_EXIT:
                result.run_timed_out = True
                print_fn(f"     ⏱️ Task timed out after {case.timeout}s")

        # A timed-out run left the device mid-task: the screen shows whatever
        # was on it when we killed the agent, so it is not evidence of the end
        # state. Judging that screenshot invites a bogus verdict, so skip AI
        # judgement entirely (items record SKIPPED). The timeout itself is
        # recorded in the detail below and counts as a run failure.
        skip_ai_judge = result.run_timed_out

        # --- verify ----------------------------------------------------
        if case.verify:
            print_fn(f"  🔍 Verify: ({len(case.verify)} checks)")
        statuses: list[str] = []
        for idx, item in enumerate(case.verify, 1):
            vr: dict = {"description": item.description}
            desc_display = item.description or f"check #{idx}"

            if item.judge == "ai_vision":
                print_fn(f"     [{idx}] {desc_display} (AI vision)")
                if skip_ai_judge:
                    vr.update(
                        status=SKIPPED,
                        detail=(
                            f"run timed out after {case.timeout}s — screenshot would "
                            f"show a mid-task screen, so AI judgement was skipped"
                        ),
                    )
                    statuses.append(SKIPPED)
                    result.verify_results.append(vr)
                    print_fn(f"         ⏭️ Skipped (run timed out)")
                    continue
                # take a screenshot for the AI to judge
                print_fn(f"         📸 Taking screenshot...")
                code, out, _err = run_cmd(screenshot_argv(device), timeout=120)
                shot = out.strip().splitlines()[-1] if out.strip() else ""
                saved = None
                if code == 0 and shot and Path(shot).is_file():
                    # index the name so multiple ai_vision items never collide
                    saved = _copy_evidence(
                        Path(shot), evidence_dir, f"{case.id}-ai-judge-{idx}.png"
                    )
                if saved:
                    result.ai_judge_images.append(saved)
                    print_fn(f"  {AI_JUDGE_MARKER} case={case.id} image={saved}")
                    vr.update(status=PENDING_AI, image=saved)
                    statuses.append(PENDING_AI)
                    print_fn(f"         🤖 Pending AI judgement")
                else:
                    vr.update(status=ERROR, detail="failed to capture screenshot")
                    statuses.append(ERROR)
                    print_fn(f"         ❌ Failed to capture screenshot")
                result.verify_results.append(vr)
                continue

            # Interpolate ${name} placeholders from prior captures before running.
            cmd = item.cmd
            for name, value in captures.items():
                cmd = cmd.replace(f"${{{name}}}", value)

            print_fn(f"     [{idx}] {desc_display}")
            print_fn(f"         → {cmd}")
            code, out, err = run_cmd(build_mobilerun_argv(cmd, device), timeout=180)
            output = out or err
            ok, why = _check_expectations(output, item)
            vr.update(status=PASS if ok else FAIL, detail=why)
            if item.capture:
                extracted = _extract_capture(output, item.capture_from)
                captures[item.capture] = extracted
                vr["captured"] = {item.capture: extracted[:200]}
                print_fn(f"         💾 Captured '{item.capture}': {extracted[:100]}")
            if item.save_to:
                # stdout of screenshot is a file path on its own line
                last = output.strip().splitlines()[-1] if output.strip() else ""
                saved = (
                    _copy_evidence(Path(last), evidence_dir, item.save_to)
                    if last and Path(last).is_file()
                    else None
                )
                vr.update(save_to=str(saved) if saved else None,
                          detail=(vr.get("detail", "") + (f"; saved {saved}" if saved else "; save failed")))

            status_icon = "✅" if ok else "❌"
            print_fn(f"         {status_icon} {why}")
            statuses.append(PASS if ok else FAIL)
            result.verify_results.append(vr)

        # --- overall status --------------------------------------------
        pending = [s for s in statuses if s == PENDING_AI]
        if result.run_timed_out:
            # A timeout is a failure of the case itself (agent too slow /
            # stuck), independent of what any verify item found — the screen
            # at kill time proves nothing. Cases with a solid deterministic
            # assertion can still rescue this later via the run_failed-but-
            # verify-passed branch... they can't: timeout outranks it, by
            # design — a killed run's end state is unknown.
            result.status = FAIL
            result.detail = (f"run timed out after {case.timeout}s | " + result.detail).strip(" |")
        elif run_failed and not any(s == PASS for s in statuses):
            result.status = FAIL
        elif ERROR in statuses:
            result.status = ERROR
        elif FAIL in statuses:
            result.status = FAIL
        elif pending:
            # Any unjudged vision item keeps the whole case pending — a mixed
            # case must not report PASS on the strength of its cmd assertions
            # while the visual half is still unresolved.
            result.status = PENDING_AI
            if run_failed:
                result.detail = (result.detail + " | run exited non-zero").strip(" |")
        elif run_failed:
            # run exited non-zero but a verify assertion still passed →
            # trust the independent verification over the agent's exit code.
            result.status = PASS
            result.detail = (result.detail + " | run exited non-zero but verify passed").strip(" |")
        else:
            result.status = PASS

        # Known limits only absolve a failure when they *match* it. A bare
        # description documents the caveat but never downgrades the status,
        # so a mis-written case can no longer hide behind it.
        limit = case.known_limits
        if result.status in _FAILING and limit is not None:
            haystack = " ".join(
                [result.detail or ""] + [str(v.get("detail") or "") for v in result.verify_results]
            )
            if limit.matches(haystack):
                result.status = EXPECTED
                result.detail = f"known limit: {limit.describe()} | {result.detail}"
            elif limit.pattern:
                result.detail = (
                    f"{result.detail} | known_limits.pattern "
                    f"{limit.pattern!r} did not match this failure"
                ).strip(" |")

    finally:
        # --- cleanup (best effort, never changes the verdict) ----------
        if case.cleanup:
            print_fn(f"  🧹 Cleanup:")
            for line in case.cleanup.splitlines():
                line = line.strip()
                if line and not line.startswith("#"):
                    print_fn(f"     → {line}")
            ok, err = _run_shell_lines(case.cleanup.splitlines(), device, timeout_each=300)
            if not ok:
                print_fn(f"     ⚠️ Cleanup failed: {err}")
            else:
                print_fn(f"     ✅ Cleanup completed")
        # Stamp elapsed time inside finally so early returns (setup failure)
        # also carry a real duration instead of 0.0.
        result.run_seconds = round(time.monotonic() - start, 1)
    return result


def execute_case(
    case: TestCase,
    device: str | None,
    overrides: dict,
    evidence_dir: Path,
    print_fn=print,
) -> CaseResult:
    """Execute a case, handling requires and repeat.

    - If any ``requires`` item fails, the case is marked SKIPPED (not ERROR),
      so an environment gap does not look like a product regression.
    - If ``repeat > 1``, run the case N times and aggregate: final status is
      the most common outcome, and attempts are recorded for pass-rate calc.
    """
    # --- requires (machine-checkable preconditions) --------------------
    if case.requires:
        for item in case.requires:
            met, detail = _check_requires(item, device)
            if not met:
                r = CaseResult(case=case, status=SKIPPED)
                r.detail = f"requires not met: {item.description or item.cmd} | {detail}"
                return r

    # --- repeat loop ---------------------------------------------------
    captures: dict[str, str] = {}
    if case.repeat == 1:
        return _execute_once(case, device, overrides, evidence_dir, captures, print_fn)

    results = []
    for i in range(case.repeat):
        print_fn(f"  🔁 attempt {i+1}/{case.repeat}")
        r = _execute_once(case, device, overrides, evidence_dir, captures, print_fn)
        results.append(r)

    # Aggregate: final status is the most common, ties go to FAIL > ERROR > PASS.
    from collections import Counter
    counts = Counter(r.status for r in results)
    priority = [FAIL, ERROR, PENDING_AI, EXPECTED, PASS, SKIPPED]
    final_status = max(counts.keys(), key=lambda s: (counts[s], -priority.index(s) if s in priority else 999))

    attempts = [{"status": r.status, "detail": r.detail[:150]} for r in results]
    agg = CaseResult(case=case, status=final_status, attempts=attempts)
    agg.detail = f"repeat {case.repeat}: {dict(counts)} | last: {attempts[-1]['detail']}"
    agg.run_seconds = sum(r.run_seconds for r in results) / len(results)
    # Inherit verify_results and ai_judge_images from the last attempt.
    agg.verify_results = results[-1].verify_results
    agg.ai_judge_images = results[-1].ai_judge_images
    return agg


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

_STATUS_ICON = {
    PASS: "✅",
    FAIL: "❌",
    ERROR: "💥",
    PENDING_AI: "🤖",
    EXPECTED: "⚠️",
    SKIPPED: "⏭️",
}


class ReportWriter:
    """Incrementally rewrite report.json / report.md after every case."""

    def __init__(self, report_dir: Path, suite: str):
        self.dir = report_dir
        self.suite = suite
        self.json_path = report_dir / "report.json"
        self.md_path = report_dir / "report.md"
        self.results: list[CaseResult] = []
        self.started = datetime.now()

    def add(self, result: CaseResult) -> None:
        self.results.append(result)
        self.flush()

    def _summary(self) -> dict:
        counts: dict[str, int] = {}
        for r in self.results:
            counts[r.status] = counts.get(r.status, 0) + 1
        return {
            "suite": self.suite,
            "started": self.started.isoformat(timespec="seconds"),
            "device": _device_arg,
            "counts": counts,
            "cases": [
                {
                    "id": r.case.id,
                    "title": r.case.title,
                    "status": r.status,
                    "run_exit_code": r.run_exit_code,
                    "seconds": r.run_seconds,
                    "detail": r.detail,
                    "verify": r.verify_results,
                    "ai_judge_images": r.ai_judge_images,
                    "source_file": r.case.source_file,
                    "attempts": r.attempts if r.attempts else None,
                    "pass_rate": r.pass_rate() if r.attempts else None,
                }
                for r in self.results
            ],
        }

    def flush(self) -> None:
        self.json_path.write_text(
            json.dumps(self._summary(), ensure_ascii=False, indent=2), encoding="utf-8"
        )
        lines = [
            f"# Mobilerun 回归报告 — {self.suite}",
            "",
            f"- 开始时间: {self.started:%Y-%m-%d %H:%M:%S}",
            f"- 设备: `{_device_arg or 'auto'}`",
            "",
            "| 状态 | 用例 | 说明 | 耗时(s) | 通过率 | 详情 |",
            "|---|---|---|---|---|---|",
        ]
        for r in self.results:
            escaped_detail = (r.detail or "").replace("|", "\\|")[:160]
            pass_rate_cell = r.pass_rate() if r.attempts else ""
            lines.append(
                f"| {_STATUS_ICON.get(r.status, '')} {r.status} "
                f"| `{r.case.id}`<br>{r.case.title} "
                f"| {r.case.pass_criteria or ''} "
                f"| {r.run_seconds} "
                f"| {pass_rate_cell} "
                f"| {escaped_detail} |"
            )
        lines += [
            "",
            "## AI 判读 (PENDING_AI)",
            "",
        ]
        pending = [(r, v) for r in self.results for v in r.verify_results if v.get("status") == PENDING_AI]
        if not pending:
            lines.append("(无)")
        else:
            lines.append("| 用例 | 截图 | AI 判定 | 理由 |")
            lines.append("|---|---|---|---|")
            for r, v in pending:
                lines.append(
                    f"| `{r.case.id}` | `{v.get('image', '')}` | 待填写 | 待填写 |"
                )
        self.md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

_device_arg: str | None = None


def main() -> int:
    global _device_arg

    _force_utf8_stdio()

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite", choices=["smoke", "full", "all"], default="smoke")
    parser.add_argument("--device", "-d", default=None, help="device serial passed to mobilerun")
    parser.add_argument("--mobilerun-bin", default=None,
                        help="mobilerun CLI to invoke (default: MOBILERUN_BIN env or 'mobilerun')")
    parser.add_argument("--provider", default=None)
    parser.add_argument("--model", default=None)
    parser.add_argument("--cases-dir", default=None, type=Path,
                        help=f"directory containing smoke/ and full/ case folders (default: {_DEFAULT_CASES})")
    parser.add_argument("--report-dir", default=None, type=Path)
    parser.add_argument("--only", action="append", default=[], help="run only these case ids")
    parser.add_argument("--stop-on-error", action="store_true", help="abort suite on first FAIL/ERROR")
    parser.add_argument("--skip-preflight", action="store_true", help="skip the device preflight check")
    args = parser.parse_args()

    global MOBILERUN_BIN
    if args.mobilerun_bin:
        MOBILERUN_BIN = args.mobilerun_bin

    _device_arg = args.device
    overrides = {}
    if args.provider:
        overrides["provider"] = args.provider
    if args.model:
        overrides["model"] = args.model

    cases_dir = args.cases_dir or _DEFAULT_CASES
    suites = ["smoke", "full"] if args.suite == "all" else [args.suite]

    # Collect cases first so schema errors fail fast before touching devices.
    try:
        all_cases = []
        for suite in suites:
            all_cases += load_cases(cases_dir, suite)
    except (FileNotFoundError, ValueError) as e:
        print(f"❌ Case collection failed: {e}", file=sys.stderr)
        return 2

    if args.only:
        wanted = set(args.only)
        all_cases = [c for c in all_cases if c.id in wanted]
        if not all_cases:
            print(f"❌ No cases matched --only {sorted(wanted)}", file=sys.stderr)
            return 2

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_dir = args.report_dir or (DEFAULT_REPORT_DIR / f"{stamp}_{args.suite}")
    report_dir.mkdir(parents=True, exist_ok=True)
    evidence_dir = report_dir / "evidence"
    evidence_dir.mkdir(exist_ok=True)
    writer = ReportWriter(report_dir, args.suite)

    # Preflight: one cheap check for the whole suite.
    if not args.skip_preflight:
        print(f"🔎 Preflight: {MOBILERUN_BIN} devices ...")
        code, out, err = run_cmd([MOBILERUN_BIN, "devices"], timeout=60)
        combined = out + err
        # Match the "Found N local device(s)" count rather than the bullet
        # glyph: rich raises UnicodeEncodeError printing "•" on a non-UTF-8
        # console (e.g. GBK on Windows), which truncates the output and used
        # to make a connected device look absent.
        m = re.search(r"Found\s+(\d+)\s+local device", combined)
        has_device = bool(m) and int(m.group(1)) > 0
        if not has_device:
            print("❌ No device found (mobilerun devices). Run `mobilerun setup` first.")
            writer.flush()
            print(f"📄 Report: {report_dir / 'report.md'}")
            return 1
        print("✅ Device detected")

    print(f"🚀 Running {len(all_cases)} case(s): suite={args.suite}\n")
    for case_idx, case in enumerate(all_cases, 1):
        # Enhanced separator with case number for easier distinction
        separator = "━" * 70
        print(f"\n{separator}")
        print(f"📦 Test Case [{case_idx}/{len(all_cases)}]: {case.id}")
        print(f"📝 Title: {case.title}")
        if case.pass_criteria:
            print(f"✓  Pass Criteria: {case.pass_criteria}")
        print(separator)
        try:
            result = execute_case(case, args.device, overrides, evidence_dir, print_fn=print)
        except KeyboardInterrupt:
            print("⏹️ interrupted — partial report kept")
            break
        icon = _STATUS_ICON.get(result.status, "")
        print(f"\n  {icon} Result: {result.status} ({result.run_seconds}s)")
        if result.detail:
            print(f"  💬 Detail: {result.detail[:200]}")
        print(f"{separator}\n")
        writer.add(result)
        if args.stop_on_error and result.status in _FAILING:
            print("⛔ --stop-on-error: aborting remaining cases")
            break

    # Summary
    counts: dict[str, int] = {}
    for r in writer.results:
        counts[r.status] = counts.get(r.status, 0) + 1
    total = len(writer.results)
    failing = sum(counts.get(s, 0) for s in _FAILING)
    pass_count = counts.get(PASS, 0)
    pending_total = counts.get(PENDING_AI, 0)
    expected_count = counts.get(EXPECTED, 0)

    print("═" * 50)
    print(f"Summary: {total} run — " + "  ".join(f"{k}={v}" for k, v in sorted(counts.items())))
    print(f"📄 Report: {report_dir / 'report.md'}")
    print(f"🧾 JSON:   {report_dir / 'report.json'}")

    # Detect the empty-run trap: if the entire suite ran without a single PASS,
    # and everything was either PENDING_AI or EXPECTED, the suite is configured
    # wrong — either the cases are all unjudged vision-only, or every case
    # carries a known_limits that absolved a real failure. This is never a green
    # signal, so exit 1 even if _FAILING is empty.
    if total > 0 and pass_count == 0 and (pending_total + expected_count) == total:
        print(
            "⚠️  WARNING: Zero cases passed. All results are PENDING_AI or EXPECTED.\n"
            "    This usually means:\n"
            "      - all cases are ai_vision only and have not been judged, OR\n"
            "      - all cases hit known_limits that absolved real failures.\n"
            "    Treating this as a failure (exit 1)."
        )
        return 1

    if pending_total:
        print(f"🤖 {pending_total} item(s) awaiting AI judgement — see report.md")

    return 1 if failing else 0


if __name__ == "__main__":
    sys.exit(main())


def main_entry() -> None:
    """Console-script entry point (pyproject [project.scripts])."""
    sys.exit(main())
