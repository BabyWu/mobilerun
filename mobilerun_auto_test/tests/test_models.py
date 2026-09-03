"""
Unit tests for data models.
"""

import pytest
from mobilerun_autotest.models import (
    TestCase,
    VerifyItem,
    RequireItem,
    KnownLimit,
    CaseResult,
)


def test_verify_item_basic():
    item = VerifyItem(
        cmd="mobilerun device ui",
        expect_contains=["Settings"],
        description="Check settings",
    )
    assert item.cmd == "mobilerun device ui"
    assert "Settings" in item.expect_contains


def test_verify_item_capture_from_validation():
    # Valid values
    VerifyItem(cmd="echo test", expect_contains=["test"], capture_from="last_line")
    VerifyItem(cmd="echo test", expect_contains=["test"], capture_from="first_line")
    VerifyItem(cmd="echo test", expect_contains=["test"], capture_from="all")
    VerifyItem(cmd="echo test", expect_contains=["test"], capture_from="regex:.*")

    # Invalid value
    with pytest.raises(ValueError):
        VerifyItem(
            cmd="echo test", expect_contains=["test"], capture_from="invalid_mode"
        )


def test_require_item_basic():
    item = RequireItem(
        cmd="mobilerun ping",
        expect_contains=["ok"],
        description="Device online",
    )
    assert item.cmd == "mobilerun ping"


def test_known_limit_matches():
    limit = KnownLimit(pattern="timeout|error", reason="Known issue")
    assert limit.matches("connection timeout occurred")
    assert limit.matches("error happened")
    assert not limit.matches("success")


def test_known_limit_no_pattern_never_matches():
    limit = KnownLimit(reason="Just documentation")
    assert not limit.matches("anything")


def test_known_limit_pattern_validation():
    # Valid regex
    KnownLimit(pattern="test.*pattern")

    # Invalid regex
    with pytest.raises(ValueError):
        KnownLimit(pattern="[invalid(regex")


def test_test_case_minimal():
    case = TestCase(
        id="test_01",
        title="Test Title",
        steps=["Step 1"],
    )
    assert case.id == "test_01"
    assert case.priority == "smoke"  # default
    assert case.timeout == 600  # default


def test_test_case_with_test_data():
    case = TestCase(
        id="test_02",
        title="With Data",
        task="Do something",
        test_data={"username": "test", "count": 5},
    )
    assert case.test_data["username"] == "test"
    assert case.test_data["count"] == 5


def test_test_case_repeat_validation():
    # Valid
    TestCase(id="t", title="T", task="x", repeat=1)
    TestCase(id="t", title="T", task="x", repeat=5)

    # Invalid
    with pytest.raises(ValueError):
        TestCase(id="t", title="T", task="x", repeat=0)


def test_test_case_extra_fields_forbidden():
    with pytest.raises(ValueError):
        TestCase(
            id="t",
            title="T",
            task="x",
            unknown_field="value",  # Should be rejected
        )


def test_case_result_pass_rate():
    case = TestCase(id="t", title="T", task="x")

    # Single run - no pass rate
    result = CaseResult(case=case, status="PASS")
    assert result.pass_rate() == ""

    # Multiple attempts
    result.attempts = [
        {"status": "PASS"},
        {"status": "FAIL"},
        {"status": "PASS"},
    ]
    assert result.pass_rate() == "2/3"

    # All pass
    result.attempts = [
        {"status": "PASS"},
        {"status": "PASS"},
    ]
    assert result.pass_rate() == "2/2"


def test_case_result_defaults():
    case = TestCase(id="t", title="T", task="x")
    result = CaseResult(case=case)

    assert result.status == "SKIPPED"
    assert result.detail == ""
    assert result.run_seconds == 0.0
    assert result.agent_steps == 0
    assert result.verify_results == []
    assert result.ai_judge_images == []


def test_case_result_with_v3_fields():
    case = TestCase(id="t", title="T", task="x")
    result = CaseResult(
        case=case,
        status="PASS",
        agent_steps=8,
        trajectory_path="/path/to/trajectory",
        compiled_goal="Test goal",
    )

    assert result.agent_steps == 8
    assert result.trajectory_path == "/path/to/trajectory"
    assert result.compiled_goal == "Test goal"
