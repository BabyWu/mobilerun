"""
Unit tests for TestCaseCompiler.
"""

import pytest
from mobilerun_autotest.compiler import TestCaseCompiler
from mobilerun_autotest.models import TestCase


def make_case(**kwargs) -> TestCase:
    defaults = dict(id="test_001", title="Test Title")
    defaults.update(kwargs)
    return TestCase(**defaults)


def test_compile_steps_only():
    compiler = TestCaseCompiler()
    case = make_case(
        steps=["Open app", "Navigate to home", "Tap button"],
    )
    goal = compiler.compile_goal(case)
    assert "Open app" in goal
    assert "Navigate to home" in goal
    assert "Tap button" in goal
    assert "1." in goal
    assert "2." in goal
    assert "3." in goal


def test_compile_task_only():
    compiler = TestCaseCompiler()
    case = make_case(task="Open Settings and navigate to WiFi")
    goal = compiler.compile_goal(case)
    assert "Open Settings and navigate to WiFi" in goal


def test_compile_steps_with_test_data():
    compiler = TestCaseCompiler()
    case = make_case(
        steps=["Login", "Send message"],
        test_data={"username": "testuser", "message": "Hello"},
    )
    goal = compiler.compile_goal(case)
    assert "username" in goal
    assert "testuser" in goal
    assert "message" in goal
    assert "Hello" in goal


def test_compile_steps_and_task_combined():
    compiler = TestCaseCompiler()
    case = make_case(
        task="Additional context here",
        steps=["Step 1", "Step 2"],
    )
    goal = compiler.compile_goal(case)
    assert "Step 1" in goal
    assert "Additional context here" in goal


def test_compile_includes_stop_instruction():
    compiler = TestCaseCompiler()
    case = make_case(steps=["Do something"])
    goal = compiler.compile_goal(case)
    # Must include instruction to stop (don't self-evaluate)
    assert "停止" in goal or "stop" in goal.lower()


def test_compile_with_pass_criteria():
    compiler = TestCaseCompiler()
    case = make_case(
        steps=["Open app"],
        pass_criteria="App opens within 2 seconds",
    )
    goal = compiler.compile_goal(case)
    assert "App opens within 2 seconds" in goal


def test_should_enable_app_card_false_by_default():
    compiler = TestCaseCompiler()
    case = make_case(steps=["Open app"])
    assert compiler.should_enable_app_card(case) is False


def test_should_enable_app_card_true_with_reasoning():
    compiler = TestCaseCompiler()
    case = make_case(steps=["Open app"], run_flags={"reasoning": True})
    assert compiler.should_enable_app_card(case) is True


def test_format_for_debug_contains_all_parts():
    compiler = TestCaseCompiler()
    case = make_case(
        id="test_debug",
        title="Debug Test",
        steps=["Step A", "Step B"],
        test_data={"key": "value"},
        run_flags={"vision": True, "steps": 15},
    )
    output = compiler.format_for_debug(case)
    assert "test_debug" in output
    assert "Debug Test" in output
    assert "Step A" in output
    assert "key: value" in output
    assert "vision: True" in output


def test_english_goal_compilation():
    compiler = TestCaseCompiler()
    case = make_case(
        steps=["Open Settings", "Go to WiFi"],
        test_data={"ssid": "TestNetwork"},
    )
    goal = compiler.compile_goal_en(case)
    assert "Open Settings" in goal
    assert "ssid" in goal
    assert "TestNetwork" in goal
    assert "Stop immediately" in goal or "stop" in goal.lower()
