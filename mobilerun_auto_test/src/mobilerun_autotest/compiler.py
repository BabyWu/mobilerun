"""
Test Case Compiler: Convert YAML steps to natural language Agent goals.

Pure Python string manipulation (no LLM), following principles from 22.docx:
- Steps describe intent, not coordinates
- All steps merged into single goal
- test_data injected into context
"""

from mobilerun_autotest.models import TestCase


class TestCaseCompiler:
    """
    Compiles TestCase YAML into natural language goal string for MobileAgent.

    Design principles:
    1. Steps are natural language ("进入直播间"), not coordinates ("click(100, 200)")
    2. All steps merged into one goal (not N separate agent.run() calls)
    3. test_data injected as context variables
    4. Final instruction: "完成后停止，不要自行判断是否成功" (don't self-evaluate)
    """

    def compile_goal(self, case: TestCase) -> str:
        """
        Compile TestCase into natural language goal string.

        Priority:
        1. If steps exist, use steps (preferred)
        2. If only task exists, use task
        3. If both exist, combine them

        Args:
            case: TestCase to compile

        Returns:
            Natural language goal string for MobileAgent
        """
        parts = []

        # Header
        if case.title:
            parts.append(f"# 测试任务: {case.title}")
            parts.append("")

        parts.append("请完成以下测试任务：")
        parts.append("")

        # Inject test_data as context variables
        if case.test_data:
            parts.append("**背景信息：**")
            for key, value in case.test_data.items():
                # Format value for readability
                if isinstance(value, str):
                    formatted_value = f'"{value}"'
                else:
                    formatted_value = str(value)
                parts.append(f"- {key} = {formatted_value}")
            parts.append("")

        # Inject steps or task
        if case.steps:
            parts.append("**操作步骤：**")
            for i, step in enumerate(case.steps, 1):
                parts.append(f"{i}. {step}")
            parts.append("")

            # If task also exists, append as additional context
            if case.task:
                parts.append(f"**补充说明：** {case.task}")
                parts.append("")

        elif case.task:
            # Fallback to legacy task field
            parts.append(f"**任务：** {case.task}")
            parts.append("")

        # Add pass criteria if specified (helps Agent understand intent)
        if case.pass_criteria:
            parts.append(f"**预期结果：** {case.pass_criteria}")
            parts.append("")

        # Final instruction: don't self-evaluate
        parts.append("**重要提示：**")
        parts.append("- 完成上述步骤后立即停止")
        parts.append("- 不要自行判断任务是否成功")
        parts.append("- 最终验证由独立的断言程序完成")

        return "\n".join(parts)

    def compile_goal_en(self, case: TestCase) -> str:
        """
        English version of compile_goal (for international projects).

        Args:
            case: TestCase to compile

        Returns:
            Natural language goal string in English
        """
        parts = []

        if case.title:
            parts.append(f"# Test Task: {case.title}")
            parts.append("")

        parts.append("Please complete the following test task:")
        parts.append("")

        if case.test_data:
            parts.append("**Context Variables:**")
            for key, value in case.test_data.items():
                if isinstance(value, str):
                    formatted_value = f'"{value}"'
                else:
                    formatted_value = str(value)
                parts.append(f"- {key} = {formatted_value}")
            parts.append("")

        if case.steps:
            parts.append("**Steps:**")
            for i, step in enumerate(case.steps, 1):
                parts.append(f"{i}. {step}")
            parts.append("")

            if case.task:
                parts.append(f"**Additional Context:** {case.task}")
                parts.append("")

        elif case.task:
            parts.append(f"**Task:** {case.task}")
            parts.append("")

        if case.pass_criteria:
            parts.append(f"**Expected Result:** {case.pass_criteria}")
            parts.append("")

        parts.append("**Important:**")
        parts.append("- Stop immediately after completing the steps")
        parts.append("- Do not evaluate success yourself")
        parts.append("- Final verification will be done by deterministic assertions")

        return "\n".join(parts)

    def should_enable_app_card(self, case: TestCase) -> bool:
        """
        Check if App Card should be enabled for this case.

        App Card only works with reasoning=true (Manager mode).

        Args:
            case: TestCase to check

        Returns:
            True if reasoning mode is enabled
        """
        return case.run_flags.get("reasoning", False) is True

    def format_for_debug(self, case: TestCase) -> str:
        """
        Format test case and compiled goal for debugging.

        Args:
            case: TestCase to format

        Returns:
            Formatted string for --show-goals output
        """
        lines = []
        lines.append("=" * 70)
        lines.append(f"Test Case: {case.id}")
        lines.append(f"Title: {case.title}")
        lines.append("=" * 70)

        if case.steps:
            lines.append("\nOriginal Steps:")
            for i, step in enumerate(case.steps, 1):
                lines.append(f"  {i}. {step}")

        if case.test_data:
            lines.append("\nTest Data:")
            for k, v in case.test_data.items():
                lines.append(f"  {k}: {v}")

        if case.run_flags:
            lines.append("\nRun Flags:")
            for k, v in case.run_flags.items():
                lines.append(f"  {k}: {v}")

        lines.append("\n" + "-" * 70)
        lines.append("Compiled Goal:")
        lines.append("-" * 70)
        lines.append(self.compile_goal(case))
        lines.append("=" * 70)
        lines.append("")

        return "\n".join(lines)
