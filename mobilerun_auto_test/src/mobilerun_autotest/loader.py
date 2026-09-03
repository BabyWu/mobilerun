"""
YAML test case loader with validation.
"""

from pathlib import Path

import yaml

from mobilerun_autotest.models import (
    KnownLimit,
    RequireItem,
    TestCase,
    VerifyItem,
)


# Supported run_flags keys mapping to CLI flags
RUN_FLAG_KEYS = {
    "provider",
    "model",
    "steps",
    "vision",
    "vision_only",
    "reasoning",
    "stream",
    "tracing",
    "debug",
    "tcp",
    "ios",
    "temperature",
    "base_url",
    "api_base",
    "save_trajectory",
    "control_backend",
    "device_id",
}


def load_cases(cases_dir: Path | str, suite: str) -> list[TestCase]:
    """
    Load all test case YAMLs from cases_dir/<suite>/ in filename order.

    Args:
        cases_dir: Directory containing suite folders
        suite: Suite name (smoke, full, etc.)

    Returns:
        List of validated TestCase objects

    Raises:
        FileNotFoundError: If suite directory doesn't exist
        ValueError: If YAML parsing or validation fails
    """
    cases_dir = Path(cases_dir)
    suite_dir = cases_dir / suite

    if not suite_dir.is_dir():
        raise FileNotFoundError(f"Suite directory not found: {suite_dir}")

    cases: list[TestCase] = []
    yaml_files = sorted(suite_dir.glob("*.yaml")) + sorted(suite_dir.glob("*.yml"))

    if not yaml_files:
        raise ValueError(f"No YAML files found in {suite_dir}")

    for path in yaml_files:
        try:
            text = path.read_text(encoding="utf-8")
            data = yaml.safe_load(text)

            if not isinstance(data, dict):
                raise ValueError(f"{path}: top level must be a mapping")

            case = parse_case(data, source=str(path))
            cases.append(case)

        except yaml.YAMLError as e:
            raise ValueError(f"{path}: YAML parse error: {e}") from e
        except Exception as e:
            raise ValueError(f"{path}: {e}") from e

    return cases


def parse_case(data: dict, source: str) -> TestCase:
    """
    Parse and validate a single test case from dict.

    Args:
        data: Parsed YAML dict
        source: Source file path for error messages

    Returns:
        Validated TestCase instance

    Raises:
        ValueError: If validation fails
    """
    # Required fields
    case_id = data.get("id")
    if not case_id or not isinstance(case_id, str):
        raise ValueError(f"{source}: missing required string field 'id'")

    title = data.get("title", case_id)

    # At least one of task/steps/verify must exist
    task = data.get("task")
    steps = data.get("steps", [])
    verify_raw = data.get("verify", [])

    if not task and not steps and not verify_raw:
        raise ValueError(
            f"{source}: case '{case_id}' has neither 'task', 'steps', nor 'verify' "
            "— nothing to do"
        )

    # Parse verify items
    verify = []
    for i, item in enumerate(verify_raw):
        if not isinstance(item, dict):
            raise ValueError(f"{source}: verify[{i}] must be a mapping")

        try:
            vi = VerifyItem(**item)
            verify.append(vi)
        except Exception as e:
            raise ValueError(f"{source}: verify[{i}] validation failed: {e}") from e

    # Parse requires
    requires = []
    for i, item in enumerate(data.get("requires", [])):
        if not isinstance(item, dict):
            raise ValueError(f"{source}: requires[{i}] must be a mapping")

        try:
            req = RequireItem(**item)
            requires.append(req)
        except Exception as e:
            raise ValueError(f"{source}: requires[{i}] validation failed: {e}") from e

    # Validate run_flags
    run_flags = data.get("run_flags", {})
    unknown_flags = set(run_flags.keys()) - RUN_FLAG_KEYS
    if unknown_flags:
        raise ValueError(
            f"{source}: unknown run_flags {sorted(unknown_flags)}; "
            f"supported: {sorted(RUN_FLAG_KEYS)}"
        )

    # Parse known_limits
    known_limits = None
    if "known_limits" in data:
        raw = data["known_limits"]
        if isinstance(raw, str):
            text = raw.strip()
            if text and text.lower() not in ("无", "none", "n/a", "-"):
                known_limits = KnownLimit(reason=text)
        elif isinstance(raw, dict):
            try:
                known_limits = KnownLimit(**raw)
            except Exception as e:
                raise ValueError(
                    f"{source}: known_limits validation failed: {e}"
                ) from e
        else:
            raise ValueError(
                f"{source}: known_limits must be string or mapping, "
                f"got {type(raw).__name__}"
            )

    # Construct TestCase
    try:
        case = TestCase(
            id=case_id,
            title=title,
            priority=data.get("priority", "smoke"),
            preconditions=[str(p) for p in data.get("preconditions", [])],
            requires=requires,
            setup=data.get("setup", ""),
            task=task,
            steps=[str(s) for s in steps],
            test_data=dict(data.get("test_data", {})),
            run_flags=dict(run_flags),
            verify=verify,
            timeout=int(data.get("timeout", 600)),
            repeat=int(data.get("repeat", 1)),
            pass_criteria=data.get("pass_criteria", ""),
            cleanup=data.get("cleanup", ""),
            known_limits=known_limits,
            source_file=source,
        )
        return case

    except Exception as e:
        raise ValueError(f"{source}: TestCase validation failed: {e}") from e
