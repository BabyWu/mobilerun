"""Data models and YAML parsing for mobilerun-testkit.

Depends on pyyaml (declared in pyproject.toml dependencies).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass
class VerifyItem:
    """One assertion inside ``verify:``.

    Exactly one of the three forms is active:
    - ``cmd`` + (``expect_contains`` | ``expect_regex``): run the command and
      match its stdout. ``expect_contains`` is OR semantics across the list.
    - ``cmd`` + ``save_to``: run the command and copy the file whose path is
      printed on stdout (e.g. ``mobilerun device screenshot``) into evidence/.
    - ``judge: ai_vision``: take a screenshot and hand judgement to the AI
      (see the skill). Runner records it as PENDING_AI.
    """

    cmd: str | None = None
    expect_contains: list[str] = field(default_factory=list)
    expect_regex: str | None = None
    save_to: str | None = None
    judge: str | None = None
    description: str = ""
    # Store part of this command's stdout under a name, for later ``${name}``
    # interpolation. Without it a case cannot feed a recorded artifact path
    # (e.g. the trajectory dir) into a subsequent command.
    capture: str | None = None
    # Which part of stdout to capture: "last_line" (default), "first_line",
    # "all", or "regex:<expr>" (group 1 if present, else group 0).
    capture_from: str = "last_line"


@dataclass
class RequireItem:
    """One machine-checkable precondition inside ``requires:``.

    Unlike ``preconditions`` (free text for humans), a failing ``requires``
    marks the case SKIPPED rather than ERROR, so an environment gap does not
    look like a product regression.
    """

    cmd: str
    expect_contains: list[str] = field(default_factory=list)
    expect_regex: str | None = None
    description: str = ""


@dataclass
class KnownLimit:
    """A documented limitation of the case or the environment.

    Only a ``pattern`` match downgrades FAIL/ERROR to EXPECTED. A bare string
    (or a mapping with only ``reason``) is documentation and never absolves a
    failure — otherwise any non-empty text would silently mask regressions.
    """

    pattern: str | None = None
    reason: str = ""

    def matches(self, haystack: str) -> bool:
        if not self.pattern:
            return False
        return re.search(self.pattern, haystack, re.IGNORECASE | re.MULTILINE) is not None

    def describe(self) -> str:
        return self.reason or (self.pattern or "")


@dataclass
class TestCase:
    """One regression case loaded from a YAML file."""

    id: str
    title: str
    priority: str = "smoke"
    preconditions: list[str] = field(default_factory=list)
    requires: list[RequireItem] = field(default_factory=list)
    setup: str = ""
    task: str | None = None
    run_flags: dict = field(default_factory=dict)
    verify: list[VerifyItem] = field(default_factory=list)
    timeout: int = 600
    # Run the case N times and report a pass rate. The agent under test is
    # probabilistic, so a single sample cannot distinguish a regression from
    # an unlucky run.
    repeat: int = 1
    pass_criteria: str = ""
    cleanup: str = ""
    known_limits: KnownLimit | None = None
    source_file: str = ""


@dataclass
class CaseResult:
    """Outcome of executing one case. Status is one of:
    PASS, FAIL, ERROR, PENDING_AI, EXPECTED (known limit hit), SKIPPED.
    """

    case: TestCase
    status: str = "SKIPPED"
    detail: str = ""
    run_exit_code: int | None = None
    run_seconds: float = 0.0
    run_timed_out: bool = False
    verify_results: list[dict] = field(default_factory=list)
    ai_judge_images: list[str] = field(default_factory=list)  # evidence paths
    # Populated when ``repeat > 1``: one status string per attempt, plus the
    # per-attempt detail, so a flaky case is visible as 3/5 rather than a
    # single arbitrary verdict.
    attempts: list[dict] = field(default_factory=list)

    def pass_rate(self) -> str:
        """"n/N" over attempts, or "" when the case ran once."""
        if len(self.attempts) <= 1:
            return ""
        good = sum(1 for a in self.attempts if a.get("status") in ("PASS", "EXPECTED"))
        return f"{good}/{len(self.attempts)}"


# ---------------------------------------------------------------------------
# Schema validation
# ---------------------------------------------------------------------------

_RUN_FLAG_KEYS = {
    # mobilerun run CLI flags we know how to map (booleans -> --flag/--no-flag)
    "provider": "--provider",
    "model": "--model",
    "steps": "--steps",
    "vision": "--vision",
    "vision_only": "--vision-only",
    "reasoning": "--reasoning",
    "stream": "--stream",
    "tracing": "--tracing",
    "debug": "--debug",
    "tcp": "--tcp",
    "ios": "--ios",
    "temperature": "--temperature",
    "base_url": "--base_url",
    "api_base": "--api_base",
    "save_trajectory": "--save-trajectory",
    "control_backend": "--control-backend",
    "device_id": "--device-id",
}

# Flags click declares as --x/--no-x pairs, so False maps to --no-x.
_BOOL_FLAGS = {"vision", "vision_only", "reasoning", "stream", "tracing", "debug", "tcp"}

# Flags click declares as is_flag=True (no --no-x counterpart): emit the flag
# only when truthy. `mobilerun run --ios` is the only one today.
_ON_OFF_FLAGS = {"ios"}


def validate_case(data: dict, source: str) -> TestCase:
    """Validate a parsed case dict into a TestCase. Raises ValueError with
    file context on schema problems."""
    if not isinstance(data, dict):
        raise ValueError(f"{source}: top level must be a mapping, got {type(data).__name__}")

    case_id = data.get("id")
    if not case_id or not isinstance(case_id, str):
        raise ValueError(f"{source}: missing required string field 'id'")

    title = data.get("title", case_id)
    task = data.get("task")
    verify_raw = data.get("verify") or []

    if task is None and not verify_raw:
        raise ValueError(
            f"{source}: case '{case_id}' has neither 'task' nor 'verify' — nothing to do"
        )

    verify: list[VerifyItem] = []
    for i, item in enumerate(verify_raw):
        if not isinstance(item, dict):
            raise ValueError(f"{source}: verify[{i}] must be a mapping")
        unknown_keys = set(item) - {
            "cmd", "expect_contains", "expect_regex", "save_to", "judge",
            "description", "capture", "capture_from",
        }
        if unknown_keys:
            raise ValueError(
                f"{source}: verify[{i}] has unknown keys {sorted(unknown_keys)}"
            )
        capture_from = item.get("capture_from", "last_line")
        if capture_from.startswith("regex:"):
            expr = capture_from[len("regex:"):]
            try:
                re.compile(expr)
            except re.error as e:
                raise ValueError(
                    f"{source}: verify[{i}] capture_from regex is invalid: {e}"
                ) from e
        elif capture_from not in ("last_line", "first_line", "all"):
            raise ValueError(
                f"{source}: verify[{i}] capture_from must be last_line / "
                f"first_line / all / regex:<expr>, got {capture_from!r}"
            )
        vi = VerifyItem(
            cmd=item.get("cmd"),
            expect_contains=list(item.get("expect_contains") or []),
            expect_regex=item.get("expect_regex"),
            save_to=item.get("save_to"),
            judge=item.get("judge"),
            description=item.get("description", ""),
            capture=item.get("capture"),
            capture_from=capture_from,
        )
        if vi.judge == "ai_vision":
            verify.append(vi)
            continue
        if not vi.cmd:
            raise ValueError(f"{source}: verify[{i}] needs 'cmd' (or judge: ai_vision)")
        if not (vi.expect_contains or vi.expect_regex or vi.save_to or vi.capture):
            raise ValueError(
                f"{source}: verify[{i}] needs one of expect_contains / "
                f"expect_regex / save_to / capture"
            )
        verify.append(vi)

    requires: list[RequireItem] = []
    for i, item in enumerate(data.get("requires") or []):
        if not isinstance(item, dict):
            raise ValueError(f"{source}: requires[{i}] must be a mapping")
        unknown_keys = set(item) - {"cmd", "expect_contains", "expect_regex", "description"}
        if unknown_keys:
            raise ValueError(
                f"{source}: requires[{i}] has unknown keys {sorted(unknown_keys)}"
            )
        cmd = item.get("cmd")
        if not cmd:
            raise ValueError(f"{source}: requires[{i}] needs 'cmd'")
        if not (item.get("expect_contains") or item.get("expect_regex")):
            raise ValueError(
                f"{source}: requires[{i}] needs expect_contains or expect_regex"
            )
        requires.append(
            RequireItem(
                cmd=cmd,
                expect_contains=list(item.get("expect_contains") or []),
                expect_regex=item.get("expect_regex"),
                description=item.get("description", ""),
            )
        )

    repeat = int(data.get("repeat") or 1)
    if repeat < 1:
        raise ValueError(f"{source}: case '{case_id}' repeat must be >= 1, got {repeat}")

    unknown_flags = set(data.get("run_flags") or {}) - set(_RUN_FLAG_KEYS)
    if unknown_flags:
        raise ValueError(
            f"{source}: unknown run_flags {sorted(unknown_flags)}; "
            f"supported: {sorted(_RUN_FLAG_KEYS)}"
        )

    known_limits = _parse_known_limits(data.get("known_limits"), case_id, source)

    return TestCase(
        id=case_id,
        title=title,
        priority=data.get("priority", "smoke"),
        preconditions=[str(p) for p in data.get("preconditions") or []],
        requires=requires,
        setup=data.get("setup") or "",
        task=task,
        run_flags=dict(data.get("run_flags") or {}),
        verify=verify,
        timeout=int(data.get("timeout") or 600),
        repeat=repeat,
        pass_criteria=data.get("pass_criteria", ""),
        cleanup=data.get("cleanup") or "",
        known_limits=known_limits,
        source_file=source,
    )


def _parse_known_limits(raw, case_id: str, source: str) -> KnownLimit | None:
    """Parse ``known_limits`` into a KnownLimit, or None when absent.

    Accepts a mapping with ``pattern`` (regex that must match the failure text
    before a FAIL/ERROR is downgraded to EXPECTED) and/or ``reason``. A bare
    string is treated as documentation only — it does NOT absolve failures.
    """
    if raw is None:
        return None
    if isinstance(raw, str):
        text = raw.strip()
        # Placeholders like "无" / "none" mean the author meant "no known limits".
        if not text or text.lower() in ("无", "none", "n/a", "-"):
            return None
        return KnownLimit(pattern=None, reason=text)
    if isinstance(raw, dict):
        unknown = set(raw) - {"pattern", "reason"}
        if unknown:
            raise ValueError(
                f"{source}: case '{case_id}' known_limits has unknown keys "
                f"{sorted(unknown)}; supported: ['pattern', 'reason']"
            )
        pattern = raw.get("pattern")
        if pattern is not None:
            if not isinstance(pattern, str) or not pattern.strip():
                raise ValueError(
                    f"{source}: case '{case_id}' known_limits.pattern must be a "
                    f"non-empty string"
                )
            try:
                re.compile(pattern)
            except re.error as e:
                raise ValueError(
                    f"{source}: case '{case_id}' known_limits.pattern is not a "
                    f"valid regex: {e}"
                ) from e
        return KnownLimit(pattern=pattern, reason=str(raw.get("reason") or ""))
    raise ValueError(
        f"{source}: case '{case_id}' known_limits must be a string or a mapping, "
        f"got {type(raw).__name__}"
    )


# ---------------------------------------------------------------------------
# YAML loading
# ---------------------------------------------------------------------------


def parse_yaml_text(text: str, source: str = "<inline>") -> object:
    """Parse YAML via pyyaml."""
    try:
        return yaml.safe_load(text)
    except yaml.YAMLError as e:
        raise ValueError(f"{source}: {e}") from e


def load_cases(cases_dir: Path, suite: str) -> list[TestCase]:
    """Load all case YAMLs from ``cases_dir/<suite>/`` in filename order."""
    suite_dir = cases_dir / suite
    if not suite_dir.is_dir():
        raise FileNotFoundError(f"suite directory not found: {suite_dir}")
    cases: list[TestCase] = []
    for path in sorted(suite_dir.glob("*.yaml")):
        text = path.read_text(encoding="utf-8")
        data = parse_yaml_text(text, source=str(path))
        cases.append(validate_case(data, source=str(path)))
    if not cases:
        raise ValueError(f"no case files found in {suite_dir}")
    return cases
