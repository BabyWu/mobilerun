"""
MobileRun AutoTest v3.0 - AI-powered mobile automation testing framework.

Core components:
- TestCaseCompiler: Convert YAML steps to Agent goals
- SharedResources: Reuse driver/LLM across test cases
- TestRunner: Execute test suites with batch optimization
- CaseExecutor: Single test case execution logic
- bootstrap: Detect/install the mobilerun dependency (public environment)
"""

__version__ = "3.0.0"

from mobilerun_autotest.bootstrap import (
    MobilerunNotInstalled,
    MobilerunStatus,
    detect_mobilerun,
    ensure_mobilerun,
    install_mobilerun,
)
from mobilerun_autotest.compiler import TestCaseCompiler
from mobilerun_autotest.executor import CaseExecutor
from mobilerun_autotest.models import CaseResult, TestCase, VerifyItem
from mobilerun_autotest.runner import TestRunner
from mobilerun_autotest.shared import SharedResources
from mobilerun_autotest.loader import load_cases

__all__ = [
    "TestCaseCompiler",
    "SharedResources",
    "TestRunner",
    "CaseExecutor",
    "CaseResult",
    "TestCase",
    "VerifyItem",
    "load_cases",
    "MobilerunNotInstalled",
    "MobilerunStatus",
    "detect_mobilerun",
    "ensure_mobilerun",
    "install_mobilerun",
]
