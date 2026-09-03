"""
Unit tests for test case loader and YAML validation.
"""

import textwrap
import pytest
from mobilerun_autotest.loader import parse_case


def test_minimal_case_with_task():
    data = {"id": "t1", "title": "Minimal", "task": "Open app"}
    case = parse_case(data, source="test")
    assert case.id == "t1"
    assert case.task == "Open app"
    assert case.title == "Minimal"


def test_minimal_case_with_steps():
    data = {
        "id": "t2",
        "title": "Steps",
        "steps": ["Open app", "Tap button"],
    }
    case = parse_case(data, source="test")
    assert case.steps == ["Open app", "Tap button"]


def test_minimal_case_with_verify_only():
    data = {
        "id": "t3",
        "title": "Verify only",
        "verify": [{"cmd": "mobilerun ping", "expect_contains": ["ok"]}],
    }
    case = parse_case(data, source="test")
    assert len(case.verify) == 1


def test_requires_id():
    with pytest.raises(ValueError, match="id"):
        parse_case({"title": "No ID"}, source="test")


def test_requires_task_or_steps_or_verify():
    with pytest.raises(ValueError, match="nothing to do"):
        parse_case({"id": "empty", "title": "Empty"}, source="test")


def test_unknown_run_flags_rejected():
    with pytest.raises(ValueError, match="unknown run_flags"):
        parse_case(
            {
                "id": "t",
                "title": "T",
                "task": "x",
                "run_flags": {"nonexistent_flag": True},
            },
            source="test",
        )


def test_test_data_parsed():
    data = {
        "id": "t4",
        "title": "Data",
        "steps": ["Send message"],
        "test_data": {"message": "Hello", "count": 3},
    }
    case = parse_case(data, source="test")
    assert case.test_data["message"] == "Hello"
    assert case.test_data["count"] == 3


def test_known_limits_string_doc_only():
    data = {
        "id": "t5",
        "title": "Limits",
        "task": "x",
        "known_limits": "This feature is not stable yet",
    }
    case = parse_case(data, source="test")
    assert case.known_limits.reason == "This feature is not stable yet"
    assert case.known_limits.pattern is None


def test_known_limits_with_pattern():
    data = {
        "id": "t6",
        "title": "Limits",
        "task": "x",
        "known_limits": {"pattern": "timeout|failed", "reason": "Known instability"},
    }
    case = parse_case(data, source="test")
    assert case.known_limits.pattern == "timeout|failed"
    assert case.known_limits.matches("connection timeout occurred")


def test_known_limits_none_value():
    data = {"id": "t7", "title": "T", "task": "x", "known_limits": "无"}
    case = parse_case(data, source="test")
    assert case.known_limits is None


def test_repeat_validation():
    with pytest.raises(ValueError):
        parse_case(
            {"id": "t8", "title": "T", "task": "x", "repeat": 0},
            source="test",
        )


def test_verify_ai_vision_item():
    data = {
        "id": "t9",
        "title": "Vision",
        "verify": [{"judge": "ai_vision", "description": "Screen looks correct"}],
    }
    case = parse_case(data, source="test")
    assert case.verify[0].judge == "ai_vision"


def test_verify_capture_from_validation():
    with pytest.raises(ValueError):
        parse_case(
            {
                "id": "t10",
                "title": "T",
                "verify": [
                    {
                        "cmd": "echo test",
                        "expect_contains": ["test"],
                        "capture_from": "invalid_mode",
                    }
                ],
            },
            source="test",
        )


def test_full_case():
    data = {
        "id": "full_case",
        "title": "Full Example",
        "priority": "smoke",
        "preconditions": ["Device connected"],
        "requires": [
            {
                "cmd": "mobilerun ping",
                "expect_contains": ["ok"],
                "description": "Device online",
            }
        ],
        "setup": "mobilerun device press home",
        "test_data": {"app": "Settings"},
        "steps": ["Open Settings"],
        "run_flags": {"vision": True, "steps": 10},
        "verify": [
            {
                "cmd": "mobilerun device ui",
                "expect_regex": "settings",
                "description": "Settings open",
            }
        ],
        "timeout": 300,
        "pass_criteria": "Settings is open",
        "cleanup": "mobilerun device press home",
        "known_limits": {"pattern": "timeout", "reason": "Sometimes slow"},
    }
    case = parse_case(data, source="test")
    assert case.id == "full_case"
    assert len(case.requires) == 1
    assert len(case.verify) == 1
    assert case.run_flags["vision"] is True
    assert case.timeout == 300
    assert case.known_limits.matches("connection timeout")
